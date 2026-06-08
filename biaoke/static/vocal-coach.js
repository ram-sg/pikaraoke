(() => {
  "use strict";

  const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  const HISTORY_SECONDS = 10;
  const MAX_CENTS_FOR_SCORE = 90;
  const GOOD_CENTS = 35;

  const RANGE_OFFSETS = {
    low: -12,
    mid: 0,
    high: 12,
  };

  const PRESETS = {
    free: [],
    sustain: [
      { midi: 60, duration: 3.2 },
      { midi: 62, duration: 3.2 },
      { midi: 64, duration: 3.2 },
      { midi: 65, duration: 3.2 },
      { midi: 67, duration: 3.2 },
      { midi: 65, duration: 3.2 },
      { midi: 64, duration: 3.2 },
      { midi: 62, duration: 3.2 },
    ],
    scale: [
      { midi: 60, duration: 1.2 },
      { midi: 62, duration: 1.2 },
      { midi: 64, duration: 1.2 },
      { midi: 65, duration: 1.2 },
      { midi: 67, duration: 1.2 },
      { midi: 69, duration: 1.2 },
      { midi: 71, duration: 1.2 },
      { midi: 72, duration: 1.6 },
      { midi: 71, duration: 1.2 },
      { midi: 69, duration: 1.2 },
      { midi: 67, duration: 1.2 },
      { midi: 65, duration: 1.2 },
      { midi: 64, duration: 1.2 },
      { midi: 62, duration: 1.2 },
      { midi: 60, duration: 1.6 },
    ],
    intervals: [
      { midi: 60, duration: 1.6 },
      { midi: 64, duration: 1.6 },
      { midi: 60, duration: 1.6 },
      { midi: 67, duration: 1.6 },
      { midi: 60, duration: 1.6 },
      { midi: 69, duration: 1.6 },
      { midi: 67, duration: 1.6 },
      { midi: 64, duration: 1.6 },
    ],
  };

  const state = {
    running: false,
    stream: null,
    audioContext: null,
    analyser: null,
    source: null,
    timeData: null,
    rafId: null,
    exerciseStartedAt: 0,
    lastSegmentKey: null,
    segmentStartedAt: 0,
    segmentFirstHitMs: null,
    history: [],
    recentErrors: [],
    metrics: emptyMetrics(),
  };

  const els = {};

  function emptyMetrics() {
    return {
      targetFrames: 0,
      voicedFrames: 0,
      accurateFrames: 0,
      timingScores: [],
    };
  }

  function bindElements() {
    [
      "coach-canvas",
      "coach-preset",
      "coach-range",
      "coach-start",
      "coach-reset",
      "coach-fullscreen",
      "coach-note",
      "coach-frequency",
      "coach-cents",
      "coach-target-note",
      "coach-target-state",
      "coach-target-progress-fill",
      "coach-status",
      "coach-accuracy",
      "coach-accuracy-fill",
      "coach-timing",
      "coach-timing-fill",
      "coach-stability",
      "coach-stability-fill",
      "coach-coverage",
      "coach-coverage-fill",
    ].forEach((id) => {
      els[id] = document.getElementById(id);
    });
    els.canvas = els["coach-canvas"];
    els.ctx = els.canvas.getContext("2d");
  }

  function midiToFrequency(midi) {
    return 440 * Math.pow(2, (midi - 69) / 12);
  }

  function frequencyToMidi(frequency) {
    return 69 + 12 * Math.log2(frequency / 440);
  }

  function noteName(midi) {
    const rounded = Math.round(midi);
    const name = NOTE_NAMES[((rounded % 12) + 12) % 12];
    const octave = Math.floor(rounded / 12) - 1;
    return `${name}${octave}`;
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function setStatus(text, tone = "") {
    els["coach-status"].textContent = text;
    els["coach-status"].className = `coach-status${tone ? ` ${tone}` : ""}`;
  }

  function setMetric(name, value) {
    const text = els[`coach-${name}`];
    const fill = els[`coach-${name}-fill`];
    if (value === null || Number.isNaN(value)) {
      text.textContent = "--";
      fill.style.width = "0%";
      fill.style.backgroundColor = "#12c79c";
      return;
    }

    const percent = clamp(Math.round(value), 0, 100);
    text.textContent = `${percent}`;
    fill.style.width = `${percent}%`;
    fill.style.backgroundColor =
      percent >= 78 ? "#12c79c" : percent >= 55 ? "#edb049" : "#cf4d43";
  }

  function resetSession() {
    state.exerciseStartedAt = performance.now();
    state.lastSegmentKey = null;
    state.segmentStartedAt = state.exerciseStartedAt;
    state.segmentFirstHitMs = null;
    state.history = [];
    state.recentErrors = [];
    state.metrics = emptyMetrics();
    updateMetricsDisplay(null);
  }

  function selectedSequence() {
    const preset = els["coach-preset"].value;
    if (preset === "free") return [];
    const offset = RANGE_OFFSETS[els["coach-range"].value] || 0;
    return PRESETS[preset].map((note) => ({
      midi: note.midi + offset,
      duration: note.duration,
    }));
  }

  function currentTarget(now) {
    const sequence = selectedSequence();
    if (sequence.length === 0) return null;

    const totalSeconds = sequence.reduce((sum, note) => sum + note.duration, 0);
    const elapsedSeconds = Math.max(0, (now - state.exerciseStartedAt) / 1000);
    const cycle = Math.floor(elapsedSeconds / totalSeconds);
    let position = elapsedSeconds % totalSeconds;

    for (let index = 0; index < sequence.length; index++) {
      const note = sequence[index];
      if (position <= note.duration || index === sequence.length - 1) {
        return {
          midi: note.midi,
          index,
          cycle,
          duration: note.duration,
          progress: clamp(position / note.duration, 0, 1),
          totalSeconds,
        };
      }
      position -= note.duration;
    }
    return null;
  }

  function parabolicInterpolation(values, index) {
    if (index <= 0 || index >= values.length - 1) return index;
    const left = values[index - 1];
    const center = values[index];
    const right = values[index + 1];
    const denominator = 2 * (2 * center - left - right);
    if (Math.abs(denominator) < 1e-9) return index;
    return index + (right - left) / denominator;
  }

  function detectPitch(buffer, sampleRate) {
    let rms = 0;
    let mean = 0;
    for (let i = 0; i < buffer.length; i++) mean += buffer[i];
    mean /= buffer.length;

    for (let i = 0; i < buffer.length; i++) {
      const sample = buffer[i] - mean;
      rms += sample * sample;
    }
    rms = Math.sqrt(rms / buffer.length);
    if (rms < 0.012) return { voiced: false, rms };

    const minFrequency = 60;
    const maxFrequency = 1050;
    const tauMin = Math.floor(sampleRate / maxFrequency);
    const tauMax = Math.min(Math.floor(sampleRate / minFrequency), Math.floor(buffer.length / 2));
    const difference = new Float32Array(tauMax + 1);

    for (let tau = tauMin; tau <= tauMax; tau++) {
      let sum = 0;
      const limit = buffer.length - tau;
      for (let i = 0; i < limit; i++) {
        const delta = buffer[i] - buffer[i + tau];
        sum += delta * delta;
      }
      difference[tau] = sum;
    }

    const normalized = new Float32Array(tauMax + 1);
    let runningSum = 0;
    let bestTau = -1;
    let bestValue = Infinity;

    for (let tau = tauMin; tau <= tauMax; tau++) {
      runningSum += difference[tau];
      normalized[tau] = runningSum > 0 ? (difference[tau] * tau) / runningSum : 1;
      if (normalized[tau] < bestValue) {
        bestValue = normalized[tau];
        bestTau = tau;
      }
    }

    const threshold = 0.14;
    let tau = -1;
    for (let candidate = tauMin; candidate <= tauMax; candidate++) {
      if (normalized[candidate] < threshold) {
        while (
          candidate + 1 <= tauMax &&
          normalized[candidate + 1] < normalized[candidate]
        ) {
          candidate++;
        }
        tau = candidate;
        break;
      }
    }

    if (tau < 0 && bestValue < 0.28) tau = bestTau;
    if (tau < 0) return { voiced: false, rms };

    const preciseTau = parabolicInterpolation(normalized, tau);
    const frequency = sampleRate / preciseTau;
    if (!Number.isFinite(frequency) || frequency < minFrequency || frequency > maxFrequency) {
      return { voiced: false, rms };
    }

    return {
      voiced: true,
      frequency,
      confidence: clamp(1 - normalized[tau], 0, 1),
      rms,
    };
  }

  function updateSegment(target, active, centsError, now) {
    if (!target) return;
    const key = `${target.cycle}:${target.index}`;
    if (key !== state.lastSegmentKey) {
      if (state.lastSegmentKey !== null) {
        const firstHit = state.segmentFirstHitMs;
        const score =
          firstHit === null
            ? 0
            : clamp(1 - Math.max(0, firstHit - 180) / 720, 0, 1);
        state.metrics.timingScores.push(score);
        if (state.metrics.timingScores.length > 40) state.metrics.timingScores.shift();
      }
      state.lastSegmentKey = key;
      state.segmentStartedAt = now;
      state.segmentFirstHitMs = null;
    }

    if (active && Math.abs(centsError) <= 70 && state.segmentFirstHitMs === null) {
      state.segmentFirstHitMs = now - state.segmentStartedAt;
    }
  }

  function updateMetricsDisplay(target) {
    if (!target) {
      setMetric("accuracy", null);
      setMetric("timing", null);
      setMetric("coverage", null);
    } else {
      const accuracy =
        state.metrics.voicedFrames > 0
          ? (100 * state.metrics.accurateFrames) / state.metrics.voicedFrames
          : 0;
      const coverage =
        state.metrics.targetFrames > 0
          ? (100 * state.metrics.voicedFrames) / state.metrics.targetFrames
          : 0;
      const timing =
        state.metrics.timingScores.length > 0
          ? 100 *
            state.metrics.timingScores.reduce((sum, score) => sum + score, 0) /
            state.metrics.timingScores.length
          : null;

      setMetric("accuracy", accuracy);
      setMetric("timing", timing);
      setMetric("coverage", coverage);
    }

    if (state.recentErrors.length < 4) {
      setMetric("stability", null);
      return;
    }
    const mean =
      state.recentErrors.reduce((sum, value) => sum + value, 0) / state.recentErrors.length;
    const variance =
      state.recentErrors.reduce((sum, value) => sum + Math.pow(value - mean, 2), 0) /
      state.recentErrors.length;
    const stdDev = Math.sqrt(variance);
    setMetric("stability", 100 * clamp(1 - stdDev / 70, 0, 1));
  }

  function updateReadout(result, pitchMidi, target, centsError) {
    if (!result.voiced) {
      els["coach-note"].textContent = "--";
      els["coach-frequency"].textContent = "-- Hz";
      els["coach-cents"].textContent = "--";
      setStatus(state.running ? "Listening" : "Mic idle", state.running ? "" : "");
    } else {
      els["coach-note"].textContent = noteName(pitchMidi);
      els["coach-frequency"].textContent = `${Math.round(result.frequency)} Hz`;
      const sign = centsError > 0 ? "+" : "";
      els["coach-cents"].textContent = `${sign}${Math.round(centsError)}c`;
      setStatus(result.confidence > 0.82 ? "Locked" : "Listening", result.confidence > 0.82 ? "is-hot" : "");
    }

    if (target) {
      els["coach-target-note"].textContent = noteName(target.midi);
      els["coach-target-state"].textContent = `${Math.round(target.progress * 100)}%`;
      els["coach-target-progress-fill"].style.width = `${Math.round(target.progress * 100)}%`;
    } else {
      els["coach-target-note"].textContent = "--";
      els["coach-target-state"].textContent = "Free pitch";
      els["coach-target-progress-fill"].style.width = "0%";
    }
  }

  function updateMetrics(result, pitchMidi, target, centsError, now) {
    const active = result.voiced && result.confidence > 0.62;
    if (target) {
      state.metrics.targetFrames++;
      if (active) {
        state.metrics.voicedFrames++;
        if (Math.abs(centsError) <= GOOD_CENTS) state.metrics.accurateFrames++;
      }
      updateSegment(target, active, centsError, now);
    }

    if (active) {
      state.recentErrors.push(centsError);
      if (state.recentErrors.length > 75) state.recentErrors.shift();
    }

    updateMetricsDisplay(target);
  }

  function visibleMidiRange(target, pitchMidi) {
    const sequence = selectedSequence();
    let minMidi = 48;
    let maxMidi = 72;

    if (sequence.length > 0) {
      minMidi = Math.min(...sequence.map((note) => note.midi)) - 3;
      maxMidi = Math.max(...sequence.map((note) => note.midi)) + 3;
    }

    if (target) {
      minMidi = Math.min(minMidi, target.midi - 5);
      maxMidi = Math.max(maxMidi, target.midi + 5);
    }

    if (Number.isFinite(pitchMidi)) {
      minMidi = Math.min(minMidi, Math.floor(pitchMidi) - 3);
      maxMidi = Math.max(maxMidi, Math.ceil(pitchMidi) + 3);
    }

    return { minMidi, maxMidi };
  }

  function resizeCanvas() {
    const rect = els.canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.floor(rect.width * dpr));
    const height = Math.max(1, Math.floor(rect.height * dpr));
    if (els.canvas.width !== width || els.canvas.height !== height) {
      els.canvas.width = width;
      els.canvas.height = height;
    }
    els.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function draw(now, target, pitchMidi) {
    resizeCanvas();
    const ctx = els.ctx;
    const rect = els.canvas.getBoundingClientRect();
    const width = rect.width;
    const height = rect.height;
    const range = visibleMidiRange(target, pitchMidi);
    const span = Math.max(1, range.maxMidi - range.minMidi);
    const yForMidi = (midi) => height - ((midi - range.minMidi) / span) * height;

    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "rgba(3, 6, 10, 0.88)";
    ctx.fillRect(0, 0, width, height);

    for (let i = 0; i <= HISTORY_SECONDS; i++) {
      const x = (i / HISTORY_SECONDS) * width;
      ctx.strokeStyle = i % 2 === 0 ? "rgba(255,255,255,0.08)" : "rgba(255,255,255,0.035)";
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();
    }

    for (let midi = Math.floor(range.minMidi); midi <= Math.ceil(range.maxMidi); midi++) {
      const y = yForMidi(midi);
      const natural = !noteName(midi).includes("#");
      ctx.strokeStyle = natural ? "rgba(255,255,255,0.12)" : "rgba(255,255,255,0.045)";
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();

      if (natural) {
        ctx.fillStyle = "rgba(246,243,234,0.62)";
        ctx.font = "12px sans-serif";
        ctx.fillText(noteName(midi), 12, y - 4);
      }
    }

    if (target) {
      const targetY = yForMidi(target.midi);
      const bandHeight = Math.max(18, height / span);
      ctx.fillStyle = "rgba(18, 199, 156, 0.2)";
      ctx.fillRect(0, targetY - bandHeight / 2, width, bandHeight);
      ctx.strokeStyle = "rgba(18, 199, 156, 0.86)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(0, targetY);
      ctx.lineTo(width, targetY);
      ctx.stroke();
      ctx.lineWidth = 1;
    }

    const cutoff = now - HISTORY_SECONDS * 1000;
    state.history = state.history.filter((point) => point.time >= cutoff);

    let started = false;
    ctx.strokeStyle = "#edb049";
    ctx.lineWidth = 3;
    ctx.beginPath();
    for (const point of state.history) {
      const x = width - ((now - point.time) / 1000 / HISTORY_SECONDS) * width;
      const y = yForMidi(point.midi);
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    }
    if (started) ctx.stroke();
    ctx.lineWidth = 1;

    if (Number.isFinite(pitchMidi)) {
      const y = yForMidi(pitchMidi);
      ctx.fillStyle = "#f6f3ea";
      ctx.beginPath();
      ctx.arc(width - 28, y, 8, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function tick(now) {
    if (!state.running) return;
    state.analyser.getFloatTimeDomainData(state.timeData);
    const result = detectPitch(state.timeData, state.audioContext.sampleRate);
    const target = currentTarget(now);

    let pitchMidi = null;
    let centsError = 0;
    if (result.voiced) {
      pitchMidi = frequencyToMidi(result.frequency);
      if (target) {
        centsError = 1200 * Math.log2(result.frequency / midiToFrequency(target.midi));
      } else {
        centsError = (pitchMidi - Math.round(pitchMidi)) * 100;
      }
      state.history.push({ time: now, midi: pitchMidi, confidence: result.confidence });
    }

    updateReadout(result, pitchMidi, target, centsError);
    updateMetrics(result, pitchMidi, target, centsError, now);
    draw(now, target, pitchMidi);
    state.rafId = requestAnimationFrame(tick);
  }

  async function startCoach() {
    if (state.running) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus("Unsupported", "is-danger");
      return;
    }

    setStatus("Opening mic", "is-warning");
    try {
      state.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: false,
          channelCount: { ideal: 1 },
          sampleRate: { ideal: 48000 },
        },
        video: false,
      });

      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      try {
        state.audioContext = new AudioContextClass({ latencyHint: "interactive" });
      } catch (_e) {
        state.audioContext = new AudioContextClass();
      }
      state.source = state.audioContext.createMediaStreamSource(state.stream);
      state.analyser = state.audioContext.createAnalyser();
      state.analyser.fftSize = 4096;
      state.analyser.smoothingTimeConstant = 0;
      state.timeData = new Float32Array(state.analyser.fftSize);
      state.source.connect(state.analyser);

      state.running = true;
      els["coach-start"].textContent = "Stop";
      resetSession();
      setStatus("Listening");
      state.rafId = requestAnimationFrame(tick);
    } catch (error) {
      console.log("Vocal coach microphone error", error);
      setStatus("Mic blocked", "is-danger");
      stopCoach();
    }
  }

  function stopCoach() {
    state.running = false;
    if (state.rafId) {
      cancelAnimationFrame(state.rafId);
      state.rafId = null;
    }
    if (state.source) {
      try {
        state.source.disconnect();
      } catch (_e) {}
      state.source = null;
    }
    if (state.stream) {
      state.stream.getTracks().forEach((track) => track.stop());
      state.stream = null;
    }
    if (state.audioContext && state.audioContext.state !== "closed") {
      state.audioContext.close().catch(() => {});
    }
    state.audioContext = null;
    state.analyser = null;
    state.timeData = null;
    els["coach-start"].textContent = "Start";
    setStatus("Mic idle");
    updateReadout({ voiced: false }, null, currentTarget(performance.now()), 0);
    draw(performance.now(), currentTarget(performance.now()), null);
  }

  function toggleFullscreen() {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen?.();
    } else {
      document.exitFullscreen?.();
    }
  }

  function setupEvents() {
    els["coach-start"].addEventListener("click", () => {
      state.running ? stopCoach() : startCoach();
    });
    els["coach-reset"].addEventListener("click", () => {
      resetSession();
      draw(performance.now(), currentTarget(performance.now()), null);
    });
    els["coach-fullscreen"].addEventListener("click", toggleFullscreen);
    els["coach-preset"].addEventListener("change", () => {
      resetSession();
      draw(performance.now(), currentTarget(performance.now()), null);
    });
    els["coach-range"].addEventListener("change", () => {
      resetSession();
      draw(performance.now(), currentTarget(performance.now()), null);
    });
    window.addEventListener("resize", () => draw(performance.now(), currentTarget(performance.now()), null));
    window.addEventListener("beforeunload", stopCoach);
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindElements();
    setupEvents();
    resetSession();
    updateReadout({ voiced: false }, null, null, 0);
    draw(performance.now(), null, null);
  });
})();

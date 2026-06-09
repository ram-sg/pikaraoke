(() => {
  "use strict";

  const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  const HISTORY_SECONDS = 10;
  const SONG_LOOKAHEAD_SECONDS = 2.5;
  const MAX_CENTS_FOR_SCORE = 90;
  const GOOD_CENTS = 35;
  const PLAYBACK_DRIFT_SECONDS = 2;
  const NOW_PLAYING_POLL_MS = 2000;
  const PLAYBACK_START_TIMEOUT_MS = 10000;
  const LYRICS_OFFSET_STEP_SECONDS = 0.5;
  const MAX_LYRICS_OFFSET_SECONDS = 120;
  const CONFIG = window.BiaokeCoachConfig || {};

  const TEXT = {
    idle: "Microfone parado",
    listening: "Ouvindo",
    locked: "Travado",
    unsupported: "Não suportado",
    openingMic: "Abrindo microfone",
    micBlocked: "Microfone bloqueado",
    start: "Iniciar",
    stop: "Parar",
    freePitch: "Afinação livre",
    loadingGuide: "Gerando guia",
    guideReady: "Guia pronto",
    noSong: "Sem música tocando",
    noGuide: "Sem guia",
    noTarget: "Sem nota alvo agora",
    guideError: "Erro no guia",
    idleSong: "Aguardando música",
    noLyrics: "Letra ainda não gerada",
    loadingLyrics: "Carregando letra",
    lyricsReady: "Letra sincronizada",
    lyricsError: "Erro ao carregar letra",
    lyricsMismatch: "Letra de outra versão",
    melodyShort: "Melodia incompleta",
  };

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
    songGuide: null,
    songGuideLoading: false,
    songSync: null,
    songSyncTimer: null,
    nowPlaying: {},
    currentVideoUrl: null,
    currentSubtitleUrl: null,
    hlsInstance: null,
    socket: null,
    isMaster: false,
    playbackConfirmed: false,
    playbackRafId: null,
    playbackPositionTimer: null,
    nowPlayingPollTimer: null,
    lyrics: [],
    lyricsOffsetSeconds: 0,
    activeLyricIndex: -1,
    lastLoadedSubtitleUrl: null,
    currentLyricsKey: null,
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
      "coach-video",
      "coach-video-source",
      "coach-video-container",
      "coach-idle",
      "coach-idle-title",
      "coach-idle-subtitle",
      "coach-now-playing-song",
      "coach-now-playing-singer",
      "coach-current",
      "coach-duration",
      "coach-song-progress-fill",
      "coach-up-next",
      "coach-up-next-song",
      "coach-up-next-singer",
      "coach-autoplay",
      "coach-autoplay-button",
      "coach-lyrics-status",
      "coach-lyrics-current",
      "coach-lyrics-next",
      "coach-lyrics-earlier",
      "coach-lyrics-later",
      "coach-lyrics-reset-sync",
      "coach-lyrics-offset",
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

  function selectedMode() {
    return els["coach-preset"].value;
  }

  function selectedSequence() {
    const preset = selectedMode();
    if (preset === "free" || preset === "song") return [];
    const offset = RANGE_OFFSETS[els["coach-range"].value] || 0;
    return PRESETS[preset].map((note) => ({
      midi: note.midi + offset,
      duration: note.duration,
    }));
  }

  function formatClock(seconds) {
    const safeSeconds = Math.max(0, Math.floor(seconds || 0));
    const minutes = Math.floor(safeSeconds / 60);
    const remainder = String(safeSeconds % 60).padStart(2, "0");
    return `${minutes}:${remainder}`;
  }

  function formatDuration(seconds) {
    return formatClock(seconds);
  }

  function isMediaPlaying(media) {
    return Boolean(
      media &&
      media.currentTime > 0 &&
      !media.paused &&
      !media.ended &&
      media.readyState > 2
    );
  }

  function getVideoPlayer() {
    return els["coach-video"];
  }

  function setText(id, text) {
    const el = els[id];
    if (el) el.textContent = text;
  }

  function showAutoplayPrompt(show) {
    if (!els["coach-autoplay"]) return;
    els["coach-autoplay"].hidden = !show;
  }

  function clearVideo() {
    const video = getVideoPlayer();
    if (state.hlsInstance) {
      state.hlsInstance.destroy();
      state.hlsInstance = null;
    }
    state.currentVideoUrl = null;
    video.pause();
    video.removeAttribute("src");
    els["coach-video-source"].setAttribute("src", "");
    video.load();
    els["coach-video-container"].classList.remove("is-playing");
  }

  function songPlaybackTime(now) {
    const video = getVideoPlayer();
    if (
      state.currentVideoUrl &&
      video &&
      Number.isFinite(video.currentTime) &&
      (video.currentTime > 0 || !video.paused)
    ) {
      return Math.max(0, video.currentTime);
    }
    if (!state.songSync) return 0;
    if (state.songSync.paused) return state.songSync.position;
    return Math.max(0, state.songSync.position + (now - state.songSync.receivedAt) / 1000);
  }

  function currentSongTarget(now) {
    if (!state.songGuide || !Array.isArray(state.songGuide.notes)) return null;
    const songTime = songPlaybackTime(now);
    const notes = state.songGuide.notes;
    for (let index = 0; index < notes.length; index++) {
      const note = notes[index];
      if (songTime >= note.start && songTime <= note.end) {
        const duration = Math.max(0.05, note.end - note.start);
        return {
          midi: note.midi,
          index,
          cycle: "song",
          duration,
          progress: clamp((songTime - note.start) / duration, 0, 1),
          source: "song",
          songTime,
        };
      }
    }
    return null;
  }

  function currentTarget(now) {
    if (selectedMode() === "song") return currentSongTarget(now);

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

  async function readJsonResponse(response) {
    const text = await response.text();
    return text ? JSON.parse(text) : {};
  }

  function parseAssTime(value) {
    const match = String(value || "").trim().match(/^(\d+):(\d{1,2}):(\d{1,2})(?:[.](\d{1,2}))?$/);
    if (!match) return null;
    const hours = Number(match[1]);
    const minutes = Number(match[2]);
    const seconds = Number(match[3]);
    const centiseconds = Number(String(match[4] || "0").padEnd(2, "0").slice(0, 2));
    return hours * 3600 + minutes * 60 + seconds + centiseconds / 100;
  }

  function splitAssFields(value, expectedFields) {
    const fields = String(value || "").split(",");
    if (fields.length <= expectedFields) return fields.map((field) => field.trim());
    return [
      ...fields.slice(0, expectedFields - 1).map((field) => field.trim()),
      fields.slice(expectedFields - 1).join(",").trim(),
    ];
  }

  function stripAssTags(text) {
    return String(text || "")
      .replace(/\\[Nn]/g, " ")
      .replace(/\{[^}]*\}/g, "")
      .replace(/\\h/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function tokenizeLineText(text, start, end) {
    const cleanText = stripAssTags(text);
    if (!cleanText) return [];
    const pieces = cleanText.match(/\S+\s*/g) || [cleanText];
    const totalWeight = pieces.reduce((sum, piece) => sum + Math.max(1, piece.trim().length), 0);
    const duration = Math.max(0.05, end - start);
    let cursor = start;
    return pieces.map((piece, index) => {
      const isLast = index === pieces.length - 1;
      const weight = Math.max(1, piece.trim().length);
      const segmentDuration = isLast ? end - cursor : duration * (weight / totalWeight);
      const segment = {
        text: piece,
        start: cursor,
        end: Math.min(end, cursor + Math.max(0.03, segmentDuration)),
      };
      cursor = segment.end;
      return segment;
    });
  }

  function parseKaraokeSegments(text, start, end) {
    const tags = [];
    const regex = /\{[^}]*\\k[fo]?(\d+)[^}]*\}/gi;
    let match;
    while ((match = regex.exec(text)) !== null) {
      tags.push({
        index: match.index,
        endIndex: match.index + match[0].length,
        duration: Number(match[1]) / 100,
      });
    }
    if (tags.length === 0) return tokenizeLineText(text, start, end);

    const rawSegments = tags
      .map((tag, index) => {
        const next = tags[index + 1];
        return {
          text: stripAssTags(text.slice(tag.endIndex, next ? next.index : text.length)),
          duration: Math.max(0.01, tag.duration),
        };
      })
      .filter((segment) => segment.text);

    if (rawSegments.length === 0) return tokenizeLineText(text, start, end);

    const lineDuration = Math.max(0.05, end - start);
    const taggedDuration = rawSegments.reduce((sum, segment) => sum + segment.duration, 0);
    const scale = taggedDuration > 0 ? lineDuration / taggedDuration : 1;
    let cursor = start;
    return rawSegments.map((segment, index) => {
      const isLast = index === rawSegments.length - 1;
      const duration = isLast ? end - cursor : segment.duration * scale;
      const timedSegment = {
        text: `${segment.text}${index < rawSegments.length - 1 ? " " : ""}`,
        start: cursor,
        end: Math.min(end, cursor + Math.max(0.03, duration)),
      };
      cursor = timedSegment.end;
      return timedSegment;
    });
  }

  function parseAssLyrics(content) {
    const lines = String(content || "").split(/\r?\n/);
    let inEvents = false;
    let format = [
      "Layer",
      "Start",
      "End",
      "Style",
      "Name",
      "MarginL",
      "MarginR",
      "MarginV",
      "Effect",
      "Text",
    ];
    const lyrics = [];

    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line || line.startsWith(";")) continue;
      const section = line.match(/^\[(.+)]$/);
      if (section) {
        inEvents = section[1].toLowerCase() === "events";
        continue;
      }
      if (!inEvents) continue;

      if (line.toLowerCase().startsWith("format:")) {
        format = line.slice(line.indexOf(":") + 1).split(",").map((field) => field.trim());
        continue;
      }
      if (!line.toLowerCase().startsWith("dialogue:")) continue;

      const fields = splitAssFields(line.slice(line.indexOf(":") + 1), format.length);
      const event = {};
      format.forEach((field, index) => {
        event[field] = fields[index] || "";
      });

      const start = parseAssTime(event.Start);
      const end = parseAssTime(event.End);
      if (start === null || end === null || end <= start) continue;

      const text = event.Text || "";
      const plain = stripAssTags(text);
      if (!plain) continue;

      lyrics.push({
        start,
        end,
        text: plain,
        segments: parseKaraokeSegments(text, start, end),
      });
    }

    return lyrics.sort((a, b) => a.start - b.start);
  }

  function renderLyricLine(container, line, time) {
    container.replaceChildren();
    if (!line) return;
    const segments = line.segments?.length ? line.segments : tokenizeLineText(line.text, line.start, line.end);
    for (const segment of segments) {
      const token = document.createElement("span");
      token.className = "coach-lyric-token";
      token.textContent = segment.text;
      if (time >= segment.end) {
        token.classList.add("is-done");
      } else if (time >= segment.start && time < segment.end) {
        const progress = clamp((time - segment.start) / Math.max(0.03, segment.end - segment.start), 0, 1);
        token.classList.add("is-active");
        token.style.setProperty("--token-progress", `${Math.round(progress * 100)}%`);
      }
      container.appendChild(token);
    }
  }

  function setLyricsStatus(text, tone = "") {
    const status = els["coach-lyrics-status"];
    status.textContent = text;
    status.className = `coach-lyrics-status${tone ? ` ${tone}` : ""}`;
  }

  function setLyricsOffsetDisplay() {
    const value = Number(state.lyricsOffsetSeconds || 0);
    const sign = value > 0 ? "+" : "";
    setText("coach-lyrics-offset", `${sign}${value.toFixed(1)}s`);
  }

  async function persistLyricsOffset() {
    if (!CONFIG.lyricsOffsetUrl || !state.nowPlaying.now_playing) return;
    try {
      const response = await fetch(CONFIG.lyricsOffsetUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ offset_seconds: state.lyricsOffsetSeconds }),
      });
      if (!response.ok) return;
      const payload = await readJsonResponse(response);
      state.lyricsOffsetSeconds = Number(payload.lyrics_offset_seconds || 0);
      setLyricsOffsetDisplay();
    } catch (error) {
      console.log("Could not persist lyrics offset", error);
    }
  }

  function adjustLyricsOffset(deltaSeconds) {
    state.lyricsOffsetSeconds = clamp(
      Number(state.lyricsOffsetSeconds || 0) + deltaSeconds,
      -MAX_LYRICS_OFFSET_SECONDS,
      MAX_LYRICS_OFFSET_SECONDS
    );
    state.lyricsOffsetSeconds = Math.round(state.lyricsOffsetSeconds * 10) / 10;
    setLyricsOffsetDisplay();
    updateLyrics(getVideoPlayer().currentTime || 0);
    persistLyricsOffset();
  }

  async function loadLyrics(subtitleUrl) {
    state.lyrics = [];
    state.activeLyricIndex = -1;
    state.currentSubtitleUrl = subtitleUrl || null;
    els["coach-lyrics-current"].replaceChildren();
    els["coach-lyrics-next"].textContent = "";

    if (CONFIG.lyricsUrl) {
      const loadedFromGuide = await loadLyricsGuide();
      if (loadedFromGuide || !subtitleUrl) return;
    }

    if (!subtitleUrl) {
      state.lastLoadedSubtitleUrl = null;
      setLyricsStatus(TEXT.noLyrics, "is-warning");
      return;
    }
    if (state.lastLoadedSubtitleUrl === subtitleUrl && state.lyrics.length > 0) return;

    state.lastLoadedSubtitleUrl = subtitleUrl;
    setLyricsStatus(TEXT.loadingLyrics, "is-warning");
    try {
      const response = await fetch(subtitleUrl, { cache: "no-store" });
      if (!response.ok) throw new Error(`Subtitle request failed: ${response.status}`);
      const content = await response.text();
      state.lyrics = parseAssLyrics(content);
      state.activeLyricIndex = -1;
      if (state.lyrics.length === 0) {
        setLyricsStatus(TEXT.noLyrics, "is-warning");
        return;
      }
      setLyricsStatus(TEXT.lyricsReady, "is-ready");
    } catch (error) {
      console.log("Could not load lyrics", error);
      state.lyrics = [];
      state.activeLyricIndex = -1;
      setLyricsStatus(TEXT.lyricsError, "is-danger");
    }
  }

  async function loadLyricsGuide() {
    setLyricsStatus(TEXT.loadingLyrics, "is-warning");
    try {
      const response = await fetch(CONFIG.lyricsUrl, { cache: "no-store" });
      if (!response.ok) return false;
      const guide = await readJsonResponse(response);
      state.lyricsOffsetSeconds = Number(guide.lyrics_offset_seconds || 0);
      setLyricsOffsetDisplay();
      const qualityMessages = Array.isArray(guide.quality_messages) ? guide.quality_messages : [];
      if (guide.status === "idle" && state.nowPlaying.now_playing) {
        state.currentLyricsKey = null;
        setLyricsStatus(TEXT.loadingLyrics, "is-warning");
        return true;
      }
      if (qualityMessages.includes("lyrics_duration_mismatch")) {
        state.lyrics = [];
        state.activeLyricIndex = -1;
        setLyricsStatus(TEXT.lyricsMismatch, "is-danger");
        return true;
      }
      if (guide.status !== "ready" || !Array.isArray(guide.lines) || guide.lines.length === 0) {
        state.lyrics = [];
        state.activeLyricIndex = -1;
        setLyricsStatus(guide.message || TEXT.noLyrics, guide.status === "error" ? "is-danger" : "is-warning");
        return true;
      }
      state.lyrics = guide.lines;
      state.activeLyricIndex = -1;
      setLyricsStatus(TEXT.lyricsReady, "is-ready");
      return true;
    } catch (error) {
      console.log("Could not load lyrics guide", error);
      return false;
    }
  }

  function updateLyrics(time) {
    if (!state.lyrics.length) return;
    const lyricTime = time - Number(state.lyricsOffsetSeconds || 0);
    const firstLine = state.lyrics[0];
    const lastLine = state.lyrics[state.lyrics.length - 1];
    let activeIndex = state.lyrics.findIndex((line) => lyricTime >= line.start && lyricTime <= line.end);
    if (activeIndex < 0) {
      if (firstLine && lyricTime < firstLine.start) {
        setLyricsStatus(TEXT.lyricsReady, "is-ready");
        renderLyricLine(els["coach-lyrics-current"], firstLine, firstLine.start);
        els["coach-lyrics-next"].textContent = state.lyrics[1]?.text || "";
        state.activeLyricIndex = 0;
        return;
      }
      if (lastLine && lyricTime > lastLine.end) {
        setLyricsStatus(TEXT.lyricsReady, "is-ready");
        renderLyricLine(els["coach-lyrics-current"], lastLine, lastLine.end);
        els["coach-lyrics-next"].textContent = "";
        state.activeLyricIndex = state.lyrics.length - 1;
        return;
      }
      activeIndex = state.lyrics.findIndex((line) => line.start > lyricTime);
      if (activeIndex >= 0) {
        setLyricsStatus(TEXT.lyricsReady, "is-ready");
        renderLyricLine(els["coach-lyrics-current"], state.lyrics[activeIndex], state.lyrics[activeIndex].start);
        els["coach-lyrics-next"].textContent = state.lyrics[activeIndex + 1]?.text || "";
        state.activeLyricIndex = activeIndex;
      }
      return;
    }

    const active = state.lyrics[activeIndex];
    setLyricsStatus(TEXT.lyricsReady, "is-ready");
    renderLyricLine(els["coach-lyrics-current"], active, lyricTime);
    els["coach-lyrics-next"].textContent = state.lyrics[activeIndex + 1]?.text || "";
    state.activeLyricIndex = activeIndex;
  }

  async function readNowPlaying() {
    const response = await fetch(CONFIG.nowPlayingUrl || "/now_playing", { cache: "no-store" });
    if (!response.ok) return {};
    return readJsonResponse(response);
  }

  function updateSongChrome(np) {
    if (np.now_playing) {
      setText("coach-now-playing-song", np.now_playing);
      setText("coach-now-playing-singer", np.now_playing_user || "--");
      setText("coach-idle-subtitle", "");
    } else {
      setText("coach-now-playing-song", "--");
      setText("coach-now-playing-singer", "--");
      setText("coach-idle-subtitle", TEXT.idleSong);
    }

    if (np.up_next) {
      els["coach-up-next"].classList.add("is-visible");
      setText("coach-up-next-song", np.up_next);
      setText("coach-up-next-singer", np.next_user || "--");
    } else {
      els["coach-up-next"].classList.remove("is-visible");
      setText("coach-up-next-song", "--");
      setText("coach-up-next-singer", "--");
    }

    const duration = Number(np.now_playing_duration || 0);
    setText("coach-duration", duration > 0 ? `/${formatDuration(duration)}` : "/00:00");
  }

  async function playCurrentVideo() {
    const video = getVideoPlayer();
    showAutoplayPrompt(false);
    try {
      await video.play();
      state.playbackConfirmed = true;
    } catch (error) {
      console.log("Video autoplay blocked", error);
      showAutoplayPrompt(true);
    }
  }

  async function loadVideoStream(streamUrl, position = 0) {
    const video = getVideoPlayer();
    if (!streamUrl) {
      clearVideo();
      return;
    }
    if (streamUrl === state.currentVideoUrl) {
      if (Number.isFinite(position) && Math.abs(video.currentTime - position) > PLAYBACK_DRIFT_SECONDS) {
        video.currentTime = position;
      }
      return;
    }

    clearVideo();
    state.currentVideoUrl = streamUrl;
    els["coach-video-container"].classList.add("is-playing");
    els["coach-video-source"].setAttribute("src", streamUrl);

    const isHls = streamUrl.endsWith(".m3u8");
    const canUseNativeHls = video.canPlayType("application/vnd.apple.mpegurl");
    if (isHls && window.Hls && !canUseNativeHls) {
      state.hlsInstance = new Hls({ startPosition: Math.max(0, Number(position || 0)) });
      state.hlsInstance.loadSource(streamUrl);
      state.hlsInstance.attachMedia(video);
    } else {
      video.src = streamUrl;
    }

    video.load();
    if (Number.isFinite(position) && position > 0) {
      video.currentTime = position;
    }
    await playCurrentVideo();

    window.setTimeout(() => {
      if (!isMediaPlaying(video) && !video.paused && state.currentVideoUrl === streamUrl) {
        endCurrentSong("failed to start");
      }
    }, PLAYBACK_START_TIMEOUT_MS);
  }

  async function handleNowPlayingUpdate(np) {
    state.nowPlaying = np || {};
    updateSongChrome(state.nowPlaying);

    if (!state.nowPlaying.now_playing) {
      clearVideo();
      state.songGuide = null;
      state.songSync = null;
      await loadLyrics(null);
      return;
    }

    const subtitleUrl = state.nowPlaying.now_playing_subtitle_url || null;
    const lyricsKey = `${state.nowPlaying.now_playing || ""}:${subtitleUrl || ""}`;
    if (lyricsKey !== state.currentLyricsKey) {
      state.currentLyricsKey = lyricsKey;
      await loadLyrics(subtitleUrl);
    }

    if (
      selectedMode() === "song" &&
      !state.songGuideLoading &&
      (!state.songGuide || state.songGuide.title !== state.nowPlaying.now_playing)
    ) {
      state.songGuide = null;
      state.songSync = null;
      loadSongGuide(true);
    }

    await loadVideoStream(
      state.nowPlaying.now_playing_url,
      Number(state.nowPlaying.now_playing_position || 0)
    );
  }

  async function loadInitialNowPlaying() {
    try {
      await handleNowPlayingUpdate(await readNowPlaying());
    } catch (error) {
      console.log("Could not load now playing", error);
    }
  }

  function shouldHandleNowPlayingUpdate(latest) {
    const current = state.nowPlaying || {};
    if ((current.now_playing || "") !== (latest.now_playing || "")) return true;
    if ((current.now_playing_url || "") !== (latest.now_playing_url || "")) return true;
    if ((current.now_playing_subtitle_url || "") !== (latest.now_playing_subtitle_url || "")) return true;
    if (Boolean(current.is_paused) !== Boolean(latest.is_paused)) return true;
    if (Number(current.now_playing_duration || 0) !== Number(latest.now_playing_duration || 0)) return true;
    if (latest.now_playing && state.lyrics.length === 0 && !state.currentLyricsKey) return true;
    return false;
  }

  async function pollNowPlaying() {
    try {
      const latest = await readNowPlaying();
      if (shouldHandleNowPlayingUpdate(latest)) {
        await handleNowPlayingUpdate(latest);
        return;
      }
      state.nowPlaying = latest || {};
      updateSongChrome(state.nowPlaying);
      if (state.songSync && state.nowPlaying.now_playing) {
        state.songSync = {
          position: Number(state.nowPlaying.now_playing_position || 0),
          paused: Boolean(state.nowPlaying.is_paused),
          receivedAt: performance.now(),
        };
      }
    } catch (error) {
      console.log("Could not poll now playing", error);
    }
  }

  function startNowPlayingPolling() {
    if (state.nowPlayingPollTimer) return;
    state.nowPlayingPollTimer = window.setInterval(pollNowPlaying, NOW_PLAYING_POLL_MS);
  }

  function endCurrentSong(reason) {
    const video = getVideoPlayer();
    video.pause();
    clearVideo();
    if (state.isMaster && state.socket) {
      state.socket.emit("end_song", reason);
    }
  }

  function updatePlaybackUi() {
    const video = getVideoPlayer();
    const duration = Number(state.nowPlaying.now_playing_duration || video.duration || 0);
    const current = Number.isFinite(video.currentTime) ? video.currentTime : 0;
    setText("coach-current", formatDuration(current));
    if (duration > 0) {
      setText("coach-duration", `/${formatDuration(duration)}`);
      els["coach-song-progress-fill"].style.width = `${clamp((current / duration) * 100, 0, 100)}%`;
    } else {
      els["coach-song-progress-fill"].style.width = "0%";
    }
    updateLyrics(current);
    state.playbackRafId = requestAnimationFrame(updatePlaybackUi);
  }

  function startPlaybackUiLoop() {
    if (state.playbackRafId) return;
    state.playbackRafId = requestAnimationFrame(updatePlaybackUi);
  }

  function startPositionReporting() {
    if (state.playbackPositionTimer) return;
    state.playbackPositionTimer = window.setInterval(() => {
      const video = getVideoPlayer();
      if (state.isMaster && state.socket && isMediaPlaying(video)) {
        state.socket.emit("playback_position", video.currentTime);
      }
    }, 1000);
  }

  function setupPlaybackSocket() {
    state.socket = window.socket || io();
    window.socket = state.socket;
    const registerCoach = () => {
      state.socket.emit("register_splash", {
        client_type: "coach",
        preferred_role: "master",
      });
    };
    state.socket.on("connect", () => {
      registerCoach();
    });
    if (state.socket.connected) {
      registerCoach();
    }
    state.socket.on("splash_role", (role) => {
      state.isMaster = role === "master";
    });
    state.socket.on("now_playing", handleNowPlayingUpdate);
    state.socket.on("playback_position", (position) => {
      const video = getVideoPlayer();
      if (!state.isMaster && isMediaPlaying(video)) {
        const serverPosition = Number(position || 0);
        if (Math.abs(video.currentTime - serverPosition) > PLAYBACK_DRIFT_SECONDS) {
          video.currentTime = serverPosition;
        }
      }
    });
    state.socket.on("pause", () => {
      getVideoPlayer().pause();
    });
    state.socket.on("play", () => {
      playCurrentVideo();
    });
    state.socket.on("skip", () => {
      clearVideo();
    });
    state.socket.on("restart", () => {
      const video = getVideoPlayer();
      video.currentTime = 0;
      playCurrentVideo();
    });
    state.socket.on("volume", (value) => {
      const video = getVideoPlayer();
      if (value === "up") {
        video.volume = Math.min(1, video.volume + 0.1);
      } else if (value === "down") {
        video.volume = Math.max(0, video.volume - 0.1);
      } else {
        video.volume = clamp(Number(value), 0, 1);
      }
    });
  }

  function setupVideoEvents() {
    const video = getVideoPlayer();
    video.addEventListener("play", () => {
      els["coach-video-container"].classList.add("is-playing");
      if (state.isMaster && state.socket) {
        window.setTimeout(() => state.socket.emit("start_song"), 1200);
      }
    });
    video.addEventListener("ended", () => {
      endCurrentSong("complete");
    });
    video.addEventListener("error", () => {
      if (state.currentVideoUrl) {
        endCurrentSong("error while playing");
      }
    });
    els["coach-autoplay-button"].addEventListener("click", () => {
      state.playbackConfirmed = true;
      playCurrentVideo();
    });
    window.addEventListener("beforeunload", () => {
      if (isMediaPlaying(video) && state.isMaster && state.socket) {
        state.socket.emit("end_song", "coach screen closed");
      }
    });
  }

  async function loadSongGuide(force = false) {
    if (selectedMode() !== "song") return null;
    if (state.songGuide && !force) return state.songGuide;
    if (state.songGuideLoading) return null;

    state.songGuideLoading = true;
    setStatus(TEXT.loadingGuide, "is-warning");
    try {
      const response = await fetch(CONFIG.melodyUrl || "/score/melody/current", {
        cache: "no-store",
      });
      const guide = await response.json();
      if (!response.ok || guide.status !== "ready" || !Array.isArray(guide.notes) || guide.notes.length === 0) {
        state.songGuide = null;
        state.songSync = null;
        setStatus(guide.message || TEXT.noGuide, guide.status === "idle" ? "" : "is-warning");
        return null;
      }

      state.songGuide = guide;
      state.songSync = {
        position: Number(guide.playback_position || 0),
        paused: Boolean(guide.is_paused),
        receivedAt: performance.now(),
      };
      const qualityMessages = Array.isArray(guide.quality_messages) ? guide.quality_messages : [];
      if (qualityMessages.includes("melody_ends_before_lyrics")) {
        setStatus(TEXT.melodyShort, "is-warning");
      } else {
        setStatus(TEXT.guideReady, "is-hot");
      }
      return guide;
    } catch (error) {
      console.log("Could not load song melody guide", error);
      state.songGuide = null;
      state.songSync = null;
      setStatus(TEXT.guideError, "is-danger");
      return null;
    } finally {
      state.songGuideLoading = false;
    }
  }

  async function syncSongPosition() {
    if (selectedMode() !== "song" || !state.songGuide) return;
    try {
      const response = await fetch(CONFIG.nowPlayingUrl || "/now_playing", { cache: "no-store" });
      if (!response.ok) return;
      const data = await readJsonResponse(response);
      if (!data.now_playing) {
        state.songGuide = null;
        state.songSync = null;
        setStatus(TEXT.noSong, "is-warning");
        return;
      }
      if (state.songGuide.title && data.now_playing !== state.songGuide.title) {
        state.songGuide = null;
        state.songSync = null;
        await loadSongGuide(true);
        return;
      }
      state.songSync = {
        position: Number(data.now_playing_position || 0),
        paused: Boolean(data.is_paused),
        receivedAt: performance.now(),
      };
    } catch (error) {
      console.log("Could not sync song position", error);
    }
  }

  function startSongSync() {
    if (state.songSyncTimer || selectedMode() !== "song") return;
    state.songSyncTimer = setInterval(syncSongPosition, 1000);
  }

  function stopSongSync() {
    if (!state.songSyncTimer) return;
    clearInterval(state.songSyncTimer);
    state.songSyncTimer = null;
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
    if (!target && state.metrics.targetFrames === 0) {
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
      if (state.songGuideLoading) {
        setStatus(TEXT.loadingGuide, "is-warning");
      } else {
        setStatus(state.running ? TEXT.listening : TEXT.idle, state.running ? "" : "");
      }
    } else {
      els["coach-note"].textContent = noteName(pitchMidi);
      els["coach-frequency"].textContent = `${Math.round(result.frequency)} Hz`;
      const sign = centsError > 0 ? "+" : "";
      els["coach-cents"].textContent = `${sign}${Math.round(centsError)}c`;
      setStatus(result.confidence > 0.82 ? TEXT.locked : TEXT.listening, result.confidence > 0.82 ? "is-hot" : "");
    }

    if (target) {
      els["coach-target-note"].textContent = noteName(target.midi);
      if (target.source === "song") {
        els["coach-target-state"].textContent = `Música ${formatClock(target.songTime || 0)}`;
      } else {
        els["coach-target-state"].textContent = `${Math.round(target.progress * 100)}%`;
      }
      els["coach-target-progress-fill"].style.width = `${Math.round(target.progress * 100)}%`;
    } else {
      els["coach-target-note"].textContent = "--";
      if (selectedMode() === "song") {
        els["coach-target-state"].textContent = state.songGuide ? TEXT.noTarget : TEXT.noGuide;
      } else {
        els["coach-target-state"].textContent = TEXT.freePitch;
      }
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

    if (selectedMode() === "song" && state.songGuide?.notes?.length) {
      minMidi = Math.min(...state.songGuide.notes.map((note) => note.midi)) - 3;
      maxMidi = Math.max(...state.songGuide.notes.map((note) => note.midi)) + 3;
    }

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

  function drawSongGuide(ctx, width, height, yForMidi, now) {
    if (selectedMode() !== "song" || !state.songGuide?.notes?.length || !state.songSync) return;
    const songTime = songPlaybackTime(now);
    const anchorX = width - 28;
    const pixelsPerSecond = width / HISTORY_SECONDS;
    const minTime = songTime - HISTORY_SECONDS;
    const maxTime = songTime + SONG_LOOKAHEAD_SECONDS;

    for (const note of state.songGuide.notes) {
      if (note.end < minTime || note.start > maxTime) continue;
      const x1 = anchorX + (note.start - songTime) * pixelsPerSecond;
      const x2 = anchorX + (note.end - songTime) * pixelsPerSecond;
      const y = yForMidi(note.midi);
      const w = Math.max(4, x2 - x1);
      const h = 16;
      const isCurrent = songTime >= note.start && songTime <= note.end;
      ctx.fillStyle = isCurrent ? "rgba(18, 199, 156, 0.82)" : "rgba(155, 230, 214, 0.34)";
      ctx.fillRect(Math.max(-20, x1), y - h / 2, Math.min(width + 40, w), h);
      ctx.strokeStyle = isCurrent ? "rgba(246, 243, 234, 0.86)" : "rgba(155, 230, 214, 0.58)";
      ctx.strokeRect(Math.max(-20, x1), y - h / 2, Math.min(width + 40, w), h);
    }

    ctx.strokeStyle = "rgba(246, 243, 234, 0.76)";
    ctx.beginPath();
    ctx.moveTo(anchorX, 0);
    ctx.lineTo(anchorX, height);
    ctx.stroke();
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

    drawSongGuide(ctx, width, height, yForMidi, now);

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
      setStatus(TEXT.unsupported, "is-danger");
      return;
    }

    if (selectedMode() === "song") {
      await loadSongGuide();
      startSongSync();
    }

    setStatus(TEXT.openingMic, "is-warning");
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
      els["coach-start"].textContent = TEXT.stop;
      resetSession();
      if (selectedMode() === "song") startSongSync();
      setStatus(TEXT.listening);
      state.rafId = requestAnimationFrame(tick);
    } catch (error) {
      console.log("Vocal coach microphone error", error);
      setStatus(TEXT.micBlocked, "is-danger");
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
    stopSongSync();
    els["coach-start"].textContent = TEXT.start;
    setStatus(TEXT.idle);
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
      if (selectedMode() === "song") {
        syncSongPosition();
      }
      draw(performance.now(), currentTarget(performance.now()), null);
    });
    els["coach-fullscreen"].addEventListener("click", toggleFullscreen);
    els["coach-lyrics-earlier"].addEventListener("click", () => {
      adjustLyricsOffset(-LYRICS_OFFSET_STEP_SECONDS);
    });
    els["coach-lyrics-later"].addEventListener("click", () => {
      adjustLyricsOffset(LYRICS_OFFSET_STEP_SECONDS);
    });
    els["coach-lyrics-reset-sync"].addEventListener("click", () => {
      state.lyricsOffsetSeconds = 0;
      setLyricsOffsetDisplay();
      updateLyrics(getVideoPlayer().currentTime || 0);
      persistLyricsOffset();
    });
    els["coach-preset"].addEventListener("change", async () => {
      resetSession();
      stopSongSync();
      if (selectedMode() === "song") {
        state.songGuide = null;
        await loadSongGuide(true);
        startSongSync();
      }
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
    setupVideoEvents();
    setupPlaybackSocket();
    startPlaybackUiLoop();
    startPositionReporting();
    resetSession();
    setLyricsOffsetDisplay();
    updateReadout({ voiced: false }, null, null, 0);
    draw(performance.now(), null, null);
    loadInitialNowPlaying();
    startNowPlayingPolling();
  });
})();

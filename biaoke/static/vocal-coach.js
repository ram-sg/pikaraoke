(() => {
  "use strict";

  const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  const HISTORY_SECONDS = 10;
  const SONG_LOOKAHEAD_SECONDS = 2.5;
  const STAGE_ROAD_TRAIL_SECONDS = 4.0;
  const STAGE_ROAD_LOOKAHEAD_SECONDS = 12.0;
  const STAGE_ROAD_MAX_LOOKAHEAD_SECONDS = 24.0;
  const STAGE_ROAD_HIT_X = 0.22;
  const STAGE_ROAD_MIN_HEIGHT = 300;
  const TRAIL_MIN_CONFIDENCE = 0.52;
  const REFERENCE_CONTOUR_MIN_CONFIDENCE = 0.38;
  const MAX_REFERENCE_SEGMENT_GAP_SECONDS = 0.28;
  const CONTOUR_TARGET_MAX_GAP_SECONDS = 0.55;
  const TARGET_BRIDGE_MAX_GAP_SECONDS = 0.9;
  const TARGET_BRIDGE_MAX_SEMITONES = 2.25;
  const VISUAL_PITCH_HOLD_MS = 420;
  const VISUAL_MIN_MIDI = 36;
  const VISUAL_MAX_MIDI = 84;
  const VISUAL_TARGET_REJECT_CENTS = 520;
  const VISUAL_STEP_REJECT_CENTS = 700;
  const VISUAL_ARTIFACT_CONFIDENCE = 0.82;
  const DEFAULT_PITCH_BANDS_CENTS = [25, 40, 60, 80, 100, 130, 160, 200, 250, 320];
  const PITCH_BAND_STYLES = [
    { cents: 320, fill: "rgba(207, 77, 67, 0.045)" },
    { cents: 200, fill: "rgba(237, 176, 73, 0.065)" },
    { cents: 100, fill: "rgba(155, 230, 214, 0.09)" },
    { cents: 40, fill: "rgba(18, 199, 156, 0.15)" },
  ];
  const MAX_CENTS_FOR_SCORE = 90;
  const GOOD_CENTS = 35;
  const PLAYBACK_DRIFT_SECONDS = 2;
  const NOW_PLAYING_POLL_MS = 2000;
  const PLAYBACK_START_TIMEOUT_MS = 10000;
  const LYRICS_OFFSET_STEP_SECONDS = 0.5;
  const MAX_LYRICS_OFFSET_SECONDS = 120;
  const VOCAL_REFERENCE_VOLUME = 0.48;
  const VOCAL_REFERENCE_SYNC_DRIFT_SECONDS = 0.75;
  const VOCAL_REFERENCE_SYNC_INTERVAL_MS = 850;
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
    lyricsHaveKaraokeTiming: false,
    lyricsOffsetSeconds: 0,
    activeLyricIndex: -1,
    lastLoadedSubtitleUrl: null,
    currentLyricsKey: null,
    latestPitchMidi: null,
    latestPitchHeld: false,
    lastAcceptedPitch: null,
    vocalReferenceEnabled: false,
    vocalReferenceAvailable: false,
    vocalReferenceKey: null,
    vocalReferenceLastSyncAt: 0,
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
      "coach-audio",
      "coach-video-container",
      "coach-song-road",
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
      "coach-reference-toggle",
      "coach-reference-audio",
    ].forEach((id) => {
      els[id] = document.getElementById(id);
    });
    els.canvas = els["coach-canvas"];
    els.ctx = els.canvas.getContext("2d");
    els.songRoad = els["coach-song-road"];
    els.songRoadCtx = els.songRoad.getContext("2d");
    els.media = els["coach-audio"] || els["coach-video"];
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
    if (!text || !fill) return;
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
    state.latestPitchMidi = null;
    state.latestPitchHeld = false;
    state.lastAcceptedPitch = null;
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
    return els.media;
  }

  function getVocalReferencePlayer() {
    return els["coach-reference-audio"];
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
    if (state.hlsInstance) {
      state.hlsInstance.destroy();
      state.hlsInstance = null;
    }
    state.currentVideoUrl = null;
    [els["coach-audio"], els["coach-video"]].forEach((media) => {
      if (!media) return;
      media.pause();
      media.removeAttribute("src");
      media.load();
    });
    clearVocalReferenceAudio();
    els["coach-video-source"].setAttribute("src", "");
    els["coach-video-container"].classList.remove("is-playing");
  }

  function vocalReferenceUrlForCurrentSong() {
    const baseUrl = CONFIG.vocalReferenceUrl || "/score/vocal-reference/current";
    const key = encodeURIComponent(state.nowPlaying.now_playing_url || state.nowPlaying.now_playing || "current");
    const separator = baseUrl.includes("?") ? "&" : "?";
    return `${baseUrl}${separator}key=${key}`;
  }

  function updateVocalReferenceControl() {
    const toggle = els["coach-reference-toggle"];
    if (!toggle) return;
    toggle.disabled = !state.vocalReferenceAvailable;
    toggle.checked = Boolean(state.vocalReferenceEnabled);
  }

  function setVocalReferenceAvailable(available) {
    state.vocalReferenceAvailable = Boolean(available);
    updateVocalReferenceControl();
    if (!state.vocalReferenceAvailable) {
      clearVocalReferenceAudio();
      return;
    }
    if (state.vocalReferenceEnabled && isMediaPlaying(getVideoPlayer())) {
      playVocalReferenceAudio();
    }
  }

  function clearVocalReferenceAudio() {
    const reference = getVocalReferencePlayer();
    if (!reference) return;
    reference.pause();
    reference.removeAttribute("src");
    reference.load();
    state.vocalReferenceKey = null;
    state.vocalReferenceLastSyncAt = 0;
  }

  function setVocalReferenceVolume() {
    const reference = getVocalReferencePlayer();
    const video = getVideoPlayer();
    if (!reference) return;
    reference.volume = clamp((Number(video?.volume) || 1) * VOCAL_REFERENCE_VOLUME, 0, 1);
  }

  function ensureVocalReferenceAudioLoaded() {
    const reference = getVocalReferencePlayer();
    if (!reference || !state.vocalReferenceEnabled || !state.vocalReferenceAvailable) return false;
    const songKey = state.nowPlaying.now_playing_url || state.nowPlaying.now_playing || "";
    if (!songKey) return false;
    if (state.vocalReferenceKey !== songKey) {
      reference.src = vocalReferenceUrlForCurrentSong();
      reference.preload = "auto";
      reference.playbackRate = getVideoPlayer()?.playbackRate || 1;
      setVocalReferenceVolume();
      reference.load();
      state.vocalReferenceKey = songKey;
    }
    return true;
  }

  function syncVocalReferenceToMain(force = false) {
    const reference = getVocalReferencePlayer();
    const video = getVideoPlayer();
    if (!reference || !video || !reference.src) return;
    const now = performance.now();
    if (!force && now - state.vocalReferenceLastSyncAt < VOCAL_REFERENCE_SYNC_INTERVAL_MS) return;
    state.vocalReferenceLastSyncAt = now;

    const position = Number(video.currentTime || 0);
    if (!Number.isFinite(position)) return;

    const applySync = () => {
      if (
        force ||
        !Number.isFinite(reference.currentTime) ||
        Math.abs(reference.currentTime - position) > VOCAL_REFERENCE_SYNC_DRIFT_SECONDS
      ) {
        try {
          reference.currentTime = position;
        } catch (error) {
          console.log("Could not sync vocal reference yet", error);
        }
      }
    };

    if (reference.readyState >= 1) {
      applySync();
      return;
    }
    reference.addEventListener("loadedmetadata", applySync, { once: true });
  }

  async function playVocalReferenceAudio() {
    if (!ensureVocalReferenceAudioLoaded()) return;
    const reference = getVocalReferencePlayer();
    const video = getVideoPlayer();
    if (!reference || !video || video.paused) return;
    syncVocalReferenceToMain(true);
    try {
      await reference.play();
    } catch (error) {
      console.log("Vocal reference playback blocked", error);
    }
  }

  function pauseVocalReferenceAudio() {
    getVocalReferencePlayer()?.pause();
  }

  function hasVocalReference(guide) {
    if (!guide || typeof guide !== "object") return false;
    if (guide.vocal_reference_available) return true;
    const assets = guide.assets && typeof guide.assets === "object" ? guide.assets : {};
    return Boolean(assets.original_audio_path);
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

  function songNoteAtTime(songTime, notes = songGuideNotes(), graceSeconds = 0) {
    for (let index = 0; index < notes.length; index++) {
      const note = notes[index];
      if (songTime >= note.start && songTime <= note.end) {
        return { note, index };
      }
    }
    if (graceSeconds <= 0) return null;
    let closest = null;
    let closestDistance = Infinity;
    for (let index = 0; index < notes.length; index++) {
      const note = notes[index];
      const distance = Math.min(Math.abs(songTime - note.start), Math.abs(songTime - note.end));
      if (distance <= graceSeconds && distance < closestDistance) {
        closest = { note, index };
        closestDistance = distance;
      }
    }
    return closest;
  }

  function lyricLineForSongTime(songTime, graceSeconds = 0) {
    if (!Array.isArray(state.lyrics) || state.lyrics.length === 0) return null;
    const lyricTime = Number(songTime) - Number(state.lyricsOffsetSeconds || 0);
    if (!Number.isFinite(lyricTime)) return null;
    for (let index = 0; index < state.lyrics.length; index++) {
      const line = state.lyrics[index];
      const start = Number(line.start);
      const end = Number(line.end);
      if (!Number.isFinite(start) || !Number.isFinite(end)) continue;
      if (lyricTime >= start - graceSeconds && lyricTime <= end + graceSeconds) {
        return {
          line,
          index,
          start: start + Number(state.lyricsOffsetSeconds || 0),
          end: end + Number(state.lyricsOffsetSeconds || 0),
        };
      }
    }
    return null;
  }

  function shouldGateTargetsByLyrics() {
    return selectedMode() === "song" && Array.isArray(state.lyrics) && state.lyrics.length > 0;
  }

  function isInsideLyricTargetWindow(songTime, graceSeconds = 0.15) {
    return !shouldGateTargetsByLyrics() || Boolean(lyricLineForSongTime(songTime, graceSeconds));
  }

  function bridgedSongNoteAtTime(songTime, notes = songGuideNotes()) {
    if (!Array.isArray(notes) || notes.length < 2) return null;
    let previous = null;
    let previousIndex = -1;
    let next = null;
    let nextIndex = -1;

    for (let index = 0; index < notes.length; index++) {
      const note = notes[index];
      const start = Number(note.start);
      const end = Number(note.end);
      if (!Number.isFinite(start) || !Number.isFinite(end)) continue;
      if (end <= songTime && (!previous || end > Number(previous.end))) {
        previous = note;
        previousIndex = index;
      }
      if (start >= songTime) {
        next = note;
        nextIndex = index;
        break;
      }
    }

    if (!previous || !next) return null;
    const previousEnd = Number(previous.end);
    const nextStart = Number(next.start);
    const gapSeconds = nextStart - previousEnd;
    if (
      gapSeconds <= 0 ||
      gapSeconds > TARGET_BRIDGE_MAX_GAP_SECONDS ||
      songTime < previousEnd ||
      songTime > nextStart
    ) {
      return null;
    }

    const previousMidi = Number(previous.midi);
    const nextMidi = Number(next.midi);
    if (
      !Number.isFinite(previousMidi) ||
      !Number.isFinite(nextMidi) ||
      Math.abs(nextMidi - previousMidi) > TARGET_BRIDGE_MAX_SEMITONES
    ) {
      return null;
    }

    const ratio = clamp((songTime - previousEnd) / gapSeconds, 0, 1);
    const midi = previousMidi + (nextMidi - previousMidi) * ratio;
    const confidence =
      Math.min(Number(previous.confidence ?? 0.6), Number(next.confidence ?? 0.6)) * 0.78;
    return {
      note: {
        start: previousEnd,
        end: nextStart,
        midi: Math.round(midi),
        confidence,
        pitchBandsCents: previous.pitchBandsCents || next.pitchBandsCents,
      },
      index: previousIndex >= 0 ? previousIndex : nextIndex,
      bridged: true,
      midi,
    };
  }

  function contourPointAtSongTime(
    songTime,
    contour = songGuideContour(),
    maxGapSeconds = CONTOUR_TARGET_MAX_GAP_SECONDS
  ) {
    if (!Array.isArray(contour) || contour.length === 0) return null;

    let low = 0;
    let high = contour.length - 1;
    while (low <= high) {
      const mid = Math.floor((low + high) / 2);
      if (Number(contour[mid].time) < songTime) {
        low = mid + 1;
      } else {
        high = mid - 1;
      }
    }

    const next = contour[low] || null;
    const previous = contour[low - 1] || null;
    if (previous && next) {
      const previousTime = Number(previous.time);
      const nextTime = Number(next.time);
      const gap = nextTime - previousTime;
      if (gap > 0 && gap <= maxGapSeconds * 2 && songTime >= previousTime && songTime <= nextTime) {
        const ratio = clamp((songTime - previousTime) / gap, 0, 1);
        const midi = Number(previous.midi) + (Number(next.midi) - Number(previous.midi)) * ratio;
        const confidence =
          Number(previous.confidence ?? 0.6) +
          (Number(next.confidence ?? 0.6) - Number(previous.confidence ?? 0.6)) * ratio;
        return { time: songTime, midi, confidence };
      }
    }

    const closest = [previous, next]
      .filter(Boolean)
      .map((point) => ({ point, distance: Math.abs(Number(point.time) - songTime) }))
      .sort((a, b) => a.distance - b.distance)[0];
    if (!closest || closest.distance > maxGapSeconds) return null;
    return {
      time: songTime,
      midi: Number(closest.point.midi),
      confidence: Number(closest.point.confidence ?? 0.6),
    };
  }

  function referenceTargetAtSongTime(songTime, notes = songGuideNotes(), contour = songGuideContour()) {
    const lyricMatch = lyricLineForSongTime(songTime, 0.12);
    if (shouldGateTargetsByLyrics() && !lyricMatch) return null;

    const noteMatch = songNoteAtTime(songTime, notes, 0.35) || bridgedSongNoteAtTime(songTime, notes);
    const contourPoint = contourPointAtSongTime(songTime, contour);
    if (!noteMatch && !contourPoint) return null;

    const note = noteMatch?.note || {
      start: lyricMatch ? lyricMatch.start : songTime,
      end: lyricMatch ? lyricMatch.end : songTime + 0.25,
      midi: contourPoint ? Math.round(contourPoint.midi) : 60,
      confidence: contourPoint ? contourPoint.confidence : 0.45,
    };
    const duration = Math.max(0.05, Number(note.end) - Number(note.start));
    const midi = contourPoint ? contourPoint.midi : Number.isFinite(noteMatch.midi) ? noteMatch.midi : Number(note.midi);
    return {
      midi,
      noteMidi: Number(note.midi),
      index: noteMatch ? noteMatch.index : `lyric-${lyricMatch?.index ?? Math.floor(songTime)}`,
      cycle: "song",
      duration,
      progress: clamp((songTime - Number(note.start)) / duration, 0, 1),
      source: contourPoint ? "song-contour" : noteMatch?.bridged ? "song-bridge" : "song",
      songTime,
      confidence: contourPoint ? contourPoint.confidence : Number(note.confidence ?? 0.6),
    };
  }

  function currentSongTarget(now) {
    if (!state.songGuide) return null;
    const songTime = songPlaybackTime(now);
    const target = referenceTargetAtSongTime(songTime);
    if (target) return target;
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

  function centsBetweenMidi(sourceMidi, targetMidi) {
    return (Number(sourceMidi) - Number(targetMidi)) * 100;
  }

  function heldVisualPitch(now) {
    const last = state.lastAcceptedPitch;
    if (!last || now - last.time > VISUAL_PITCH_HOLD_MS) return null;
    return last.midi;
  }

  function acceptVisualPitch(pitchMidi, result, target, now) {
    if (!Number.isFinite(pitchMidi) || pitchMidi < VISUAL_MIN_MIDI || pitchMidi > VISUAL_MAX_MIDI) {
      return false;
    }
    if (!result || Number(result.confidence || 0) < TRAIL_MIN_CONFIDENCE) {
      return false;
    }

    const targetDelta = target ? Math.abs(centsBetweenMidi(pitchMidi, target.midi)) : 0;
    const previous = state.lastAcceptedPitch;
    const previousAge = previous ? now - previous.time : Infinity;
    const stepDelta = previous ? Math.abs(centsBetweenMidi(pitchMidi, previous.midi)) : 0;

    if (target && targetDelta > VISUAL_TARGET_REJECT_CENTS && result.confidence < VISUAL_ARTIFACT_CONFIDENCE) {
      return false;
    }
    if (previousAge <= VISUAL_PITCH_HOLD_MS && stepDelta > VISUAL_STEP_REJECT_CENTS && result.confidence < 0.88) {
      return false;
    }
    return true;
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

  function hasKaraokeTimingText(text) {
    return /\{[^}]*\\k[fo]?\d+[^}]*\}/i.test(String(text || ""));
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
      const lineHasKaraokeTiming = hasKaraokeTimingText(text);

      lyrics.push({
        start,
        end,
        text: plain,
        has_karaoke_timing: lineHasKaraokeTiming,
        segments: parseKaraokeSegments(text, start, end),
      });
    }

    return lyrics.sort((a, b) => a.start - b.start);
  }

  function renderLyricLine(container, line, time) {
    container.replaceChildren();
    if (!line) return;
    const hasPreciseTiming =
      state.lyricsHaveKaraokeTiming && (line.has_karaoke_timing !== false);
    const segments =
      hasPreciseTiming && line.segments?.length
        ? line.segments
        : [{ text: line.text, start: line.start, end: line.end }];
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
    state.lyricsHaveKaraokeTiming = false;
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
      state.lyricsHaveKaraokeTiming = hasKaraokeTimingText(content);
      state.activeLyricIndex = -1;
      if (state.lyrics.length === 0) {
        setLyricsStatus(TEXT.noLyrics, "is-warning");
        return;
      }
      setLyricsStatus(TEXT.lyricsReady, "is-ready");
    } catch (error) {
      console.log("Could not load lyrics", error);
      state.lyrics = [];
      state.lyricsHaveKaraokeTiming = false;
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
        state.lyricsHaveKaraokeTiming = false;
        state.activeLyricIndex = -1;
        setLyricsStatus(TEXT.lyricsMismatch, "is-danger");
        return true;
      }
      if (guide.status !== "ready" || !Array.isArray(guide.lines) || guide.lines.length === 0) {
        state.lyrics = [];
        state.lyricsHaveKaraokeTiming = false;
        state.activeLyricIndex = -1;
        setLyricsStatus(guide.message || TEXT.noLyrics, guide.status === "error" ? "is-danger" : "is-warning");
        return true;
      }
      state.lyrics = guide.lines;
      state.lyricsHaveKaraokeTiming = Boolean(guide.has_karaoke_timing);
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
      playVocalReferenceAudio();
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
        syncVocalReferenceToMain(true);
      }
      return;
    }

    clearVideo();
    state.currentVideoUrl = streamUrl;
    els["coach-video-container"].classList.add("is-playing");

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
    seekMedia(video, position);
    await playCurrentVideo();

    window.setTimeout(() => {
      if (!isMediaPlaying(video) && !video.paused && state.currentVideoUrl === streamUrl) {
        endCurrentSong("failed to start");
      }
    }, PLAYBACK_START_TIMEOUT_MS);
  }

  function seekMedia(media, position) {
    const requestedPosition = Number(position || 0);
    if (!Number.isFinite(requestedPosition) || requestedPosition <= 0) return;
    const applySeek = () => {
      try {
        media.currentTime = requestedPosition;
      } catch (error) {
        console.log("Could not seek media yet", error);
      }
    };
    if (media.readyState >= 1) {
      applySeek();
      return;
    }
    media.addEventListener("loadedmetadata", applySeek, { once: true });
  }

  async function handleNowPlayingUpdate(np) {
    state.nowPlaying = np || {};
    updateSongChrome(state.nowPlaying);

    if (!state.nowPlaying.now_playing) {
      clearVideo();
      state.songGuide = null;
      state.songSync = null;
      setVocalReferenceAvailable(false);
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
      setVocalReferenceAvailable(false);
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
        if (state.nowPlaying.is_paused) {
          pauseVocalReferenceAudio();
        } else if (state.vocalReferenceEnabled) {
          playVocalReferenceAudio();
        }
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
    const now = performance.now();
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
    syncVocalReferenceToMain(false);
    drawStageSongRoad(now, currentTarget(now), state.latestPitchMidi);
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
      pauseVocalReferenceAudio();
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
      setVocalReferenceVolume();
    });
  }

  function setupVideoEvents() {
    const video = getVideoPlayer();
    const reference = getVocalReferencePlayer();
    video.addEventListener("play", () => {
      els["coach-video-container"].classList.add("is-playing");
      if (state.isMaster && state.socket) {
        const streamUrl = state.currentVideoUrl;
        window.setTimeout(() => {
          if (streamUrl && state.currentVideoUrl === streamUrl && isMediaPlaying(video)) {
            state.socket.emit("start_song", { stream_url: streamUrl });
          }
        }, 1200);
      }
      playVocalReferenceAudio();
    });
    video.addEventListener("pause", () => {
      pauseVocalReferenceAudio();
    });
    video.addEventListener("seeked", () => {
      syncVocalReferenceToMain(true);
    });
    video.addEventListener("ratechange", () => {
      const reference = getVocalReferencePlayer();
      if (reference) reference.playbackRate = video.playbackRate || 1;
    });
    video.addEventListener("volumechange", () => {
      setVocalReferenceVolume();
    });
    video.addEventListener("ended", () => {
      pauseVocalReferenceAudio();
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
    reference?.addEventListener("error", () => {
      if (!reference.src) return;
      console.log("Vocal reference stream failed");
      clearVocalReferenceAudio();
      setVocalReferenceAvailable(false);
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
      let guide = normalizeSongGuide(await response.json());
      if ((!response.ok || guide.notes.length === 0) && CONFIG.guideUrl) {
        guide = await loadFullSongGuideFallback(guide);
      }
      if (guide.notes.length === 0) {
        state.songGuide = null;
        state.songSync = null;
        setVocalReferenceAvailable(false);
        setStatus(guide.message || TEXT.noGuide, guide.status === "idle" ? "" : "is-warning");
        return null;
      }

      state.songGuide = guide;
      setVocalReferenceAvailable(hasVocalReference(guide));
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
      setVocalReferenceAvailable(false);
      setStatus(TEXT.guideError, "is-danger");
      return null;
    } finally {
      state.songGuideLoading = false;
    }
  }

  async function loadFullSongGuideFallback(previousGuide) {
    try {
      const response = await fetch(CONFIG.guideUrl, { cache: "no-store" });
      const guide = normalizeSongGuide(await response.json());
      if (response.ok && guide.notes.length > 0) return guide;
    } catch (error) {
      console.log("Could not load full song guide fallback", error);
    }
    return previousGuide;
  }

  function normalizeSongGuide(rawGuide) {
    const raw = rawGuide && typeof rawGuide === "object" ? rawGuide : {};
    const runtime = raw.runtime && typeof raw.runtime === "object" ? raw.runtime : {};
    const melody = raw.melody && typeof raw.melody === "object" ? raw.melody : {};
    const quality = raw.quality && typeof raw.quality === "object" ? raw.quality : {};
    const assets = raw.assets && typeof raw.assets === "object" ? raw.assets : {};
    const notes = normalizeGuideNotes(raw);
    const contour = normalizeGuideContour(raw);
    return {
      ...raw,
      ...melody,
      status: notes.length > 0 ? "ready" : (melody.status || raw.status || "missing"),
      message: melody.message || raw.message,
      title: raw.title || runtime.title || state.nowPlaying.now_playing || "",
      playback_position: Number(raw.playback_position ?? runtime.playback_position ?? 0),
      is_paused: Boolean(raw.is_paused ?? runtime.is_paused ?? false),
      quality_messages: raw.quality_messages || quality.messages || melody.quality_messages || [],
      guide_status: raw.guide_status || quality.status || raw.status,
      vocal_reference_available: Boolean(raw.vocal_reference_available || assets.original_audio_path),
      assets,
      notes,
      contour,
    };
  }

  function normalizeGuideNotes(raw) {
    const directNotes = Array.isArray(raw?.notes)
      ? raw.notes
      : Array.isArray(raw?.melody?.notes)
        ? raw.melody.notes
        : [];
    const taskNotes = normalizeTaskNotes(raw?.tasks);
    const source = directNotes.length > 0 ? directNotes : taskNotes;
    return source
      .map((note) => {
        const start = Number(note.start);
        const end = Number(note.end);
        const midi = Number(note.midi ?? note.target_midi);
        if (!Number.isFinite(start) || !Number.isFinite(end) || !Number.isFinite(midi) || end <= start) {
          return null;
        }
        const matchingTask = findMatchingTaskNote(taskNotes, start, end, midi);
        return {
          ...note,
          start,
          end,
          midi,
          note: note.note || note.target_note || noteName(midi),
          frequency: Number(note.frequency ?? note.target_frequency ?? midiToFrequency(midi)),
          confidence: Number(note.confidence ?? note.weight ?? 0.6),
          pitchBandsCents: normalizePitchBands(
            note.pitchBandsCents || note.pitch_bands_cents || matchingTask?.pitchBandsCents
          ),
        };
      })
      .filter(Boolean)
      .sort((a, b) => a.start - b.start);
  }

  function findMatchingTaskNote(tasks, start, end, midi) {
    if (!Array.isArray(tasks) || tasks.length === 0) return null;
    return tasks.find(
      (task) =>
        Math.abs(Number(task.start) - start) <= 0.04 &&
        Math.abs(Number(task.end) - end) <= 0.04 &&
        Math.abs(Number(task.midi) - midi) <= 0.01
    );
  }

  function normalizePitchBands(value) {
    const bands = Array.isArray(value)
      ? value
          .map((band) => Number(band))
          .filter((band) => Number.isFinite(band) && band > 0)
          .sort((a, b) => a - b)
      : [];
    return bands.length > 0 ? bands : DEFAULT_PITCH_BANDS_CENTS;
  }

  function normalizeGuideContour(raw) {
    const source = Array.isArray(raw?.contour)
      ? raw.contour
      : Array.isArray(raw?.melody?.contour)
        ? raw.melody.contour
        : [];
    return source
      .map((point) => {
        const time = Number(point.time ?? point.t ?? point.start);
        const midi = Number(point.midi);
        const confidence = Number(point.confidence ?? point.weight ?? 0.6);
        if (!Number.isFinite(time) || !Number.isFinite(midi) || midi < 24 || midi > 96) {
          return null;
        }
        return { time, midi, confidence };
      })
      .filter(Boolean)
      .sort((a, b) => a.time - b.time);
  }

  function normalizeTaskNotes(tasks) {
    if (!Array.isArray(tasks)) return [];
    return tasks
      .filter((task) => task && task.type === "pitch")
      .map((task) => ({
        start: task.start,
        end: task.end,
        midi: task.target_midi,
        note: task.target_note,
        frequency: task.target_frequency,
        confidence: task.confidence ?? task.weight,
        pitchBandsCents: normalizePitchBands(task.pitch_bands_cents || task.pitchBandsCents),
      }));
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
        setVocalReferenceAvailable(false);
        setStatus(TEXT.noSong, "is-warning");
        return;
      }
      if (state.songGuide.title && data.now_playing !== state.songGuide.title) {
        state.songGuide = null;
        state.songSync = null;
        setVocalReferenceAvailable(false);
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
      if (String(target.source || "").startsWith("song")) {
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

  function resizeSongRoadCanvas() {
    const canvas = els.songRoad;
    const ctx = els.songRoadCtx;
    if (!canvas || !ctx) return null;
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    const dpr = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.floor(rect.width * dpr));
    const height = Math.max(1, Math.floor(rect.height * dpr));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, width: rect.width, height: rect.height };
  }

  function drawRoundRect(ctx, x, y, width, height, radius) {
    const r = Math.min(radius, width / 2, height / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + width - r, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + r);
    ctx.lineTo(x + width, y + height - r);
    ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
    ctx.lineTo(x + r, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  function songRoadMidiRange(songTime) {
    const notes = songGuideNotes();
    const contour = songGuideContour();
    const minTime = songTime - 4;
    const maxTime = songTime + songRoadLookaheadSeconds(songTime, notes);
    const visibleNotes = visibleRoadNotes(notes, minTime, maxTime);
    const midiValues = [];
    visibleNotes.forEach((note) => {
      const midi = Number(note.midi);
      if (!Number.isFinite(midi)) return;
      const outerBand = Math.max(...normalizePitchBands(note.pitchBandsCents)) / 100;
      midiValues.push(midi - outerBand, midi, midi + outerBand);
    });
    visibleRoadContour(contour, minTime, maxTime).forEach((point) => {
      const midi = Number(point.midi);
      if (Number.isFinite(midi)) midiValues.push(midi - 0.4, midi, midi + 0.4);
    });

    if (midiValues.length === 0) return { minMidi: 48, maxMidi: 72 };

    let minMidi = Math.floor(Math.min(...midiValues)) - 1;
    let maxMidi = Math.ceil(Math.max(...midiValues)) + 1;
    const currentNote = visibleNotes.find((note) => songTime >= Number(note.start) && songTime <= Number(note.end));
    if (currentNote && Number.isFinite(Number(currentNote.midi))) {
      const outerBand = Math.max(...normalizePitchBands(currentNote.pitchBandsCents)) / 100;
      minMidi = Math.min(minMidi, Number(currentNote.midi) - outerBand - 2);
      maxMidi = Math.max(maxMidi, Number(currentNote.midi) + outerBand + 2);
    }
    const span = maxMidi - minMidi;
    if (span < 10) {
      const pad = (10 - span) / 2;
      minMidi -= pad;
      maxMidi += pad;
    }
    return { minMidi, maxMidi };
  }

  function songGuideNotes() {
    return Array.isArray(state.songGuide?.notes) ? state.songGuide.notes : [];
  }

  function songGuideContour() {
    return Array.isArray(state.songGuide?.contour) ? state.songGuide.contour : [];
  }

  function songRoadLookaheadSeconds(songTime, notes = songGuideNotes()) {
    const baseLookahead = STAGE_ROAD_LOOKAHEAD_SECONDS;
    const hasVisibleNotes = notes.some(
      (note) => Number(note.end) >= songTime - STAGE_ROAD_TRAIL_SECONDS && Number(note.start) <= songTime + baseLookahead
    );
    if (hasVisibleNotes) return baseLookahead;

    const nextNote = notes.find((note) => Number(note.start) > songTime);
    if (!nextNote) return baseLookahead;
    return clamp(Number(nextNote.start) - songTime + 4, baseLookahead, STAGE_ROAD_MAX_LOOKAHEAD_SECONDS);
  }

  function songRoadLayout(width, height) {
    const stageRect = els["coach-video-container"]?.getBoundingClientRect();
    const lyricsRect = els["coach-lyrics-current"]?.closest(".coach-lyrics")?.getBoundingClientRect();
    const measuredLyricsTop =
      stageRect && lyricsRect ? lyricsRect.top - stageRect.top : height * 0.68;
    const lyricsTop = clamp(measuredLyricsTop, height * 0.58, height - 96);
    const roadTop = clamp(height * 0.08, 48, 96);
    const railY = clamp(lyricsTop - 24, roadTop + STAGE_ROAD_MIN_HEIGHT, height - 74);
    const roadBottom = Math.max(roadTop + STAGE_ROAD_MIN_HEIGHT, railY - 24);
    const labelInset = clamp(width * 0.018, 16, 32);
    return {
      roadTop,
      roadBottom,
      roadHeight: Math.max(STAGE_ROAD_MIN_HEIGHT, roadBottom - roadTop),
      railY,
      labelInset,
    };
  }

  function activeLyricLineAt(songTime) {
    if (!state.lyrics.length) return null;
    const lyricTime = songTime - Number(state.lyricsOffsetSeconds || 0);
    return (
      state.lyrics.find((line) => lyricTime >= line.start && lyricTime <= line.end) ||
      state.lyrics.find((line) => line.start > lyricTime) ||
      null
    );
  }

  function visibleLyricSegments(minTime, maxTime) {
    const offset = Number(state.lyricsOffsetSeconds || 0);
    const segments = [];
    state.lyrics.forEach((line, lineIndex) => {
      const lineStart = Number(line.start) + offset;
      const lineEnd = Number(line.end) + offset;
      const lineText = String(line.text || "").trim();
      const hasPreciseTiming =
        state.lyricsHaveKaraokeTiming && line.has_karaoke_timing !== false && line.segments?.length;

      if (!hasPreciseTiming) {
        if (
          lineText &&
          Number.isFinite(lineStart) &&
          Number.isFinite(lineEnd) &&
          lineEnd > lineStart &&
          lineEnd >= minTime &&
          lineStart <= maxTime
        ) {
          segments.push({
            start: lineStart,
            end: lineEnd,
            text: lineText,
            lineIndex,
            segmentIndex: 0,
            precision: "line",
          });
        }
        return;
      }

      const lineSegments = line.segments;
      lineSegments.forEach((segment, segmentIndex) => {
        const start = Number(segment.start) + offset;
        const end = Number(segment.end) + offset;
        const text = String(segment.text || "").trim();
        if (!text || !Number.isFinite(start) || !Number.isFinite(end) || end <= start) return;
        if (end < minTime || start > maxTime) return;
        segments.push({
          start,
          end,
          text,
          lineIndex,
          segmentIndex,
          precision: "karaoke",
        });
      });
    });
    return segments.sort((a, b) => a.start - b.start || a.segmentIndex - b.segmentIndex);
  }

  function lyricFontForWidth(ctx, text, maxWidth, baseSize = 22, minSize = 11) {
    const cleanText = String(text || "").trim();
    let size = baseSize;
    while (size > minSize) {
      ctx.font = `900 ${size}px sans-serif`;
      if (ctx.measureText(cleanText).width <= maxWidth) return size;
      size -= 1;
    }
    return minSize;
  }

  function drawLyricSegmentText(ctx, segment, x1, x2, textY, songTime, hitX) {
    const slotWidth = x2 - x1;
    const isActive = songTime >= segment.start && songTime < segment.end;
    if (slotWidth < 18 && !isActive) return;

    const textPadding = 4;
    const safeWidth = Math.max(10, slotWidth - textPadding * 2);
    const fontSize = lyricFontForWidth(ctx, segment.text, safeWidth);
    const textX = x1 + textPadding;
    const clipTop = textY - fontSize * 0.82;
    const clipHeight = fontSize * 1.7;
    ctx.font = `900 ${fontSize}px sans-serif`;
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";

    ctx.save();
    ctx.beginPath();
    ctx.rect(x1, clipTop, Math.max(1, slotWidth), clipHeight);
    ctx.clip();
    ctx.fillStyle = songTime >= segment.end ? "rgba(18, 199, 156, 0.96)" : "rgba(246, 243, 234, 0.72)";
    ctx.fillText(segment.text, textX, textY);
    ctx.restore();

    if (songTime < segment.start || songTime >= segment.end) return;

    ctx.save();
    ctx.beginPath();
    ctx.rect(x1, clipTop, Math.max(1, clamp(hitX, x1, x2) - x1), clipHeight);
    ctx.clip();
    ctx.fillStyle = "rgba(18, 199, 156, 1)";
    ctx.fillText(segment.text, textX, textY);
    ctx.restore();
  }

  function drawStageLyricRail(ctx, width, xForTime, songTime, railY, minTime, maxTime, hitX) {
    if (!state.lyrics.length) return;

    const segments = visibleLyricSegments(minTime, maxTime);
    if (segments.length === 0) return;

    const railH = 8;
    const railTop = railY - 11;
    const textY = railY + 8;

    ctx.save();
    ctx.fillStyle = "rgba(3, 6, 10, 0.46)";
    drawRoundRect(ctx, 0, railTop - 8, width, 42, 0);
    ctx.fill();

    ctx.strokeStyle = "rgba(246, 243, 234, 0.14)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, railY);
    ctx.lineTo(width, railY);
    ctx.stroke();

    segments.forEach((segment) => {
      const x1 = xForTime(segment.start);
      const x2 = xForTime(segment.end);
      if (x2 < -20 || x1 > width + 20) return;

      const blockX = Math.max(-20, x1);
      const blockW = Math.min(width + 40, Math.max(5, x2 - x1));
      const isDone = songTime >= segment.end;
      const isActive = songTime >= segment.start && songTime < segment.end;

      ctx.fillStyle = isDone
        ? "rgba(18, 199, 156, 0.44)"
        : isActive
          ? "rgba(237, 176, 73, 0.62)"
          : "rgba(246, 243, 234, 0.14)";
      drawRoundRect(ctx, blockX, railTop, blockW, railH, 4);
      ctx.fill();

      if (isActive) {
        ctx.fillStyle = "rgba(18, 199, 156, 0.88)";
        drawRoundRect(ctx, blockX, railTop, Math.max(1, clamp(hitX, x1, x2) - x1), railH, 4);
        ctx.fill();
      }

      drawLyricSegmentText(ctx, segment, x1, x2, textY, songTime, hitX);
    });

    ctx.fillStyle = "rgba(246, 243, 234, 0.72)";
    ctx.font = "800 11px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "alphabetic";
    ctx.fillText("agora", hitX, railTop - 10);
    ctx.restore();
    ctx.textAlign = "start";
    ctx.textBaseline = "alphabetic";
  }

  function visibleRoadNotes(notes, minTime, maxTime) {
    return notes.filter((note) => {
      const start = Number(note.start);
      const end = Number(note.end);
      const midi = Number(note.midi);
      if (!Number.isFinite(start) || !Number.isFinite(end) || !Number.isFinite(midi)) return false;
      if (end < minTime || start > maxTime) return false;
      if (!shouldGateTargetsByLyrics()) return true;
      const midpoint = start + (end - start) / 2;
      return (
        isInsideLyricTargetWindow(midpoint, 0.25) ||
        isInsideLyricTargetWindow(start, 0.15) ||
        isInsideLyricTargetWindow(end, 0.15)
      );
    });
  }

  function visibleRoadContour(contour, minTime, maxTime) {
    return contour.filter((point) => {
      const time = Number(point.time);
      const midi = Number(point.midi);
      const confidence = Number(point.confidence ?? 1);
      return (
        Number.isFinite(time) &&
        Number.isFinite(midi) &&
        confidence >= REFERENCE_CONTOUR_MIN_CONFIDENCE &&
        time >= minTime &&
        time <= maxTime &&
        isInsideLyricTargetWindow(time, 0.15)
      );
    });
  }

  function clampRoadY(y, layout) {
    return clamp(y, layout.roadTop, layout.roadTop + layout.roadHeight);
  }

  function targetNoteAtSongTime(songTime, notes = songGuideNotes(), graceSeconds = 0.25) {
    return (
      notes.find((note) => songTime >= Number(note.start) && songTime <= Number(note.end)) ||
      notes.find((note) => Math.abs(songTime - Number(note.start)) <= graceSeconds) ||
      notes.find((note) => Math.abs(songTime - Number(note.end)) <= graceSeconds) ||
      null
    );
  }

  function graphPitchPoint(point, notes, contour = songGuideContour()) {
    if (!point || Number(point.confidence ?? 1) < TRAIL_MIN_CONFIDENCE) return null;
    const songTime = Number(point.songTime);
    const midi = Number(point.midi);
    if (!Number.isFinite(songTime) || !Number.isFinite(midi)) return null;
    const target = referenceTargetAtSongTime(songTime, notes, contour);
    if (!target || !Number.isFinite(Number(target.midi))) return null;

    const targetMidi = Number(target.midi);
    const targetNote = targetNoteAtSongTime(songTime, notes, 0.35);
    const maxBandMidi = Math.max(...normalizePitchBands(targetNote?.pitchBandsCents)) / 100;
    const deltaMidi = midi - targetMidi;
    return {
      songTime,
      cents: Math.abs(deltaMidi * 100),
      midi: targetMidi + clamp(deltaMidi, -maxBandMidi, maxBandMidi),
      rawMidi: midi,
    };
  }

  function graphReferencePoint(point, notes, contour = songGuideContour()) {
    if (!point || Number(point.confidence ?? 1) < REFERENCE_CONTOUR_MIN_CONFIDENCE) return null;
    const songTime = Number(point.time ?? point.songTime);
    const midi = Number(point.midi);
    if (!Number.isFinite(songTime) || !Number.isFinite(midi)) return null;
    const target = referenceTargetAtSongTime(songTime, notes, contour);
    if (!target || !Number.isFinite(Number(target.midi))) return null;

    const targetMidi = Number(target.midi);
    const targetNote = targetNoteAtSongTime(songTime, notes, 0.3);
    const maxBandMidi = Math.max(...normalizePitchBands(targetNote?.pitchBandsCents)) / 100;
    return {
      songTime,
      midi: targetMidi + clamp(midi - targetMidi, -maxBandMidi, maxBandMidi),
      rawMidi: midi,
    };
  }

  function drawPitchBandCorridors(ctx, visibleNotes, xForTime, yForMidi, layout) {
    visibleNotes.forEach((note) => {
      const start = Number(note.start);
      const end = Number(note.end);
      const midi = Number(note.midi);
      const x1 = Math.max(-48, xForTime(start));
      const x2 = Math.min(layout.width + 48, xForTime(end));
      const width = Math.max(3, x2 - x1);
      PITCH_BAND_STYLES.forEach((style) => {
        const cents = style.cents;
        const upperY = clampRoadY(yForMidi(midi + cents / 100), layout);
        const lowerY = clampRoadY(yForMidi(midi - cents / 100), layout);
        const top = Math.min(upperY, lowerY);
        const height = Math.max(2, Math.abs(lowerY - upperY));
        ctx.fillStyle = style.fill;
        drawRoundRect(ctx, x1, top, width, height, Math.min(10, height / 2));
        ctx.fill();
      });
    });
  }

  function drawTargetNoteBlocks(ctx, visibleNotes, xForTime, yForMidi, layout, songTime) {
    let previous = null;
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";

    visibleNotes.forEach((note) => {
      const start = Number(note.start);
      const end = Number(note.end);
      const midi = Number(note.midi);
      const x1 = Math.max(-48, xForTime(start));
      const x2 = Math.min(layout.width + 48, xForTime(end));
      const y = clampRoadY(yForMidi(midi), layout);
      const width = Math.max(4, x2 - x1);
      const blockHeight = clamp(layout.roadHeight * 0.052, 18, 32);
      const blockY = y - blockHeight / 2;
      const isCurrent = songTime >= start && songTime <= end;
      const isDone = songTime > end;

      if (previous && start - previous.end <= 1.35) {
        ctx.strokeStyle = "rgba(246, 243, 234, 0.16)";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(previous.x, previous.y);
        ctx.lineTo(x1, y);
        ctx.stroke();
      }

      const outerTop = clampRoadY(yForMidi(midi + 2), layout);
      const outerBottom = clampRoadY(yForMidi(midi - 2), layout);
      const innerTop = clampRoadY(yForMidi(midi + 0.5), layout);
      const innerBottom = clampRoadY(yForMidi(midi - 0.5), layout);

      ctx.fillStyle = "rgba(237, 176, 73, 0.07)";
      drawRoundRect(ctx, x1, Math.min(outerTop, outerBottom), width, Math.max(6, Math.abs(outerBottom - outerTop)), 10);
      ctx.fill();

      ctx.fillStyle = isCurrent ? "rgba(18, 199, 156, 0.24)" : "rgba(18, 199, 156, 0.12)";
      drawRoundRect(ctx, x1, Math.min(innerTop, innerBottom), width, Math.max(4, Math.abs(innerBottom - innerTop)), 8);
      ctx.fill();

      ctx.fillStyle = isCurrent
        ? "rgba(246, 243, 234, 0.94)"
        : isDone
          ? "rgba(18, 199, 156, 0.36)"
          : "rgba(155, 230, 214, 0.62)";
      drawRoundRect(ctx, x1, blockY, width, blockHeight, Math.min(9, blockHeight / 2));
      ctx.fill();

      ctx.strokeStyle = isCurrent ? "rgba(3, 6, 10, 0.84)" : "rgba(246, 243, 234, 0.18)";
      ctx.lineWidth = isCurrent ? 2 : 1;
      drawRoundRect(ctx, x1, blockY, width, blockHeight, Math.min(9, blockHeight / 2));
      ctx.stroke();

      if (isCurrent) {
        const doneWidth = Math.max(0, clamp(xForTime(songTime), x1, x2) - x1);
        ctx.fillStyle = "rgba(18, 199, 156, 0.92)";
        drawRoundRect(ctx, x1, blockY, doneWidth, blockHeight, Math.min(9, blockHeight / 2));
        ctx.fill();
      }

      if (width > 54) {
        ctx.fillStyle = isCurrent ? "rgba(3, 6, 10, 0.78)" : "rgba(3, 6, 10, 0.5)";
        ctx.font = "800 12px sans-serif";
        ctx.fillText(noteName(midi), x1 + 8, blockY + blockHeight - 8);
      }

      previous = { end, x: x2, y };
    });
    ctx.restore();
  }

  function drawTargetContourTiles(ctx, visibleContour, xForTime, yForMidi, layout, songTime) {
    if (!Array.isArray(visibleContour) || visibleContour.length === 0) return;
    ctx.save();
    ctx.lineWidth = 1;

    visibleContour.forEach((point, index) => {
      const next = visibleContour[index + 1] || null;
      const start = Number(point.time);
      const midi = Number(point.midi);
      const confidence = clamp(Number(point.confidence ?? 0.6), 0.25, 1);
      if (!Number.isFinite(start) || !Number.isFinite(midi)) return;

      const nextTime = Number(next?.time);
      const gap = Number.isFinite(nextTime) ? nextTime - start : 0;
      const end = gap > 0 && gap <= CONTOUR_TARGET_MAX_GAP_SECONDS ? nextTime : start + 0.14;
      const x1 = Math.max(-48, xForTime(start));
      const x2 = Math.min(layout.width + 48, xForTime(end));
      const width = Math.max(6, x2 - x1);
      const y = clampRoadY(yForMidi(midi), layout);
      const height = clamp(layout.roadHeight * 0.028, 9, 16);
      const isCurrent = songTime >= start && songTime <= end;
      const isDone = songTime > end;

      ctx.globalAlpha = isCurrent ? 1 : isDone ? 0.44 : 0.54 + confidence * 0.28;
      ctx.fillStyle = isCurrent
        ? "rgba(246, 243, 234, 0.96)"
        : isDone
          ? "rgba(18, 199, 156, 0.56)"
          : "rgba(155, 230, 214, 0.78)";
      drawRoundRect(ctx, x1, y - height / 2, width, height, Math.min(7, height / 2));
      ctx.fill();

      if (isCurrent) {
        ctx.globalAlpha = 1;
        ctx.strokeStyle = "rgba(18, 199, 156, 0.94)";
        ctx.lineWidth = 2;
        drawRoundRect(ctx, x1, y - height / 2, width, height, Math.min(7, height / 2));
        ctx.stroke();
        ctx.lineWidth = 1;
      }
    });

    ctx.globalAlpha = 1;
    ctx.restore();
  }

  function drawReferenceVocalContour(ctx, contour, notes, xForTime, yForMidi, layout) {
    const points = contour
      .map((point) => graphReferencePoint(point, notes, contour))
      .filter(Boolean)
      .sort((a, b) => a.songTime - b.songTime);
    if (points.length < 2) return false;

    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";

    for (const pass of [
      { width: 8, color: "rgba(2, 5, 8, 0.72)" },
      { width: 4, color: "rgba(246, 243, 234, 0.92)" },
      { width: 2, color: "rgba(18, 199, 156, 0.96)" },
    ]) {
      ctx.strokeStyle = pass.color;
      ctx.lineWidth = pass.width;
      let started = false;
      let previous = null;
      ctx.beginPath();
      points.forEach((point) => {
        if (previous && point.songTime - previous.songTime > MAX_REFERENCE_SEGMENT_GAP_SECONDS) {
          if (started) ctx.stroke();
          ctx.beginPath();
          started = false;
        }
        const x = xForTime(point.songTime);
        const y = clampRoadY(yForMidi(point.midi), layout);
        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else {
          ctx.lineTo(x, y);
        }
        previous = point;
      });
      if (started) ctx.stroke();
    }

    ctx.restore();
    return true;
  }

  function trailColorForCents(absCents) {
    if (!Number.isFinite(absCents)) return "rgba(255, 216, 124, 0.9)";
    if (absCents <= 40) return "rgba(18, 199, 156, 0.98)";
    if (absCents <= 100) return "rgba(237, 176, 73, 0.98)";
    if (absCents <= 200) return "rgba(244, 132, 76, 0.98)";
    return "rgba(207, 77, 67, 0.98)";
  }

  function drawSingerTrail(ctx, xForTime, yForMidi, layout, minTime, maxTime, notes, contour, songTime) {
    const points = state.history
      .filter(
        (point) =>
          Number.isFinite(point.songTime) &&
          Number.isFinite(point.midi) &&
          point.songTime >= minTime &&
          point.songTime <= maxTime
      )
      .map((point) => graphPitchPoint(point, notes, contour))
      .filter(Boolean)
      .sort((a, b) => a.songTime - b.songTime);
    if (points.length === 0) return;

    ctx.save();
    points.forEach((point) => {
      const age = Math.max(0, songTime - point.songTime);
      const alpha = clamp(1 - age / Math.max(0.5, STAGE_ROAD_TRAIL_SECONDS), 0.14, 0.86);
      const radius = clamp(7 - age * 1.4, 2.5, 7);
      const x = xForTime(point.songTime);
      const y = clampRoadY(yForMidi(point.midi), layout);
      ctx.globalAlpha = alpha;
      ctx.fillStyle = trailColorForCents(point.cents);
      ctx.strokeStyle = "rgba(3, 6, 10, 0.64)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    });
    ctx.globalAlpha = 1;
    ctx.restore();
  }

  function drawStageSongRoad(now, target = null, pitchMidi = null) {
    const canvasState = resizeSongRoadCanvas();
    if (!canvasState) return;
    const { ctx, width, height } = canvasState;
    ctx.clearRect(0, 0, width, height);

    const songTime = songPlaybackTime(now);
    const notes = songGuideNotes();
    const contour = songGuideContour();
    const lookaheadSeconds = songRoadLookaheadSeconds(songTime, notes);
    const hitX = width * STAGE_ROAD_HIT_X;
    const pixelsPerSecond = (width - hitX) / lookaheadSeconds;
    const minTime = songTime - Math.max(STAGE_ROAD_TRAIL_SECONDS, hitX / pixelsPerSecond);
    const maxTime = songTime + lookaheadSeconds;
    const xForTime = (time) => hitX + (time - songTime) * pixelsPerSecond;
    const range = songRoadMidiRange(songTime);
    const span = Math.max(1, range.maxMidi - range.minMidi);
    const layout = songRoadLayout(width, height);
    layout.width = width;
    const yForMidi = (midi) =>
      layout.roadTop + layout.roadHeight - ((midi - range.minMidi) / span) * layout.roadHeight;

    ctx.save();
    const backdrop = ctx.createLinearGradient(0, 0, 0, height);
    backdrop.addColorStop(0, "rgba(3, 6, 10, 0.2)");
    backdrop.addColorStop(0.42, "rgba(3, 6, 10, 0.48)");
    backdrop.addColorStop(0.74, "rgba(3, 6, 10, 0.24)");
    backdrop.addColorStop(1, "rgba(3, 6, 10, 0)");
    ctx.fillStyle = backdrop;
    ctx.fillRect(0, 0, width, height);

    if (selectedMode() !== "song" || (notes.length === 0 && contour.length === 0)) {
      drawRoadMessage(ctx, width, height, state.songGuideLoading ? TEXT.loadingGuide : TEXT.noGuide);
      ctx.restore();
      return;
    }

    for (let i = 0; i <= Math.ceil(lookaheadSeconds) + 2; i++) {
      const x = xForTime(Math.floor(songTime) + i);
      if (x < 0 || x > width) continue;
      ctx.strokeStyle = i % 2 === 0 ? "rgba(246, 243, 234, 0.055)" : "rgba(246, 243, 234, 0.022)";
      ctx.beginPath();
      ctx.moveTo(x, layout.roadTop);
      ctx.lineTo(x, layout.railY + 20);
      ctx.stroke();
    }

    for (let midi = Math.floor(range.minMidi); midi <= Math.ceil(range.maxMidi); midi++) {
      const y = yForMidi(midi);
      const natural = !noteName(midi).includes("#");
      ctx.strokeStyle = natural ? "rgba(246, 243, 234, 0.075)" : "rgba(246, 243, 234, 0.025)";
      ctx.beginPath();
      ctx.moveTo(layout.labelInset, y);
      ctx.lineTo(width, y);
      ctx.stroke();

      if (natural) {
        ctx.fillStyle = "rgba(246, 243, 234, 0.38)";
        ctx.font = "700 12px sans-serif";
        ctx.fillText(noteName(midi), layout.labelInset, y - 5);
      }
    }

    const visibleNotes = visibleRoadNotes(notes, minTime, maxTime);
    const visibleContour = visibleRoadContour(contour, minTime, maxTime);
    if (visibleContour.length > 0) {
      drawTargetContourTiles(ctx, visibleContour, xForTime, yForMidi, layout, songTime);
    } else {
      drawTargetNoteBlocks(ctx, visibleNotes, xForTime, yForMidi, layout, songTime);
    }

    ctx.strokeStyle = "rgba(246, 243, 234, 0.84)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(hitX, layout.roadTop - 8);
    ctx.lineTo(hitX, layout.railY + 24);
    ctx.stroke();
    ctx.lineWidth = 1;

    drawSingerTrail(ctx, xForTime, yForMidi, layout, minTime, maxTime, notes, contour, songTime);

    if (Number.isFinite(pitchMidi)) {
      const livePoint = graphPitchPoint({ songTime, midi: pitchMidi, confidence: 1 }, notes, contour);
      if (livePoint) {
        const y = clampRoadY(yForMidi(livePoint.midi), layout);
        const isHeld = Boolean(state.latestPitchHeld);
        ctx.globalAlpha = isHeld ? 0.54 : 1;
        ctx.fillStyle = trailColorForCents(livePoint.cents);
        ctx.strokeStyle = "rgba(246, 243, 234, 0.98)";
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.arc(hitX, y, isHeld ? 6 : 8, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.globalAlpha = 1;
        ctx.lineWidth = 1;
      }
    } else if (target) {
      const y = yForMidi(target.midi);
      ctx.strokeStyle = "rgba(237, 176, 73, 0.48)";
      ctx.beginPath();
      ctx.arc(hitX, y, 9, 0, Math.PI * 2);
      ctx.stroke();
    }

    drawStageLyricRail(ctx, width, xForTime, songTime, layout.railY, minTime, maxTime, hitX);
    ctx.restore();
  }

  function drawRoadMessage(ctx, width, height, message) {
    ctx.fillStyle = "rgba(246, 243, 234, 0.68)";
    ctx.font = "700 15px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(message, width / 2, height / 2);
    ctx.textAlign = "start";
    ctx.textBaseline = "alphabetic";
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
    let visualPitchMidi = null;
    let centsError = 0;
    let effectiveResult = result;
    if (result.voiced) {
      const detectedPitchMidi = frequencyToMidi(result.frequency);
      const detectedCentsError = target
        ? 1200 * Math.log2(result.frequency / midiToFrequency(target.midi))
        : centsBetweenMidi(detectedPitchMidi, Math.round(detectedPitchMidi));
      const accepted = acceptVisualPitch(detectedPitchMidi, result, target, now);
      if (accepted) {
        pitchMidi = detectedPitchMidi;
        centsError = detectedCentsError;
        visualPitchMidi = detectedPitchMidi;
        state.lastAcceptedPitch = {
          time: now,
          midi: detectedPitchMidi,
          songTime: selectedMode() === "song" ? songPlaybackTime(now) : null,
          confidence: result.confidence,
        };
        state.history.push({
          time: now,
          midi: detectedPitchMidi,
          confidence: result.confidence,
          songTime: selectedMode() === "song" ? songPlaybackTime(now) : null,
        });
      } else {
        visualPitchMidi = heldVisualPitch(now);
        effectiveResult = { ...result, voiced: false, filtered: true };
      }
    } else {
      visualPitchMidi = heldVisualPitch(now);
    }

    if (visualPitchMidi !== null) {
      state.latestPitchMidi = visualPitchMidi;
      state.latestPitchHeld = pitchMidi === null;
    } else {
      state.latestPitchMidi = null;
      state.latestPitchHeld = false;
    }

    updateReadout(effectiveResult, pitchMidi, target, centsError);
    updateMetrics(effectiveResult, pitchMidi, target, centsError, now);
    draw(now, target, pitchMidi);
    drawStageSongRoad(now, target, state.latestPitchMidi);
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
    state.latestPitchMidi = null;
    state.latestPitchHeld = false;
    state.lastAcceptedPitch = null;
    stopSongSync();
    els["coach-start"].textContent = TEXT.start;
    setStatus(TEXT.idle);
    updateReadout({ voiced: false }, null, currentTarget(performance.now()), 0);
    draw(performance.now(), currentTarget(performance.now()), null);
    drawStageSongRoad(performance.now(), currentTarget(performance.now()), null);
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
      drawStageSongRoad(performance.now(), currentTarget(performance.now()), state.latestPitchMidi);
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
    els["coach-reference-toggle"].addEventListener("change", () => {
      state.vocalReferenceEnabled = Boolean(els["coach-reference-toggle"].checked);
      updateVocalReferenceControl();
      if (!state.vocalReferenceEnabled) {
        pauseVocalReferenceAudio();
        return;
      }
      playVocalReferenceAudio();
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
      drawStageSongRoad(performance.now(), currentTarget(performance.now()), state.latestPitchMidi);
    });
    els["coach-range"].addEventListener("change", () => {
      resetSession();
      draw(performance.now(), currentTarget(performance.now()), null);
      drawStageSongRoad(performance.now(), currentTarget(performance.now()), state.latestPitchMidi);
    });
    window.addEventListener("resize", () => {
      draw(performance.now(), currentTarget(performance.now()), null);
      drawStageSongRoad(performance.now(), currentTarget(performance.now()), state.latestPitchMidi);
    });
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
    updateVocalReferenceControl();
    updateReadout({ voiced: false }, null, null, 0);
    draw(performance.now(), null, null);
    drawStageSongRoad(performance.now(), null, null);
    loadInitialNowPlaying();
    startNowPlayingPolling();
  });
})();

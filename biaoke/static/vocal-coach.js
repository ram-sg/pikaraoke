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
  const STAGE_ROAD_MIN_VISIBLE_HEIGHT = 170;
  const STAGE_ROAD_LYRIC_BOTTOM_SAFE_PX = 38;
  const LYRIC_SILENCE_CUE_COUNT = 5;
  const LYRIC_SILENCE_MIN_GAP_SECONDS = 0.25;
  const VOCAL_TIMELINE_MIN_SEGMENT_SECONDS = 0.035;
  const VOCAL_TIMELINE_SHORT_SILENCE_RATE = 0.72;
  const VOCAL_TIMELINE_LONG_SILENCE_RATE = 0.34;
  const VOCAL_TIMELINE_NOTE_RATE = 1.0;
  const VOCAL_TIMELINE_SUSTAIN_RATE = 0.22;
  const VOCAL_TIMELINE_EFFECT_RATE = 0.54;
  const VOCAL_TIMELINE_TEXT_PADDING = 22;
  const VOCAL_TIMELINE_MAX_TEXT_WIDTH = 240;
  const VOCAL_TIMELINE_MAX_DENSE_RATE = 2.85;
  const VOCAL_TIMELINE_CONTOUR_GAP_SECONDS = 0.48;
  const VOCAL_TIMELINE_LYRIC_FONT_SIZE = 23;
  const VOCAL_TIMELINE_LYRIC_MIN_GAP_PX = 9;
  const TRAIL_MIN_CONFIDENCE = 0.52;
  const VISUAL_CURSOR_MIN_CONFIDENCE = 0.25;
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
  const DEFAULT_PITCH_BANDS_CENTS = [25, 40, 60, 80, 100, 130, 160, 200, 250, 320];
  const AUTO_START_MIC_DELAY_MS = 650;
  const SCORE_MIN_TARGET_SECONDS = 1.5;
  const SCORE_SAMPLE_MAX_DELTA_SECONDS = 0.12;
  const SCORE_MIN_CURSOR_CONFIDENCE = VISUAL_CURSOR_MIN_CONFIDENCE;
  const PITCH_BAND_STYLES = [
    { cents: 320, fill: "rgba(207, 77, 67, 0.003)" },
    { cents: 200, fill: "rgba(237, 176, 73, 0.004)" },
    { cents: 100, fill: "rgba(155, 230, 214, 0.006)" },
    { cents: 40, fill: "rgba(18, 199, 156, 0.009)" },
  ];
  const MAX_CENTS_FOR_SCORE = 90;
  const GOOD_CENTS = 35;
  const PLAYBACK_DRIFT_SECONDS = 2;
  const NOW_PLAYING_POLL_MS = 2000;
  const PLAYBACK_START_TIMEOUT_MS = 10000;
  const LYRICS_RETRY_INTERVAL_MS = 1800;
  const LYRICS_RETRY_MAX_ATTEMPTS = 10;
  const GUIDE_RETRY_INTERVAL_MS = 2200;
  const GUIDE_RETRY_MAX_ATTEMPTS = 8;
  const LYRICS_OFFSET_STEP_SECONDS = 0.5;
  const MAX_LYRICS_OFFSET_SECONDS = 120;
  const VOCAL_REFERENCE_VOLUME = 0.48;
  const VOCAL_REFERENCE_SYNC_DRIFT_SECONDS = 0.75;
  const VOCAL_REFERENCE_SYNC_INTERVAL_MS = 850;
  const COACH_DIFFICULTY_STORAGE_KEY = "biaoke-coach-difficulty";
  const FIXED_LYRICS_STORAGE_KEY = "biaoke-coach-fixed-lyrics";
  const VOCAL_SCORE_STORAGE_KEY = "biaoke-coach-score-justo";
  const LYRIC_ROAD_LANE_COUNT = 3;
  const LYRIC_ROAD_LANE_HEIGHT = 42;
  const LYRIC_ROAD_LANE_GAP_SECONDS = 0.18;
  const COACH_DIFFICULTY_PROFILES = {
    festa: {
      fairVocalUnits: true,
      transitionGraceSeconds: 0.22,
      minPitchUnitSeconds: 0.16,
      pitchBandMultiplier: 1.45,
      lightPitchWeight: 0.45,
      lightPitchBandMultiplier: 1.75,
      minVoicedScore: 35,
    },
    treino: {
      fairVocalUnits: true,
      transitionGraceSeconds: 0.14,
      minPitchUnitSeconds: 0.12,
      pitchBandMultiplier: 1,
      lightPitchWeight: 0.68,
      lightPitchBandMultiplier: 1.35,
      minVoicedScore: 0,
    },
    pro: {
      fairVocalUnits: false,
      transitionGraceSeconds: 0.04,
      minPitchUnitSeconds: 0.08,
      pitchBandMultiplier: 0.75,
      lightPitchWeight: 0.9,
      lightPitchBandMultiplier: 1.05,
      minVoicedScore: 0,
    },
  };
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
    songGuideKey: null,
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
    lyricPaintUnits: [],
    lyricVocalUnits: [],
    lyricsHaveKaraokeTiming: false,
    lyricsOffsetSeconds: 0,
    lyricsRetryCount: 0,
    lyricsRetryAfter: 0,
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
    fixedLyricsEnabled: false,
    coachDifficulty: "treino",
    lyricPhrasesCacheKey: null,
    lyricPhrasesCache: null,
    lyricLaneCacheKey: null,
    lyricLaneCache: null,
    lyricVisualCacheKey: null,
    lyricVisualIntervals: null,
    lyricVocalUnitsCacheKey: null,
    lyricVocalUnitsCache: null,
    lyricVocalWordCacheKey: null,
    lyricVocalWordCache: null,
    songMidiRangeCacheKey: null,
    songMidiRangeCache: null,
    guideRetryCount: 0,
    guideRetryAfter: 0,
    score: emptyScore(),
    autoStartAttempted: false,
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
      "coach-player-back",
      "coach-player-pause",
      "coach-player-pause-icon",
      "coach-player-stop",
      "coach-player-repeat",
      "coach-player-forward",
      "coach-settings-toggle",
      "coach-settings-menu",
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
      "coach-fixed-lyrics-toggle",
      "coach-difficulty",
      "coach-score-result",
      "coach-score-close",
      "coach-score-value",
      "coach-score-label",
      "coach-score-pitch",
      "coach-score-coverage",
      "coach-score-hit-rate",
      "coach-score-error",
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

  function emptyScore() {
    return {
      songKey: null,
      lastSampleAt: null,
      targetSeconds: 0,
      voicedSeconds: 0,
      hitSeconds: 0,
      scoreSeconds: 0,
      weightedScore: 0,
      errorSeconds: 0,
      weightedAbsCents: 0,
      sampleCount: 0,
    };
  }

  function hideScoreResult() {
    if (els["coach-score-result"]) els["coach-score-result"].hidden = true;
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
    state.score = emptyScore();
    hideScoreResult();
    updateMetricsDisplay(null);
  }

  function selectedMode() {
    return els["coach-preset"]?.value || "song";
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

  function nowPlayingSongKey(np = state.nowPlaying) {
    const current = np || {};
    return [
      current.now_playing_url || "",
      current.now_playing || "",
      current.now_playing_duration || "",
    ].join("|");
  }

  function clearLyricRenderCaches() {
    state.lyricPhrasesCacheKey = null;
    state.lyricPhrasesCache = null;
    state.lyricLaneCacheKey = null;
    state.lyricLaneCache = null;
    state.lyricVisualCacheKey = null;
    state.lyricVisualIntervals = null;
    state.lyricVocalUnitsCacheKey = null;
    state.lyricVocalUnitsCache = null;
    state.lyricVocalWordCacheKey = null;
    state.lyricVocalWordCache = null;
    state.songMidiRangeCacheKey = null;
    state.songMidiRangeCache = null;
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

  function loadFixedLyricsPreference() {
    try {
      state.fixedLyricsEnabled = localStorage.getItem(FIXED_LYRICS_STORAGE_KEY) === "1";
    } catch (_error) {
      state.fixedLyricsEnabled = false;
    }
  }

  function persistFixedLyricsPreference() {
    try {
      localStorage.setItem(FIXED_LYRICS_STORAGE_KEY, state.fixedLyricsEnabled ? "1" : "0");
    } catch (_error) {}
  }

  function updateFixedLyricsControl() {
    const toggle = els["coach-fixed-lyrics-toggle"];
    if (toggle) toggle.checked = Boolean(state.fixedLyricsEnabled);
    els["coach-video-container"]?.classList.toggle("has-fixed-lyrics", Boolean(state.fixedLyricsEnabled));
  }

  function currentDifficultyProfile() {
    return COACH_DIFFICULTY_PROFILES[state.coachDifficulty] || COACH_DIFFICULTY_PROFILES.treino;
  }

  function normalizeCoachDifficulty(value) {
    const key = String(value || "").trim().toLowerCase();
    return COACH_DIFFICULTY_PROFILES[key] ? key : "treino";
  }

  function loadCoachDifficultyPreference() {
    try {
      const stored = localStorage.getItem(COACH_DIFFICULTY_STORAGE_KEY);
      if (stored) {
        state.coachDifficulty = normalizeCoachDifficulty(stored);
        return;
      }
      const legacyScoreJusto = localStorage.getItem(VOCAL_SCORE_STORAGE_KEY);
      state.coachDifficulty = legacyScoreJusto === "0" ? "pro" : "treino";
    } catch (_error) {
      state.coachDifficulty = "treino";
    }
  }

  function persistCoachDifficultyPreference() {
    try {
      localStorage.setItem(COACH_DIFFICULTY_STORAGE_KEY, normalizeCoachDifficulty(state.coachDifficulty));
    } catch (_error) {}
  }

  function updateCoachDifficultyControl() {
    const select = els["coach-difficulty"];
    if (select) select.value = normalizeCoachDifficulty(state.coachDifficulty);
    els["coach-video-container"]?.setAttribute("data-difficulty", normalizeCoachDifficulty(state.coachDifficulty));
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
    const scorePolicy = vocalScorePolicyAtSongTime(songTime);

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
      scorePolicy,
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

    if (
      target &&
      targetDelta > VISUAL_TARGET_REJECT_CENTS &&
      result.confidence < 0.58 &&
      previousAge > VISUAL_PITCH_HOLD_MS
    ) {
      return false;
    }
    if (previousAge <= VISUAL_PITCH_HOLD_MS && stepDelta > VISUAL_STEP_REJECT_CENTS && result.confidence < 0.88) {
      return false;
    }
    return true;
  }

  function canShowVisualPitch(pitchMidi, result) {
    return (
      Number.isFinite(pitchMidi) &&
      pitchMidi >= VISUAL_MIN_MIDI &&
      pitchMidi <= VISUAL_MAX_MIDI &&
      result &&
      Number(result.confidence || 0) >= VISUAL_CURSOR_MIN_CONFIDENCE
    );
  }

  function pushSingerHistoryPoint(now, midi, result) {
    state.history.push({
      time: now,
      midi,
      confidence: Number(result?.confidence ?? 1),
      songTime: selectedMode() === "song" ? songPlaybackTime(now) : null,
    });
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

  function renderLyricLine(container, line, time, lineIndex = null) {
    container.replaceChildren();
    if (!line) return;
    const hasPreciseTiming =
      state.lyricsHaveKaraokeTiming && (line.has_karaoke_timing !== false);
    const segments =
      lyricPaintSegmentsForLine(lineIndex) ||
      (hasPreciseTiming && line.segments?.length
        ? line.segments
        : [{ text: line.text, start: line.start, end: line.end }]);
    for (const segment of segments) {
      const token = document.createElement("span");
      token.className = "coach-lyric-token";
      token.textContent = segment.text;
      if (time >= segment.end) {
        token.classList.add("is-done");
      } else if (time >= segment.start && time < segment.end) {
        const progress = lyricUnitPaintRatio(segment, time);
        token.classList.add("is-active");
        token.style.setProperty("--token-progress", `${Math.round(progress * 100)}%`);
      }
      container.appendChild(token);
    }
  }

  function lyricPaintSegmentsForLine(lineIndex) {
    if (!Number.isFinite(Number(lineIndex))) return null;
    const offset = Number(state.lyricsOffsetSeconds || 0);
    const segments = normalizedLyricPaintUnits()
      .filter((unit) => unit.unitType !== "line" && Number(unit.lineIndex) === Number(lineIndex))
      .map((unit, index, units) => {
        const subUnits = lyricVocalSubUnitsForWord(unit.lineIndex, unit.segmentIndex, unit.start, unit.end);
        const effectiveTiming = lyricSegmentTimingFromSubUnits(unit.start, unit.end, subUnits);
        return {
          text: `${unit.text}${unit.unitType === "word" && index < units.length - 1 ? " " : ""}`,
          start: effectiveTiming.start - offset,
          end: effectiveTiming.end - offset,
          subUnits: subUnits.map((subUnit) => ({
            ...subUnit,
            start: subUnit.start - offset,
            end: subUnit.end - offset,
          })),
        };
      });
    return segments.length ? segments : null;
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

  function resetLoadRetries() {
    state.lyricsRetryCount = 0;
    state.lyricsRetryAfter = 0;
    state.guideRetryCount = 0;
    state.guideRetryAfter = 0;
  }

  function scheduleLyricsRetry() {
    if (state.lyrics.length > 0) {
      state.lyricsRetryCount = 0;
      state.lyricsRetryAfter = 0;
      return;
    }
    state.lyricsRetryCount = Math.min(state.lyricsRetryCount + 1, LYRICS_RETRY_MAX_ATTEMPTS);
    state.lyricsRetryAfter = performance.now() + LYRICS_RETRY_INTERVAL_MS;
  }

  function shouldRetryLyricsLoad() {
    return Boolean(state.nowPlaying.now_playing)
      && state.lyrics.length === 0
      && state.lyricsRetryCount < LYRICS_RETRY_MAX_ATTEMPTS
      && performance.now() >= Number(state.lyricsRetryAfter || 0);
  }

  function scheduleGuideRetry() {
    if (state.songGuide) {
      state.guideRetryCount = 0;
      state.guideRetryAfter = 0;
      return;
    }
    state.guideRetryCount = Math.min(state.guideRetryCount + 1, GUIDE_RETRY_MAX_ATTEMPTS);
    state.guideRetryAfter = performance.now() + GUIDE_RETRY_INTERVAL_MS;
  }

  function shouldRetryGuideLoad() {
    return selectedMode() === "song"
      && Boolean(state.nowPlaying.now_playing)
      && !state.songGuide
      && !state.songGuideLoading
      && state.guideRetryCount < GUIDE_RETRY_MAX_ATTEMPTS
      && performance.now() >= Number(state.guideRetryAfter || 0);
  }

  function setSettingsMenuOpen(open) {
    const menu = els["coach-settings-menu"];
    const toggle = els["coach-settings-toggle"];
    if (!menu || !toggle) return;
    menu.hidden = !open;
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function updateHeaderMarquees() {
    window.requestAnimationFrame(() => {
      document.querySelectorAll(".coach-marquee").forEach((marquee) => {
        const text = marquee.querySelector(".coach-marquee-text");
        if (!text) return;
        marquee.classList.remove("is-overflowing");
        marquee.style.removeProperty("--marquee-distance");
        marquee.style.removeProperty("--marquee-duration");
        if ((text.textContent || "").trim() === "--") return;
        const distance = Math.ceil(text.scrollWidth - marquee.clientWidth);
        if (distance <= 8) return;
        marquee.style.setProperty("--marquee-distance", `${distance + 42}px`);
        marquee.style.setProperty(
          "--marquee-duration",
          `${clamp((distance + marquee.clientWidth) / 42, 12, 30).toFixed(1)}s`
        );
        marquee.classList.add("is-overflowing");
      });
    });
  }

  function updatePlayerControls() {
    const hasSong = Boolean(state.nowPlaying?.now_playing);
    [
      "coach-player-back",
      "coach-player-pause",
      "coach-player-stop",
      "coach-player-repeat",
      "coach-player-forward",
    ].forEach((id) => {
      if (els[id]) els[id].disabled = !hasSong;
    });

    const pauseIcon = els["coach-player-pause-icon"];
    if (!pauseIcon) return;
    pauseIcon.classList.toggle("icon-pause", !state.nowPlaying?.is_paused);
    pauseIcon.classList.toggle("icon-play", Boolean(state.nowPlaying?.is_paused));
  }

  async function sendPlayerCommand(path) {
    try {
      const response = await fetch(path, {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`Player command failed: ${response.status}`);
      const payload = await readJsonResponse(response);
      if (payload && payload.state) {
        await handleNowPlayingUpdate(payload.state);
      }
    } catch (error) {
      console.log("Could not send player command", error);
    } finally {
      updatePlayerControls();
    }
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
    clearLyricRenderCaches();
    updateLyrics(getVideoPlayer().currentTime || 0);
    persistLyricsOffset();
  }

  async function loadLyrics(subtitleUrl) {
    state.lyrics = [];
    state.lyricPaintUnits = [];
    state.lyricVocalUnits = [];
    state.lyricsHaveKaraokeTiming = false;
    state.activeLyricIndex = -1;
    state.currentSubtitleUrl = subtitleUrl || null;
    clearLyricRenderCaches();
    els["coach-lyrics-current"].replaceChildren();
    els["coach-lyrics-next"].textContent = "";

    if (CONFIG.lyricsUrl) {
      const loadedFromGuide = await loadLyricsGuide();
      if (loadedFromGuide || !subtitleUrl) return state.lyrics.length > 0;
    }

    if (!subtitleUrl) {
      state.lastLoadedSubtitleUrl = null;
      setLyricsStatus(TEXT.noLyrics, "is-warning");
      return false;
    }
    if (state.lastLoadedSubtitleUrl === subtitleUrl && state.lyrics.length > 0) return true;

    state.lastLoadedSubtitleUrl = subtitleUrl;
    setLyricsStatus(TEXT.loadingLyrics, "is-warning");
    try {
      const response = await fetch(subtitleUrl, { cache: "no-store" });
      if (!response.ok) throw new Error(`Subtitle request failed: ${response.status}`);
      const content = await response.text();
      state.lyrics = parseAssLyrics(content);
      state.lyricPaintUnits = [];
      state.lyricVocalUnits = [];
      state.lyricsHaveKaraokeTiming = hasKaraokeTimingText(content);
      state.activeLyricIndex = -1;
      clearLyricRenderCaches();
      if (state.lyrics.length === 0) {
        setLyricsStatus(TEXT.noLyrics, "is-warning");
        return false;
      }
      setLyricsStatus(TEXT.lyricsReady, "is-ready");
      return true;
    } catch (error) {
      console.log("Could not load lyrics", error);
      state.lyrics = [];
      state.lyricPaintUnits = [];
      state.lyricVocalUnits = [];
      state.lyricsHaveKaraokeTiming = false;
      state.activeLyricIndex = -1;
      clearLyricRenderCaches();
      setLyricsStatus(TEXT.lyricsError, "is-danger");
      return false;
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
        setLyricsStatus(TEXT.loadingLyrics, "is-warning");
        return true;
      }
      if (qualityMessages.includes("lyrics_duration_mismatch")) {
        state.lyrics = [];
        state.lyricPaintUnits = [];
        state.lyricVocalUnits = [];
        state.lyricsHaveKaraokeTiming = false;
        state.activeLyricIndex = -1;
        clearLyricRenderCaches();
        setLyricsStatus(TEXT.lyricsMismatch, "is-danger");
        return true;
      }
      if (guide.status !== "ready" || !Array.isArray(guide.lines) || guide.lines.length === 0) {
        state.lyrics = [];
        state.lyricPaintUnits = [];
        state.lyricVocalUnits = [];
        state.lyricsHaveKaraokeTiming = false;
        state.activeLyricIndex = -1;
        clearLyricRenderCaches();
        setLyricsStatus(guide.message || TEXT.noLyrics, guide.status === "error" ? "is-danger" : "is-warning");
        return true;
      }
      state.lyrics = guide.lines;
      state.lyricPaintUnits = Array.isArray(guide.alignment?.paint_units)
        ? guide.alignment.paint_units
        : [];
      state.lyricVocalUnits = Array.isArray(guide.vocal_units) ? guide.vocal_units : [];
      state.lyricsHaveKaraokeTiming = Boolean(guide.has_karaoke_timing);
      state.activeLyricIndex = -1;
      clearLyricRenderCaches();
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
        renderLyricLine(els["coach-lyrics-current"], firstLine, firstLine.start, 0);
        els["coach-lyrics-next"].textContent = state.lyrics[1]?.text || "";
        state.activeLyricIndex = 0;
        return;
      }
      if (lastLine && lyricTime > lastLine.end) {
        setLyricsStatus(TEXT.lyricsReady, "is-ready");
        renderLyricLine(els["coach-lyrics-current"], lastLine, lastLine.end, state.lyrics.length - 1);
        els["coach-lyrics-next"].textContent = "";
        state.activeLyricIndex = state.lyrics.length - 1;
        return;
      }
      activeIndex = state.lyrics.findIndex((line) => line.start > lyricTime);
      if (activeIndex >= 0) {
        setLyricsStatus(TEXT.lyricsReady, "is-ready");
        renderLyricLine(
          els["coach-lyrics-current"],
          state.lyrics[activeIndex],
          state.lyrics[activeIndex].start,
          activeIndex,
        );
        els["coach-lyrics-next"].textContent = state.lyrics[activeIndex + 1]?.text || "";
        state.activeLyricIndex = activeIndex;
      }
      return;
    }

    const active = state.lyrics[activeIndex];
    setLyricsStatus(TEXT.lyricsReady, "is-ready");
    renderLyricLine(els["coach-lyrics-current"], active, lyricTime, activeIndex);
    els["coach-lyrics-next"].textContent = state.lyrics[activeIndex + 1]?.text || "";
    state.activeLyricIndex = activeIndex;
  }

  async function readNowPlaying() {
    const response = await fetch(CONFIG.nowPlayingUrl || "/now_playing", { cache: "no-store" });
    if (!response.ok) return {};
    return readJsonResponse(response);
  }

  function updateSongChrome(np) {
    const nowTitle = np.now_playing_title || np.now_playing || "--";
    const nextTitle = np.up_next_title || np.up_next || "--";
    if (np.now_playing) {
      setText("coach-now-playing-song", nowTitle);
      setText("coach-now-playing-singer", np.now_playing_user || "--");
      setText("coach-idle-subtitle", "");
    } else {
      setText("coach-now-playing-song", "--");
      setText("coach-now-playing-singer", "--");
      setText("coach-idle-subtitle", TEXT.idleSong);
    }

    if (np.up_next) {
      els["coach-up-next"].classList.add("is-visible");
      els["coach-up-next"].classList.remove("is-empty");
      setText("coach-up-next-song", nextTitle);
      setText("coach-up-next-singer", np.next_user || "--");
    } else {
      els["coach-up-next"].classList.remove("is-visible");
      els["coach-up-next"].classList.add("is-empty");
      setText("coach-up-next-song", "--");
      setText("coach-up-next-singer", "--");
    }

    const duration = Number(np.now_playing_duration || 0);
    setText("coach-duration", duration > 0 ? `/${formatDuration(duration)}` : "/00:00");
    updatePlayerControls();
    updateHeaderMarquees();
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
    const previousSongKey = nowPlayingSongKey(state.nowPlaying);
    const nextNowPlaying = np || {};
    const nextSongKey = nowPlayingSongKey(nextNowPlaying);
    const songChanged = Boolean(nextNowPlaying.now_playing) && nextSongKey !== previousSongKey;
    state.nowPlaying = nextNowPlaying;
    if (songChanged) {
      resetLoadRetries();
      resetSession();
    }
    updateSongChrome(state.nowPlaying);

    if (!state.nowPlaying.now_playing) {
      resetLoadRetries();
      clearVideo();
      state.songGuide = null;
      state.songGuideKey = null;
      state.songSync = null;
      setVocalReferenceAvailable(false);
      await loadLyrics(null);
      return;
    }

    const subtitleUrl = state.nowPlaying.now_playing_subtitle_url || null;
    const lyricsKey = `${state.nowPlaying.now_playing || ""}:${subtitleUrl || ""}`;
    if (lyricsKey !== state.currentLyricsKey || shouldRetryLyricsLoad()) {
      state.currentLyricsKey = lyricsKey;
      const loadedLyrics = await loadLyrics(subtitleUrl);
      if (loadedLyrics) {
        state.lyricsRetryCount = 0;
        state.lyricsRetryAfter = 0;
      } else {
        scheduleLyricsRetry();
      }
    }

    const songKey = nowPlayingSongKey(state.nowPlaying);
    if (
      selectedMode() === "song"
      && !state.songGuideLoading
      && (state.songGuideKey !== songKey || shouldRetryGuideLoad())
    ) {
      state.songGuide = null;
      state.songGuideKey = null;
      state.songSync = null;
      setVocalReferenceAvailable(false);
      loadSongGuide(true).then((guide) => {
        if (guide) {
          state.guideRetryCount = 0;
          state.guideRetryAfter = 0;
        } else {
          scheduleGuideRetry();
        }
      });
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
    if (latest.now_playing && shouldRetryLyricsLoad()) return true;
    if (latest.now_playing && shouldRetryGuideLoad()) return true;
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
    showScoreResult(reason);
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
    const current = songPlaybackTime(now);
    setText("coach-current", formatDuration(current));
    if (duration > 0) {
      setText("coach-duration", `/${formatDuration(duration)}`);
      els["coach-song-progress-fill"].style.width = `${clamp((current / duration) * 100, 0, 100)}%`;
    } else {
      els["coach-song-progress-fill"].style.width = "0%";
    }
    updateLyrics(current);
    syncVocalReferenceToMain(false);
    drawStageSongRoad(now, currentTarget(now), state.latestPitchMidi, current);
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
      state.nowPlaying.is_paused = true;
      updatePlayerControls();
      getVideoPlayer().pause();
      pauseVocalReferenceAudio();
    });
    state.socket.on("play", () => {
      state.nowPlaying.is_paused = false;
      updatePlayerControls();
      playCurrentVideo();
    });
    state.socket.on("skip", () => {
      resetSession();
      clearVideo();
      state.nowPlaying = {};
      updatePlayerControls();
    });
    state.socket.on("restart", () => {
      const video = getVideoPlayer();
      video.currentTime = 0;
      state.nowPlaying.is_paused = false;
      state.nowPlaying.now_playing_position = 0;
      updatePlayerControls();
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
        state.songGuideKey = null;
        state.songSync = null;
        setVocalReferenceAvailable(false);
        setStatus(guide.message || TEXT.noGuide, guide.status === "idle" ? "" : "is-warning");
        return null;
      }

      state.songGuide = guide;
      state.songGuideKey = nowPlayingSongKey();
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
      state.songGuideKey = null;
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
    const referenceMelody =
      raw.reference_melody && typeof raw.reference_melody === "object" ? raw.reference_melody : {};
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
      reference_melody: referenceMelody,
      vocal_reference_available: Boolean(raw.vocal_reference_available || assets.original_audio_path),
      assets,
      notes,
      contour,
    };
  }

  function normalizeGuideNotes(raw) {
    const directNotes = Array.isArray(raw?.reference_melody?.notes)
      ? raw.reference_melody.notes
      : Array.isArray(raw?.notes)
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
    const source = Array.isArray(raw?.reference_melody?.contour)
      ? raw.reference_melody.contour
      : Array.isArray(raw?.contour)
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

  function scoreForCents(centsError, target, policy = null) {
    const note = target?.songTime !== undefined ? targetNoteAtSongTime(target.songTime, songGuideNotes(), 0.35) : null;
    const multiplier = Math.max(0.1, Number(policy?.bandMultiplier || 1));
    const bands = normalizePitchBands(note?.pitchBandsCents).map((band) => band * multiplier);
    const cents = Math.abs(Number(centsError));
    if (!Number.isFinite(cents)) return 0;
    for (let index = 0; index < bands.length; index++) {
      if (cents <= bands[index]) return Math.max(0, 100 - index * 10);
    }
    return 0;
  }

  function updateGameScore(result, pitchMidi, pitchHeld, target, now) {
    if (selectedMode() !== "song") return;
    const video = getVideoPlayer();
    if (!target || !state.currentVideoUrl || !video || video.paused || video.ended) {
      state.score.lastSampleAt = null;
      return;
    }
    const policy = target.scorePolicy || vocalScorePolicyAtSongTime(target.songTime);
    if (policy.hasUnits && !policy.pitchScore) {
      state.score.lastSampleAt = now;
      return;
    }

    const songKey = nowPlayingSongKey(state.nowPlaying);
    if (state.score.songKey && state.score.songKey !== songKey) {
      state.score = emptyScore();
      hideScoreResult();
    }
    if (!state.score.songKey) state.score.songKey = songKey;

    let deltaSeconds = state.score.lastSampleAt ? (now - state.score.lastSampleAt) / 1000 : 1 / 60;
    state.score.lastSampleAt = now;
    if (!Number.isFinite(deltaSeconds) || deltaSeconds <= 0) return;
    deltaSeconds = clamp(deltaSeconds, 1 / 120, SCORE_SAMPLE_MAX_DELTA_SECONDS);
    const weight = Math.max(0, Number(policy.weight || 1));
    if (weight <= 0) return;
    const weightedDelta = deltaSeconds * weight;

    state.score.targetSeconds += weightedDelta;
    state.score.sampleCount += 1;

    const voiced =
      result?.voiced &&
      !pitchHeld &&
      Number.isFinite(pitchMidi) &&
      Number(result.confidence || 0) >= SCORE_MIN_CURSOR_CONFIDENCE;
    if (!voiced) {
      state.score.scoreSeconds += weightedDelta;
      return;
    }

    const centsError = Math.abs(centsBetweenMidi(pitchMidi, target.midi));
    const sampleScore = Math.max(Number(policy.minVoicedScore || 0), scoreForCents(centsError, target, policy));
    state.score.voicedSeconds += weightedDelta;
    state.score.scoreSeconds += weightedDelta;
    state.score.weightedScore += sampleScore * weightedDelta;
    state.score.errorSeconds += weightedDelta;
    state.score.weightedAbsCents += centsError * weightedDelta;
    if (sampleScore >= 80) state.score.hitSeconds += weightedDelta;
  }

  function finalScoreSummary() {
    const score = state.score || emptyScore();
    if (score.targetSeconds < SCORE_MIN_TARGET_SECONDS) {
      return {
        available: false,
        value: null,
        label: "Sem dados suficientes",
        pitch: null,
        coverage: null,
        hitRate: null,
        avgError: null,
      };
    }

    const value = clamp(score.weightedScore / Math.max(0.001, score.targetSeconds), 0, 100);
    const pitch = score.voicedSeconds > 0 ? clamp(score.weightedScore / score.voicedSeconds, 0, 100) : 0;
    const coverage = clamp((100 * score.voicedSeconds) / score.targetSeconds, 0, 100);
    const hitRate = clamp((100 * score.hitSeconds) / score.targetSeconds, 0, 100);
    const avgError = score.errorSeconds > 0 ? score.weightedAbsCents / score.errorSeconds : null;
    return {
      available: true,
      value,
      label: scoreLabel(value),
      pitch,
      coverage,
      hitRate,
      avgError,
    };
  }

  function scoreLabel(value) {
    if (value >= 92) return "Excelente";
    if (value >= 82) return "Muito bom";
    if (value >= 68) return "Bom";
    if (value >= 50) return "Quase";
    return "Precisa treinar";
  }

  function formatScorePercent(value) {
    return value === null || value === undefined || Number.isNaN(value) ? "--" : `${Math.round(value)}%`;
  }

  function showScoreResult(reason = "complete") {
    if (reason !== "complete" || !els["coach-score-result"]) return;
    const summary = finalScoreSummary();
    els["coach-score-result"].hidden = false;
    els["coach-score-value"].textContent = summary.available ? String(Math.round(summary.value)) : "--";
    els["coach-score-label"].textContent = summary.label;
    els["coach-score-pitch"].textContent = formatScorePercent(summary.pitch);
    els["coach-score-coverage"].textContent = formatScorePercent(summary.coverage);
    els["coach-score-hit-rate"].textContent = formatScorePercent(summary.hitRate);
    els["coach-score-error"].textContent =
      summary.avgError === null || Number.isNaN(summary.avgError) ? "--" : `${Math.round(summary.avgError)}c`;
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
      const policy = target.scorePolicy || vocalScorePolicyAtSongTime(target.songTime);
      if (policy.hasUnits && !policy.pitchScore) {
        const label = policy.kind === "transition" ? "Transição" : policy.kind === "silent" ? "Pausa vocal" : "Timing";
        els["coach-target-state"].textContent = `${label} ${formatClock(target.songTime || 0)}`;
      } else if (String(target.source || "").startsWith("song")) {
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
    const policy = target ? target.scorePolicy || vocalScorePolicyAtSongTime(target.songTime) : null;
    const scoreableTarget = Boolean(target && (!policy?.hasUnits || policy.pitchScore));
    if (scoreableTarget) {
      state.metrics.targetFrames++;
      if (active) {
        state.metrics.voicedFrames++;
        if (Math.abs(centsError) <= GOOD_CENTS) state.metrics.accurateFrames++;
      }
      updateSegment(target, active, centsError, now);
    }

    if (active && scoreableTarget) {
      state.recentErrors.push(centsError);
      if (state.recentErrors.length > 75) state.recentErrors.shift();
    }

    updateMetricsDisplay(scoreableTarget ? target : null);
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

  function songRoadMidiRange(songTime, minTime = null, maxTime = null) {
    const stableRange = stableSongMidiRange();
    if (stableRange) return stableRange;

    const notes = songGuideNotes();
    const contour = songGuideContour();
    const windowMinTime = Number.isFinite(minTime) ? minTime : songTime - 4;
    const windowMaxTime = Number.isFinite(maxTime) ? maxTime : songTime + songRoadLookaheadSeconds(songTime, notes);
    const visibleNotes = visibleRoadNotes(notes, windowMinTime, windowMaxTime);
    const midiValues = [];
    visibleNotes.forEach((note) => {
      const midi = Number(note.midi);
      if (!Number.isFinite(midi)) return;
      const outerBand = Math.max(...normalizePitchBands(note.pitchBandsCents)) / 100;
      midiValues.push(midi - outerBand, midi, midi + outerBand);
    });
    visibleRoadContour(contour, windowMinTime, windowMaxTime).forEach((point) => {
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

  function stableSongMidiRange() {
    const notes = songGuideNotes();
    const contour = songGuideContour();
    const cacheKey = [
      state.songGuideKey || state.songGuide?.title || "",
      notes.length,
      contour.length,
      notes[0]?.start ?? "",
      notes[notes.length - 1]?.end ?? "",
    ].join("|");
    if (state.songMidiRangeCacheKey === cacheKey && state.songMidiRangeCache) return state.songMidiRangeCache;

    const midiValues = [];
    notes.forEach((note) => {
      const midi = Number(note.midi);
      if (!Number.isFinite(midi)) return;
      const outerBand = Math.max(...normalizePitchBands(note.pitchBandsCents)) / 100;
      midiValues.push(midi - outerBand, midi, midi + outerBand);
    });
    contour.forEach((point) => {
      const midi = Number(point.midi);
      const confidence = Number(point.confidence ?? 1);
      if (Number.isFinite(midi) && confidence >= REFERENCE_CONTOUR_MIN_CONFIDENCE) {
        midiValues.push(midi - 0.4, midi, midi + 0.4);
      }
    });

    if (!midiValues.length) return null;
    midiValues.sort((a, b) => a - b);
    const lowIndex = Math.floor((midiValues.length - 1) * 0.03);
    const highIndex = Math.ceil((midiValues.length - 1) * 0.97);
    let minMidi = Math.floor(midiValues[lowIndex]) - 2;
    let maxMidi = Math.ceil(midiValues[highIndex]) + 2;
    const span = maxMidi - minMidi;
    if (span < 14) {
      const pad = (14 - span) / 2;
      minMidi -= pad;
      maxMidi += pad;
    }
    const range = { minMidi, maxMidi };
    state.songMidiRangeCacheKey = cacheKey;
    state.songMidiRangeCache = range;
    return range;
  }

  function songGuideNotes() {
    return Array.isArray(state.songGuide?.notes) ? state.songGuide.notes : [];
  }

  function songGuideContour() {
    return Array.isArray(state.songGuide?.contour) ? state.songGuide.contour : [];
  }

  function songRoadLookaheadSeconds(songTime, notes = songGuideNotes()) {
    return STAGE_ROAD_LOOKAHEAD_SECONDS;
  }

  function songRoadLayout(width, height) {
    const roadTop = clamp(height * 0.08, 48, 96);
    const lyricReserve =
      LYRIC_ROAD_LANE_HEIGHT * Math.max(0, LYRIC_ROAD_LANE_COUNT - 1) + STAGE_ROAD_LYRIC_BOTTOM_SAFE_PX + 34;
    const roadMinHeight = clamp(height * 0.48, STAGE_ROAD_MIN_VISIBLE_HEIGHT, STAGE_ROAD_MIN_HEIGHT);
    const railMin = Math.min(height - lyricReserve, roadTop + Math.min(roadMinHeight, height * 0.52));
    const railMax = Math.max(railMin, height - lyricReserve);
    const railY = clamp(height * 0.72, railMin, railMax);
    const roadBottom = Math.max(roadTop + roadMinHeight, railY - 24);
    const labelInset = clamp(width * 0.018, 16, 32);
    return {
      roadTop,
      roadBottom,
      roadHeight: Math.max(roadMinHeight, roadBottom - roadTop),
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

  function normalizedLyricPaintUnits() {
    const offset = Number(state.lyricsOffsetSeconds || 0);
    if (!Array.isArray(state.lyricPaintUnits) || state.lyricPaintUnits.length === 0) return [];
    return state.lyricPaintUnits
      .map((unit, unitIndex) => {
        const start = Number(unit.start) + offset;
        const end = Number(unit.end) + offset;
        const text = String(unit.text || "").trim();
        if (!text || !Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
        return {
          start,
          end,
          text,
          lineIndex: Number(unit.line_index ?? 0),
          segmentIndex: Number(unit.unit_index ?? unitIndex),
          precision: String(unit.precision || unit.unit_type || "alignment"),
          unitType: String(unit.unit_type || "unit").toLowerCase(),
        };
      })
      .filter(Boolean)
      .sort((a, b) => a.start - b.start || a.lineIndex - b.lineIndex || a.segmentIndex - b.segmentIndex);
  }

  function normalizedLyricVocalUnits() {
    const offset = Number(state.lyricsOffsetSeconds || 0);
    if (!Array.isArray(state.lyricVocalUnits) || state.lyricVocalUnits.length === 0) return [];
    const cacheKey = lyricVocalUnitsCacheKey();
    if (state.lyricVocalUnitsCacheKey === cacheKey && state.lyricVocalUnitsCache) return state.lyricVocalUnitsCache;
    const units = [];
    state.lyricVocalUnits.forEach((wordUnit, wordIndex) => {
      if (!wordUnit || !Array.isArray(wordUnit.sub_units)) return;
      const lineIndex = Number(wordUnit.line_index ?? 0);
      const segmentIndex = Number(wordUnit.unit_index ?? wordIndex);
      const wordText = String(wordUnit.text || "").trim();
      wordUnit.sub_units.forEach((subUnit, subIndex) => {
        const start = Number(subUnit.start) + offset;
        const end = Number(subUnit.end) + offset;
        const text = String(subUnit.text || subUnit.display_text || "").trim();
        if (!text || !Number.isFinite(start) || !Number.isFinite(end) || end <= start) return;
        units.push({
          start,
          end,
          text,
          displayText: String(subUnit.display_text || text).trim(),
          wordText,
          lineIndex,
          segmentIndex,
          subIndex: Number(subUnit.sub_index ?? subIndex),
          charStart: Number(subUnit.char_start),
          charEnd: Number(subUnit.char_end),
          type: String(subUnit.type || "sub_unit"),
          score: String(subUnit.score || "paint_only"),
          sustain: Boolean(subUnit.sustain),
          duration: Number(subUnit.duration || end - start),
          noteCount: Number(subUnit.note_count || 0),
        });
      });
    });
    const sortedUnits = units.sort(
      (a, b) =>
        a.start - b.start ||
        a.lineIndex - b.lineIndex ||
        a.segmentIndex - b.segmentIndex ||
        a.subIndex - b.subIndex,
    );
    state.lyricVocalUnitsCacheKey = cacheKey;
    state.lyricVocalUnitsCache = sortedUnits;
    return sortedUnits;
  }

  function lyricVocalUnitsCacheKey() {
    return [
      state.currentLyricsKey || state.currentSubtitleUrl || state.nowPlaying.now_playing_url || "",
      state.lyricVocalUnits.length,
      Number(state.lyricsOffsetSeconds || 0).toFixed(3),
    ].join("|");
  }

  function lyricVocalSubUnitsByWordKey() {
    const cacheKey = lyricVocalUnitsCacheKey();
    if (state.lyricVocalWordCacheKey === cacheKey && state.lyricVocalWordCache) return state.lyricVocalWordCache;
    const map = new Map();
    normalizedLyricVocalUnits().forEach((unit) => {
      const key = `${unit.lineIndex}:${unit.segmentIndex}`;
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(unit);
    });
    state.lyricVocalWordCacheKey = cacheKey;
    state.lyricVocalWordCache = map;
    return map;
  }

  function lyricVocalSubUnitsForWord(lineIndex, segmentIndex, start, end) {
    const safeLineIndex = Number(lineIndex);
    const safeSegmentIndex = Number(segmentIndex);
    const units = lyricVocalSubUnitsByWordKey().get(`${safeLineIndex}:${safeSegmentIndex}`) || [];
    return units.filter((unit) => unit.end > start - 0.05 && unit.start < end + 0.5);
  }

  function lyricSegmentTimingFromSubUnits(start, end, subUnits) {
    const starts = [Number(start)];
    const ends = [Number(end)];
    if (Array.isArray(subUnits)) {
      subUnits.forEach((unit) => {
        const unitStart = Number(unit.start);
        const unitEnd = Number(unit.end);
        if (Number.isFinite(unitStart)) starts.push(unitStart);
        if (Number.isFinite(unitEnd)) ends.push(unitEnd);
      });
    }
    return {
      start: Math.min(...starts.filter(Number.isFinite)),
      end: Math.max(...ends.filter(Number.isFinite)),
    };
  }

  function visibleLyricVocalSubUnits(minTime, maxTime) {
    return normalizedLyricVocalUnits().filter((unit) => {
      if (unit.end < minTime || unit.start > maxTime) return false;
      if (unit.sustain) return true;
      return ["vowel_sustain", "sonorant_sustain", "fricative_effect"].includes(unit.type) && unit.duration >= 0.22;
    });
  }

  function isPitchScoreVocalUnit(unit) {
    const score = String(unit?.score || "").toLowerCase();
    return score === "pitch_timing" || score === "light_pitch_timing";
  }

  function isLightPitchVocalUnit(unit) {
    return String(unit?.score || "").toLowerCase() === "light_pitch_timing";
  }

  function vocalScorePolicyAtSongTime(songTime) {
    const time = Number(songTime);
    const units = normalizedLyricVocalUnits();
    const profile = currentDifficultyProfile();
    if (!profile.fairVocalUnits || !Number.isFinite(time) || units.length === 0) {
      return {
        hasUnits: false,
        pitchScore: true,
        kind: "fallback",
        weight: 1,
        bandMultiplier: profile.pitchBandMultiplier,
        minVoicedScore: profile.minVoicedScore,
      };
    }

    let nearestTransitionDistance = Infinity;
    const active = units.find((unit) => {
      const start = Number(unit.start);
      const end = Number(unit.end);
      if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return false;
      nearestTransitionDistance = Math.min(
        nearestTransitionDistance,
        Math.abs(time - start),
        Math.abs(time - end),
      );
      return time >= start && time <= end;
    });

    if (!active) {
      const inTransitionGrace = nearestTransitionDistance <= profile.transitionGraceSeconds;
      return {
        hasUnits: true,
        pitchScore: false,
        kind: inTransitionGrace ? "transition" : "silent",
        weight: 0,
        bandMultiplier: 1,
      };
    }

    const start = Number(active.start);
    const end = Number(active.end);
    const duration = Math.max(0, end - start);
    const edgeGrace = Math.min(
      profile.transitionGraceSeconds,
      Math.max(0.035, duration * 0.24),
    );
    if (duration >= profile.minPitchUnitSeconds + edgeGrace * 2) {
      const inEdgeGrace = time - start < edgeGrace || end - time < edgeGrace;
      if (inEdgeGrace) {
        return {
          hasUnits: true,
          unit: active,
          pitchScore: false,
          kind: "transition",
          weight: 0,
          bandMultiplier: 1,
        };
      }
    }

    if (!isPitchScoreVocalUnit(active)) {
      return {
        hasUnits: true,
        unit: active,
        pitchScore: false,
        kind: active.score || active.type || "timing_only",
        weight: 0,
        bandMultiplier: 1,
      };
    }

    const lightPitch = isLightPitchVocalUnit(active);
    return {
      hasUnits: true,
      unit: active,
      pitchScore: true,
      kind: active.score,
      weight: lightPitch ? profile.lightPitchWeight : 1,
      bandMultiplier: profile.pitchBandMultiplier * (lightPitch ? profile.lightPitchBandMultiplier : 1),
      minVoicedScore: profile.minVoicedScore,
    };
  }

  function pitchScoreFractionForInterval(start, end) {
    if (!currentDifficultyProfile().fairVocalUnits) return null;
    const intervalStart = Number(start);
    const intervalEnd = Number(end);
    const units = normalizedLyricVocalUnits();
    if (!Number.isFinite(intervalStart) || !Number.isFinite(intervalEnd) || intervalEnd <= intervalStart) return null;
    if (units.length === 0) return null;
    const duration = intervalEnd - intervalStart;
    let scoreable = 0;
    units.forEach((unit) => {
      if (!isPitchScoreVocalUnit(unit)) return;
      const overlap = Math.max(0, Math.min(intervalEnd, Number(unit.end)) - Math.max(intervalStart, Number(unit.start)));
      scoreable += overlap;
    });
    return clamp(scoreable / duration, 0, 1);
  }

  function visibleLyricSegments(minTime, maxTime) {
    const paintTimeline = lyricPaintTimelineSegments();
    if (paintTimeline.length > 0) return paintTimeline.filter((unit) => unit.end >= minTime && unit.start <= maxTime);

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
            unitType: "line",
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
          unitType: "segment",
        });
      });
    });
    return segments.sort((a, b) => a.start - b.start || a.segmentIndex - b.segmentIndex);
  }

  function lyricPaintTimelineSegments() {
    const paintUnits = normalizedLyricPaintUnits()
      .filter((unit) => unit.unitType !== "line")
      .map((unit, index) => {
        const segmentIndex = Number.isFinite(unit.segmentIndex) ? unit.segmentIndex : index;
        const subUnits = lyricVocalSubUnitsForWord(unit.lineIndex, segmentIndex, unit.start, unit.end);
        const effectiveTiming = lyricSegmentTimingFromSubUnits(unit.start, unit.end, subUnits);
        return {
          ...unit,
          start: effectiveTiming.start,
          end: effectiveTiming.end,
          segmentIndex,
          subUnits,
          estimated: false,
        };
      });
    if (paintUnits.length > 0) {
      return paintUnits.sort((a, b) => a.start - b.start || a.lineIndex - b.lineIndex || a.segmentIndex - b.segmentIndex);
    }
    return lyricWordTimelineSegments();
  }

  function lyricWordTimelineSegments() {
    if (!state.lyrics.length) return [];

    const offset = Number(state.lyricsOffsetSeconds || 0);
    const unitsByLine = new Map();
    const normalizedUnits = normalizedLyricPaintUnits();
    normalizedUnits
      .filter((unit) => unit.unitType === "word")
      .forEach((unit) => {
        const lineIndex = Number.isFinite(unit.lineIndex) ? unit.lineIndex : 0;
        if (!unitsByLine.has(lineIndex)) unitsByLine.set(lineIndex, new Map());
        const lineUnits = unitsByLine.get(lineIndex);
        if (!lineUnits.has(unit.segmentIndex)) lineUnits.set(unit.segmentIndex, unit);
      });

    const lineTimingsByLine = new Map();
    normalizedUnits
      .filter((unit) => unit.unitType === "line")
      .forEach((unit) => {
        const lineIndex = Number.isFinite(unit.lineIndex) ? unit.lineIndex : 0;
        const start = Number(unit.start);
        const end = Number(unit.end);
        if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return;
        const current = lineTimingsByLine.get(lineIndex);
        if (!current || end - start < current.end - current.start) {
          lineTimingsByLine.set(lineIndex, { start, end });
        }
      });

    const segments = [];
    state.lyrics.forEach((line, lineIndex) => {
      const words = splitLyricCaptionWords(line.text);
      if (!words.length) return;
      const lineTiming = lineTimingsByLine.get(lineIndex);
      const lineStart = Number.isFinite(lineTiming?.start) ? lineTiming.start : Number(line.start) + offset;
      const lineEnd = Number.isFinite(lineTiming?.end) ? lineTiming.end : Number(line.end) + offset;
      if (!Number.isFinite(lineStart) || !Number.isFinite(lineEnd) || lineEnd <= lineStart) return;

      const lineUnits = unitsByLine.get(lineIndex) || new Map();
      const wordSegments = words.map((text, index) => {
        const unit = lineUnits.get(index);
        const start = Number(unit?.start);
        const end = Number(unit?.end);
        return {
          start,
          end,
          text,
          lineIndex,
          segmentIndex: index,
          precision: unit ? unit.precision : "estimated_word",
          unitType: "word",
          subUnits: Number.isFinite(start) && Number.isFinite(end)
            ? lyricVocalSubUnitsForWord(lineIndex, index, start, end)
            : [],
          estimated: !unit,
        };
      });

      fillEstimatedWordTimes(wordSegments, lineStart, lineEnd);
      wordSegments.forEach((segment) => {
        if (!Number.isFinite(segment.start) || !Number.isFinite(segment.end) || segment.end <= segment.start) return;
        if (!Array.isArray(segment.subUnits) || segment.subUnits.length === 0) {
          segment.subUnits = lyricVocalSubUnitsForWord(lineIndex, segment.segmentIndex, segment.start, segment.end);
        }
        if (Array.isArray(segment.subUnits) && segment.subUnits.length > 0) {
          const effectiveTiming = lyricSegmentTimingFromSubUnits(segment.start, segment.end, segment.subUnits);
          segment.start = effectiveTiming.start;
          segment.end = effectiveTiming.end;
        }
        segments.push(segment);
      });
    });

    return segments.sort((a, b) => a.start - b.start || a.lineIndex - b.lineIndex || a.segmentIndex - b.segmentIndex);
  }

  function lyricRoadTimingUnits() {
    return lyricPaintTimelineSegments();
  }

  function fillEstimatedWordTimes(wordSegments, lineStart, lineEnd) {
    for (let index = 0; index < wordSegments.length; index++) {
      const segment = wordSegments[index];
      if (Number.isFinite(segment.start) && Number.isFinite(segment.end) && segment.end > segment.start) continue;

      let runEnd = index;
      while (
        runEnd + 1 < wordSegments.length &&
        !(Number.isFinite(wordSegments[runEnd + 1].start) && Number.isFinite(wordSegments[runEnd + 1].end))
      ) {
        runEnd += 1;
      }

      const previous = index > 0 ? wordSegments[index - 1] : null;
      const next = runEnd + 1 < wordSegments.length ? wordSegments[runEnd + 1] : null;
      const startBoundary =
        previous && Number.isFinite(previous.end) && previous.end > lineStart ? previous.end : lineStart;
      const endBoundary = next && Number.isFinite(next.start) && next.start > startBoundary ? next.start : lineEnd;
      const duration = Math.max(0.18 * (runEnd - index + 1), endBoundary - startBoundary);
      const slot = duration / (runEnd - index + 1);
      for (let wordIndex = index; wordIndex <= runEnd; wordIndex++) {
        const localIndex = wordIndex - index;
        wordSegments[wordIndex].start = startBoundary + slot * localIndex;
        wordSegments[wordIndex].end = startBoundary + slot * (localIndex + 1);
      }
      index = runEnd;
    }
  }

  function lyricContentCacheKey() {
    const firstLine = state.lyrics[0];
    const lastLine = state.lyrics[state.lyrics.length - 1];
    return [
      state.currentLyricsKey || state.currentSubtitleUrl || state.nowPlaying.now_playing_url || "",
      state.lyrics.length,
      state.lyricPaintUnits.length,
      state.lyricVocalUnits.length,
      Number(state.lyricsOffsetSeconds || 0).toFixed(3),
      Number(firstLine?.start ?? 0).toFixed(3),
      Number(lastLine?.end ?? 0).toFixed(3),
    ].join("|");
  }

  function lyricPhrases() {
    const cacheKey = lyricContentCacheKey();
    if (state.lyricPhrasesCacheKey === cacheKey && state.lyricPhrasesCache) return state.lyricPhrasesCache;

    const groups = new Map();
    lyricPaintTimelineSegments().forEach((segment) => {
      if (!groups.has(segment.lineIndex)) groups.set(segment.lineIndex, []);
      groups.get(segment.lineIndex).push(segment);
    });

    const phrases = Array.from(groups.entries())
      .map(([lineIndex, words]) => {
        const sortedWords = words.sort((a, b) => a.segmentIndex - b.segmentIndex || a.start - b.start);
        const starts = sortedWords.map((word) => Number(word.start)).filter(Number.isFinite);
        const ends = sortedWords.map((word) => Number(word.end)).filter(Number.isFinite);
        return {
          lineIndex,
          words: sortedWords,
          start: starts.length ? Math.min(...starts) : sortedWords[0].start,
          end: ends.length ? Math.max(...ends) : sortedWords[sortedWords.length - 1].end,
          text: sortedWords.map((word) => word.text).join(" "),
        };
      })
      .sort((a, b) => a.start - b.start || a.lineIndex - b.lineIndex);
    state.lyricPhrasesCacheKey = cacheKey;
    state.lyricPhrasesCache = phrases;
    return phrases;
  }

  function visibleLyricPhrases(minTime, maxTime) {
    return lyricPhrases().filter((phrase) => phrase.end >= minTime - 1.2 && phrase.start <= maxTime + 1.2);
  }

  function fixedRoadTimeScale(width, songTime, notes) {
    const lookaheadSeconds = songRoadLookaheadSeconds(songTime, notes);
    const hitX = width * STAGE_ROAD_HIT_X;
    const pixelsPerSecond = (width - hitX) / lookaheadSeconds;
    return {
      mode: "fixed",
      hitX,
      lookaheadSeconds,
      pixelsPerSecond,
      minTime: songTime - Math.max(STAGE_ROAD_TRAIL_SECONDS, hitX / pixelsPerSecond),
      maxTime: songTime + lookaheadSeconds,
      xForTime: (time) => hitX + (time - songTime) * pixelsPerSecond,
    };
  }

  function vocalRoadTimeScale(ctx, width, songTime, notes, contour = songGuideContour()) {
    const fallback = fixedRoadTimeScale(width, songTime, notes);

    const intervals = vocalVisualIntervals(ctx, notes, contour, fallback.pixelsPerSecond);
    if (!intervals.length) return fallback;

    const currentVisual = visualPositionAtTime(songTime, intervals, fallback.pixelsPerSecond);
    const minVisual = currentVisual - fallback.hitX - 160;
    const maxVisual = currentVisual + (width - fallback.hitX) + 220;
    const minTime = timeAtVisualPosition(minVisual, intervals, fallback.pixelsPerSecond);
    const maxTime = timeAtVisualPosition(maxVisual, intervals, fallback.pixelsPerSecond);
    return {
      mode: "vocal",
      hitX: fallback.hitX,
      lookaheadSeconds: fallback.lookaheadSeconds,
      pixelsPerSecond: fallback.pixelsPerSecond,
      minTime: Math.max(songTime - STAGE_ROAD_MAX_LOOKAHEAD_SECONDS, minTime),
      maxTime: Math.min(songTime + STAGE_ROAD_MAX_LOOKAHEAD_SECONDS, maxTime),
      xForTime: (time) =>
        fallback.hitX + visualPositionAtTime(time, intervals, fallback.pixelsPerSecond) - currentVisual,
    };
  }

  function vocalVisualIntervals(ctx, notes, contour, pixelsPerSecond) {
    const lyricUnits = lyricRoadTimingUnits();
    const vocalSubUnits = normalizedLyricVocalUnits();
    const firstNote = notes[0];
    const lastNote = notes[notes.length - 1];
    const firstContour = contour[0];
    const lastContour = contour[contour.length - 1];
    const firstVocalSubUnit = vocalSubUnits[0];
    const lastVocalSubUnit = vocalSubUnits[vocalSubUnits.length - 1];
    const cacheKey = [
      lyricContentCacheKey(),
      lyricUnits.length,
      vocalSubUnits.length,
      Number(firstVocalSubUnit?.start ?? 0).toFixed(3),
      Number(lastVocalSubUnit?.end ?? 0).toFixed(3),
      notes.length,
      Number(firstNote?.start ?? 0).toFixed(3),
      Number(lastNote?.end ?? 0).toFixed(3),
      contour.length,
      Number(firstContour?.time ?? 0).toFixed(3),
      Number(lastContour?.time ?? 0).toFixed(3),
      Math.round(pixelsPerSecond * 100),
    ].join("|");
    if (state.lyricVisualCacheKey === cacheKey && state.lyricVisualIntervals) return state.lyricVisualIntervals;
    const intervals = applyLyricSpacingToVisualIntervals(
      ctx,
      buildVocalVisualIntervals(ctx, lyricUnits, vocalSubUnits, notes, contour, pixelsPerSecond),
      lyricUnits,
      pixelsPerSecond,
    );
    state.lyricVisualCacheKey = cacheKey;
    state.lyricVisualIntervals = intervals;
    return intervals;
  }

  function buildVocalVisualIntervals(ctx, lyricUnits, vocalSubUnits, notes, contour, pixelsPerSecond) {
    const lyricEvents = lyricTimelineEvents(ctx, lyricUnits, pixelsPerSecond);
    const vocalUnitEvents = vocalUnitTimelineEvents(vocalSubUnits);
    const noteEvents = noteTimelineEvents(notes);
    const contourEvents = contourTimelineEvents(contour);
    const events = [...lyricEvents, ...vocalUnitEvents, ...noteEvents, ...contourEvents].sort(
      (a, b) => a.start - b.start || a.end - b.end
    );
    if (!events.length) return [];

    const breakpoints = new Set();
    events.forEach((event) => {
      breakpoints.add(roundTimelineTime(event.start));
      breakpoints.add(roundTimelineTime(event.end));
    });
    const orderedBreakpoints = [...breakpoints]
      .map((value) => Number(value))
      .filter(Number.isFinite)
      .sort((a, b) => a - b);

    const intervals = [];
    let cursor = 0;
    let previousEnd = orderedBreakpoints[0];
    for (let index = 0; index < orderedBreakpoints.length - 1; index++) {
      const start = orderedBreakpoints[index];
      const end = orderedBreakpoints[index + 1];
      if (!Number.isFinite(start) || !Number.isFinite(end) || end - start < VOCAL_TIMELINE_MIN_SEGMENT_SECONDS) {
        continue;
      }

      if (start - previousEnd >= VOCAL_TIMELINE_MIN_SEGMENT_SECONDS) {
        const gapWidth = visualWidthForTimelineSegment(
          previousEnd,
          start,
          [],
          pixelsPerSecond
        );
        intervals.push({
          start: previousEnd,
          end: start,
          visualStart: cursor,
          visualEnd: cursor + gapWidth,
          kind: "silence",
        });
        cursor += gapWidth;
      }

      const activeEvents = events.filter((event) => event.end > start && event.start < end);
      const visualWidth = visualWidthForTimelineSegment(start, end, activeEvents, pixelsPerSecond);
      intervals.push({
        start,
        end,
        visualStart: cursor,
        visualEnd: cursor + visualWidth,
        kind: timelineSegmentKind(activeEvents),
      });
      cursor += visualWidth;
      previousEnd = end;
    }

    return intervals;
  }

  function lyricTimelineEvents(ctx, units, pixelsPerSecond) {
    if (!Array.isArray(units) || units.length === 0) return [];
    ctx.save();
    ctx.font = "900 23px sans-serif";
    const events = units
      .map((unit) => {
        const start = Number(unit.start);
        const end = Number(unit.end);
        const text = String(unit.text || "").trim();
        if (!text || !Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
        const textWidth = ctx.measureText(text).width;
        const minimumWidth = clamp(textWidth + VOCAL_TIMELINE_TEXT_PADDING, 30, VOCAL_TIMELINE_MAX_TEXT_WIDTH);
        return {
          start,
          end,
          kind: "lyric",
          minimumWidth,
          duration: end - start,
        };
      })
      .filter(Boolean);
    ctx.restore();
    return events;
  }

  function vocalUnitTimelineEvents(units) {
    if (!Array.isArray(units) || units.length === 0) return [];
    return units
      .map((unit) => {
        const start = Number(unit.start);
        const end = Number(unit.end);
        if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
        if (!["vowel_sustain", "sonorant_sustain", "fricative_effect"].includes(unit.type)) return null;
        const duration = end - start;
        if (duration < 0.16) return null;
        const isSustain = unit.sustain || unit.type === "vowel_sustain" || unit.type === "sonorant_sustain";
        return {
          start,
          end,
          kind: "vocal_unit",
          subtype: unit.type,
          duration,
          rate: unit.type === "fricative_effect" && !unit.sustain
            ? VOCAL_TIMELINE_EFFECT_RATE
            : isSustain
              ? VOCAL_TIMELINE_SUSTAIN_RATE
              : VOCAL_TIMELINE_EFFECT_RATE,
        };
      })
      .filter(Boolean);
  }

  function noteTimelineEvents(notes) {
    if (!Array.isArray(notes) || notes.length === 0) return [];
    return notes
      .map((note) => {
        const start = Number(note.start);
        const end = Number(note.end);
        if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
        return {
          start,
          end,
          kind: "note",
          duration: end - start,
        };
      })
      .filter(Boolean);
  }

  function contourTimelineEvents(contour) {
    if (!Array.isArray(contour) || contour.length < 2) return [];
    const events = [];
    let clusterStart = null;
    let previousTime = null;
    contour.forEach((point) => {
      const time = Number(point.time);
      const confidence = Number(point.confidence ?? 1);
      if (!Number.isFinite(time) || confidence < REFERENCE_CONTOUR_MIN_CONFIDENCE) return;
      if (clusterStart === null || previousTime === null) {
        clusterStart = time;
        previousTime = time;
        return;
      }
      if (time - previousTime > VOCAL_TIMELINE_CONTOUR_GAP_SECONDS) {
        if (previousTime > clusterStart) events.push({ start: clusterStart, end: previousTime, kind: "contour" });
        clusterStart = time;
      }
      previousTime = time;
    });
    if (clusterStart !== null && previousTime !== null && previousTime > clusterStart) {
      events.push({ start: clusterStart, end: previousTime, kind: "contour" });
    }
    return events;
  }

  function visualWidthForTimelineSegment(start, end, activeEvents, pixelsPerSecond) {
    const duration = Math.max(VOCAL_TIMELINE_MIN_SEGMENT_SECONDS, end - start);
    const baseWidth = duration * pixelsPerSecond;
    if (!activeEvents.length) {
      const rate = duration > 1.6 ? VOCAL_TIMELINE_LONG_SILENCE_RATE : VOCAL_TIMELINE_SHORT_SILENCE_RATE;
      return Math.max(4, baseWidth * rate);
    }

    const hasLyric = activeEvents.some((event) => event.kind === "lyric");
    const vocalUnitEvents = activeEvents.filter((event) => event.kind === "vocal_unit");
    const hasVocal = activeEvents.some((event) => event.kind === "note" || event.kind === "contour");
    let rate = hasVocal ? VOCAL_TIMELINE_NOTE_RATE : 0.86;
    let hasSustain = false;
    if (vocalUnitEvents.length > 0) {
      const vocalRate = Math.min(...vocalUnitEvents.map((event) => Number(event.rate) || VOCAL_TIMELINE_EFFECT_RATE));
      hasSustain = vocalUnitEvents.some((event) => event.subtype === "vowel_sustain" || event.subtype === "sonorant_sustain");
      rate = Math.min(rate, vocalRate);
    }
    let minimumWidth = 0;
    activeEvents.forEach((event) => {
      if (event.kind !== "lyric") return;
      const overlap = Math.max(0, Math.min(end, event.end) - Math.max(start, event.start));
      if (overlap <= 0) return;
      const eventDuration = Math.max(VOCAL_TIMELINE_MIN_SEGMENT_SECONDS, event.duration || event.end - event.start);
      minimumWidth = Math.max(minimumWidth, (Number(event.minimumWidth) || 0) * (overlap / eventDuration));
    });
    if (hasLyric && minimumWidth > 0) {
      const denseRate = Math.min(VOCAL_TIMELINE_MAX_DENSE_RATE, minimumWidth / Math.max(1, baseWidth));
      rate = hasSustain ? Math.min(rate, denseRate) : Math.max(rate, denseRate);
    }
    return Math.max(4, baseWidth * rate, minimumWidth);
  }

  function applyLyricSpacingToVisualIntervals(ctx, intervals, lyricUnits, pixelsPerSecond) {
    if (!intervals.length || !Array.isArray(lyricUnits) || lyricUnits.length < 2) return intervals;
    const constraints = lyricSpacingConstraints(ctx, lyricUnits);
    if (!constraints.length) return intervals;

    let adjusted = intervals;
    for (let pass = 0; pass < 2; pass++) {
      let changed = false;
      constraints.forEach((constraint) => {
        const fromX = visualPositionAtTime(constraint.from, adjusted, pixelsPerSecond);
        const toX = visualPositionAtTime(constraint.to, adjusted, pixelsPerSecond);
        const deficit = constraint.requiredWidth - (toX - fromX);
        if (deficit <= 0.75) return;
        adjusted = addVisualWidthBetweenTimes(adjusted, constraint.from, constraint.to, deficit);
        changed = true;
      });
      if (!changed) break;
    }
    return adjusted;
  }

  function lyricSpacingConstraints(ctx, lyricUnits) {
    const unitsByLine = new Map();
    lyricUnits.forEach((unit) => {
      const text = String(unit?.text || "").trim();
      const start = Number(unit?.start);
      if (!text || !Number.isFinite(start)) return;
      const lineIndex = Number(unit.lineIndex ?? 0);
      if (!unitsByLine.has(lineIndex)) unitsByLine.set(lineIndex, []);
      unitsByLine.get(lineIndex).push({
        start,
        segmentIndex: Number(unit.segmentIndex ?? 0),
        text,
      });
    });

    const constraints = [];
    ctx.save();
    ctx.font = `900 ${VOCAL_TIMELINE_LYRIC_FONT_SIZE}px sans-serif`;
    const minGap = Math.max(VOCAL_TIMELINE_LYRIC_MIN_GAP_PX, ctx.measureText(" ").width * 0.9);
    unitsByLine.forEach((units) => {
      const sorted = units.sort((a, b) => a.segmentIndex - b.segmentIndex || a.start - b.start);
      let previous = null;
      sorted.forEach((unit) => {
        const width = ctx.measureText(unit.text).width;
        if (previous && unit.start > previous.start + 0.012) {
          constraints.push({
            from: previous.start,
            to: unit.start,
            requiredWidth: previous.width + minGap,
          });
        }
        previous = { start: unit.start, width };
      });
    });
    ctx.restore();
    return constraints.sort((a, b) => a.to - b.to || a.from - b.from);
  }

  function addVisualWidthBetweenTimes(intervals, start, end, extraWidth) {
    const extra = Math.max(0, Number(extraWidth) || 0);
    if (!extra) return intervals;
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start + 0.012) {
      return addVisualWidthBeforeTime(intervals, end, extra);
    }

    const overlaps = intervals.map((interval) =>
      Math.max(0, Math.min(end, interval.end) - Math.max(start, interval.start))
    );
    const totalOverlap = overlaps.reduce((sum, overlap) => sum + overlap, 0);
    if (totalOverlap <= 0.001) {
      return addVisualWidthBeforeTime(intervals, end, extra);
    }

    const additions = overlaps.map((overlap) => (overlap > 0 ? extra * (overlap / totalOverlap) : 0));
    return reflowVisualIntervals(intervals, additions);
  }

  function addVisualWidthBeforeTime(intervals, time, extraWidth) {
    if (!intervals.length) return intervals;
    const additions = Array.from({ length: intervals.length }, () => 0);
    let targetIndex = -1;
    for (let index = intervals.length - 1; index >= 0; index--) {
      if (intervals[index].end <= time + 0.001) {
        targetIndex = index;
        break;
      }
    }
    if (targetIndex < 0) {
      targetIndex = intervals.findIndex((interval) => interval.start <= time && interval.end >= time);
    }
    additions[Math.max(0, targetIndex)] = Math.max(0, Number(extraWidth) || 0);
    return reflowVisualIntervals(intervals, additions);
  }

  function reflowVisualIntervals(intervals, additions = []) {
    let cursor = 0;
    return intervals.map((interval, index) => {
      const width = Math.max(0, interval.visualEnd - interval.visualStart) + Math.max(0, additions[index] || 0);
      const next = {
        ...interval,
        visualStart: cursor,
        visualEnd: cursor + width,
      };
      cursor = next.visualEnd;
      return next;
    });
  }

  function timelineSegmentKind(activeEvents) {
    if (activeEvents.some((event) => event.kind === "lyric")) return "lyric";
    if (activeEvents.some((event) => event.kind === "vocal_unit")) return "vocal_unit";
    if (activeEvents.some((event) => event.kind === "note")) return "note";
    if (activeEvents.some((event) => event.kind === "contour")) return "contour";
    return "silence";
  }

  function roundTimelineTime(value) {
    return Math.round(Number(value) * 1000) / 1000;
  }

  function visualPositionAtTime(time, intervals, pixelsPerSecond) {
    if (!intervals.length) return time * pixelsPerSecond;
    const first = intervals[0];
    if (time <= first.start) return first.visualStart + (time - first.start) * pixelsPerSecond;

    let low = 0;
    let high = intervals.length - 1;
    while (low <= high) {
      const mid = Math.floor((low + high) / 2);
      const current = intervals[mid];
      if (time < current.start) {
        high = mid - 1;
      } else if (time > current.end) {
        low = mid + 1;
      } else {
        const progress = clamp((time - current.start) / Math.max(0.08, current.end - current.start), 0, 1);
        return current.visualStart + (current.visualEnd - current.visualStart) * progress;
      }
    }

    const previous = intervals[high] || null;
    const next = intervals[low] || null;
    if (previous && next) {
      const progress = clamp((time - previous.end) / Math.max(0.08, next.start - previous.end), 0, 1);
      return previous.visualEnd + (next.visualStart - previous.visualEnd) * progress;
    }

    const last = intervals[intervals.length - 1];
    return last.visualEnd + (time - last.end) * pixelsPerSecond;
  }

  function timeAtVisualPosition(visualPosition, intervals, pixelsPerSecond) {
    if (!intervals.length) return visualPosition / pixelsPerSecond;
    const first = intervals[0];
    if (visualPosition <= first.visualStart) {
      return first.start + (visualPosition - first.visualStart) / Math.max(1, pixelsPerSecond);
    }

    let low = 0;
    let high = intervals.length - 1;
    while (low <= high) {
      const mid = Math.floor((low + high) / 2);
      const current = intervals[mid];
      if (visualPosition < current.visualStart) {
        high = mid - 1;
      } else if (visualPosition > current.visualEnd) {
        low = mid + 1;
      } else {
        const progress = clamp(
          (visualPosition - current.visualStart) / Math.max(1, current.visualEnd - current.visualStart),
          0,
          1,
        );
        return current.start + (current.end - current.start) * progress;
      }
    }

    const previous = intervals[high] || null;
    const next = intervals[low] || null;
    if (previous && next) {
      const progress = clamp(
        (visualPosition - previous.visualEnd) / Math.max(1, next.visualStart - previous.visualEnd),
        0,
        1,
      );
      return previous.end + (next.start - previous.end) * progress;
    }

    const last = intervals[intervals.length - 1];
    return last.end + (visualPosition - last.visualEnd) / Math.max(1, pixelsPerSecond);
  }

  function lyricFontForWidth(ctx, text, maxWidth, baseSize = 34, minSize = 18) {
    const cleanText = String(text || "").trim();
    let size = baseSize;
    while (size > minSize) {
      ctx.font = `900 ${size}px sans-serif`;
      if (ctx.measureText(cleanText).width <= maxWidth) return size;
      size -= 1;
    }
    return minSize;
  }

  function drawLyricSegmentText(ctx, segment, x1, x2, textY, songTime, hitX, canvasWidth) {
    const slotWidth = x2 - x1;
    const isActive = songTime >= segment.start && songTime < segment.end;
    if (slotWidth < 18 && !isActive) return;

    const textPadding = 0;
    const isLineUnit = segment.unitType === "line" || segment.precision?.startsWith("line");
    const safeWidth = Math.max(10, (isLineUnit ? canvasWidth * 0.74 : slotWidth) - textPadding * 2);
    const baseFontSize = isLineUnit ? 44 : 30;
    const minFontSize = isLineUnit ? 26 : 15;
    const fontSize = lyricFontForWidth(ctx, segment.text, safeWidth, baseFontSize, minFontSize);
    const textX = x1 + textPadding;
    const clipTop = textY - fontSize * 0.82;
    const clipHeight = fontSize * 1.7;
    ctx.font = `900 ${fontSize}px sans-serif`;
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";

    ctx.save();
    ctx.beginPath();
    ctx.rect(isLineUnit ? 0 : x1, clipTop, Math.max(1, isLineUnit ? canvasWidth : slotWidth), clipHeight);
    ctx.clip();
    ctx.fillStyle = songTime >= segment.end ? "rgba(18, 199, 156, 0.96)" : "rgba(246, 243, 234, 0.72)";
    ctx.fillText(segment.text, textX, textY);
    ctx.restore();

    if (songTime < segment.start || songTime >= segment.end) return;

    ctx.save();
    ctx.beginPath();
    ctx.rect(textX, clipTop, Math.max(1, lyricUnitPaintFillWidth(ctx, segment, songTime)), clipHeight);
    ctx.clip();
    ctx.fillStyle = "rgba(18, 199, 156, 1)";
    ctx.fillText(segment.text, textX, textY);
    ctx.restore();
  }

  function splitLyricCaptionWords(text) {
    const cleanText = String(text || "").trim();
    if (!cleanText) return [];
    const tokens = cleanText.match(/[\p{L}\p{N}]+(?:['’][\p{L}\p{N}]+)*/gu);
    return tokens?.length ? tokens : cleanText.split(/\s+/).filter(Boolean);
  }

  function lyricUnitPaintProgress(segment, songTime) {
    const start = Number(segment?.start);
    const end = Number(segment?.end);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return 0;
    return clamp((songTime - start) / Math.max(0.04, end - start), 0, 1);
  }

  function lyricUnitPaintRatio(segment, songTime) {
    const text = String(segment?.text || "");
    const chars = Array.from(text);
    if (!chars.length) return lyricUnitPaintProgress(segment, songTime);
    if (songTime <= Number(segment?.start)) return 0;
    if (songTime >= Number(segment?.end)) return 1;
    const subUnits = Array.isArray(segment?.subUnits)
      ? segment.subUnits
          .filter((unit) => unit && Number.isFinite(Number(unit.start)) && Number.isFinite(Number(unit.end)))
          .sort((a, b) => Number(a.start) - Number(b.start) || Number(a.subIndex || 0) - Number(b.subIndex || 0))
      : [];
    if (!subUnits.length) return lyricUnitPaintProgress(segment, songTime);

    for (const unit of subUnits) {
      const start = Number(unit.start);
      const end = Number(unit.end);
      const charStart = Number(unit.charStart);
      const charEnd = Number(unit.charEnd);
      if (
        !Number.isFinite(start) ||
        !Number.isFinite(end) ||
        !Number.isFinite(charStart) ||
        !Number.isFinite(charEnd) ||
        charEnd <= charStart ||
        charStart < 0 ||
        charStart > chars.length
      ) {
        return lyricUnitPaintProgress(segment, songTime);
      }
      const clampedCharEnd = Math.min(chars.length, charEnd);
      if (songTime >= end) continue;
      if (songTime <= start) return clamp(charStart / chars.length, 0, 1);
      const progress = clamp((songTime - start) / Math.max(0.035, end - start), 0, 1);
      return clamp((charStart + (clampedCharEnd - charStart) * progress) / chars.length, 0, 1);
    }
    return 1;
  }

  function lyricUnitPaintFillWidth(ctx, segment, songTime) {
    const text = String(segment?.text || "");
    if (!text) return 0;
    const fullWidth = ctx.measureText(text).width;
    if (songTime <= Number(segment?.start)) return 0;
    if (songTime >= Number(segment?.end)) return fullWidth;

    const subUnits = Array.isArray(segment?.subUnits)
      ? segment.subUnits
          .filter((unit) => unit && Number.isFinite(Number(unit.start)) && Number.isFinite(Number(unit.end)))
          .sort((a, b) => Number(a.start) - Number(b.start) || Number(a.subIndex || 0) - Number(b.subIndex || 0))
      : [];
    if (!subUnits.length) {
      return weightedLyricTextFillWidth(ctx, text, lyricUnitPaintProgress(segment, songTime));
    }

    const spanWidth = lyricSubUnitSpanPaintWidth(ctx, text, subUnits, songTime);
    if (Number.isFinite(spanWidth)) return spanWidth;

    const unitWidths = subUnits.map((unit) => ctx.measureText(String(unit.text || unit.displayText || "")).width);
    const unitWidthSum = unitWidths.reduce((sum, width) => sum + width, 0);
    if (unitWidthSum <= 0) {
      return weightedLyricTextFillWidth(ctx, text, lyricUnitPaintProgress(segment, songTime));
    }

    let paintedWidth = 0;
    for (let index = 0; index < subUnits.length; index++) {
      const unit = subUnits[index];
      const start = Number(unit.start);
      const end = Number(unit.end);
      const unitWidth = unitWidths[index];
      if (songTime >= end) {
        paintedWidth += unitWidth;
        continue;
      }
      if (songTime > start) {
        const progress = clamp((songTime - start) / Math.max(0.035, end - start), 0, 1);
        paintedWidth += unitWidth * progress;
      }
      break;
    }
    return clamp(paintedWidth * (fullWidth / unitWidthSum), 0, fullWidth);
  }

  function lyricSubUnitSpanPaintWidth(ctx, text, subUnits, songTime) {
    const chars = Array.from(String(text || ""));
    if (!chars.length) return 0;
    const fullWidth = ctx.measureText(text).width;
    let paintedWidth = 0;
    for (const unit of subUnits) {
      const start = Number(unit.start);
      const end = Number(unit.end);
      const charStart = Number(unit.charStart);
      const charEnd = Number(unit.charEnd);
      if (
        !Number.isFinite(start) ||
        !Number.isFinite(end) ||
        !Number.isFinite(charStart) ||
        !Number.isFinite(charEnd) ||
        charEnd <= charStart ||
        charStart < 0 ||
        charEnd > chars.length
      ) {
        return Number.NaN;
      }
      const prefixWidth = ctx.measureText(chars.slice(0, charStart).join("")).width;
      const unitWidth = ctx.measureText(chars.slice(charStart, charEnd).join("")).width;
      if (songTime >= end) {
        paintedWidth = Math.max(paintedWidth, prefixWidth + unitWidth);
        continue;
      }
      if (songTime > start) {
        const progress = clamp((songTime - start) / Math.max(0.035, end - start), 0, 1);
        paintedWidth = Math.max(paintedWidth, prefixWidth + unitWidth * progress);
      }
      break;
    }
    return clamp(paintedWidth, 0, fullWidth);
  }

  function weightedLyricTextFillWidth(ctx, text, progress) {
    const cleanText = String(text || "");
    const chars = Array.from(cleanText);
    if (!chars.length) return 0;
    const safeProgress = clamp(Number(progress), 0, 1);
    if (safeProgress <= 0) return 0;
    if (safeProgress >= 1) return ctx.measureText(cleanText).width;

    const weights = chars.map((char) => lyricPaintCharacterWeight(char));
    const totalWeight = weights.reduce((sum, weight) => sum + weight, 0);
    if (totalWeight <= 0) return ctx.measureText(cleanText).width * safeProgress;
    const targetWeight = totalWeight * safeProgress;

    let consumed = 0;
    let width = 0;
    for (let index = 0; index < chars.length; index++) {
      const char = chars[index];
      const weight = weights[index];
      const charWidth = ctx.measureText(char).width;
      if (consumed + weight >= targetWeight) {
        const localProgress = clamp((targetWeight - consumed) / Math.max(0.001, weight), 0, 1);
        return width + charWidth * localProgress;
      }
      consumed += weight;
      width += charWidth;
    }
    return ctx.measureText(cleanText).width;
  }

  function lyricPaintCharacterWeight(char) {
    if (/[\p{N}]/u.test(char)) return 0.8;
    if (/[aeiouáàâãäåéèêëíìîïóòôõöúùûüýÿAEIOUÁÀÂÃÄÅÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÝ]/u.test(char)) {
      return 2.8;
    }
    if (/[\p{L}]/u.test(char)) return 0.48;
    if (/\s/u.test(char)) return 0.25;
    return 0.35;
  }

  function drawScrollingLyricPhrases(ctx, width, phrases, xForTime, songTime, textY, hitX) {
    if (!phrases.length) return false;

    const laneHeight = LYRIC_ROAD_LANE_HEIGHT;
    const laneCount = LYRIC_ROAD_LANE_COUNT;
    const phraseLanes = cachedLyricPhraseLanes(laneCount);
    ctx.save();
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.shadowColor = "rgba(0, 0, 0, 0.78)";
    ctx.shadowBlur = 8;
    ctx.shadowOffsetY = 2;

    const allPhrases = lyricPhrases();
    const phraseTimings = lyricPhraseTimingMap(allPhrases);
    drawLyricSilenceCues(ctx, width, allPhrases, phraseLanes, phraseTimings, xForTime, textY, laneHeight);

    phrases.forEach((phrase) => {
      const timing = phraseTimings.get(phrase.lineIndex) || phrase;
      const phraseStart = Number(timing.start);
      const phraseEnd = Number(timing.end);
      const isActive = songTime >= phraseStart && songTime <= phraseEnd;
      const isDone = songTime > phraseEnd;
      const fontSize = 23;
      ctx.font = `900 ${fontSize}px sans-serif`;
      const timeX1 = xForTime(phraseStart);
      const timeX2 = xForTime(phraseEnd);
      const timingWidth = Math.max(4, timeX2 - timeX1);
      const timingX = timeX1;
      const layouts = timedPhraseWordLayouts(ctx, phrase.words, fontSize, xForTime);
      if (Math.max(timingX + timingWidth, layouts.maxX) < -120) return;
      if (Math.min(timingX, layouts.minX) > width + 120) return;

      const laneIndex = phraseLanes.get(phrase.lineIndex) ?? stableLyricLane(phrase.lineIndex, laneCount);
      const y = textY + laneIndex * laneHeight;
      ctx.globalAlpha = phrase.words.every((word) => word.estimated) ? 0.72 : 1;
      ctx.fillStyle = isActive
        ? "rgba(237, 176, 73, 0.18)"
        : isDone
          ? "rgba(18, 199, 156, 0.1)"
          : "rgba(246, 243, 234, 0.08)";
      drawRoundRect(ctx, timingX, y - 17, timingWidth, 30, 8);
      ctx.fill();

      layouts.items.forEach((layout) => {
        const word = layout.word;
        const x = layout.x;
        const wordActive = songTime >= word.start && songTime < word.end;
        const wordDone = songTime >= word.end;
        ctx.globalAlpha = word.estimated ? 0.72 : 1;
        ctx.fillStyle = wordDone ? "rgba(18, 199, 156, 0.98)" : "rgba(246, 243, 234, 0.84)";
        ctx.fillText(word.text, x, y);

        if (!wordActive) return;
        ctx.save();
        ctx.beginPath();
        ctx.rect(x, y - fontSize, Math.max(1, lyricUnitPaintFillWidth(ctx, word, songTime)), fontSize * 2);
        ctx.clip();
        ctx.globalAlpha = 1;
        ctx.fillStyle = "rgba(18, 199, 156, 1)";
        ctx.fillText(word.text, x, y);
        ctx.restore();
      });
    });

    ctx.globalAlpha = 1;
    ctx.restore();
    return true;
  }

  function lyricPhraseTimingMap(phrases) {
    const timings = new Map();
    phrases.forEach((phrase) => {
      timings.set(phrase.lineIndex, {
        start: Number(phrase.start),
        end: Number(phrase.end),
      });
    });
    return timings;
  }

  function drawLyricSilenceCues(ctx, width, phrases, phraseLanes, phraseTimings, xForTime, textY, laneHeight) {
    const ordered = [...phrases].sort((a, b) => a.start - b.start || a.lineIndex - b.lineIndex);
    ordered.forEach((phrase, index) => {
      const next = ordered[index + 1];
      if (!next) return;
      const timing = phraseTimings.get(phrase.lineIndex) || phrase;
      const nextTiming = phraseTimings.get(next.lineIndex) || next;
      const gapStart = Number(timing.end);
      const gapEnd = Number(nextTiming.start);
      const gap = gapEnd - gapStart;
      if (!Number.isFinite(gap) || gap < LYRIC_SILENCE_MIN_GAP_SECONDS) return;

      const laneIndex = phraseLanes.get(next.lineIndex) ?? 0;
      const y = textY + laneIndex * laneHeight;
      const unit = gap / LYRIC_SILENCE_CUE_COUNT;
      for (let cueIndex = 0; cueIndex < LYRIC_SILENCE_CUE_COUNT; cueIndex++) {
        const cueStart = gapStart + unit * cueIndex;
        const cueEnd = cueStart + unit;
        const x1 = xForTime(cueStart);
        const x2 = xForTime(cueEnd);
        if (x2 < -20 || x1 > width + 20) continue;
        const cueWidth = Math.max(3, x2 - x1);
        const inset = Math.min(4, Math.max(1, cueWidth * 0.12));
        const alpha = 0.07 + cueIndex * 0.025;
        ctx.globalAlpha = 1;
        ctx.fillStyle = `rgba(246, 243, 234, ${alpha})`;
        ctx.strokeStyle = `rgba(246, 243, 234, ${alpha + 0.08})`;
        ctx.lineWidth = 1;
        drawRoundRect(ctx, x1 + inset, y - 17, Math.max(2, cueWidth - inset * 2), 30, 8);
        ctx.fill();
        ctx.stroke();
      }
    });
  }

  function cachedLyricPhraseLanes(laneCount) {
    const cacheKey = [
      lyricContentCacheKey(),
      laneCount,
    ].join("|");
    if (state.lyricLaneCacheKey === cacheKey && state.lyricLaneCache) return state.lyricLaneCache;
    const lanes = assignLyricPhraseLanes(lyricPhrases(), laneCount);
    state.lyricLaneCacheKey = cacheKey;
    state.lyricLaneCache = lanes;
    return lanes;
  }

  function assignLyricPhraseLanes(phrases, laneCount) {
    const assignments = new Map();
    const laneAvailableAt = Array.from({ length: laneCount }, () => -Infinity);
    [...phrases]
      .sort((a, b) => a.start - b.start || a.lineIndex - b.lineIndex)
      .forEach((phrase, order) => {
        const preferredLane = stableLyricLane(Number.isFinite(Number(phrase.lineIndex)) ? phrase.lineIndex : order, laneCount);
        const lane = chooseStableLyricLane(preferredLane, phrase, laneAvailableAt, LYRIC_ROAD_LANE_GAP_SECONDS);
        assignments.set(phrase.lineIndex, lane);
        laneAvailableAt[lane] = Math.max(laneAvailableAt[lane], Number(phrase.end) + LYRIC_ROAD_LANE_GAP_SECONDS);
      });
    return assignments;
  }

  function chooseStableLyricLane(preferredLane, phrase, laneAvailableAt, laneGapSeconds) {
    const candidates = lyricLaneCandidates(preferredLane, laneAvailableAt.length);
    const start = Number(phrase.start);
    const openLane = candidates.find((lane) => start >= laneAvailableAt[lane] - laneGapSeconds * 0.2);
    if (Number.isFinite(openLane)) return openLane;
    return candidates.sort((a, b) => laneAvailableAt[a] - laneAvailableAt[b] || a - b)[0] ?? preferredLane;
  }

  function lyricLaneCandidates(preferredLane, laneCount) {
    return Array.from({ length: laneCount }, (_, lane) => lane).sort(
      (a, b) => Math.abs(a - preferredLane) - Math.abs(b - preferredLane) || a - b,
    );
  }

  function stableLyricLane(lineIndex, laneCount) {
    const index = Math.max(0, Math.floor(Number(lineIndex) || 0));
    return index % Math.max(1, laneCount);
  }

  function phraseWordLayouts(ctx, words, fontSize) {
    const spaceWidth = Math.max(fontSize * 0.36, ctx.measureText(" ").width);
    const items = [];
    let totalWidth = 0;
    words.forEach((word, index) => {
      const width = ctx.measureText(word.text).width;
      if (index > 0) totalWidth += spaceWidth;
      items.push({ word, x: totalWidth, width });
      totalWidth += width;
    });
    return { items, totalWidth };
  }

  function timedPhraseWordLayouts(ctx, words, fontSize, xForTime) {
    const items = [];
    let minX = Infinity;
    let maxX = -Infinity;
    let previousRight = -Infinity;
    const minGap = Math.max(fontSize * 0.34, ctx.measureText(" ").width * 0.8);
    words.forEach((word) => {
      const width = ctx.measureText(word.text).width;
      const startX = xForTime(Number(word.start));
      const endX = xForTime(Number(word.end));
      const preferredX = startX + 6;
      const x = preferredX;
      const slotEndX = Math.max(x + 1, endX - 6);
      const overlap = Math.max(0, previousRight + minGap - x);
      items.push({ word, x, endX: slotEndX, width, overlap });
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x + width, slotEndX);
      previousRight = x + width;
    });
    if (!items.length) {
      return { items: [], minX: Infinity, maxX: -Infinity };
    }
    return { items, minX, maxX };
  }

  function drawStageLyricRail(ctx, width, xForTime, songTime, railY, minTime, maxTime, hitX, contour = [], notes = []) {
    if (!state.lyrics.length) return;

    const phrases = visibleLyricPhrases(minTime, maxTime);
    const segments = visibleLyricSegments(minTime, maxTime);
    if (segments.length === 0 && phrases.length === 0) return;
    const timedSegments = segments.filter((segment) => segment.unitType !== "line");
    const hasTimedSegments = timedSegments.length > 0;
    const fixedLyrics = Boolean(state.fixedLyricsEnabled);

    const railH = 10;
    const railTop = railY - 13;
    const textY = railY + (hasTimedSegments ? 24 : 20);

    ctx.save();
    ctx.fillStyle = "rgba(3, 6, 10, 0.46)";
    drawRoundRect(ctx, 0, railTop - 16, width, fixedLyrics ? 44 : hasTimedSegments ? 168 : 78, 0);
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

      if (!hasTimedSegments && !fixedLyrics) {
        drawLyricSegmentText(ctx, segment, x1, x2, textY, songTime, hitX, width);
      }
    });

    if (hasTimedSegments && !fixedLyrics) {
      drawScrollingLyricPhrases(ctx, width, phrases, xForTime, songTime, textY + 8, hitX);
    }

    ctx.fillStyle = "rgba(246, 243, 234, 0.72)";
    ctx.font = "800 11px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "alphabetic";
    ctx.fillText("agora", hitX, railTop - 10);
    ctx.restore();
    ctx.textAlign = "start";
    ctx.textBaseline = "alphabetic";
  }

  function drawLyricWordTimingBands(ctx, wordSegments, xForTime, layout, songTime) {
    if (!wordSegments.length) return;
    ctx.save();
    wordSegments.forEach((segment) => {
      const x1 = xForTime(segment.start);
      const x2 = xForTime(segment.end);
      if (x2 < 0 || x1 > layout.width) return;
      const width = Math.max(2, x2 - x1);
      const isActive = songTime >= segment.start && songTime < segment.end;
      const isDone = songTime >= segment.end;
      ctx.fillStyle = isActive
        ? "rgba(237, 176, 73, 0.18)"
        : isDone
          ? "rgba(18, 199, 156, 0.055)"
          : "rgba(246, 243, 234, 0.035)";
      ctx.fillRect(Math.max(0, x1), layout.roadTop - 10, Math.min(layout.width, width), layout.railY - layout.roadTop + 34);

      if (isActive) {
        ctx.strokeStyle = "rgba(237, 176, 73, 0.5)";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x1, layout.roadTop - 12);
        ctx.lineTo(x1, layout.railY + 24);
        ctx.stroke();
      }
    });
    ctx.restore();
  }

  function drawLyricWordPitchBars(ctx, wordSegments, contour, notes, xForTime, yForMidi, layout, songTime) {
    if (!wordSegments.length) return;
    ctx.save();
    wordSegments.forEach((segment) => {
      const midi = lyricWordMidi(segment, contour, notes);
      if (!Number.isFinite(midi)) return;
      const x1 = Math.max(-48, xForTime(segment.start));
      const x2 = Math.min(layout.width + 48, xForTime(segment.end));
      if (x2 < -20 || x1 > layout.width + 20) return;
      const width = Math.max(5, x2 - x1);
      const y = clampRoadY(yForMidi(midi), layout);
      const isActive = songTime >= segment.start && songTime < segment.end;
      const isDone = songTime >= segment.end;
      ctx.globalAlpha = segment.estimated ? 0.44 : 0.68;
      ctx.fillStyle = isActive
        ? "rgba(246, 243, 234, 0.82)"
        : isDone
          ? "rgba(18, 199, 156, 0.32)"
          : "rgba(155, 230, 214, 0.46)";
      drawRoundRect(ctx, x1, y - 6, width, 12, 6);
      ctx.fill();
      if (isActive) {
        ctx.globalAlpha = 1;
        ctx.strokeStyle = "rgba(18, 199, 156, 0.94)";
        ctx.lineWidth = 2;
        drawRoundRect(ctx, x1, y - 7, width, 14, 7);
        ctx.stroke();
      }
    });
    ctx.globalAlpha = 1;
    ctx.restore();
  }

  function lyricWordMidi(segment, contour, notes) {
    const points = (contour || [])
      .filter((point) => {
        const time = Number(point.time);
        const midi = Number(point.midi);
        return Number.isFinite(time) && Number.isFinite(midi) && time >= segment.start && time <= segment.end;
      })
      .map((point) => Number(point.midi))
      .sort((a, b) => a - b);
    if (points.length) return points[Math.floor(points.length / 2)];

    let bestNote = null;
    let bestOverlap = 0;
    (notes || []).forEach((note) => {
      const start = Number(note.start);
      const end = Number(note.end);
      const midi = Number(note.midi);
      if (!Number.isFinite(start) || !Number.isFinite(end) || !Number.isFinite(midi)) return;
      const overlap = Math.max(0, Math.min(end, segment.end) - Math.max(start, segment.start));
      if (overlap > bestOverlap) {
        bestOverlap = overlap;
        bestNote = midi;
      }
    });
    return bestNote;
  }

  function visibleRoadNotes(notes, minTime, maxTime) {
    return notes.filter((note) => {
      const start = Number(note.start);
      const end = Number(note.end);
      const midi = Number(note.midi);
      if (!Number.isFinite(start) || !Number.isFinite(end) || !Number.isFinite(midi)) return false;
      return !(end < minTime || start > maxTime);
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
        time <= maxTime
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
    if (!point || Number(point.confidence ?? 1) < VISUAL_CURSOR_MIN_CONFIDENCE) return null;
    const songTime = Number(point.songTime);
    const midi = Number(point.midi);
    if (!Number.isFinite(songTime) || !Number.isFinite(midi)) return null;
    const target = referenceTargetAtSongTime(songTime, notes, contour);
    if (!target || !Number.isFinite(Number(target.midi))) {
      return {
        songTime,
        cents: Number.NaN,
        midi,
        rawMidi: midi,
        raw: true,
      };
    }
    const policy = target.scorePolicy || vocalScorePolicyAtSongTime(songTime);
    if (policy.hasUnits && !policy.pitchScore) {
      return {
        songTime,
        cents: Number.NaN,
        midi,
        rawMidi: midi,
        raw: true,
        noPitchScore: true,
        scoreKind: policy.kind,
      };
    }

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
    const policy = target.scorePolicy || vocalScorePolicyAtSongTime(songTime);
    if (policy.hasUnits && !policy.pitchScore) return null;

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
      const scoreFraction = pitchScoreFractionForInterval(start, end);
      if (scoreFraction !== null && scoreFraction <= 0.05) return;
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

  function drawTargetNoteBlocks(ctx, visibleNotes, vocalSubUnits, xForTime, yForMidi, layout, songTime) {
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
      const scoreFraction = pitchScoreFractionForInterval(start, end);
      const noPitchScore = scoreFraction !== null && scoreFraction <= 0.05;

      if (previous && start - previous.end <= 1.35) {
        ctx.strokeStyle = noPitchScore ? "rgba(246, 243, 234, 0.026)" : "rgba(246, 243, 234, 0.055)";
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

      ctx.fillStyle = noPitchScore ? "rgba(246, 243, 234, 0.004)" : "rgba(237, 176, 73, 0.012)";
      drawRoundRect(ctx, x1, Math.min(outerTop, outerBottom), width, Math.max(6, Math.abs(outerBottom - outerTop)), 10);
      ctx.fill();

      ctx.fillStyle = noPitchScore
        ? "rgba(246, 243, 234, 0.012)"
        : isCurrent
          ? "rgba(18, 199, 156, 0.055)"
          : "rgba(18, 199, 156, 0.025)";
      drawRoundRect(ctx, x1, Math.min(innerTop, innerBottom), width, Math.max(4, Math.abs(innerBottom - innerTop)), 8);
      ctx.fill();

      ctx.fillStyle = noPitchScore
        ? isCurrent
          ? "rgba(246, 243, 234, 0.18)"
          : "rgba(246, 243, 234, 0.055)"
        : isCurrent
          ? "rgba(246, 243, 234, 0.34)"
          : isDone
            ? "rgba(18, 199, 156, 0.1)"
            : "rgba(155, 230, 214, 0.16)";
      drawRoundRect(ctx, x1, blockY, width, blockHeight, Math.min(9, blockHeight / 2));
      ctx.fill();

      ctx.strokeStyle = noPitchScore
        ? "rgba(246, 243, 234, 0.04)"
        : isCurrent
          ? "rgba(246, 243, 234, 0.2)"
          : "rgba(246, 243, 234, 0.055)";
      ctx.lineWidth = isCurrent ? 2 : 1;
      drawRoundRect(ctx, x1, blockY, width, blockHeight, Math.min(9, blockHeight / 2));
      ctx.stroke();

      if (isCurrent) {
        const doneWidth = Math.max(0, clamp(xForTime(songTime), x1, x2) - x1);
        ctx.fillStyle = "rgba(18, 199, 156, 0.18)";
        drawRoundRect(ctx, x1, blockY, doneWidth, blockHeight, Math.min(9, blockHeight / 2));
        ctx.fill();
      }

      const vocalLabel = bestVocalLabelForNote(note, vocalSubUnits);
      if (vocalLabel && width > 38) {
        ctx.fillStyle = vocalLabelStyle(vocalLabel, isCurrent);
        ctx.font = "900 13px sans-serif";
        ctx.fillText(vocalLabel.displayText, x1 + 8, blockY + blockHeight - 8);
      } else if (width > 54) {
        ctx.fillStyle = isCurrent ? "rgba(246, 243, 234, 0.42)" : "rgba(246, 243, 234, 0.16)";
        ctx.font = "800 12px sans-serif";
        ctx.fillText(noteName(midi), x1 + 8, blockY + blockHeight - 8);
      }

      previous = { end, x: x2, y };
    });
    ctx.restore();
  }

  function bestVocalLabelForNote(note, vocalSubUnits) {
    if (!Array.isArray(vocalSubUnits) || vocalSubUnits.length === 0) return null;
    const start = Number(note?.start);
    const end = Number(note?.end);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
    let best = null;
    let bestOverlap = 0;
    vocalSubUnits.forEach((unit) => {
      if (!["vowel_sustain", "sonorant_sustain", "fricative_effect"].includes(unit.type)) return;
      const overlap = Math.max(0, Math.min(end, Number(unit.end)) - Math.max(start, Number(unit.start)));
      if (overlap <= bestOverlap) return;
      const displayText = String(unit.displayText || unit.text || "").trim();
      if (!displayText) return;
      bestOverlap = overlap;
      best = { ...unit, displayText };
    });
    if (!best || bestOverlap < Math.min(0.08, (end - start) * 0.35)) return null;
    return best;
  }

  function vocalLabelStyle(unit, isCurrent) {
    if (unit.type === "fricative_effect" || unit.score === "timing_only") {
      return isCurrent ? "rgba(246, 243, 234, 0.76)" : "rgba(246, 243, 234, 0.34)";
    }
    if (unit.type === "sonorant_sustain") {
      return isCurrent ? "rgba(237, 176, 73, 0.92)" : "rgba(237, 176, 73, 0.48)";
    }
    return isCurrent ? "rgba(18, 199, 156, 0.98)" : "rgba(18, 199, 156, 0.58)";
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
      const policy = vocalScorePolicyAtSongTime(start);
      if (policy.hasUnits && !policy.pitchScore) return;
      const x1 = Math.max(-48, xForTime(start));
      const x2 = Math.min(layout.width + 48, xForTime(end));
      const width = Math.max(6, x2 - x1);
      const y = clampRoadY(yForMidi(midi), layout);
      const height = clamp(layout.roadHeight * 0.038, 13, 22);
      const isCurrent = songTime >= start && songTime <= end;
      const isDone = songTime > end;

      ctx.globalAlpha = isCurrent ? 1 : isDone ? 0.62 : 0.78 + confidence * 0.18;
      ctx.fillStyle = isCurrent
        ? "rgba(246, 243, 234, 0.98)"
        : isDone
          ? "rgba(18, 199, 156, 0.78)"
          : "rgba(87, 230, 214, 0.96)";
      drawRoundRect(ctx, x1, y - height / 2, width, height, Math.min(7, height / 2));
      ctx.fill();

      ctx.strokeStyle = "rgba(3, 6, 10, 0.74)";
      ctx.lineWidth = 2;
      drawRoundRect(ctx, x1, y - height / 2, width, height, Math.min(7, height / 2));
      ctx.stroke();

      if (isCurrent) {
        ctx.globalAlpha = 1;
        ctx.strokeStyle = "rgba(18, 199, 156, 0.94)";
        ctx.lineWidth = 3;
        drawRoundRect(ctx, x1, y - height / 2, width, height, Math.min(7, height / 2));
        ctx.stroke();
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
    if (absCents <= 45) return "rgba(18, 199, 156, 1)";
    if (absCents <= 130) return "rgba(237, 176, 73, 1)";
    return "rgba(207, 77, 67, 1)";
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
      const alpha = clamp(1 - age / Math.max(0.5, STAGE_ROAD_TRAIL_SECONDS), 0.28, 1);
      const radius = clamp(9 - age * 1.25, 3.25, 9);
      const x = xForTime(point.songTime);
      const y = clampRoadY(yForMidi(point.midi), layout);
      ctx.globalAlpha = alpha;
      ctx.fillStyle = trailColorForCents(point.cents);
      ctx.strokeStyle = "rgba(3, 6, 10, 0.82)";
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    });
    ctx.globalAlpha = 1;
    ctx.restore();
  }

  function drawStageSongRoad(now, target = null, pitchMidi = null, songTimeOverride = null) {
    const canvasState = resizeSongRoadCanvas();
    if (!canvasState) return;
    const { ctx, width, height } = canvasState;
    ctx.clearRect(0, 0, width, height);

    const songTime = Number.isFinite(songTimeOverride) ? songTimeOverride : songPlaybackTime(now);
    const notes = songGuideNotes();
    const contour = songGuideContour();
    const timeScale = vocalRoadTimeScale(ctx, width, songTime, notes, contour);
    const { hitX, minTime, maxTime, xForTime } = timeScale;
    const range = songRoadMidiRange(songTime, minTime, maxTime);
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

    const hasPitchRoad = notes.length > 0 || contour.length > 0;
    if (selectedMode() !== "song") {
      drawRoadMessage(ctx, width, height, state.songGuideLoading ? TEXT.loadingGuide : TEXT.noGuide);
      ctx.restore();
      return;
    }
    if (!hasPitchRoad) {
      drawRoadMessage(ctx, width, height, state.songGuideLoading ? TEXT.loadingGuide : TEXT.noGuide);
    }

    for (let second = Math.floor(minTime); second <= Math.ceil(maxTime); second++) {
      const x = xForTime(second);
      if (x < 0 || x > width) continue;
      ctx.strokeStyle = second % 2 === 0 ? "rgba(246, 243, 234, 0.055)" : "rgba(246, 243, 234, 0.022)";
      ctx.beginPath();
      ctx.moveTo(x, layout.roadTop);
      ctx.lineTo(x, layout.railY + 20);
      ctx.stroke();
    }

    const lyricSegments = visibleLyricSegments(minTime, maxTime);
    const timedSegments = lyricSegments.filter((segment) => segment.unitType !== "line");
    drawLyricWordTimingBands(ctx, timedSegments, xForTime, layout, songTime);

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
    const visibleVocalSubUnits = visibleLyricVocalSubUnits(minTime, maxTime);
    drawLyricWordPitchBars(ctx, timedSegments, visibleContour, visibleNotes, xForTime, yForMidi, layout, songTime);
    drawPitchBandCorridors(ctx, visibleNotes, xForTime, yForMidi, layout);
    drawTargetNoteBlocks(ctx, visibleNotes, visibleVocalSubUnits, xForTime, yForMidi, layout, songTime);
    if (visibleContour.length > 0) {
      drawTargetContourTiles(ctx, visibleContour, xForTime, yForMidi, layout, songTime);
    }

    ctx.strokeStyle = "rgba(246, 243, 234, 0.84)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(hitX, layout.roadTop - 8);
    ctx.lineTo(hitX, layout.railY + 24);
    ctx.stroke();
    ctx.lineWidth = 1;

    drawSingerTrail(ctx, xForTime, yForMidi, layout, minTime, maxTime, notes, contour, songTime);
    drawStageLyricRail(ctx, width, xForTime, songTime, layout.railY, minTime, maxTime, hitX, contour, notes);
    drawLivePitchCursor(ctx, hitX, yForMidi, layout, songTime, pitchMidi, target, notes, contour);
    ctx.restore();
  }

  function drawLivePitchCursor(ctx, hitX, yForMidi, layout, songTime, pitchMidi, target, notes, contour) {
    if (Number.isFinite(pitchMidi)) {
      const livePoint = graphPitchPoint({ songTime, midi: pitchMidi, confidence: 1 }, notes, contour);
      if (!livePoint) return;
      const y = clampRoadY(yForMidi(livePoint.midi), layout);
      const isHeld = Boolean(state.latestPitchHeld);
      ctx.save();
      ctx.globalAlpha = isHeld ? 0.72 : 1;
      ctx.fillStyle = trailColorForCents(livePoint.cents);
      ctx.strokeStyle = "rgba(246, 243, 234, 0.98)";
      ctx.lineWidth = 4;
      ctx.beginPath();
      ctx.arc(hitX, y, isHeld ? 8 : 12, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.restore();
      return;
    }
    if (!target) return;
    const policy = target.scorePolicy || vocalScorePolicyAtSongTime(target.songTime);
    if (policy.hasUnits && !policy.pitchScore) return;
    const y = yForMidi(target.midi);
    ctx.save();
    ctx.strokeStyle = "rgba(237, 176, 73, 0.48)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(hitX, y, 9, 0, Math.PI * 2);
    ctx.stroke();
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
    let visualPitchHeld = false;
    let centsError = 0;
    let effectiveResult = result;
    if (result.voiced) {
      const detectedPitchMidi = frequencyToMidi(result.frequency);
      const detectedCentsError = target
        ? 1200 * Math.log2(result.frequency / midiToFrequency(target.midi))
        : centsBetweenMidi(detectedPitchMidi, Math.round(detectedPitchMidi));
      const accepted = acceptVisualPitch(detectedPitchMidi, result, target, now);
      const visible = canShowVisualPitch(detectedPitchMidi, result);
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
        pushSingerHistoryPoint(now, detectedPitchMidi, result);
      } else {
        if (visible) {
          visualPitchMidi = detectedPitchMidi;
          pushSingerHistoryPoint(now, detectedPitchMidi, result);
        } else {
          visualPitchMidi = heldVisualPitch(now);
          visualPitchHeld = visualPitchMidi !== null;
        }
        effectiveResult = { ...result, voiced: false, filtered: true };
      }
    } else {
      visualPitchMidi = heldVisualPitch(now);
      visualPitchHeld = visualPitchMidi !== null;
    }

    if (visualPitchMidi !== null) {
      state.latestPitchMidi = visualPitchMidi;
      state.latestPitchHeld = visualPitchHeld;
    } else {
      state.latestPitchMidi = null;
      state.latestPitchHeld = false;
    }

    updateReadout(effectiveResult, pitchMidi, target, centsError);
    updateMetrics(effectiveResult, pitchMidi, target, centsError, now);
    updateGameScore(result, visualPitchMidi, visualPitchHeld, target, now);
    draw(now, target, pitchMidi);
    drawStageSongRoad(now, target, state.latestPitchMidi);
    state.rafId = requestAnimationFrame(tick);
  }

  async function startCoach(options = {}) {
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
      stopCoach({ preserveStatus: true });
    }
  }

  function stopCoach(options = {}) {
    const preserveStatus = Boolean(options.preserveStatus);
    const previousStatusText = els["coach-status"]?.textContent || TEXT.idle;
    const previousStatusClass = els["coach-status"]?.className || "coach-status";
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
    if (!preserveStatus) setStatus(TEXT.idle);
    updateReadout({ voiced: false }, null, currentTarget(performance.now()), 0);
    if (preserveStatus && els["coach-status"]) {
      els["coach-status"].textContent = previousStatusText;
      els["coach-status"].className = previousStatusClass;
    }
    draw(performance.now(), currentTarget(performance.now()), null);
    drawStageSongRoad(performance.now(), currentTarget(performance.now()), null);
  }

  function scheduleAutoStartCoach() {
    if (state.autoStartAttempted || state.running) return;
    state.autoStartAttempted = true;
    window.setTimeout(() => {
      if (!state.running) startCoach({ auto: true });
    }, AUTO_START_MIC_DELAY_MS);
  }

  function toggleFullscreen() {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen?.();
    } else {
      document.exitFullscreen?.();
    }
  }

  function setupEvents() {
    els["coach-settings-toggle"]?.addEventListener("click", (event) => {
      event.stopPropagation();
      setSettingsMenuOpen(Boolean(els["coach-settings-menu"]?.hidden));
    });
    els["coach-settings-menu"]?.addEventListener("click", (event) => {
      event.stopPropagation();
    });
    document.addEventListener("click", () => {
      setSettingsMenuOpen(false);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") setSettingsMenuOpen(false);
    });
    els["coach-player-back"]?.addEventListener("click", () => {
      sendPlayerCommand("/player/previous");
    });
    els["coach-player-pause"]?.addEventListener("click", () => {
      sendPlayerCommand("/player/pause");
    });
    els["coach-player-stop"]?.addEventListener("click", () => {
      sendPlayerCommand("/player/stop");
    });
    els["coach-player-repeat"]?.addEventListener("click", () => {
      sendPlayerCommand("/player/restart");
    });
    els["coach-player-forward"]?.addEventListener("click", () => {
      sendPlayerCommand("/player/next");
    });
    els["coach-start"].addEventListener("click", () => {
      state.running ? stopCoach() : startCoach();
    });
    els["coach-score-close"]?.addEventListener("click", hideScoreResult);
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
    els["coach-fixed-lyrics-toggle"].addEventListener("change", () => {
      state.fixedLyricsEnabled = Boolean(els["coach-fixed-lyrics-toggle"].checked);
      persistFixedLyricsPreference();
      updateFixedLyricsControl();
      updateLyrics(getVideoPlayer().currentTime || 0);
      drawStageSongRoad(performance.now(), currentTarget(performance.now()), state.latestPitchMidi);
    });
    els["coach-difficulty"]?.addEventListener("change", () => {
      state.coachDifficulty = normalizeCoachDifficulty(els["coach-difficulty"].value);
      persistCoachDifficultyPreference();
      updateCoachDifficultyControl();
      state.score = emptyScore();
      hideScoreResult();
      drawStageSongRoad(performance.now(), currentTarget(performance.now()), state.latestPitchMidi);
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
      updateHeaderMarquees();
      draw(performance.now(), currentTarget(performance.now()), null);
      drawStageSongRoad(performance.now(), currentTarget(performance.now()), state.latestPitchMidi);
    });
    window.addEventListener("beforeunload", stopCoach);
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindElements();
    loadFixedLyricsPreference();
    loadCoachDifficultyPreference();
    setupEvents();
    setupVideoEvents();
    setupPlaybackSocket();
    startPlaybackUiLoop();
    startPositionReporting();
    resetSession();
    setLyricsOffsetDisplay();
    updateVocalReferenceControl();
    updateFixedLyricsControl();
    updateCoachDifficultyControl();
    updatePlayerControls();
    updateReadout({ voiced: false }, null, null, 0);
    draw(performance.now(), null, null);
    drawStageSongRoad(performance.now(), null, null);
    loadInitialNowPlaying().finally(scheduleAutoStartCoach);
    startNowPlayingPolling();
  });
})();

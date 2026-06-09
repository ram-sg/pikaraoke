let socket = io();
let mouseTimer = null;
let cursorVisible = false;
let nowPlaying = {};
let octopusInstance = null;
let showMenu = false;
let menuButtonVisible = false;
let autoplayConfirmed = false;
let volume = 0.85;
const playbackStartTimeout = 10000;
const bgMediaResumeDelay = 2000;
const scoreCaptureMaxSeconds = 90;
let isScoreShown = false;
const hasBgVideo = BiaokeConfig.hasBgVideo;
let currentVideoUrl = null;
let hlsInstance = null;
let idleTime = 0;
let screensaverTimeoutSeconds = BiaokeConfig.screensaverTimeout;
let bg_playlist = [];
let bgMediaResumeTimeout = null;
let scoreReviews = {
  low: ["Better luck next time!"],
  mid: ["Not bad!"],
  high: ["Great job!"],
};
let isMaster = false;
let uiScale = null;
let clockIntervalId = null;
let scoreMediaStream = null;
let scoreRecorder = null;
let scoreChunks = [];
let scoreRecordingMeta = null;
let scoreCaptureReady = false;
let scoreRecordingBlob = null;
let scoreStopPromise = null;
let scoreAutoStopTimeout = null;
let micMonitorContext = null;
let micMonitorSource = null;
let micMonitorGain = null;

// Browser detection
const isSafari = /^((?!chrome|android).)*safari/i.test(navigator.userAgent);
const isMobileSafari = isSafari && (/iPhone|iPad|iPod/i.test(navigator.userAgent) || navigator.maxTouchPoints > 1);
const isChrome = /chrome/i.test(navigator.userAgent) && !/edg/i.test(navigator.userAgent);
const isFirefox = /firefox/i.test(navigator.userAgent);
const isEdge = /edg/i.test(navigator.userAgent);
const isSupportedBrowser = isSafari || isChrome || isFirefox || isEdge;

const isMediaPlaying = (media) =>
  !!(
    media.currentTime > 0 &&
    !media.paused &&
    !media.ended &&
    media.readyState > 2
  );

const formatTime = (seconds) => {
  if (isNaN(seconds)) {
    return "00:00";
  }
  const totalSeconds = Math.floor(seconds);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const secs = totalSeconds % 60;
  const formattedMinutes = String(minutes).padStart(2, "0");
  const formattedSeconds = String(secs).padStart(2, "0");
  return `${formattedMinutes}:${formattedSeconds}`;
}

const testAutoplayCapability = async () => {
  // Test if autoplay with audio is allowed using a real video file
  try {
    const testVideo = document.createElement('video');
    testVideo.playsInline = true;
    testVideo.muted = true;  // Start muted (always allowed)
    testVideo.src = "/static/video/test_autoplay.mp4";

    // Wait for video to be ready
    await new Promise((resolve, reject) => {
      testVideo.onloadeddata = resolve;
      testVideo.onerror = reject;
    });

    await testVideo.play();
    // Now try to unmute - this is the real test
    testVideo.muted = false;
    testVideo.volume = 0.01;

    // Brief delay to let browser enforce policy
    await new Promise(resolve => setTimeout(resolve, 500));

    // Check if browser paused or muted the video
    if (testVideo.muted || testVideo.paused) {
      testVideo.pause();
      $('#permissions-modal').addClass('is-active');
    } else {
      testVideo.pause();
      handleConfirmation();
    }
  } catch (e) {
    // Autoplay blocked
    console.log("Autoplay error thrown", e);
    $('#permissions-modal').addClass('is-active');
  }
};

const handleConfirmation = () => {
  $('#permissions-modal').removeClass('is-active');
  autoplayConfirmed = true;
  setupScoreCapture();
  updateBackgroundMediaState(true);
  loadNowPlaying();
};
window.handleConfirmation = handleConfirmation;

const hideVideo = () => {
  $("#video-container").hide();
}

const showVideo = () => {
  $("#video-container").css("display", "flex");
}

const getScoreMimeType = () => {
  const types = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/mp4",
  ];
  if (!window.MediaRecorder) return "";
  return types.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

const needsMicrophoneStream = () => !BiaokeConfig.disableScore || BiaokeConfig.enableMicMonitor;

const clampMicMonitorVolume = (value) => {
  const volume = Number(value);
  if (!Number.isFinite(volume)) return 0.75;
  return Math.max(0, Math.min(1, volume));
}

const getMicAudioConstraints = () => {
  const browserProcessing = !BiaokeConfig.enableMicMonitor;
  const constraints = {
    echoCancellation: browserProcessing,
    noiseSuppression: browserProcessing,
    autoGainControl: false,
  };
  if (BiaokeConfig.enableMicMonitor) {
    constraints.latency = { ideal: 0.005, max: 0.02 };
    constraints.channelCount = { ideal: 1 };
    constraints.sampleRate = { ideal: 48000 };
  }
  return constraints;
}

const setMicMonitorVolume = (value) => {
  BiaokeConfig.micMonitorVolume = clampMicMonitorVolume(value);
  if (micMonitorGain) micMonitorGain.gain.value = BiaokeConfig.micMonitorVolume;
}

const stopMicMonitor = () => {
  if (micMonitorSource) {
    try { micMonitorSource.disconnect(); } catch (_e) {}
    micMonitorSource = null;
  }
  if (micMonitorGain) {
    try { micMonitorGain.disconnect(); } catch (_e) {}
    micMonitorGain = null;
  }
  if (micMonitorContext) {
    const context = micMonitorContext;
    micMonitorContext = null;
    if (context.state !== "closed") {
      context.close().catch((e) => console.log("Could not close microphone output.", e));
    }
  }
}

const stopMicrophoneStream = () => {
  stopMicMonitor();
  if (scoreMediaStream) {
    scoreMediaStream.getTracks().forEach((track) => track.stop());
    scoreMediaStream = null;
  }
  scoreCaptureReady = false;
}

const startMicMonitor = async () => {
  if (!BiaokeConfig.enableMicMonitor || !scoreMediaStream) return;
  try {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) {
      console.log("Microphone output is not supported in this browser.");
      return;
    }
    if (!micMonitorContext) {
      try {
        micMonitorContext = new AudioContextClass({ latencyHint: "interactive" });
      } catch (_e) {
        micMonitorContext = new AudioContextClass();
      }
    }
    if (micMonitorContext.state === "suspended") {
      await micMonitorContext.resume();
    }
    if (!micMonitorSource) {
      micMonitorSource = micMonitorContext.createMediaStreamSource(scoreMediaStream);
      micMonitorGain = micMonitorContext.createGain();
      micMonitorSource.connect(micMonitorGain);
      micMonitorGain.connect(micMonitorContext.destination);
    }
    setMicMonitorVolume(BiaokeConfig.micMonitorVolume);
  } catch (e) {
    console.log("Could not start microphone output.", e);
    stopMicMonitor();
  }
}

const setupScoreCapture = async () => {
  if (scoreCaptureReady || !needsMicrophoneStream()) return;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    console.log("Microphone access is not supported in this browser.");
    return;
  }
  if (!BiaokeConfig.disableScore && !window.MediaRecorder) {
    console.log("Microphone scoring is not supported in this browser.");
  }
  try {
    scoreMediaStream = await navigator.mediaDevices.getUserMedia({
      audio: getMicAudioConstraints(),
      video: false,
    });
    scoreCaptureReady = true;
  } catch (e) {
    console.log("Microphone permission not granted; microphone features disabled.", e);
  }
}

const startScoreCapture = () => {
  if (!isMaster || BiaokeConfig.disableScore || !scoreMediaStream || !window.MediaRecorder) return;
  if (scoreRecorder && scoreRecorder.state === "recording") return;

  scoreChunks = [];
  scoreRecordingBlob = null;
  scoreStopPromise = null;
  scoreRecordingMeta = {
    title: nowPlaying.now_playing || "",
    duration: nowPlaying.now_playing_duration || "",
    startedAt: Date.now(),
  };

  const mimeType = getScoreMimeType();
  const options = mimeType ? { mimeType } : undefined;
  try {
    scoreRecorder = new MediaRecorder(scoreMediaStream, options);
    scoreRecorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) scoreChunks.push(event.data);
    };
    scoreRecorder.start(1000);
    scoreAutoStopTimeout = setTimeout(() => {
      stopScoreCapture(false);
    }, scoreCaptureMaxSeconds * 1000);
  } catch (e) {
    console.log("Could not start microphone scoring.", e);
  }
}

const uploadScoreRecording = async (blob) => {
  const formData = new FormData();
  const extension = blob.type.includes("ogg") ? "ogg" : blob.type.includes("mp4") ? "m4a" : "webm";
  formData.append("audio", blob, `score-recording.${extension}`);
  if (scoreRecordingMeta) {
    formData.append("title", scoreRecordingMeta.title);
    formData.append("duration", scoreRecordingMeta.duration);
    formData.append("started_at", scoreRecordingMeta.startedAt);
  }

  const response = await fetch(BiaokeConfig.scoreAnalyzeUrl, {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Score analysis failed: ${response.status}`);
  }
  return response.json();
}

const stopScoreCapture = async (analyze = false) => {
  if (scoreAutoStopTimeout) {
    clearTimeout(scoreAutoStopTimeout);
    scoreAutoStopTimeout = null;
  }

  if (scoreStopPromise) {
    await scoreStopPromise;
    if (analyze && scoreRecordingBlob) {
      const blob = scoreRecordingBlob;
      scoreRecordingBlob = null;
      return uploadScoreRecording(blob);
    }
    return null;
  }

  if (!scoreRecorder || scoreRecorder.state !== "recording") {
    if (analyze && scoreRecordingBlob) {
      const blob = scoreRecordingBlob;
      scoreRecordingBlob = null;
      return uploadScoreRecording(blob);
    }
    return null;
  }

  const recorder = scoreRecorder;
  scoreStopPromise = new Promise((resolve) => {
    recorder.onstop = async () => {
      try {
        const blob = new Blob(scoreChunks, { type: recorder.mimeType || "audio/webm" });
        scoreRecorder = null;
        if (!analyze || blob.size < 1024) {
          if (blob.size >= 1024) scoreRecordingBlob = blob;
          resolve(null);
          return;
        }
        resolve(await uploadScoreRecording(blob));
      } catch (e) {
        console.log("Score upload failed; falling back to entertainment score.", e);
        resolve(null);
      } finally {
        scoreChunks = [];
        scoreStopPromise = null;
      }
    };
    recorder.stop();
  });
  return scoreStopPromise;
}

const endSong = async (reason = null, showScore = false) => {
  stopMicMonitor();
  if (showScore && !BiaokeConfig.disableScore) {
    const realScorePromise = stopScoreCapture(true);
    isScoreShown = true;
    await startScore("/static/", realScorePromise);
    isScoreShown = false;
  } else {
    await stopScoreCapture(false);
  }
  scoreRecordingMeta = null;
  currentVideoUrl = null;
  if (hlsInstance) {
    hlsInstance.destroy();
    hlsInstance = null;
  }
  const video = getVideoPlayer();
  video.pause();
  $("#video-source").attr("src", "");
  video.load();
  hideVideo();
  if (isMaster) {
    socket.emit("end_song", reason);
  } else {
    console.log("Slave active (read-only): skipping end_song emission");
  }
}

const getBackgroundMusicPlayer = () => document.getElementById('background-music');
const getBackgroundVideoPlayer = () => document.getElementById('bg-video');
const getVideoPlayer = () => $("#video")[0]

const getNextBgMusicSong = () => {
  let currentSong = getBackgroundMusicPlayer().getAttribute('src');
  let nextSong = bg_playlist[0];
  if (currentSong) {
    let currentIndex = bg_playlist.indexOf(currentSong);
    if (currentIndex >= 0 && currentIndex < bg_playlist.length - 1) {
      nextSong = bg_playlist[currentIndex + 1];
    }
  }
  return nextSong;
}

const playBGMusic = async (play) => {
  const audio = getBackgroundMusicPlayer();
  if (play) {
    if (BiaokeConfig.disableBgMusic) return;
    if (!autoplayConfirmed) return;
    if (bg_playlist.length === 0) return;

    if (!audio.getAttribute('src')) audio.setAttribute('src', getNextBgMusicSong());

    if (isMediaPlaying(audio)) return;
    audio.volume = 0;
    if (audio.readyState <= 2) await audio.load();
    await audio.play().catch(e => console.log("Autoplay blocked (music)"));
    $(audio).animate({ volume: BiaokeConfig.bgMusicVolume }, 2000);
  } else {
    if (audio) {
      $(audio).animate({ volume: 0 }, 2000, () => audio.pause());
    }
  }
}

const playBGVideo = async (play) => {
  const bgVideo = getBackgroundVideoPlayer();
  const bgVideoContainer = $('#bg-video-container');

  if (play) {
    if (BiaokeConfig.disableBgVideo) return;
    if (!autoplayConfirmed) return;

    if (isMediaPlaying(bgVideo)) return;
    $("#bg-video").attr("src", "/stream/bg_video");
    if (bgVideo.readyState <= 2) await bgVideo.load();
    bgVideo.play().catch(() => console.log("Autoplay blocked (video)"));
    bgVideoContainer.fadeIn(2000);
  } else {
    if (bgVideo && isMediaPlaying(bgVideo)) {
      bgVideo.pause();
      bgVideoContainer.fadeOut(2000);
    }
  }
}

const shouldBackgroundMediaPlay = () => {
  return autoplayConfirmed &&
    !nowPlaying.now_playing &&
    !nowPlaying.up_next;
};

const updateBackgroundMediaState = (immediate = false) => {
  // Clear any pending resume
  if (bgMediaResumeTimeout) {
    clearTimeout(bgMediaResumeTimeout);
    bgMediaResumeTimeout = null;
  }

  if (shouldBackgroundMediaPlay()) {
    if (immediate) {
      playBGMusic(true);
      if (hasBgVideo) playBGVideo(true);
    } else {
      bgMediaResumeTimeout = setTimeout(() => {
        bgMediaResumeTimeout = null;
        if (shouldBackgroundMediaPlay()) {
          playBGMusic(true);
          if (hasBgVideo) playBGVideo(true);
        }
      }, bgMediaResumeDelay);
    }
  } else {
    playBGMusic(false);
    playBGVideo(false);
  }
};

const flashNotification = (message, categoryClass) => {
  const sn = $("#splash-notification");
  if (sn.html()) return;
  sn.html(message);
  sn.addClass(categoryClass);
  sn.fadeIn();
  setTimeout(() => {
    sn.fadeOut();
    setTimeout(() => {
      sn.html("");
      sn.removeClass(categoryClass);
    }, 450);
  }, 3000);
}

const setupScreensaver = () => {
  if (screensaverTimeoutSeconds > 0) {
    setInterval(() => {
      let screensaver = document.getElementById('screensaver');
      let video = getVideoPlayer();
      if (isMediaPlaying(video) || cursorVisible) {
        idleTime = 0;
      }
      if (idleTime >= screensaverTimeoutSeconds) {
        if (screensaver.style.visibility === 'hidden') {
          screensaver.style.visibility = 'visible';
          playBGVideo(false);
          startScreensaver(); // depends on upstream screensaver.js import
        }
        if (idleTime > screensaverTimeoutSeconds + 36000) idleTime = screensaverTimeoutSeconds;
      } else {
        if (screensaver.style.visibility === 'visible') {
          screensaver.style.visibility = 'hidden';
          stopScreensaver(); // depends on upstream screensaver.js import
          updateBackgroundMediaState(true);
        }
      }
      idleTime++;
    }, 1000)
  }
}

const handleNowPlayingUpdate = (np) => {
  nowPlaying = np;
  if (np.now_playing) {

    // Handle updating now playing HTML
    let nowPlayingHtml = `<span>${np.now_playing}</span> `;
    if (np.now_playing_transpose !== 0) {
      nowPlayingHtml += `<span class='is-size-6 has-text-success'><b>Key</b>: ${getSemitonesLabel(np.now_playing_transpose)} </span>`;
    }
    $("#now-playing-song").html(nowPlayingHtml);
    $("#now-playing-singer").html(np.now_playing_user);
    $("#now-playing").fadeIn();
  } else {
    $("#now-playing").fadeOut();
  }
  if (np.up_next) {
    $("#up-next-song").html(np.up_next);
    $("#up-next-singer").html(np.next_user);
    $("#up-next").fadeIn();
  } else {
    $("#up-next").fadeOut();
  }

  // Update bg music and video state
  if (np.now_playing || np.up_next) {
    idleTime = 0;
  }
  updateBackgroundMediaState();

  const video = getVideoPlayer();

  // Setup ASS subtitle file if found
  const subtitleUrl = np.now_playing_subtitle_url;
  if (octopusInstance) {
    octopusInstance.dispose();
    octopusInstance = null;
  }
  if (subtitleUrl && video) {
    const options = {
      video: video,
      subUrl: subtitleUrl,
      fonts: ["/static/fonts/Arial.ttf", "/static/fonts/DroidSansFallback.ttf"],
      debug: true,
      workerUrl: "/static/js/subtitles-octopus-worker.js"
    };
    try {
      octopusInstance = new SubtitlesOctopus(options);
      if (uiScale) {
        // Find the canvas created by SubtitlesOctopus (sibling of the video)
        const canvas = video.parentNode.querySelector('canvas');
        if (canvas) {
          canvas.style.transform = `scale(${uiScale})`;
          canvas.style.transformOrigin = 'bottom center';
        }
      }
    } catch (e) { console.error(e); }
  }

  if (np.now_playing_url && np.now_playing_url !== currentVideoUrl) {
    currentVideoUrl = np.now_playing_url;
    const streamUrl = np.now_playing_url;
    $("#video-source").attr("src", "");
    video.load();
    $("#video-source").attr("src", streamUrl);

    if (streamUrl.endsWith('.m3u8')) {
      const useNativeHLS = video.canPlayType('application/vnd.apple.mpegurl') && !isChrome && !isEdge && !isMobileSafari;
      if (useNativeHLS) {
        video.src = streamUrl;
      } else {
        if (hlsInstance) { hlsInstance.destroy(); hlsInstance = null; }
        hlsInstance = new Hls({ startPosition: 0 });
        hlsInstance.loadSource(streamUrl);
        hlsInstance.attachMedia(video);
      }
    }

    video.load();
    if (volume !== np.volume) {
      volume = np.volume;
      video.volume = volume;
    }

    const duration = $("#duration");
    if (np.now_playing_duration) {
      duration.text(`/${formatTime(np.now_playing_duration)}`);
      duration.show();
    } else {
      duration.hide();
    }

    showVideo();

    video.play().catch(err => {
      console.error('Play failed:', err);
      // Retry once if it was an autoplay block
      setTimeout(() => video.play(), 1000);
    });

    if (np.now_playing_position && isMediaPlaying(video)) {
      if (Math.abs(video.currentTime - np.now_playing_position) > 2) {
        console.log("Syncing to server position:", np.now_playing_position);
        video.currentTime = np.now_playing_position;
      }
    }

    setTimeout(() => {
      if (!isMediaPlaying(video) && !video.paused) {
        endSong("failed to start");
      }
    }, playbackStartTimeout);
  }
}

async function loadNowPlaying() {
  const data = await $.get("/now_playing");
  handleNowPlayingUpdate(JSON.parse(data));
}

const setupOverlayMenus = () => {
  if (BiaokeConfig.hideOverlay) {
    $('#bottom-container').hide();
    $('#top-container').hide();
  }
  $("#menu a").fadeOut(); // start hidden
  const triggerInactivity = () => {
    mouseTimer = null;
    document.body.style.cursor = 'none';
    cursorVisible = false;
    $("#menu a").fadeOut();
    if (BiaokeConfig.showSplashClock) {
      setTimeout(() => {
        if (!cursorVisible) $("#clock").fadeIn();
      }, 1000);
    }
    menuButtonVisible = false;
  };

  document.onmousemove = function () {
    if (mouseTimer) window.clearTimeout(mouseTimer);
    if (!cursorVisible) {
      document.body.style.cursor = 'default';
      cursorVisible = true;
    }
    if (!menuButtonVisible) {
      $("#menu a").fadeIn();
      $("#clock").hide();
      menuButtonVisible = true;
    }
    mouseTimer = window.setTimeout(triggerInactivity, 5000);
  };

  // Set initial state to hidden
  triggerInactivity();
  $('#menu a').click(function () {
    if (showMenu) {
      $('#menu-container').hide();
      $('#menu-container iframe').attr('src', '');
      showMenu = false;
    } else {
      setUserCookie();
      $("#menu-container").show();
      $("#menu-container iframe").attr("src", "/");
      showMenu = true;
    }
  });
  $('#menu-background').click(function () {
    if (showMenu) {
      $(".navbar-burger").click();
    }
  });
}

const setupVideoPlayer = () => {
  $('#video-container').hide();
  const video = getVideoPlayer();
  video.addEventListener("play", async () => {
    showVideo();
    await setupScoreCapture();
    await startMicMonitor();
    startScoreCapture();
    if (isMaster) {
      const streamUrl = currentVideoUrl;
      setTimeout(() => {
        if (streamUrl && currentVideoUrl === streamUrl && isMediaPlaying(video)) {
          socket.emit("start_song", { stream_url: streamUrl });
        }
      }, 1200);
    }
  });

  // Master reports playback position to server
  setInterval(() => {
    if (isMaster && isMediaPlaying(video)) {
      socket.emit("playback_position", video.currentTime);
    }
  }, 1000);

  video.addEventListener("ended", () => { endSong("complete", true); });
  video.addEventListener("timeupdate", (e) => { $("#current").text(formatTime(video.currentTime)); });
  $("#video source")[0].addEventListener("error", (e) => {
    if (isMediaPlaying(video)) {
      endSong("error while playing");
    }
  });
  window.addEventListener(
    'beforeunload',
    function (event) {
      if (isMediaPlaying(video)) {
        endSong("splash screen closed");
      }
    },
    true
  );
}

const setupBackgroundMusicPlayer = () => {
  $.get("/bg_playlist", function (data) {
    if (data) bg_playlist = data;
  });
  const bgMusic = getBackgroundMusicPlayer();
  bgMusic.addEventListener("ended", async () => {
    bgMusic.setAttribute('src', getNextBgMusicSong());
    await bgMusic.load();
    await bgMusic.play();
  });
}

const handleUnsupportedBrowser = () => {
  if (!isSupportedBrowser) {
    let modalContents = document.getElementById("permissions-modal-content");
    let warningMessage = document.createElement("p");
    warningMessage.classList.add("notification", "is-warning");
    warningMessage.innerHTML =
      BiaokeConfig.translations.unsupportedBrowser;
    modalContents.prepend(warningMessage);
  }
}

const startClock = () => {
  if (clockIntervalId) return;
  const update = () => {
    const el = document.getElementById('clock');
    if (el) el.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: true });
  };
  update();
  clockIntervalId = setInterval(update, 1000);
}

const stopClock = () => {
  if (!clockIntervalId) return;
  clearInterval(clockIntervalId);
  clockIntervalId = null;
}

const toggleBGMedia = (configKey, playFn, disabled) => {
  BiaokeConfig[configKey] = disabled;
  disabled ? playFn(false) : shouldBackgroundMediaPlay() && playFn(true);
};

const PREFERENCE_EFFECTS = {
  disable_bg_video:    (v) => toggleBGMedia("disableBgVideo", playBGVideo, v),
  disable_bg_music:    (v) => toggleBGMedia("disableBgMusic", playBGMusic, v),
  disable_score:       (v) => {
    BiaokeConfig.disableScore = v;
    if (needsMicrophoneStream()) setupScoreCapture();
    else stopMicrophoneStream();
  },
  enable_mic_monitor:  async (v) => {
    BiaokeConfig.enableMicMonitor = v;
    if (v) {
      await setupScoreCapture();
      if (isMediaPlaying(getVideoPlayer())) await startMicMonitor();
    } else {
      stopMicMonitor();
      if (!needsMicrophoneStream()) stopMicrophoneStream();
    }
  },
  mic_monitor_volume:  (v) => { setMicMonitorVolume(v); },
  show_splash_clock:   (v) => {
    BiaokeConfig.showSplashClock = v;
    v ? startClock() : (stopClock(), $("#clock").hide());
  },
  hide_overlay:        (v) => {
    BiaokeConfig.hideOverlay = v;
    $("#bottom-container, #top-container").toggle(!v);
  },
  hide_url:            (v) => { $("#qr-code, #screensaver-qr").toggle(!v); },
  bg_music_volume:     (v) => {
    BiaokeConfig.bgMusicVolume = v;
    const player = getBackgroundMusicPlayer();
    if (isMediaPlaying(player)) $(player).animate({ volume: v }, 1000);
  },
  screensaver_timeout: (v) => {
    screensaverTimeoutSeconds = v;
    BiaokeConfig.screensaverTimeout = v;
  },
};

const parsePreferenceValue = (value) => {
  if (typeof value !== "string") return value;
  if (value === "True") return true;
  if (value === "False") return false;
  const num = Number(value);
  return !isNaN(num) && value.trim() !== "" ? num : value;
};

const applyPreferenceUpdate = (data) => {
  const effect = PREFERENCE_EFFECTS[data.key];
  if (effect) effect(parsePreferenceValue(data.value));
};

const applyPreferencesReset = (defaults) => {
  Object.entries(defaults).forEach(([key, value]) => applyPreferenceUpdate({ key, value }));
};

const setupSocketEvents = () => {
  socket.on('connect', () => {
    console.log('Socket connected');
    socket.emit("register_splash");
  });
  socket.on('splash_role', (role) => {
    isMaster = (role === "master");
    console.log("Splash role assigned:", role, isMaster ? "(Master active)" : "(Slave active - read-only)");
  });
  socket.on('connect_error', (error) => {
    console.error('Connection error:', error);
    flashNotification(BiaokeConfig.translations.socketConnectionLost, "is-danger");
  });
  socket.on('disconnect', (reason) => {
    console.warn('Socket disconnected:', reason);
    flashNotification(BiaokeConfig.translations.socketConnectionLost, "is-danger");
  });
  socket.on('pause', () => {
    const video = getVideoPlayer();
    const currVolume = video.volume;
    if (!video.paused) {
      stopMicMonitor();
      $(video).animate({ volume: 0 }, 1000, () => {
        video.pause();
        video.volume = currVolume;
      });
    }
  });
  socket.on('play', () => {
    const video = getVideoPlayer();
    const currVolume = video.volume;
    if (video.paused) {
      video.play();
      video.volume = 0;
      $(video).animate({ volume: currVolume }, 1000);
    }
  });
  socket.on('skip', (reason) => {
    stopScoreCapture(false);
    stopMicMonitor();
    const video = getVideoPlayer();
    const currVolume = video.volume;
    if (isMediaPlaying(video)) {
      $(video).animate({ volume: 0 }, 1000, () => {
        video.pause();
        video.volume = currVolume;
        hideVideo();
      });
    } else {
      video.pause();
      hideVideo();
    }
  });
  socket.on('volume', (val) => {
    const video = getVideoPlayer();
    if (val === "up") {
      video.volume = Math.min(1, video.volume + 0.1);
    } else if (val === "down") {
      video.volume = Math.max(0, video.volume - 0.1);
    } else {
      video.volume = val;
    }
  });
  socket.on('restart', () => {
    const video = getVideoPlayer();
    video.currentTime = 0;
    if (video.paused) video.play();
  });
  socket.on("notification", (data) => {
    const notification = data.split("::");
    const message = notification[0];
    const categoryClass = notification.length > 1 ? notification[1] : "is-primary";
    flashNotification(message, categoryClass);
    if (isMaster) {
      socket.emit("clear_notification");
    }
  });
  socket.on("now_playing", handleNowPlayingUpdate);
  socket.on("preferences_update", applyPreferenceUpdate);
  socket.on("preferences_reset", applyPreferencesReset);
  socket.on("score_phrases_update", (phrases) => { scoreReviews = phrases; });

  socket.on("playback_position", (position) => {
    if (!isMaster) {
      const video = getVideoPlayer();
      if (isMediaPlaying(video)) {
        if (Math.abs(video.currentTime - position) > 2) {
          console.log("Slave drifting, syncing position to:", position);
          video.currentTime = position;
        }
      }
    }
  });
}

const handleSocketRecovery = () => {
  // A socket may disconnect if the tab is backgrounded for a while
  // Reconnect and configure event listeners when tab becomes visible again
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === 'visible') {
      autoplayConfirmed && loadNowPlaying();
      if (!socket.connected) {
        socket = io();
        setupSocketEvents();
      }
    }
  });
}

const setupUIScaling = () => {
  const urlParams = new URLSearchParams(window.location.search);
  const rawScale = urlParams.get('scale');
  if (!rawScale) return;
  uiScale = parseFloat(rawScale) || 1;

  const scaleTargets = [
    { selector: '#logo-container .biaoke-brand', origin: null },
    { selector: '#top-container', origin: 'top right' },
    { selector: '#ap-container', origin: 'top left' },
    { selector: '#qr-code', origin: 'bottom left' },
    { selector: '#up-next', origin: 'bottom right' },
    { selector: '#dvd', origin: null },
    { selector: '#your-score-text', origin: null },
    { selector: '#score-number-text', origin: null },
    { selector: '#score-review-text', origin: null },
    { selector: '#splash-notification', origin: 'top left' },
    { selector: '#clock', origin: 'top left' },
  ];

  scaleTargets.forEach(({ selector, origin }) => {
    const el = document.querySelector(selector);
    if (el) {
      el.style.transform = `scale(${uiScale})`;
      if (origin) el.style.transformOrigin = origin;
    }
  });
}

// Document ready procedures

$(function () {
  // Setup various features and listeners
  setupUIScaling();
  if (BiaokeConfig.showSplashClock) startClock();
  setupScreensaver();
  setupOverlayMenus();
  setupVideoPlayer();
  setupBackgroundMusicPlayer();

  // Handle browser compatibility
  handleUnsupportedBrowser();
  testAutoplayCapability();
});


// Setup sockets and recovery outside of document ready to prevent race conditions
setupSocketEvents();
handleSocketRecovery();

// Fallback: if socket connected before listeners were attached, register now
if (socket.connected) {
  console.log('Socket already connected, registering splash...');
  socket.emit("register_splash");
}

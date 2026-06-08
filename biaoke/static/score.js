const SCORE_MIN_WAIT_MS = 2600;
const SCORE_ROLL_MS = 2400;

function getScoreData(scoreValue, scoreResult = null) {
  function randomPhrase(phrases) {
    return phrases[Math.floor(Math.random() * phrases.length)];
  }

  const review =
    scoreResult && scoreResult.review
      ? scoreResult.review
      : scoreValue < 30
        ? randomPhrase(scoreReviews.low)
        : scoreValue < 60
          ? randomPhrase(scoreReviews.mid)
          : randomPhrase(scoreReviews.high);

  if (scoreValue < 25) {
    return { reaction: "boo-strong.mp3", reactionVolume: 0.52, review };
  }
  if (scoreValue < 45) {
    return { reaction: "boo-soft.mp3", reactionVolume: 0.42, review };
  }
  if (scoreValue < 70) {
    return { reaction: "applause-l.mp3", reactionVolume: 0.42, review };
  }
  if (scoreValue < 85) {
    return { reaction: "applause-h.mp3", reactionVolume: 0.55, review };
  }
  return { reaction: "applause-xl.mp3", reactionVolume: 0.68, review };
}

function getScoreValue(scoreResult = null) {
  if (scoreResult && Number.isFinite(scoreResult.score)) {
    return Math.max(0, Math.min(99, Math.floor(scoreResult.score)));
  }
  const random = Math.random();
  const bias = 2;
  const scoreValue = Math.pow(random, 1 / bias) * 99;
  return Math.floor(scoreValue);
}

function ensureJudgesPanel(scoreElement) {
  let panel = $("#score-waiting-panel");
  if (panel.length) return panel;

  panel = $(`
    <div id="score-waiting-panel">
      <div class="judge-row">
        <div class="judge-card judge-one"><div class="judge-head"></div><div class="judge-body"></div></div>
        <div class="judge-card judge-two"><div class="judge-head"></div><div class="judge-body"></div></div>
        <div class="judge-card judge-three"><div class="judge-head"></div><div class="judge-body"></div></div>
      </div>
      <div id="judge-debate-text">Jurados debatendo<span class="debate-dots"></span></div>
    </div>
  `);
  scoreElement.append(panel);
  return panel;
}

function showWaitingState(scoreElement, scoreTextElement, scoreReviewElement) {
  scoreElement.show();
  scoreElement.addClass("is-waiting");
  scoreTextElement.text("--");
  scoreReviewElement.text("");
  ensureJudgesPanel(scoreElement).show();
}

function hideWaitingState(scoreElement) {
  scoreElement.removeClass("is-waiting");
  $("#score-waiting-panel").hide();
}

async function showFinalScoreWithAudio(
  scoreTextElement,
  scoreValue,
  scoreReviewElement,
  scoreData,
  reactionElement
) {
  scoreTextElement.text(String(scoreValue).padStart(2, "0"));
  scoreReviewElement.text(scoreData.review);
  launchFireworkShow(scoreValue);
  reactionElement.volume = scoreData.reactionVolume;
  reactionElement.play().catch(() => {});
  return new Promise((resolve) => {
    reactionElement.onended = resolve;
    setTimeout(resolve, 4500);
  });
}

async function rotateScore(scoreTextElement, duration) {
  const interval = 90;
  const startTime = performance.now();

  while (true) {
    const elapsed = performance.now() - startTime;

    if (elapsed >= duration) break;

    const randomScore = String(Math.floor(Math.random() * 99) + 1).padStart(
      2,
      "0"
    );
    scoreTextElement.text(randomScore);

    const nextUpdate = interval - (performance.now() - (startTime + elapsed));
    await new Promise((resolve) =>
      setTimeout(resolve, Math.max(0, nextUpdate))
    );
  }
}

async function resolveScoreResult(scoreResultOrPromise) {
  try {
    return await Promise.resolve(scoreResultOrPromise);
  } catch (e) {
    console.log("Score analysis failed; falling back to entertainment score.", e);
    return null;
  }
}

async function startScore(staticPath, scoreResultOrPromise = null) {
  const phrasesPromise = fetch(BiaokeConfig.scorePhrasesUrl)
    .then((r) => r.json())
    .then((phrases) => { scoreReviews = phrases; })
    .catch(() => {});

  const scoreElement = $("#score");
  const scoreTextElement = $("#score-number-text");
  const scoreReviewElement = $("#score-review-text");

  showWaitingState(scoreElement, scoreTextElement, scoreReviewElement);

  const drums = new Audio(staticPath + "sounds/score-drums.mp3");
  drums.loop = true;
  drums.volume = 0.16;
  drums.play().catch(() => {});

  const waitStartedAt = performance.now();
  const scoreResult = await resolveScoreResult(scoreResultOrPromise);
  await phrasesPromise;
  const elapsed = performance.now() - waitStartedAt;
  if (elapsed < SCORE_MIN_WAIT_MS) {
    await new Promise((resolve) => setTimeout(resolve, SCORE_MIN_WAIT_MS - elapsed));
  }

  const scoreValue = getScoreValue(scoreResult);
  const scoreData = getScoreData(scoreValue, scoreResult);
  const reaction = new Audio(staticPath + "sounds/" + scoreData.reaction);

  hideWaitingState(scoreElement);
  await rotateScore(scoreTextElement, SCORE_ROLL_MS);

  drums.pause();
  drums.currentTime = 0;

  await showFinalScoreWithAudio(
    scoreTextElement,
    scoreValue,
    scoreReviewElement,
    scoreData,
    reaction
  );
  scoreReviewElement.text("");
  scoreElement.hide();
}

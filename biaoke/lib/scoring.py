"""Audio scoring utilities for post-song vocal analysis."""

from __future__ import annotations

import math
import os
import statistics
import subprocess
import tempfile
import wave
from dataclasses import asdict, dataclass
from pathlib import Path


MAX_SCORE_UPLOAD_BYTES = 80 * 1024 * 1024
ANALYSIS_SAMPLE_RATE = 8000
FRAME_SECONDS = 0.04
HOP_SECONDS = 0.05
MIN_SINGING_FREQUENCY = 70
MAX_SINGING_FREQUENCY = 700


class ScoreAnalysisError(Exception):
    """Raised when an uploaded scoring recording cannot be analyzed."""


@dataclass
class ScoreResult:
    score: int
    tier: str
    review: str
    engine: str
    metrics: dict[str, float | int | str | bool]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PitchFrame:
    time: float
    pitch_hz: float | None
    confidence: float
    rms: float

    @property
    def voiced(self) -> bool:
        return self.pitch_hz is not None


def get_scoring_engine_status() -> dict[str, str | bool]:
    """Return the best available scoring backend without importing heavy deps eagerly."""
    try:
        import torch  # type: ignore
        import torchcrepe  # noqa: F401  # type: ignore

        if torch.cuda.is_available():
            return {"engine": "torchcrepe-cuda", "gpu": True}
        return {"engine": "torchcrepe-cpu", "gpu": False}
    except Exception:
        return {"engine": "autocorrelation", "gpu": False}


def analyze_upload_bytes(
    data: bytes,
    suffix: str = ".webm",
    *,
    prefer_torchcrepe: bool = True,
    ffmpeg_bin: str = "ffmpeg",
) -> dict:
    """Convert an uploaded browser recording to WAV and analyze it."""
    if not data:
        raise ScoreAnalysisError("No audio data received")
    if len(data) > MAX_SCORE_UPLOAD_BYTES:
        raise ScoreAnalysisError("Audio upload is too large")

    safe_suffix = suffix if suffix.startswith(".") and len(suffix) <= 12 else ".webm"
    with tempfile.TemporaryDirectory(prefix="biaoke-score-") as tmp:
        input_path = Path(tmp) / f"input{safe_suffix}"
        wav_path = Path(tmp) / "recording.wav"
        input_path.write_bytes(data)
        _convert_to_analysis_wav(input_path, wav_path, ffmpeg_bin)
        return analyze_wav_file(wav_path, prefer_torchcrepe=prefer_torchcrepe).to_dict()


def analyze_wav_file(path: str | os.PathLike, *, prefer_torchcrepe: bool = True) -> ScoreResult:
    """Analyze a mono WAV recording and return a normalized vocal score."""
    sample_rate, samples = _load_wav_mono(path)
    if len(samples) < sample_rate:
        raise ScoreAnalysisError("Recording is too short to score")

    if prefer_torchcrepe:
        try:
            frames = _extract_pitch_torchcrepe(samples, sample_rate)
            engine = str(get_scoring_engine_status()["engine"])
            return _score_pitch_frames(frames, engine)
        except Exception:
            pass

    frames = _extract_pitch_autocorrelation(samples, sample_rate)
    return _score_pitch_frames(frames, "autocorrelation")


def _convert_to_analysis_wav(input_path: Path, output_path: Path, ffmpeg_bin: str) -> None:
    cmd = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(ANALYSIS_SAMPLE_RATE),
        "-f",
        "wav",
        str(output_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    except FileNotFoundError as exc:
        raise ScoreAnalysisError("ffmpeg is required for scoring uploads") from exc
    except subprocess.TimeoutExpired as exc:
        raise ScoreAnalysisError("Timed out while preparing scoring audio") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", "ignore").strip()
        raise ScoreAnalysisError(f"Could not decode scoring audio: {stderr}") from exc


def _load_wav_mono(path: str | os.PathLike) -> tuple[int, list[float]]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        raw = wav.readframes(wav.getnframes())

    if channels < 1:
        raise ScoreAnalysisError("Recording has no audio channels")
    if sample_width not in {1, 2, 3, 4}:
        raise ScoreAnalysisError(f"Unsupported WAV sample width: {sample_width}")

    step = sample_width * channels
    samples: list[float] = []
    for offset in range(0, len(raw), step):
        channel_values = []
        for channel in range(channels):
            start = offset + channel * sample_width
            chunk = raw[start : start + sample_width]
            if len(chunk) != sample_width:
                continue
            channel_values.append(_pcm_bytes_to_float(chunk, sample_width))
        if channel_values:
            samples.append(sum(channel_values) / len(channel_values))

    return sample_rate, samples


def _pcm_bytes_to_float(chunk: bytes, sample_width: int) -> float:
    if sample_width == 1:
        return (chunk[0] - 128) / 128.0
    value = int.from_bytes(chunk, byteorder="little", signed=True)
    max_value = float(1 << (8 * sample_width - 1))
    return max(-1.0, min(1.0, value / max_value))


def _extract_pitch_torchcrepe(samples: list[float], sample_rate: int) -> list[PitchFrame]:
    import torch  # type: ignore
    import torchcrepe  # type: ignore

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    audio = torch.tensor(samples, dtype=torch.float32, device=device).unsqueeze(0)
    hop_length = max(1, int(sample_rate * HOP_SECONDS))
    pitch, periodicity = torchcrepe.predict(
        audio,
        sample_rate,
        hop_length,
        MIN_SINGING_FREQUENCY,
        MAX_SINGING_FREQUENCY,
        "tiny",
        batch_size=2048,
        device=device,
        return_periodicity=True,
    )
    pitch_values = pitch.squeeze(0).detach().cpu().tolist()
    confidence_values = periodicity.squeeze(0).detach().cpu().tolist()
    rms_values = _frame_rms_values(samples, sample_rate)
    frames = []
    for idx, (pitch_hz, confidence) in enumerate(zip(pitch_values, confidence_values)):
        voiced_pitch = float(pitch_hz) if pitch_hz and confidence >= 0.45 else None
        rms = rms_values[idx] if idx < len(rms_values) else 0.0
        frames.append(PitchFrame(idx * HOP_SECONDS, voiced_pitch, float(confidence), rms))
    return frames


def _extract_pitch_autocorrelation(samples: list[float], sample_rate: int) -> list[PitchFrame]:
    frame_size = max(64, int(sample_rate * FRAME_SECONDS))
    hop_size = max(64, int(sample_rate * HOP_SECONDS))
    min_lag = max(1, int(sample_rate / MAX_SINGING_FREQUENCY))
    max_lag = max(min_lag + 1, int(sample_rate / MIN_SINGING_FREQUENCY))

    rms_values = _frame_rms_values(samples, sample_rate, frame_size, hop_size)
    threshold = _voicing_threshold(rms_values)
    frames = []

    for frame_index, start in enumerate(range(0, len(samples) - frame_size + 1, hop_size)):
        frame = samples[start : start + frame_size]
        rms = rms_values[frame_index]
        if rms < threshold:
            frames.append(PitchFrame(start / sample_rate, None, 0.0, rms))
            continue

        pitch_hz, confidence = _estimate_pitch_autocorrelation(
            frame, sample_rate, min_lag, min(max_lag, frame_size - 2)
        )
        if confidence < 0.33:
            pitch_hz = None
        frames.append(PitchFrame(start / sample_rate, pitch_hz, confidence, rms))

    return frames


def _frame_rms_values(
    samples: list[float],
    sample_rate: int,
    frame_size: int | None = None,
    hop_size: int | None = None,
) -> list[float]:
    frame_size = frame_size or max(64, int(sample_rate * FRAME_SECONDS))
    hop_size = hop_size or max(64, int(sample_rate * HOP_SECONDS))
    values = []
    for start in range(0, len(samples) - frame_size + 1, hop_size):
        frame = samples[start : start + frame_size]
        values.append(math.sqrt(sum(sample * sample for sample in frame) / len(frame)))
    return values


def _voicing_threshold(rms_values: list[float]) -> float:
    if not rms_values:
        return 1.0
    noise = _percentile(rms_values, 20)
    peak = _percentile(rms_values, 95)
    threshold = max(0.006, peak * 0.08)
    if noise < peak * 0.35:
        threshold = max(threshold, noise * 2.5)
    return threshold


def _estimate_pitch_autocorrelation(
    frame: list[float], sample_rate: int, min_lag: int, max_lag: int
) -> tuple[float | None, float]:
    mean = sum(frame) / len(frame)
    centered = [sample - mean for sample in frame]
    energy = sum(sample * sample for sample in centered)
    if energy <= 1e-9:
        return None, 0.0

    best_lag = 0
    best_corr = 0.0
    for lag in range(min_lag, max_lag + 1):
        limit = len(centered) - lag
        if limit <= 0:
            break
        corr = 0.0
        for idx in range(limit):
            corr += centered[idx] * centered[idx + lag]
        if corr > best_corr:
            best_corr = corr
            best_lag = lag

    if best_lag <= 0:
        return None, 0.0
    confidence = max(0.0, min(1.0, best_corr / energy))
    return sample_rate / best_lag, confidence


def _score_pitch_frames(frames: list[PitchFrame], engine: str) -> ScoreResult:
    if not frames:
        raise ScoreAnalysisError("No analyzable audio frames found")

    voiced = [frame for frame in frames if frame.voiced]
    voiced_ratio = len(voiced) / len(frames)
    if not voiced or voiced_ratio < 0.02:
        return ScoreResult(
            score=0,
            tier="low",
            review="No clear singing voice was captured.",
            engine=engine,
            metrics={
                "voiced_ratio": round(voiced_ratio, 4),
                "voiced_frames": len(voiced),
                "total_frames": len(frames),
            },
        )

    confidence = statistics.mean(frame.confidence for frame in voiced)
    pitch_values = [frame.pitch_hz for frame in voiced if frame.pitch_hz]
    pitch_range_cents = _pitch_range_cents(pitch_values)
    stability = _pitch_stability(voiced)
    volume_consistency = _volume_consistency([frame.rms for frame in voiced])
    coverage = min(1.0, voiced_ratio / 0.45)
    range_factor = _clamp((pitch_range_cents - 250.0) / 950.0)

    weighted_score = (
        0.32 * coverage
        + 0.30 * confidence
        + 0.20 * stability
        + 0.10 * volume_consistency
        + 0.08 * range_factor
    )
    score = int(round(_clamp(weighted_score) * 100))
    tier = "high" if score >= 70 else "mid" if score >= 40 else "low"
    review = _review_for_score(score, coverage, confidence, stability)

    return ScoreResult(
        score=score,
        tier=tier,
        review=review,
        engine=engine,
        metrics={
            "voiced_ratio": round(voiced_ratio, 4),
            "coverage": round(coverage, 4),
            "pitch_confidence": round(confidence, 4),
            "pitch_stability": round(stability, 4),
            "volume_consistency": round(volume_consistency, 4),
            "pitch_range_cents": round(pitch_range_cents, 1),
            "voiced_frames": len(voiced),
            "total_frames": len(frames),
        },
    )


def _pitch_range_cents(pitch_values: list[float]) -> float:
    if len(pitch_values) < 2:
        return 0.0
    low = _percentile(pitch_values, 10)
    high = _percentile(pitch_values, 90)
    if low <= 0 or high <= 0:
        return 0.0
    return 1200.0 * math.log2(high / low)


def _pitch_stability(voiced_frames: list[PitchFrame]) -> float:
    deltas = []
    previous = None
    for frame in voiced_frames:
        if previous and frame.pitch_hz and previous.pitch_hz and frame.time - previous.time <= 0.16:
            cents = abs(1200.0 * math.log2(frame.pitch_hz / previous.pitch_hz))
            deltas.append(cents)
        previous = frame
    if not deltas:
        return 0.0
    median_delta = statistics.median(deltas)
    return _clamp(1.0 - median_delta / 220.0)


def _volume_consistency(rms_values: list[float]) -> float:
    if len(rms_values) < 4:
        return 0.0
    median = statistics.median(rms_values)
    if median <= 1e-6:
        return 0.0
    spread = _percentile(rms_values, 75) - _percentile(rms_values, 25)
    return _clamp(1.0 - spread / (median * 1.6))


def _review_for_score(score: int, coverage: float, confidence: float, stability: float) -> str:
    if coverage < 0.25:
        return "The mic captured only a small amount of singing."
    if confidence < 0.45:
        return "The voice was detected, but pitch clarity was inconsistent."
    if score >= 70:
        return "Strong vocal capture with clear pitch and steady delivery."
    if stability < 0.35:
        return "Good vocal presence, but pitch stability needs work."
    return "Solid vocal capture with room to tighten pitch and timing."


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile / 100.0
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[int(rank)]
    fraction = rank - low
    return ordered[low] * (1 - fraction) + ordered[high] * fraction


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))

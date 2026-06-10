"""GPU-capable scoring microservice used by the Docker compose setup."""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from threading import Lock, Thread
from typing import Any
import unicodedata
import wave

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from biaoke.lib.scoring import (
    ScoreAnalysisError,
    analyze_upload_bytes,
    analyze_wav_file,
    extract_melody_guide_from_media,
    get_scoring_engine_status,
)

app = FastAPI(title="Biaoke Scoring Service")
_WARMED_UP = False
MEDIA_ROOT = Path(os.environ.get("BIAOKE_MEDIA_ROOT", "/app/biaoke-songs")).resolve()
DEFAULT_DEMUCS_MODEL = "htdemucs"
ALIGNMENT_MODEL_ENV = "BIAOKE_ALIGNMENT_MODEL"
ALIGNMENT_DEVICE_ENV = "BIAOKE_ALIGNMENT_DEVICE"
DEFAULT_ALIGNMENT_MODEL = "mms_fa"
SUPPORTED_ALIGNMENT_LANGUAGES = {"auto", "en", "es", "pt"}
ALIGNMENT_MIN_OVERALL_CONFIDENCE = 0.18
ALIGNMENT_LINE_WINDOW_LEAD_SECONDS = 0.35
ALIGNMENT_LINE_WINDOW_TAIL_SECONDS = 0.75
ALIGNMENT_TRANSCRIPT_WINDOW_LEAD_SECONDS = 0.75
ALIGNMENT_TRANSCRIPT_WINDOW_TAIL_SECONDS = 1.65
ALIGNMENT_MAX_WINDOW_SECONDS = 32.0
ALIGNMENT_MIN_WINDOW_SECONDS = 0.4
ALIGNMENT_MIN_LINE_CONFIDENCE = 0.16
_ALIGNMENT_CACHE: dict[tuple[str, str], dict[str, Any]] = {}
_ALIGNMENT_LOCK = Lock()


class StemSeparationRequest(BaseModel):
    input_path: str
    vocals_path: str
    instrumental_path: str
    model: str = DEFAULT_DEMUCS_MODEL


class TranscriptRequest(BaseModel):
    input_path: str
    model: str = "medium"
    language: str | None = None
    vad_filter: bool = True
    initial_prompt: str | None = None
    beam_size: int = 5


class LyricAlignmentLine(BaseModel):
    start: float
    end: float
    text: str
    line_index: int | None = None
    timing_source: str | None = None


class LyricAlignmentRequest(BaseModel):
    input_path: str
    lines: list[LyricAlignmentLine]
    language: str | None = None
    model: str = DEFAULT_ALIGNMENT_MODEL


def _warm_up_scoring_engine() -> None:
    global _WARMED_UP
    try:
        sample_rate = 8000
        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
            with wave.open(tmp.name, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate)
                raw = bytearray()
                for index in range(sample_rate * 2):
                    value = int(0.25 * math.sin(2 * math.pi * 220 * index / sample_rate) * 32767)
                    raw.extend(value.to_bytes(2, "little", signed=True))
                wav.writeframes(bytes(raw))
            analyze_wav_file(tmp.name, prefer_torchcrepe=True)
        _WARMED_UP = True
        logging.info("Scoring engine warm-up complete")
    except Exception as exc:
        logging.warning("Scoring engine warm-up failed: %s", exc)


@app.on_event("startup")
def startup() -> None:
    Thread(target=_warm_up_scoring_engine, daemon=True).start()


@app.get("/health")
def health():
    return {"ok": True, "warmed_up": _WARMED_UP, **get_scoring_engine_status()}


@app.post("/analyze")
async def analyze(audio: UploadFile = File(...)):
    data = await audio.read()
    suffix = Path(audio.filename or "").suffix or ".webm"
    try:
        return analyze_upload_bytes(data, suffix=suffix, prefer_torchcrepe=True)
    except ScoreAnalysisError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/melody")
async def melody(audio: UploadFile = File(...), max_seconds: int | None = None):
    data = await audio.read()
    suffix = Path(audio.filename or "").suffix or ".media"
    try:
        with tempfile.TemporaryDirectory(prefix="biaoke-melody-service-") as tmp:
            input_path = Path(tmp) / f"input{suffix}"
            input_path.write_bytes(data)
            return extract_melody_guide_from_media(
                input_path,
                prefer_torchcrepe=True,
                max_seconds=max_seconds,
            )
    except ScoreAnalysisError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/separate")
def separate_stems(request: StemSeparationRequest):
    input_path = _validated_media_path(request.input_path, must_exist=True)
    vocals_path = _validated_media_path(request.vocals_path, must_exist=False)
    instrumental_path = _validated_media_path(request.instrumental_path, must_exist=False)
    vocals_path.parent.mkdir(parents=True, exist_ok=True)
    instrumental_path.parent.mkdir(parents=True, exist_ok=True)

    model = _safe_demucs_model(request.model)
    device = _demucs_device()
    try:
        with tempfile.TemporaryDirectory(prefix="biaoke-demucs-") as tmp:
            work_dir = Path(tmp)
            cmd = [
                sys.executable,
                "-m",
                "demucs.separate",
                "--two-stems",
                "vocals",
                "-n",
                model,
                "--device",
                device,
                "--out",
                str(work_dir),
                str(input_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "Demucs failed").strip()
                raise HTTPException(status_code=500, detail=detail[-2000:])

            demucs_output = work_dir / model
            source_vocals = _find_stem_file(demucs_output, "vocals.wav")
            source_instrumental = _find_stem_file(demucs_output, "no_vocals.wav")
            if not source_vocals or not source_instrumental:
                raise HTTPException(status_code=500, detail="Demucs did not produce expected stems")

            shutil.copyfile(source_vocals, vocals_path)
            shutil.copyfile(source_instrumental, instrumental_path)
            _make_readable(vocals_path)
            _make_readable(instrumental_path)
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Stem separation timed out") from exc

    return {
        "status": "ready",
        "engine": "demucs",
        "model": model,
        "device": device,
        "vocals_path": str(vocals_path),
        "instrumental_path": str(instrumental_path),
    }


@app.post("/transcribe")
def transcribe(request: TranscriptRequest):
    input_path = _validated_media_path(request.input_path, must_exist=True)
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception as exc:
        raise HTTPException(
            status_code=501,
            detail="faster-whisper is not installed in the scoring service",
        ) from exc

    model_name = _safe_transcription_model(request.model)
    device = _whisper_device()
    compute_type = "float16" if device == "cuda" else "int8"
    try:
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
        segments, info = model.transcribe(
            str(input_path),
            language=request.language or None,
            beam_size=_safe_beam_size(request.beam_size),
            vad_filter=bool(request.vad_filter),
            word_timestamps=True,
            condition_on_previous_text=True,
            initial_prompt=_safe_transcription_prompt(request.initial_prompt),
        )
        words = []
        for segment in segments:
            for word in segment.words or []:
                text = str(word.word or "").strip()
                if not text:
                    continue
                words.append(
                    {
                        "word": text,
                        "start": round(float(word.start), 3),
                        "end": round(float(word.end), 3),
                        "probability": round(float(word.probability or 0), 4),
                    }
                )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[-2000:]) from exc

    return {
        "status": "ready",
        "engine": "faster-whisper",
        "model": model_name,
        "device": device,
        "vad_filter": bool(request.vad_filter),
        "prompted": bool(_safe_transcription_prompt(request.initial_prompt)),
        "language": getattr(info, "language", request.language),
        "language_probability": round(float(getattr(info, "language_probability", 0) or 0), 4),
        "words": words,
    }


@app.post("/align-lyrics")
def align_lyrics(request: LyricAlignmentRequest):
    input_path = _validated_media_path(request.input_path, must_exist=True)
    language = _normalize_alignment_language(request.language)
    if language not in SUPPORTED_ALIGNMENT_LANGUAGES:
        raise HTTPException(
            status_code=422,
            detail="Forced lyric alignment currently supports pt, en and es.",
        )

    model_name = _safe_alignment_model(request.model)
    if model_name != "mms_fa":
        raise HTTPException(status_code=422, detail="Unsupported alignment model")

    try:
        return _align_lyrics_with_mms_fa(input_path, request.lines, language=language)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)[-2000:]) from exc


def _validated_media_path(raw_path: str, *, must_exist: bool) -> Path:
    path = Path(raw_path).expanduser()
    if must_exist:
        try:
            path = path.resolve(strict=True)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Media file not found") from exc
    else:
        path = path.resolve(strict=False)

    try:
        path.relative_to(MEDIA_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Path is outside media root") from exc
    return path


def _safe_demucs_model(model: str) -> str:
    model = (model or DEFAULT_DEMUCS_MODEL).strip()
    if not model.replace("_", "").replace("-", "").isalnum():
        return DEFAULT_DEMUCS_MODEL
    return model


def _demucs_device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _whisper_device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _alignment_device() -> str:
    requested = os.environ.get(ALIGNMENT_DEVICE_ENV, "").strip().casefold()
    if requested in {"cpu", "cuda"}:
        if requested == "cuda":
            try:
                import torch

                return "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                return "cpu"
        return "cpu"
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _safe_transcription_model(model: str) -> str:
    model = (model or "medium").strip()
    allowed = {"tiny", "base", "small", "medium", "large-v2", "large-v3", "distil-large-v3"}
    return model if model in allowed else "medium"


def _safe_beam_size(value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 5
    return max(1, min(10, parsed))


def _safe_transcription_prompt(value: str | None) -> str | None:
    prompt = re.sub(r"\s+", " ", str(value or "")).strip()
    if not prompt:
        return None
    return prompt[:2400]


def _safe_alignment_model(model: str) -> str:
    model = (model or os.environ.get(ALIGNMENT_MODEL_ENV) or DEFAULT_ALIGNMENT_MODEL).strip().casefold()
    return model if model in {"mms_fa"} else DEFAULT_ALIGNMENT_MODEL


def _normalize_alignment_language(language: str | None) -> str:
    value = str(language or "auto").strip().casefold().replace("_", "-")
    if value in {"", "auto", "unknown"}:
        return "auto"
    if value in {"en", "eng", "english"} or value.startswith("en-"):
        return "en"
    if value in {"es", "spa", "spanish", "espanol", "español"} or value.startswith("es-"):
        return "es"
    if value in {"pt", "por", "portuguese", "portugues", "português"} or value.startswith("pt-"):
        return "pt"
    return value


def _align_lyrics_with_mms_fa(
    input_path: Path,
    lines: list[LyricAlignmentLine],
    *,
    language: str,
) -> dict[str, Any]:
    context = _mms_alignment_context(_alignment_device())
    waveform, sample_rate = _load_alignment_audio(input_path, context["sample_rate"])
    duration_seconds = waveform.size(1) / sample_rate
    if duration_seconds <= 0:
        return _missing_alignment_payload(language, "empty_audio")

    paint_units: list[dict[str, Any]] = []
    total_words = 0
    aligned_words = 0
    aligned_lines = 0
    confidence_values = []
    for line_position, line in enumerate(lines[:600]):
        line_index = line.line_index if line.line_index is not None else line_position
        words = _alignment_words_for_text(line.text)
        if not words:
            continue
        total_words += len(words)

        window = _alignment_window(line.start, line.end, duration_seconds, timing_source=line.timing_source)
        if not window:
            continue
        units = _align_line_with_mms_fa(
            context,
            waveform,
            sample_rate,
            words,
            window_start=window[0],
            window_end=window[1],
            line_index=int(line_index),
        )
        if not units:
            continue
        line_confidence = sum(float(unit.get("confidence") or 0.0) for unit in units) / len(units)
        if line_confidence < ALIGNMENT_MIN_LINE_CONFIDENCE:
            logging.debug(
                "MMS forced alignment skipped line %s due to low confidence %.3f",
                line_index,
                line_confidence,
            )
            continue
        aligned_lines += 1
        aligned_words += len(units)
        confidence_values.extend(float(unit.get("confidence") or 0.0) for unit in units)
        paint_units.extend(units)

    paint_units.sort(key=lambda unit: (int(unit.get("line_index", 0)), float(unit.get("start", 0.0))))
    _normalize_alignment_unit_timeline(paint_units)
    overall_confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
    coverage = aligned_words / max(total_words, 1)
    if not paint_units or overall_confidence < ALIGNMENT_MIN_OVERALL_CONFIDENCE:
        return {
            **_missing_alignment_payload(language, "low_alignment_confidence"),
            "confidence": {
                "overall": round(overall_confidence, 3),
                "coverage": round(coverage, 3),
                "aligned_words": aligned_words,
                "total_words": total_words,
                "aligned_lines": aligned_lines,
            },
        }

    return {
        "status": "ready",
        "engine": "torchaudio",
        "model": "mms_fa",
        "method": "mms_fa_forced_alignment",
        "device": context["device"],
        "language": language,
        "granularity": "word",
        "paint_units": paint_units,
        "confidence": {
            "overall": round(overall_confidence, 3),
            "coverage": round(coverage, 3),
            "aligned_words": aligned_words,
            "total_words": total_words,
            "aligned_lines": aligned_lines,
        },
    }


def _mms_alignment_context(device: str) -> dict[str, Any]:
    key = ("mms_fa", device)
    with _ALIGNMENT_LOCK:
        cached = _ALIGNMENT_CACHE.get(key)
        if cached:
            return cached
        try:
            import torchaudio  # type: ignore
        except Exception as exc:
            raise RuntimeError("torchaudio is not installed in the scoring service") from exc

        bundle = torchaudio.pipelines.MMS_FA
        model = bundle.get_model().to(device).eval()
        context = {
            "bundle": bundle,
            "model": model,
            "tokenizer": bundle.get_tokenizer(),
            "aligner": bundle.get_aligner(),
            "sample_rate": int(bundle.sample_rate),
            "device": device,
        }
        _ALIGNMENT_CACHE[key] = context
        return context


def _load_alignment_audio(input_path: Path, target_sample_rate: int):
    try:
        import torch
        import torchaudio  # type: ignore
    except Exception as exc:
        raise RuntimeError("torchaudio is not installed in the scoring service") from exc

    waveform, sample_rate = torchaudio.load(str(input_path))
    if waveform.ndim > 1 and waveform.size(0) > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    if sample_rate != target_sample_rate:
        waveform = torchaudio.functional.resample(waveform, sample_rate, target_sample_rate)
        sample_rate = target_sample_rate
    return waveform.to(dtype=torch.float32), int(sample_rate)


def _align_line_with_mms_fa(
    context: dict[str, Any],
    waveform,
    sample_rate: int,
    words: list[dict[str, Any]],
    *,
    window_start: float,
    window_end: float,
    line_index: int,
) -> list[dict[str, Any]]:
    start_sample = max(0, int(round(window_start * sample_rate)))
    end_sample = min(waveform.size(1), int(round(window_end * sample_rate)))
    if end_sample <= start_sample:
        return []
    segment = waveform[:, start_sample:end_sample]
    if segment.size(1) < int(sample_rate * ALIGNMENT_MIN_WINDOW_SECONDS):
        return []

    try:
        import torch

        tokenized_words = context["tokenizer"]([word["normalized"] for word in words])
        with torch.inference_mode():
            emission, _ = context["model"](segment.to(context["device"]))
        emission = emission[0]
        spans_by_word = context["aligner"](emission, tokenized_words)
    except Exception as exc:
        logging.debug("MMS forced alignment skipped line %s: %s", line_index, exc)
        return []

    frame_seconds = (segment.size(1) / sample_rate) / max(int(emission.size(0)), 1)
    units = []
    for word_position, (word, token_spans) in enumerate(zip(words, spans_by_word)):
        if not token_spans:
            continue
        start_frame = min(int(span.start) for span in token_spans)
        end_frame = max(int(span.end) for span in token_spans)
        if end_frame <= start_frame:
            end_frame = start_frame + 1
        confidence = _mms_span_confidence(token_spans)
        start = window_start + start_frame * frame_seconds
        end = window_start + end_frame * frame_seconds
        units.append(
            {
                "start": round(max(window_start, start), 3),
                "end": round(min(window_end, max(end, start + 0.06)), 3),
                "text": word["text"],
                "line_index": line_index,
                "unit_index": int(word["index"]),
                "unit_type": "word",
                "precision": "mms_fa_forced_alignment",
                "confidence": round(confidence, 3),
                "normalized": word["normalized"],
            }
        )
    _normalize_alignment_unit_timeline(units)
    return units


def _alignment_words_for_text(text: str) -> list[dict[str, Any]]:
    raw_tokens = re.findall(r"[^\W_]+(?:['’][^\W_]+)*", str(text or ""), flags=re.UNICODE)
    words = []
    for index, raw_token in enumerate(raw_tokens):
        normalized = _normalize_mms_word(raw_token)
        if not normalized:
            continue
        words.append({"text": raw_token, "normalized": normalized, "index": index})
    return words


def _normalize_mms_word(text: str) -> str:
    text = str(text or "").replace("’", "'").replace("`", "'").casefold()
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    stripped = stripped.replace("ç", "c").replace("ñ", "n")
    return "".join(char for char in stripped if ("a" <= char <= "z") or char == "'").strip("'")


def _alignment_window(
    start: float,
    end: float,
    duration_seconds: float,
    *,
    timing_source: str | None = None,
) -> tuple[float, float] | None:
    try:
        start_value = float(start)
        end_value = float(end)
    except (TypeError, ValueError):
        return None
    if duration_seconds <= 0 or end_value <= start_value:
        return None
    source = str(timing_source or "").strip().casefold()
    if source == "transcript_words":
        lead_seconds = ALIGNMENT_TRANSCRIPT_WINDOW_LEAD_SECONDS
        tail_seconds = ALIGNMENT_TRANSCRIPT_WINDOW_TAIL_SECONDS
    else:
        lead_seconds = ALIGNMENT_LINE_WINDOW_LEAD_SECONDS
        tail_seconds = ALIGNMENT_LINE_WINDOW_TAIL_SECONDS
    start_value = max(0.0, start_value - lead_seconds)
    end_value = min(duration_seconds, end_value + tail_seconds)
    if end_value - start_value > ALIGNMENT_MAX_WINDOW_SECONDS:
        midpoint = (start_value + end_value) / 2.0
        half = ALIGNMENT_MAX_WINDOW_SECONDS / 2.0
        start_value = max(0.0, midpoint - half)
        end_value = min(duration_seconds, midpoint + half)
    if end_value - start_value < ALIGNMENT_MIN_WINDOW_SECONDS:
        return None
    return (start_value, end_value)


def _mms_span_confidence(token_spans: list[Any]) -> float:
    scores = [float(getattr(span, "score", 0.0) or 0.0) for span in token_spans]
    if not scores:
        return 0.0
    average = sum(scores) / len(scores)
    if average <= 0:
        average = math.exp(max(-20.0, average))
    return max(0.0, min(1.0, average))


def _normalize_alignment_unit_timeline(units: list[dict[str, Any]]) -> None:
    previous_end: float | None = None
    previous_line: int | None = None
    for unit in units:
        start = _float_or_none(unit.get("start"))
        end = _float_or_none(unit.get("end"))
        if start is None or end is None:
            continue
        line_index = int(unit.get("line_index", 0) or 0)
        if previous_line is not None and line_index != previous_line:
            previous_end = None
        if previous_end is not None and start < previous_end:
            start = previous_end
            end = max(end, start + 0.06)
            unit["start"] = round(start, 3)
            unit["end"] = round(end, 3)
        previous_end = max(start + 0.06, end)
        previous_line = line_index


def _missing_alignment_payload(language: str, reason: str) -> dict[str, Any]:
    return {
        "status": "missing",
        "engine": "torchaudio",
        "model": "mms_fa",
        "method": "mms_fa_forced_alignment",
        "language": language,
        "granularity": "none",
        "paint_units": [],
        "reason": reason,
    }


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _find_stem_file(root: Path, filename: str) -> Path | None:
    direct = root / filename
    if direct.is_file():
        return direct
    matches = list(root.rglob(filename)) if root.exists() else []
    return matches[0] if matches else None


def _make_readable(path: Path) -> None:
    try:
        os.chmod(path.parent, 0o777)
        os.chmod(path, 0o666)
    except OSError:
        pass

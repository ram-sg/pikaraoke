"""GPU-capable scoring microservice used by the Docker compose setup."""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from threading import Thread
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


class StemSeparationRequest(BaseModel):
    input_path: str
    vocals_path: str
    instrumental_path: str
    model: str = DEFAULT_DEMUCS_MODEL


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

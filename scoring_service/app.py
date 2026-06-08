"""GPU-capable scoring microservice used by the Docker compose setup."""

from __future__ import annotations

import logging
import math
from pathlib import Path
import tempfile
from threading import Thread
import wave

from fastapi import FastAPI, File, HTTPException, UploadFile

from biaoke.lib.scoring import (
    ScoreAnalysisError,
    analyze_upload_bytes,
    analyze_wav_file,
    get_scoring_engine_status,
)

app = FastAPI(title="Biaoke Scoring Service")
_WARMED_UP = False


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

"""GPU-capable scoring microservice used by the Docker compose setup."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile

from pikaraoke.lib.scoring import ScoreAnalysisError, analyze_upload_bytes, get_scoring_engine_status

app = FastAPI(title="PiKaraoke Scoring Service")


@app.get("/health")
def health():
    return {"ok": True, **get_scoring_engine_status()}


@app.post("/analyze")
async def analyze(audio: UploadFile = File(...)):
    data = await audio.read()
    suffix = Path(audio.filename or "").suffix or ".webm"
    try:
        return analyze_upload_bytes(data, suffix=suffix, prefer_torchcrepe=True)
    except ScoreAnalysisError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

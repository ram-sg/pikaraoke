"""Routes for real vocal scoring."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import requests
from flask import Blueprint, jsonify, request

from biaoke.lib.scoring import ScoreAnalysisError, analyze_upload_bytes, get_scoring_engine_status

score_bp = Blueprint("score", __name__)

SCORING_SERVICE_ENV = "BIAOKE_SCORING_SERVICE_URL"


@score_bp.route("/score/status")
def score_status():
    """Return the scoring backend currently configured."""
    service_url = os.environ.get(SCORING_SERVICE_ENV, "").strip()
    if service_url:
        try:
            response = requests.get(service_url.rsplit("/", 1)[0] + "/health", timeout=2)
            response.raise_for_status()
            return jsonify({"mode": "service", **response.json()})
        except requests.RequestException as exc:
            return jsonify({"mode": "fallback", "service_error": str(exc), **get_scoring_engine_status()})
    return jsonify({"mode": "local", **get_scoring_engine_status()})


@score_bp.route("/score/analyze", methods=["POST"])
def analyze_score():
    """Analyze a browser microphone recording and return a real score."""
    upload = request.files.get("audio")
    if upload is None:
        return jsonify({"error": "Missing audio upload"}), 400

    data = upload.read()
    suffix = Path(upload.filename or "").suffix or ".webm"
    service_url = os.environ.get(SCORING_SERVICE_ENV, "").strip()

    if service_url:
        try:
            return jsonify(_analyze_with_service(service_url, data, upload.filename, upload.content_type))
        except requests.RequestException as exc:
            logging.warning("Scoring service failed, falling back locally: %s", exc)

    try:
        return jsonify(analyze_upload_bytes(data, suffix=suffix, prefer_torchcrepe=True))
    except ScoreAnalysisError as exc:
        return jsonify({"error": str(exc)}), 400


def _analyze_with_service(
    service_url: str, data: bytes, filename: str | None, content_type: str | None
) -> dict:
    files = {
        "audio": (
            filename or "recording.webm",
            data,
            content_type or "application/octet-stream",
        )
    }
    response = requests.post(service_url, files=files, timeout=180)
    response.raise_for_status()
    return response.json()

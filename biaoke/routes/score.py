"""Routes for real vocal scoring."""

from __future__ import annotations

import logging
import os
from copy import deepcopy
from pathlib import Path

import requests
from flask import Blueprint, jsonify, request

from biaoke.lib.current_app import get_karaoke_instance
from biaoke.lib.scoring import (
    ScoreAnalysisError,
    analyze_upload_bytes,
    extract_melody_guide_from_media,
    get_scoring_engine_status,
    midi_to_frequency,
    midi_to_note_name,
)
from biaoke.lib.song_guide import ensure_song_guide, guide_path_for_media
from biaoke.lib.song_guide import get_lyrics_offset, set_lyrics_offset

score_bp = Blueprint("score", __name__)

SCORING_SERVICE_ENV = "BIAOKE_SCORING_SERVICE_URL"
_MELODY_CACHE: dict[str, dict] = {}
_MAX_MELODY_CACHE_ITEMS = 6


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


@score_bp.route("/score/melody/current")
def current_melody_guide():
    """Return a best-effort melody guide for the currently loaded song."""
    k = get_karaoke_instance()
    controller = k.playback_controller
    filename = controller.now_playing_filename
    if not filename:
        return jsonify(
            {"status": "idle", "message": "Nenhuma música tocando agora.", "notes": []}
        )

    path = Path(filename)
    if not path.is_file():
        return jsonify(
            {
                "status": "error",
                "message": "Arquivo da música atual não encontrado.",
                "notes": [],
            }
        ), 404

    try:
        guide = _get_cached_melody_guide(path)
    except ScoreAnalysisError as exc:
        return jsonify({"status": "error", "message": str(exc), "notes": []}), 400

    transposed = _transpose_guide(guide, int(controller.now_playing_transpose or 0))
    transposed.update(
        {
            "title": controller.now_playing,
            "playback_position": controller.now_playing_position or 0,
            "is_paused": controller.is_paused,
            "transpose": controller.now_playing_transpose or 0,
        }
    )
    return jsonify(transposed)


@score_bp.route("/score/lyrics/current")
def current_lyrics_guide():
    """Return normalized lyrics for the currently loaded song."""
    k = get_karaoke_instance()
    controller = k.playback_controller
    filename = controller.now_playing_filename
    if not filename:
        return jsonify(
            {
                "status": "idle",
                "message": "Nenhuma música tocando agora.",
                "lines": [],
            }
        )

    path = Path(filename)
    if not path.is_file():
        return jsonify(
            {
                "status": "error",
                "message": "Arquivo da música atual não encontrado.",
                "lines": [],
            }
        ), 404

    try:
        guide = ensure_song_guide(path, rebuild=_truthy(request.args.get("rebuild")))
    except Exception as exc:
        logging.warning("Failed to load Biaoke guide for %s: %s", path, exc)
        return jsonify(
            {
                "status": "error",
                "message": "Nao foi possivel gerar a letra sincronizada desta musica.",
                "title": controller.now_playing,
                "playback_position": controller.now_playing_position or 0,
                "is_paused": controller.is_paused,
                "lines": [],
            }
        ), 500

    lyrics = deepcopy(guide.get("lyrics") or {})
    lyrics.setdefault("status", "missing")
    lyrics.setdefault("lines", [])
    lyrics.update(
        {
            "title": controller.now_playing,
            "playback_position": controller.now_playing_position or 0,
            "is_paused": controller.is_paused,
            "guide_status": (guide.get("quality") or {}).get("status"),
            "lyrics_offset_seconds": get_lyrics_offset(guide),
        }
    )
    return jsonify(lyrics)


@score_bp.route("/score/lyrics-offset/current", methods=["GET", "POST"])
def current_lyrics_offset():
    """Get or set the per-song lyrics timing offset."""
    k = get_karaoke_instance()
    controller = k.playback_controller
    filename = controller.now_playing_filename
    if not filename:
        return jsonify(
            {
                "status": "idle",
                "message": "Nenhuma música tocando agora.",
                "lyrics_offset_seconds": 0,
            }
        )

    path = Path(filename)
    if not path.is_file():
        return jsonify(
            {
                "status": "error",
                "message": "Arquivo da música atual não encontrado.",
                "lyrics_offset_seconds": 0,
            }
        ), 404

    try:
        guide = ensure_song_guide(path)
        if request.method == "POST":
            payload = request.get_json(silent=True) or request.form.to_dict()
            current_offset = get_lyrics_offset(guide)
            if "delta_seconds" in payload:
                requested_offset = current_offset + float(payload["delta_seconds"])
            else:
                requested_offset = float(payload.get("offset_seconds", current_offset))
            guide = set_lyrics_offset(path, requested_offset)
    except (TypeError, ValueError) as exc:
        return jsonify({"status": "error", "message": str(exc), "lyrics_offset_seconds": 0}), 400
    except Exception as exc:
        logging.warning("Failed to update lyrics offset for %s: %s", path, exc)
        return jsonify(
            {
                "status": "error",
                "message": "Nao foi possivel salvar o sincronismo da legenda.",
                "lyrics_offset_seconds": 0,
            }
        ), 500

    return jsonify(
        {
            "status": "ready",
            "title": controller.now_playing,
            "lyrics_offset_seconds": get_lyrics_offset(guide),
        }
    )


@score_bp.route("/score/guide/current")
def current_song_guide():
    """Return the full Biaoke guide package for the currently loaded song."""
    k = get_karaoke_instance()
    controller = k.playback_controller
    filename = controller.now_playing_filename
    if not filename:
        return jsonify(
            {
                "status": "idle",
                "message": "Nenhuma música tocando agora.",
                "lyrics": {"status": "idle", "lines": []},
            }
        )

    path = Path(filename)
    if not path.is_file():
        return jsonify(
            {
                "status": "error",
                "message": "Arquivo da música atual não encontrado.",
                "lyrics": {"status": "error", "lines": []},
            }
        ), 404

    try:
        guide = ensure_song_guide(path, rebuild=_truthy(request.args.get("rebuild")))
    except Exception as exc:
        logging.warning("Failed to load Biaoke guide for %s: %s", path, exc)
        return jsonify(
            {
                "status": "error",
                "message": "Nao foi possivel gerar o pacote desta musica.",
                "lyrics": {"status": "error", "lines": []},
            }
        ), 500

    payload = deepcopy(guide)
    payload["status"] = (guide.get("quality") or {}).get("status", "unknown")
    payload["guide_path"] = guide_path_for_media(path).name
    payload["runtime"] = {
        "title": controller.now_playing,
        "playback_position": controller.now_playing_position or 0,
        "is_paused": controller.is_paused,
    }
    return jsonify(payload)


def _get_cached_melody_guide(path: Path) -> dict:
    stat = path.stat()
    key = f"{path}:{stat.st_mtime_ns}:{stat.st_size}"
    cached = _MELODY_CACHE.get(key)
    if cached is not None:
        return cached

    guide = extract_melody_guide_from_media(path, prefer_torchcrepe=False)
    _MELODY_CACHE[key] = guide
    while len(_MELODY_CACHE) > _MAX_MELODY_CACHE_ITEMS:
        _MELODY_CACHE.pop(next(iter(_MELODY_CACHE)))
    return guide


def _transpose_guide(guide: dict, semitones: int) -> dict:
    if semitones == 0:
        return {**guide, "notes": [dict(note) for note in guide.get("notes", [])]}

    notes = []
    for note in guide.get("notes", []):
        midi = int(note["midi"]) + semitones
        transposed = dict(note)
        transposed["midi"] = midi
        transposed["note"] = midi_to_note_name(midi)
        transposed["frequency"] = round(midi_to_frequency(midi), 2)
        notes.append(transposed)
    return {**guide, "notes": notes}


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


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}

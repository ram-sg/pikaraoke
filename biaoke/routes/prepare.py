"""Stage preparation catalog routes."""

from __future__ import annotations

import flask_babel
from flask import jsonify, render_template, request
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from biaoke.lib.current_app import get_karaoke_instance, get_site_name
from biaoke.lib.guest_manager import format_guest_names
from biaoke.lib.metadata_parser import remove_accents
from biaoke.lib.youtube_dl import get_search_results

_ = flask_babel.gettext

prepare_bp = Blueprint("prepare", __name__)
DEFAULT_SEARCH_COUNT = 10
MAX_SEARCH_COUNT = 50


def _guest_names(k) -> list[str]:
    manager = getattr(k, "guest_manager", None)
    if not manager or not callable(getattr(manager, "list_guests", None)):
        return []
    return manager.list_guests()


class PrepareYoutubeBody(Schema):
    song_url = fields.String(required=True, metadata={"description": "YouTube URL to prepare"})
    song_title = fields.String(load_default="", metadata={"description": "Display title"})
    song_added_by = fields.String(load_default="", metadata={"description": "Requesting user"})


class PrepareLocalBody(Schema):
    file_path = fields.String(required=True, metadata={"description": "Local media file path"})


class EnqueueCoachBody(Schema):
    track_id = fields.Integer(required=True, metadata={"description": "Prepared stage track id"})
    song_added_by = fields.String(load_default="", metadata={"description": "Requesting user"})


class CoachTrackActionBody(Schema):
    track_id = fields.Integer(required=True, metadata={"description": "Prepared stage track id"})
    delete_files = fields.Boolean(load_default=True, metadata={"description": "Delete generated files"})


@prepare_bp.route("/prepare", methods=["GET"])
def prepare():
    """Stage preparation page."""
    k = get_karaoke_instance()
    search_string = request.args.get("search_string")
    search_count = _bounded_int_arg("search_count", DEFAULT_SEARCH_COUNT, DEFAULT_SEARCH_COUNT, MAX_SEARCH_COUNT)
    local_track_results = []
    local_file_results = []
    if search_string:
        local_track_results = _search_prepared_tracks(k, search_string, limit=12)
        local_file_results = _search_local_song_files(k, search_string, local_track_results, limit=8)
        search_results = get_search_results(
            search_string,
            k.additional_ytdl_args,
            limit=search_count,
        )
    else:
        search_string = None
        search_results = None
    tracks = _list_prepared_tracks(k, limit=50)
    processing_queue = _get_processing_queue(k, limit=100)

    return render_template(
        "prepare.html",
        site_title=get_site_name(),
        title="Musicas",
        search_results=search_results,
        local_track_results=local_track_results,
        local_file_results=local_file_results,
        search_string=search_string,
        search_count=search_count,
        next_search_count=min(search_count + DEFAULT_SEARCH_COUNT, MAX_SEARCH_COUNT),
        max_search_count=MAX_SEARCH_COUNT,
        tracks=tracks,
        processing_queue=processing_queue,
        has_active_preparation=_has_active_preparation(tracks, processing_queue),
        guests=_guest_names(k),
    )


@prepare_bp.route("/prepare/youtube", methods=["POST"])
@prepare_bp.arguments(PrepareYoutubeBody, location="json")
def prepare_youtube(form):
    """Queue a YouTube/YouTube Music result for stage preparation."""
    k = get_karaoke_instance()
    result = k.coach_preparation.prepare_youtube(
        url=form["song_url"],
        title=form.get("song_title"),
        user=form.get("song_added_by"),
    )
    return jsonify({"status": "ok", **result})


@prepare_bp.route("/prepare/local", methods=["POST"])
@prepare_bp.arguments(PrepareLocalBody, location="json")
def prepare_local(form):
    """Register a local media file for stage preparation."""
    k = get_karaoke_instance()
    result = k.coach_preparation.register_local_file(form["file_path"])
    return jsonify({"status": "ok", **result})


@prepare_bp.route("/prepare/enqueue", methods=["POST"])
@prepare_bp.arguments(EnqueueCoachBody, location="json")
def enqueue_prepared_track(form):
    """Queue a prepared stage track, preferring its instrumental stem."""
    k = get_karaoke_instance()
    playable = k.coach_preparation.get_playable_track_asset(int(form["track_id"]))
    if not playable:
        return jsonify({"status": "error", "message": "Track preparado nao encontrado."}), 404

    result = k.queue_manager.enqueue(
        playable["path"],
        format_guest_names(form.get("song_added_by"), fallback="Biaoke Palco"),
        title=playable["title"],
    )
    return jsonify(
        {
            "status": "ok" if result[0] else "error",
            "success": result[0],
            "message": result[1],
            "using_instrumental": playable["using_instrumental"],
        }
    ), 200 if result[0] else 400


@prepare_bp.route("/prepare/reanalyze", methods=["POST"])
@prepare_bp.arguments(CoachTrackActionBody, location="json")
def reanalyze_prepared_track(form):
    """Queue a prepared stage track for a fresh guide generation."""
    k = get_karaoke_instance()
    try:
        result = k.coach_preparation.reanalyze_track(int(form["track_id"]))
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    if not result:
        return jsonify({"status": "error", "message": "Track preparado nao encontrado."}), 404
    return jsonify({"status": "ok", **result})


@prepare_bp.route("/prepare/review-ai", methods=["POST"])
@prepare_bp.arguments(CoachTrackActionBody, location="json")
def review_ai_prepared_track(form):
    """Review and correct a generated stage guide with AI."""
    k = get_karaoke_instance()
    try:
        result = k.coach_preparation.review_track_with_ai(int(form["track_id"]))
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    if not result:
        return jsonify({"status": "error", "message": "Track preparado nao encontrado."}), 404
    return jsonify({"status": "ok", "message": "Revisao por IA concluida.", **result})


@prepare_bp.route("/prepare/revert-ai", methods=["POST"])
@prepare_bp.arguments(CoachTrackActionBody, location="json")
def revert_ai_prepared_track(form):
    """Restore the stage guide snapshot saved before AI review."""
    k = get_karaoke_instance()
    try:
        result = k.coach_preparation.revert_ai_review(int(form["track_id"]))
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    if not result:
        return jsonify({"status": "error", "message": "Track preparado nao encontrado."}), 404
    return jsonify({"status": "ok", "message": "Revisao por IA revertida.", **result})


@prepare_bp.route("/prepare/delete", methods=["POST"])
@prepare_bp.arguments(CoachTrackActionBody, location="json")
def delete_prepared_track(form):
    """Delete a prepared stage track and its generated files."""
    k = get_karaoke_instance()
    result = k.coach_preparation.delete_track(
        int(form["track_id"]),
        delete_files=bool(form.get("delete_files", True)),
    )
    if not result:
        return jsonify({"status": "error", "message": "Track preparado nao encontrado."}), 404
    return jsonify({"status": "ok", "message": "Musica removida do Palco.", **result})


@prepare_bp.route("/prepare/status", methods=["GET"])
def prepare_status():
    """Return current stage preparation catalog status."""
    k = get_karaoke_instance()
    tracks = _list_prepared_tracks(k, limit=100)
    processing_queue = _get_processing_queue(k, limit=100)
    downloads = _get_downloads_status(k)
    return jsonify(
        {
            "tracks": tracks,
            "processing_queue": processing_queue,
            "downloads": downloads,
            "has_active_preparation": _has_active_preparation(tracks, processing_queue, downloads),
        }
    )


def _bounded_int_arg(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


def _has_active_preparation(
    tracks: list[dict],
    processing_queue: list[dict],
    downloads: dict | None = None,
) -> bool:
    if processing_queue:
        return True
    if any(track.get("status") in {"queued", "processing"} for track in tracks):
        return True
    downloads = downloads or {}
    return bool(downloads.get("active") or downloads.get("pending"))


def _list_prepared_tracks(k, *, limit: int) -> list[dict]:
    tracks = k.coach_preparation.list_tracks(limit=limit)
    return tracks if isinstance(tracks, list) else []


def _search_prepared_tracks(k, query: str, *, limit: int) -> list[dict]:
    search = getattr(k.coach_preparation, "search_tracks", None)
    if not callable(search):
        return []
    tracks = search(query, limit=limit)
    return tracks if isinstance(tracks, list) else []


def _get_processing_queue(k, *, limit: int) -> list[dict]:
    get_queue = getattr(k.coach_preparation, "get_processing_queue", None)
    if not callable(get_queue):
        return []
    queue = get_queue(limit=limit)
    return queue if isinstance(queue, list) else []


def _get_downloads_status(k) -> dict:
    download_manager = getattr(k, "download_manager", None)
    get_status = getattr(download_manager, "get_downloads_status", None)
    if not callable(get_status):
        return {}
    downloads = get_status()
    return downloads if isinstance(downloads, dict) else {}


def _search_local_song_files(
    k,
    query: str,
    prepared_tracks: list[dict],
    *,
    limit: int = 8,
) -> list[dict]:
    """Find matching local library files that do not already have a Palco track."""
    terms = _prepare_search_terms(query)
    if not terms:
        return []

    prepared_paths = _prepared_track_paths(prepared_tracks)
    matches = []
    for song_path in k.song_manager.songs:
        if song_path in prepared_paths:
            continue
        display_title = k.song_manager.display_name_from_path(song_path)
        haystack = _normalize_prepare_search(f"{display_title} {song_path}")
        if not all(term in haystack for term in terms):
            continue
        matches.append(
            {
                "display_title": display_title,
                "file_path": song_path,
                "source_type": "local",
                "status": "not_prepared",
            }
        )
        if len(matches) >= limit:
            break
    return matches


def _prepared_track_paths(tracks: list[dict]) -> set[str]:
    paths = set()
    for track in tracks:
        assets = track.get("assets") or {}
        for raw_path in (
            track.get("file_path"),
            assets.get("original_audio_path"),
            assets.get("instrumental_audio_path"),
            assets.get("vocal_reference_path"),
        ):
            if raw_path:
                paths.add(str(raw_path))
    return paths


def _prepare_search_terms(query: str) -> list[str]:
    return [term for term in _normalize_prepare_search(query).split() if term]


def _normalize_prepare_search(text: str | None) -> str:
    import re

    normalized = remove_accents(str(text or "")).casefold()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()

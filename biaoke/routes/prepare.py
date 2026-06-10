"""Coach preparation catalog routes."""

from __future__ import annotations

import flask_babel
from flask import jsonify, render_template, request
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from biaoke.lib.current_app import get_karaoke_instance, get_site_name
from biaoke.lib.youtube_dl import get_search_results

_ = flask_babel.gettext

prepare_bp = Blueprint("prepare", __name__)


class PrepareYoutubeBody(Schema):
    song_url = fields.String(required=True, metadata={"description": "YouTube URL to prepare"})
    song_title = fields.String(load_default="", metadata={"description": "Display title"})
    song_added_by = fields.String(load_default="", metadata={"description": "Requesting user"})


class PrepareLocalBody(Schema):
    file_path = fields.String(required=True, metadata={"description": "Local media file path"})


class EnqueueCoachBody(Schema):
    track_id = fields.Integer(required=True, metadata={"description": "Prepared coach track id"})
    song_added_by = fields.String(load_default="", metadata={"description": "Requesting user"})


class CoachTrackActionBody(Schema):
    track_id = fields.Integer(required=True, metadata={"description": "Prepared coach track id"})
    delete_files = fields.Boolean(load_default=True, metadata={"description": "Delete generated files"})


@prepare_bp.route("/prepare", methods=["GET"])
def prepare():
    """Coach preparation page."""
    k = get_karaoke_instance()
    search_string = request.args.get("search_string")
    if search_string:
        search_results = get_search_results(search_string, k.additional_ytdl_args)
    else:
        search_string = None
        search_results = None
    tracks = k.coach_preparation.list_tracks(limit=50)

    return render_template(
        "prepare.html",
        site_title=get_site_name(),
        title=_("Prepare Coach"),
        search_results=search_results,
        search_string=search_string,
        tracks=tracks,
        has_active_preparation=any(
            track.get("status") in {"queued", "processing"} for track in tracks
        ),
    )


@prepare_bp.route("/prepare/youtube", methods=["POST"])
@prepare_bp.arguments(PrepareYoutubeBody, location="json")
def prepare_youtube(form):
    """Queue a YouTube/YouTube Music result for coach preparation."""
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
    """Register a local media file for coach preparation."""
    k = get_karaoke_instance()
    result = k.coach_preparation.register_local_file(form["file_path"])
    return jsonify({"status": "ok", **result})


@prepare_bp.route("/prepare/enqueue", methods=["POST"])
@prepare_bp.arguments(EnqueueCoachBody, location="json")
def enqueue_prepared_track(form):
    """Queue a prepared coach track, preferring its instrumental stem."""
    k = get_karaoke_instance()
    playable = k.coach_preparation.get_playable_track_asset(int(form["track_id"]))
    if not playable:
        return jsonify({"status": "error", "message": "Track preparado nao encontrado."}), 404

    result = k.queue_manager.enqueue(
        playable["path"],
        form.get("song_added_by") or "Biaoke Coach",
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
    """Queue a prepared coach track for a fresh guide generation."""
    k = get_karaoke_instance()
    try:
        result = k.coach_preparation.reanalyze_track(int(form["track_id"]))
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    if not result:
        return jsonify({"status": "error", "message": "Track preparado nao encontrado."}), 404
    return jsonify({"status": "ok", **result})


@prepare_bp.route("/prepare/delete", methods=["POST"])
@prepare_bp.arguments(CoachTrackActionBody, location="json")
def delete_prepared_track(form):
    """Delete a prepared coach track and its generated files."""
    k = get_karaoke_instance()
    result = k.coach_preparation.delete_track(
        int(form["track_id"]),
        delete_files=bool(form.get("delete_files", True)),
    )
    if not result:
        return jsonify({"status": "error", "message": "Track preparado nao encontrado."}), 404
    return jsonify({"status": "ok", "message": "Musica removida do Coach.", **result})


@prepare_bp.route("/prepare/status", methods=["GET"])
def prepare_status():
    """Return current coach preparation catalog status."""
    k = get_karaoke_instance()
    return jsonify({"tracks": k.coach_preparation.list_tracks(limit=100)})

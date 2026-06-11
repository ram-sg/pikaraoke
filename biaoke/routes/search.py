"""YouTube search and download routes."""

from __future__ import annotations

import json

import flask_babel
from flask import current_app, jsonify, redirect, request, url_for
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from biaoke.lib.current_app import get_karaoke_instance
from biaoke.lib.youtube_dl import get_stream_url

_ = flask_babel.gettext

search_bp = Blueprint("search", __name__)


class AutocompleteQuery(Schema):
    q = fields.String(required=True, metadata={"description": "Search query for autocomplete"})


class PreviewQuery(Schema):
    url = fields.String(required=True, metadata={"description": "YouTube video URL to preview"})


class DownloadBody(Schema):
    song_url = fields.String(required=True, metadata={"description": "YouTube URL to download"})
    song_added_by = fields.String(
        required=True, metadata={"description": "Name of the user requesting the download"}
    )
    song_title = fields.String(
        required=True, metadata={"description": "Display title for the song"}
    )
    queue = fields.Boolean(
        load_default=False, metadata={"description": "Whether to queue the song after download"}
    )


@search_bp.route("/search", methods=["GET"])
def search():
    """Compatibility alias for the unified stage preparation page."""
    args = request.args.to_dict(flat=True)
    args.pop("non_karaoke", None)
    return redirect(url_for("prepare.prepare", **args))


@search_bp.route("/autocomplete")
@search_bp.arguments(AutocompleteQuery, location="query")
def autocomplete(query):
    """Search available songs for autocomplete."""
    k = get_karaoke_instance()
    q = query["q"].lower()
    result = []
    for each in k.song_manager.songs:
        if q in each.lower():
            result.append(
                {
                    "path": each,
                    "fileName": k.song_manager.display_name_from_path(each),
                    "type": "autocomplete",
                }
            )
    response = current_app.response_class(response=json.dumps(result), mimetype="application/json")
    return response


@search_bp.route("/preview")
@search_bp.arguments(PreviewQuery, location="query")
def preview(query):
    """Get a direct stream URL for previewing a YouTube video."""
    k = get_karaoke_instance()
    stream_url = get_stream_url(query["url"], k.additional_ytdl_args)
    if stream_url is None:
        return jsonify({"error": "Could not fetch stream URL"}), 500
    return jsonify({"stream_url": stream_url})


@search_bp.route("/download", methods=["POST"])
@search_bp.arguments(DownloadBody, location="json")
def download(form):
    """Compatibility endpoint that now prepares a stage track instead of raw playback."""
    k = get_karaoke_instance()
    song = form["song_url"]
    user = form["song_added_by"]
    title = form["song_title"]
    result = k.coach_preparation.prepare_youtube(url=song, title=title, user=user)

    return jsonify(
        {
            "status": "ok",
            "mode": "palco_prepare",
            "message": "Musica enviada para preparo do Palco.",
            **result,
        }
    )

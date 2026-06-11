"""Playback control routes for skip, pause, volume, and transpose."""

import flask_babel
from flask import jsonify, redirect, url_for
from flask_smorest import Blueprint

from biaoke.lib.current_app import broadcast_event, get_karaoke_instance

_ = flask_babel.gettext


controller_bp = Blueprint("controller", __name__)


def _playback_state(k) -> dict:
    """Return the current player state for lightweight frontend controls."""
    try:
        state = k.get_now_playing()
    except AttributeError:
        state = k.playback_controller.get_now_playing()
    return state or {}


def _json_player_response(k, success: bool = True, **extra):
    payload = {"success": success, "state": _playback_state(k)}
    payload.update(extra)
    return jsonify(payload)


def _current_queue_item(k) -> dict | None:
    controller = k.playback_controller
    if not controller.now_playing_filename:
        return None
    return {
        "file": controller.now_playing_filename,
        "user": controller.now_playing_user or "Biaoke",
        "title": controller.now_playing or controller.now_playing_filename,
        "semitones": int(controller.now_playing_transpose or 0),
    }


@controller_bp.route("/skip")
def skip():
    """Skip the currently playing song."""
    k = get_karaoke_instance()
    broadcast_event("skip", "user command")
    k.playback_controller.skip()
    return redirect(url_for("home.home"))


@controller_bp.route("/pause")
def pause():
    """Toggle pause/resume playback."""
    k = get_karaoke_instance()
    if k.playback_controller.is_paused:
        broadcast_event("play")
    else:
        broadcast_event("pause")
    k.playback_controller.pause()
    return redirect(url_for("home.home"))


@controller_bp.route("/player/pause", methods=["POST"])
def player_pause():
    """Toggle pause/resume playback and return JSON for the stage header."""
    k = get_karaoke_instance()
    was_paused = bool(k.playback_controller.is_paused)
    success = k.playback_controller.pause()
    if success:
        broadcast_event("play" if was_paused else "pause")
    return _json_player_response(k, success=success)


@controller_bp.route("/player/stop", methods=["POST"])
def player_stop():
    """Stop the current song without navigating away from the stage."""
    k = get_karaoke_instance()
    has_song = bool(k.playback_controller.now_playing)
    if has_song:
        broadcast_event("skip", "user stop")
        k.playback_controller.end_song(reason="skip")
    return _json_player_response(k, success=has_song)


@controller_bp.route("/player/next", methods=["POST"])
def player_next():
    """Advance to the next queued song."""
    k = get_karaoke_instance()
    has_song = bool(k.playback_controller.now_playing)
    if has_song:
        broadcast_event("skip", "next song")
        if not k.playback_controller.skip(log_action=False):
            k.playback_controller.end_song(reason="skip")
    return _json_player_response(k, success=has_song)


@controller_bp.route("/player/previous", methods=["POST"])
def player_previous():
    """Return to the previous played song, if history is available."""
    k = get_karaoke_instance()
    queued = k.queue_manager.queue_previous(_current_queue_item(k))
    if queued and k.playback_controller.now_playing:
        broadcast_event("skip", "previous song")
        if not k.playback_controller.skip(log_action=False):
            k.playback_controller.end_song(reason="skip")
    return _json_player_response(k, success=queued)


@controller_bp.route("/player/restart", methods=["POST"])
def player_restart():
    """Restart the current song from the beginning and return JSON."""
    k = get_karaoke_instance()
    has_song = bool(k.playback_controller.now_playing)
    if has_song:
        k.playback_controller.now_playing_position = 0
        broadcast_event("restart")
        k.restart()
    return _json_player_response(k, success=has_song, position=0 if has_song else None)


@controller_bp.route("/transpose/<semitones>", methods=["GET"])
def transpose(semitones):
    """Transpose (pitch shift) the current song."""
    k = get_karaoke_instance()
    broadcast_event("skip", "transpose current")
    k.transpose_current(int(semitones))
    return redirect(url_for("home.home"))


@controller_bp.route("/restart")
def restart():
    """Restart the current song from the beginning."""
    k = get_karaoke_instance()
    broadcast_event("restart")
    k.restart()
    return redirect(url_for("home.home"))


@controller_bp.route("/volume/<volume>")
def volume(volume):
    """Set the playback volume."""
    k = get_karaoke_instance()
    broadcast_event("volume", volume)
    k.volume_change(float(volume))
    return redirect(url_for("home.home"))


@controller_bp.route("/vol_up")
def vol_up():
    """Increase volume by 10%."""
    k = get_karaoke_instance()
    broadcast_event("volume", "up")
    k.vol_up()
    return redirect(url_for("home.home"))


@controller_bp.route("/vol_down")
def vol_down():
    """Decrease volume by 10%."""
    k = get_karaoke_instance()
    broadcast_event("volume", "down")
    k.vol_down()
    return redirect(url_for("home.home"))

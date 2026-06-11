"""Tests for stage player control routes."""

from unittest.mock import MagicMock, patch

import pytest
import werkzeug
from flask import Flask

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from biaoke.routes.controller import controller_bp


@pytest.fixture
def app():
    test_app = Flask(__name__)
    test_app.register_blueprint(controller_bp)
    return test_app


@pytest.fixture
def client(app):
    return app.test_client()


def _mock_karaoke():
    k = MagicMock()
    k.get_now_playing.return_value = {
        "now_playing": "Song",
        "now_playing_url": "/stream",
        "is_paused": False,
    }
    k.playback_controller.now_playing = "Song"
    k.playback_controller.now_playing_filename = "/songs/song.mp4"
    k.playback_controller.now_playing_user = "User"
    k.playback_controller.now_playing_transpose = 0
    return k


@patch("biaoke.routes.controller.broadcast_event")
@patch("biaoke.routes.controller.get_karaoke_instance")
def test_player_next_skips_current_song(mock_get_instance, mock_broadcast, client):
    k = _mock_karaoke()
    mock_get_instance.return_value = k

    response = client.post("/player/next")

    assert response.status_code == 200
    assert response.get_json()["success"] is True
    k.playback_controller.skip.assert_called_once_with(log_action=False)
    mock_broadcast.assert_called_once_with("skip", "next song")


@patch("biaoke.routes.controller.broadcast_event")
@patch("biaoke.routes.controller.get_karaoke_instance")
def test_player_previous_queues_previous_before_skipping(mock_get_instance, mock_broadcast, client):
    k = _mock_karaoke()
    k.queue_manager.queue_previous.return_value = True
    mock_get_instance.return_value = k

    response = client.post("/player/previous")

    assert response.status_code == 200
    assert response.get_json()["success"] is True
    k.queue_manager.queue_previous.assert_called_once_with(
        {
            "file": "/songs/song.mp4",
            "user": "User",
            "title": "Song",
            "semitones": 0,
        }
    )
    k.playback_controller.skip.assert_called_once_with(log_action=False)
    mock_broadcast.assert_called_once_with("skip", "previous song")


@patch("biaoke.routes.controller.broadcast_event")
@patch("biaoke.routes.controller.get_karaoke_instance")
def test_player_previous_without_history_does_not_skip(mock_get_instance, mock_broadcast, client):
    k = _mock_karaoke()
    k.queue_manager.queue_previous.return_value = False
    mock_get_instance.return_value = k

    response = client.post("/player/previous")

    assert response.status_code == 200
    assert response.get_json()["success"] is False
    k.playback_controller.skip.assert_not_called()
    mock_broadcast.assert_not_called()

import json
from unittest.mock import MagicMock, patch

import werkzeug
from flask import Flask

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from biaoke.routes.prepare import prepare_bp


def test_prepare_youtube_route_queues_job():
    app = Flask(__name__)
    app.register_blueprint(prepare_bp)
    client = app.test_client()

    mock_karaoke = MagicMock()
    mock_karaoke.coach_preparation.prepare_youtube.return_value = {
        "track": {"id": 1},
        "job": {"id": 2},
    }

    with patch("biaoke.routes.prepare.get_karaoke_instance", return_value=mock_karaoke):
        response = client.post(
            "/prepare/youtube",
            json={
                "song_url": "https://youtube.com/watch?v=abc12345678",
                "song_title": "Artist - Song",
                "song_added_by": "Ramon",
            },
        )

    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "ok"
    mock_karaoke.coach_preparation.prepare_youtube.assert_called_once_with(
        url="https://youtube.com/watch?v=abc12345678",
        title="Artist - Song",
        user="Ramon",
    )


def test_prepare_status_route_lists_tracks():
    app = Flask(__name__)
    app.register_blueprint(prepare_bp)
    client = app.test_client()

    mock_karaoke = MagicMock()
    mock_karaoke.coach_preparation.list_tracks.return_value = [{"id": 1, "status": "queued"}]

    with patch("biaoke.routes.prepare.get_karaoke_instance", return_value=mock_karaoke):
        response = client.get("/prepare/status")

    assert response.status_code == 200
    assert json.loads(response.data)["tracks"] == [{"id": 1, "status": "queued"}]


def test_prepare_enqueue_route_queues_playable_coach_asset():
    app = Flask(__name__)
    app.register_blueprint(prepare_bp)
    client = app.test_client()

    mock_karaoke = MagicMock()
    mock_karaoke.coach_preparation.get_playable_track_asset.return_value = {
        "path": "/songs/.biaoke-stems/song.instrumental.wav",
        "title": "Artist - Song",
        "using_instrumental": True,
    }
    mock_karaoke.queue_manager.enqueue.return_value = [True, "ok"]

    with patch("biaoke.routes.prepare.get_karaoke_instance", return_value=mock_karaoke):
        response = client.post(
            "/prepare/enqueue",
            json={"track_id": 7, "song_added_by": "Ramon"},
        )

    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "ok"
    assert data["using_instrumental"] is True
    mock_karaoke.coach_preparation.get_playable_track_asset.assert_called_once_with(7)
    mock_karaoke.queue_manager.enqueue.assert_called_once_with(
        "/songs/.biaoke-stems/song.instrumental.wav",
        "Ramon",
        title="Artist - Song",
    )


def test_prepare_reanalyze_route_queues_track():
    app = Flask(__name__)
    app.register_blueprint(prepare_bp)
    client = app.test_client()

    mock_karaoke = MagicMock()
    mock_karaoke.coach_preparation.reanalyze_track.return_value = {
        "track": {"id": 7, "status": "processing"},
        "job": {"id": 8, "stage": "analyze_pending"},
    }

    with patch("biaoke.routes.prepare.get_karaoke_instance", return_value=mock_karaoke):
        response = client.post("/prepare/reanalyze", json={"track_id": 7})

    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "ok"
    mock_karaoke.coach_preparation.reanalyze_track.assert_called_once_with(7)


def test_prepare_review_ai_route_reviews_track():
    app = Flask(__name__)
    app.register_blueprint(prepare_bp)
    client = app.test_client()

    mock_karaoke = MagicMock()
    mock_karaoke.coach_preparation.review_track_with_ai.return_value = {
        "track": {"id": 7, "status": "ready"},
        "job": {"id": 9, "stage": "ai_review"},
        "review": {"model": "deepseek-v4-pro"},
    }

    with patch("biaoke.routes.prepare.get_karaoke_instance", return_value=mock_karaoke):
        response = client.post("/prepare/review-ai", json={"track_id": 7})

    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "ok"
    assert data["message"] == "Revisao por IA concluida."
    mock_karaoke.coach_preparation.review_track_with_ai.assert_called_once_with(7)


def test_prepare_revert_ai_route_restores_track():
    app = Flask(__name__)
    app.register_blueprint(prepare_bp)
    client = app.test_client()

    mock_karaoke = MagicMock()
    mock_karaoke.coach_preparation.revert_ai_review.return_value = {
        "track": {"id": 7, "status": "needs_review"},
        "job": {"id": 10, "stage": "ai_revert"},
    }

    with patch("biaoke.routes.prepare.get_karaoke_instance", return_value=mock_karaoke):
        response = client.post("/prepare/revert-ai", json={"track_id": 7})

    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "ok"
    assert data["message"] == "Revisao por IA revertida."
    mock_karaoke.coach_preparation.revert_ai_review.assert_called_once_with(7)


def test_prepare_delete_route_removes_track():
    app = Flask(__name__)
    app.register_blueprint(prepare_bp)
    client = app.test_client()

    mock_karaoke = MagicMock()
    mock_karaoke.coach_preparation.delete_track.return_value = {
        "track": {"id": 7},
        "deleted_paths": ["/songs/song.mp4"],
        "kept_paths": [],
    }

    with patch("biaoke.routes.prepare.get_karaoke_instance", return_value=mock_karaoke):
        response = client.post("/prepare/delete", json={"track_id": 7, "delete_files": True})

    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "ok"
    assert data["message"] == "Musica removida do Palco."
    mock_karaoke.coach_preparation.delete_track.assert_called_once_with(7, delete_files=True)

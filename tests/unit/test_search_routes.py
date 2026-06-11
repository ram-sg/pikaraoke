import json
from unittest.mock import MagicMock, patch

import werkzeug
from flask import Flask

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from biaoke.routes.prepare import prepare_bp
from biaoke.routes.search import search_bp


def test_search_page_redirects_to_unified_prepare_page():
    app = Flask(__name__)
    app.register_blueprint(prepare_bp)
    app.register_blueprint(search_bp)
    client = app.test_client()

    response = client.get("/search?search_string=alice%20in%20chains&non_karaoke=true")

    assert response.status_code == 302
    assert response.headers["Location"] == "/prepare?search_string=alice+in+chains"


def test_legacy_download_endpoint_prepares_coach_track():
    app = Flask(__name__)
    app.register_blueprint(search_bp)
    client = app.test_client()

    mock_karaoke = MagicMock()
    mock_karaoke.coach_preparation.prepare_youtube.return_value = {
        "track": {"id": 1},
        "job": {"id": 2},
    }

    with patch("biaoke.routes.search.get_karaoke_instance", return_value=mock_karaoke):
        response = client.post(
            "/download",
            json={
                "song_url": "https://youtube.com/watch?v=abc12345678",
                "song_title": "Artist - Song",
                "song_added_by": "Ramon",
                "queue": True,
            },
        )

    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "ok"
    assert data["mode"] == "palco_prepare"
    mock_karaoke.coach_preparation.prepare_youtube.assert_called_once_with(
        url="https://youtube.com/watch?v=abc12345678",
        title="Artist - Song",
        user="Ramon",
    )
    mock_karaoke.download_manager.queue_download.assert_not_called()

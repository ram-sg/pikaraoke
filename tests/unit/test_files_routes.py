from unittest.mock import MagicMock, patch

import werkzeug
from flask import Flask

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from biaoke.routes.files import files_bp


def test_delete_file_route_deletes_library_song_when_not_queued():
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(files_bp)
    client = app.test_client()

    mock_karaoke = MagicMock()
    mock_karaoke.queue_manager.is_song_in_queue.return_value = False
    mock_karaoke.song_manager.display_name_from_path.return_value = "Problem Song"

    with (
        patch("biaoke.routes.files.get_karaoke_instance", return_value=mock_karaoke),
        patch("biaoke.routes.files.is_admin", return_value=True),
        patch("biaoke.routes.files._", side_effect=lambda value, *args, **kwargs: value),
    ):
        response = client.get("/files/delete?song=/songs/problem.mp4&referrer=/browse")

    assert response.status_code == 302
    assert response.headers["Location"] == "/browse"
    mock_karaoke.song_manager.delete.assert_called_once_with("/songs/problem.mp4")

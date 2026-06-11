"""Tests for guest management routes."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import werkzeug
from flask import Blueprint, Flask
from flask_babel import Babel

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from biaoke.routes.guests import guests_bp


@pytest.fixture
def app():
    template_dir = Path(__file__).parents[2] / "biaoke" / "templates"
    test_app = Flask(__name__, template_folder=str(template_dir))
    test_app.secret_key = "test"
    Babel(test_app)
    for name, endpoint, path in [
        ("home", "home", "/"),
        ("queue", "queue", "/queue"),
        ("prepare", "prepare", "/prepare"),
        ("files", "browse", "/browse"),
        ("splash", "palco_display", "/palco"),
        ("info", "info", "/info"),
    ]:
        bp = Blueprint(name, __name__)
        bp.add_url_rule(path, endpoint, lambda: "")
        test_app.register_blueprint(bp)
    test_app.register_blueprint(guests_bp)
    return test_app


@pytest.fixture
def client(app):
    return app.test_client()


@patch("biaoke.routes.guests.get_site_name", return_value="Biaoke")
@patch("biaoke.routes.guests.get_karaoke_instance")
def test_guests_page_lists_saved_guests(mock_get_instance, _mock_site_name, client):
    mock_karaoke = MagicMock()
    mock_karaoke.guest_manager.list_guests.return_value = ["Ana", "Joao"]
    mock_get_instance.return_value = mock_karaoke

    response = client.get("/guests")

    assert response.status_code == 200
    assert b"Ana" in response.data
    assert b"Joao" in response.data


@patch("biaoke.routes.guests.get_karaoke_instance")
def test_add_guest_posts_to_manager(mock_get_instance, client):
    mock_karaoke = MagicMock()
    mock_karaoke.guest_manager.add_guest.return_value = (True, "ok")
    mock_get_instance.return_value = mock_karaoke

    response = client.post("/guests", data={"name": "Ana"})

    assert response.status_code == 302
    mock_karaoke.guest_manager.add_guest.assert_called_once_with("Ana")

"""Tests for the optional site-wide login gate."""

from pathlib import Path

import pytest
from flask import Flask
from flask_babel import Babel

from pikaraoke.routes.site_auth import require_site_auth, site_auth_bp


@pytest.fixture
def app():
    template_dir = Path(__file__).parents[2] / "pikaraoke" / "templates"
    test_app = Flask(__name__, template_folder=str(template_dir))
    test_app.secret_key = "test"
    test_app.jinja_env.add_extension("jinja2.ext.i18n")
    test_app.config["SITE_NAME"] = "PiKaraoke"
    test_app.config["SITE_AUTH_LOGIN"] = None
    test_app.config["SITE_AUTH_PASSWORD"] = None
    Babel(test_app)
    test_app.register_blueprint(site_auth_bp)
    test_app.before_request(require_site_auth)

    @test_app.route("/")
    def index():
        return "ok"

    @test_app.route("/json")
    def json_route():
        return {"ok": True}

    return test_app


@pytest.fixture
def client(app):
    return app.test_client()


def enable_site_auth(app):
    app.config["SITE_AUTH_LOGIN"] = "owner"
    app.config["SITE_AUTH_PASSWORD"] = "secret"


class TestSiteAuth:
    def test_disabled_allows_requests(self, client):
        response = client.get("/")

        assert response.status_code == 200
        assert response.data == b"ok"

    def test_enabled_redirects_to_login(self, app, client):
        enable_site_auth(app)

        response = client.get("/queue?x=1")

        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login?next=/queue?x%3D1")

    def test_successful_login_allows_next_request(self, app, client):
        enable_site_auth(app)

        response = client.post(
            "/login",
            data={"login": "owner", "password": "secret", "next": "/"},
        )

        assert response.status_code == 302
        assert response.headers["Location"] == "/"
        assert client.get("/").status_code == 200

    def test_failed_login_shows_error(self, app, client):
        enable_site_auth(app)

        response = client.post(
            "/login",
            data={"login": "owner", "password": "wrong", "next": "/"},
        )

        assert response.status_code == 200
        assert b"Invalid login or password" in response.data

    def test_socketio_without_session_returns_unauthorized(self, app, client):
        enable_site_auth(app)

        response = client.get("/socket.io/")

        assert response.status_code == 401

    def test_json_without_session_returns_json_unauthorized(self, app, client):
        enable_site_auth(app)

        response = client.get("/json", headers={"Accept": "application/json"})

        assert response.status_code == 401
        assert response.get_json() == {"error": "Authentication required"}

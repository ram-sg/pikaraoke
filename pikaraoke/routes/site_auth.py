"""Site-wide login gate for public deployments."""

from __future__ import annotations

import hmac
import os

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

site_auth_bp = Blueprint("site_auth", __name__)

LOGIN_ENV = "PIKARAOKE_LOGIN"
PASSWORD_ENV = "PIKARAOKE_PASSWORD"
LOGIN_SESSION_KEY = "site_authenticated"
LOGIN_NAME_SESSION_KEY = "site_login"


def site_auth_config_from_env() -> dict[str, str | None]:
    """Return site auth config from environment variables."""
    return {
        "SITE_AUTH_LOGIN": os.environ.get(LOGIN_ENV, "").strip() or None,
        "SITE_AUTH_PASSWORD": os.environ.get(PASSWORD_ENV) or None,
    }


def is_site_auth_enabled() -> bool:
    """Return whether site-wide auth should protect requests."""
    return bool(
        current_app.config.get("SITE_AUTH_LOGIN")
        and current_app.config.get("SITE_AUTH_PASSWORD")
    )


def _safe_next_url(next_url: str | None) -> str:
    if not next_url or not next_url.startswith("/") or next_url.startswith("//"):
        return "/"
    return next_url


def _current_url() -> str:
    if request.query_string:
        return f"{request.path}?{request.query_string.decode('utf-8', 'ignore')}"
    return request.path


def _is_authenticated() -> bool:
    return bool(
        session.get(LOGIN_SESSION_KEY)
        and session.get(LOGIN_NAME_SESSION_KEY) == current_app.config.get("SITE_AUTH_LOGIN")
    )


def require_site_auth():
    """Flask before_request hook that redirects unauthenticated users."""
    if not is_site_auth_enabled():
        return None

    if request.endpoint in {"static", "site_auth.login"}:
        return None

    if request.method == "OPTIONS":
        return None

    if _is_authenticated():
        return None

    if request.path.startswith("/socket.io/"):
        return "Authentication required", 401

    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        return jsonify({"error": "Authentication required"}), 401

    return redirect(url_for("site_auth.login", next=_safe_next_url(_current_url())))


@site_auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Render and process the site-wide login form."""
    if not is_site_auth_enabled():
        return redirect("/")

    next_url = _safe_next_url(request.values.get("next"))
    error = None

    if request.method == "POST":
        expected_login = current_app.config["SITE_AUTH_LOGIN"]
        expected_password = current_app.config["SITE_AUTH_PASSWORD"]
        submitted_login = request.form.get("login", "").strip()
        submitted_password = request.form.get("password", "")

        if hmac.compare_digest(submitted_login, expected_login) and hmac.compare_digest(
            submitted_password, expected_password
        ):
            session[LOGIN_SESSION_KEY] = True
            session[LOGIN_NAME_SESSION_KEY] = expected_login
            return redirect(next_url)

        error = "Invalid login or password"

    return render_template(
        "login.html",
        site_title=current_app.config.get("SITE_NAME", "PiKaraoke"),
        title="Login",
        blank_page=True,
        next_url=next_url,
        error=error,
    )


@site_auth_bp.route("/site-logout")
def logout():
    """Clear the site-wide login session."""
    session.pop(LOGIN_SESSION_KEY, None)
    session.pop(LOGIN_NAME_SESSION_KEY, None)
    return redirect(url_for("site_auth.login"))

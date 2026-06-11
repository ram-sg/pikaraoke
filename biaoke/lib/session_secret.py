"""Persistent Flask session secret handling."""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

from biaoke.lib.get_platform import get_data_directory

SECRET_KEY_ENV = "BIAOKE_SECRET_KEY"
SECRET_KEY_FILE = "session_secret_key"


def load_flask_secret_key() -> str:
    """Return a stable Flask secret key for signing browser sessions."""
    env_value = os.environ.get(SECRET_KEY_ENV, "").strip()
    if env_value:
        return env_value

    secret_path = Path(get_data_directory()) / SECRET_KEY_FILE
    try:
        existing = secret_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""
    except OSError as exc:
        logging.warning("Could not read Flask session secret from %s: %s", secret_path, exc)
        existing = ""

    if existing:
        return existing

    secret = secrets.token_urlsafe(48)
    try:
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = secret_path.with_suffix(".tmp")
        tmp_path.write_text(secret + "\n", encoding="utf-8")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, secret_path)
    except OSError as exc:
        logging.warning("Could not persist Flask session secret to %s: %s", secret_path, exc)

    return secret

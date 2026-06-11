from pathlib import Path
from unittest.mock import patch

from biaoke.lib.session_secret import SECRET_KEY_ENV, SECRET_KEY_FILE, load_flask_secret_key


def test_env_secret_key_takes_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv(SECRET_KEY_ENV, "fixed-secret")

    with patch("biaoke.lib.session_secret.get_data_directory", return_value=str(tmp_path)):
        assert load_flask_secret_key() == "fixed-secret"

    assert not (tmp_path / SECRET_KEY_FILE).exists()


def test_existing_secret_key_file_is_reused(tmp_path, monkeypatch):
    monkeypatch.delenv(SECRET_KEY_ENV, raising=False)
    secret_path = tmp_path / SECRET_KEY_FILE
    secret_path.write_text("persisted-secret\n", encoding="utf-8")

    with patch("biaoke.lib.session_secret.get_data_directory", return_value=str(tmp_path)):
        assert load_flask_secret_key() == "persisted-secret"


def test_missing_secret_key_file_is_created_and_reused(tmp_path, monkeypatch):
    monkeypatch.delenv(SECRET_KEY_ENV, raising=False)

    with patch("biaoke.lib.session_secret.get_data_directory", return_value=str(tmp_path)):
        first = load_flask_secret_key()
        second = load_flask_secret_key()

    assert first
    assert second == first
    assert (tmp_path / SECRET_KEY_FILE).read_text(encoding="utf-8").strip() == first


def test_blank_env_secret_key_falls_back_to_file(tmp_path, monkeypatch):
    monkeypatch.setenv(SECRET_KEY_ENV, "   ")
    Path(tmp_path / SECRET_KEY_FILE).write_text("file-secret\n", encoding="utf-8")

    with patch("biaoke.lib.session_secret.get_data_directory", return_value=str(tmp_path)):
        assert load_flask_secret_key() == "file-secret"

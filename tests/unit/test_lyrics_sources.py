"""Tests for external lyrics providers."""

import os
from unittest.mock import MagicMock, patch

from biaoke.lib.lyrics_sources import (
    find_lrclib_lyrics_for_media,
    infer_song_identity,
)


def test_infer_song_identity_from_youtube_karaoke_filename(tmp_path):
    media = tmp_path / "Adele - Hello Karaoke---abcdefghijk.mp4"
    media.write_bytes(b"fake")

    identity = infer_song_identity(media, duration_seconds=295)

    assert identity["artist_name"] == "Adele"
    assert identity["track_name"] == "Hello"
    assert identity["query"] == "Adele - Hello"
    assert identity["duration_seconds"] == 295


@patch("biaoke.lib.lyrics_sources.requests.get")
def test_find_lrclib_lyrics_for_media_returns_synced_guide(mock_get, tmp_path):
    media = tmp_path / "Adele - Hello---abcdefghijk.mp4"
    media.write_bytes(b"fake")
    response = MagicMock(status_code=200)
    response.json.return_value = [
        {
            "id": 10,
            "trackName": "Hello",
            "artistName": "Adele",
            "albumName": "25",
            "duration": 295,
            "syncedLyrics": "[00:01.00]Line one\n[00:03.00]Line two",
        }
    ]
    mock_get.return_value = response

    guide = find_lrclib_lyrics_for_media(media, duration_seconds=295)

    assert guide is not None
    assert guide["status"] == "ready"
    assert guide["source"] == "lrclib"
    assert guide["line_count"] == 2
    assert guide["source_metadata"]["id"] == 10
    assert guide["source_metadata"]["match_confidence"] == 0.88


@patch.dict(os.environ, {"BIAOKE_LRCLIB_BASE_URL": ""})
@patch("biaoke.lib.lyrics_sources.requests.get")
def test_find_lrclib_uses_default_base_url_when_env_is_empty(mock_get, tmp_path):
    media = tmp_path / "Adele - Hello---abcdefghijk.mp4"
    media.write_bytes(b"fake")
    response = MagicMock(status_code=200)
    response.json.return_value = []
    mock_get.return_value = response

    find_lrclib_lyrics_for_media(media, duration_seconds=295)

    assert mock_get.call_args[0][0] == "https://lrclib.net/api/search"


@patch.dict(os.environ, {"BIAOKE_LRCLIB_TIMEOUT": "12"})
@patch("biaoke.lib.lyrics_sources.requests.get")
def test_find_lrclib_uses_configured_timeout(mock_get, tmp_path):
    media = tmp_path / "Adele - Hello---abcdefghijk.mp4"
    media.write_bytes(b"fake")
    response = MagicMock(status_code=200)
    response.json.return_value = []
    mock_get.return_value = response

    find_lrclib_lyrics_for_media(media, duration_seconds=295)

    assert mock_get.call_args[1]["timeout"] == 12


@patch("biaoke.lib.lyrics_sources.requests.get")
def test_find_lrclib_lyrics_rejects_unsynced_results(mock_get, tmp_path):
    media = tmp_path / "Adele - Hello---abcdefghijk.mp4"
    media.write_bytes(b"fake")
    response = MagicMock(status_code=200)
    response.json.return_value = [
        {
            "id": 10,
            "trackName": "Hello",
            "artistName": "Adele",
            "duration": 295,
            "plainLyrics": "Line one",
            "syncedLyrics": None,
        }
    ]
    mock_get.return_value = response

    assert find_lrclib_lyrics_for_media(media, duration_seconds=295) is None

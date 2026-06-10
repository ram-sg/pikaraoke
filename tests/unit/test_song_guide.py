"""Tests for persistent Biaoke song guide packages."""

import json
from unittest.mock import patch

from biaoke.lib.song_guide import (
    build_song_guide,
    ensure_song_guide,
    get_lyrics_offset,
    guide_path_for_media,
    is_song_guide_stale,
    set_lyrics_offset,
    write_song_guide,
)


def test_guide_path_for_media_uses_biaoke_suffix(tmp_path):
    media = tmp_path / "Artist - Song---abc1234567x.mp4"

    assert guide_path_for_media(media) == (
        tmp_path / "Artist - Song---abc1234567x.biaoke-guide.json"
    )


def test_build_song_guide_from_language_ass(tmp_path):
    media = tmp_path / "song.mp4"
    subtitle = tmp_path / "song.pt-BR.ass"
    media.write_bytes(b"video")
    subtitle.write_text(
        """
[Events]
Format: Start, End, Text
Dialogue: 0:00:01.00,0:00:03.00,Primeira linha
""",
        encoding="utf-8",
    )

    guide = build_song_guide(media)

    assert guide["schema"] == "biaoke.song_guide"
    assert guide["version"] == 3
    assert guide["subtitle"]["basename"] == "song.pt-BR.ass"
    assert guide["lyrics"]["status"] == "ready"
    assert guide["lyrics"]["lines"][0]["text"] == "Primeira linha"
    assert guide["quality"]["status"] == "ready"


@patch("biaoke.lib.song_guide.find_external_lyrics_for_media", return_value=None)
def test_build_song_guide_without_subtitle_marks_lyrics_missing(mock_external, tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"video")

    guide = build_song_guide(media)

    mock_external.assert_called_once()
    assert guide["subtitle"] is None
    assert guide["lyrics"]["status"] == "missing"
    assert guide["lyrics"]["lines"] == []
    assert guide["quality"]["status"] == "needs_lyrics"


@patch("biaoke.lib.song_guide.find_external_lyrics_for_media", return_value=None)
def test_write_and_ensure_song_guide(mock_external, tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"video")

    guide = write_song_guide(media)
    path = guide_path_for_media(media)

    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["created_at"] == guide["created_at"]
    assert ensure_song_guide(media)["created_at"] == guide["created_at"]
    assert is_song_guide_stale(media) is False
    mock_external.assert_called_once()


@patch("biaoke.lib.song_guide.find_external_lyrics_for_media", return_value=None)
def test_guide_becomes_stale_when_subtitle_appears(mock_external, tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"video")
    write_song_guide(media)

    subtitle = tmp_path / "song.en.ass"
    subtitle.write_text(
        """
[Events]
Format: Start, End, Text
Dialogue: 0:00:01.00,0:00:02.00,Line
""",
        encoding="utf-8",
    )

    assert is_song_guide_stale(media) is True
    assert ensure_song_guide(media)["lyrics"]["status"] == "ready"


@patch("biaoke.lib.song_guide.find_external_lyrics_for_media")
def test_build_song_guide_uses_external_synced_lyrics(mock_external, tmp_path):
    media = tmp_path / "Adele - Hello---abcdefghijk.mp4"
    media.write_bytes(b"video")
    mock_external.return_value = {
        "status": "ready",
        "source": "lrclib",
        "source_format": "lrc",
        "confidence": 0.88,
        "has_karaoke_timing": False,
        "line_count": 1,
        "lines": [{"start": 1.0, "end": 3.0, "text": "Line", "segments": []}],
    }

    guide = build_song_guide(media)

    assert guide["lyrics"]["source"] == "lrclib"
    assert guide["lyrics"]["alignment"]["granularity"] == "line"
    assert guide["lyrics"]["alignment"]["paint_units"][0]["text"] == "Line"
    assert guide["metadata"]["artist_name"] == "Adele"
    assert guide["metadata"]["track_name"] == "Hello"
    assert guide["quality"]["status"] == "ready"


@patch("biaoke.lib.song_guide.find_external_lyrics_for_media", return_value=None)
def test_lyrics_offset_is_persisted_and_preserved_on_rebuild(mock_external, tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"video")

    guide = set_lyrics_offset(media, 2.5)
    rebuilt = write_song_guide(media)

    assert get_lyrics_offset(guide) == 2.5
    assert get_lyrics_offset(rebuilt) == 2.5
    assert get_lyrics_offset(ensure_song_guide(media)) == 2.5


@patch("biaoke.lib.song_guide.find_external_lyrics_for_media", return_value=None)
def test_lyrics_offset_is_clamped(mock_external, tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"video")

    guide = set_lyrics_offset(media, 999)

    assert get_lyrics_offset(guide) == 120.0

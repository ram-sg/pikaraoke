"""Tests for lyrics guide parsing."""

from biaoke.lib.lyrics import (
    build_lyrics_guide_from_ass,
    build_lyrics_guide_from_lrc,
    parse_ass_lyrics,
    parse_ass_time,
    parse_lrc_lyrics,
    parse_lrc_time,
)


def test_parse_ass_time():
    assert parse_ass_time("0:01:02.34") == 62.34
    assert parse_ass_time("bad") is None


def test_parse_lrc_time():
    assert parse_lrc_time("01:02.34") == 62.34
    assert parse_lrc_time("[00:17.123]") == 17.123
    assert parse_lrc_time("bad") is None


def test_parse_ass_lyrics_plain_dialogue():
    content = """
[Script Info]
Title: Test

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Hello world
"""

    lines, has_karaoke_timing = parse_ass_lyrics(content)

    assert has_karaoke_timing is False
    assert lines == [
        {
            "start": 1.0,
            "end": 3.0,
            "text": "Hello world",
            "has_karaoke_timing": False,
            "segments": [
                {"text": "Hello ", "start": 1.0, "end": 2.0},
                {"text": "world", "start": 2.0, "end": 3.0},
            ],
        }
    ]


def test_parse_ass_lyrics_karaoke_tags():
    content = r"""
[Events]
Format: Start, End, Text
Dialogue: 0:00:05.00,0:00:07.00,{\k50}Hel{\k150}lo
"""

    lines, has_karaoke_timing = parse_ass_lyrics(content)

    assert has_karaoke_timing is True
    assert lines[0]["text"] == "Hello"
    assert lines[0]["has_karaoke_timing"] is True
    assert lines[0]["segments"] == [
        {"text": "Hel ", "start": 5.0, "end": 5.5},
        {"text": "lo", "start": 5.5, "end": 7.0},
    ]


def test_build_lyrics_guide_from_ass(tmp_path):
    subtitle = tmp_path / "song.ass"
    subtitle.write_text(
        """
[Events]
Format: Start, End, Text
Dialogue: 0:00:01.00,0:00:02.00,Line one
""",
        encoding="utf-8",
    )

    guide = build_lyrics_guide_from_ass(subtitle)

    assert guide["status"] == "ready"
    assert guide["source"] == "sidecar_ass"
    assert guide["line_count"] == 1
    assert guide["lines"][0]["text"] == "Line one"


def test_parse_lrc_lyrics():
    lines = parse_lrc_lyrics(
        """
[00:01.00]Line one
[00:03.00][00:05.00]Repeated
""",
        duration_seconds=8,
    )

    assert [line["start"] for line in lines] == [1.0, 3.0, 5.0]
    assert lines[0]["end"] == 3.0
    assert lines[1]["text"] == "Repeated"
    assert lines[2]["end"] == 8.0


def test_build_lyrics_guide_from_lrc():
    guide = build_lyrics_guide_from_lrc(
        "[00:01.00]Line one\n[00:03.00]Line two",
        source="lrclib",
        duration_seconds=5,
        source_metadata={"provider": "lrclib", "id": 123},
    )

    assert guide["status"] == "ready"
    assert guide["source"] == "lrclib"
    assert guide["source_format"] == "lrc"
    assert guide["line_count"] == 2
    assert guide["lines"][0]["has_karaoke_timing"] is False
    assert guide["source_metadata"]["id"] == 123

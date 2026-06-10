"""Tests for canonical lyric paint unit alignment."""

from biaoke.lib.lyrics_alignment import with_vocal_activity_alignment


def test_vocal_activity_alignment_contracts_line_end_before_next_lrc_line():
    lyrics = {
        "status": "ready",
        "source": "lrclib",
        "source_format": "lrc",
        "confidence": 0.82,
        "has_karaoke_timing": False,
        "lines": [
            {"start": 4.88, "end": 11.15, "text": "Don't let me down"},
            {"start": 11.15, "end": 17.34, "text": "Don't let me down"},
        ],
    }
    melody = {
        "contour": [
            {"time": 4.95, "midi": 61.0, "confidence": 0.65},
            {"time": 5.40, "midi": 63.7, "confidence": 0.56},
            {"time": 6.00, "midi": 64.2, "confidence": 0.61},
            {"time": 7.00, "midi": 61.5, "confidence": 0.72},
            {"time": 8.05, "midi": 54.0, "confidence": 0.57},
            {"time": 9.25, "midi": 54.2, "confidence": 0.62},
            {"time": 11.20, "midi": 68.0, "confidence": 0.78},
            {"time": 12.00, "midi": 64.0, "confidence": 0.78},
        ]
    }

    guide = with_vocal_activity_alignment(lyrics, melody)
    first_unit = guide["alignment"]["paint_units"][0]

    assert guide["alignment"]["method"] == "line_timing_vocal_activity"
    assert first_unit["start"] == 4.88
    assert first_unit["end"] == 9.72
    assert first_unit["source_end"] == 11.15
    assert first_unit["precision"] == "line_vocal_activity"


def test_vocal_activity_alignment_keeps_source_when_no_activity_matches():
    lyrics = {
        "status": "ready",
        "confidence": 0.8,
        "has_karaoke_timing": False,
        "lines": [{"start": 20.0, "end": 24.0, "text": "No matching vocal"}],
    }
    melody = {"contour": [{"time": 2.0, "midi": 60.0, "confidence": 0.9}]}

    guide = with_vocal_activity_alignment(lyrics, melody)
    unit = guide["alignment"]["paint_units"][0]

    assert guide["alignment"]["method"] == "line_timing_fallback"
    assert unit["start"] == 20.0
    assert unit["end"] == 24.0


def test_vocal_activity_alignment_does_not_move_lrc_start_later():
    lyrics = {
        "status": "ready",
        "confidence": 0.8,
        "has_karaoke_timing": False,
        "lines": [{"start": 37.53, "end": 55.68, "text": "I'm the man in the box"}],
    }
    melody = {
        "notes": [
            {"start": 39.2, "end": 40.6, "midi": 56, "confidence": 0.9},
            {"start": 40.8, "end": 42.9, "midi": 61, "confidence": 0.88},
        ]
    }

    guide = with_vocal_activity_alignment(lyrics, melody)
    unit = guide["alignment"]["paint_units"][0]

    assert guide["alignment"]["method"] == "line_timing_vocal_activity"
    assert unit["start"] == 37.53
    assert unit["source_start"] == 37.53
    assert unit["precision"] == "line_vocal_activity"

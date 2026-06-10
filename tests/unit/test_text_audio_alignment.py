"""Tests for aligning lyrics to timestamped transcript words."""

from biaoke.lib.text_audio_alignment import build_word_alignment_from_transcript


def test_build_word_alignment_from_transcript_returns_word_paint_units():
    lyrics = {
        "status": "ready",
        "lines": [
            {"start": 4.88, "end": 11.15, "text": "Don't let me down"},
            {"start": 11.15, "end": 17.34, "text": "Don't let me down"},
        ],
    }
    transcript = [
        {"word": "dont", "start": 4.95, "end": 5.35, "probability": 0.91},
        {"word": "let", "start": 5.42, "end": 5.77, "probability": 0.94},
        {"word": "me", "start": 5.82, "end": 6.02, "probability": 0.93},
        {"word": "down", "start": 6.09, "end": 7.25, "probability": 0.9},
        {"word": "don't", "start": 11.2, "end": 11.64, "probability": 0.88},
        {"word": "let", "start": 11.72, "end": 12.04, "probability": 0.86},
        {"word": "me", "start": 12.11, "end": 12.31, "probability": 0.82},
        {"word": "down", "start": 12.4, "end": 13.62, "probability": 0.87},
    ]

    alignment = build_word_alignment_from_transcript(lyrics, transcript)

    assert alignment is not None
    assert alignment["granularity"] == "word"
    assert alignment["method"] == "transcript_word_alignment"
    assert [unit["text"] for unit in alignment["paint_units"]] == [
        "Don't",
        "let",
        "me",
        "down",
        "Don't",
        "let",
        "me",
        "down",
    ]
    assert alignment["paint_units"][0]["start"] == 4.95
    assert alignment["paint_units"][4]["start"] == 11.2


def test_build_word_alignment_rejects_low_coverage():
    lyrics = {
        "status": "ready",
        "lines": [{"start": 0, "end": 4, "text": "hello world again today"}],
    }
    transcript = [{"word": "unrelated", "start": 0.5, "end": 1.0, "probability": 0.9}]

    assert build_word_alignment_from_transcript(lyrics, transcript) is None


def test_build_word_alignment_tokenizes_unspaced_text_as_characters():
    lyrics = {"status": "ready", "lines": [{"start": 1, "end": 3, "text": "愛して"}]}
    transcript = [
        {"word": "愛", "start": 1.0, "end": 1.4},
        {"word": "し", "start": 1.4, "end": 1.7},
        {"word": "て", "start": 1.7, "end": 2.0},
    ]

    alignment = build_word_alignment_from_transcript(lyrics, transcript)

    assert alignment is not None
    assert [unit["text"] for unit in alignment["paint_units"]] == ["愛", "し", "て"]


def test_build_word_alignment_rejects_repeated_word_at_impossible_time():
    lyrics = {
        "status": "ready",
        "lines": [{"start": 23.2, "end": 28.49, "text": "Don't let me down"}],
    }
    transcript = [
        {"word": "don't", "start": 4.66, "end": 5.8, "probability": 0.95},
        {"word": "let", "start": 24.13, "end": 24.41, "probability": 0.95},
        {"word": "me", "start": 24.48, "end": 24.7, "probability": 0.95},
        {"word": "down", "start": 24.76, "end": 25.3, "probability": 0.95},
    ]

    alignment = build_word_alignment_from_transcript(lyrics, transcript)

    assert alignment is not None
    units = alignment["paint_units"]
    assert [unit["text"] for unit in units] == ["Don't", "let", "me", "down"]
    assert units[0]["precision"] == "transcript_interpolated_word"
    assert units[0]["start"] > 22
    assert units[1]["start"] == 24.13
    assert alignment["confidence"]["estimated_words"] == 1


def test_build_word_alignment_keeps_high_coverage_transcript_timing_when_lrc_is_offset():
    lyrics = {
        "status": "ready",
        "lines": [{"start": 4.52, "end": 5.72, "text": "It's a God awful small affair"}],
    }
    transcript = [
        {"word": "it's", "start": 9.58, "end": 10.48, "probability": 0.9},
        {"word": "a", "start": 10.48, "end": 10.7, "probability": 0.9},
        {"word": "god", "start": 10.7, "end": 11.02, "probability": 0.9},
        {"word": "awful", "start": 11.02, "end": 11.42, "probability": 0.9},
        {"word": "small", "start": 11.42, "end": 12.08, "probability": 0.9},
        {"word": "affair", "start": 12.08, "end": 12.94, "probability": 0.9},
    ]

    alignment = build_word_alignment_from_transcript(lyrics, transcript)

    assert alignment is not None
    assert alignment["confidence"]["overall"] == 1
    assert alignment["confidence"]["estimated_words"] == 0
    assert [unit["start"] for unit in alignment["paint_units"]] == [9.58, 10.48, 10.7, 11.02, 11.42, 12.08]


def test_build_word_alignment_normalizes_overlapping_word_timestamps():
    lyrics = {"status": "ready", "lines": [{"start": 0, "end": 3, "text": "one two three"}]}
    transcript = [
        {"word": "one", "start": 0.0, "end": 1.0, "probability": 0.9},
        {"word": "two", "start": 0.94, "end": 1.4, "probability": 0.9},
        {"word": "three", "start": 1.35, "end": 2.0, "probability": 0.9},
    ]

    alignment = build_word_alignment_from_transcript(lyrics, transcript)

    assert alignment is not None
    units = alignment["paint_units"]
    assert units[1]["start"] == units[0]["end"]
    assert units[2]["start"] == units[1]["end"]


def test_build_word_alignment_bounds_interpolated_words_between_adjacent_lines():
    lyrics = {
        "status": "ready",
        "lines": [
            {"start": 0, "end": 10, "text": "one missing"},
            {"start": 10, "end": 12, "text": "two three four"},
        ],
    }
    transcript = [
        {"word": "one", "start": 0.0, "end": 1.0, "probability": 0.9},
        {"word": "two", "start": 4.0, "end": 5.0, "probability": 0.9},
        {"word": "three", "start": 5.0, "end": 6.0, "probability": 0.9},
        {"word": "four", "start": 6.0, "end": 7.0, "probability": 0.9},
    ]

    alignment = build_word_alignment_from_transcript(lyrics, transcript)

    assert alignment is not None
    units = alignment["paint_units"]
    assert [unit["text"] for unit in units] == ["one", "missing", "two", "three", "four"]
    assert units[1]["precision"] == "transcript_interpolated_word"
    assert units[1]["end"] == units[2]["start"]
    assert units[2]["start"] == 4.0

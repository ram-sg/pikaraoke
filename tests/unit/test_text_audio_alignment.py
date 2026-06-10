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

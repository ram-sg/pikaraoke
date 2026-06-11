import json
from unittest.mock import MagicMock, patch

import pytest

from biaoke.lib.coach_preparation import (
    CoachPreparationManager,
    _adjust_first_word_onsets_with_melody,
    _attach_vocal_units,
    _filter_melody_to_vocal_windows,
    _lyrics_lines_for_forced_alignment,
    _review_coach_guide_with_ai,
    _review_coach_guide_with_deepseek,
    _transcribe_and_align_coach_vocals,
    _write_coach_guide,
)
from biaoke.lib.events import EventSystem
from biaoke.lib.karaoke_database import KaraokeDatabase


def test_prepare_youtube_creates_track_job_and_queues_download(tmp_path):
    db = KaraokeDatabase(str(tmp_path / "test.db"))
    download_manager = MagicMock()
    manager = CoachPreparationManager(
        db=db,
        events=EventSystem(),
        download_manager=download_manager,
        download_path=str(tmp_path),
    )

    result = manager.prepare_youtube(
        url="https://music.youtube.com/watch?v=dQw4w9WgXcQ",
        title="Artist - Song",
        user="Ramon",
    )

    assert result["track"]["source_id"] == "dQw4w9WgXcQ"
    assert result["job"]["stage"] == "acquire"
    download_manager.queue_download.assert_called_once()
    kwargs = download_manager.queue_download.call_args.kwargs
    assert kwargs["enqueue"] is False
    assert kwargs["context"]["coach_track_id"] == result["track"]["id"]
    assert kwargs["download_subtitles"] is False
    db.close()


def test_download_lifecycle_updates_track_job_and_assets(tmp_path):
    db = KaraokeDatabase(str(tmp_path / "test.db"))
    manager = CoachPreparationManager(
        db=db,
        events=EventSystem(),
        download_manager=MagicMock(),
        download_path=str(tmp_path),
    )
    result = manager.prepare_youtube(url="https://youtube.com/watch?v=abc12345678", title="Song")
    context = {
        "coach_track_id": result["track"]["id"],
        "coach_job_id": result["job"]["id"],
    }

    manager.handle_download_started(context)
    running_job = db.get_coach_job(result["job"]["id"])
    assert running_job["status"] == "running"

    song_path = str(tmp_path / "Artist - Song---abc12345678.mp4")
    manager.handle_download_completed(song_path, context)

    track = db.get_coach_track(result["track"]["id"])
    assets = db.get_coach_assets(result["track"]["id"])
    jobs = db.list_coach_jobs(result["track"]["id"])

    assert track["status"] == "processing"
    assert track["file_path"] == song_path
    assert assets["original_audio_path"] == song_path
    assert any(job["stage"] == "analyze_pending" for job in jobs)
    db.close()


def test_start_recovers_interrupted_analysis_jobs(tmp_path):
    db = KaraokeDatabase(str(tmp_path / "test.db"))
    manager = CoachPreparationManager(
        db=db,
        events=EventSystem(),
        download_manager=MagicMock(),
        download_path=str(tmp_path),
        analyzer_poll_seconds=60,
    )
    track = db.upsert_coach_track(
        source_type="local",
        source_url=str(tmp_path / "Song.mp4"),
        source_id=str(tmp_path / "Song.mp4"),
        display_title="Song",
        status="processing",
    )
    job = db.create_coach_job(track["id"], stage="build_guide")
    db.update_coach_job(job["id"], status="running", progress=10)

    with patch.object(manager, "run_pending_analysis_once", return_value=False):
        manager.start()
        manager.stop()

    recovered = db.get_coach_job(job["id"])
    assert recovered["stage"] == "analyze_pending"
    assert recovered["status"] == "queued"
    assert recovered["progress"] == 0
    db.close()


def test_pending_analysis_writes_coach_guide_and_marks_ready(tmp_path):
    media_path = tmp_path / "Artist - Song---abc12345678.mp4"
    media_path.write_bytes(b"fake media")
    db = KaraokeDatabase(str(tmp_path / "test.db"))
    manager = CoachPreparationManager(
        db=db,
        events=EventSystem(),
        download_manager=MagicMock(),
        download_path=str(tmp_path),
    )
    result = manager.register_local_file(str(media_path))
    lyrics_guide = {
        "lyrics": {
            "status": "ready",
            "has_karaoke_timing": True,
            "lines": [{"start": 0.0, "end": 2.0, "text": "hello"}],
        }
    }
    melody_guide = {
        "status": "ready",
        "notes": [
            {
                "start": 0.1,
                "end": 0.8,
                "midi": 60,
                "note": "C4",
                "frequency": 261.63,
                "confidence": 0.9,
            }
        ],
    }
    stems = {
        "status": "ready",
        "engine": "demucs",
        "vocals_path": str(tmp_path / "vocals.wav"),
        "instrumental_path": str(tmp_path / "instrumental.wav"),
    }

    with (
        patch("biaoke.lib.coach_preparation.write_song_guide", return_value=lyrics_guide),
        patch("biaoke.lib.coach_preparation._separate_coach_stems", return_value=stems),
        patch(
            "biaoke.lib.coach_preparation._extract_coach_melody",
            return_value=melody_guide,
        ) as melody_mock,
        patch(
            "biaoke.lib.coach_preparation._transcribe_coach_vocals",
            return_value={
                "status": "ready",
                "engine": "faster-whisper",
                "words": [{"word": "hello", "start": 0.12, "end": 0.65, "probability": 0.94}],
            },
        ) as transcribe_mock,
    ):
        assert manager.run_pending_analysis_once() is True

    track = db.get_coach_track(result["track"]["id"])
    assets = db.get_coach_assets(result["track"]["id"])
    job = db.list_coach_jobs(result["track"]["id"])[0]

    assert track["status"] == "ready"
    assert track["quality_status"] == "ready"
    assert job["status"] == "complete"
    assert assets["guide_path"].endswith(".biaoke-coach.json")
    assert assets["vocal_reference_path"] == str(tmp_path / "vocals.wav")
    assert assets["instrumental_audio_path"] == str(tmp_path / "instrumental.wav")
    melody_mock.assert_called_once_with(tmp_path / "vocals.wav")
    transcribe_mock.assert_called_once_with(tmp_path / "vocals.wav")

    with open(assets["guide_path"], encoding="utf-8") as handle:
        coach_guide = json.load(handle)

    assert coach_guide["schema"] == "biaoke.coach_guide"
    assert coach_guide["stems"]["engine"] == "demucs"
    assert coach_guide["transcript"]["engine"] == "faster-whisper"
    assert coach_guide["lyrics"]["alignment"]["granularity"] == "word"
    assert coach_guide["lyrics"]["alignment"]["paint_units"][0]["start"] == 0.12
    assert coach_guide["melody"]["vocal_filter"]["applied"] is True
    assert coach_guide["tasks"][0]["target_midi"] == 60
    assert coach_guide["tasks"][0]["text"] == "hello"
    db.close()


def test_write_coach_guide_prefers_forced_alignment_over_transcript(tmp_path):
    media_path = tmp_path / "Artist - Aligned---abc12345678.mp4"
    media_path.write_bytes(b"fake media")
    lyrics_guide = {
        "lyrics": {
            "status": "ready",
            "confidence": 0.8,
            "has_karaoke_timing": False,
            "lines": [{"start": 10.0, "end": 20.0, "text": "hello world"}],
        }
    }
    melody_guide = {
        "status": "ready",
        "notes": [{"start": 12.0, "end": 13.0, "midi": 60, "confidence": 0.9}],
        "contour": [{"time": 12.2, "midi": 60, "confidence": 0.9}],
    }
    transcript = {
        "status": "ready",
        "engine": "faster-whisper",
        "words": [{"word": "hello", "start": 15.0, "end": 15.4, "probability": 0.9}],
    }
    transcript_alignment = {
        "status": "ready",
        "granularity": "word",
        "paint_units": [{"start": 15.0, "end": 15.4, "text": "hello", "line_index": 0, "unit_index": 0}],
    }
    forced_alignment = {
        "status": "ready",
        "engine": "torchaudio",
        "model": "mms_fa",
        "method": "mms_fa_forced_alignment",
        "language": "en",
        "granularity": "word",
        "paint_units": [
            {
                "start": 12.1,
                "end": 12.45,
                "text": "hello",
                "line_index": 0,
                "unit_index": 0,
                "confidence": 0.74,
            },
            {
                "start": 12.48,
                "end": 12.9,
                "text": "world",
                "line_index": 0,
                "unit_index": 1,
                "confidence": 0.72,
            },
        ],
        "confidence": {"overall": 0.73, "coverage": 1.0},
    }

    guide_path = _write_coach_guide(
        media_path,
        lyrics_guide,
        melody_guide,
        transcript=transcript,
        transcript_alignment=transcript_alignment,
        forced_alignment=forced_alignment,
    )

    with open(guide_path, encoding="utf-8") as handle:
        guide = json.load(handle)

    alignment = guide["lyrics"]["alignment"]
    assert alignment["method"] == "mms_fa_forced_alignment"
    assert alignment["paint_units"][0]["start"] == 12.1
    assert alignment["paint_units"][1]["text"] == "world"
    assert "line_timing_only" not in guide["quality"]["messages"]


def test_attach_vocal_units_marks_sustained_vowels_with_pitch():
    lyrics = {
        "status": "ready",
        "lines": [{"start": 10.0, "end": 13.0, "text": "Feed my eyes"}],
        "alignment": {
            "status": "ready",
            "granularity": "word",
            "paint_units": [
                {
                    "start": 10.0,
                    "end": 12.2,
                    "text": "Feed",
                    "line_index": 0,
                    "unit_index": 0,
                    "unit_type": "word",
                }
            ],
        },
    }
    melody = {
        "notes": [
            {"start": 10.15, "end": 12.4, "midi": 66, "confidence": 0.91},
        ]
    }

    enriched = _attach_vocal_units(lyrics, melody)

    feed = enriched["vocal_units"][0]
    sub_units = feed["sub_units"]
    vowel = next(unit for unit in sub_units if unit["text"].lower() == "ee")
    consonant_durations = [
        unit["duration"]
        for unit in sub_units
        if unit["type"] in {"fricative_effect", "consonant_release", "consonant_attack"}
    ]
    assert enriched["vocal_units_schema"] == "biaoke.vocal_units"
    assert vowel["type"] == "vowel_sustain"
    assert vowel["score"] == "pitch_timing"
    assert vowel["char_start"] == 1
    assert vowel["char_end"] == 3
    assert vowel["duration"] > max(consonant_durations)
    assert vowel["end"] == pytest.approx(12.4)
    assert feed["end"] > 12.2
    assert vowel["note_count"] == 1


def test_attach_vocal_units_supports_sonorant_and_fricative_exceptions():
    lyrics = {
        "status": "ready",
        "lines": [{"start": 0.0, "end": 2.2, "text": "mmm sh"}],
        "alignment": {
            "status": "ready",
            "granularity": "word",
            "paint_units": [
                {
                    "start": 0.0,
                    "end": 1.1,
                    "text": "mmm",
                    "line_index": 0,
                    "unit_index": 0,
                    "unit_type": "word",
                },
                {
                    "start": 1.2,
                    "end": 2.0,
                    "text": "sh",
                    "line_index": 0,
                    "unit_index": 1,
                    "unit_type": "word",
                },
            ],
        },
    }
    melody = {"notes": [{"start": 0.05, "end": 1.0, "midi": 58, "confidence": 0.9}]}

    enriched = _attach_vocal_units(lyrics, melody)

    sonorant = enriched["vocal_units"][0]["sub_units"][0]
    fricative = enriched["vocal_units"][1]["sub_units"][0]
    assert sonorant["type"] == "sonorant_sustain"
    assert sonorant["score"] == "light_pitch_timing"
    assert sonorant["sustain"] is True
    assert fricative["type"] == "fricative_effect"
    assert fricative["score"] == "timing_only"


def test_write_coach_guide_adds_transcript_vocalization_lines(tmp_path):
    media_path = tmp_path / "Artist - Chant---abc12345678.mp4"
    media_path.write_bytes(b"fake media")
    lyrics_guide = {
        "lyrics": {
            "status": "ready",
            "confidence": 0.8,
            "has_karaoke_timing": False,
            "lines": [{"start": 0.0, "end": 2.0, "text": "hello world"}],
        }
    }
    melody_guide = {
        "status": "ready",
        "duration_seconds": 12,
        "notes": [
            {"start": 0.2, "end": 1.0, "midi": 60, "confidence": 0.9},
            {"start": 5.0, "end": 6.8, "midi": 64, "confidence": 0.88},
        ],
        "contour": [
            {"time": 0.5, "midi": 60, "confidence": 0.9},
            {"time": 5.2, "midi": 64, "confidence": 0.88},
            {"time": 6.2, "midi": 64, "confidence": 0.86},
        ],
    }
    transcript = {
        "status": "ready",
        "engine": "faster-whisper",
        "words": [
            {"word": "hello", "start": 0.2, "end": 0.6, "probability": 0.93},
            {"word": "la", "start": 5.05, "end": 5.35, "probability": 0.84},
            {"word": "la", "start": 5.7, "end": 6.05, "probability": 0.86},
            {"word": "oh", "start": 6.25, "end": 6.65, "probability": 0.82},
        ],
    }

    guide_path = _write_coach_guide(media_path, lyrics_guide, melody_guide, transcript=transcript)

    with open(guide_path, encoding="utf-8") as handle:
        guide = json.load(handle)

    generated_lines = [line for line in guide["lyrics"]["lines"] if line.get("generated")]
    assert len(generated_lines) == 1
    assert generated_lines[0]["text"] == "La, la, oh"
    assert generated_lines[0]["timing_source"] == "transcript_vocalization"
    generated_units = [
        unit
        for unit in guide["lyrics"]["alignment"]["paint_units"]
        if unit.get("precision") == "transcript_vocalization"
    ]
    assert [unit["text"] for unit in generated_units] == ["la", "la", "oh"]
    assert guide["lyrics"]["auto_vocalizations"]["line_count"] == 1


def test_forced_alignment_lines_prefer_transcript_word_windows():
    lyrics = {
        "status": "ready",
        "has_karaoke_timing": False,
        "lines": [{"start": 4.0, "end": 18.0, "text": "It's a God awful small affair"}],
    }
    melody = {
        "contour": [{"time": 9.8, "midi": 60, "confidence": 0.9}],
        "notes": [{"start": 9.7, "end": 12.8, "midi": 60, "confidence": 0.9}],
    }
    transcript_alignment = {
        "paint_units": [
            {
                "start": 9.58,
                "end": 10.48,
                "text": "It's",
                "line_index": 0,
                "unit_index": 0,
                "unit_type": "word",
                "precision": "transcript_word",
            },
            {
                "start": 10.48,
                "end": 10.7,
                "text": "a",
                "line_index": 0,
                "unit_index": 1,
                "unit_type": "word",
                "precision": "transcript_word",
            },
            {
                "start": 10.7,
                "end": 11.02,
                "text": "God",
                "line_index": 0,
                "unit_index": 2,
                "unit_type": "word",
                "precision": "transcript_word",
            },
        ]
    }

    lines = _lyrics_lines_for_forced_alignment(lyrics, melody, transcript_alignment)

    assert lines == [
        {
            "line_index": 0,
            "start": 9.58,
            "end": 11.02,
            "text": "It's a God awful small affair",
            "timing_source": "transcript_words",
        }
    ]


def test_pending_analysis_filters_pitch_notes_outside_vocal_windows(tmp_path):
    media_path = tmp_path / "Artist - Song---abc12345678.mp4"
    media_path.write_bytes(b"fake media")
    db = KaraokeDatabase(str(tmp_path / "test.db"))
    manager = CoachPreparationManager(
        db=db,
        events=EventSystem(),
        download_manager=MagicMock(),
        download_path=str(tmp_path),
    )
    result = manager.register_local_file(str(media_path))
    lyrics_guide = {
        "lyrics": {
            "status": "ready",
            "has_karaoke_timing": True,
            "lines": [
                {"start": 0.0, "end": 2.0, "text": "hello"},
                {"start": 8.0, "end": 10.0, "text": "again"},
            ],
        }
    }
    melody_guide = {
        "status": "ready",
        "duration_seconds": 12,
        "notes": [
            {"start": 0.2, "end": 1.0, "midi": 60, "note": "C4", "frequency": 261.63, "confidence": 0.9},
            {"start": 4.0, "end": 5.0, "midi": 65, "note": "F4", "frequency": 349.23, "confidence": 0.92},
            {"start": 8.2, "end": 9.0, "midi": 62, "note": "D4", "frequency": 293.66, "confidence": 0.88},
        ],
        "contour": [
            {"time": 0.3, "midi": 60, "confidence": 0.9},
            {"time": 4.4, "midi": 65, "confidence": 0.92},
            {"time": 8.4, "midi": 62, "confidence": 0.88},
        ],
    }
    stems = {
        "status": "ready",
        "engine": "demucs",
        "vocals_path": str(tmp_path / "vocals.wav"),
        "instrumental_path": str(tmp_path / "instrumental.wav"),
    }

    with (
        patch("biaoke.lib.coach_preparation.write_song_guide", return_value=lyrics_guide),
        patch("biaoke.lib.coach_preparation._separate_coach_stems", return_value=stems),
        patch("biaoke.lib.coach_preparation._extract_coach_melody", return_value=melody_guide),
        patch(
            "biaoke.lib.coach_preparation._transcribe_coach_vocals",
            return_value={
                "status": "ready",
                "engine": "faster-whisper",
                "words": [
                    {"word": "hello", "start": 0.15, "end": 0.7, "probability": 0.94},
                    {"word": "again", "start": 8.15, "end": 8.75, "probability": 0.93},
                ],
            },
        ),
    ):
        assert manager.run_pending_analysis_once() is True

    assets = db.get_coach_assets(result["track"]["id"])
    with open(assets["guide_path"], encoding="utf-8") as handle:
        coach_guide = json.load(handle)

    assert [note["midi"] for note in coach_guide["melody"]["notes"]] == [60, 62]
    assert [point["midi"] for point in coach_guide["melody"]["contour"]] == [60, 62]
    assert [note["midi"] for note in coach_guide["reference_melody"]["notes"]] == [60, 65, 62]
    assert [point["midi"] for point in coach_guide["reference_melody"]["contour"]] == [60, 65, 62]
    assert [task["target_midi"] for task in coach_guide["tasks"]] == [60, 62]
    assert coach_guide["melody"]["vocal_filter"]["removed_notes"] == 1
    assert coach_guide["melody"]["vocal_filter"]["removed_contour_points"] == 1
    db.close()


def test_pending_analysis_preserves_sustained_note_tail_after_last_word(tmp_path):
    media_path = tmp_path / "Artist - Ballad---abc12345678.mp4"
    media_path.write_bytes(b"fake media")
    db = KaraokeDatabase(str(tmp_path / "test.db"))
    manager = CoachPreparationManager(
        db=db,
        events=EventSystem(),
        download_manager=MagicMock(),
        download_path=str(tmp_path),
    )
    result = manager.register_local_file(str(media_path))
    lyrics_guide = {
        "lyrics": {
            "status": "ready",
            "has_karaoke_timing": True,
            "lines": [{"start": 10.0, "end": 20.0, "text": "life on Mars"}],
        }
    }
    melody_guide = {
        "status": "ready",
        "duration_seconds": 24,
        "notes": [
            {"start": 14.9, "end": 18.75, "midi": 69, "note": "A4", "frequency": 440.0, "confidence": 0.88},
            {"start": 20.0, "end": 20.35, "midi": 57, "note": "A3", "frequency": 220.0, "confidence": 0.91},
        ],
        "contour": [
            {"time": 15.0, "midi": 69, "confidence": 0.9},
            {"time": 17.5, "midi": 69, "confidence": 0.86},
            {"time": 20.1, "midi": 57, "confidence": 0.91},
        ],
    }
    stems = {
        "status": "ready",
        "engine": "demucs",
        "vocals_path": str(tmp_path / "vocals.wav"),
        "instrumental_path": str(tmp_path / "instrumental.wav"),
    }

    with (
        patch("biaoke.lib.coach_preparation.write_song_guide", return_value=lyrics_guide),
        patch("biaoke.lib.coach_preparation._separate_coach_stems", return_value=stems),
        patch("biaoke.lib.coach_preparation._extract_coach_melody", return_value=melody_guide),
        patch(
            "biaoke.lib.coach_preparation._transcribe_coach_vocals",
            return_value={
                "status": "ready",
                "engine": "faster-whisper",
                "words": [{"word": "Mars", "start": 14.79, "end": 15.19, "probability": 0.91}],
            },
        ),
    ):
        assert manager.run_pending_analysis_once() is True

    assets = db.get_coach_assets(result["track"]["id"])
    with open(assets["guide_path"], encoding="utf-8") as handle:
        coach_guide = json.load(handle)

    assert coach_guide["melody"]["notes"] == [melody_guide["notes"][0]]
    assert [point["time"] for point in coach_guide["melody"]["contour"]] == [15.0, 17.5]
    assert coach_guide["melody"]["vocal_filter"]["removed_notes"] == 1
    db.close()


def test_pending_analysis_uses_line_lyrics_when_transcript_misses_repeated_chants(tmp_path):
    media_path = tmp_path / "Artist - Repeated---abc12345678.mp4"
    media_path.write_bytes(b"fake media")
    db = KaraokeDatabase(str(tmp_path / "test.db"))
    manager = CoachPreparationManager(
        db=db,
        events=EventSystem(),
        download_manager=MagicMock(),
        download_path=str(tmp_path),
    )
    result = manager.register_local_file(str(media_path))
    lyrics_guide = {
        "lyrics": {
            "status": "ready",
            "has_karaoke_timing": False,
            "lines": [
                {"start": 40.0, "end": 44.0, "text": "Fa-fa-fa-fa, fa-fa-fa-fa-fa-fa, better"},
                {"start": 44.0, "end": 52.0, "text": "Run, run, run, run, run away"},
                {"start": 90.0, "end": 94.0, "text": "Fa-fa-fa-fa, fa-fa-fa-fa-fa-fa, better"},
                {"start": 94.0, "end": 102.0, "text": "Run, run, run, run, run away"},
            ],
        }
    }
    melody_guide = {
        "status": "ready",
        "duration_seconds": 110,
        "notes": [
            {"start": 42.0, "end": 43.0, "midi": 59, "note": "B3", "frequency": 246.94, "confidence": 0.9},
            {"start": 46.0, "end": 47.0, "midi": 60, "note": "C4", "frequency": 261.63, "confidence": 0.88},
            {"start": 70.0, "end": 71.0, "midi": 65, "note": "F4", "frequency": 349.23, "confidence": 0.92},
            {"start": 96.0, "end": 97.0, "midi": 60, "note": "C4", "frequency": 261.63, "confidence": 0.87},
        ],
        "contour": [
            {"time": 42.5, "midi": 59, "confidence": 0.9},
            {"time": 46.5, "midi": 60, "confidence": 0.88},
            {"time": 70.5, "midi": 65, "confidence": 0.92},
            {"time": 96.5, "midi": 60, "confidence": 0.87},
        ],
    }
    stems = {
        "status": "ready",
        "engine": "demucs",
        "vocals_path": str(tmp_path / "vocals.wav"),
        "instrumental_path": str(tmp_path / "instrumental.wav"),
    }

    with (
        patch("biaoke.lib.coach_preparation.write_song_guide", return_value=lyrics_guide),
        patch("biaoke.lib.coach_preparation._separate_coach_stems", return_value=stems),
        patch("biaoke.lib.coach_preparation._extract_coach_melody", return_value=melody_guide),
        patch(
            "biaoke.lib.coach_preparation._transcribe_coach_vocals",
            return_value={
                "status": "ready",
                "engine": "faster-whisper",
                "words": [{"word": "run", "start": 96.2, "end": 96.8, "probability": 0.92}],
            },
        ),
    ):
        assert manager.run_pending_analysis_once() is True

    assets = db.get_coach_assets(result["track"]["id"])
    with open(assets["guide_path"], encoding="utf-8") as handle:
        coach_guide = json.load(handle)

    assert [note["start"] for note in coach_guide["melody"]["notes"]] == [42.0, 46.0, 96.0]
    assert [point["time"] for point in coach_guide["melody"]["contour"]] == [42.5, 46.5, 96.5]
    assert coach_guide["melody"]["vocal_filter"]["source"] == "transcript_words+line_lyrics"
    assert coach_guide["melody"]["vocal_filter"]["removed_notes"] == 1
    db.close()


def test_filter_preserves_first_vocal_stem_preface_cluster():
    lyrics = {
        "status": "ready",
        "has_karaoke_timing": False,
        "lines": [
            {"start": 37.53, "end": 55.68, "text": "I'm the man in the box buried in my shit"},
            {"start": 55.68, "end": 73.33, "text": "Won't you come and save me"},
        ],
    }
    melody = {
        "status": "ready",
        "notes": [
            {"start": 10.0, "end": 11.0, "midi": 64, "confidence": 0.92},
            {"start": 30.15, "end": 31.8, "midi": 58, "confidence": 0.9},
            {"start": 32.0, "end": 35.2, "midi": 60, "confidence": 0.89},
            {"start": 39.2, "end": 40.6, "midi": 56, "confidence": 0.9},
        ],
        "contour": [
            {"time": 10.2, "midi": 64, "confidence": 0.92},
            {"time": 30.4, "midi": 58, "confidence": 0.9},
            {"time": 34.8, "midi": 60, "confidence": 0.89},
            {"time": 39.8, "midi": 56, "confidence": 0.9},
        ],
    }

    filtered = _filter_melody_to_vocal_windows(
        melody,
        lyrics,
        None,
        preserve_vocal_stem_preface=True,
    )

    assert [note["start"] for note in filtered["notes"]] == [30.15, 32.0, 39.2]
    assert [point["time"] for point in filtered["contour"]] == [30.4, 34.8, 39.8]
    assert filtered["vocal_filter"]["source"] == "line_lyrics"
    assert filtered["vocal_filter"]["preface_first_window_extended"] is True
    assert filtered["vocal_filter"]["removed_notes"] == 1


def test_transcription_retries_without_vad_when_prompt_improves_alignment(tmp_path):
    lyrics = {
        "status": "ready",
        "lines": [
            {"start": 37.53, "end": 55.68, "text": "I'm the man in the box buried in my shit"},
            {"start": 55.68, "end": 73.33, "text": "Won't you come and save me"},
        ],
    }
    weak_transcript = {
        "status": "ready",
        "engine": "faster-whisper",
        "words": [
            {"word": "unrelated", "start": 61.0, "end": 61.4, "probability": 0.2},
            {"word": "la", "start": 86.0, "end": 86.35, "probability": 0.84},
        ],
    }
    prompted_transcript = {
        "status": "ready",
        "engine": "faster-whisper",
        "mode": "lyrics_prompt_no_vad",
        "words": [
            {"word": "I'm", "start": 30.5, "end": 31.9, "probability": 0.8},
            {"word": "the", "start": 31.9, "end": 32.1, "probability": 0.8},
            {"word": "man", "start": 32.1, "end": 33.7, "probability": 0.95},
            {"word": "in", "start": 33.7, "end": 34.1, "probability": 0.95},
            {"word": "the", "start": 34.1, "end": 34.5, "probability": 0.95},
            {"word": "box", "start": 34.5, "end": 37.5, "probability": 0.9},
            {"word": "buried", "start": 40.4, "end": 40.9, "probability": 0.7},
            {"word": "in", "start": 40.9, "end": 43.2, "probability": 0.9},
            {"word": "my", "start": 43.2, "end": 44.0, "probability": 0.9},
            {"word": "shit", "start": 44.0, "end": 44.4, "probability": 0.9},
            {"word": "Won't", "start": 50.0, "end": 51.4, "probability": 0.7},
            {"word": "you", "start": 51.4, "end": 52.8, "probability": 0.9},
            {"word": "come", "start": 52.8, "end": 55.0, "probability": 0.8},
            {"word": "and", "start": 55.0, "end": 56.7, "probability": 0.9},
            {"word": "save", "start": 56.7, "end": 57.4, "probability": 0.9},
            {"word": "me", "start": 57.4, "end": 58.5, "probability": 0.95},
        ],
    }

    with patch(
        "biaoke.lib.coach_preparation._transcribe_coach_vocals",
        side_effect=[weak_transcript, prompted_transcript],
    ) as transcribe_mock:
        transcript, alignment = _transcribe_and_align_coach_vocals(tmp_path / "vocals.wav", lyrics)

    assert transcript["mode"] == "lyrics_prompt_no_vad"
    assert transcript["selection_reason"] == "lyrics_prompt_no_vad_improved_alignment"
    assert transcript["merged_vocalization_words"] == 1
    assert any(word.get("source") == "fallback_vocalization" for word in transcript["words"])
    assert transcript["fallback_of"]["word_count"] == 2
    assert alignment["method"] == "faster_whisper_lyrics_prompt_no_vad_alignment"
    assert alignment["confidence"]["overall"] > 0.9
    assert alignment["paint_units"][0]["start"] == 30.5
    assert transcribe_mock.call_args_list[1].kwargs["vad_filter"] is False
    assert "man in the box" in transcribe_mock.call_args_list[1].kwargs["initial_prompt"]


def test_adjust_first_word_onset_uses_nearby_vocal_note_without_crossing_previous_line():
    alignment = {
        "status": "ready",
        "granularity": "word",
        "paint_units": [
            {"start": 72.0, "end": 73.0, "text": "eyes", "line_index": 0, "unit_index": 0, "unit_type": "word"},
            {"start": 73.1, "end": 75.2, "text": "shut", "line_index": 0, "unit_index": 1, "unit_type": "word"},
            {
                "start": 77.72,
                "end": 79.0,
                "text": "Jesus",
                "line_index": 1,
                "unit_index": 0,
                "unit_type": "word",
                "precision": "mms_fa_forced_alignment",
                "confidence": 0.33,
            },
            {
                "start": 79.0,
                "end": 80.4,
                "text": "Christ",
                "line_index": 1,
                "unit_index": 1,
                "unit_type": "word",
            },
        ],
    }
    melody = {
        "notes": [
            {"start": 74.2, "end": 75.3, "midi": 60, "confidence": 0.92},
            {"start": 76.92, "end": 77.86, "midi": 63, "confidence": 0.88},
        ]
    }

    adjusted = _adjust_first_word_onsets_with_melody(alignment, melody)
    first_next_line = adjusted["paint_units"][2]

    assert first_next_line["start"] == 76.92
    assert first_next_line["source_start"] == 77.72
    assert first_next_line["precision"].endswith("+vocal_onset")
    assert adjusted["confidence"]["vocal_onset_adjusted_first_words"] == 1


def test_adjust_first_word_onset_allows_small_melismatic_overlap():
    alignment = {
        "status": "ready",
        "granularity": "word",
        "paint_units": [
            {"start": 74.58, "end": 75.18, "text": "shut", "line_index": 0, "unit_index": 7, "unit_type": "word"},
            {
                "start": 77.713,
                "end": 78.555,
                "text": "Jesus",
                "line_index": 1,
                "unit_index": 0,
                "unit_type": "word",
                "precision": "mms_fa_forced_alignment",
                "confidence": 0.33,
            },
            {"start": 78.695, "end": 80.941, "text": "Christ", "line_index": 1, "unit_index": 1, "unit_type": "word"},
        ],
    }
    melody = {
        "notes": [
            {"start": 74.75, "end": 76.35, "midi": 70, "confidence": 0.83},
            {"start": 76.35, "end": 77.2, "midi": 69, "confidence": 0.81},
            {"start": 77.2, "end": 77.95, "midi": 68, "confidence": 0.79},
        ]
    }

    adjusted = _adjust_first_word_onsets_with_melody(alignment, melody)
    jesus = adjusted["paint_units"][1]

    assert jesus["start"] == 74.75
    assert jesus["source_start"] == 77.713
    assert jesus["precision"].endswith("+vocal_onset")


def test_adjust_internal_singable_word_onset_and_truncates_previous_word():
    alignment = {
        "status": "ready",
        "granularity": "word",
        "paint_units": [
            {"start": 52.8, "end": 55.06, "text": "come", "line_index": 0, "unit_index": 2, "unit_type": "word"},
            {"start": 55.06, "end": 56.74, "text": "and", "line_index": 0, "unit_index": 3, "unit_type": "word"},
            {
                "start": 56.74,
                "end": 57.38,
                "text": "save",
                "line_index": 0,
                "unit_index": 4,
                "unit_type": "word",
                "precision": "transcript_word",
                "confidence": 0.96,
            },
        ],
    }
    melody = {
        "notes": [
            {"start": 55.6, "end": 55.75, "midi": 53, "confidence": 0.75},
            {"start": 56.4, "end": 56.55, "midi": 53, "confidence": 0.76},
        ]
    }

    adjusted = _adjust_first_word_onsets_with_melody(alignment, melody)
    previous = adjusted["paint_units"][1]
    save = adjusted["paint_units"][2]

    assert previous["end"] == 55.6
    assert previous["source_end"] == 56.74
    assert save["start"] == 55.6
    assert save["source_start"] == 56.74
    assert save["precision"] == "transcript_word+vocal_onset"
    assert adjusted["confidence"]["vocal_onset_adjusted_internal_words"] == 1


def test_adjust_internal_short_vocalization_onset():
    alignment = {
        "status": "ready",
        "granularity": "word",
        "paint_units": [
            {"start": 10.0, "end": 10.4, "text": "La", "line_index": 0, "unit_index": 0, "unit_type": "word"},
            {"start": 10.9, "end": 11.2, "text": "la", "line_index": 0, "unit_index": 1, "unit_type": "word"},
            {"start": 11.8, "end": 12.2, "text": "oh", "line_index": 0, "unit_index": 2, "unit_type": "word"},
        ],
    }
    melody = {
        "notes": [
            {"start": 10.72, "end": 10.95, "midi": 60, "confidence": 0.82},
            {"start": 11.35, "end": 11.85, "midi": 62, "confidence": 0.84},
        ]
    }

    adjusted = _adjust_first_word_onsets_with_melody(alignment, melody)

    assert adjusted["paint_units"][1]["start"] == 10.72
    assert adjusted["paint_units"][2]["start"] == 11.35
    assert adjusted["confidence"]["vocal_onset_adjusted_internal_words"] == 2


def test_reanalyze_track_queues_fresh_analysis(tmp_path):
    media_path = tmp_path / "Artist - Song---abc12345678.mp4"
    media_path.write_bytes(b"fake media")
    db = KaraokeDatabase(str(tmp_path / "test.db"))
    manager = CoachPreparationManager(
        db=db,
        events=EventSystem(),
        download_manager=MagicMock(),
        download_path=str(tmp_path),
    )
    result = manager.register_local_file(str(media_path))

    reanalysis = manager.reanalyze_track(result["track"]["id"])

    assert reanalysis is not None
    assert reanalysis["track"]["status"] == "processing"
    assert reanalysis["job"]["stage"] == "analyze_pending"
    assert reanalysis["job"]["status"] == "queued"
    db.close()


def test_delete_track_removes_generated_files_and_metadata(tmp_path):
    media_path = tmp_path / "Artist - Song---abc12345678.mp4"
    guide_path = tmp_path / "Artist - Song---abc12345678.biaoke-coach.json"
    lyrics_path = tmp_path / "Artist - Song---abc12345678.biaoke-guide.json"
    stems_dir = tmp_path / ".biaoke-stems"
    stems_dir.mkdir()
    vocals_path = stems_dir / "Artist - Song---abc12345678.vocals.wav"
    instrumental_path = stems_dir / "Artist - Song---abc12345678.instrumental.wav"
    for path in (media_path, guide_path, lyrics_path, vocals_path, instrumental_path):
        path.write_bytes(b"fake")

    db = KaraokeDatabase(str(tmp_path / "test.db"))
    manager = CoachPreparationManager(
        db=db,
        events=EventSystem(),
        download_manager=MagicMock(),
        download_path=str(tmp_path),
    )
    result = manager.register_local_file(str(media_path))
    track_id = result["track"]["id"]
    db.set_coach_assets(
        track_id,
        original_audio_path=str(media_path),
        instrumental_audio_path=str(instrumental_path),
        vocal_reference_path=str(vocals_path),
        guide_path=str(guide_path),
        lyrics_path=str(lyrics_path),
    )

    deleted = manager.delete_track(track_id)

    assert deleted is not None
    assert db.get_coach_track(track_id) is None
    assert db.get_coach_assets(track_id) is None
    for path in (media_path, guide_path, lyrics_path, vocals_path, instrumental_path):
        assert not path.exists()
    db.close()


def test_pending_analysis_marks_needs_review_when_lyrics_missing(tmp_path):
    media_path = tmp_path / "Song.mp4"
    media_path.write_bytes(b"fake media")
    db = KaraokeDatabase(str(tmp_path / "test.db"))
    manager = CoachPreparationManager(
        db=db,
        events=EventSystem(),
        download_manager=MagicMock(),
        download_path=str(tmp_path),
    )
    result = manager.register_local_file(str(media_path))

    with (
        patch(
            "biaoke.lib.coach_preparation.write_song_guide",
            return_value={"lyrics": {"status": "missing", "lines": []}},
        ),
        patch("biaoke.lib.coach_preparation._separate_coach_stems", return_value=None),
        patch(
            "biaoke.lib.coach_preparation._extract_coach_melody",
            return_value={"status": "ready", "notes": [{"start": 0, "end": 1, "midi": 60}]},
        ),
    ):
        manager.run_pending_analysis_once()

    track = db.get_coach_track(result["track"]["id"])
    assert track["status"] == "needs_review"
    assert track["quality_status"] == "needs_review"
    db.close()


def test_pending_analysis_accepts_line_timed_lyrics(tmp_path):
    media_path = tmp_path / "Song.mp4"
    media_path.write_bytes(b"fake media")
    db = KaraokeDatabase(str(tmp_path / "test.db"))
    manager = CoachPreparationManager(
        db=db,
        events=EventSystem(),
        download_manager=MagicMock(),
        download_path=str(tmp_path),
    )
    result = manager.register_local_file(str(media_path))

    with (
        patch(
            "biaoke.lib.coach_preparation.write_song_guide",
            return_value={
                "lyrics": {
                    "status": "ready",
                    "has_karaoke_timing": False,
                    "lines": [
                        {"start": 0, "end": 1, "text": "hello"},
                        {"start": 2, "end": 3, "text": "again"},
                    ],
                }
            },
        ),
        patch(
            "biaoke.lib.coach_preparation._separate_coach_stems",
            return_value={
                "status": "ready",
                "vocals_path": str(tmp_path / "vocals.wav"),
                "instrumental_path": str(tmp_path / "instrumental.wav"),
            },
        ),
        patch(
            "biaoke.lib.coach_preparation._extract_coach_melody",
            return_value={"status": "ready", "notes": [{"start": 0, "end": 1, "midi": 60}]},
        ),
    ):
        manager.run_pending_analysis_once()

    track = db.get_coach_track(result["track"]["id"])
    assets = db.get_coach_assets(result["track"]["id"])
    with open(assets["guide_path"], encoding="utf-8") as handle:
        coach_guide = json.load(handle)

    assert track["status"] == "ready"
    assert track["quality_status"] == "ready"
    assert "line_timing_only" in coach_guide["quality"]["messages"]
    assert coach_guide["melody"]["vocal_filter"]["source"] == "line_lyrics"
    db.close()


def test_pending_analysis_marks_needs_review_when_lyrics_duration_mismatches(tmp_path):
    media_path = tmp_path / "Song.mp4"
    media_path.write_bytes(b"fake media")
    db = KaraokeDatabase(str(tmp_path / "test.db"))
    manager = CoachPreparationManager(
        db=db,
        events=EventSystem(),
        download_manager=MagicMock(),
        download_path=str(tmp_path),
    )
    result = manager.register_local_file(str(media_path))

    with (
        patch(
            "biaoke.lib.coach_preparation.write_song_guide",
            return_value={
                "lyrics": {
                    "status": "ready",
                    "has_karaoke_timing": False,
                    "lines": [{"start": 0, "end": 260, "text": "wrong long version"}],
                }
            },
        ),
        patch(
            "biaoke.lib.coach_preparation._separate_coach_stems",
            return_value={
                "status": "ready",
                "vocals_path": str(tmp_path / "vocals.wav"),
                "instrumental_path": str(tmp_path / "instrumental.wav"),
            },
        ),
        patch(
            "biaoke.lib.coach_preparation._extract_coach_melody",
            return_value={
                "status": "ready",
                "duration_seconds": 180,
                "notes": [{"start": 10, "end": 170, "midi": 60}],
            },
        ),
    ):
        manager.run_pending_analysis_once()

    track = db.get_coach_track(result["track"]["id"])
    assets = db.get_coach_assets(result["track"]["id"])
    with open(assets["guide_path"], encoding="utf-8") as handle:
        coach_guide = json.load(handle)

    assert track["status"] == "needs_review"
    assert "lyrics_duration_mismatch" in coach_guide["quality"]["messages"]
    db.close()


def test_pending_analysis_marks_needs_review_when_melody_ends_before_lyrics(tmp_path):
    media_path = tmp_path / "Song.mp4"
    media_path.write_bytes(b"fake media")
    db = KaraokeDatabase(str(tmp_path / "test.db"))
    manager = CoachPreparationManager(
        db=db,
        events=EventSystem(),
        download_manager=MagicMock(),
        download_path=str(tmp_path),
    )
    result = manager.register_local_file(str(media_path))

    with (
        patch(
            "biaoke.lib.coach_preparation.write_song_guide",
            return_value={
                "lyrics": {
                    "status": "ready",
                    "has_karaoke_timing": False,
                    "lines": [{"start": 0, "end": 175, "text": "lyrics continue"}],
                }
            },
        ),
        patch(
            "biaoke.lib.coach_preparation._separate_coach_stems",
            return_value={
                "status": "ready",
                "vocals_path": str(tmp_path / "vocals.wav"),
                "instrumental_path": str(tmp_path / "instrumental.wav"),
            },
        ),
        patch(
            "biaoke.lib.coach_preparation._extract_coach_melody",
            return_value={
                "status": "ready",
                "duration_seconds": 180,
                "notes": [{"start": 10, "end": 140, "midi": 60}],
            },
        ),
    ):
        manager.run_pending_analysis_once()

    track = db.get_coach_track(result["track"]["id"])
    assets = db.get_coach_assets(result["track"]["id"])
    with open(assets["guide_path"], encoding="utf-8") as handle:
        coach_guide = json.load(handle)

    assert track["status"] == "needs_review"
    assert "melody_ends_before_lyrics" in coach_guide["quality"]["messages"]
    db.close()


def test_pending_analysis_marks_needs_review_without_vocal_stem(tmp_path):
    media_path = tmp_path / "Song.mp4"
    media_path.write_bytes(b"fake media")
    db = KaraokeDatabase(str(tmp_path / "test.db"))
    manager = CoachPreparationManager(
        db=db,
        events=EventSystem(),
        download_manager=MagicMock(),
        download_path=str(tmp_path),
    )
    result = manager.register_local_file(str(media_path))

    with (
        patch(
            "biaoke.lib.coach_preparation.write_song_guide",
            return_value={
                "lyrics": {
                    "status": "ready",
                    "has_karaoke_timing": True,
                    "lines": [{"start": 0, "end": 1, "text": "hello"}],
                }
            },
        ),
        patch("biaoke.lib.coach_preparation._separate_coach_stems", return_value=None),
        patch(
            "biaoke.lib.coach_preparation._extract_coach_melody",
            return_value={"status": "ready", "notes": [{"start": 0, "end": 1, "midi": 60}]},
        ) as melody_mock,
    ):
        manager.run_pending_analysis_once()

    track = db.get_coach_track(result["track"]["id"])
    assets = db.get_coach_assets(result["track"]["id"])
    with open(assets["guide_path"], encoding="utf-8") as handle:
        coach_guide = json.load(handle)

    assert track["status"] == "needs_review"
    assert "mix_melody_only" in coach_guide["quality"]["messages"]
    melody_mock.assert_called_once_with(media_path)
    db.close()


def test_review_track_with_ai_applies_revised_lyrics_and_marks_ready(tmp_path):
    media_path = tmp_path / "Artist - Song.mp4"
    media_path.write_bytes(b"fake media")
    guide_path = tmp_path / "Artist - Song.biaoke-coach.json"
    guide_path.write_text(
        json.dumps(
            {
                "schema": "biaoke.coach_guide",
                "version": 1,
                "stems": {
                    "status": "ready",
                    "vocals_path": str(tmp_path / "vocals.wav"),
                    "instrumental_path": str(tmp_path / "instrumental.wav"),
                },
                "transcript": {
                    "status": "ready",
                    "words": [
                        {"word": "hello", "start": 1.0, "end": 1.4, "probability": 0.95},
                        {"word": "again", "start": 1.45, "end": 2.0, "probability": 0.94},
                    ],
                },
                "lyrics": {"status": "missing", "lines": []},
                "melody": {
                    "status": "ready",
                    "duration_seconds": 12,
                    "notes": [{"start": 1.0, "end": 2.0, "midi": 60, "confidence": 0.9}],
                },
                "quality": {
                    "status": "needs_review",
                    "messages": ["needs_lyrics"],
                    "lyrics_ready": False,
                    "melody_ready": True,
                    "vocal_stem_ready": True,
                },
                "tasks": [],
            }
        ),
        encoding="utf-8",
    )
    db = KaraokeDatabase(str(tmp_path / "test.db"))
    manager = CoachPreparationManager(
        db=db,
        events=EventSystem(),
        download_manager=MagicMock(),
        download_path=str(tmp_path),
    )
    track = db.upsert_coach_track(
        source_type="local",
        source_url=str(media_path),
        source_id=str(media_path),
        display_title="Artist - Song",
        file_path=str(media_path),
        status="needs_review",
    )
    db.set_coach_assets(
        track["id"],
        original_audio_path=str(media_path),
        guide_path=str(guide_path),
        vocal_reference_path=str(tmp_path / "vocals.wav"),
        instrumental_audio_path=str(tmp_path / "instrumental.wav"),
    )

    with patch(
        "biaoke.lib.coach_preparation._review_coach_guide_with_ai",
        return_value={
            "_provider": "deepseek",
            "_model": "deepseek-v4-pro",
            "action": "apply",
            "confidence": 0.86,
            "summary": "Built line captions from transcript words.",
            "issues": ["needs_lyrics"],
            "lines": [{"start": 1.0, "end": 2.0, "text": "hello again"}],
            "alignment": {
                "granularity": "word",
                "paint_units": [
                    {
                        "start": 1.0,
                        "end": 1.4,
                        "text": "hello",
                        "line_index": 0,
                        "unit_index": 0,
                        "unit_type": "word",
                    },
                    {
                        "start": 1.45,
                        "end": 2.0,
                        "text": "again",
                        "line_index": 0,
                        "unit_index": 1,
                        "unit_type": "word",
                    },
                ],
            },
        },
    ):
        result = manager.review_track_with_ai(track["id"])

    updated_track = db.get_coach_track(track["id"])
    jobs = db.list_coach_jobs(track["id"], limit=1)
    revised = json.loads(guide_path.read_text(encoding="utf-8"))

    assert result is not None
    assert updated_track["status"] == "ready"
    assert updated_track["quality_status"] == "ready"
    assert jobs[0]["stage"] == "ai_review"
    assert jobs[0]["status"] == "complete"
    assert revised["lyrics"]["status"] == "ready"
    assert revised["lyrics"]["lines"][0]["text"] == "hello again"
    assert revised["lyrics"]["alignment"]["method"] == "deepseek_review_paint_units"
    assert revised["lyrics"]["alignment"]["granularity"] == "word"
    assert revised["lyrics"]["alignment"]["paint_units"][1]["text"] == "again"
    assert revised["quality"]["status"] == "ready"
    assert revised["quality"]["ai_review"]["model"] == "deepseek-v4-pro"
    assert revised["tasks"][0]["text"] == "hello again"
    assert guide_path.with_name(guide_path.name + ".before-ai-review").exists()
    db.close()


def test_review_track_with_ai_uses_local_transcript_when_lyrics_are_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_REVIEW_PROVIDER", raising=False)
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    monkeypatch.delenv("XIAOMI_MIMO_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    media_path = tmp_path / "Artist - Missing Lyrics.mp4"
    media_path.write_bytes(b"fake media")
    guide_path = tmp_path / "Artist - Missing Lyrics.biaoke-coach.json"
    guide_path.write_text(
        json.dumps(
            {
                "schema": "biaoke.coach_guide",
                "version": 1,
                "stems": {
                    "status": "ready",
                    "vocals_path": str(tmp_path / "vocals.wav"),
                    "instrumental_path": str(tmp_path / "instrumental.wav"),
                },
                "transcript": {
                    "status": "ready",
                    "engine": "faster-whisper",
                    "words": [
                        {"word": "won't", "start": 1.0, "end": 1.25, "probability": 0.92},
                        {"word": "you", "start": 1.28, "end": 1.45, "probability": 0.91},
                        {"word": "come", "start": 1.48, "end": 1.8, "probability": 0.93},
                        {"word": "and", "start": 1.85, "end": 2.0, "probability": 0.9},
                        {"word": "save", "start": 2.05, "end": 2.35, "probability": 0.94},
                        {"word": "me", "start": 2.4, "end": 2.7, "probability": 0.95},
                    ],
                },
                "lyrics": {"status": "missing", "lines": []},
                "melody": {
                    "status": "ready",
                    "duration_seconds": 8,
                    "notes": [{"start": 1.0, "end": 2.7, "midi": 60, "confidence": 0.9}],
                },
                "quality": {
                    "status": "needs_review",
                    "messages": ["needs_lyrics"],
                    "lyrics_ready": False,
                    "melody_ready": True,
                    "vocal_stem_ready": True,
                },
                "tasks": [],
            }
        ),
        encoding="utf-8",
    )
    db = KaraokeDatabase(str(tmp_path / "test.db"))
    manager = CoachPreparationManager(
        db=db,
        events=EventSystem(),
        download_manager=MagicMock(),
        download_path=str(tmp_path),
    )
    track = db.upsert_coach_track(
        source_type="local",
        source_url=str(media_path),
        source_id=str(media_path),
        display_title="Artist - Missing Lyrics",
        file_path=str(media_path),
        status="needs_review",
    )
    db.set_coach_assets(
        track["id"],
        original_audio_path=str(media_path),
        guide_path=str(guide_path),
        vocal_reference_path=str(tmp_path / "vocals.wav"),
        instrumental_audio_path=str(tmp_path / "instrumental.wav"),
    )

    with patch("biaoke.lib.coach_preparation.requests.post") as post_mock:
        result = manager.review_track_with_ai(track["id"])

    updated_track = db.get_coach_track(track["id"])
    revised = json.loads(guide_path.read_text(encoding="utf-8"))

    assert result is not None
    assert updated_track["status"] == "ready"
    assert updated_track["quality_status"] == "ready"
    assert post_mock.call_count == 0
    assert revised["lyrics"]["status"] == "ready"
    assert revised["lyrics"]["source"] == "local_transcript_review"
    assert revised["lyrics"]["lines"][0]["text"] == "won't you come and save me"
    assert revised["lyrics"]["alignment"]["method"] == "local_transcript_review_paint_units"
    assert revised["lyrics"]["alignment"]["paint_units"][0]["text"] == "won't"
    assert revised["quality"]["ai_review"]["provider"] == "local_transcript"
    assert revised["quality"]["ai_review"]["model"] == "faster-whisper"
    db.close()


def test_deepseek_review_uses_pro_model_and_alignment_payload(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_THINKING", raising=False)
    monkeypatch.delenv("DEEPSEEK_REASONING_EFFORT", raising=False)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "model": "deepseek-v4-pro",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "action": "no_change",
                                    "confidence": 0.8,
                                    "summary": "No change.",
                                    "issues": [],
                                    "lines": [],
                                }
                            )
                        }
                    }
                ],
            }

    guide = {
        "lyrics": {
            "status": "ready",
            "lines": [{"start": 10.0, "end": 13.0, "text": "hello again"}],
            "alignment": {
                "status": "ready",
                "granularity": "word",
                "paint_units": [
                    {"start": 10.0, "end": 10.5, "text": "hello", "line_index": 0, "unit_index": 0, "unit_type": "word"}
                ],
            },
        },
        "transcript": {
            "status": "ready",
            "words": [
                {"word": "hello", "start": 10.05, "end": 10.5, "probability": 0.95},
                {"word": "again", "start": 10.6, "end": 11.0, "probability": 0.94},
            ],
        },
        "melody": {
            "duration_seconds": 20,
            "notes": [
                {"start": 10.0, "end": 10.5, "midi": 60, "confidence": 0.9},
                {"start": 10.6, "end": 11.0, "midi": 62, "confidence": 0.9},
            ],
        },
        "quality": {"status": "needs_review", "messages": ["lyrics_duration_mismatch"]},
    }

    with patch("biaoke.lib.coach_preparation.requests.post", return_value=FakeResponse()) as post_mock:
        review = _review_coach_guide_with_deepseek({"id": 7, "display_title": "Artist - Song"}, guide)

    request_body = post_mock.call_args.kwargs["json"]
    review_input = json.loads(request_body["messages"][1]["content"])
    assert review["_model"] == "deepseek-v4-pro"
    assert request_body["model"] == "deepseek-v4-pro"
    assert request_body["thinking"] == {"type": "enabled"}
    assert request_body["reasoning_effort"] == "high"
    assert "alignment" in review_input["output_schema"]
    assert review_input["lyrics"]["current_alignment"]["paint_units"][0]["text"] == "hello"
    assert review_input["melody"]["vocal_activity_spans"][0]["start"] == 10.0


def test_ai_review_auto_prefers_mimo_when_configured(monkeypatch):
    monkeypatch.delenv("AI_REVIEW_PROVIDER", raising=False)
    monkeypatch.setenv("MIMO_API_KEY", "test-mimo-key")
    monkeypatch.delenv("MIMO_MODEL", raising=False)
    monkeypatch.delenv("MIMO_BASE_URL", raising=False)
    monkeypatch.delenv("MIMO_TIMEOUT", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "model": "mimo-v2.5-pro",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "action": "apply",
                                    "confidence": 0.82,
                                    "summary": "Adjusted timing.",
                                    "issues": [],
                                    "lines": [{"start": 1.0, "end": 2.0, "text": "hello"}],
                                }
                            )
                        }
                    }
                ],
                "usage": {"total_tokens": 123},
            }

    guide = {
        "lyrics": {"status": "ready", "lines": [{"start": 1.0, "end": 2.0, "text": "hello"}]},
        "transcript": {"status": "ready", "words": [{"word": "hello", "start": 1.0, "end": 1.5}]},
        "melody": {"duration_seconds": 5, "notes": [{"start": 1.0, "end": 1.5, "midi": 60}]},
        "quality": {"status": "needs_review"},
    }

    with patch("biaoke.lib.coach_preparation.requests.post", return_value=FakeResponse()) as post_mock:
        review = _review_coach_guide_with_ai({"id": 7, "display_title": "Artist - Song"}, guide)

    request_body = post_mock.call_args.kwargs["json"]
    headers = post_mock.call_args.kwargs["headers"]
    assert post_mock.call_args.args[0] == "https://api.xiaomimimo.com/v1/chat/completions"
    assert headers["api-key"] == "test-mimo-key"
    assert request_body["model"] == "mimo-v2.5-pro"
    assert request_body["temperature"] == 0.1
    assert review["_provider"] == "mimo"
    assert review["_model"] == "mimo-v2.5-pro"
    assert review["_usage"]["total_tokens"] == 123


def test_review_track_with_ai_rejects_rewritten_existing_lyrics(tmp_path):
    media_path = tmp_path / "Artist - Canonical.mp4"
    media_path.write_bytes(b"fake media")
    guide_path = tmp_path / "Artist - Canonical.biaoke-coach.json"
    original_guide = {
        "schema": "biaoke.coach_guide",
        "version": 1,
        "stems": {
            "status": "ready",
            "vocals_path": str(tmp_path / "vocals.wav"),
            "instrumental_path": str(tmp_path / "instrumental.wav"),
        },
        "transcript": {"status": "ready", "words": []},
        "lyrics": {
            "status": "ready",
            "source": "lrclib",
            "lines": [
                {"start": 1, "end": 2, "text": "First real line"},
                {"start": 2, "end": 3, "text": "Second real line"},
                {"start": 3, "end": 4, "text": "Third real line"},
                {"start": 4, "end": 5, "text": "Fourth real line"},
            ],
        },
        "melody": {
            "status": "ready",
            "duration_seconds": 20,
            "notes": [{"start": 1.0, "end": 2.0, "midi": 60, "confidence": 0.9}],
        },
        "quality": {
            "status": "needs_review",
            "messages": ["lyrics_duration_mismatch"],
            "lyrics_ready": True,
            "melody_ready": True,
            "vocal_stem_ready": True,
        },
        "tasks": [],
    }
    guide_path.write_text(json.dumps(original_guide), encoding="utf-8")
    db = KaraokeDatabase(str(tmp_path / "test.db"))
    manager = CoachPreparationManager(
        db=db,
        events=EventSystem(),
        download_manager=MagicMock(),
        download_path=str(tmp_path),
    )
    track = db.upsert_coach_track(
        source_type="local",
        source_url=str(media_path),
        source_id=str(media_path),
        display_title="Artist - Canonical",
        file_path=str(media_path),
        status="needs_review",
    )
    db.set_coach_assets(track["id"], original_audio_path=str(media_path), guide_path=str(guide_path))

    with (
        patch(
            "biaoke.lib.coach_preparation._review_coach_guide_with_ai",
            return_value={
                "_provider": "deepseek",
                "_model": "deepseek-v4-flash",
                "action": "apply",
                "confidence": 0.9,
                "summary": "Bad rewrite.",
                "issues": [],
                "lines": [
                    {"start": 1, "end": 2, "text": "Completely different words"},
                    {"start": 2, "end": 3, "text": "Invented transcript caption"},
                    {"start": 3, "end": 4, "text": "Another wrong phrase"},
                    {"start": 4, "end": 5, "text": "Not from source lyric"},
                ],
            },
        ),
        pytest.raises(ValueError, match="alterou texto demais"),
    ):
        manager.review_track_with_ai(track["id"])

    unchanged = json.loads(guide_path.read_text(encoding="utf-8"))
    job = db.list_coach_jobs(track["id"], limit=1)[0]

    assert unchanged["lyrics"]["lines"][0]["text"] == "First real line"
    assert job["stage"] == "ai_review"
    assert job["status"] == "failed"
    assert not guide_path.with_name(guide_path.name + ".before-ai-review").exists()
    db.close()


def test_revert_ai_review_restores_backup_and_updates_status(tmp_path):
    media_path = tmp_path / "Artist - Song.mp4"
    media_path.write_bytes(b"fake media")
    guide_path = tmp_path / "Artist - Song.biaoke-coach.json"
    backup_path = guide_path.with_name(guide_path.name + ".before-ai-review")
    guide_path.write_text(
        json.dumps(
            {
                "schema": "biaoke.coach_guide",
                "lyrics": {
                    "status": "ready",
                    "source": "lrclib+deepseek_ai_review",
                    "lines": [{"start": 1, "end": 2, "text": "AI line"}],
                },
                "melody": {"status": "ready", "notes": [{"start": 1, "end": 2, "midi": 60}]},
                "quality": {"status": "ready", "messages": ["line_timing_only"]},
            }
        ),
        encoding="utf-8",
    )
    backup_path.write_text(
        json.dumps(
            {
                "schema": "biaoke.coach_guide",
                "lyrics": {
                    "status": "ready",
                    "source": "lrclib",
                    "lines": [{"start": 1, "end": 4, "text": "Original line"}],
                },
                "melody": {"status": "ready", "notes": [{"start": 1, "end": 2, "midi": 60}]},
                "quality": {"status": "needs_review", "messages": ["lyrics_duration_mismatch"]},
            }
        ),
        encoding="utf-8",
    )
    db = KaraokeDatabase(str(tmp_path / "test.db"))
    manager = CoachPreparationManager(
        db=db,
        events=EventSystem(),
        download_manager=MagicMock(),
        download_path=str(tmp_path),
    )
    track = db.upsert_coach_track(
        source_type="local",
        source_url=str(media_path),
        source_id=str(media_path),
        display_title="Artist - Song",
        file_path=str(media_path),
        status="ready",
    )
    db.update_coach_track(track["id"], quality_status="ready")
    db.set_coach_assets(track["id"], original_audio_path=str(media_path), guide_path=str(guide_path))

    assert manager.get_track_with_assets(track["id"])["assets"]["has_ai_review_backup"] is True

    result = manager.revert_ai_review(track["id"])
    restored = json.loads(guide_path.read_text(encoding="utf-8"))
    updated_track = db.get_coach_track(track["id"])
    jobs = db.list_coach_jobs(track["id"], limit=1)

    assert result is not None
    assert restored["lyrics"]["lines"][0]["text"] == "Original line"
    assert updated_track["status"] == "needs_review"
    assert updated_track["quality_status"] == "needs_review"
    assert jobs[0]["stage"] == "ai_revert"
    assert jobs[0]["status"] == "complete"
    assert not backup_path.exists()
    assert guide_path.with_name(guide_path.name + ".after-ai-review").exists()
    db.close()


def test_playable_asset_prefers_instrumental_and_loads_guide_from_stem(tmp_path):
    original_path = tmp_path / "Artist - Song.mp3"
    instrumental_path = tmp_path / ".biaoke-stems" / "Artist - Song.instrumental.wav"
    guide_path = tmp_path / "Artist - Song.biaoke-coach.json"
    original_path.write_bytes(b"original")
    instrumental_path.parent.mkdir()
    instrumental_path.write_bytes(b"instrumental")
    guide_path.write_text(
        json.dumps(
            {
                "schema": "biaoke.coach_guide",
                "lyrics": {"status": "ready", "lines": []},
                "melody": {"status": "ready", "notes": []},
                "quality": {"status": "ready"},
            }
        ),
        encoding="utf-8",
    )

    db = KaraokeDatabase(str(tmp_path / "test.db"))
    manager = CoachPreparationManager(
        db=db,
        events=EventSystem(),
        download_manager=MagicMock(),
        download_path=str(tmp_path),
    )
    track = db.upsert_coach_track(
        source_type="local",
        source_url=str(original_path),
        source_id=str(original_path),
        display_title="Artist - Song",
        file_path=str(original_path),
        status="ready",
    )
    db.set_coach_assets(
        track["id"],
        original_audio_path=str(original_path),
        instrumental_audio_path=str(instrumental_path),
        guide_path=str(guide_path),
    )

    playable = manager.get_playable_track_asset(track["id"])
    loaded_guide = manager.load_coach_guide_for_media_path(instrumental_path)

    assert playable["path"] == str(instrumental_path)
    assert playable["title"] == "Artist - Song"
    assert playable["using_instrumental"] is True
    assert loaded_guide["track"]["id"] == track["id"]
    assert loaded_guide["assets"]["original_audio_path"] == str(original_path)
    db.close()

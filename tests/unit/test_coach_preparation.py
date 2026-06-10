import json
from unittest.mock import MagicMock, patch

import pytest

from biaoke.lib.coach_preparation import (
    CoachPreparationManager,
    _lyrics_lines_for_forced_alignment,
    _review_coach_guide_with_ai,
    _review_coach_guide_with_deepseek,
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

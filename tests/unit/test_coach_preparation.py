import json
from unittest.mock import MagicMock, patch

from biaoke.lib.coach_preparation import CoachPreparationManager
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

    with open(assets["guide_path"], encoding="utf-8") as handle:
        coach_guide = json.load(handle)

    assert coach_guide["schema"] == "biaoke.coach_guide"
    assert coach_guide["stems"]["engine"] == "demucs"
    assert coach_guide["tasks"][0]["target_midi"] == 60
    assert coach_guide["tasks"][0]["text"] == "hello"
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
                    "lines": [{"start": 0, "end": 1, "text": "hello"}],
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

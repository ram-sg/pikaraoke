"""Tests for scoring routes."""

from io import BytesIO
from unittest.mock import MagicMock, patch

from flask import Flask

from biaoke.routes.score import score_bp


def test_score_analyze_requires_audio():
    app = Flask(__name__)
    app.register_blueprint(score_bp)

    response = app.test_client().post("/score/analyze")

    assert response.status_code == 400
    assert response.get_json() == {"error": "Missing audio upload"}


def test_score_analyze_returns_local_result():
    app = Flask(__name__)
    app.register_blueprint(score_bp)
    fake_result = {"score": 77, "tier": "high", "review": "ok", "engine": "test", "metrics": {}}

    with patch("biaoke.routes.score.analyze_upload_bytes", return_value=fake_result):
        response = app.test_client().post(
            "/score/analyze",
            data={"audio": (BytesIO(b"audio"), "recording.webm")},
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert response.get_json() == fake_result


def test_current_melody_guide_returns_idle_without_song():
    app = Flask(__name__)
    app.register_blueprint(score_bp)
    mock_karaoke = MagicMock()
    mock_karaoke.playback_controller.now_playing_filename = None
    app.config["KARAOKE_INSTANCE"] = mock_karaoke

    response = app.test_client().get("/score/melody/current")

    assert response.status_code == 200
    assert response.get_json()["status"] == "idle"


def test_current_lyrics_guide_returns_idle_without_song():
    app = Flask(__name__)
    app.register_blueprint(score_bp)
    mock_karaoke = MagicMock()
    mock_karaoke.playback_controller.now_playing_filename = None
    app.config["KARAOKE_INSTANCE"] = mock_karaoke

    response = app.test_client().get("/score/lyrics/current")

    assert response.status_code == 200
    assert response.get_json()["status"] == "idle"


@patch("biaoke.lib.song_guide.find_external_lyrics_for_media", return_value=None)
def test_current_lyrics_guide_returns_missing_without_sidecar(mock_external, tmp_path):
    app = Flask(__name__)
    app.register_blueprint(score_bp)
    song_path = tmp_path / "song.mp4"
    song_path.write_bytes(b"fake")
    mock_karaoke = MagicMock()
    controller = mock_karaoke.playback_controller
    controller.now_playing_filename = str(song_path)
    controller.now_playing = "Artist - Song"
    controller.now_playing_position = 4.5
    controller.is_paused = False
    app.config["KARAOKE_INSTANCE"] = mock_karaoke

    response = app.test_client().get("/score/lyrics/current")

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "missing"
    assert data["title"] == "Artist - Song"
    assert data["playback_position"] == 4.5
    assert data["lines"] == []
    assert (tmp_path / "song.biaoke-guide.json").exists()
    mock_external.assert_called_once()


def test_current_lyrics_guide_returns_ass_lines(tmp_path):
    app = Flask(__name__)
    app.register_blueprint(score_bp)
    song_path = tmp_path / "song.mp4"
    subtitle_path = tmp_path / "song.pt-BR.ass"
    song_path.write_bytes(b"fake")
    subtitle_path.write_text(
        """
[Events]
Format: Start, End, Text
Dialogue: 0:00:01.00,0:00:03.00,Primeira linha
""",
        encoding="utf-8",
    )
    mock_karaoke = MagicMock()
    controller = mock_karaoke.playback_controller
    controller.now_playing_filename = str(song_path)
    controller.now_playing = "Artist - Song"
    controller.now_playing_position = 8
    controller.is_paused = True
    app.config["KARAOKE_INSTANCE"] = mock_karaoke

    response = app.test_client().get("/score/lyrics/current")

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ready"
    assert data["source"] == "sidecar_ass"
    assert data["line_count"] == 1
    assert data["title"] == "Artist - Song"
    assert data["is_paused"] is True
    assert data["lyrics_offset_seconds"] == 0
    assert data["lines"][0]["text"] == "Primeira linha"
    assert (tmp_path / "song.biaoke-guide.json").exists()


def test_current_lyrics_offset_can_be_updated(tmp_path):
    app = Flask(__name__)
    app.register_blueprint(score_bp)
    song_path = tmp_path / "song.mp4"
    subtitle_path = tmp_path / "song.ass"
    song_path.write_bytes(b"fake")
    subtitle_path.write_text(
        """
[Events]
Format: Start, End, Text
Dialogue: 0:00:01.00,0:00:03.00,Primeira linha
""",
        encoding="utf-8",
    )
    mock_karaoke = MagicMock()
    controller = mock_karaoke.playback_controller
    controller.now_playing_filename = str(song_path)
    controller.now_playing = "Artist - Song"
    controller.now_playing_position = 0
    controller.is_paused = False
    app.config["KARAOKE_INSTANCE"] = mock_karaoke

    response = app.test_client().post(
        "/score/lyrics-offset/current",
        json={"offset_seconds": 1.5},
    )

    assert response.status_code == 200
    assert response.get_json()["lyrics_offset_seconds"] == 1.5

    response = app.test_client().post(
        "/score/lyrics-offset/current",
        json={"delta_seconds": -0.5},
    )

    assert response.status_code == 200
    assert response.get_json()["lyrics_offset_seconds"] == 1.0

    response = app.test_client().get("/score/lyrics/current")
    assert response.get_json()["lyrics_offset_seconds"] == 1.0


def test_current_song_guide_returns_package(tmp_path):
    app = Flask(__name__)
    app.register_blueprint(score_bp)
    song_path = tmp_path / "song.mp4"
    subtitle_path = tmp_path / "song.ass"
    song_path.write_bytes(b"fake")
    subtitle_path.write_text(
        """
[Events]
Format: Start, End, Text
Dialogue: 0:00:01.00,0:00:03.00,Primeira linha
""",
        encoding="utf-8",
    )
    mock_karaoke = MagicMock()
    controller = mock_karaoke.playback_controller
    controller.now_playing_filename = str(song_path)
    controller.now_playing = "Artist - Song"
    controller.now_playing_position = 2
    controller.is_paused = False
    app.config["KARAOKE_INSTANCE"] = mock_karaoke

    response = app.test_client().get("/score/guide/current")

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ready"
    assert data["guide_path"] == "song.biaoke-guide.json"
    assert data["lyrics"]["lines"][0]["text"] == "Primeira linha"
    assert data["runtime"]["title"] == "Artist - Song"


def test_current_melody_guide_returns_transposed_notes(tmp_path):
    app = Flask(__name__)
    app.register_blueprint(score_bp)
    song_path = tmp_path / "song.mp4"
    song_path.write_bytes(b"fake")
    mock_karaoke = MagicMock()
    controller = mock_karaoke.playback_controller
    controller.now_playing_filename = str(song_path)
    controller.now_playing = "Artist - Song"
    controller.now_playing_position = 12.5
    controller.now_playing_transpose = 2
    controller.is_paused = False
    app.config["KARAOKE_INSTANCE"] = mock_karaoke
    fake_guide = {
        "status": "ready",
        "engine": "test",
        "duration_seconds": 30,
        "notes": [{"start": 1.0, "end": 2.0, "midi": 60, "note": "C4", "frequency": 261.63}],
        "contour": [{"time": 1.0, "midi": 60.125, "frequency": 263.53, "confidence": 0.9}],
    }

    with patch("biaoke.routes.score.extract_melody_guide_from_media", return_value=fake_guide):
        response = app.test_client().get("/score/melody/current")

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ready"
    assert data["title"] == "Artist - Song"
    assert data["playback_position"] == 12.5
    assert data["transpose"] == 2
    assert data["notes"][0]["midi"] == 62
    assert data["notes"][0]["note"] == "D4"
    assert data["contour"][0]["midi"] == 62.125


def test_current_routes_use_prepared_coach_package_for_playing_stem(tmp_path):
    app = Flask(__name__)
    app.register_blueprint(score_bp)
    original_path = tmp_path / "song.mp3"
    instrumental_path = tmp_path / "song.instrumental.wav"
    original_path.write_bytes(b"fake original")
    instrumental_path.write_bytes(b"fake instrumental")

    mock_karaoke = MagicMock()
    controller = mock_karaoke.playback_controller
    controller.now_playing_filename = str(instrumental_path)
    controller.now_playing = "Artist - Song"
    controller.now_playing_position = 9.25
    controller.now_playing_transpose = 1
    controller.is_paused = False
    mock_karaoke.coach_preparation.load_coach_guide_for_media_path.return_value = {
        "schema": "biaoke.coach_guide",
        "track": {"id": 42, "display_title": "Artist - Song"},
        "assets": {"original_audio_path": str(original_path)},
        "lyrics": {
            "status": "ready",
            "lines": [{"start": 1.0, "end": 3.0, "text": "Primeira linha"}],
        },
        "melody": {
            "status": "ready",
            "notes": [
                {"start": 1.0, "end": 2.0, "midi": 60, "note": "C4", "frequency": 261.63}
            ],
        },
        "quality": {"status": "ready", "messages": ["line_timing_only"]},
    }
    app.config["KARAOKE_INSTANCE"] = mock_karaoke
    client = app.test_client()

    lyrics = client.get("/score/lyrics/current").get_json()
    melody = client.get("/score/melody/current").get_json()
    package = client.get("/score/guide/current").get_json()

    assert lyrics["status"] == "ready"
    assert lyrics["coach_track_id"] == 42
    assert lyrics["quality_messages"] == ["line_timing_only"]
    assert lyrics["lines"][0]["text"] == "Primeira linha"
    assert melody["coach_track_id"] == 42
    assert melody["quality_messages"] == ["line_timing_only"]
    assert melody["notes"][0]["midi"] == 61
    assert melody["notes"][0]["note"] == "C#4"
    assert package["status"] == "ready"
    assert package["runtime"]["title"] == "Artist - Song"
    assert package["vocal_reference_available"] is True


def test_current_vocal_reference_streams_original_for_playing_coach_stem(tmp_path):
    app = Flask(__name__)
    app.register_blueprint(score_bp)
    original_path = tmp_path / "song.mp3"
    instrumental_path = tmp_path / "song.instrumental.wav"
    original_path.write_bytes(b"fake original audio")
    instrumental_path.write_bytes(b"fake instrumental")

    mock_karaoke = MagicMock()
    controller = mock_karaoke.playback_controller
    controller.now_playing_filename = str(instrumental_path)
    mock_karaoke.coach_preparation.load_coach_guide_for_media_path.return_value = {
        "assets": {"original_audio_path": str(original_path)},
    }
    app.config["KARAOKE_INSTANCE"] = mock_karaoke

    response = app.test_client().get("/score/vocal-reference/current")

    assert response.status_code == 200
    assert response.data == b"fake original audio"
    assert response.mimetype == "audio/mpeg"


def test_current_vocal_reference_prefers_vocal_stem(tmp_path):
    app = Flask(__name__)
    app.register_blueprint(score_bp)
    original_path = tmp_path / "song.mp3"
    vocal_path = tmp_path / "song.vocals.wav"
    instrumental_path = tmp_path / "song.instrumental.wav"
    original_path.write_bytes(b"fake original audio")
    vocal_path.write_bytes(b"fake vocal stem")
    instrumental_path.write_bytes(b"fake instrumental")

    mock_karaoke = MagicMock()
    controller = mock_karaoke.playback_controller
    controller.now_playing_filename = str(instrumental_path)
    mock_karaoke.coach_preparation.load_coach_guide_for_media_path.return_value = {
        "assets": {
            "original_audio_path": str(original_path),
            "vocal_reference_path": str(vocal_path),
        },
    }
    app.config["KARAOKE_INSTANCE"] = mock_karaoke

    response = app.test_client().get("/score/vocal-reference/current")

    assert response.status_code == 200
    assert response.data == b"fake vocal stem"
    assert response.mimetype == "audio/x-wav"


def test_current_vocal_reference_returns_missing_without_coach_package(tmp_path):
    app = Flask(__name__)
    app.register_blueprint(score_bp)
    song_path = tmp_path / "song.mp3"
    song_path.write_bytes(b"fake")

    mock_karaoke = MagicMock()
    mock_karaoke.playback_controller.now_playing_filename = str(song_path)
    mock_karaoke.coach_preparation.load_coach_guide_for_media_path.return_value = None
    app.config["KARAOKE_INSTANCE"] = mock_karaoke

    response = app.test_client().get("/score/vocal-reference/current")

    assert response.status_code == 404
    assert response.get_json()["status"] == "missing"

"""Tests for scoring routes."""

from io import BytesIO
from unittest.mock import patch

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

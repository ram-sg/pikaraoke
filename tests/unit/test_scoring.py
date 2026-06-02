"""Tests for real vocal scoring analysis."""

import math
import wave

import pytest

from pikaraoke.lib.scoring import ScoreAnalysisError, analyze_wav_file


def write_wav(path, samples, sample_rate=8000):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        raw = bytearray()
        for sample in samples:
            value = max(-32768, min(32767, int(sample * 32767)))
            raw.extend(value.to_bytes(2, "little", signed=True))
        wav.writeframes(bytes(raw))


def sine_wave(freq, seconds, sample_rate=8000, amplitude=0.35):
    count = int(seconds * sample_rate)
    return [
        amplitude * math.sin(2 * math.pi * freq * index / sample_rate)
        for index in range(count)
    ]


def test_scores_clear_pitched_audio(tmp_path):
    path = tmp_path / "tone.wav"
    write_wav(path, sine_wave(220, 3.0))

    result = analyze_wav_file(path, prefer_torchcrepe=False)

    assert result.score >= 40
    assert result.metrics["voiced_ratio"] > 0.8
    assert result.engine == "autocorrelation"


def test_scores_silence_as_zero(tmp_path):
    path = tmp_path / "silence.wav"
    write_wav(path, [0.0] * 16000)

    result = analyze_wav_file(path, prefer_torchcrepe=False)

    assert result.score == 0
    assert result.tier == "low"


def test_rejects_too_short_recording(tmp_path):
    path = tmp_path / "short.wav"
    write_wav(path, sine_wave(220, 0.2))

    with pytest.raises(ScoreAnalysisError):
        analyze_wav_file(path, prefer_torchcrepe=False)

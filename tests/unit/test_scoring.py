"""Tests for real vocal scoring analysis."""

import math
import shutil
import wave

import pytest

from biaoke.lib.scoring import (
    PitchFrame,
    ScoreAnalysisError,
    _pitch_frames_to_melody_contour,
    _pitch_frames_to_melody_notes,
    analyze_wav_file,
    extract_melody_guide_from_media,
    midi_to_frequency,
)


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


def test_extracts_melody_guide_from_pitched_audio(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed on this host")

    path = tmp_path / "tone.wav"
    write_wav(path, sine_wave(261.63, 2.0))

    guide = extract_melody_guide_from_media(path, prefer_torchcrepe=False, max_seconds=5)

    assert guide["status"] == "ready"
    assert guide["notes"]
    assert guide["contour"]
    assert any(note["midi"] == 60 for note in guide["notes"])
    assert any(59.5 <= point["midi"] <= 60.5 for point in guide["contour"])


def test_extracts_high_melody_guide_from_pitched_audio(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed on this host")

    path = tmp_path / "high-tone.wav"
    write_wav(path, sine_wave(880.0, 2.0))

    guide = extract_melody_guide_from_media(path, prefer_torchcrepe=False, max_seconds=5)

    assert guide["status"] == "ready"
    assert any(80 <= note["midi"] <= 82 for note in guide["notes"])
    assert any(80.5 <= point["midi"] <= 81.5 for point in guide["contour"])


def test_melody_contour_rejects_isolated_pitch_spikes():
    frames = [
        PitchFrame(0.00, midi_to_frequency(60), 0.9, 0.4),
        PitchFrame(0.05, midi_to_frequency(60.1), 0.9, 0.4),
        PitchFrame(0.10, midi_to_frequency(72), 0.9, 0.4),
        PitchFrame(0.15, midi_to_frequency(60.05), 0.9, 0.4),
        PitchFrame(0.20, midi_to_frequency(60), 0.9, 0.4),
    ]

    contour = _pitch_frames_to_melody_contour(frames)
    notes = _pitch_frames_to_melody_notes(frames)

    assert contour
    assert all(point["midi"] < 61 for point in contour)
    assert {note["midi"] for note in notes} == {60}


def test_melody_contour_preserves_short_sustained_high_notes():
    frames = [
        PitchFrame(0.00, midi_to_frequency(60), 0.9, 0.4),
        PitchFrame(0.05, midi_to_frequency(60.1), 0.9, 0.4),
        PitchFrame(0.10, midi_to_frequency(72), 0.9, 0.4),
        PitchFrame(0.15, midi_to_frequency(72.1), 0.9, 0.4),
        PitchFrame(0.20, midi_to_frequency(72.05), 0.9, 0.4),
        PitchFrame(0.25, midi_to_frequency(60.05), 0.9, 0.4),
        PitchFrame(0.30, midi_to_frequency(60), 0.9, 0.4),
    ]

    contour = _pitch_frames_to_melody_contour(frames)
    notes = _pitch_frames_to_melody_notes(frames)

    assert any(point["midi"] > 71 for point in contour)
    assert 72 in {note["midi"] for note in notes}

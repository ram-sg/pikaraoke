"""Lyrics guide parsing and normalization."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


_ASS_TIME_RE = re.compile(r"^(\d+):(\d{1,2}):(\d{1,2})(?:[.](\d{1,2}))?$")
_LRC_TIME_RE = re.compile(r"^(\d+):(\d{1,2})(?:[.:](\d{1,3}))?$")
_LRC_TIMESTAMP_RE = re.compile(r"\[(\d+:\d{1,2}(?:[.:]\d{1,3})?)\]")
_KARAOKE_TAG_RE = re.compile(r"\{[^}]*\\k[fo]?(\d+)[^}]*\}", re.IGNORECASE)


def parse_ass_time(value: str) -> float | None:
    """Parse an ASS timestamp like H:MM:SS.CS into seconds."""
    match = _ASS_TIME_RE.match(str(value or "").strip())
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    centiseconds = int((match.group(4) or "0").ljust(2, "0")[:2])
    return hours * 3600 + minutes * 60 + seconds + centiseconds / 100


def parse_lrc_time(value: str) -> float | None:
    """Parse an LRC timestamp like MM:SS.xx into seconds."""
    value = str(value or "").strip().strip("[]")
    match = _LRC_TIME_RE.match(value)
    if not match:
        return None
    minutes = int(match.group(1))
    seconds = int(match.group(2))
    fraction = match.group(3) or "0"
    if len(fraction) == 1:
        fraction_seconds = int(fraction) / 10
    elif len(fraction) == 2:
        fraction_seconds = int(fraction) / 100
    else:
        fraction_seconds = int(fraction[:3]) / 1000
    return minutes * 60 + seconds + fraction_seconds


def strip_ass_tags(text: str) -> str:
    """Remove ASS formatting tags from visible lyric text."""
    return (
        str(text or "")
        .replace("\\N", " ")
        .replace("\\n", " ")
        .replace("\\h", " ")
    )


def plain_ass_text(text: str) -> str:
    """Return readable lyric text without ASS override blocks."""
    return re.sub(r"\s+", " ", re.sub(r"\{[^}]*\}", "", strip_ass_tags(text))).strip()


def split_ass_fields(value: str, expected_fields: int) -> list[str]:
    """Split ASS dialogue fields while preserving commas in the final text field."""
    fields = str(value or "").split(",")
    if len(fields) <= expected_fields:
        return [field.strip() for field in fields]
    return [
        *[field.strip() for field in fields[: expected_fields - 1]],
        ",".join(fields[expected_fields - 1 :]).strip(),
    ]


def _tokenize_line_text(text: str, start: float, end: float) -> list[dict[str, Any]]:
    clean_text = plain_ass_text(text)
    if not clean_text:
        return []
    pieces = re.findall(r"\S+\s*", clean_text) or [clean_text]
    total_weight = sum(max(1, len(piece.strip())) for piece in pieces)
    duration = max(0.05, end - start)
    cursor = start
    segments = []
    for index, piece in enumerate(pieces):
        is_last = index == len(pieces) - 1
        weight = max(1, len(piece.strip()))
        segment_duration = end - cursor if is_last else duration * (weight / total_weight)
        segment_end = min(end, cursor + max(0.03, segment_duration))
        segments.append({"text": piece, "start": round(cursor, 3), "end": round(segment_end, 3)})
        cursor = segment_end
    return segments


def _parse_karaoke_segments(text: str, start: float, end: float) -> tuple[list[dict[str, Any]], bool]:
    tags = [
        {
            "index": match.start(),
            "end_index": match.end(),
            "duration": max(0.01, int(match.group(1)) / 100),
        }
        for match in _KARAOKE_TAG_RE.finditer(text)
    ]
    if not tags:
        return _tokenize_line_text(text, start, end), False

    raw_segments = []
    for index, tag in enumerate(tags):
        next_tag = tags[index + 1] if index + 1 < len(tags) else None
        raw_text = text[tag["end_index"] : next_tag["index"] if next_tag else len(text)]
        clean_text = plain_ass_text(raw_text)
        if clean_text:
            raw_segments.append({"text": clean_text, "duration": tag["duration"]})

    if not raw_segments:
        return _tokenize_line_text(text, start, end), False

    line_duration = max(0.05, end - start)
    tagged_duration = sum(segment["duration"] for segment in raw_segments)
    scale = line_duration / tagged_duration if tagged_duration > 0 else 1
    cursor = start
    segments = []
    for index, segment in enumerate(raw_segments):
        is_last = index == len(raw_segments) - 1
        duration = end - cursor if is_last else segment["duration"] * scale
        segment_end = min(end, cursor + max(0.03, duration))
        text_suffix = " " if index < len(raw_segments) - 1 else ""
        segments.append(
            {
                "text": f"{segment['text']}{text_suffix}",
                "start": round(cursor, 3),
                "end": round(segment_end, 3),
            }
        )
        cursor = segment_end
    return segments, True


def parse_ass_lyrics(content: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse ASS dialogue events into normalized lyric lines."""
    lines = str(content or "").splitlines()
    in_events = False
    format_fields = [
        "Layer",
        "Start",
        "End",
        "Style",
        "Name",
        "MarginL",
        "MarginR",
        "MarginV",
        "Effect",
        "Text",
    ]
    lyrics = []
    has_karaoke_timing = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith(";"):
            continue
        section = re.match(r"^\[(.+)]$", line)
        if section:
            in_events = section.group(1).casefold() == "events"
            continue
        if not in_events:
            continue

        if line.casefold().startswith("format:"):
            format_fields = [
                field.strip() for field in line[line.index(":") + 1 :].split(",")
            ]
            continue
        if not line.casefold().startswith("dialogue:"):
            continue

        fields = split_ass_fields(line[line.index(":") + 1 :], len(format_fields))
        event = {field: fields[index] if index < len(fields) else "" for index, field in enumerate(format_fields)}
        start = parse_ass_time(event.get("Start", ""))
        end = parse_ass_time(event.get("End", ""))
        if start is None or end is None or end <= start:
            continue

        raw_text = event.get("Text", "")
        text = plain_ass_text(raw_text)
        if not text:
            continue

        segments, line_has_karaoke_timing = _parse_karaoke_segments(raw_text, start, end)
        has_karaoke_timing = has_karaoke_timing or line_has_karaoke_timing
        lyrics.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
                "has_karaoke_timing": line_has_karaoke_timing,
                "segments": segments,
            }
        )

    lyrics.sort(key=lambda item: item["start"])
    return lyrics, has_karaoke_timing


def parse_lrc_lyrics(
    content: str, duration_seconds: float | int | None = None
) -> list[dict[str, Any]]:
    """Parse LRC timestamped lyrics into normalized lyric lines."""
    entries = []
    for raw_line in str(content or "").splitlines():
        matches = list(_LRC_TIMESTAMP_RE.finditer(raw_line))
        if not matches:
            continue

        text = _LRC_TIMESTAMP_RE.sub("", raw_line).strip()
        if not text:
            continue

        for match in matches:
            start = parse_lrc_time(match.group(1))
            if start is not None:
                entries.append({"start": start, "text": text})

    entries.sort(key=lambda item: item["start"])
    lyrics = []
    for index, entry in enumerate(entries):
        start = float(entry["start"])
        next_start = (
            float(entries[index + 1]["start"]) if index + 1 < len(entries) else None
        )
        if next_start is not None and next_start > start:
            end = next_start
        elif duration_seconds and float(duration_seconds) > start:
            end = min(float(duration_seconds), start + 4)
        else:
            end = start + 4

        end = max(start + 0.2, end)
        text = re.sub(r"\s+", " ", str(entry["text"])).strip()
        if not text:
            continue
        lyrics.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
                "has_karaoke_timing": False,
                "segments": _tokenize_line_text(text, start, end),
            }
        )

    return lyrics


def build_lyrics_guide_from_ass(path: str | Path) -> dict[str, Any]:
    """Build a Biaoke lyrics guide from an ASS subtitle sidecar."""
    subtitle_path = Path(path)
    content = subtitle_path.read_text(encoding="utf-8-sig", errors="replace")
    lines, has_karaoke_timing = parse_ass_lyrics(content)
    confidence = 0.9 if has_karaoke_timing else 0.7
    return {
        "status": "ready" if lines else "missing",
        "source": "sidecar_ass",
        "source_format": "ass",
        "confidence": confidence if lines else 0,
        "has_karaoke_timing": has_karaoke_timing,
        "line_count": len(lines),
        "lines": lines,
    }


def build_lyrics_guide_from_lrc(
    content: str,
    *,
    source: str = "lrc",
    duration_seconds: float | int | None = None,
    confidence: float = 0.82,
    source_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a Biaoke lyrics guide from LRC content."""
    lines = parse_lrc_lyrics(content, duration_seconds=duration_seconds)
    guide = {
        "status": "ready" if lines else "missing",
        "source": source,
        "source_format": "lrc",
        "confidence": confidence if lines else 0,
        "has_karaoke_timing": False,
        "line_count": len(lines),
        "lines": lines,
    }
    if source_metadata:
        guide["source_metadata"] = source_metadata
    return guide

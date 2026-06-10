"""Canonical lyric alignment units for the vocal coach renderer."""

from __future__ import annotations

import re
from typing import Any


ALIGNMENT_SCHEMA = "biaoke.lyrics_alignment"
ALIGNMENT_VERSION = 1
VOCAL_ACTIVITY_MIN_CONFIDENCE = 0.5
VOCAL_ACTIVITY_MAX_GAP_SECONDS = 1.15
VOCAL_ACTIVITY_LINE_LEAD_SECONDS = 0.65
VOCAL_ACTIVITY_LINE_TAIL_SECONDS = 0.35


def with_lyrics_alignment(lyrics: dict[str, Any] | None) -> dict[str, Any]:
    """Return a lyrics guide with canonical paint units for the coach renderer."""
    guide = dict(lyrics or {})
    alignment = guide.get("alignment")
    if _is_current_alignment(alignment):
        return guide
    guide["alignment"] = build_lyrics_alignment(guide)
    return guide


def with_vocal_activity_alignment(
    lyrics: dict[str, Any] | None,
    melody_guide: dict[str, Any] | None,
) -> dict[str, Any]:
    """Refine line-level lyric paint timing with the extracted vocal activity.

    LRC files usually use the next line's timestamp as the current line's end.
    That makes the visual paint too slow whenever the phrase ends before the
    next line starts. This keeps line-level text, but contracts each line's
    visual paint interval to the vocal span detected from the already-extracted
    melody contour.
    """
    guide = with_lyrics_alignment(lyrics)
    alignment = guide.get("alignment")
    if not _is_current_alignment(alignment):
        return guide
    if alignment.get("granularity") != "line":
        return guide

    activity_spans = _vocal_activity_spans(melody_guide or {})
    if not activity_spans:
        return guide

    refined_units, changed = _refine_line_units_with_activity(
        alignment.get("paint_units") or [],
        activity_spans,
    )

    if not changed:
        return guide

    refined_alignment = dict(alignment)
    refined_alignment["method"] = "line_timing_vocal_activity"
    refined_alignment["paint_units"] = refined_units
    refined_alignment["confidence"] = {
        **(alignment.get("confidence") or {}),
        "uses_vocal_activity": True,
        "vocal_activity_refined_units": changed,
    }
    guide["alignment"] = refined_alignment
    return guide


def build_lyrics_alignment(lyrics: dict[str, Any] | None) -> dict[str, Any]:
    """Build language-agnostic paint units from the best timing available.

    This is intentionally conservative: it only emits sub-line units when the
    source has real karaoke timing. Otherwise the renderer gets line-level
    units and never invents word timing in the browser.
    """
    guide = lyrics or {}
    lines = guide.get("lines") if isinstance(guide.get("lines"), list) else []
    status = guide.get("status") or ("ready" if lines else "missing")
    if status != "ready" or not lines:
        return {
            "schema": ALIGNMENT_SCHEMA,
            "version": ALIGNMENT_VERSION,
            "status": "missing",
            "method": "none",
            "language": "auto",
            "granularity": "none",
            "paint_units": [],
            "confidence": {"overall": 0.0},
        }

    has_karaoke_timing = bool(guide.get("has_karaoke_timing"))
    paint_units: list[dict[str, Any]] = []
    precise_units = 0
    for line_index, line in enumerate(lines):
        line_units, line_precise_units = _paint_units_for_line(
            line,
            line_index=line_index,
            use_segments=has_karaoke_timing,
        )
        paint_units.extend(line_units)
        precise_units += line_precise_units

    granularity = "segment" if precise_units else "line"
    method = "source_karaoke_timing" if precise_units else "line_timing_fallback"
    overall_confidence = float(guide.get("confidence") or 0.0)
    if not precise_units:
        overall_confidence = min(overall_confidence, 0.65)

    return {
        "schema": ALIGNMENT_SCHEMA,
        "version": ALIGNMENT_VERSION,
        "status": "ready" if paint_units else "missing",
        "method": method,
        "language": "auto",
        "granularity": granularity,
        "source": guide.get("source"),
        "source_format": guide.get("source_format"),
        "paint_units": paint_units,
        "confidence": {
            "overall": round(max(0.0, min(1.0, overall_confidence)), 3),
            "uses_source_karaoke_timing": bool(precise_units),
        },
    }


def _paint_units_for_line(
    line: dict[str, Any],
    *,
    line_index: int,
    use_segments: bool,
) -> tuple[list[dict[str, Any]], int]:
    line_start = _safe_float(line.get("start"))
    line_end = _safe_float(line.get("end"))
    line_text = re.sub(r"\s+", " ", str(line.get("text") or "")).strip()
    if line_start is None or line_end is None or line_end <= line_start or not line_text:
        return [], 0

    line_has_karaoke_timing = bool(line.get("has_karaoke_timing"))
    if use_segments and line_has_karaoke_timing and isinstance(line.get("segments"), list):
        units = []
        for segment_index, segment in enumerate(line["segments"]):
            unit = _paint_unit(
                segment,
                line_index=line_index,
                unit_index=segment_index,
                unit_type="segment",
                precision="source_karaoke",
            )
            if unit:
                units.append(unit)
        if units:
            return units, len(units)

    unit = {
        "start": round(line_start, 3),
        "end": round(line_end, 3),
        "text": line_text,
        "line_index": line_index,
        "unit_index": 0,
        "unit_type": "line",
        "precision": "line",
        "confidence": 0.65,
    }
    return [unit], 0


def _paint_unit(
    item: dict[str, Any],
    *,
    line_index: int,
    unit_index: int,
    unit_type: str,
    precision: str,
) -> dict[str, Any] | None:
    start = _safe_float(item.get("start"))
    end = _safe_float(item.get("end"))
    text = str(item.get("text") or "").strip()
    if start is None or end is None or end <= start or not text:
        return None
    return {
        "start": round(start, 3),
        "end": round(end, 3),
        "text": text,
        "line_index": line_index,
        "unit_index": unit_index,
        "unit_type": unit_type,
        "precision": precision,
        "confidence": 0.9,
    }


def _is_current_alignment(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("schema") == ALIGNMENT_SCHEMA
        and value.get("version") == ALIGNMENT_VERSION
        and isinstance(value.get("paint_units"), list)
    )


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _vocal_activity_spans(melody_guide: dict[str, Any]) -> list[tuple[float, float]]:
    intervals: list[tuple[float, float]] = []
    for point in melody_guide.get("contour") or []:
        time = _safe_float(point.get("time") if isinstance(point, dict) else None)
        confidence = _safe_float(point.get("confidence") if isinstance(point, dict) else None)
        if time is None or (confidence is not None and confidence < VOCAL_ACTIVITY_MIN_CONFIDENCE):
            continue
        intervals.append((time, time + 0.12))

    for note in melody_guide.get("notes") or []:
        if not isinstance(note, dict):
            continue
        start = _safe_float(note.get("start"))
        end = _safe_float(note.get("end"))
        confidence = _safe_float(note.get("confidence"))
        if (
            start is None
            or end is None
            or end <= start
            or (confidence is not None and confidence < VOCAL_ACTIVITY_MIN_CONFIDENCE)
        ):
            continue
        intervals.append((start, end))

    if not intervals:
        return []

    intervals.sort()
    merged = []
    current_start, current_end = intervals[0]
    for start, end in intervals[1:]:
        if start - current_end <= VOCAL_ACTIVITY_MAX_GAP_SECONDS:
            current_end = max(current_end, end)
            continue
        merged.append((round(current_start, 3), round(current_end, 3)))
        current_start, current_end = start, end
    merged.append((round(current_start, 3), round(current_end, 3)))
    return merged


def _refine_line_units_with_activity(
    paint_units: list[dict[str, Any]],
    activity_spans: list[tuple[float, float]],
) -> tuple[list[dict[str, Any]], int]:
    refined_units = []
    changed = 0
    for index, unit in enumerate(paint_units):
        if unit.get("unit_type") != "line":
            refined_units.append(unit)
            continue
        next_line_start = _next_line_unit_start(paint_units, index)
        refined = _refine_line_unit_with_activity(
            unit,
            activity_spans,
            next_line_start=next_line_start,
        )
        if refined != unit:
            changed += 1
        refined_units.append(refined)
    return refined_units, changed


def _refine_line_unit_with_activity(
    unit: dict[str, Any],
    activity_spans: list[tuple[float, float]],
    *,
    next_line_start: float | None = None,
) -> dict[str, Any]:
    start = _safe_float(unit.get("start"))
    end = _safe_float(unit.get("end"))
    if start is None or end is None or end <= start:
        return unit

    window_start = max(0.0, start - VOCAL_ACTIVITY_LINE_LEAD_SECONDS)
    window_end = max(start, end - 0.08)
    candidates = [
        (span_start, span_end)
        for span_start, span_end in activity_spans
        if span_end >= window_start and span_start < window_end
    ]
    candidates = _line_activity_candidates(candidates, start, next_line_start)
    if not candidates:
        return unit

    first_start = candidates[0][0]
    last_end = candidates[-1][1]
    refined_start = start
    if first_start < start and start - first_start <= VOCAL_ACTIVITY_LINE_LEAD_SECONDS:
        refined_start = max(0.0, first_start - 0.03)

    min_duration = min(end - refined_start, max(0.85, len(str(unit.get("text") or "")) * 0.045))
    end_cap = end
    if next_line_start is not None and next_line_start > refined_start:
        end_cap = min(end_cap, max(refined_start + 0.35, next_line_start - 0.05))
    candidate_end = min(end_cap, last_end + VOCAL_ACTIVITY_LINE_TAIL_SECONDS)
    refined_end = min(end_cap, max(refined_start + min_duration, candidate_end))
    if abs(refined_start - start) < 0.08 and abs(refined_end - end) < 0.2:
        return unit

    refined = dict(unit)
    refined["source_start"] = round(start, 3)
    refined["source_end"] = round(end, 3)
    refined["start"] = round(refined_start, 3)
    refined["end"] = round(refined_end, 3)
    refined["precision"] = "line_vocal_activity"
    refined["confidence"] = max(float(refined.get("confidence") or 0.65), 0.72)
    return refined


def _next_line_unit_start(paint_units: list[dict[str, Any]], current_index: int) -> float | None:
    for unit in paint_units[current_index + 1 :]:
        if unit.get("unit_type") != "line":
            continue
        start = _safe_float(unit.get("start"))
        if start is not None:
            return start
    return None


def _line_activity_candidates(
    candidates: list[tuple[float, float]],
    line_start: float,
    next_line_start: float | None,
) -> list[tuple[float, float]]:
    usable = []
    for span_start, span_end in candidates:
        if span_start < line_start - VOCAL_ACTIVITY_LINE_LEAD_SECONDS and span_end < line_start + 0.25:
            continue
        if next_line_start is not None and span_start >= next_line_start - 0.6:
            continue
        usable.append((span_start, span_end))
    return usable

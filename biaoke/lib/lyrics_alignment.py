"""Canonical lyric alignment units for the vocal coach renderer."""

from __future__ import annotations

import re
from typing import Any


ALIGNMENT_SCHEMA = "biaoke.lyrics_alignment"
ALIGNMENT_VERSION = 1


def with_lyrics_alignment(lyrics: dict[str, Any] | None) -> dict[str, Any]:
    """Return a lyrics guide with canonical paint units for the coach renderer."""
    guide = dict(lyrics or {})
    alignment = guide.get("alignment")
    if _is_current_alignment(alignment):
        return guide
    guide["alignment"] = build_lyrics_alignment(guide)
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

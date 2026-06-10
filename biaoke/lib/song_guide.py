"""Persistent per-song guide packages for Biaoke coach mode."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from biaoke.lib.ffmpeg import get_media_duration
from biaoke.lib.file_resolver import find_ass_subtitle_for_media
from biaoke.lib.lyrics import build_lyrics_guide_from_ass
from biaoke.lib.lyrics_alignment import with_lyrics_alignment
from biaoke.lib.lyrics_sources import find_external_lyrics_for_media, infer_song_identity

GUIDE_SCHEMA = "biaoke.song_guide"
GUIDE_VERSION = 3
GUIDE_SUFFIX = ".biaoke-guide.json"
MAX_LYRICS_OFFSET_SECONDS = 120.0


def guide_path_for_media(media_path: str | Path) -> Path:
    """Return the sidecar guide path for a media file."""
    return Path(media_path).with_suffix(GUIDE_SUFFIX)


def load_song_guide(media_path: str | Path) -> dict[str, Any] | None:
    """Load a guide package if it exists and is valid JSON."""
    path = guide_path_for_media(media_path)
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def build_song_guide(media_path: str | Path) -> dict[str, Any]:
    """Build a guide package from the media file and available sidecars."""
    media = Path(media_path)
    duration_seconds = get_media_duration(str(media))
    identity = infer_song_identity(media, duration_seconds=duration_seconds)
    subtitle = find_ass_subtitle_for_media(str(media))
    subtitle_meta = _file_metadata(Path(subtitle)) if subtitle else None

    if subtitle:
        lyrics = build_lyrics_guide_from_ass(subtitle)
    else:
        lyrics = find_external_lyrics_for_media(media, duration_seconds=duration_seconds)
        if not lyrics:
            lyrics = {
                "status": "missing",
                "source": "none",
                "source_format": None,
                "confidence": 0,
                "has_karaoke_timing": False,
                "line_count": 0,
                "lines": [],
                "message": "Letra sincronizada ainda nao foi gerada para esta musica.",
            }

    lyrics = with_lyrics_alignment(lyrics)

    messages = []
    if lyrics.get("status") != "ready":
        messages.append("lyrics_missing")
    elif not lyrics.get("has_karaoke_timing"):
        messages.append("lyrics_line_timing_only")

    return {
        "schema": GUIDE_SCHEMA,
        "version": GUIDE_VERSION,
        "created_at": _utc_now(),
        "media": _file_metadata(media),
        "metadata": identity,
        "subtitle": subtitle_meta,
        "adjustments": _default_adjustments(),
        "lyrics": lyrics,
        "quality": {
            "status": "ready" if lyrics.get("status") == "ready" else "needs_lyrics",
            "lyrics_ready": lyrics.get("status") == "ready",
            "has_karaoke_timing": bool(lyrics.get("has_karaoke_timing")),
            "messages": messages,
        },
    }


def write_song_guide(media_path: str | Path) -> dict[str, Any]:
    """Build and write a guide package atomically."""
    existing = load_song_guide(media_path)
    guide = build_song_guide(media_path)
    guide["adjustments"] = _guide_adjustments(existing)
    _write_song_guide(media_path, guide)
    return guide


def set_lyrics_offset(media_path: str | Path, offset_seconds: float) -> dict[str, Any]:
    """Persist a per-song lyrics timing offset in seconds."""
    guide = ensure_song_guide(media_path)
    guide["adjustments"] = _guide_adjustments(guide)
    guide["adjustments"]["lyrics_offset_seconds"] = _clamp_offset(offset_seconds)
    guide["updated_at"] = _utc_now()
    _write_song_guide(media_path, guide)
    return guide


def get_lyrics_offset(guide: dict[str, Any] | None) -> float:
    """Return the lyrics timing offset from a guide package."""
    return _guide_adjustments(guide)["lyrics_offset_seconds"]


def _write_song_guide(media_path: str | Path, guide: dict[str, Any]) -> None:
    path = guide_path_for_media(media_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(guide, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_path, path)


def ensure_song_guide(media_path: str | Path, rebuild: bool = False) -> dict[str, Any]:
    """Return an existing fresh guide package, or rebuild it."""
    if not rebuild:
        guide = load_song_guide(media_path)
        if guide and not is_song_guide_stale(media_path, guide):
            return guide
    return write_song_guide(media_path)


def is_song_guide_stale(media_path: str | Path, guide: dict[str, Any] | None = None) -> bool:
    """Return True when the package no longer matches media or subtitle files."""
    media = Path(media_path)
    if guide is None:
        guide = load_song_guide(media)
    if not guide:
        return True

    if guide.get("schema") != GUIDE_SCHEMA or guide.get("version") != GUIDE_VERSION:
        return True

    if _fingerprint(guide.get("media")) != _fingerprint(_file_metadata(media)):
        return True

    subtitle = find_ass_subtitle_for_media(str(media))
    current_subtitle_meta = _file_metadata(Path(subtitle)) if subtitle else None
    return _fingerprint(guide.get("subtitle")) != _fingerprint(current_subtitle_meta)


def _file_metadata(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "basename": path.name,
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }


def _fingerprint(metadata: dict[str, Any] | None) -> tuple[Any, Any, Any] | None:
    if not metadata:
        return None
    return (metadata.get("basename"), metadata.get("mtime_ns"), metadata.get("size"))


def _default_adjustments() -> dict[str, Any]:
    return {"lyrics_offset_seconds": 0.0}


def _guide_adjustments(guide: dict[str, Any] | None) -> dict[str, Any]:
    adjustments = _default_adjustments()
    if isinstance(guide, dict) and isinstance(guide.get("adjustments"), dict):
        adjustments.update(guide["adjustments"])
    adjustments["lyrics_offset_seconds"] = _clamp_offset(
        adjustments.get("lyrics_offset_seconds", 0)
    )
    return adjustments


def _clamp_offset(value: Any) -> float:
    try:
        offset = float(value)
    except (TypeError, ValueError):
        offset = 0.0
    return round(max(-MAX_LYRICS_OFFSET_SECONDS, min(MAX_LYRICS_OFFSET_SECONDS, offset)), 3)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

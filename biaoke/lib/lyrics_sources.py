"""External synchronized lyrics providers."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import requests

from biaoke.lib.ffmpeg import get_media_duration
from biaoke.lib.lyrics import build_lyrics_guide_from_lrc
from biaoke.lib.metadata_parser import regex_tidy, remove_accents, youtube_id_suffix
from biaoke.version import __version__

LRCLIB_BASE_URL_ENV = "BIAOKE_LRCLIB_BASE_URL"
LRCLIB_TIMEOUT_ENV = "BIAOKE_LRCLIB_TIMEOUT"
DISABLE_EXTERNAL_LYRICS_ENV = "BIAOKE_DISABLE_EXTERNAL_LYRICS"
DEFAULT_LRCLIB_BASE_URL = "https://lrclib.net"
DEFAULT_LRCLIB_TIMEOUT_SECONDS = 10
LRCLIB_USER_AGENT = f"Biaoke/{__version__} (https://github.com/vicwomg/biaoke)"


def find_external_lyrics_for_media(
    media_path: str | Path,
    *,
    duration_seconds: int | float | None = None,
) -> dict[str, Any] | None:
    """Return the best external synchronized lyrics guide for a media file."""
    if _truthy(os.environ.get(DISABLE_EXTERNAL_LYRICS_ENV)):
        return None

    try:
        return find_lrclib_lyrics_for_media(media_path, duration_seconds=duration_seconds)
    except Exception as exc:
        logging.warning("External lyrics lookup failed for %s: %s", media_path, exc)
        return None


def find_lrclib_lyrics_for_media(
    media_path: str | Path,
    *,
    duration_seconds: int | float | None = None,
) -> dict[str, Any] | None:
    """Search LRCLIB for synchronized LRC lyrics matching a media file."""
    identity = infer_song_identity(media_path, duration_seconds=duration_seconds)
    if not identity.get("query"):
        return None

    results = _search_lrclib(identity)
    best = _select_lrclib_result(results, identity)
    if not best:
        logging.info("LRCLIB did not find synced lyrics for %s", identity["query"])
        return None

    synced_lyrics = _field(best, "syncedLyrics", "synced_lyrics")
    if not synced_lyrics:
        return None

    confidence = _lrclib_confidence(best, identity)
    source_metadata = {
        "provider": "lrclib",
        "id": best.get("id"),
        "track_name": _field(best, "trackName", "track_name", "name"),
        "artist_name": _field(best, "artistName", "artist_name"),
        "album_name": _field(best, "albumName", "album_name"),
        "duration": _field(best, "duration"),
        "match_confidence": confidence,
    }
    return build_lyrics_guide_from_lrc(
        synced_lyrics,
        source="lrclib",
        duration_seconds=identity.get("duration_seconds"),
        confidence=confidence,
        source_metadata=source_metadata,
    )


def infer_song_identity(
    media_path: str | Path,
    *,
    duration_seconds: int | float | None = None,
) -> dict[str, Any]:
    """Infer searchable artist/title metadata from a downloaded song filename."""
    path = Path(media_path)
    stem = path.stem
    suffix = youtube_id_suffix(path.name)
    if suffix:
        stem = stem[: -len(suffix)]

    query = regex_tidy(stem) or stem
    artist_name = None
    track_name = query
    parts = re.split(r"\s+-\s+", query, maxsplit=1)
    if len(parts) == 2:
        artist_name, track_name = parts[0].strip(), parts[1].strip()

    if duration_seconds is None and path.exists():
        duration_seconds = get_media_duration(str(path))

    return {
        "query": query.strip(),
        "artist_name": artist_name,
        "track_name": track_name.strip(),
        "duration_seconds": duration_seconds,
    }


def _search_lrclib(identity: dict[str, Any]) -> list[dict[str, Any]]:
    base_url = (os.environ.get(LRCLIB_BASE_URL_ENV) or DEFAULT_LRCLIB_BASE_URL).rstrip("/")
    url = f"{base_url}/api/search"
    headers = {"User-Agent": LRCLIB_USER_AGENT}
    requests_to_try = []

    track = identity.get("track_name")
    artist = identity.get("artist_name")
    if track and artist:
        requests_to_try.append({"track_name": track, "artist_name": artist})
        requests_to_try.append({"track_name": artist, "artist_name": track})
    requests_to_try.append({"q": identity.get("query")})

    results = []
    seen = set()
    for params in requests_to_try:
        if not params.get("q") and not params.get("track_name"):
            continue
        try:
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=_lrclib_timeout_seconds(),
            )
            if response.status_code == 404:
                continue
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            logging.info("LRCLIB lookup failed for %s: %s", params, exc)
            continue
        except ValueError as exc:
            logging.info("LRCLIB returned invalid JSON for %s: %s", params, exc)
            continue

        if not isinstance(payload, list):
            continue
        for item in payload:
            if not isinstance(item, dict):
                continue
            key = item.get("id") or (
                _field(item, "trackName", "track_name", "name"),
                _field(item, "artistName", "artist_name"),
                _field(item, "duration"),
            )
            if key in seen:
                continue
            seen.add(key)
            results.append(item)

        best = _select_lrclib_result(results, identity)
        if best and _score_lrclib_result(best, identity) >= 70:
            return results

    return results


def _select_lrclib_result(
    results: list[dict[str, Any]], identity: dict[str, Any]
) -> dict[str, Any] | None:
    synced = [item for item in results if _field(item, "syncedLyrics", "synced_lyrics")]
    if not synced:
        return None

    best = max(synced, key=lambda item: _score_lrclib_result(item, identity))
    if _score_lrclib_result(best, identity) < 35:
        return None
    return best


def _score_lrclib_result(item: dict[str, Any], identity: dict[str, Any]) -> float:
    score = 0.0
    wanted_track = _normalize(identity.get("track_name"))
    wanted_artist = _normalize(identity.get("artist_name"))
    wanted_query = _normalize(identity.get("query"))
    result_track = _normalize(_field(item, "trackName", "track_name", "name"))
    result_artist = _normalize(_field(item, "artistName", "artist_name"))

    if result_track and result_track == wanted_track:
        score += 45
    elif result_track and (result_track in wanted_query or wanted_track in result_track):
        score += 24

    if wanted_artist and result_artist == wanted_artist:
        score += 35
    elif wanted_artist and result_artist and (
        result_artist in wanted_artist or wanted_artist in result_artist
    ):
        score += 18

    duration = identity.get("duration_seconds")
    result_duration = _field(item, "duration")
    if duration and result_duration:
        diff = abs(float(duration) - float(result_duration))
        if diff <= 3:
            score += 25
        elif diff <= 8:
            score += 16
        elif diff <= 15:
            score += 8
        else:
            score -= min(30, diff / 2)

    return score


def _lrclib_confidence(item: dict[str, Any], identity: dict[str, Any]) -> float:
    score = _score_lrclib_result(item, identity)
    if score >= 95:
        return 0.88
    if score >= 70:
        return 0.8
    return 0.68


def _normalize(value: Any) -> str:
    value = remove_accents(str(value or "").casefold())
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _field(item: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in item and item[name] not in ("", None):
            return item[name]
    return None


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _lrclib_timeout_seconds() -> float:
    try:
        return max(2.0, float(os.environ.get(LRCLIB_TIMEOUT_ENV) or DEFAULT_LRCLIB_TIMEOUT_SECONDS))
    except ValueError:
        return DEFAULT_LRCLIB_TIMEOUT_SECONDS

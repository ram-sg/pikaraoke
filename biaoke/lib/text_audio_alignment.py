"""Align canonical lyrics to timestamped transcript words."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import unicodedata
from typing import Any

from biaoke.lib.lyrics_alignment import ALIGNMENT_SCHEMA, ALIGNMENT_VERSION


MIN_WORD_MATCH_SCORE = 0.58


@dataclass(frozen=True)
class LyricToken:
    text: str
    normalized: str
    line_index: int
    token_index: int
    line_token_count: int
    line_start: float
    line_end: float
    approx_time: float


@dataclass(frozen=True)
class TranscriptToken:
    text: str
    normalized: str
    start: float
    end: float
    confidence: float
    index: int


def build_word_alignment_from_transcript(
    lyrics: dict[str, Any] | None,
    transcript_words: list[dict[str, Any]],
    *,
    method: str = "transcript_word_alignment",
) -> dict[str, Any] | None:
    """Build canonical word paint units by matching lyrics to transcript timestamps.

    The alignment is monotonic: lyric words can only match transcript words in
    forward order. This handles repeated choruses better than local nearest-word
    matching and avoids letting late-song drift compound silently.
    """
    lyric_tokens = _lyrics_tokens(lyrics)
    transcript_tokens = _transcript_tokens(transcript_words)
    if not lyric_tokens or not transcript_tokens:
        return None

    initial_matches = _monotonic_matches(lyric_tokens, transcript_tokens, use_temporal=False)
    global_offset = _estimate_global_offset_from_matches(initial_matches) or _estimate_global_offset(
        lyric_tokens,
        transcript_tokens,
    )
    initial_coverage = _matched_count(initial_matches) / max(len(lyric_tokens), 1)
    use_temporal = initial_coverage < 0.75
    matches = (
        _monotonic_matches(lyric_tokens, transcript_tokens, global_offset=global_offset)
        if use_temporal
        else initial_matches
    )
    matches = _remove_line_time_outliers(matches)
    if not matches:
        return None

    matched_count = 0
    matched_tokens: dict[tuple[int, int], tuple[TranscriptToken, float]] = {}
    for lyric_token, transcript_token, score in matches:
        if transcript_token is None:
            continue
        matched_count += 1
        matched_tokens[(lyric_token.line_index, lyric_token.token_index)] = (transcript_token, score)

    coverage = matched_count / max(len(lyric_tokens), 1)
    if coverage < 0.35:
        return None
    paint_units = _paint_units_from_matches(lyric_tokens, matched_tokens, global_offset)

    return {
        "schema": ALIGNMENT_SCHEMA,
        "version": ALIGNMENT_VERSION,
        "status": "ready",
        "method": method,
        "language": "auto",
        "granularity": "word",
        "paint_units": paint_units,
        "confidence": {
            "overall": round(coverage, 3),
            "matched_words": matched_count,
            "estimated_words": len(paint_units) - matched_count,
            "total_words": len(lyric_tokens),
            "global_offset_seconds": round(global_offset, 3) if global_offset is not None else None,
        },
    }


def _lyrics_tokens(lyrics: dict[str, Any] | None) -> list[LyricToken]:
    guide = lyrics or {}
    lines = guide.get("lines") if isinstance(guide.get("lines"), list) else []
    tokens = []
    for line_index, line in enumerate(lines):
        if not isinstance(line, dict):
            continue
        line_start = _safe_float(line.get("start"))
        line_end = _safe_float(line.get("end"))
        if line_start is None or line_end is None or line_end <= line_start:
            continue
        line_tokens = _tokenize_text(str(line.get("text") or ""))
        token_count = len(line_tokens)
        for token_index, text in enumerate(line_tokens):
            normalized = _normalize_token(text)
            if not normalized:
                continue
            approx_time = _approx_token_time(line_start, line_end, token_index, token_count)
            tokens.append(
                LyricToken(
                    text=text,
                    normalized=normalized,
                    line_index=line_index,
                    token_index=token_index,
                    line_token_count=token_count,
                    line_start=line_start,
                    line_end=line_end,
                    approx_time=approx_time,
                )
            )
    return tokens


def _transcript_tokens(words: list[dict[str, Any]]) -> list[TranscriptToken]:
    tokens = []
    for index, item in enumerate(words or []):
        if not isinstance(item, dict):
            continue
        start = _safe_float(item.get("start"))
        end = _safe_float(item.get("end"))
        if start is None or end is None or end <= start:
            continue
        text = str(item.get("word") or item.get("text") or "").strip()
        normalized = _normalize_token(text)
        if not normalized:
            continue
        confidence = _safe_float(item.get("confidence") or item.get("probability")) or 0.75
        tokens.append(
            TranscriptToken(
                text=text,
                normalized=normalized,
                start=start,
                end=end,
                confidence=max(0.0, min(1.0, confidence)),
                index=index,
            )
        )
    return tokens


def _monotonic_matches(
    lyric_tokens: list[LyricToken],
    transcript_tokens: list[TranscriptToken],
    *,
    global_offset: float | None = None,
    use_temporal: bool = True,
) -> list[tuple[LyricToken, TranscriptToken | None, float]]:
    n = len(lyric_tokens)
    m = len(transcript_tokens)
    gap_penalty = -0.34
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    back: list[list[tuple[str, int, int, float] | None]] = [[None] * (m + 1) for _ in range(n + 1)]

    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + gap_penalty
        back[i][0] = ("skip_lyric", i - 1, 0, 0.0)
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + gap_penalty * 0.25
        back[0][j] = ("skip_transcript", 0, j - 1, 0.0)

    for i in range(1, n + 1):
        lyric = lyric_tokens[i - 1]
        for j in range(1, m + 1):
            transcript = transcript_tokens[j - 1]
            score = _token_similarity(lyric.normalized, transcript.normalized)
            temporal_score = _temporal_match_score(lyric, transcript, global_offset) if use_temporal else 1.0
            if score >= MIN_WORD_MATCH_SCORE and temporal_score > 0:
                match_delta = score + 0.24 * temporal_score
            else:
                match_delta = -0.72 if score >= MIN_WORD_MATCH_SCORE and temporal_score <= 0 else -0.52
            match_score = dp[i - 1][j - 1] + match_delta
            skip_lyric = dp[i - 1][j] + gap_penalty
            skip_transcript = dp[i][j - 1] + gap_penalty * 0.25
            best = max(match_score, skip_lyric, skip_transcript)
            dp[i][j] = best
            if best == match_score:
                back[i][j] = ("match", i - 1, j - 1, score)
            elif best == skip_lyric:
                back[i][j] = ("skip_lyric", i - 1, j, 0.0)
            else:
                back[i][j] = ("skip_transcript", i, j - 1, 0.0)

    matches: list[tuple[LyricToken, TranscriptToken | None, float]] = []
    i, j = n, m
    while i > 0 or j > 0:
        step = back[i][j]
        if step is None:
            break
        action, prev_i, prev_j, score = step
        if action == "match":
            lyric = lyric_tokens[i - 1]
            transcript = transcript_tokens[j - 1]
            temporal_ok = not use_temporal or _temporal_match_score(lyric, transcript, global_offset) > 0
            if score >= MIN_WORD_MATCH_SCORE and temporal_ok:
                matches.append((lyric, transcript, score))
            else:
                matches.append((lyric, None, 0.0))
        elif action == "skip_lyric":
            matches.append((lyric_tokens[i - 1], None, 0.0))
        i, j = prev_i, prev_j

    matches.reverse()
    return matches


def _paint_units_from_matches(
    lyric_tokens: list[LyricToken],
    matched_tokens: dict[tuple[int, int], tuple[TranscriptToken, float]],
    global_offset: float | None,
) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    lines: dict[int, list[LyricToken]] = {}
    for token in lyric_tokens:
        lines.setdefault(token.line_index, []).append(token)

    for line_index in sorted(lines):
        line_tokens = sorted(lines[line_index], key=lambda token: token.token_index)
        line_units: list[dict[str, Any] | None] = [None] * len(line_tokens)
        matched_indexes = []
        for local_index, token in enumerate(line_tokens):
            match = matched_tokens.get((token.line_index, token.token_index))
            if not match:
                continue
            transcript_token, score = match
            line_units[local_index] = _word_paint_unit(
                token,
                start=transcript_token.start,
                end=max(transcript_token.end, transcript_token.start + 0.08),
                precision="transcript_word",
                confidence=min(transcript_token.confidence, score),
            )
            matched_indexes.append(local_index)

        if len(matched_indexes) < len(line_tokens):
            _fill_missing_line_units(line_tokens, line_units, global_offset)

        _normalize_line_unit_order(line_units)
        units.extend(unit for unit in line_units if unit)

    _normalize_paint_unit_timeline(units)
    return units


def _normalize_line_unit_order(line_units: list[dict[str, Any] | None]) -> None:
    previous_end: float | None = None
    for index, unit in enumerate(line_units):
        if unit is None:
            continue
        start = _safe_float(unit.get("start"))
        end = _safe_float(unit.get("end"))
        if start is None or end is None:
            continue
        normalized = dict(unit)
        if previous_end is not None and start < previous_end:
            start = previous_end
            if end <= start:
                end = start + 0.08
            normalized["start"] = round(start, 3)
            normalized["end"] = round(end, 3)
            line_units[index] = normalized
        previous_end = max(end, start + 0.08)


def _normalize_paint_unit_timeline(units: list[dict[str, Any]]) -> None:
    """Keep the rendered lyric timeline monotonic without moving reliable words first."""
    previous_unit: dict[str, Any] | None = None
    for unit in units:
        start = _safe_float(unit.get("start"))
        end = _safe_float(unit.get("end"))
        if start is None or end is None:
            continue
        if previous_unit is None:
            previous_unit = unit
            continue

        previous_start = _safe_float(previous_unit.get("start"))
        previous_end = _safe_float(previous_unit.get("end"))
        if previous_start is None or previous_end is None or start >= previous_end:
            previous_unit = unit
            continue

        minimum_duration = 0.08
        if _unit_timing_is_estimated(previous_unit) and start >= previous_start + minimum_duration:
            previous_unit["end"] = round(start, 3)
        else:
            unit["start"] = round(previous_end, 3)
            if end <= previous_end + minimum_duration:
                unit["end"] = round(previous_end + minimum_duration, 3)
        previous_unit = unit


def _unit_timing_is_estimated(unit: dict[str, Any]) -> bool:
    precision = str(unit.get("precision") or "")
    confidence = _safe_float(unit.get("confidence")) or 0.0
    return "interpolated" in precision or precision == "estimated_word" or confidence <= 0.5


def _remove_line_time_outliers(
    matches: list[tuple[LyricToken, TranscriptToken | None, float]],
) -> list[tuple[LyricToken, TranscriptToken | None, float]]:
    cleaned = list(matches)
    by_line: dict[int, list[tuple[int, LyricToken, TranscriptToken]]] = {}
    for index, (lyric, transcript, score) in enumerate(matches):
        if transcript is None or score < MIN_WORD_MATCH_SCORE:
            continue
        by_line.setdefault(lyric.line_index, []).append((index, lyric, transcript))

    outlier_indexes: set[int] = set()
    for line_matches in by_line.values():
        line_matches.sort(key=lambda item: item[1].token_index)
        if len(line_matches) < 2:
            continue
        for local_index, (match_index, lyric, transcript) in enumerate(line_matches[:-1]):
            next_match_index, next_lyric, next_transcript = line_matches[local_index + 1]
            gap = next_transcript.start - transcript.end
            line_duration = max(0.5, lyric.line_end - lyric.line_start)
            max_reasonable_gap = max(4.0, line_duration * 1.25)
            if gap <= max_reasonable_gap:
                continue
            if local_index == 0:
                outlier_indexes.add(match_index)
            elif local_index + 1 == len(line_matches) - 1:
                outlier_indexes.add(next_match_index)

    for index in outlier_indexes:
        lyric, _transcript, _score = cleaned[index]
        cleaned[index] = (lyric, None, 0.0)
    return cleaned


def _fill_missing_line_units(
    line_tokens: list[LyricToken],
    line_units: list[dict[str, Any] | None],
    global_offset: float | None,
) -> None:
    line_start = line_tokens[0].line_start + (global_offset or 0.0)
    line_end = line_tokens[0].line_end + (global_offset or 0.0)
    index = 0
    while index < len(line_tokens):
        if line_units[index] is not None:
            index += 1
            continue

        run_start = index
        while index + 1 < len(line_tokens) and line_units[index + 1] is None:
            index += 1
        run_end = index

        missing_count = run_end - run_start + 1
        previous_unit = line_units[run_start - 1] if run_start > 0 else None
        next_unit = line_units[run_end + 1] if run_end + 1 < len(line_units) else None
        previous_end = _safe_float(previous_unit.get("end")) if previous_unit else None
        next_start = _safe_float(next_unit.get("start")) if next_unit else None
        minimum_duration = 0.08 * missing_count

        if previous_end is not None and next_start is not None:
            start_boundary = previous_end
            end_boundary = next_start
        elif previous_end is not None:
            start_boundary = previous_end
            end_boundary = max(line_end, previous_end + minimum_duration)
        elif next_start is not None:
            end_boundary = next_start
            start_boundary = min(line_start, next_start - minimum_duration)
        else:
            start_boundary = line_start
            end_boundary = max(line_end, line_start + minimum_duration)

        if end_boundary <= start_boundary:
            if next_start is not None:
                end_boundary = next_start
                start_boundary = max(0.0, next_start - minimum_duration)
            else:
                end_boundary = start_boundary + minimum_duration

        slot = max(0.08, (end_boundary - start_boundary) / missing_count)
        for unit_index in range(run_start, run_end + 1):
            local_index = unit_index - run_start
            start = start_boundary + slot * local_index
            end = min(end_boundary, start_boundary + slot * (local_index + 1))
            if end <= start:
                end = start + 0.08
            line_units[unit_index] = _word_paint_unit(
                line_tokens[unit_index],
                start=start,
                end=end,
                precision="transcript_interpolated_word",
                confidence=0.42,
            )
        index = run_end + 1


def _word_paint_unit(
    token: LyricToken,
    *,
    start: float,
    end: float,
    precision: str,
    confidence: float,
) -> dict[str, Any]:
    return {
        "start": round(start, 3),
        "end": round(max(end, start + 0.08), 3),
        "text": token.text,
        "line_index": token.line_index,
        "unit_index": token.token_index,
        "unit_type": "word",
        "precision": precision,
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
        "source_start": round(token.line_start, 3),
        "source_end": round(token.line_end, 3),
    }


def _matched_count(matches: list[tuple[LyricToken, TranscriptToken | None, float]]) -> int:
    return sum(1 for _, transcript, score in matches if transcript is not None and score >= MIN_WORD_MATCH_SCORE)


def _estimate_global_offset_from_matches(
    matches: list[tuple[LyricToken, TranscriptToken | None, float]],
) -> float | None:
    bins: dict[float, float] = {}
    bin_counts: dict[float, int] = {}
    samples: list[tuple[float, float, float]] = []
    for lyric, transcript, score in matches:
        if transcript is None or score < 0.8 or len(lyric.normalized) < 3:
            continue
        weight = score * transcript.confidence * min(1.0, len(lyric.normalized) / 8)
        offset = transcript.start - lyric.approx_time
        bin_key = round(offset * 2) / 2
        bins[bin_key] = bins.get(bin_key, 0.0) + weight
        bin_counts[bin_key] = bin_counts.get(bin_key, 0) + 1
        samples.append((bin_key, offset, weight))

    if not bins:
        return None
    supported_bins = {
        bin_key: weight
        for bin_key, weight in bins.items()
        if bin_counts.get(bin_key, 0) >= 2
    }
    if not supported_bins:
        return None
    best_bin = max(supported_bins.items(), key=lambda item: item[1])[0]
    selected = [
        (offset, weight)
        for bin_key, offset, weight in samples
        if abs(bin_key - best_bin) <= 0.5
    ]
    total_weight = sum(weight for _, weight in selected)
    if total_weight <= 0:
        return best_bin
    return sum(offset * weight for offset, weight in selected) / total_weight


def _offset_consistency(
    matches: list[tuple[LyricToken, TranscriptToken | None, float]],
    global_offset: float | None,
) -> float:
    if global_offset is None:
        return 0.0
    total_weight = 0.0
    consistent_weight = 0.0
    for lyric, transcript, score in matches:
        if transcript is None or score < MIN_WORD_MATCH_SCORE:
            continue
        weight = max(0.05, score * transcript.confidence)
        total_weight += weight
        if abs((transcript.start - lyric.approx_time) - global_offset) <= 2.0:
            consistent_weight += weight
    if total_weight <= 0:
        return 0.0
    return consistent_weight / total_weight


def _estimate_global_offset(
    lyric_tokens: list[LyricToken],
    transcript_tokens: list[TranscriptToken],
) -> float | None:
    lyric_frequency: dict[str, int] = {}
    for token in lyric_tokens:
        lyric_frequency[token.normalized] = lyric_frequency.get(token.normalized, 0) + 1

    bins: dict[float, float] = {}
    bin_counts: dict[float, int] = {}
    samples: list[tuple[float, float, float]] = []
    for lyric in lyric_tokens:
        if len(lyric.normalized) < 3:
            continue
        for transcript in transcript_tokens:
            score = _token_similarity(lyric.normalized, transcript.normalized)
            if score < 0.86:
                continue
            rarity = 1 / max(1, lyric_frequency.get(lyric.normalized, 1)) ** 0.5
            length_weight = min(1.0, len(lyric.normalized) / 8)
            weight = score * transcript.confidence * rarity * length_weight
            offset = transcript.start - lyric.approx_time
            bin_key = round(offset * 2) / 2
            bins[bin_key] = bins.get(bin_key, 0.0) + weight
            bin_counts[bin_key] = bin_counts.get(bin_key, 0) + 1
            samples.append((bin_key, offset, weight))

    if not bins:
        return None
    supported_bins = {
        bin_key: weight
        for bin_key, weight in bins.items()
        if bin_counts.get(bin_key, 0) >= 2
    }
    if not supported_bins and len(samples) >= 2:
        return None
    best_bin = max((supported_bins or bins).items(), key=lambda item: item[1])[0]
    selected = [
        (offset, weight)
        for bin_key, offset, weight in samples
        if abs(bin_key - best_bin) <= 0.5
    ]
    total_weight = sum(weight for _, weight in selected)
    if total_weight <= 0:
        return best_bin
    return sum(offset * weight for offset, weight in selected) / total_weight


def _temporal_match_score(
    lyric: LyricToken,
    transcript: TranscriptToken,
    global_offset: float | None,
) -> float:
    effective_offset = global_offset if global_offset is not None else 0.0

    line_duration = max(0.5, lyric.line_end - lyric.line_start)
    guard = max(1.15, min(2.4, line_duration * 0.35))
    shifted_start = lyric.line_start + effective_offset - guard
    shifted_end = lyric.line_end + effective_offset + guard
    if transcript.start < shifted_start:
        outside = shifted_start - transcript.start
    elif transcript.start > shifted_end:
        outside = transcript.start - shifted_end
    else:
        expected = lyric.approx_time + effective_offset
        delta = abs(transcript.start - expected)
        return max(0.35, 1.0 - delta / max(2.5, line_duration))

    if outside > max(2.0, guard):
        return 0.0
    return max(0.0, 1.0 - outside / max(2.0, guard))


def _tokenize_text(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    if " " not in text and _contains_cjk(text):
        return [char for char in text if not char.isspace()]
    return re.findall(r"[^\W_]+(?:['’][^\W_]+)*", text, flags=re.UNICODE)


def _approx_token_time(line_start: float, line_end: float, token_index: int, token_count: int) -> float:
    if token_count <= 1:
        return line_start
    line_duration = max(0.0, line_end - line_start)
    return line_start + line_duration * (token_index / max(1, token_count))


def _normalize_token(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text or "").casefold())
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return "".join(char for char in stripped if char.isalnum())


def _contains_cjk(text: str) -> bool:
    return any(
        "\u3040" <= char <= "\u30ff"
        or "\u3400" <= char <= "\u4dbf"
        or "\u4e00" <= char <= "\u9fff"
        or "\uf900" <= char <= "\ufaff"
        for char in text
    )


def _token_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return min(len(left), len(right)) / max(len(left), len(right))
    return SequenceMatcher(None, left, right).ratio()


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

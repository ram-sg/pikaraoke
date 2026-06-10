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
    line_start: float
    line_end: float


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

    matches = _monotonic_matches(lyric_tokens, transcript_tokens)
    if not matches:
        return None

    paint_units = []
    matched_count = 0
    for lyric_token, transcript_token, score in matches:
        if transcript_token is None:
            continue
        matched_count += 1
        paint_units.append(
            {
                "start": round(transcript_token.start, 3),
                "end": round(max(transcript_token.end, transcript_token.start + 0.08), 3),
                "text": lyric_token.text,
                "line_index": lyric_token.line_index,
                "unit_index": lyric_token.token_index,
                "unit_type": "word",
                "precision": "transcript_word",
                "confidence": round(min(transcript_token.confidence, score), 3),
                "source_start": round(lyric_token.line_start, 3),
                "source_end": round(lyric_token.line_end, 3),
            }
        )

    coverage = matched_count / max(len(lyric_tokens), 1)
    if coverage < 0.35:
        return None

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
            "total_words": len(lyric_tokens),
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
        for token_index, text in enumerate(_tokenize_text(str(line.get("text") or ""))):
            normalized = _normalize_token(text)
            if not normalized:
                continue
            tokens.append(
                LyricToken(
                    text=text,
                    normalized=normalized,
                    line_index=line_index,
                    token_index=token_index,
                    line_start=line_start,
                    line_end=line_end,
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
            match_score = dp[i - 1][j - 1] + (score if score >= MIN_WORD_MATCH_SCORE else -0.52)
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
            if score >= MIN_WORD_MATCH_SCORE:
                matches.append((lyric, transcript, score))
            else:
                matches.append((lyric, None, 0.0))
        elif action == "skip_lyric":
            matches.append((lyric_tokens[i - 1], None, 0.0))
        i, j = prev_i, prev_j

    matches.reverse()
    return matches


def _tokenize_text(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    if " " not in text and _contains_cjk(text):
        return [char for char in text if not char.isspace()]
    return re.findall(r"[^\W_]+(?:['’][^\W_]+)*", text, flags=re.UNICODE)


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

"""Provider-independent parsing and validation of AI-suggested moments.

Any provider that returns JSON like
    [{"title": "...", "start": 12.5, "end": 48.0, "reason": "..."}]
can reuse parse_moments(); nothing here knows about Gemini.
"""
import json
import logging
import re
from typing import Any, List, Optional

from app.exceptions import MomentDetectionError
from app.models import Moment, Transcript

logger = logging.getLogger(__name__)

MIN_MOMENT_SECONDS = 5.0  # anything shorter is discarded as useless
_MAX_OVERLAP = 0.5        # drop a moment overlapping an earlier one by more than this fraction
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _to_seconds(value: Any) -> Optional[float]:
    """Accept 12.5, "12.5", "1:05", "01:02:03". Returns None if not a valid time."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value == value and abs(value) != float("inf") else None
    if isinstance(value, str):
        text = re.sub(r"\s*(seconds?|secs?|s)$", "", value.strip(), flags=re.IGNORECASE)
        parts = text.split(":")
        if not 1 <= len(parts) <= 3:
            return None
        try:
            nums = [float(p) for p in parts]
        except ValueError:
            return None
        total = 0.0
        for n in nums:
            total = total * 60 + n
        return total
    return None


_ALIASES = {
    "title": ("title", "name", "headline"),
    "reason": ("reason", "why", "explanation", "rationale", "description"),
    "start": ("start", "start_time", "start_seconds", "begin"),
    "end": ("end", "end_time", "end_seconds", "stop"),
}


def _get(item: dict, field: str) -> Any:
    for key in _ALIASES[field]:
        if item.get(key) not in (None, ""):
            return item[key]
    return None


def _extract_items(text: str) -> list:
    cleaned = _FENCE_RE.sub("", (text or "").strip()).strip()
    if not cleaned:
        raise MomentDetectionError("The AI returned an empty response.")
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise MomentDetectionError("The AI returned invalid JSON.") from exc
    if isinstance(data, dict):
        data = data.get("moments")
    if not isinstance(data, list):
        raise MomentDetectionError("The AI response did not contain a list of moments.")
    return data


_SNAP_TOLERANCE = 3.0  # seconds; don't move a cut further than this to reach a boundary


def _snap(value: float, points: List[float]) -> float:
    nearest = min(points, key=lambda p: abs(p - value))
    return nearest if abs(nearest - value) <= _SNAP_TOLERANCE else value


def parse_moments(
    text: str,
    transcript: Transcript,
    max_moments: int,
    max_seconds: float,
    min_seconds: float = MIN_MOMENT_SECONDS,
) -> List[Moment]:
    """Turn raw AI text into validated Moments, or raise MomentDetectionError.

    Each item needs title, start, end and reason. Times within 3s of a transcript
    segment boundary are snapped to it (so cuts land between sentences), clamped to the transcript,
    length-limited (max_seconds; a hard floor of 5s), and de-duplicated. Bad items are dropped with a warning; if none
    survive, an error is raised.
    """
    if not transcript.segments:
        raise MomentDetectionError("Transcript is empty.")
    starts = [s.start for s in transcript.segments]
    ends = [s.end for s in transcript.segments]
    duration = max(ends)

    items = _extract_items(text)
    moments: List[Moment] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            logger.warning("Moment %d dropped: not an object", i)
            continue
        title, reason = _get(item, "title"), _get(item, "reason")
        start, end = _to_seconds(_get(item, "start")), _to_seconds(_get(item, "end"))
        if not (isinstance(title, str) and title.strip()
                and isinstance(reason, str) and reason.strip()
                and start is not None and end is not None):
            logger.warning("Moment %d dropped: missing/invalid title, reason, start or end", i)
            continue
        if start < 0 or start >= duration or end <= start:
            logger.warning("Moment %d dropped: bad range %.1f-%.1f (transcript is %.1fs)",
                           i, start, end, duration)
            continue

        start = _snap(start, starts)
        end = _snap(min(end, duration), ends)
        if end - start > max_seconds:  # prefer a segment boundary, else a hard trim
            fitting = [e for e in ends if start < e <= start + max_seconds]
            end = max(fitting) if fitting else start + max_seconds
            end = min(end, duration)
        if end - start < max(min_seconds, MIN_MOMENT_SECONDS):
            logger.warning("Moment %d dropped: too short (%.1fs, minimum %.0fs)",
                           i, end - start, max(min_seconds, MIN_MOMENT_SECONDS))
            continue

        overlaps = any(
            max(0.0, min(end, m.end) - max(start, m.start)) / min(end - start, m.end - m.start)
            > _MAX_OVERLAP for m in moments
        )
        if overlaps:
            logger.warning("Moment %d dropped: overlaps an earlier moment", i)
            continue

        moments.append(Moment(start=round(start, 2), end=round(end, 2),
                              title=title.strip()[:120], reason=reason.strip()))
        if len(moments) >= max_moments:
            break

    if not moments:
        logger.warning("No usable moments. Raw AI response (first 800 chars): %s",
                       (text or "")[:800].replace("\n", " "))
        raise MomentDetectionError(
            f"The AI returned {len(items)} moment(s), but none passed validation "
            "(details are in logs/app.log)."
        )
    return moments

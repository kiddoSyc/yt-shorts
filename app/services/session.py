"""Processing sessions: validated (url, clip_duration, max_moments, moment_prompt, manual_ranges) requests."""
import uuid
from typing import Any, List, Optional, Tuple

from app.config import Settings, get_settings
from app.exceptions import (InvalidDurationError, InvalidMomentCountError, InvalidMomentRangeError,
                            InvalidPromptError)
from app.models import ProcessingSession
from app.services.downloader import extract_video_id

# Options a UI can offer; anything else is a "custom" duration within the allowed range.
CLIP_DURATION_PRESETS = (30, 40, 60)


def validate_clip_duration(value: Any, settings: Optional[Settings] = None) -> int:
    """Return `value` as a whole number of seconds within the allowed range, or raise."""
    settings = settings or get_settings()
    lo, hi = settings.clip_duration_min, settings.clip_duration_max
    if isinstance(value, bool):
        raise InvalidDurationError("clip_duration must be a number of seconds.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise InvalidDurationError("clip_duration must be a number of seconds.") from None
    if number != number or number != int(number):  # NaN or fractional
        raise InvalidDurationError("clip_duration must be a whole number of seconds.")
    seconds = int(number)
    if not lo <= seconds <= hi:
        raise InvalidDurationError(f"clip_duration must be between {lo} and {hi} seconds.")
    return seconds


def validate_max_moments(value: Any, settings: Optional[Settings] = None) -> Optional[int]:
    """Return `value` (number of clips to generate) as a validated int, or None to use the default."""
    if value is None:
        return None
    settings = settings or get_settings()
    if isinstance(value, bool):
        raise InvalidMomentCountError("num_clips must be a whole number.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise InvalidMomentCountError("num_clips must be a whole number.") from None
    if number != number or number != int(number):
        raise InvalidMomentCountError("num_clips must be a whole number.")
    count = int(number)
    hi = settings.max_moments_limit
    if not 1 <= count <= hi:
        raise InvalidMomentCountError(f"num_clips must be between 1 and {hi}.")
    return count


def validate_moment_prompt(value: Any) -> Optional[str]:
    """Return a trimmed, length-capped prompt hint, or None."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidPromptError("prompt must be text.")
    trimmed = value.strip()
    if not trimmed:
        return None
    if len(trimmed) > 300:
        raise InvalidPromptError("prompt must be 300 characters or fewer.")
    return trimmed


def validate_manual_ranges(value: Any, settings: Optional[Settings] = None) -> Optional[List[Tuple[float, float]]]:
    """Return validated (start, end) second pairs, or None. Each range must be a sane clip length;
    the count is capped the same way as num_clips."""
    if value is None:
        return None
    settings = settings or get_settings()
    if not isinstance(value, (list, tuple)) or len(value) == 0:
        raise InvalidMomentRangeError("ranges must be a non-empty list of {start, end} times.")
    if len(value) > settings.max_moments_limit:
        raise InvalidMomentRangeError(f"You can specify at most {settings.max_moments_limit} ranges.")
    out: List[Tuple[float, float]] = []
    for i, item in enumerate(value):
        if isinstance(item, dict):
            start, end = item.get("start"), item.get("end")
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            start, end = item
        else:
            raise InvalidMomentRangeError(f"Range {i + 1} must be {{start, end}} in seconds.")
        try:
            start, end = float(start), float(end)
        except (TypeError, ValueError):
            raise InvalidMomentRangeError(f"Range {i + 1}: start/end must be numbers.") from None
        if start != start or end != end or start < 0:  # NaN check + negative
            raise InvalidMomentRangeError(f"Range {i + 1}: start/end must be non-negative numbers.")
        length = end - start
        if length <= 0:
            raise InvalidMomentRangeError(f"Range {i + 1}: end must be after start.")
        if length < 3:
            raise InvalidMomentRangeError(f"Range {i + 1}: must be at least 3 seconds long.")
        if length > settings.clip_duration_max:
            raise InvalidMomentRangeError(
                f"Range {i + 1}: {length:.0f}s is longer than the {settings.clip_duration_max}s limit.")
        out.append((round(start, 3), round(end, 3)))
    return out


def new_session(url: str, clip_duration: Any = None, settings: Optional[Settings] = None,
                *, max_moments: Any = None, moment_prompt: Any = None,
                manual_ranges: Any = None) -> ProcessingSession:
    """Validate the URL, duration, clip count/prompt/ranges, and create a session.
    Duration defaults from .env. If manual_ranges is given, max_moments/moment_prompt are
    ignored by the pipeline (AI moment detection is skipped in favor of the exact ranges)."""
    settings = settings or get_settings()
    extract_video_id(url)  # raises InvalidURLError
    if clip_duration is None:
        clip_duration = settings.clip_duration_default
    return ProcessingSession(url=url.strip(), clip_duration=validate_clip_duration(clip_duration, settings),
                             max_moments=validate_max_moments(max_moments, settings),
                             moment_prompt=validate_moment_prompt(moment_prompt),
                             manual_ranges=validate_manual_ranges(manual_ranges, settings),
                             session_id=uuid.uuid4().hex[:8])

"""Processing sessions: validated (url, clip_duration, max_moments) requests."""
import uuid
from typing import Any, Optional

from app.config import Settings, get_settings
from app.exceptions import InvalidDurationError, InvalidMomentCountError
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


def new_session(url: str, clip_duration: Any = None, settings: Optional[Settings] = None,
                *, max_moments: Any = None) -> ProcessingSession:
    """Validate the URL, duration and clip count, and create a session. Duration defaults from .env."""
    settings = settings or get_settings()
    extract_video_id(url)  # raises InvalidURLError
    if clip_duration is None:
        clip_duration = settings.clip_duration_default
    return ProcessingSession(url=url.strip(), clip_duration=validate_clip_duration(clip_duration, settings),
                             max_moments=validate_max_moments(max_moments, settings),
                             session_id=uuid.uuid4().hex[:8])

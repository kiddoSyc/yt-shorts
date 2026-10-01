"""Request models for the HTTP API."""
from pydantic import BaseModel, Field, field_validator

from app.exceptions import InvalidDurationError, InvalidMomentCountError
from app.services.session import CLIP_DURATION_PRESETS, validate_clip_duration, validate_max_moments


class ProcessRequest(BaseModel):
    """Body of POST /process, e.g. {"url": "https://youtu.be/...", "clip_duration": 40}.

    clip_duration is in seconds: use a preset (30, 40, 60) or any custom whole number
    within CLIP_DURATION_MIN..CLIP_DURATION_MAX (default 15..180). Omit it for the default.
    """
    url: str = Field(..., min_length=1)
    clip_duration: int | None = Field(default=None, description=f"Seconds. Presets: {CLIP_DURATION_PRESETS}")

    @field_validator("clip_duration")
    @classmethod
    def _check_duration(cls, value):
        if value is None:
            return None
        try:
            return validate_clip_duration(value)
        except InvalidDurationError as exc:
            raise ValueError(exc.message) from None  # becomes a normal 422 validation error


class JobCreateRequest(BaseModel):
    """Body of POST /jobs, e.g. {"url": "...", "clip_duration": 40, "num_clips": 3}.

    Both clip_duration and num_clips are optional; omitted values use the server defaults
    (from .env). num_clips is how many Shorts to generate (the AI still chooses which moments).
    """
    url: str = Field(..., min_length=1)
    clip_duration: int | None = Field(default=None, description=f"Seconds. Presets: {CLIP_DURATION_PRESETS}")
    num_clips: int | None = Field(default=None, description="How many Shorts to generate.")

    @field_validator("clip_duration")
    @classmethod
    def _check_duration(cls, value):
        if value is None:
            return None
        try:
            return validate_clip_duration(value)
        except InvalidDurationError as exc:
            raise ValueError(exc.message) from None

    @field_validator("num_clips")
    @classmethod
    def _check_num_clips(cls, value):
        if value is None:
            return None
        try:
            return validate_max_moments(value)
        except InvalidMomentCountError as exc:
            raise ValueError(exc.message) from None

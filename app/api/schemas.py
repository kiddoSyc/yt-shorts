"""Request models for the HTTP API."""
from pydantic import BaseModel, Field, field_validator

from app.exceptions import (InvalidDurationError, InvalidMomentCountError, InvalidMomentRangeError,
                            InvalidPromptError)
from app.services.session import (CLIP_DURATION_PRESETS, validate_clip_duration, validate_manual_ranges,
                                  validate_max_moments, validate_moment_prompt)


class ManualRange(BaseModel):
    """One user-picked clip time range, in seconds into the source video."""
    start: float = Field(..., ge=0)
    end: float = Field(...)


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

    clip_duration and num_clips are optional; omitted values use the server defaults (from .env).
    num_clips is how many Shorts to generate (the AI still chooses which moments, unless
    manual_ranges is given).

    Two ways to choose *which* moments become Shorts (pick at most one):
    - prompt: a free-text steer for the AI, e.g. "funny moments" or "arguments about money".
      num_clips/clip_duration still apply; the AI just prioritizes moments matching this.
    - manual_ranges: exact [{"start": 12.5, "end": 45.0}, ...] times you already know you want.
      AI moment detection is skipped entirely; clip_duration/num_clips/prompt are ignored.
    """
    url: str = Field(..., min_length=1)
    clip_duration: int | None = Field(default=None, description=f"Seconds. Presets: {CLIP_DURATION_PRESETS}")
    num_clips: int | None = Field(default=None, description="How many Shorts to generate.")
    prompt: str | None = Field(default=None, max_length=300,
                               description="What kind of moment to look for, e.g. 'funny moments'.")
    manual_ranges: list[ManualRange] | None = Field(
        default=None, description="Exact times to cut, skipping AI moment detection.")

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

    @field_validator("prompt")
    @classmethod
    def _check_prompt(cls, value):
        try:
            return validate_moment_prompt(value)
        except InvalidPromptError as exc:
            raise ValueError(exc.message) from None

    @field_validator("manual_ranges")
    @classmethod
    def _check_manual_ranges(cls, value):
        if value is None:
            return None
        try:
            validate_manual_ranges([r.model_dump() for r in value])
        except InvalidMomentRangeError as exc:
            raise ValueError(exc.message) from None
        return value

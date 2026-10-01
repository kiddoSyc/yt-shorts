import pytest

from app.exceptions import InvalidDurationError, InvalidURLError
from app.services.session import CLIP_DURATION_PRESETS, new_session, validate_clip_duration

URL = "https://youtu.be/dQw4w9WgXcQ"


@pytest.mark.parametrize("value,expected", [(15, 15), (30, 30), (40, 40), (60, 60), (180, 180),
                                            ("45", 45), (90.0, 90)])
def test_valid_durations(settings, value, expected):
    assert validate_clip_duration(value, settings) == expected


@pytest.mark.parametrize("value", [14, 0, -30, 181, 1000, 40.5, "abc", "", None, True, float("nan"), [40]])
def test_invalid_durations(settings, value):
    with pytest.raises(InvalidDurationError):
        validate_clip_duration(value, settings)


def test_presets_are_valid(settings):
    assert CLIP_DURATION_PRESETS == (30, 40, 60)
    assert all(validate_clip_duration(p, settings) == p for p in CLIP_DURATION_PRESETS)


def test_new_session_uses_default_when_missing(settings):
    s = new_session(URL, None, settings)
    assert s.clip_duration == settings.clip_duration_default == 60
    assert s.url == URL and len(s.session_id) == 8


def test_new_session_bounds_come_from_env(settings):
    settings.clip_duration_max = 90
    with pytest.raises(InvalidDurationError):
        new_session(URL, 120, settings)
    assert new_session(URL, 90, settings).clip_duration == 90


def test_new_session_rejects_bad_url(settings):
    with pytest.raises(InvalidURLError):
        new_session("https://example.com/x", 40, settings)


# ---- max_moments / num_clips ----
from app.exceptions import InvalidMomentCountError  # noqa: E402
from app.services.session import validate_max_moments  # noqa: E402


def test_max_moments_none_means_use_default(settings):
    assert validate_max_moments(None, settings) is None


@pytest.mark.parametrize("value,expected", [(1, 1), (5, 5), ("3", 3), (10.0, 10)])
def test_max_moments_valid_values(settings, value, expected):
    assert validate_max_moments(value, settings) == expected


@pytest.mark.parametrize("value", [0, -1, 11, 1000, 2.5, "abc", True, float("nan"), [3]])
def test_max_moments_invalid_values(settings, value):
    with pytest.raises(InvalidMomentCountError):
        validate_max_moments(value, settings)


def test_max_moments_respects_configured_limit(settings):
    settings.max_moments_limit = 3
    assert validate_max_moments(3, settings) == 3
    with pytest.raises(InvalidMomentCountError):
        validate_max_moments(4, settings)


def test_new_session_carries_max_moments(settings):
    s = new_session(URL, 40, settings, max_moments=3)
    assert s.max_moments == 3
    assert s.clip_duration == 40


def test_new_session_default_max_moments_is_none(settings):
    assert new_session(URL, 40, settings).max_moments is None


def test_new_session_settings_stays_third_positional_argument(settings):
    """Regression guard: max_moments must be keyword-only so existing positional
    callers (new_session(url, duration, settings)) keep working unchanged."""
    s = new_session(URL, 90, settings)
    assert s.clip_duration == 90 and s.max_moments is None

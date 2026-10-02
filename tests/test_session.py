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


# ---- moment_prompt ----
from app.exceptions import InvalidMomentRangeError, InvalidPromptError  # noqa: E402
from app.services.session import validate_manual_ranges, validate_moment_prompt  # noqa: E402


def test_moment_prompt_none_passes_through():
    assert validate_moment_prompt(None) is None


def test_moment_prompt_blank_becomes_none():
    assert validate_moment_prompt("   ") is None


def test_moment_prompt_trims_whitespace():
    assert validate_moment_prompt("  funny moments  ") == "funny moments"


def test_moment_prompt_rejects_too_long():
    with pytest.raises(InvalidPromptError):
        validate_moment_prompt("x" * 301)


def test_moment_prompt_rejects_non_string():
    with pytest.raises(InvalidPromptError):
        validate_moment_prompt(123)


# ---- manual_ranges ----
def test_manual_ranges_none_passes_through(settings):
    assert validate_manual_ranges(None, settings) is None


def test_manual_ranges_accepts_dicts(settings):
    out = validate_manual_ranges([{"start": 10, "end": 40}, {"start": 100, "end": 130}], settings)
    assert out == [(10.0, 40.0), (100.0, 130.0)]


def test_manual_ranges_accepts_tuples(settings):
    out = validate_manual_ranges([(5, 20)], settings)
    assert out == [(5.0, 20.0)]


def test_manual_ranges_rejects_empty_list(settings):
    with pytest.raises(InvalidMomentRangeError):
        validate_manual_ranges([], settings)


def test_manual_ranges_rejects_end_before_start(settings):
    with pytest.raises(InvalidMomentRangeError):
        validate_manual_ranges([{"start": 40, "end": 10}], settings)


def test_manual_ranges_rejects_negative_start(settings):
    with pytest.raises(InvalidMomentRangeError):
        validate_manual_ranges([{"start": -5, "end": 10}], settings)


def test_manual_ranges_rejects_too_short(settings):
    with pytest.raises(InvalidMomentRangeError):
        validate_manual_ranges([{"start": 10, "end": 11}], settings)  # 1 second


def test_manual_ranges_rejects_too_long(settings):
    settings.clip_duration_max = 180
    with pytest.raises(InvalidMomentRangeError):
        validate_manual_ranges([{"start": 0, "end": 300}], settings)


def test_manual_ranges_rejects_too_many(settings):
    settings.max_moments_limit = 2
    with pytest.raises(InvalidMomentRangeError):
        validate_manual_ranges([{"start": 0, "end": 10}, {"start": 20, "end": 30},
                                {"start": 40, "end": 50}], settings)


def test_manual_ranges_rejects_malformed_item(settings):
    with pytest.raises(InvalidMomentRangeError):
        validate_manual_ranges(["not a range"], settings)


def test_new_session_with_manual_ranges(settings):
    s = new_session(URL, settings=settings, manual_ranges=[{"start": 10, "end": 40}])
    assert s.manual_ranges == [(10.0, 40.0)]


def test_new_session_with_moment_prompt(settings):
    s = new_session(URL, settings=settings, moment_prompt="arguments about money")
    assert s.moment_prompt == "arguments about money"

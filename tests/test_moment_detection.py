"""Moment detection tests: fake Gemini client, no network, no API key."""
import json
from types import SimpleNamespace

import pytest

from app.exceptions import ConfigError, MomentDetectionError
from app.models import Transcript, TranscriptSegment
from app.services.moment_detection import parsing
from app.services.moment_detection.gemini import (
    GeminiMomentDetector, build_prompt, format_transcript)


def make_transcript(n=40, step=5.0):
    """40 segments of 5s each -> 200s long, boundaries every 5s."""
    return Transcript(language="en", segments=[
        TranscriptSegment(start=i * step, end=(i + 1) * step, text=f"sentence {i}") for i in range(n)])


T = make_transcript()


def item(title="Great bit", start=10, end=40, reason="Strong hook"):
    return {"title": title, "start": start, "end": end, "reason": reason}


def parse(payload, max_moments=5, max_seconds=60):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return parsing.parse_moments(text, T, max_moments, max_seconds)


# ---------- validation ----------
def test_valid_moment():
    (m,) = parse([item()])
    assert (m.start, m.end, m.title, m.reason) == (10.0, 40.0, "Great bit", "Strong hook")


def test_accepts_code_fences_and_moments_key():
    assert len(parse("```json\n" + json.dumps([item()]) + "\n```")) == 1
    assert len(parse({"moments": [item()]})) == 1


def test_time_formats():
    (m,) = parse([item(start="0:10", end="00:00:40")])
    assert (m.start, m.end) == (10.0, 40.0)
    (m,) = parse([item(start="10.5", end="40")])
    assert m.start == 10.0  # snapped to segment boundary


def test_snaps_to_segment_boundaries():
    (m,) = parse([item(start=11.2, end=38.4)])
    assert (m.start, m.end) == (10.0, 40.0)


def test_clamps_end_to_transcript():
    (m,) = parse([item(start=170, end=999)])
    assert m.end == 200.0


@pytest.mark.parametrize("bad", [
    {"title": "x", "start": 10, "end": 40},                      # no reason
    {"reason": "x", "start": 10, "end": 40},                     # no title
    {"title": "x", "reason": "y", "end": 40},                    # no start
    {"title": "x", "reason": "y", "start": 10},                  # no end
    {"title": "", "reason": "y", "start": 10, "end": 40},
    {"title": "x", "reason": "y", "start": "abc", "end": 40},
    {"title": "x", "reason": "y", "start": 40, "end": 10},       # reversed
    {"title": "x", "reason": "y", "start": -5, "end": 30},
    {"title": "x", "reason": "y", "start": 500, "end": 600},     # beyond transcript
    {"title": "x", "reason": "y", "start": 10, "end": 12},       # too short
    "just a string",
])
def test_bad_items_dropped_then_error(bad):
    with pytest.raises(MomentDetectionError):
        parse([bad])


def test_bad_items_dropped_good_kept():
    result = parse([{"title": "x"}, item(start=50, end=90)])
    assert len(result) == 1 and result[0].start == 50.0


def test_too_long_is_trimmed_to_max():
    (m,) = parse([item(start=0, end=150)], max_seconds=60)
    assert m.end - m.start <= 60


def test_overlaps_dropped_and_max_moments_enforced():
    result = parse([item(start=10, end=40), item(start=15, end=45), item(start=60, end=90),
                    item(start=100, end=130), item(start=140, end=170)], max_moments=3)
    assert [(m.start, m.end) for m in result] == [(10.0, 40.0), (60.0, 90.0), (100.0, 130.0)]


def test_key_aliases_and_unit_suffixes():
    (m,) = parse([{"name": "A title", "why": "Because", "start_time": "10s", "end_time": "40 sec"}])
    assert (m.title, m.reason, m.start, m.end) == ("A title", "Because", 10.0, 40.0)


def test_far_from_boundary_is_not_snapped():
    coarse = Transcript("en", [TranscriptSegment(0, 60, "a"), TranscriptSegment(60, 120, "b")])
    (m,) = parsing.parse_moments(json.dumps([item(start=20, end=50)]), coarse, 5, 60)
    assert (m.start, m.end) == (20.0, 50.0)  # kept as Gemini gave it, not collapsed to 0/60


def test_long_segments_hard_trim_instead_of_drop():
    long_seg = Transcript("en", [TranscriptSegment(0, 300, "one huge segment")])
    (m,) = parsing.parse_moments(json.dumps([item(start=10, end=200)]), long_seg, 5, 60)
    assert (m.start, m.end) == (10.0, 70.0)


def test_failure_message_counts_items():
    with pytest.raises(MomentDetectionError) as exc:
        parse([{"title": "x"}, {"title": "y"}])
    assert "2 moment(s)" in exc.value.message


@pytest.mark.parametrize("text", ["", "not json", "{\"a\": 1}", "42", "[]"])
def test_bad_payloads(text):
    with pytest.raises(MomentDetectionError):
        parse(text)


# ---------- prompt: only text is sent ----------
def test_prompt_contains_timestamped_text_only():
    prompt = build_prompt(T, 5, 15, 60)
    assert "[0.0-5.0] sentence 0" in prompt
    assert "between 15 and 60 seconds" in prompt
    assert format_transcript(T).count("\n") == len(T.segments) - 1


# ---------- detector with fake client ----------
class FakeClient:
    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), []
        self.models = self

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return SimpleNamespace(text=out)


class ApiError(Exception):
    def __init__(self, code, msg="err"):
        super().__init__(f"{code} {msg}")
        self.code = code


def detector(settings, *outcomes):
    client = FakeClient(*outcomes)
    sleeps = []
    return GeminiMomentDetector(settings, client=client, sleep=sleeps.append), client, sleeps


def test_detect_success_uses_configured_model(settings):
    settings.gemini_model = "gemini-test-model"
    det, client, _ = detector(settings, json.dumps([item()]))
    moments = det.detect_moments(T, max_moments=3)
    assert len(moments) == 1
    call = client.calls[0]
    assert call["model"] == "gemini-test-model"
    assert isinstance(call["contents"], str) and "sentence 0" in call["contents"]  # text only
    assert call["config"]["response_mime_type"] == "application/json"


def test_missing_api_key(settings):
    settings.gemini_api_key = ""
    with pytest.raises(ConfigError):
        GeminiMomentDetector(settings)


def test_invalid_json_from_gemini(settings):
    det, _, _ = detector(settings, "Sorry, I can't do that")
    with pytest.raises(MomentDetectionError):
        det.detect_moments(T)


def test_empty_response(settings):
    det, _, _ = detector(settings, None)
    with pytest.raises(MomentDetectionError):
        det.detect_moments(T)


def test_rate_limit_retries_then_succeeds(settings):
    det, client, sleeps = detector(settings, ApiError(429), json.dumps([item()]))
    assert len(det.detect_moments(T)) == 1
    assert len(client.calls) == 2 and len(sleeps) == 1


def test_rate_limit_gives_clean_error(settings):
    det, client, sleeps = detector(settings, ApiError(429), ApiError(429), ApiError(429))
    with pytest.raises(MomentDetectionError) as exc:
        det.detect_moments(T)
    assert "rate limit" in exc.value.message.lower()
    assert len(client.calls) == 3


def test_bad_key_not_retried(settings):
    det, client, sleeps = detector(settings, ApiError(403, "PERMISSION_DENIED"))
    with pytest.raises(MomentDetectionError) as exc:
        det.detect_moments(T)
    assert "GEMINI_API_KEY" in exc.value.message
    assert len(client.calls) == 1 and sleeps == []


def test_model_not_found(settings):
    det, _, _ = detector(settings, ApiError(404))
    with pytest.raises(MomentDetectionError) as exc:
        det.detect_moments(T)
    assert "GEMINI_MODEL" in exc.value.message


def test_empty_transcript(settings):
    det, client, _ = detector(settings)
    with pytest.raises(MomentDetectionError):
        det.detect_moments(Transcript(language="en", segments=[]))
    assert client.calls == []


# ---------- session clip length (target_seconds) ----------
def test_prompt_mentions_target_length_and_context_rule():
    prompt = build_prompt(T, 5, 32, 48, target_seconds=40)
    assert "about 40 seconds" in prompt and "32-48 seconds" in prompt
    assert "Do NOT pad" in prompt and "mid-sentence" in prompt


def test_prompt_without_target_uses_range():
    assert "between 15 and 60 seconds" in build_prompt(T, 5, 15, 60)


@pytest.mark.parametrize("target,expected", [(30, (24.0, 36.0)), (40, (32.0, 48.0)), (60, (48.0, 72.0))])
def test_length_bounds(target, expected):
    from app.services.moment_detection.gemini import clip_length_bounds
    lo, hi, hard_min, hard_max = clip_length_bounds(target, 0.2)
    assert (round(lo, 1), round(hi, 1)) == expected
    assert hard_min == target * 0.6 and hard_max > hi


def test_detect_passes_target_to_gemini_and_enforces_bounds(settings):
    # 20s is far below 0.6 * 40 = 24s -> dropped; 200s-long request is trimmed to <= 52s
    reply = json.dumps([item(start=0, end=20), item(start=50, end=150), item(start=155, end=195)])
    det, client, _ = detector(settings, reply)
    moments = det.detect_moments(T, max_moments=5, target_seconds=40)
    assert "about 40 seconds" in client.calls[0]["contents"]
    assert all(24 <= m.end - m.start <= 52 for m in moments)
    assert len(moments) == 2 and det.last_raw_response == reply


def test_detect_without_target_keeps_default_range(settings):
    det, client, _ = detector(settings, json.dumps([item(start=10, end=40)]))
    assert len(det.detect_moments(T)) == 1
    assert "between 15 and 60 seconds" in client.calls[0]["contents"]

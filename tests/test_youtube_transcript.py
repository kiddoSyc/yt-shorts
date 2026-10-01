"""Caption parsing/selection tests: no network."""
import json

import pytest

from app.exceptions import CaptionsUnavailableError
from app.models import TranscriptSegment
from app.services import youtube_transcript as yt


def entries(*exts):
    return [{"ext": e, "url": f"https://x/{e}"} for e in exts]


# ---------- track selection ----------
def test_prefers_manual_in_video_language():
    info = {"language": "fr", "subtitles": {"en": entries("json3"), "fr": entries("vtt", "json3")},
            "automatic_captions": {"fr-orig": entries("json3")}}
    t = yt.pick_caption_track(info)
    assert (t.kind, t.lang) == ("manual", "fr")


def test_manual_falls_back_to_english_then_any():
    info = {"subtitles": {"de": entries("json3"), "en-GB": entries("json3")}}
    assert yt.pick_caption_track(info).lang == "en-GB"
    assert yt.pick_caption_track({"subtitles": {"de": entries("json3")}}).lang == "de"


def test_auto_uses_original_track_not_translations():
    info = {"language": "es", "automatic_captions": {
        "en": entries("json3"), "es": entries("json3"), "es-orig": entries("json3"), "fr": entries("json3")}}
    t = yt.pick_caption_track(info)
    assert (t.kind, t.lang) == ("auto", "es-orig")


def test_auto_unknown_language_only_accepts_orig_or_en():
    assert yt.pick_caption_track({"automatic_captions": {"fr": entries("json3"), "de": entries("json3")}}) is None
    assert yt.pick_caption_track({"automatic_captions": {"fr": entries("json3"), "en": entries("json3")}}).lang == "en"


def test_needs_json3_and_ignores_live_chat():
    assert yt.pick_caption_track({"subtitles": {"en": entries("vtt", "srv1")}}) is None
    assert yt.pick_caption_track({"subtitles": {"live_chat": entries("json3")}}) is None
    assert yt.pick_caption_track({}) is None


# ---------- json3 parsing ----------
def ev(start_ms, dur_ms, *texts):
    return {"tStartMs": start_ms, "dDurationMs": dur_ms, "segs": [{"utf8": t} for t in texts]}


def test_parse_json3_basic_and_cleanup():
    raw = json.dumps({"events": [
        {"tStartMs": 0, "dDurationMs": 100},                       # no segs
        ev(1000, 3000, "Hello ", "world\n"),
        ev(4000, 2000, "\n"),                                      # blank
        ev(5000, 4000, "Second   line"),
    ]})
    segs = yt.parse_json3(raw)
    assert [(s.start, s.text) for s in segs] == [(1.0, "Hello world"), (5.0, "Second line")]
    assert segs[0].end == 4.0


def test_parse_json3_clamps_overlap_and_drops_duplicates():
    raw = json.dumps({"events": [ev(0, 5000, "one"), ev(2000, 5000, "two"), ev(4000, 1000, "two")]})
    segs = yt.parse_json3(raw.encode())
    assert [(s.start, s.end, s.text) for s in segs] == [(0.0, 2.0, "one"), (2.0, 4.0, "two")]


@pytest.mark.parametrize("raw", ["not json", "{}", "[]", b"\xff\xfe"])
def test_parse_json3_bad_input(raw):
    with pytest.raises(CaptionsUnavailableError):
        yt.parse_json3(raw)


def test_merge_segments_groups_short_lines():
    segs = [TranscriptSegment(i * 2.0, i * 2.0 + 2.0, f"w{i}") for i in range(10)]  # 20s total
    merged = yt.merge_segments(segs)
    assert all(m.end - m.start <= 15.0 for m in merged) and len(merged) < 10
    assert merged[0].start == 0.0 and merged[-1].end == 20.0
    assert " ".join(m.text for m in merged) == " ".join(f"w{i}" for i in range(10))


def test_merge_breaks_on_gap_and_sentence_end():
    segs = [TranscriptSegment(0, 2, "a"), TranscriptSegment(2, 4, "done."), TranscriptSegment(4, 6, "next"),
            TranscriptSegment(20, 22, "far")]
    merged = yt.merge_segments(segs)
    assert [m.text for m in merged] == ["a done.", "next", "far"]


# ---------- fetching with a fake source ----------
class FakeSource:
    def __init__(self, info, payload=b"", fail=None):
        self._info, self._payload, self._fail = info, payload, fail

    def info(self):
        return self._info

    def read_url(self, url):
        if self._fail:
            raise self._fail
        return self._payload


def long_json3():
    return json.dumps({"events": [ev(i * 3000, 3000, f"This is caption sentence number {i}.") for i in range(20)]}).encode()


def test_fetch_success():
    src = FakeSource({"language": "en", "subtitles": {"en": entries("json3")}}, long_json3())
    result = yt.fetch_caption_transcript(src)
    assert result.kind == "manual" and result.bytes_downloaded == len(long_json3())
    assert result.transcript.language == "en" and len(result.transcript.segments) >= 3


def test_fetch_no_captions():
    with pytest.raises(CaptionsUnavailableError):
        yt.fetch_caption_transcript(FakeSource({}))


def test_fetch_too_short_captions():
    raw = json.dumps({"events": [ev(0, 1000, "hi")]}).encode()
    with pytest.raises(CaptionsUnavailableError):
        yt.fetch_caption_transcript(FakeSource({"subtitles": {"en": entries("json3")}}, raw))


def test_fetch_download_failure_becomes_unavailable():
    from app.exceptions import DownloadError
    src = FakeSource({"subtitles": {"en": entries("json3")}}, fail=DownloadError("403"))
    with pytest.raises(CaptionsUnavailableError):
        yt.fetch_caption_transcript(src)

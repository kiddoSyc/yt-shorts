"""Tests for caption slicing, line-wrapping, and .ass rendering."""
import pytest

from app.exceptions import CaptionError
from app.models import Transcript, TranscriptSegment
from app.services.captions import (
    build_caption_events,
    render_ass,
    slice_to_clip,
    wrap_words,
    write_caption_file,
)


def test_slice_to_clip_keeps_only_overlapping_segments_and_retimes():
    transcript = Transcript(language="en", segments=[
        TranscriptSegment(start=0, end=5, text="before the clip"),
        TranscriptSegment(start=10, end=15, text="inside the clip"),
        TranscriptSegment(start=40, end=45, text="after the clip"),
    ])
    sliced = slice_to_clip(transcript, clip_start=10, clip_end=20)
    assert len(sliced) == 1
    assert sliced[0].text == "inside the clip"
    assert sliced[0].start == 0.0 and sliced[0].end == 5.0  # re-timed relative to the clip


def test_slice_to_clip_trims_boundary_segment_text_proportionally():
    # 10-word segment spanning 10s (1 word/s); only the last 2s (2 words) fall in the clip.
    transcript = Transcript(language="en", segments=[
        TranscriptSegment(start=0, end=10, text="one two three four five six seven eight nine ten"),
    ])
    sliced = slice_to_clip(transcript, clip_start=8, clip_end=20)
    assert len(sliced) == 1
    # Should keep roughly the last ~2 words, not all 10 crammed into 2 seconds.
    assert len(sliced[0].text.split()) <= 3
    assert sliced[0].text.split()[-1] == "ten"


def test_slice_to_clip_empty_range_returns_nothing():
    transcript = Transcript(language="en", segments=[TranscriptSegment(0, 5, "hello")])
    assert slice_to_clip(transcript, 10, 5) == []  # end before start


def test_wrap_words_respects_max_chars_and_lines():
    words = "the quick brown fox jumps over the lazy dog".split()
    lines, remaining = wrap_words(words, max_chars=15, max_lines=2)
    assert len(lines) <= 2
    assert all(len(line) <= 15 or len(line.split()) == 1 for line in lines)


def test_wrap_words_never_infinite_loops_on_one_long_word():
    lines, remaining = wrap_words(["supercalifragilisticexpialidocious"], max_chars=5, max_lines=1)
    assert lines == ["supercalifragilisticexpialidocious"]
    assert remaining == []


def test_build_caption_events_splits_long_segment_into_multiple_events():
    seg = TranscriptSegment(start=0, end=10, text="one two three four five six seven eight nine ten "
                                                "eleven twelve thirteen fourteen fifteen")
    events = build_caption_events([seg])
    assert len(events) > 1
    # events are sequential and stay within the segment's time range
    assert events[0].start == 0.0
    assert events[-1].end <= 10.0
    for a, b in zip(events, events[1:]):
        assert a.end <= b.start + 1e-6


def test_build_caption_events_keeps_short_segment_as_one_event():
    seg = TranscriptSegment(start=1.0, end=3.0, text="hello there")
    events = build_caption_events([seg])
    assert len(events) == 1
    assert events[0].lines == ["hello there"]


def test_render_ass_contains_header_and_dialogue_lines():
    seg = TranscriptSegment(start=0.0, end=2.0, text="hi there")
    events = build_caption_events([seg])
    ass = render_ass(events)
    assert "[Script Info]" in ass
    assert "[V4+ Styles]" in ass
    assert "[Events]" in ass
    assert "Dialogue:" in ass
    assert "hi there" in ass


def test_render_ass_escapes_curly_braces():
    seg = TranscriptSegment(start=0.0, end=1.0, text="a {weird} line")
    ass = render_ass(build_caption_events([seg]))
    assert "\\{weird\\}" in ass


def test_render_ass_with_no_events_is_still_a_valid_header():
    ass = render_ass([])
    assert "[Events]" in ass
    assert "Dialogue:" not in ass


def test_write_caption_file_returns_none_when_no_speech_in_range(tmp_path):
    transcript = Transcript(language="en", segments=[TranscriptSegment(0, 5, "only near the start")])
    result = write_caption_file(transcript, clip_start=100, clip_end=120, out_path=tmp_path / "c.ass")
    assert result is None
    assert not (tmp_path / "c.ass").exists()


def test_write_caption_file_writes_ass_when_speech_present(tmp_path):
    transcript = Transcript(language="en", segments=[TranscriptSegment(2, 6, "hello from the clip")])
    out = write_caption_file(transcript, clip_start=0, clip_end=10, out_path=tmp_path / "c.ass")
    assert out is not None and out.exists()
    assert "hello from the clip" in out.read_text(encoding="utf-8")


def test_write_caption_file_raises_caption_error_on_unwritable_path(tmp_path):
    transcript = Transcript(language="en", segments=[TranscriptSegment(0, 2, "hi")])
    bad_path = tmp_path / "no_such_dir_parent_is_a_file"
    bad_path.write_text("x")  # make it a file so mkdir(parents=True) under it fails
    with pytest.raises(CaptionError):
        write_caption_file(transcript, 0, 2, bad_path / "c.ass")

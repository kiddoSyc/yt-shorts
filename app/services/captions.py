"""Builds burned-in captions from transcript data for one clip.

Works with any Transcript, so it supports both sources the pipeline can produce:
YouTube captions (manual or auto) and the local Whisper fallback.

Pipeline:
    Transcript (full-video timeline)
      -> slice_to_clip(): keep only the words spoken during [moment.start, moment.end),
                          re-time them to start at 0 for the clip
      -> build_caption_events(): wrap each segment's text into readable 1-2 line
                                 chunks, splitting long segments into several
                                 time-spaced captions (by word count) so nothing
                                 sits on screen too long
      -> render_ass(): write an .ass subtitle file styled for a 1080x1920 phone
                       screen, positioned to clear on-screen UI (like/share
                       buttons) at the bottom

No word-level timestamps are available from either caption source, so timing
within a segment is approximated proportionally by word count. This is precise
enough for phone-readable captions; it is not karaoke-accurate.
"""
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from app.config import Settings, get_settings
from app.exceptions import CaptionError
from app.models import Transcript, TranscriptSegment

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"\S+")


@dataclass
class CaptionEvent:
    start: float  # seconds, relative to the clip start
    end: float
    lines: List[str]


# ----------------------------------------------------------------------------
# 1. Slice the full-video transcript down to one clip's time range
# ----------------------------------------------------------------------------
def slice_to_clip(transcript: Transcript, clip_start: float, clip_end: float) -> List[TranscriptSegment]:
    """Segments that overlap [clip_start, clip_end), re-timed to start at 0.

    A segment that straddles a clip boundary has its text trimmed proportionally
    to the fraction of its original duration that falls outside the clip - otherwise
    the full sentence would be crammed into whatever sliver of time remains inside
    the clip, making captions flash by unreadably at the very start/end of a clip.
    """
    if clip_end <= clip_start:
        return []
    out: List[TranscriptSegment] = []
    for seg in transcript.segments:
        if seg.end <= clip_start or seg.start >= clip_end:
            continue
        orig_duration = max(seg.end - seg.start, 0.01)
        start, end = max(seg.start, clip_start), min(seg.end, clip_end)
        if end <= start:
            continue
        words = seg.text.split()
        truncated_before, truncated_after = start > seg.start, end < seg.end
        if words and (truncated_before or truncated_after):
            n = len(words)
            keep_from = int(round((start - seg.start) / orig_duration * n)) if truncated_before else 0
            keep_to = n - int(round((seg.end - end) / orig_duration * n)) if truncated_after else n
            words = words[keep_from:max(keep_to, keep_from + 1)]
        text = (" ".join(words) if words else seg.text).strip()
        rel_start, rel_end = round(start - clip_start, 3), round(end - clip_start, 3)
        if rel_end > rel_start and text:
            out.append(TranscriptSegment(start=rel_start, end=rel_end, text=text))
    return out


# ----------------------------------------------------------------------------
# 2. Wrap text into readable lines, and split segments that are too long
#    for a couple of lines into several time-spaced caption events
# ----------------------------------------------------------------------------
def wrap_words(words: List[str], max_chars: int, max_lines: int) -> Tuple[List[str], List[str]]:
    """Greedy word-wrap. Returns (lines_that_fit, remaining_words)."""
    lines: List[str] = []
    current: List[str] = []
    remaining = list(words)
    while remaining and len(lines) < max_lines:
        word = remaining[0]
        candidate = " ".join(current + [word])
        if not current or len(candidate) <= max_chars:
            current.append(word)
            remaining.pop(0)
        else:
            lines.append(" ".join(current))
            current = []
    if current:
        lines.append(" ".join(current))
    return lines, remaining


def segment_to_events(seg: TranscriptSegment, max_chars: int, max_lines: int) -> List[CaptionEvent]:
    """One segment -> one or more CaptionEvents, timed proportionally by word count."""
    words = _WORD_RE.findall(seg.text)
    if not words:
        return []
    duration = max(seg.end - seg.start, 0.05)
    total = len(words)
    consumed = 0
    events: List[CaptionEvent] = []
    remaining = words
    while remaining:
        lines, remaining = wrap_words(remaining, max_chars, max_lines)
        used = sum(len(line.split()) for line in lines)
        if used == 0:  # safety: a single word longer than max_chars still advances
            used = 1
        frac_start, frac_end = consumed / total, min((consumed + used) / total, 1.0)
        consumed += used
        events.append(CaptionEvent(
            start=round(seg.start + frac_start * duration, 3),
            end=round(seg.start + frac_end * duration, 3),
            lines=lines,
        ))
    return events


def build_caption_events(
    segments: List[TranscriptSegment],
    settings: Optional[Settings] = None,
) -> List[CaptionEvent]:
    """Turn clip-relative segments into display-ready caption events."""
    settings = settings or get_settings()
    events: List[CaptionEvent] = []
    for seg in segments:
        events.extend(segment_to_events(seg, settings.caption_max_chars_per_line, settings.caption_max_lines))
    return events


# ----------------------------------------------------------------------------
# 3. Render as an .ass subtitle file (full style control via libass)
# ----------------------------------------------------------------------------
def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def render_ass(events: List[CaptionEvent], settings: Optional[Settings] = None) -> str:
    """Build the full .ass file content: header, one readable style, one line per event."""
    settings = settings or get_settings()
    w, h = settings.shorts_width, settings.shorts_height
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, \
Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, \
Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{settings.caption_font_name},{settings.caption_font_size},&H00FFFFFF,&H000000FF,\
&H00101010,&H64000000,-1,0,0,0,100,100,0,0,1,4,1,2,60,60,{settings.caption_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for ev in events:
        if ev.end <= ev.start or not ev.lines:
            continue
        text = "\\N".join(_ass_escape(line) for line in ev.lines)
        lines.append(f"Dialogue: 0,{_ass_time(ev.start)},{_ass_time(ev.end)},Default,,0,0,0,,{text}")
    return header + "\n".join(lines) + ("\n" if lines else "")


def write_caption_file(
    transcript: Transcript,
    clip_start: float,
    clip_end: float,
    out_path: Path,
    settings: Optional[Settings] = None,
) -> Optional[Path]:
    """Build and save the .ass file for one clip's time range.

    Returns None (and writes nothing) if there is no speech in that range -
    that is normal, not an error, so the caller can skip the subtitles filter.
    """
    settings = settings or get_settings()
    segments = slice_to_clip(transcript, clip_start, clip_end)
    events = build_caption_events(segments, settings)
    if not events:
        logger.info("No captions to render for %.1f-%.1fs (no speech in range)", clip_start, clip_end)
        return None
    content = render_ass(events, settings)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise CaptionError(f"Could not write caption file {out_path}: {exc}") from exc
    logger.info("Captions ready: %d line(s) -> %s", len(events), out_path.name)
    return out_path

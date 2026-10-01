"""Get a timestamped transcript from YouTube's own captions (no audio/video download).

Prefers manual captions in the video's language, then the original auto-generated
track. Raises CaptionsUnavailableError when nothing usable exists so the pipeline can
fall back to audio-only + Whisper.
"""
import json
import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.exceptions import CaptionsUnavailableError, DownloadError
from app.models import Transcript, TranscriptSegment
from app.services.downloader import YouTubeSource

logger = logging.getLogger(__name__)

MIN_SEGMENTS = 3
MIN_CHARS = 100


@dataclass
class CaptionTrack:
    kind: str   # "manual" | "auto"
    lang: str
    url: str


@dataclass
class CaptionResult:
    transcript: Transcript
    kind: str
    language: str
    bytes_downloaded: int


def _base(lang: str) -> str:
    return (lang or "").lower().split("-")[0]


def _json3_url(entries: object) -> Optional[str]:
    for entry in entries or []:
        if isinstance(entry, dict) and entry.get("ext") == "json3" and entry.get("url"):
            return entry["url"]
    return None


def pick_caption_track(info: dict) -> Optional[CaptionTrack]:
    """Choose the best caption track from yt-dlp metadata, or None.

    Auto-caption lists contain machine translations into ~150 languages, so only the
    original-language track (``xx-orig``, or the video's own language) is accepted.
    """
    video_lang = _base(info.get("language") or "")
    manual: Dict[str, list] = {k: v for k, v in (info.get("subtitles") or {}).items()
                               if k != "live_chat"}
    auto: Dict[str, list] = info.get("automatic_captions") or {}

    def first_with_json3(keys: List[str], kind: str) -> Optional[CaptionTrack]:
        source = manual if kind == "manual" else auto
        for key in keys:
            url = _json3_url(source.get(key))
            if url:
                return CaptionTrack(kind, key, url)
        return None

    # 1) manual captions: video's language, then English, then anything
    keys = sorted(manual)
    ordered = ([k for k in keys if video_lang and _base(k) == video_lang]
               + [k for k in keys if _base(k) == "en"] + keys)
    track = first_with_json3(list(dict.fromkeys(ordered)), "manual")
    if track:
        return track

    # 2) auto captions: original-language track only
    akeys = sorted(auto)
    orig = [k for k in akeys if k.endswith("-orig")]
    ordered = ([k for k in orig if video_lang and _base(k) == video_lang] + orig
               + [k for k in akeys if video_lang and k.lower() == video_lang]
               + ([k for k in akeys if k.lower() == "en"] if not video_lang else []))
    return first_with_json3(list(dict.fromkeys(ordered)), "auto")


def parse_json3(raw: object) -> List[TranscriptSegment]:
    """Parse YouTube's json3 caption format into segments (start/end in seconds)."""
    try:
        data = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
        events = data["events"]
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise CaptionsUnavailableError("Caption file could not be parsed.") from exc

    rows = []
    for ev in events:
        if not isinstance(ev, dict) or "segs" not in ev or "tStartMs" not in ev:
            continue
        text = re.sub(r"\s+", " ", "".join(s.get("utf8", "") for s in ev["segs"])).strip()
        if not text:
            continue
        start = ev["tStartMs"] / 1000.0
        rows.append([start, start + ev.get("dDurationMs", 0) / 1000.0, text])

    rows.sort(key=lambda r: r[0])
    segments: List[TranscriptSegment] = []
    for i, (start, end, text) in enumerate(rows):
        if i + 1 < len(rows) and rows[i + 1][0] > start:
            end = min(end, rows[i + 1][0])  # auto-caption lines overlap; clamp
        if end <= start:
            end = start + 1.0
        if segments and segments[-1].text == text:  # rolling duplicate line
            continue
        segments.append(TranscriptSegment(round(start, 2), round(end, 2), text))
    return segments


def merge_segments(segments: List[TranscriptSegment], target: float = 6.0,
                   max_len: float = 15.0, max_gap: float = 1.5) -> List[TranscriptSegment]:
    """Join short caption lines into ~6-15s chunks (fewer tokens sent to Gemini)."""
    merged: List[TranscriptSegment] = []
    cur: Optional[TranscriptSegment] = None
    for seg in segments:
        if cur is not None:
            length = cur.end - cur.start
            ends_sentence = cur.text.rstrip().endswith((".", "?", "!"))
            if (seg.start - cur.end <= max_gap and seg.end - cur.start <= max_len
                    and length < target and not (ends_sentence and length >= 3.0)):
                cur = TranscriptSegment(cur.start, seg.end, f"{cur.text} {seg.text}")
                continue
            merged.append(cur)
        cur = TranscriptSegment(seg.start, seg.end, seg.text)
    if cur is not None:
        merged.append(cur)
    return merged


def fetch_caption_transcript(source: YouTubeSource) -> CaptionResult:
    """Download the caption file (a few KB) and turn it into a Transcript."""
    try:
        info = source.info()
    except DownloadError as exc:
        raise CaptionsUnavailableError(exc.message) from exc

    track = pick_caption_track(info)
    if track is None:
        raise CaptionsUnavailableError("This video has no usable YouTube captions.")
    logger.info("Using %s YouTube captions (%s)", track.kind, track.lang)

    try:
        raw = source.read_url(track.url)
    except DownloadError as exc:
        raise CaptionsUnavailableError(f"Caption download failed: {exc.message}") from exc

    segments = merge_segments(parse_json3(raw))
    if len(segments) < MIN_SEGMENTS or sum(len(s.text) for s in segments) < MIN_CHARS:
        raise CaptionsUnavailableError("The captions are empty or too short to use.")
    logger.info("Captions: %d segments from %d bytes", len(segments), len(raw))
    return CaptionResult(Transcript(language=_base(track.lang) or "", segments=segments),
                         track.kind, track.lang, len(raw))

"""Shared data structures passed between pipeline stages."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class TranscriptSegment:
    start: float  # seconds
    end: float
    text: str


@dataclass
class Transcript:
    language: str
    segments: List[TranscriptSegment] = field(default_factory=list)


@dataclass
class Moment:
    start: float  # seconds
    end: float
    title: str
    reason: str = ""
    score: float = 0.0


@dataclass
class ProcessingSession:
    """One request to turn a YouTube URL into clips of a chosen length."""
    url: str
    clip_duration: int  # target seconds per clip (validated)
    session_id: str = ""
    max_moments: Optional[int] = None  # None = use settings.max_moments
    moment_prompt: Optional[str] = None  # user steer for what AI should look for, e.g. "funny moments"
    manual_ranges: Optional[List[Tuple[float, float]]] = None  # user-picked (start, end) seconds;
    # when set, AI moment detection is skipped entirely and these exact ranges are clipped instead


@dataclass
class ClipInfo:
    path: Path
    start: float             # seconds in the source video
    end: float
    title: str
    reason: str = ""
    method: str = ""         # "ffmpeg-range" or "yt-dlp-section"
    size_bytes: int = 0
    duration: Optional[float] = None   # measured with ffprobe, if available
    input_bytes_read: Optional[int] = None  # network bytes FFmpeg read (measure mode)


@dataclass
class PipelineResult:
    session: ProcessingSession
    video_id: str
    transcript_method: str   # youtube_captions_manual | youtube_captions_auto | whisper_audio | cached
    transcript_path: Path
    moments: List[Moment] = field(default_factory=list)
    clips: List[ClipInfo] = field(default_factory=list)
    shorts: List[Path] = field(default_factory=list)  # final vertical, captioned outputs
    moments_path: Optional[Path] = None
    stats: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session.session_id,
            "video_id": self.video_id,
            "clip_duration": self.session.clip_duration,
            "transcript_method": self.transcript_method,
            "transcript_path": str(self.transcript_path),
            "moments": [{"title": m.title, "start": m.start, "end": m.end, "reason": m.reason}
                        for m in self.moments],
            "clips": [{"path": str(c.path), "title": c.title, "start": c.start, "end": c.end,
                       "duration": c.duration, "size_bytes": c.size_bytes, "method": c.method}
                      for c in self.clips],
            "shorts": [str(p) for p in self.shorts],
            "stats": self.stats,
        }

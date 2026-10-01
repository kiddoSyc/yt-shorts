"""Cuts moments out of the source video with FFmpeg (no captions, no vertical crop yet).

Each clip is re-encoded (H.264 CRF 18 + AAC 192k) so cuts are frame-accurate
rather than snapping to the nearest keyframe, while keeping quality visually
close to the source. Clips are written to settings.clips_dir.
"""
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional

from app.config import Settings, get_settings
from app.exceptions import ClippingError
from app.models import ClipInfo, Moment
from app.services.downloader import StreamInfo, check_ffmpeg, make_temp_dir

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_MIN_CLIP_BYTES = 1024


def safe_slug(text: str, max_len: int = 40) -> str:
    """Lowercase ASCII letters/digits/hyphens only; never empty."""
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")[:max_len].strip("-")
    return slug or "clip"


def clip_filename(video_path: Path, index: int, moment: Moment) -> str:
    """e.g. MvWjV_up8Gs_01_big-reveal_12s-48s.mp4 (index + times keep names unique)."""
    return (f"{safe_slug(video_path.stem, 30)}_{index:02d}_{safe_slug(moment.title)}"
            f"_{int(moment.start)}s-{int(round(moment.end))}s.mp4")


def encode_args(settings: Optional[Settings] = None) -> List[str]:
    """Video/audio encode settings shared by both the local-file and remote-range cut paths."""
    settings = settings or get_settings()
    return ["-c:v", "libx264", "-preset", settings.video_preset, "-crf", str(settings.video_crf),
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]


def build_ffmpeg_command(ffmpeg: str, video_path: Path, moment: Moment, output: Path,
                         settings: Optional[Settings] = None) -> List[str]:
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{moment.start:.3f}",
        "-i", str(video_path),
        "-t", f"{moment.end - moment.start:.3f}",
        *encode_args(settings),
        str(output),
    ]


def clip_moments(
    video_path: Path,
    moments: List[Moment],
    settings: Optional[Settings] = None,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> List[Path]:
    """Cut each moment from `video_path` and return the created clip paths.

    A clip that fails is logged and skipped; ClippingError is raised only if no
    clip could be produced. `runner` is injectable for tests.
    """
    settings = settings or get_settings()
    video_path = Path(video_path)
    if not video_path.is_file():
        raise ClippingError(f"Video file not found: {video_path}")
    if not moments:
        logger.warning("clip_moments called with no moments; nothing to do")
        return []

    ffmpeg = check_ffmpeg(settings)
    settings.clips_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Clipping %d moment(s) from %s", len(moments), video_path.name)

    clips: List[Path] = []
    for i, moment in enumerate(moments, start=1):
        if moment.end <= moment.start or moment.start < 0:
            logger.error("Skipping moment %d: invalid range %.2f-%.2f", i, moment.start, moment.end)
            continue
        final = settings.clips_dir / clip_filename(video_path, i, moment)
        temp = final.with_name(final.stem + ".tmp.mp4")
        cmd = build_ffmpeg_command(ffmpeg, video_path, moment, temp, settings)
        timeout = max(300.0, (moment.end - moment.start) * 20)
        try:
            result = runner(cmd, capture_output=True, text=True, timeout=timeout)
            if result.returncode != 0:
                raise ClippingError((result.stderr or "").strip()[-500:] or "FFmpeg failed")
            if not temp.exists() or temp.stat().st_size < _MIN_CLIP_BYTES:
                raise ClippingError("FFmpeg produced an empty file (is the range inside the video?)")
            temp.replace(final)
        except subprocess.TimeoutExpired:
            logger.error("Clip %d timed out after %.0fs", i, timeout)
            temp.unlink(missing_ok=True)
            continue
        except (ClippingError, OSError) as exc:
            logger.error("Clip %d (%.1f-%.1fs) failed: %s", i, moment.start, moment.end,
                         getattr(exc, "message", exc))
            temp.unlink(missing_ok=True)
            continue
        logger.info("Clip %d saved: %s (%.1f MB)", i, final.name, final.stat().st_size / 1e6)
        clips.append(final)

    if not clips:
        raise ClippingError("No clips could be created. See logs for FFmpeg details.")
    return clips


# ---------------------------------------------------------------------------
# Remote clipping: cut straight from YouTube's media URLs. FFmpeg seeks with HTTP
# range requests, so only the bytes for each clip are downloaded - never the full video.
# ---------------------------------------------------------------------------

_STATS_RE = re.compile(r"Statistics:\s+(\d+)\s+bytes read")
_DROP_HEADERS = {"accept-encoding", "range", "content-length", "host"}  # would corrupt raw media


def _input_args(url: str, headers: Dict[str, str], start: float) -> List[str]:
    args = ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
            "-rw_timeout", "30000000"]
    clean = {k: v for k, v in (headers or {}).items() if k.lower() not in _DROP_HEADERS}
    ua = next((v for k, v in clean.items() if k.lower() == "user-agent"), None)
    if ua:
        args += ["-user_agent", ua]
    rest = "".join(f"{k}: {v}\r\n" for k, v in clean.items() if k.lower() != "user-agent")
    if rest:
        args += ["-headers", rest]
    return args + ["-ss", f"{start:.3f}", "-i", url]


def build_remote_ffmpeg_command(ffmpeg: str, stream: StreamInfo, moment: Moment, output: Path,
                                measure: bool = False, settings: Optional[Settings] = None) -> List[str]:
    """FFmpeg command that reads only [moment.start, moment.end] from remote URLs."""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "debug" if measure else "error", "-y"]
    cmd += _input_args(stream.video_url, stream.video_headers, moment.start)
    if stream.audio_url:
        cmd += _input_args(stream.audio_url, stream.audio_headers, moment.start)
        maps = ["-map", "0:v:0", "-map", "1:a:0"]
    else:
        maps = ["-map", "0:v:0", "-map", "0:a:0"]
    return cmd + ["-t", f"{moment.end - moment.start:.3f}", *maps, *encode_args(settings), str(output)]


def parse_input_bytes(stderr: str, output_size: int) -> Optional[int]:
    """Sum FFmpeg's per-input 'bytes read' statistics (debug log), ignoring the output file.

    +faststart makes FFmpeg re-read its own output, which shows up as one more
    statistic; it is the one closest to the output file size.
    """
    values = [int(v) for v in _STATS_RE.findall(stderr or "")]
    if not values:
        return None
    if len(values) > 1:
        values.remove(min(values, key=lambda v: abs(v - output_size)))
    return sum(values)


def probe_duration(path: Path, settings: Optional[Settings] = None) -> Optional[float]:
    """Clip length in seconds via ffprobe (None if ffprobe is unavailable)."""
    settings = settings or get_settings()
    ffmpeg = shutil.which(settings.ffmpeg_path)
    candidates = [shutil.which("ffprobe")]
    if ffmpeg:
        candidates.append(str(Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix)))
    for probe in candidates:
        if not probe or not Path(probe).exists():
            continue
        try:
            out = subprocess.run(
                [probe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", str(path)],
                capture_output=True, text=True, timeout=30)
            return round(float(out.stdout.strip()), 2)
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
    return None


def clip_remote_moments(
    stream: StreamInfo,
    moments: List[Moment],
    settings: Optional[Settings] = None,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    section_fallback: Optional[Callable[[Moment, Path], Path]] = None,
    measure: bool = False,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> List[ClipInfo]:
    """Cut each moment directly from the remote stream into settings.clips_dir.

    If FFmpeg cannot read the URLs, `section_fallback(moment, dest_dir)` (yt-dlp's own
    section download) is tried for that clip. A failing clip is skipped; ClippingError is
    raised only if no clip could be produced. With measure=True, FFmpeg's own read
    statistics are recorded in ClipInfo.input_bytes_read. If given, on_progress(i, total)
    is called after each moment is attempted (whether it succeeded or was skipped).
    """
    settings = settings or get_settings()
    if not moments:
        logger.warning("clip_remote_moments called with no moments; nothing to do")
        return []
    ffmpeg = check_ffmpeg(settings)
    settings.clips_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(stream.video_id)
    logger.info("Cutting %d clip(s) from remote stream %s (range requests, no full download)",
                len(moments), stream.video_id)

    clips: List[ClipInfo] = []
    total = len(moments)
    for i, moment in enumerate(moments, start=1):
        if moment.end <= moment.start or moment.start < 0:
            logger.error("Skipping moment %d: invalid range %.2f-%.2f", i, moment.start, moment.end)
            if on_progress:
                on_progress(i, total)
            continue
        final = settings.clips_dir / clip_filename(stem, i, moment)
        temp = final.with_name(final.stem + ".tmp.mp4")
        cmd = build_remote_ffmpeg_command(ffmpeg, stream, moment, temp, measure=measure, settings=settings)
        timeout = max(600.0, (moment.end - moment.start) * 30)
        method, bytes_read = "ffmpeg-range", None
        try:
            result = runner(cmd, capture_output=True, text=True, timeout=timeout)
            if result.returncode != 0:
                raise ClippingError((result.stderr or "").strip()[-500:] or "FFmpeg failed")
            if not temp.exists() or temp.stat().st_size < _MIN_CLIP_BYTES:
                raise ClippingError("FFmpeg produced an empty file")
            if measure:
                bytes_read = parse_input_bytes(result.stderr, temp.stat().st_size)
            temp.replace(final)
        except (ClippingError, OSError, subprocess.TimeoutExpired) as exc:
            temp.unlink(missing_ok=True)
            logger.warning("Range clip %d failed (%s)", i, getattr(exc, "message", exc))
            if section_fallback is None:
                if on_progress:
                    on_progress(i, total)
                continue
            method = "yt-dlp-section"
            tmp_dir = make_temp_dir(settings, "section")
            try:
                produced = section_fallback(moment, tmp_dir)
                shutil.move(str(produced), str(final))
            except Exception as fb_exc:  # any failure here just skips this clip
                logger.error("Clip %d fallback failed: %s", i, getattr(fb_exc, "message", fb_exc))
                if on_progress:
                    on_progress(i, total)
                continue
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
        info = ClipInfo(path=final, start=moment.start, end=moment.end, title=moment.title,
                        reason=moment.reason, method=method, size_bytes=final.stat().st_size,
                        duration=probe_duration(final, settings), input_bytes_read=bytes_read)
        logger.info("Clip %d saved: %s (%.1f MB, %s, %s s)", i, final.name,
                    info.size_bytes / 1e6, method, info.duration)
        clips.append(info)
        if on_progress:
            on_progress(i, total)

    if not clips:
        raise ClippingError("No clips could be created. See logs for FFmpeg details.")
    return clips

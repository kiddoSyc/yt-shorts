"""Turns a cut clip into the final vertical (9:16) Short with burned-in captions.

This runs entirely on the already-downloaded clip files in settings.clips_dir - it
reads no network data, so it doesn't affect the pipeline's low-data budget.

Vertical formatting: scale to cover 1080x1920 then center-crop to exactly that size.
This never letterboxes (no wasted black bars) and never re-encodes a second background
layer, so it stays cheap on CPU and keeps quality close to the source. The crop is
centered, which keeps typical talking-head/interview footage in frame; content pinned
hard to one edge of a wide source can lose that edge (see README limitations).

Captions are burned in via FFmpeg's `subtitles` filter (libass). The clip's own audio
is copied, not re-encoded, so it stays byte-identical and in sync.

Output: settings.shorts_dir/<clip stem>_short.mp4 - kept separate from the raw clips
in settings.clips_dir.
"""
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, List, Optional

from app.config import Settings, get_settings
from app.exceptions import CaptionError, ClippingError, DependencyMissingError
from app.models import ClipInfo, Transcript
from app.services.captions import write_caption_file
from app.services.downloader import check_ffmpeg

logger = logging.getLogger(__name__)

_CAPTION_FILENAME = "captions.ass"  # kept short & ASCII; ffmpeg is run with cwd=tmp dir
_MIN_OUTPUT_BYTES = 1024


def short_filename(clip_path: Path) -> str:
    return f"{clip_path.stem}_short.mp4"


def build_vertical_filter(settings: Settings, caption_file: Optional[str]) -> str:
    """scale-to-cover + center-crop to shorts_width x shorts_height, then optionally burn captions."""
    w, h = settings.shorts_width, settings.shorts_height
    parts = [
        f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos",
        f"crop={w}:{h}",
        "setsar=1",
    ]
    if caption_file:
        parts.append(f"subtitles={caption_file}")
    return ",".join(parts)


def build_ffmpeg_command(ffmpeg: str, clip_path: Path, output: Path, settings: Settings,
                         caption_file: Optional[str]) -> List[str]:
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(clip_path),
        "-vf", build_vertical_filter(settings, caption_file),
        "-c:v", "libx264", "-preset", settings.video_preset, "-crf", str(settings.video_crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",  # already AAC from the clipping step; keeps audio in sync, no re-encode
        "-movflags", "+faststart",
        str(output),
    ]


def _format_failure_message(result: subprocess.CompletedProcess) -> str:
    """Always include the exit code - an empty stderr with a negative/137 code almost
    always means the OS killed FFmpeg (most commonly: out of memory), not a real encode
    error, and that distinction is the single most useful thing for diagnosing this."""
    stderr = (result.stderr or "").strip()[-500:]
    code = result.returncode
    if not stderr:
        if code == -9 or code == 137:
            return (f"FFmpeg was killed (exit code {code}) with no error output - this is almost "
                    "always the OS killing it for using too much memory (OOM), not a real encoding "
                    "error. Try a lower MAX_VIDEO_HEIGHT, a smaller WHISPER_MODEL_SIZE, or a host "
                    "with more RAM.")
        if code < 0:
            return f"FFmpeg was killed by signal {-code} with no error output."
        return f"FFmpeg failed while formatting (exit code {code}, no error output)."
    return f"{stderr} (exit code {code})"


def format_short(
    clip: ClipInfo,
    transcript: Optional[Transcript],
    settings: Optional[Settings] = None,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Path:
    """Produce one vertical, captioned Short from an already-cut clip.

    Raises ClippingError if FFmpeg fails; CaptionError only for a caption-file
    write failure (formatting still proceeds without captions in that case).
    """
    settings = settings or get_settings()
    clip_path = Path(clip.path)
    if not clip_path.is_file():
        raise ClippingError(f"Clip file not found: {clip_path}")

    ffmpeg = check_ffmpeg(settings)
    settings.shorts_dir.mkdir(parents=True, exist_ok=True)
    final = settings.shorts_dir / short_filename(clip_path)
    temp_out = final.with_name(final.stem + ".tmp.mp4")

    settings.tmp_dir.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="short_", dir=settings.tmp_dir))
    caption_arg: Optional[str] = None
    try:
        if settings.captions_enabled and transcript is not None:
            try:
                caption_path = write_caption_file(
                    transcript, clip.start, clip.end, work_dir / _CAPTION_FILENAME, settings)
                if caption_path is not None:
                    caption_arg = _CAPTION_FILENAME  # relative: cwd is work_dir, avoids path-escaping issues
            except CaptionError as exc:
                logger.warning("Captions skipped for %s: %s", clip_path.name, exc.message)

        cmd = build_ffmpeg_command(ffmpeg, clip_path.resolve(), temp_out.resolve(), settings, caption_arg)
        duration = clip.duration or max((clip.end - clip.start), 1.0)
        timeout = max(300.0, duration * 20)
        try:
            result = runner(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(work_dir))
        except subprocess.TimeoutExpired:
            raise ClippingError(f"Formatting timed out after {timeout:.0f}s for {clip_path.name}") from None
        if result.returncode != 0:
            raise ClippingError(_format_failure_message(result))
        if not temp_out.exists() or temp_out.stat().st_size < _MIN_OUTPUT_BYTES:
            raise ClippingError("FFmpeg produced an empty file while formatting")
        temp_out.replace(final)
    except (ClippingError, DependencyMissingError, OSError):
        temp_out.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    logger.info("Short ready: %s (%.1f MB, %sx%s%s)", final.name, final.stat().st_size / 1e6,
               settings.shorts_width, settings.shorts_height, " + captions" if caption_arg else "")
    return final


def format_shorts(
    clips: List[ClipInfo],
    transcript: Optional[Transcript],
    settings: Optional[Settings] = None,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> List[Path]:
    """Format every clip. A clip that fails is logged and skipped, not fatal to the batch.

    If given, on_progress(i, total) is called after each clip is attempted.
    """
    settings = settings or get_settings()
    if not clips:
        return []
    outputs: List[Path] = []
    total = len(clips)
    for i, clip in enumerate(clips, start=1):
        try:
            outputs.append(format_short(clip, transcript, settings, runner=runner))
        except (ClippingError, DependencyMissingError) as exc:
            logger.error("Short %d/%d failed for %s: %s", i, len(clips), clip.path,
                        getattr(exc, "message", exc))
        finally:
            if on_progress:
                on_progress(i, total)
    return outputs


def probe_resolution(path: Path, settings: Optional[Settings] = None) -> Optional[str]:
    """'{width}x{height}' via ffprobe, for reporting/testing (None if ffprobe is unavailable)."""
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
                [probe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                 "stream=width,height", "-of", "csv=s=x:p=0", str(path)],
                capture_output=True, text=True, timeout=30)
            value = out.stdout.strip()
            if value:
                return value
        except (OSError, subprocess.SubprocessError):
            continue
    return None

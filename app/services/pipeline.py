"""Low-data pipeline for one processing session:

    YouTube URL -> captions (else audio-only + Whisper) -> Gemini timestamps
                -> FFmpeg cuts only those ranges from the remote stream -> clips

The full video is never downloaded.
"""
import json
import logging
import shutil
import subprocess
import time
from typing import Any, Callable, Optional, Tuple

from app.config import Settings, get_settings
from app.exceptions import CaptionsUnavailableError, TranscriptionError
from app.models import PipelineResult, ProcessingSession, Transcript
from app.services.clipping import clip_remote_moments
from app.services.downloader import (YouTubeSource, check_ffmpeg, download_audio_only,
                                     download_section, make_temp_dir)
from app.services.moment_detection import get_moment_detector
from app.services.moment_detection.base import MomentDetector
from app.services.shorts import format_shorts
from app.services.transcription import (load_transcript, save_transcript, transcribe,
                                        transcript_path_for)
from app.services.youtube_transcript import fetch_caption_transcript
from pathlib import Path

logger = logging.getLogger(__name__)

_VALID_SOURCES = ("auto", "captions", "whisper")


def _transcript_via_whisper(source: YouTubeSource, settings: Settings, ydl_factory: Any,
                            model_factory: Any) -> Tuple[Transcript, int]:
    """Audio-only download -> local Whisper -> delete the temp audio. Returns (transcript, audio_bytes)."""
    tmp = make_temp_dir(settings, source.video_id)
    try:
        audio = download_audio_only(source.url, settings, dest_dir=tmp, ydl_factory=ydl_factory)
        audio_bytes = audio.stat().st_size
        transcript = transcribe(audio, settings, model_factory=model_factory)
        return transcript, audio_bytes
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # temporary audio is always removed
        logger.info("Temporary audio deleted")


def _get_transcript(source: YouTubeSource, settings: Settings, use_cache: bool,
                    ydl_factory: Any, model_factory: Any) -> Tuple[Transcript, str, Path, dict]:
    """Returns (transcript, method, transcript_path, data stats)."""
    path = transcript_path_for(Path(source.video_id), settings)
    stats = {"caption_bytes": 0, "audio_bytes": 0}

    if use_cache and path.is_file():
        try:
            transcript = load_transcript(path)
            if transcript.segments:
                method = json.loads(path.read_text(encoding="utf-8")).get("method", "cached")
                logger.info("Reusing saved transcript %s (%s)", path.name, method)
                return transcript, f"cached ({method})", path, stats
        except (TranscriptionError, ValueError):
            logger.warning("Saved transcript unreadable; regenerating")

    mode = settings.transcript_source.lower()
    if mode not in _VALID_SOURCES:
        raise TranscriptionError(f"TRANSCRIPT_SOURCE must be one of {_VALID_SOURCES}, got '{mode}'.")

    transcript: Optional[Transcript] = None
    method = ""
    if mode in ("auto", "captions"):
        try:
            result = fetch_caption_transcript(source)
            transcript, method = result.transcript, f"youtube_captions_{result.kind}"
            stats["caption_bytes"] = result.bytes_downloaded
        except CaptionsUnavailableError as exc:
            if mode == "captions":
                raise
            logger.info("No YouTube captions (%s) - falling back to audio-only + Whisper", exc.message)

    if transcript is None:
        transcript, stats["audio_bytes"] = _transcript_via_whisper(
            source, settings, ydl_factory, model_factory)
        method = "whisper_audio"

    save_transcript(transcript, Path(source.video_id), settings, method=method)
    return transcript, method, path, stats


def run_session(
    session: ProcessingSession,
    settings: Optional[Settings] = None,
    *,
    ydl_factory: Optional[Callable[[dict], Any]] = None,
    detector: Optional[MomentDetector] = None,
    model_factory: Optional[Callable[[Settings], Any]] = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    use_cache: bool = True,
    measure: bool = False,
    on_progress: Optional[Callable[[str, dict], None]] = None,
) -> PipelineResult:
    """Run the whole pipeline for `session`. Everything injectable so it can be tested offline.

    If given, on_progress(stage, data) is called as the pipeline advances through:
    "starting" -> "transcript" -> "moments" -> "clipping" (data: done/total, repeated)
    -> "formatting" (data: done/total, repeated) -> "done".
    """
    settings = settings or get_settings()
    settings.ensure_dirs()
    check_ffmpeg(settings)  # fail before spending any data
    started = time.time()
    logger.info("Session %s: %s, target clip length %ss",
                session.session_id, session.url, session.clip_duration)
    notify = on_progress or (lambda stage, data: None)
    notify("starting", {})

    with YouTubeSource(session.url, settings, ydl_factory=ydl_factory) as source:
        transcript, method, transcript_path, stats = _get_transcript(
            source, settings, use_cache, ydl_factory, model_factory)
        notify("transcript", {"method": method})

        detector = detector or get_moment_detector()
        target_moments = session.max_moments or settings.max_moments
        moments = detector.detect_moments(
            transcript, max_moments=target_moments, target_seconds=session.clip_duration)
        notify("moments", {"count": len(moments)})

        moments_path = settings.output_dir / f"{source.video_id}_{session.clip_duration}s_moments.json"
        moments_path.write_text(json.dumps(
            [{"title": m.title, "start": m.start, "end": m.end, "reason": m.reason} for m in moments],
            ensure_ascii=False, indent=2), encoding="utf-8")

        stream = source.stream()
        clips = clip_remote_moments(
            stream, moments, settings, runner=runner, measure=measure,
            section_fallback=lambda moment, dest: download_section(
                source.url, moment.start, moment.end, dest, settings, ydl_factory=ydl_factory),
            on_progress=lambda i, n: notify("clipping", {"done": i, "total": n}))

        # Vertical (9:16) formatting + burned-in captions. Runs on the local clip files
        # already produced above, so it uses no additional network data. A clip that
        # fails to format is logged and skipped; the raw clip in clips_dir still exists.
        shorts = format_shorts(clips, transcript, settings, runner=runner,
                               on_progress=lambda i, n: notify("formatting", {"done": i, "total": n}))

    clip_bytes = sum(c.size_bytes for c in clips)
    read = [c.input_bytes_read for c in clips if c.input_bytes_read is not None]
    stats.update({
        "full_video_downloaded": False,
        "clip_output_bytes": clip_bytes,
        "clip_input_bytes_read": sum(read) if len(read) == len(clips) else None,
        "full_video_size_estimate": stream.full_size_estimate,
        "source_video_height": stream.height,
        "video_duration": stream.duration,
        "shorts_created": len(shorts),
        "elapsed_seconds": round(time.time() - started, 1),
    })
    logger.info("Session %s done: %d clip(s), %d short(s), method=%s",
                session.session_id, len(clips), len(shorts), method)
    notify("done", {"clips": len(clips), "shorts": len(shorts)})
    return PipelineResult(session=session, video_id=source.video_id, transcript_method=method,
                          transcript_path=transcript_path, moments=moments, clips=clips,
                          shorts=shorts, moments_path=moments_path, stats=stats)

"""Local Whisper transcription with faster-whisper (no external services).

- The model is imported and loaded only when transcription is requested, then
  cached for later calls. Model name/device/precision come from .env
  (WHISPER_MODEL_SIZE, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE).
- Audio is decoded by faster-whisper itself, so the video file can be passed directly.
- Transcripts are saved as JSON in settings.transcripts_dir.
"""
import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

from app.config import Settings, get_settings
from app.exceptions import DependencyMissingError, TranscriptionError
from app.models import Transcript, TranscriptSegment

logger = logging.getLogger(__name__)

_model_lock = threading.Lock()
_model_cache: dict = {}  # (size, device, compute_type) -> WhisperModel


def _load_model(settings: Settings) -> Any:
    """Create a faster-whisper model (downloads it on first use)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise DependencyMissingError(
            "faster-whisper is not installed. Run: pip install -r requirements.txt"
        ) from None
    logger.info("Loading Whisper model '%s' (device=%s, compute_type=%s). "
                "The first run downloads the model.",
                settings.whisper_model_size, settings.whisper_device,
                settings.whisper_compute_type)
    return WhisperModel(
        settings.whisper_model_size,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )


def _get_model(settings: Settings, model_factory: Optional[Callable[[Settings], Any]]) -> Any:
    if model_factory is not None:  # injected (tests): no caching
        return model_factory(settings)
    key = (settings.whisper_model_size, settings.whisper_device, settings.whisper_compute_type)
    with _model_lock:
        if key not in _model_cache:
            _model_cache[key] = _load_model(settings)
        return _model_cache[key]


def unload_model() -> None:
    """Drop cached models to free RAM."""
    with _model_lock:
        _model_cache.clear()


def _run_model(model: Any, video_path: Path, vad_filter: bool) -> Tuple[list, Any]:
    """One transcription pass. Returns (non-empty segments, info)."""
    # beam_size=1 keeps CPU time/RAM low on modest machines.
    raw_segments, info = model.transcribe(str(video_path), beam_size=1, vad_filter=vad_filter)
    segments = []
    for seg in raw_segments:  # lazy generator: decoding happens here
        text = (seg.text or "").strip()
        if text:
            segments.append(TranscriptSegment(
                start=round(float(seg.start), 2),
                end=round(float(seg.end), 2),
                text=text,
            ))
    return segments, info


def transcribe(
    video_path: Path,
    settings: Optional[Settings] = None,
    *,
    model_factory: Optional[Callable[[Settings], Any]] = None,
) -> Transcript:
    """Return a timestamped transcript (segments with start, end, text) for `video_path`.

    `model_factory(settings)` may return a faster-whisper-like model; it exists
    so tests can run without downloading a model.
    """
    settings = settings or get_settings()
    video_path = Path(video_path)
    if not video_path.is_file():
        raise TranscriptionError(f"Media file not found: {video_path}")

    model = _get_model(settings, model_factory)
    logger.info("Transcribing %s with model '%s'", video_path.name, settings.whisper_model_size)
    try:
        use_vad = settings.whisper_vad_filter
        segments, info = _run_model(model, video_path, use_vad)
        if not segments and use_vad:
            # The voice-activity filter can discard quiet/noisy speech; try once without it.
            logger.warning("No speech found with the VAD filter on; retrying without it")
            segments, info = _run_model(model, video_path, False)
    except (DependencyMissingError, TranscriptionError):
        raise
    except Exception as exc:
        logger.exception("Transcription failed for %s", video_path.name)
        raise TranscriptionError(
            "Transcription failed. If this is the first run, check your internet "
            "connection (the Whisper model must be downloaded once). See logs for details."
        ) from exc

    if not segments:
        raise TranscriptionError(
            "No speech was detected in this video. It may be music-only, silent, or have "
            "very quiet audio. Try a video with clear spoken words."
        )

    language = getattr(info, "language", "") or ""
    logger.info("Transcribed %d segments (language=%s)", len(segments), language or "unknown")
    return Transcript(language=language, segments=segments)


def transcript_path_for(video_path: Path, settings: Optional[Settings] = None) -> Path:
    """Where the JSON transcript for `video_path` is stored."""
    settings = settings or get_settings()
    return settings.transcripts_dir / f"{Path(video_path).stem}.json"


def save_transcript(
    transcript: Transcript,
    video_path: Path,
    settings: Optional[Settings] = None,
    method: Optional[str] = None,
) -> Path:
    """Write the transcript as UTF-8 JSON and return the file path."""
    settings = settings or get_settings()
    out = transcript_path_for(video_path, settings)
    payload = {
        "source": Path(video_path).name,
        "model": settings.whisper_model_size,
        **({"method": method} if method else {}),
        "language": transcript.language,
        "segments": [{"start": s.start, "end": s.end, "text": s.text}
                     for s in transcript.segments],
    }
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(out)
    except OSError as exc:
        logger.error("Could not save transcript to %s: %s", out, exc)
        raise TranscriptionError(f"Could not save transcript to {out}.") from exc
    logger.info("Saved transcript: %s", out)
    return out


def load_transcript(path: Path) -> Transcript:
    """Read a transcript JSON file written by save_transcript()."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return Transcript(
            language=data.get("language", ""),
            segments=[TranscriptSegment(start=float(s["start"]), end=float(s["end"]),
                                        text=str(s["text"])) for s in data["segments"]],
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise TranscriptionError(f"Could not read transcript file: {path}") from exc


def transcribe_and_save(
    video_path: Path,
    settings: Optional[Settings] = None,
    *,
    model_factory: Optional[Callable[[Settings], Any]] = None,
) -> Tuple[Transcript, Path]:
    """Transcribe `video_path`, save the JSON, and return (transcript, json_path)."""
    settings = settings or get_settings()
    transcript = transcribe(video_path, settings, model_factory=model_factory)
    return transcript, save_transcript(transcript, video_path, settings)

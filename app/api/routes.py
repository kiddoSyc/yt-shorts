"""HTTP routes."""
import http.cookiejar
import importlib.util
import shutil
from pathlib import Path

from fastapi import APIRouter

from app.api.schemas import ProcessRequest
from app.config import get_settings
from app.services.pipeline import run_session
from app.services.session import new_session

router = APIRouter()


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


@router.get("/health")
def health() -> dict:
    """Liveness check."""
    return {"status": "ok"}


def _cookies_status(s) -> dict:
    """Checks the configured cookies file without ever returning its contents."""
    if not s.ytdlp_cookies_file:
        return {"configured": False}
    path = Path(s.ytdlp_cookies_file)
    if not path.is_file():
        return {"configured": True, "file_found": False}
    try:
        jar = http.cookiejar.MozillaCookieJar(str(path))
        jar.load(ignore_discard=True, ignore_expires=True)
        domains = {c.domain.lstrip(".") for c in jar}
        youtube_domains = {d for d in domains if "youtube.com" in d or "google.com" in d}
        return {
            "configured": True,
            "file_found": True,
            "parses_correctly": True,
            "cookie_count": len(jar),
            "has_youtube_or_google_cookies": bool(youtube_domains),
        }
    except Exception as exc:  # noqa: BLE001 - this IS the diagnostic, we want the reason
        return {"configured": True, "file_found": True, "parses_correctly": False, "error": str(exc)}


@router.get("/status")
def status() -> dict:
    """Readiness check: reports what is installed/configured. Never returns secrets."""
    s = get_settings()
    return {
        "status": "ok",
        "env": s.app_env,
        "ai_provider": s.ai_provider,
        "checks": {
            "ffmpeg_found": shutil.which(s.ffmpeg_path) is not None,
            "deno_found": shutil.which("deno") is not None,
            "yt_dlp_installed": _installed("yt_dlp"),
            "whisper_installed": _installed("faster_whisper"),
            "gemini_sdk_installed": _installed("google.genai"),
            "gemini_key_set": bool(s.gemini_api_key),
            "cookies": _cookies_status(s),
        },
    }


@router.post("/process")
def process(request: ProcessRequest) -> dict:
    """Run the low-data pipeline for one URL and clip length.

    Synchronous for now: it returns when the clips exist (can take minutes).
    """
    session = new_session(request.url, request.clip_duration)
    return run_session(session).to_dict()

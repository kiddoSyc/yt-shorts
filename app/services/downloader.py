"""Downloads a YouTube video with yt-dlp into settings.downloads_dir.

- Nothing is downloaded at import/startup; yt-dlp is imported lazily.
- Files are named ``<video_id>.mp4`` (the 11-char YouTube id), which is always
  filesystem-safe and lets repeat requests reuse the existing file.
- Resolution is capped by settings.max_video_height to keep downloads small.
"""
import contextlib
import logging
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from app.config import Settings, get_settings
from app.exceptions import DependencyMissingError, DownloadError, InvalidURLError

logger = logging.getLogger(__name__)

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtube-nocookie.com", "www.youtube-nocookie.com",
}
_SHORT_HOST = "youtu.be"
_PATH_PREFIXES = ("shorts", "embed", "live", "v")


def extract_video_id(url: str) -> str:
    """Validate `url` as a single YouTube video URL and return its video id.

    Raises InvalidURLError for anything else (other sites, playlists without a
    video, malformed input).
    """
    if not isinstance(url, str) or not url.strip():
        raise InvalidURLError("URL is empty.")
    raw = url.strip()
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
    except ValueError:
        raise InvalidURLError("URL is malformed.") from None
    if parsed.scheme not in ("http", "https"):
        raise InvalidURLError("URL must start with http:// or https://.")

    video_id = ""
    parts = [p for p in parsed.path.split("/") if p]
    if host == _SHORT_HOST:
        video_id = parts[0] if parts else ""
    elif host in _YOUTUBE_HOSTS:
        if parsed.path.rstrip("/") == "/watch":
            video_id = (parse_qs(parsed.query).get("v") or [""])[0]
        elif len(parts) >= 2 and parts[0] in _PATH_PREFIXES:
            video_id = parts[1]
    else:
        raise InvalidURLError("Only YouTube video URLs are supported.")

    if not _VIDEO_ID_RE.match(video_id):
        raise InvalidURLError("Could not find a valid YouTube video id in the URL.")
    return video_id


def check_ffmpeg(settings: Optional[Settings] = None) -> str:
    """Return the resolved FFmpeg path, or raise DependencyMissingError."""
    settings = settings or get_settings()
    found = shutil.which(settings.ffmpeg_path)
    if not found:
        raise DependencyMissingError(
            f"FFmpeg not found (looked for '{settings.ffmpeg_path}'). Install FFmpeg and "
            "make sure it is on your PATH, or set FFMPEG_PATH in .env."
        )
    return found


class _YtDlpLogger:
    """Routes yt-dlp's own messages into our logging setup."""

    def debug(self, msg: str) -> None:
        if not msg.startswith("[debug]"):
            logger.debug("yt-dlp: %s", msg)

    def info(self, msg: str) -> None:
        logger.debug("yt-dlp: %s", msg)

    def warning(self, msg: str) -> None:
        logger.warning("yt-dlp: %s", msg)

    def error(self, msg: str) -> None:
        logger.error("yt-dlp: %s", msg)


def _format_selector(max_height: int) -> str:
    h = int(max_height)
    # Prefer H.264 (avc1): plays everywhere and is cheap to decode. AV1 often shows
    # audio only in common players. Fall back to any codec if H.264 isn't offered.
    return (
        f"bv*[height<={h}][vcodec^=avc1][ext=mp4]+ba[ext=m4a]"
        f"/b[height<={h}][vcodec^=avc1][ext=mp4]"
        f"/bv*[height<={h}][ext=mp4]+ba[ext=m4a]"
        f"/b[height<={h}][ext=mp4]"
        f"/bv*[height<={h}]+ba"
        f"/b[height<={h}]"
        f"/w"  # last resort: smallest available, never the largest
    )


def build_ydl_options(settings: Settings, ffmpeg_path: str) -> dict:
    """yt-dlp options (pure function so it can be unit-tested)."""
    opts = {
        "format": _format_selector(settings.max_video_height),
        "merge_output_format": "mp4",
        "outtmpl": str(settings.downloads_dir / "%(id)s.%(ext)s"),
        "ffmpeg_location": ffmpeg_path,
        "noplaylist": True,
        "restrictfilenames": True,
        "windowsfilenames": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _YtDlpLogger(),
        "retries": 3,
        "socket_timeout": 30,
    }
    if settings.ytdlp_cookies_file:
        opts["cookiefile"] = settings.ytdlp_cookies_file
    return opts


def _friendly_message(raw: str) -> str:
    low = raw.lower()
    if "private video" in low:
        return "This video is private."
    if "video unavailable" in low or "not available" in low:
        return "This video is unavailable."
    if "confirm you" in low and "bot" in low:
        return ("YouTube is blocking this server as a suspected bot (common on cloud/VPS hosting). "
                "This isn't about the video - it needs YouTube cookies configured on the server "
                "(see the README's Deploying section).")
    if "sign in" in low or ("age" in low and "restrict" in low):
        return "This video requires sign-in or is age-restricted."
    if "live event" in low or "is live" in low:
        return "Live streams are not supported."
    if "429" in low or "too many requests" in low:
        return ("YouTube is rate-limiting this server (HTTP 429). This is common on cloud hosting - "
                "configuring YouTube cookies usually helps (see the README's Deploying section). "
                "Try again in a few minutes either way.")
    if "unable to download" in low or "urlopen" in low or "timed out" in low:
        return "Network error while contacting YouTube. Check your connection and try again."
    return "Download failed. See logs for details."


def download_video(
    url: str,
    settings: Optional[Settings] = None,
    *,
    ydl_factory: Optional[Callable[[dict], Any]] = None,
) -> Path:
    """Download `url` into settings.downloads_dir and return the file path.

    `ydl_factory(options)` must return a yt-dlp-like context manager; it exists
    so tests can run without network or yt-dlp installed.
    """
    settings = settings or get_settings()
    video_id = extract_video_id(url)
    ffmpeg_path = check_ffmpeg(settings)

    settings.downloads_dir.mkdir(parents=True, exist_ok=True)
    target = settings.downloads_dir / f"{video_id}.mp4"
    if target.exists() and target.stat().st_size > 0:
        logger.info("Video %s already downloaded, reusing %s", video_id, target)
        return target

    if ydl_factory is None:
        try:
            import yt_dlp
            from yt_dlp.utils import DownloadError as YtDlpDownloadError
        except ImportError:
            raise DependencyMissingError(
                "yt-dlp is not installed. Run: pip install -r requirements.txt"
            ) from None
        ydl_factory = yt_dlp.YoutubeDL
        errors: tuple = (YtDlpDownloadError,)
    else:
        errors = (Exception,)

    canonical = f"https://www.youtube.com/watch?v={video_id}"
    options = build_ydl_options(settings, ffmpeg_path)
    logger.info("Downloading %s (max height %sp) -> %s",
                video_id, settings.max_video_height, settings.downloads_dir)
    try:
        with ydl_factory(options) as ydl:
            info = ydl.extract_info(canonical, download=False)
            if info.get("is_live"):
                raise DownloadError("Live streams are not supported.")
            ydl.process_ie_result(info, download=True)
    except DownloadError:
        raise
    except errors as exc:
        logger.error("yt-dlp failed for %s: %s", video_id, exc)
        raise DownloadError(_friendly_message(str(exc))) from exc
    except OSError as exc:
        logger.error("Filesystem error while downloading %s: %s", video_id, exc)
        raise DownloadError(f"Could not write to {settings.downloads_dir}.") from exc

    if not target.exists() or target.stat().st_size == 0:
        # Fallback: an unexpected extension (e.g. mkv/webm) if merging to mp4 was skipped.
        others = [p for p in settings.downloads_dir.glob(f"{video_id}.*")
                  if p.suffix not in (".part", ".ytdl") and p.stat().st_size > 0]
        if not others:
            raise DownloadError("Download finished but no video file was produced.")
        target = others[0]
    logger.info("Download complete: %s (%.1f MB)", target, target.stat().st_size / 1e6)
    return target


# ---------------------------------------------------------------------------
# Low-data helpers: metadata only, audio only, and single time ranges.
# None of these downloads the full video.
# ---------------------------------------------------------------------------

_AUDIO_FORMAT = "wa[abr>=40]/wa/ba"  # smallest audio that is still fine for speech recognition


def _load_ytdlp() -> Tuple[Any, tuple]:
    """Import yt-dlp lazily. Returns (YoutubeDL class, error types to catch)."""
    try:
        import yt_dlp
        from yt_dlp import utils
    except ImportError:
        raise DependencyMissingError(
            "yt-dlp is not installed. Run: pip install -r requirements.txt"
        ) from None
    base = getattr(utils, "YoutubeDLError", utils.DownloadError)
    return yt_dlp.YoutubeDL, (base,)


def _has_codec(fmt: dict, key: str) -> bool:
    return fmt.get(key) not in (None, "", "none")


@dataclass
class StreamInfo:
    """Direct media URLs for a video, resolved without downloading any media."""
    video_id: str
    title: str
    duration: Optional[float]
    video_url: str
    video_headers: Dict[str, str] = field(default_factory=dict)
    audio_url: Optional[str] = None       # None when the video URL already contains audio
    audio_headers: Dict[str, str] = field(default_factory=dict)
    height: Optional[int] = None
    full_size_estimate: Optional[int] = None  # bytes the full video would have needed


class YouTubeSource:
    """One yt-dlp metadata fetch, reused for captions and stream URLs.

    Downloads no media. Use as a context manager:
        with YouTubeSource(url) as src:
            info = src.info()
    """

    def __init__(self, url: str, settings: Optional[Settings] = None, *,
                 ydl_factory: Optional[Callable[[dict], Any]] = None) -> None:
        self.settings = settings or get_settings()
        self.video_id = extract_video_id(url)
        self.url = f"https://www.youtube.com/watch?v={self.video_id}"
        self._factory = ydl_factory
        self._errors: tuple = (Exception,) if ydl_factory else ()
        self._stack = contextlib.ExitStack()
        self._ydl: Any = None
        self._info: Optional[dict] = None

    def __enter__(self) -> "YouTubeSource":
        return self

    def __exit__(self, *exc: Any) -> bool:
        self._stack.close()
        return False

    def _open(self) -> Any:
        if self._ydl is None:
            factory = self._factory
            if factory is None:
                factory, self._errors = _load_ytdlp()
            ffmpeg = shutil.which(self.settings.ffmpeg_path) or self.settings.ffmpeg_path
            opts = build_ydl_options(self.settings, ffmpeg)
            opts.update({"skip_download": True, "ignore_no_formats_error": True})
            self._ydl = self._stack.enter_context(factory(opts))
        return self._ydl

    def info(self) -> dict:
        """Video metadata (formats, captions, duration). Fetched once."""
        if self._info is None:
            ydl = self._open()
            logger.info("Fetching metadata for %s (no media download)", self.video_id)
            try:
                info = ydl.extract_info(self.url, download=False)
            except self._errors as exc:
                logger.error("Metadata fetch failed for %s: %s", self.video_id, exc)
                raise DownloadError(_friendly_message(str(exc))) from exc
            if not info:
                raise DownloadError("Could not read video information.")
            if info.get("is_live"):
                raise DownloadError("Live streams are not supported.")
            self._info = info
        return self._info

    def read_url(self, url: str) -> bytes:
        """Fetch a small resource (e.g. a caption file) using yt-dlp's HTTP session."""
        ydl = self._open()
        try:
            response = ydl.urlopen(url)
            try:
                return response.read()
            finally:
                response.close()
        except self._errors as exc:
            raise DownloadError(f"Could not fetch resource: {exc}") from exc

    def stream(self) -> StreamInfo:
        """Direct video (+ audio) URLs chosen by the height-capped, H.264-preferred selector."""
        info = self.info()
        formats = info.get("requested_formats") or [info]
        video = next((f for f in formats if _has_codec(f, "vcodec") and f.get("url")), None)
        if video is None:
            raise DownloadError("No downloadable video format was found for this video.")
        audio = None
        if not _has_codec(video, "acodec"):
            audio = next((f for f in formats if f is not video and _has_codec(f, "acodec")
                          and f.get("url")), None)
            if audio is None:
                raise DownloadError("No audio stream was found for this video.")

        def headers(fmt: dict) -> Dict[str, str]:
            return dict(fmt.get("http_headers") or info.get("http_headers") or {})

        sizes = [f.get("filesize") or f.get("filesize_approx") for f in formats]
        estimate = sum(sizes) if sizes and all(sizes) else None
        return StreamInfo(
            video_id=self.video_id,
            title=str(info.get("title") or self.video_id),
            duration=info.get("duration"),
            video_url=video["url"],
            video_headers=headers(video),
            audio_url=audio["url"] if audio else None,
            audio_headers=headers(audio) if audio else {},
            height=video.get("height"),
            full_size_estimate=estimate,
        )


def download_audio_only(
    url: str,
    settings: Optional[Settings] = None,
    *,
    dest_dir: Path,
    ydl_factory: Optional[Callable[[dict], Any]] = None,
) -> Path:
    """Download only the (lowest practical bitrate) audio track into `dest_dir`.

    The caller is responsible for deleting the file after use.
    """
    settings = settings or get_settings()
    video_id = extract_video_id(url)
    dest_dir.mkdir(parents=True, exist_ok=True)
    options = {
        "format": _AUDIO_FORMAT,
        "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "restrictfilenames": True,
        "windowsfilenames": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _YtDlpLogger(),
        "retries": 3,
        "socket_timeout": 30,
    }
    if settings.ytdlp_cookies_file:
        options["cookiefile"] = settings.ytdlp_cookies_file
    if ydl_factory is None:
        ydl_factory, errors = _load_ytdlp()
    else:
        errors = (Exception,)
    logger.info("Downloading audio only for %s -> %s", video_id, dest_dir)
    try:
        with ydl_factory(options) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            if info.get("is_live"):
                raise DownloadError("Live streams are not supported.")
            ydl.process_ie_result(info, download=True)
    except DownloadError:
        raise
    except errors as exc:
        logger.error("Audio download failed for %s: %s", video_id, exc)
        raise DownloadError(_friendly_message(str(exc))) from exc
    except OSError as exc:
        raise DownloadError(f"Could not write to {dest_dir}.") from exc

    files = [p for p in dest_dir.glob(f"{video_id}.*")
             if p.suffix not in (".part", ".ytdl") and p.stat().st_size > 0]
    if not files:
        raise DownloadError("Audio download finished but no file was produced.")
    logger.info("Audio downloaded: %s (%.1f MB)", files[0].name, files[0].stat().st_size / 1e6)
    return files[0]


def download_section(
    url: str,
    start: float,
    end: float,
    dest_dir: Path,
    settings: Optional[Settings] = None,
    *,
    ydl_factory: Optional[Callable[[dict], Any]] = None,
) -> Path:
    """Fallback: let yt-dlp cut one time range (frame-accurate, re-encoded) into `dest_dir`."""
    settings = settings or get_settings()
    video_id = extract_video_id(url)
    ffmpeg_path = check_ffmpeg(settings)
    dest_dir.mkdir(parents=True, exist_ok=True)
    options = build_ydl_options(settings, ffmpeg_path)
    options["outtmpl"] = str(dest_dir / "section.%(ext)s")
    if ydl_factory is None:
        ydl_factory, errors = _load_ytdlp()
        from yt_dlp.utils import download_range_func
        options["download_ranges"] = download_range_func(None, [(start, end)])
    else:
        errors = (Exception,)
        options["download_ranges"] = [(start, end)]
    options["force_keyframes_at_cuts"] = True
    logger.info("Fallback: yt-dlp section download %s %.1f-%.1fs", video_id, start, end)
    try:
        with ydl_factory(options) as ydl:
            ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
    except errors as exc:
        logger.error("Section download failed for %s: %s", video_id, exc)
        raise DownloadError(_friendly_message(str(exc))) from exc
    except OSError as exc:
        raise DownloadError(f"Could not write to {dest_dir}.") from exc
    exact = dest_dir / "section.mp4"
    files = [exact] if exact.is_file() and exact.stat().st_size > 0 else [
        p for p in sorted(dest_dir.glob("section*"))
        if p.suffix not in (".part", ".ytdl") and p.is_file() and p.stat().st_size > 0]
    if not files:
        raise DownloadError("Section download finished but no file was produced.")
    return files[0]


def make_temp_dir(settings: Settings, prefix: str) -> Path:
    """A fresh directory under data/tmp for temporary media; caller deletes it."""
    settings.tmp_dir.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{prefix}_", dir=settings.tmp_dir))

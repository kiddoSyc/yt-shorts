"""Central configuration, loaded from environment variables / .env."""
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    app_env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"

    # Storage (relative paths are resolved against the project root)
    data_dir: Path = Path("data")
    log_dir: Path = Path("logs")

    # AI provider
    ai_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"

    # Clip length guidance for moment detection (seconds)
    clip_min_seconds: float = Field(15.0, ge=3, le=600)
    clip_max_seconds: float = Field(60.0, ge=5, le=900)

    # Sessions / clip length
    clip_duration_default: int = 60
    clip_duration_min: int = Field(15, ge=5, le=600)
    clip_duration_max: int = Field(180, ge=15, le=900)
    clip_length_tolerance: float = Field(0.2, ge=0.05, le=0.5)  # +/- around the target
    max_moments: int = Field(5, ge=1, le=20)
    max_moments_limit: int = Field(10, ge=1, le=30)  # highest num_clips a caller may request

    # Transcript source: auto = YouTube captions, else audio-only + Whisper
    transcript_source: str = "auto"  # auto | captions | whisper

    # Download
    # Download (raising this improves output quality - clips get upscaled to 1080x1920,
    # so a higher-res source means less upscaling and a sharper final Short - at the cost
    # of more data per clip. 720 is a solid default; drop to 480 to save data/bandwidth.)
    max_video_height: int = Field(720, ge=144, le=2160)

    # Whisper (bigger model = more accurate transcript/captions, slower to run.
    # tiny < base < small < medium < large; "small" is a solid accuracy/speed balance)
    whisper_model_size: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_vad_filter: bool = True  # skip silence; auto-retried without it if nothing is found

    # FFmpeg
    ffmpeg_path: str = "ffmpeg"

    # Video encode quality (used for both the raw clip cut and the final vertical Short).
    # Lower crf = higher quality/bigger files (18 is near-visually-lossless; 23 is typical
    # "good enough" web quality). Slower presets compress better at the same crf (smaller
    # files, same quality) but take longer: veryfast < fast < medium < slow.
    video_crf: int = Field(17, ge=0, le=51)
    video_preset: str = "fast"

    # yt-dlp / YouTube access. On cloud hosts (shared datacenter IPs), YouTube often shows
    # "Sign in to confirm you're not a bot" or rate-limits with HTTP 429. Exporting cookies
    # from a real, logged-in YouTube session and pointing this at that file fixes most of
    # these - see the README's "Deploying" section for how to export one.
    ytdlp_cookies_file: str = ""
    # Alternative for hosts with no persistent file storage (e.g. Railway): paste the full
    # cookies.txt content into this one env var instead. Written to ytdlp_cookies_file (or a
    # default path under data_dir) once at startup if that path isn't already set.
    ytdlp_cookies_content: str = ""

    # Vertical Shorts formatting (final output, 9:16)
    shorts_width: int = Field(1080, ge=240, le=2160)
    shorts_height: int = Field(1920, ge=426, le=3840)

    # Burned-in captions
    captions_enabled: bool = True
    caption_font_name: str = "DejaVu Sans"
    caption_font_size: int = Field(64, ge=20, le=160)
    caption_max_chars_per_line: int = Field(21, ge=8, le=60)
    caption_max_lines: int = Field(2, ge=1, le=4)
    # Distance from the bottom edge, so text clears phone-app UI (share/like buttons etc.)
    caption_margin_v: int = Field(260, ge=0, le=1000)

    def resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else BASE_DIR / path

    @property
    def downloads_dir(self) -> Path:
        return self.resolve(self.data_dir) / "downloads"

    @property
    def transcripts_dir(self) -> Path:
        return self.resolve(self.data_dir) / "transcripts"

    @property
    def clips_dir(self) -> Path:
        return self.resolve(self.data_dir) / "clips"

    @property
    def tmp_dir(self) -> Path:
        return self.resolve(self.data_dir) / "tmp"

    @property
    def output_dir(self) -> Path:
        return self.resolve(self.data_dir) / "output"

    @property
    def logs_dir(self) -> Path:
        return self.resolve(self.log_dir)

    @property
    def shorts_dir(self) -> Path:
        return self.resolve(self.data_dir) / "shorts"

    def ensure_dirs(self) -> None:
        for d in (self.downloads_dir, self.transcripts_dir, self.clips_dir,
                  self.output_dir, self.shorts_dir, self.tmp_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._materialize_cookies_file()

    def _materialize_cookies_file(self) -> None:
        """If YTDLP_COOKIES_CONTENT is set but no file path is, write it to one.
        Lets a host with no persistent file storage (e.g. Railway) pass cookies as plain env text."""
        if self.ytdlp_cookies_content and not self.ytdlp_cookies_file:
            path = self.resolve(self.data_dir) / "cookies.txt"
            path.write_text(normalize_netscape_cookies(self.ytdlp_cookies_content), encoding="utf-8")
            self.ytdlp_cookies_file = str(path)


_NETSCAPE_HEADER = "# Netscape HTTP Cookie File"


def normalize_netscape_cookies(raw: str) -> str:
    """Best-effort repair of a pasted cookies.txt so it still parses after going through a
    web form (copy/paste commonly loses tabs or the header comment). Three fixes:
    - normalizes line endings and strips stray surrounding whitespace/quotes
    - converts a JSON cookie export (e.g. from "EditThisCookie"-style extensions) to Netscape format
    - reconstructs tabs on cookie lines where they were collapsed to spaces, and adds the
      required header line if it's missing
    Lines that don't clearly fit the expected 7-field shape are left untouched rather than guessed at.
    """
    text = raw.strip().strip('"\'')
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text:
        return text

    if text.lstrip().startswith(("[", "{")):
        try:
            text = _cookies_json_to_netscape(json.loads(text))
        except (ValueError, TypeError, KeyError):
            pass  # not actually valid JSON cookies - fall through and let yt-dlp report it

    lines = text.split("\n")
    fixed = []
    for line in lines:
        if not line.strip() or line.startswith("#"):
            fixed.append(line)
            continue
        if "\t" not in line:
            parts = line.split()
            if len(parts) == 7:
                line = "\t".join(parts)
        fixed.append(line)
    text = "\n".join(fixed)

    if not text.startswith(_NETSCAPE_HEADER) and not text.startswith("# HTTP Cookie File"):
        text = f"{_NETSCAPE_HEADER}\n{text}"
    return text + "\n"


def _cookies_json_to_netscape(data: Any) -> str:
    """Convert a JSON cookie export (list of cookie objects) to Netscape TSV format."""
    if not isinstance(data, list):
        raise TypeError("expected a JSON array of cookie objects")
    lines = [_NETSCAPE_HEADER]
    for c in data:
        domain = c["domain"]
        path = c.get("path", "/")
        secure = "TRUE" if c.get("secure") else "FALSE"
        include_sub = "TRUE" if domain.startswith(".") else "FALSE"
        expiry = c.get("expirationDate") or c.get("expires") or 0
        lines.append("\t".join([domain, include_sub, path, secure, str(int(expiry)),
                                c["name"], str(c["value"])]))
    return "\n".join(lines)


@lru_cache
def get_settings() -> Settings:
    return Settings()

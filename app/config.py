"""Central configuration, loaded from environment variables / .env."""
from functools import lru_cache
from pathlib import Path

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


@lru_cache
def get_settings() -> Settings:
    return Settings()

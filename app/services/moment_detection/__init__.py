"""Moment detection package. Use get_moment_detector() to obtain the configured provider."""
from app.config import get_settings
from app.exceptions import ConfigError
from app.services.moment_detection.base import MomentDetector


def get_moment_detector() -> MomentDetector:
    provider = get_settings().ai_provider.lower()
    if provider == "gemini":
        from app.services.moment_detection.gemini import GeminiMomentDetector
        return GeminiMomentDetector()
    raise ConfigError(f"Unknown AI_PROVIDER '{provider}'. Supported: gemini")


__all__ = ["MomentDetector", "get_moment_detector"]

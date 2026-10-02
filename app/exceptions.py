"""Application errors. Each carries an HTTP status code for the API layer."""


class AppError(Exception):
    status_code = 500

    def __init__(self, message: str = "Internal error"):
        super().__init__(message)
        self.message = message


class ConfigError(AppError):
    status_code = 500


class DependencyMissingError(AppError):
    """A required package or external tool (e.g. FFmpeg) is not available."""
    status_code = 503


class NotImplementedYetError(AppError):
    """Raised by placeholder services that are built in a later step."""
    status_code = 501


class InvalidURLError(AppError):
    """The supplied URL is not a valid YouTube video URL."""
    status_code = 400


class InvalidDurationError(AppError):
    """clip_duration is missing, not a whole number, or outside the allowed range."""
    status_code = 400


class InvalidMomentCountError(AppError):
    """num_clips is missing, not a whole number, or outside the allowed range."""
    status_code = 400


class InvalidMomentRangeError(AppError):
    """A manually-specified clip time range is malformed (bad start/end, too long, etc.)."""
    status_code = 400


class InvalidPromptError(AppError):
    """The moment-type prompt hint is not text, or too long."""
    status_code = 400


class JobNotFoundError(AppError):
    """No job exists with the given id (or the server has since restarted - jobs are in-memory)."""
    status_code = 404


class ResourceNotFoundError(AppError):
    """A requested file (clip/short) does not exist or the filename was invalid."""
    status_code = 404


class CaptionsUnavailableError(AppError):
    """No usable YouTube captions for this video (the pipeline falls back to Whisper)."""
    status_code = 404


class DownloadError(AppError):
    status_code = 502


class TranscriptionError(AppError):
    status_code = 500


class MomentDetectionError(AppError):
    status_code = 502


class ClippingError(AppError):
    status_code = 500


class CaptionError(AppError):
    status_code = 500

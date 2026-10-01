"""Provider-agnostic interface for AI moment detection."""
from abc import ABC, abstractmethod
from typing import List, Optional

from app.models import Moment, Transcript


class MomentDetector(ABC):
    """Implement this to add a new AI provider."""

    name: str = "base"

    @abstractmethod
    def detect_moments(self, transcript: Transcript, max_moments: int = 5,
                       target_seconds: Optional[float] = None) -> List[Moment]:
        """Return the most interesting moments in the transcript.

        `target_seconds` is the clip length the user asked for; moments should naturally
        fit it without cutting sentences. None means "use the configured default range".
        """

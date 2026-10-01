"""Whole flow with a fake Gemini client and (if installed) real FFmpeg:
saved transcript JSON -> Gemini moments -> clips cut from the video."""
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from app.services import clipping
from app.services.moment_detection.gemini import GeminiMomentDetector
from app.services.transcription import load_transcript, save_transcript
from app.models import Transcript, TranscriptSegment


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")
def test_transcript_to_moments_to_clips(settings, tmp_path):
    video = settings.downloads_dir / "vidX.mp4"
    video.parent.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "60", "-c:v", "libx264",
                    "-c:a", "aac", "-shortest", str(video)], check=True)

    transcript = Transcript("en", [TranscriptSegment(i * 5.0, (i + 1) * 5.0, f"line {i}") for i in range(12)])
    tpath = save_transcript(transcript, video, settings)
    loaded = load_transcript(tpath)

    reply = json.dumps([{"title": "Opening hook", "start": 5, "end": 25, "reason": "Strong start"},
                        {"title": "The payoff", "start": 35, "end": 55, "reason": "Resolves the story"}])
    client = SimpleNamespace(models=SimpleNamespace(
        generate_content=lambda **kw: SimpleNamespace(text=reply)))
    moments = GeminiMomentDetector(settings, client=client).detect_moments(loaded, max_moments=5)
    clips = clipping.clip_moments(video, moments, settings)

    assert len(clips) == 2
    assert all(c.parent == settings.clips_dir and c.stat().st_size > 1024 for c in clips)

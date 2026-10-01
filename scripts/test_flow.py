"""Live end-to-end test of Steps 4-5 using files you already have:

    saved transcript JSON  ->  Gemini (text only)  ->  moments  ->  FFmpeg clips

Usage (from the project root, venv active):
    python -m scripts.test_flow                  # newest transcript in data/transcripts
    python -m scripts.test_flow MvWjV_up8Gs      # a specific video id
    python -m scripts.test_flow --max-moments 3

Needs GEMINI_API_KEY in .env. Sends only transcript text to Gemini.
"""
import argparse
import json
import sys
from pathlib import Path

from app.config import get_settings
from app.exceptions import AppError
from app.logging_config import setup_logging
from app.services.clipping import clip_moments
from app.services.moment_detection import get_moment_detector
from app.services.transcription import load_transcript


def _find_transcript(settings, video_id):
    if video_id:
        path = settings.transcripts_dir / f"{Path(video_id).stem}.json"
        return path if path.is_file() else None
    files = [p for p in settings.transcripts_dir.glob("*.json") if not p.name.endswith("_moments.json")]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video_id", nargs="?", help="video id (file name without extension)")
    parser.add_argument("--max-moments", type=int, default=5)
    args = parser.parse_args()

    settings = get_settings()
    settings.ensure_dirs()
    setup_logging(settings)

    transcript_path = _find_transcript(settings, args.video_id)
    if not transcript_path:
        print(f"No transcript found in {settings.transcripts_dir}. Run Steps 2-3 first.")
        return 1
    video_path = next((p for p in settings.downloads_dir.glob(f"{transcript_path.stem}.*")
                       if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}), None)
    if not video_path:
        print(f"No downloaded video named {transcript_path.stem}.* in {settings.downloads_dir}.")
        return 1

    print(f"Transcript: {transcript_path.name}\nVideo:      {video_path.name}")
    try:
        transcript = load_transcript(transcript_path)
        print(f"Asking Gemini ({settings.gemini_model}) - text only, {len(transcript.segments)} segments...")
        moments = get_moment_detector().detect_moments(transcript, max_moments=args.max_moments)

        moments_file = settings.output_dir / f"{transcript_path.stem}_moments.json"
        moments_file.write_text(json.dumps(
            [{"title": m.title, "start": m.start, "end": m.end, "reason": m.reason} for m in moments],
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n{len(moments)} moment(s) (saved to {moments_file}):")
        for m in moments:
            print(f"  {m.start:7.1f} - {m.end:7.1f}  {m.title}\n      {m.reason}")

        print("\nCutting clips with FFmpeg...")
        clips = clip_moments(video_path, moments)
    except AppError as exc:
        print(f"\nFAILED ({type(exc).__name__}): {exc.message}")
        return 2

    print(f"\nDone. {len(clips)} clip(s) in {settings.clips_dir}:")
    for c in clips:
        print(f"  {c.name}  ({c.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

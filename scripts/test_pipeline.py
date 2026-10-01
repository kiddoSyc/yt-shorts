"""Live test of the low-data pipeline with a real YouTube URL at several clip lengths.

    python -m scripts.test_pipeline "https://www.youtube.com/watch?v=VIDEO_ID"
    python -m scripts.test_pipeline URL --durations 30 40 60
    python -m scripts.test_pipeline URL --source whisper --fresh     # force audio-only + Whisper
    python -m scripts.test_pipeline URL --source captions --fresh    # captions only (no fallback)

Prints, per duration: transcript method, the timestamps Gemini returned, actual clip
durations (ffprobe), and how much data was downloaded. Needs GEMINI_API_KEY in .env.
The full video is never downloaded. Optional: `pip install psutil` adds a system-wide
network byte counter to the report (includes traffic from other programs).
"""
import argparse
import json
import sys
import time

from app.config import get_settings
from app.exceptions import AppError
from app.logging_config import setup_logging
from app.services.moment_detection import get_moment_detector
from app.services.pipeline import run_session
from app.services.session import new_session


def _mb(n):
    return "n/a" if n is None else f"{n / 1e6:.2f} MB"


def _net_bytes():
    try:
        import psutil
        c = psutil.net_io_counters()
        return c.bytes_recv
    except Exception:
        return None


def _raw_timestamps(detector):
    try:
        text = (detector.last_raw_response or "").strip().strip("`")
        text = text[4:] if text.lower().startswith("json") else text
        data = json.loads(text)
        data = data.get("moments", data) if isinstance(data, dict) else data
        return [(m.get("start"), m.get("end")) for m in data]
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url")
    parser.add_argument("--durations", type=int, nargs="+", default=[30, 40, 60])
    parser.add_argument("--source", choices=["auto", "captions", "whisper"], default=None)
    parser.add_argument("--fresh", action="store_true", help="ignore any saved transcript")
    args = parser.parse_args()

    settings = get_settings()
    settings.ensure_dirs()
    setup_logging(settings)
    if args.source:
        settings.transcript_source = args.source
    downloads_before = sorted(p.name for p in settings.downloads_dir.glob("*") if p.name != ".gitkeep")
    detector = get_moment_detector()
    report = []
    net_start = _net_bytes()

    for i, duration in enumerate(args.durations):
        print(f"\n===== session {i + 1}: clip_duration = {duration}s =====")
        net_before = _net_bytes()
        t0 = time.time()
        try:
            session = new_session(args.url, duration)
            result = run_session(session, detector=detector, use_cache=not args.fresh or i > 0, measure=True)
        except AppError as exc:
            print(f"FAILED ({type(exc).__name__}): {exc.message}")
            return 2
        net_after = _net_bytes()
        st = result.stats
        print(f"transcript method : {result.transcript_method}  ({len(result.moments)} moment(s) from Gemini)")
        print(f"gemini raw times  : {_raw_timestamps(detector)}")
        print("moments used      :")
        for m in result.moments:
            print(f"   {m.start:8.1f} -> {m.end:8.1f}  ({m.end - m.start:5.1f}s)  {m.title}")
        print("clips             :")
        for c in result.clips:
            print(f"   {c.path.name}  {c.duration}s  {_mb(c.size_bytes)}  [{c.method}]  "
                  f"input read {_mb(c.input_bytes_read)}")
        print(f"data: captions {_mb(st['caption_bytes'])} | audio {_mb(st['audio_bytes'])} | "
              f"FFmpeg input for clips {_mb(st['clip_input_bytes_read'])} | "
              f"clip files {_mb(st['clip_output_bytes'])}")
        print(f"full video would have been about {_mb(st['full_video_size_estimate'])} at "
              f"{st['source_video_height']}p  |  full video downloaded: {st['full_video_downloaded']}")
        if net_before is not None and net_after is not None:
            print(f"system network received during session: {_mb(net_after - net_before)} (all programs)")
        print(f"elapsed {time.time() - t0:.0f}s")
        report.append(result.to_dict())

    leftover = [p.name for p in settings.tmp_dir.glob("*")]
    new_downloads = sorted(p.name for p in settings.downloads_dir.glob("*") if p.name != ".gitkeep")
    print("\n===== checks =====")
    print(f"temp audio/sections left in data/tmp : {leftover or 'none'}")
    print(f"new files in data/downloads          : {sorted(set(new_downloads) - set(downloads_before)) or 'none (no full video)'}")
    if net_start is not None:
        print(f"system network received, whole run   : {_mb(_net_bytes() - net_start)} (all programs)")
    out = settings.output_dir / f"{report[0]['video_id']}_pipeline_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"report saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

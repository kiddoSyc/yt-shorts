"""End-to-end pipeline tests, offline: fake yt-dlp + fake Gemini, but REAL FFmpeg reading
from a local Range-capable HTTP server (a stand-in for YouTube's media servers)."""
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.exceptions import CaptionsUnavailableError
from app.models import Moment
from app.services import pipeline
from app.services.moment_detection.base import MomentDetector
from app.services.session import new_session
from tests import media_server

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")
VID = "dQw4w9WgXcQ"
URL = f"https://youtu.be/{VID}"


def caption_payload():
    events = [{"tStartMs": i * 3000, "dDurationMs": 3000,
               "segs": [{"utf8": f"This is caption sentence number {i} of the test video."}]}
              for i in range(80)]
    return json.dumps({"events": events}).encode()


class World:
    """What the fake YouTube knows, and what the pipeline asked it to do."""

    def __init__(self, base, captions=True, bad_media=False):
        d = media_server.media_dir()
        self.dir = d
        media = "http://127.0.0.1:1" if bad_media else base  # port 1: connection refused
        self.info = {
            "id": VID, "title": "Test video", "duration": media_server.MEDIA_SECONDS, "language": "en",
            "requested_formats": [
                {"url": f"{media}/video_only.mp4", "vcodec": "avc1.4d401e", "acodec": "none", "height": 240,
                 "filesize": os.path.getsize(f"{d}/video_only.mp4"),
                 "http_headers": {"User-Agent": "UA-test", "Accept-Encoding": "gzip, deflate"}},
                {"url": f"{media}/audio_only.m4a", "vcodec": "none", "acodec": "mp4a.40.2",
                 "filesize": os.path.getsize(f"{d}/audio_only.m4a"),
                 "http_headers": {"User-Agent": "UA-test", "Accept-Encoding": "gzip, deflate"}},
            ],
        }
        if captions:
            self.info["subtitles"] = {"en": [{"ext": "json3", "url": "https://captions.test/en.json3"}]}
        self.caption_fetches = 0
        self.full_video_downloads = 0
        self.audio_downloads = 0
        self.section_requests = []

    def factory(self, opts):
        return FakeYDL(opts, self)


class FakeYDL:
    def __init__(self, opts, world):
        self.opts, self.world = opts, world

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def close(self):
        pass

    def extract_info(self, url, download=False):
        if download:
            if "download_ranges" in self.opts:  # yt-dlp section fallback
                (start, end), = self.opts["download_ranges"]
                self.world.section_requests.append((start, end))
                out = Path(self.opts["outtmpl"].replace("%(ext)s", "mp4"))
                out.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(start), "-i",
                                f"{self.world.dir}/video_only.mp4", "-t", str(end - start),
                                "-c:v", "libx264", "-preset", "ultrafast", str(out)], check=True)
            else:
                self.world.full_video_downloads += 1
        return self.world.info

    def process_ie_result(self, info, download=True):
        if "wa[" in self.opts.get("format", ""):  # audio-only download
            self.world.audio_downloads += 1
            out_dir = Path(self.opts["outtmpl"]).parent
            shutil.copy(f"{self.world.dir}/audio_only.m4a", out_dir / f"{VID}.m4a")
        else:
            self.world.full_video_downloads += 1

    def urlopen(self, url):
        self.world.caption_fetches += 1
        return SimpleNamespace(read=caption_payload, close=lambda: None)


class FakeDetector(MomentDetector):
    """Stands in for Gemini: returns moments scaled to the requested length."""

    def __init__(self):
        self.targets = []
        self.prompt_hints = []

    def detect_moments(self, transcript, max_moments=5, target_seconds=None, prompt_hint=None):
        self.targets.append(target_seconds)
        self.prompt_hints.append(prompt_hint)
        t = target_seconds
        return [Moment(start=21.0, end=21.0 + t, title=f"Best bit {t}", reason="r"),
                Moment(start=120.0, end=120.0 + t * 0.9, title=f"Second bit {t}", reason="r")]


class FakeWhisper:
    def transcribe(self, path, **kwargs):
        assert Path(path).exists()
        segs = [SimpleNamespace(start=i * 4.0, end=i * 4.0 + 4.0, text=f"spoken line {i} with words")
                for i in range(30)]
        return iter(segs), SimpleNamespace(language="en")


@pytest.fixture
def server():
    srv, base = media_server.start_server(media_server.media_dir())
    yield base
    srv.shutdown()


@pytest.mark.parametrize("duration", [30, 40, 60])
def test_captions_pipeline_range_download(settings, server, duration):
    world = World(server)
    detector = FakeDetector()
    result = pipeline.run_session(new_session(URL, duration, settings), settings,
                                  ydl_factory=world.factory, detector=detector, measure=True)

    assert detector.targets == [duration]                       # session length reached Gemini
    assert result.transcript_method == "youtube_captions_manual"
    assert world.audio_downloads == 0 and world.full_video_downloads == 0
    assert list(settings.downloads_dir.glob("*")) == []          # no full video saved
    assert result.stats["full_video_downloaded"] is False
    assert json.loads(result.transcript_path.read_text())["method"] == "youtube_captions_manual"

    assert len(result.clips) == 2
    for clip, moment in zip(result.clips, result.moments):
        assert clip.method == "ffmpeg-range" and clip.path.exists()
        assert clip.path.parent == settings.clips_dir
        assert abs(clip.duration - (moment.end - moment.start)) < 0.4   # exact cut, real ffprobe

    total = sum(os.path.getsize(f"{media_server.media_dir()}/{f}") for f in ("video_only.mp4", "audio_only.m4a"))
    read = result.stats["clip_input_bytes_read"]
    assert read is not None and read < 0.6 * total   # far less than the whole file (2 clips, <=60s each of 240s)


def test_whisper_fallback_deletes_temp_audio(settings, server):
    world = World(server, captions=False)
    result = pipeline.run_session(new_session(URL, 30, settings), settings, ydl_factory=world.factory,
                                  detector=FakeDetector(), model_factory=lambda s: FakeWhisper())
    assert result.transcript_method == "whisper_audio"
    assert world.audio_downloads == 1 and world.full_video_downloads == 0
    assert result.stats["audio_bytes"] > 0
    assert list(settings.tmp_dir.iterdir()) == []                # temp audio removed
    assert len(result.clips) == 2


def test_whisper_source_forced_and_captions_source_strict(settings, server):
    settings.transcript_source = "whisper"
    world = World(server)  # has captions, but they must not be used
    r = pipeline.run_session(new_session(URL, 30, settings), settings, ydl_factory=world.factory,
                             detector=FakeDetector(), model_factory=lambda s: FakeWhisper(), use_cache=False)
    assert r.transcript_method == "whisper_audio" and world.caption_fetches == 0

    settings.transcript_source = "captions"
    with pytest.raises(CaptionsUnavailableError):
        pipeline.run_session(new_session(URL, 30, settings), settings,
                             ydl_factory=World(server, captions=False).factory,
                             detector=FakeDetector(), use_cache=False)


def test_transcript_is_cached_between_sessions(settings, server):
    world = World(server)
    for duration in (30, 40):
        pipeline.run_session(new_session(URL, duration, settings), settings,
                             ydl_factory=world.factory, detector=FakeDetector())
    assert world.caption_fetches == 1   # second session reused the saved transcript


def test_section_fallback_when_range_read_fails(settings, server):
    world = World(server, bad_media=True)
    result = pipeline.run_session(new_session(URL, 30, settings), settings,
                                  ydl_factory=world.factory, detector=FakeDetector())
    assert [c.method for c in result.clips] == ["yt-dlp-section", "yt-dlp-section"]
    assert world.section_requests == [(21.0, 51.0), (120.0, 147.0)]
    assert world.full_video_downloads == 0
    assert list(settings.tmp_dir.iterdir()) == []


def test_missing_ffmpeg_fails_before_any_network(settings, monkeypatch):
    from app.exceptions import DependencyMissingError
    from app.services import downloader
    monkeypatch.setattr(downloader.shutil, "which", lambda _: None)

    def boom(opts):
        raise AssertionError("must not touch YouTube")

    with pytest.raises(DependencyMissingError):
        pipeline.run_session(new_session(URL, 30, settings), settings, ydl_factory=boom,
                             detector=FakeDetector())

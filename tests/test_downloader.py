"""Downloader tests: no network, no yt-dlp, no real FFmpeg needed."""
import pytest

from app.exceptions import DependencyMissingError, DownloadError, InvalidURLError
from app.services import downloader

VID = "dQw4w9WgXcQ"


@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={VID}",
    f"https://youtube.com/watch?v={VID}&list=PL123&t=30s",
    f"http://m.youtube.com/watch?v={VID}",
    f"https://youtu.be/{VID}?si=abc",
    f"https://www.youtube.com/shorts/{VID}",
    f"https://www.youtube.com/embed/{VID}",
    f"www.youtube.com/watch?v={VID}",
    f"  https://youtu.be/{VID}  ",
])
def test_valid_urls(url):
    assert downloader.extract_video_id(url) == VID


@pytest.mark.parametrize("url", [
    "", "   ", "not a url", "https://example.com/watch?v=" + VID,
    f"https://youtube.com.evil.com/watch?v={VID}",
    f"https://evil.com/?u=youtube.com/watch?v={VID}",
    "https://www.youtube.com/playlist?list=PL123",
    "https://www.youtube.com/watch?v=short",
    "https://www.youtube.com/",
    f"ftp://youtu.be/{VID}",
    f"javascript:alert('{VID}')",
    None, 123,
])
def test_invalid_urls(url):
    with pytest.raises(InvalidURLError):
        downloader.extract_video_id(url)


def test_check_ffmpeg_missing(settings, monkeypatch):
    monkeypatch.setattr(downloader.shutil, "which", lambda _: None)
    with pytest.raises(DependencyMissingError):
        downloader.check_ffmpeg(settings)


def test_check_ffmpeg_found(settings, monkeypatch):
    monkeypatch.setattr(downloader.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    assert downloader.check_ffmpeg(settings) == "/usr/bin/ffmpeg"


def test_ydl_options(settings):
    opts = downloader.build_ydl_options(settings, "/usr/bin/ffmpeg")
    assert "height<=480" in opts["format"]
    assert opts["format"].startswith("bv*[height<=480][vcodec^=avc1]")  # H.264 preferred over AV1
    assert opts["noplaylist"] is True
    assert opts["merge_output_format"] == "mp4"
    assert opts["ffmpeg_location"] == "/usr/bin/ffmpeg"
    assert opts["outtmpl"].startswith(str(settings.downloads_dir))
    assert "%(id)s" in opts["outtmpl"]  # safe name: never the video title


class FakeYDL:
    """Stands in for yt_dlp.YoutubeDL."""
    last = None

    def __init__(self, opts, info=None, fail=None):
        self.opts, self.info, self.fail = opts, info or {"id": VID}, fail
        FakeYDL.last = self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=True):
        if self.fail:
            raise self.fail
        self.url = url
        return self.info

    def process_ie_result(self, info, download=True):
        (self.opts_dir() / f"{VID}.mp4").write_bytes(b"fake-video")

    def opts_dir(self):
        from pathlib import Path
        return Path(self.opts["outtmpl"]).parent


@pytest.fixture(autouse=True)
def fake_ffmpeg(monkeypatch):
    monkeypatch.setattr(downloader.shutil, "which", lambda _: "/usr/bin/ffmpeg")


def test_download_success(settings):
    path = downloader.download_video(f"https://youtu.be/{VID}?si=x", settings, ydl_factory=FakeYDL)
    assert path == settings.downloads_dir / f"{VID}.mp4"
    assert path.read_bytes() == b"fake-video"
    assert FakeYDL.last.url == f"https://www.youtube.com/watch?v={VID}"


def test_download_reuses_existing_file(settings):
    settings.downloads_dir.mkdir(parents=True)
    existing = settings.downloads_dir / f"{VID}.mp4"
    existing.write_bytes(b"already here")

    def boom(opts):
        raise AssertionError("must not download again")

    assert downloader.download_video(f"https://youtu.be/{VID}", settings, ydl_factory=boom) == existing


def test_download_rejects_bad_url_before_any_work(settings):
    def boom(opts):
        raise AssertionError("must not be called")

    with pytest.raises(InvalidURLError):
        downloader.download_video("https://example.com/x", settings, ydl_factory=boom)


def test_download_error_is_wrapped(settings):
    factory = lambda opts: FakeYDL(opts, fail=RuntimeError("ERROR: Private video. Sign in"))
    with pytest.raises(DownloadError) as exc:
        downloader.download_video(f"https://youtu.be/{VID}", settings, ydl_factory=factory)
    assert "private" in exc.value.message.lower()


def test_live_stream_rejected(settings):
    factory = lambda opts: FakeYDL(opts, info={"id": VID, "is_live": True})
    with pytest.raises(DownloadError):
        downloader.download_video(f"https://youtu.be/{VID}", settings, ydl_factory=factory)


def test_missing_ffmpeg_stops_download(settings, monkeypatch):
    monkeypatch.setattr(downloader.shutil, "which", lambda _: None)
    with pytest.raises(DependencyMissingError):
        downloader.download_video(f"https://youtu.be/{VID}", settings, ydl_factory=FakeYDL)


def test_no_download_on_import():
    # Importing the module must not import yt-dlp (lazy import) or touch the network.
    assert not hasattr(downloader, "yt_dlp")

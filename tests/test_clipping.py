"""Clipping tests: command/filename logic with a fake runner, plus a real-FFmpeg test if available."""
import shutil
import subprocess

import pytest

from app.exceptions import ClippingError, DependencyMissingError
from app.models import Moment
from app.services import clipping, downloader

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def test_safe_slug():
    assert clipping.safe_slug("Wow!! ../../etc/passwd  é") == "wow-etc-passwd"
    assert clipping.safe_slug("???") == "clip"
    assert len(clipping.safe_slug("a" * 100)) <= 40


def test_filenames_safe_and_unique(tmp_path):
    v = tmp_path / "abc123.mp4"
    m1 = Moment(start=10, end=40, title="Same title", reason="r")
    m2 = Moment(start=50, end=80, title="Same title", reason="r")
    n1, n2 = clipping.clip_filename(v, 1, m1), clipping.clip_filename(v, 2, m2)
    assert n1 != n2
    assert n1 == "abc123_01_same-title_10s-40s.mp4"
    assert "/" not in n1 and "\\" not in n1 and ".." not in n1


def test_command_shape(tmp_path, settings):
    cmd = clipping.build_ffmpeg_command("ffmpeg", tmp_path / "v.mp4",
                                        Moment(start=10, end=40.5, title="t", reason="r"),
                                        tmp_path / "o.mp4", settings)
    assert cmd[cmd.index("-ss") + 1] == "10.000"
    assert cmd[cmd.index("-t") + 1] == "30.500"
    assert "libx264" in cmd and "aac" in cmd
    assert cmd[cmd.index("-crf") + 1] == str(settings.video_crf)
    assert cmd[cmd.index("-preset") + 1] == settings.video_preset
    assert not any("caption" in c or "crop" in c or "scale" in c for c in cmd)  # no vertical/captions yet


@pytest.fixture
def video(tmp_path):
    f = tmp_path / "vid1.mp4"
    f.write_bytes(b"x")
    return f


def fake_ffmpeg_ok(monkeypatch):
    monkeypatch.setattr(downloader.shutil, "which", lambda _: "/usr/bin/ffmpeg")


def test_missing_video(settings, tmp_path):
    with pytest.raises(ClippingError):
        clipping.clip_moments(tmp_path / "no.mp4", [Moment(0, 10, "t", "r")], settings)


def test_no_moments_returns_empty(settings, video):
    assert clipping.clip_moments(video, [], settings) == []


def test_missing_ffmpeg(settings, video, monkeypatch):
    monkeypatch.setattr(downloader.shutil, "which", lambda _: None)
    with pytest.raises(DependencyMissingError):
        clipping.clip_moments(video, [Moment(0, 10, "t", "r")], settings)


def test_partial_failure_keeps_good_clips(settings, video, monkeypatch):
    fake_ffmpeg_ok(monkeypatch)
    calls = []

    def runner(cmd, **kw):
        calls.append(cmd)
        out = cmd[-1]
        if len(calls) == 1:
            return subprocess.CompletedProcess(cmd, 1, "", "boom")
        open(out, "wb").write(b"0" * 2048)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    moments = [Moment(0, 10, "first", "r"), Moment(20, 30, "second", "r")]
    clips = clipping.clip_moments(video, moments, settings, runner=runner)
    assert [c.name for c in clips] == ["vid1_02_second_20s-30s.mp4"]
    assert not list(settings.clips_dir.glob("*.tmp.mp4"))  # no leftovers


def test_all_fail_raises(settings, video, monkeypatch):
    fake_ffmpeg_ok(monkeypatch)
    runner = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "boom")
    with pytest.raises(ClippingError):
        clipping.clip_moments(video, [Moment(0, 10, "t", "r")], settings, runner=runner)


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg not installed")
def test_real_ffmpeg_clip_duration(settings, tmp_path):
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "12", "-c:v", "libx264",
                    "-c:a", "aac", "-shortest", str(src)], check=True)
    clips = clipping.clip_moments(src, [Moment(2, 7, "Real test", "r")], settings)
    assert len(clips) == 1 and clips[0].exists()
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(clips[0])], capture_output=True, text=True)
    assert abs(float(out.stdout) - 5.0) < 0.3

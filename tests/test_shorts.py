"""Tests for vertical (9:16) formatting + caption burn-in, using a fake runner (no real FFmpeg)."""
import subprocess

import pytest

from app.exceptions import ClippingError
from app.models import ClipInfo, Transcript, TranscriptSegment
from app.services import shorts


def test_short_filename_is_derived_from_clip_stem():
    from pathlib import Path
    assert shorts.short_filename(Path("abc_01_title_10s-40s.mp4")) == "abc_01_title_10s-40s_short.mp4"


def test_vertical_filter_scales_and_crops_to_configured_size(settings):
    settings.shorts_width, settings.shorts_height = 1080, 1920
    f = shorts.build_vertical_filter(settings, caption_file=None)
    assert "scale=1080:1920" in f
    assert "crop=1080:1920" in f
    assert "subtitles" not in f


def test_vertical_filter_appends_subtitles_when_a_caption_file_is_given(settings):
    f = shorts.build_vertical_filter(settings, caption_file="captions.ass")
    assert f.endswith("subtitles=captions.ass")


def test_ffmpeg_command_copies_audio_and_keeps_quality_settings(settings, tmp_path):
    cmd = shorts.build_ffmpeg_command("ffmpeg", tmp_path / "clip.mp4", tmp_path / "out.mp4",
                                      settings, caption_file=None)
    assert "-c:a" in cmd and cmd[cmd.index("-c:a") + 1] == "copy"
    assert "libx264" in cmd
    assert "-vf" in cmd


@pytest.fixture
def clip(tmp_path):
    p = tmp_path / "src.mp4"
    p.write_bytes(b"x" * 2000)
    return ClipInfo(path=p, start=10.0, end=15.0, title="t", reason="r", method="ffmpeg-range",
                    size_bytes=p.stat().st_size)


def fake_ok_runner(output_path):
    def runner(cmd, **kwargs):
        out = cmd[-1]
        with open(out, "wb") as fh:
            fh.write(b"y" * 2000)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
    return runner


def test_format_short_missing_clip_raises(settings, tmp_path):
    missing = ClipInfo(path=tmp_path / "nope.mp4", start=0, end=5, title="t", reason="r")
    with pytest.raises(ClippingError):
        shorts.format_short(missing, None, settings)


def test_format_short_missing_ffmpeg_raises(settings, clip, monkeypatch):
    monkeypatch.setattr(shorts.shutil, "which", lambda _: None)
    from app.exceptions import DependencyMissingError
    with pytest.raises(DependencyMissingError):
        shorts.format_short(clip, None, settings)


def test_format_short_succeeds_with_fake_runner_and_no_transcript(settings, clip, monkeypatch):
    monkeypatch.setattr(shorts.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    out = shorts.format_short(clip, None, settings, runner=lambda cmd, **kw: (
        open(cmd[-1], "wb").write(b"y" * 2000),
        subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr=""))[1])
    assert out.exists()
    assert out.parent == settings.shorts_dir
    assert out.name.endswith("_short.mp4")


def test_format_short_uses_captions_when_transcript_has_speech_in_range(settings, clip, monkeypatch):
    monkeypatch.setattr(shorts.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    transcript = Transcript(language="en", segments=[TranscriptSegment(11, 13, "hello there")])
    seen_cmds = []

    def runner(cmd, **kw):
        seen_cmds.append(cmd)
        open(cmd[-1], "wb").write(b"y" * 2000)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    out = shorts.format_short(clip, transcript, settings, runner=runner)
    assert out.exists()
    vf = seen_cmds[0][seen_cmds[0].index("-vf") + 1]
    assert "subtitles=" in vf


def test_format_short_skips_captions_when_no_speech_in_range(settings, clip, monkeypatch):
    monkeypatch.setattr(shorts.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    transcript = Transcript(language="en", segments=[TranscriptSegment(500, 505, "far away")])
    seen_cmds = []

    def runner(cmd, **kw):
        seen_cmds.append(cmd)
        open(cmd[-1], "wb").write(b"y" * 2000)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    shorts.format_short(clip, transcript, settings, runner=runner)
    vf = seen_cmds[0][seen_cmds[0].index("-vf") + 1]
    assert "subtitles" not in vf


def test_format_short_raises_on_ffmpeg_failure(settings, clip, monkeypatch):
    monkeypatch.setattr(shorts.shutil, "which", lambda _: "/usr/bin/ffmpeg")

    def failing_runner(cmd, **kw):
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="boom")

    with pytest.raises(ClippingError):
        shorts.format_short(clip, None, settings, runner=failing_runner)


def test_format_shorts_skips_failing_clips_but_keeps_the_rest(settings, tmp_path, monkeypatch):
    monkeypatch.setattr(shorts.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    good = tmp_path / "good.mp4"
    good.write_bytes(b"x" * 2000)
    bad = tmp_path / "bad.mp4"  # never created on disk -> missing-file error inside format_short
    clips = [
        ClipInfo(path=good, start=0, end=5, title="g", reason="r"),
        ClipInfo(path=bad, start=0, end=5, title="b", reason="r"),
    ]

    def runner(cmd, **kw):
        open(cmd[-1], "wb").write(b"y" * 2000)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    outputs = shorts.format_shorts(clips, None, settings, runner=runner)
    assert len(outputs) == 1
    assert outputs[0].name.startswith("good")

"""Transcription tests: use a fake model, so no download and no faster-whisper needed."""
import json
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.exceptions import TranscriptionError
from app.models import Transcript, TranscriptSegment
from app.services import transcription


class FakeModel:
    def __init__(self, segments, language="en"):
        self._segments, self._language = segments, language
        self.calls = []

    def transcribe(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return iter(self._segments), SimpleNamespace(language=self._language)


def seg(start, end, text):
    return SimpleNamespace(start=start, end=end, text=text)


@pytest.fixture
def media(tmp_path):
    f = tmp_path / "abc123.mp4"
    f.write_bytes(b"x")
    return f


def test_segments_have_start_end_text(settings, media):
    model = FakeModel([seg(0.0, 2.345, " Hello world "), seg(2.5, 4.0, "   "), seg(4.0, 6.126, "Bye")])
    t = transcription.transcribe(media, settings, model_factory=lambda s: model)
    assert t.language == "en"
    assert [(s.start, s.end, s.text) for s in t.segments] == [(0.0, 2.35, "Hello world"), (4.0, 6.13, "Bye")]
    assert model.calls[0][0] == str(media)


def test_model_loaded_lazily_and_uses_env_model_name(settings, media, monkeypatch):
    loaded = []

    def factory(s):
        loaded.append(s.whisper_model_size)
        return FakeModel([seg(0, 1, "hi")])

    assert loaded == []  # nothing loaded before transcription is requested
    transcription.transcribe(media, settings, model_factory=factory)
    assert loaded == ["tiny"]


def test_model_name_comes_from_env(monkeypatch):
    monkeypatch.setenv("WHISPER_MODEL_SIZE", "tiny.en")
    assert Settings(_env_file=None).whisper_model_size == "tiny.en"


def test_missing_file(settings, tmp_path):
    with pytest.raises(TranscriptionError):
        transcription.transcribe(tmp_path / "nope.mp4", settings, model_factory=lambda s: FakeModel([]))


def test_model_failure_is_wrapped(settings, media):
    class Broken:
        def transcribe(self, *a, **k):
            raise RuntimeError("decode error")

    with pytest.raises(TranscriptionError):
        transcription.transcribe(media, settings, model_factory=lambda s: Broken())


def test_save_and_load_json(settings, media):
    t = Transcript(language="en", segments=[TranscriptSegment(1.0, 2.5, "héllo — wörld")])
    path = transcription.save_transcript(t, media, settings)
    assert path == settings.transcripts_dir / "abc123.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["segments"] == [{"start": 1.0, "end": 2.5, "text": "héllo — wörld"}]
    assert data["language"] == "en" and data["source"] == "abc123.mp4"
    assert transcription.load_transcript(path) == t


def test_transcribe_and_save(settings, media):
    model = FakeModel([seg(0, 1, "one")])
    t, path = transcription.transcribe_and_save(media, settings, model_factory=lambda s: model)
    assert path.exists() and len(t.segments) == 1


def test_load_transcript_bad_file(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(TranscriptionError):
        transcription.load_transcript(bad)


def test_no_faster_whisper_import_at_module_level():
    assert not hasattr(transcription, "WhisperModel")


class VadPickyModel(FakeModel):
    """Finds speech only when the VAD filter is off."""

    def transcribe(self, path, **kwargs):
        self.calls.append((path, kwargs))
        segs = [] if kwargs.get("vad_filter") else self._segments
        return iter(segs), SimpleNamespace(language=self._language)


def test_retries_without_vad_when_nothing_found(settings, media):
    model = VadPickyModel([seg(0, 2, "quiet speech")])
    t = transcription.transcribe(media, settings, model_factory=lambda s: model)
    assert [s.text for s in t.segments] == ["quiet speech"]
    assert [c[1]["vad_filter"] for c in model.calls] == [True, False]


def test_no_speech_raises_clear_error(settings, media):
    model = FakeModel([])
    with pytest.raises(TranscriptionError) as exc:
        transcription.transcribe(media, settings, model_factory=lambda s: model)
    assert "no speech" in exc.value.message.lower()
    assert len(model.calls) == 2  # VAD on, then off


def test_vad_can_be_disabled_from_env(settings, media):
    settings.whisper_vad_filter = False
    model = FakeModel([seg(0, 1, "hi")])
    transcription.transcribe(media, settings, model_factory=lambda s: model)
    assert [c[1]["vad_filter"] for c in model.calls] == [False]

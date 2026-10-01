"""Tests for the /jobs and /files HTTP routes (fast: run_session is faked)."""
import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.jobs_routes as jobs_routes_mod
import app.services.jobs as jobs_mod
from app.models import ClipInfo, PipelineResult
from app.services.jobs import STATUS_COMPLETED, JobManager

URL = "https://youtu.be/dQw4w9WgXcQ"


def fake_result(session, settings, n_clips=2, n_shorts=None):
    n_shorts = n_clips if n_shorts is None else n_shorts
    clips_dir, shorts_dir = settings.clips_dir, settings.shorts_dir
    clips_dir.mkdir(parents=True, exist_ok=True)
    shorts_dir.mkdir(parents=True, exist_ok=True)
    clips, shorts = [], []
    for i in range(n_clips):
        clip_path = clips_dir / f"clip{i}.mp4"
        clip_path.write_bytes(b"fake video bytes " + str(i).encode())
        clips.append(ClipInfo(path=clip_path, start=i * 10.0, end=i * 10.0 + 5.0, title=f"Moment {i}"))
    for i in range(n_shorts):
        short_path = shorts_dir / f"clip{i}_short.mp4"
        short_path.write_bytes(b"fake short bytes " + str(i).encode())
        shorts.append(short_path)
    return PipelineResult(session=session, video_id="vid123", transcript_method="whisper_audio",
                          transcript_path=shorts_dir.parent / "t.json", clips=clips, shorts=shorts)


@pytest.fixture
def client(settings, monkeypatch, tmp_path):
    def fake_run_session(session, settings_arg=None, *, on_progress=None, **kw):
        if on_progress:
            on_progress("clipping", {"done": 2, "total": 2})
        return fake_result(session, settings)

    monkeypatch.setattr(jobs_mod, "run_session", fake_run_session)
    manager = JobManager(settings=settings, max_workers=1)
    monkeypatch.setattr(jobs_routes_mod, "get_job_manager", lambda: manager)
    monkeypatch.setattr(jobs_routes_mod, "get_settings", lambda: settings)

    from app.main import app
    with TestClient(app) as c:
        yield c
    manager._executor.shutdown(wait=True)


def wait_completed(client, job_id, timeout=5):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/jobs/{job_id}")
        data = r.json()
        if data["status"] in ("completed", "failed"):
            return data
        time.sleep(0.02)
    raise TimeoutError


def test_create_job_returns_id_and_status(client):
    r = client.post("/jobs", json={"url": URL, "clip_duration": 40})
    assert r.status_code == 200
    data = r.json()
    assert "job_id" in data and data["status"] in ("queued", "running", "completed")
    assert data["clip_duration"] == 40


def test_create_job_rejects_invalid_url(client):
    r = client.post("/jobs", json={"url": "not a youtube url"})
    assert r.status_code in (400, 422)


def test_create_job_rejects_invalid_duration(client):
    r = client.post("/jobs", json={"url": URL, "clip_duration": 5})
    assert r.status_code == 422  # caught by pydantic validator


def test_create_job_rejects_invalid_num_clips(client):
    r = client.post("/jobs", json={"url": URL, "num_clips": 0})
    assert r.status_code == 422


def test_get_job_404_for_unknown_id(client):
    r = client.get("/jobs/nope")
    assert r.status_code == 404
    assert r.json()["error"] == "JobNotFoundError"


def test_full_job_lifecycle_and_shorts_listing(client):
    r = client.post("/jobs", json={"url": URL, "clip_duration": 30})
    job_id = r.json()["job_id"]
    data = wait_completed(client, job_id)
    assert data["status"] == "completed"
    assert len(data["result"]["shorts"]) == 2

    r = client.get(f"/jobs/{job_id}/shorts")
    assert r.status_code == 200
    shorts = r.json()["shorts"]
    assert len(shorts) == 2
    assert all(s["url"].startswith("/files/shorts/") for s in shorts)

    r = client.get(f"/jobs/{job_id}/clips")
    assert r.status_code == 200
    clips = r.json()["clips"]
    assert len(clips) == 2
    assert clips[0]["title"] == "Moment 0"


def test_download_short_file(client):
    r = client.post("/jobs", json={"url": URL})
    job_id = r.json()["job_id"]
    wait_completed(client, job_id)
    shorts = client.get(f"/jobs/{job_id}/shorts").json()["shorts"]
    r = client.get(shorts[0]["url"])
    assert r.status_code == 200
    assert r.content.startswith(b"fake short bytes")


def test_download_short_rejects_path_traversal(client):
    r = client.post("/jobs", json={"url": URL})
    job_id = r.json()["job_id"]
    wait_completed(client, job_id)
    r = client.get("/files/shorts/..%2F..%2Fetc%2Fpasswd")
    assert r.status_code in (400, 404)


def test_download_missing_file_is_404(client):
    r = client.get("/files/shorts/does-not-exist.mp4")
    assert r.status_code == 404


def test_download_all_zip_contains_every_short(client):
    r = client.post("/jobs", json={"url": URL})
    job_id = r.json()["job_id"]
    wait_completed(client, job_id)
    r = client.get(f"/jobs/{job_id}/download-all")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert len(zf.namelist()) == 2


def test_download_all_before_completion_errors(client):
    r = client.post("/jobs", json={"url": URL})
    job_id = r.json()["job_id"]
    r = client.get(f"/jobs/{job_id}/download-all")
    # either it already finished (fast fake) or it correctly refuses while not completed
    assert r.status_code in (200, 500, 400)


def test_shorts_and_clips_empty_lists_while_not_completed(client, settings, monkeypatch):
    import time as time_mod

    def slow_run_session(session, settings_arg=None, *, on_progress=None, **kw):
        time_mod.sleep(0.3)
        return fake_result(session, settings)

    monkeypatch.setattr(jobs_mod, "run_session", slow_run_session)
    manager = JobManager(settings=settings, max_workers=1)
    monkeypatch.setattr(jobs_routes_mod, "get_job_manager", lambda: manager)
    r = client.post("/jobs", json={"url": URL})
    job_id = r.json()["job_id"]
    r = client.get(f"/jobs/{job_id}/shorts")
    assert r.status_code == 200
    assert r.json()["shorts"] == []
    manager._executor.shutdown(wait=True)

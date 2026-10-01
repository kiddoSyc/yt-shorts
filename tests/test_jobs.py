"""Tests for the in-memory job manager (fast: run_session is faked, no real FFmpeg/network)."""
import threading
import time
from pathlib import Path

import pytest

from app.exceptions import AppError, JobNotFoundError
from app.models import ClipInfo, PipelineResult
from app.services import jobs as jobs_mod
from app.services.jobs import STATUS_COMPLETED, STATUS_FAILED, JobManager
from app.services.session import new_session

URL = "https://youtu.be/dQw4w9WgXcQ"


def fake_result(session, n_clips=2):
    clips = [ClipInfo(path=Path(f"/tmp/clip{i}.mp4"), start=i * 10.0, end=i * 10.0 + 5.0, title=f"t{i}")
             for i in range(n_clips)]
    return PipelineResult(session=session, video_id="vid123", transcript_method="whisper_audio",
                          transcript_path=Path("/tmp/t.json"), clips=clips,
                          shorts=[Path(f"/tmp/clip{i}_short.mp4") for i in range(n_clips)])


@pytest.fixture
def manager(settings, monkeypatch):
    def fake_run_session(session, settings_arg=None, *, on_progress=None, **kw):
        if on_progress:
            on_progress("starting", {})
            on_progress("transcript", {"method": "whisper_audio"})
            on_progress("moments", {"count": 2})
            on_progress("clipping", {"done": 1, "total": 2})
            on_progress("clipping", {"done": 2, "total": 2})
            on_progress("formatting", {"done": 1, "total": 2})
            on_progress("formatting", {"done": 2, "total": 2})
            on_progress("done", {"clips": 2, "shorts": 2})
        return fake_result(session)

    monkeypatch.setattr(jobs_mod, "run_session", fake_run_session)
    m = JobManager(settings=settings, max_workers=1)
    yield m
    m._executor.shutdown(wait=True)


def wait_until_done(manager, job_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = manager.get(job_id)
        if job.status in (STATUS_COMPLETED, STATUS_FAILED):
            return job
        time.sleep(0.02)
    raise TimeoutError(f"job {job_id} did not finish in time")


def test_create_runs_in_background_and_completes(manager, settings):
    session = new_session(URL, 30, settings)
    job = manager.create(session)
    assert job.status in ("queued", "running", STATUS_COMPLETED)  # background execution has started
    finished = wait_until_done(manager, job.job_id)
    assert finished.status == STATUS_COMPLETED
    assert finished.stage == "done"
    assert len(finished.result.clips) == 2
    assert len(finished.result.shorts) == 2


def test_snapshot_includes_result_only_when_completed(manager, settings):
    session = new_session(URL, 30, settings)
    job = manager.create(session)
    wait_until_done(manager, job.job_id)
    snap = job.snapshot()
    assert snap["status"] == "completed"
    assert "result" in snap and len(snap["result"]["shorts"]) == 2
    assert "error" not in snap


def test_snapshot_progress_updates_are_visible_while_running(manager, settings, monkeypatch):
    # Slow the fake run down so we can observe an intermediate progress state.
    seen_stages = []

    def slow_run_session(session, settings_arg=None, *, on_progress=None, **kw):
        for stage, data in [("starting", {}), ("clipping", {"done": 1, "total": 2}),
                            ("clipping", {"done": 2, "total": 2})]:
            if on_progress:
                on_progress(stage, data)
            time.sleep(0.05)
        return fake_result(session)

    monkeypatch.setattr(jobs_mod, "run_session", slow_run_session)
    job = manager.create(session=new_session(URL, 30, settings))
    time.sleep(0.02)
    snap = job.snapshot()
    seen_stages.append(snap["stage"])
    wait_until_done(manager, job.job_id)
    assert "clipping" in seen_stages or job.snapshot()["stage"] == "done"


def test_get_missing_job_raises(manager):
    with pytest.raises(JobNotFoundError):
        manager.get("does-not-exist")


def test_list_returns_newest_first(manager, settings):
    j1 = manager.create(new_session(URL, 30, settings))
    time.sleep(0.01)
    j2 = manager.create(new_session(URL, 40, settings))
    wait_until_done(manager, j1.job_id)
    wait_until_done(manager, j2.job_id)
    ids = [j.job_id for j in manager.list()]
    assert ids[0] == j2.job_id and j1.job_id in ids


def test_failed_job_records_error_message_and_no_result(manager, settings, monkeypatch):
    def failing_run_session(session, settings_arg=None, *, on_progress=None, **kw):
        raise AppError("synthetic failure for testing")

    monkeypatch.setattr(jobs_mod, "run_session", failing_run_session)
    job = manager.create(new_session(URL, 30, settings))
    finished = wait_until_done(manager, job.job_id)
    assert finished.status == STATUS_FAILED
    assert finished.result is None
    snap = finished.snapshot()
    assert snap["error"] == "synthetic failure for testing"
    assert "result" not in snap


def test_unexpected_exception_still_marks_job_failed_not_stuck(manager, settings, monkeypatch):
    def crashing_run_session(session, settings_arg=None, *, on_progress=None, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(jobs_mod, "run_session", crashing_run_session)
    job = manager.create(new_session(URL, 30, settings))
    finished = wait_until_done(manager, job.job_id)
    assert finished.status == STATUS_FAILED
    assert "boom" in finished.error


def test_jobs_run_one_at_a_time_with_single_worker(manager, settings, monkeypatch):
    order = []
    started = threading.Event()

    def blocking_run_session(session, settings_arg=None, *, on_progress=None, **kw):
        order.append(("start", session.session_id))
        started.set()
        time.sleep(0.05)
        order.append(("end", session.session_id))
        return fake_result(session)

    monkeypatch.setattr(jobs_mod, "run_session", blocking_run_session)
    j1 = manager.create(new_session(URL, 30, settings))
    j2 = manager.create(new_session(URL, 40, settings))
    wait_until_done(manager, j1.job_id)
    wait_until_done(manager, j2.job_id)
    # first job's end must come before the second job's start (single worker, serialized)
    end_index = order.index(("end", j1.session.session_id))
    start2_index = order.index(("start", j2.session.session_id))
    assert end_index < start2_index

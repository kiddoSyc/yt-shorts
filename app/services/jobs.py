"""In-memory background job runner for the pipeline.

This is a single-process, single-machine job store: it's the right amount of
infrastructure for "runs locally, one user at a time" (per the project's current
scope). Jobs live only as long as the server process; restarting the server clears
them (the underlying files in data/ are unaffected and are picked up again via the
transcript/clip caches on the next request). A small ThreadPoolExecutor is used
because the pipeline is CPU/subprocess-bound (FFmpeg, Whisper), not async I/O.
"""
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.config import Settings, get_settings
from app.exceptions import AppError, JobNotFoundError
from app.models import PipelineResult, ProcessingSession
from app.services.pipeline import run_session

logger = logging.getLogger(__name__)

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

# One job at a time: gentle on a low-spec PC running FFmpeg/Whisper, and avoids
# several sessions fighting over the same video's cache files.
_MAX_WORKERS = 1


@dataclass
class Job:
    job_id: str
    session: ProcessingSession
    status: str = STATUS_QUEUED
    stage: str = "queued"
    progress: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    result: Optional[PipelineResult] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def snapshot(self) -> Dict[str, Any]:
        """A thread-safe, JSON-friendly view of the job's current state."""
        with self.lock:
            data: Dict[str, Any] = {
                "job_id": self.job_id,
                "status": self.status,
                "stage": self.stage,
                "progress": dict(self.progress),
                "url": self.session.url,
                "clip_duration": self.session.clip_duration,
                "num_clips_requested": self.session.max_moments,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            }
            if self.status == STATUS_FAILED:
                data["error"] = self.error
            if self.status == STATUS_COMPLETED and self.result is not None:
                data["result"] = self.result.to_dict()
            return data


class JobManager:
    """Owns the job dict and the worker pool. One instance per process (see get_job_manager)."""

    def __init__(self, settings: Optional[Settings] = None, max_workers: int = _MAX_WORKERS) -> None:
        self._settings = settings
        self._jobs: Dict[str, Job] = {}
        self._jobs_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="job")

    def create(self, session: ProcessingSession, **run_session_kwargs: Any) -> Job:
        job = Job(job_id=uuid.uuid4().hex[:12], session=session)
        with self._jobs_lock:
            self._jobs[job.job_id] = job
        self._executor.submit(self._run, job, run_session_kwargs)
        logger.info("Job %s queued for %s", job.job_id, session.url)
        return job

    def get(self, job_id: str) -> Job:
        with self._jobs_lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFoundError(f"No job with id '{job_id}'.")
        return job

    def list(self) -> List[Job]:
        with self._jobs_lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def _update(self, job: Job, **fields: Any) -> None:
        with job.lock:
            for key, value in fields.items():
                setattr(job, key, value)
            job.updated_at = time.time()

    def _on_progress(self, job: Job, stage: str, data: Dict[str, Any]) -> None:
        self._update(job, stage=stage, progress=data)

    def _run(self, job: Job, run_session_kwargs: Dict[str, Any]) -> None:
        self._update(job, status=STATUS_RUNNING, stage="starting")
        try:
            result = run_session(
                job.session, self._settings,
                on_progress=lambda stage, data: self._on_progress(job, stage, data),
                **run_session_kwargs,
            )
            self._update(job, status=STATUS_COMPLETED, stage="done", result=result)
            logger.info("Job %s completed: %d short(s)", job.job_id, len(result.shorts))
        except AppError as exc:
            logger.warning("Job %s failed: %s", job.job_id, exc.message)
            self._update(job, status=STATUS_FAILED, stage="failed", error=exc.message)
        except Exception as exc:  # anything unexpected: never leave a job stuck "running"
            logger.exception("Job %s failed unexpectedly", job.job_id)
            self._update(job, status=STATUS_FAILED, stage="failed", error=f"Unexpected error: {exc}")


_manager: Optional[JobManager] = None
_manager_lock = threading.Lock()


def get_job_manager() -> JobManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = JobManager()
        return _manager


def reset_job_manager() -> None:
    """Testing helper: drop the singleton so a fresh JobManager is created next time."""
    global _manager
    with _manager_lock:
        _manager = None

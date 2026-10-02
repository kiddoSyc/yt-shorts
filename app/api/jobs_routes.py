"""Job-based processing API: create a job, poll its status, fetch/download results.

This is the API a frontend should use (POST /process still exists for quick
synchronous scripting/testing, but blocks for the whole pipeline run).
"""
import logging
import zipfile
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.api.schemas import JobCreateRequest
from app.config import get_settings
from app.exceptions import AppError, ResourceNotFoundError
from app.services.jobs import STATUS_COMPLETED, Job, get_job_manager
from app.services.session import new_session

logger = logging.getLogger(__name__)
router = APIRouter(tags=["jobs"])


def _safe_path_in(directory: Path, filename: str) -> Path:
    """Resolve `filename` inside `directory`, rejecting any attempt to escape it."""
    directory = directory.resolve()
    candidate = (directory / Path(filename).name).resolve()
    if directory not in candidate.parents and candidate != directory:
        raise ResourceNotFoundError("Invalid filename.")
    return candidate


def _clip_entries(job: Job) -> List[Dict[str, Any]]:
    if job.result is None:
        return []
    return [{"filename": Path(c.path).name, "title": c.title, "start": c.start, "end": c.end,
             "duration": c.duration, "url": f"/files/clips/{Path(c.path).name}"}
            for c in job.result.clips]


def _short_entries(job: Job) -> List[Dict[str, Any]]:
    if job.result is None:
        return []
    clip_by_stem = {Path(c.path).stem: c for c in job.result.clips}
    entries = []
    for short_path in job.result.shorts:
        name = Path(short_path).name
        stem = Path(short_path).stem.removesuffix("_short")
        clip = clip_by_stem.get(stem)
        entries.append({
            "filename": name,
            "title": clip.title if clip else name,
            "start": clip.start if clip else None,
            "end": clip.end if clip else None,
            "duration": clip.duration if clip else None,
            "url": f"/files/shorts/{name}",
        })
    return entries


@router.post("/jobs")
def create_job(body: JobCreateRequest) -> Dict[str, Any]:
    """Start processing a YouTube URL. Returns immediately with a job id to poll."""
    ranges = [(r.start, r.end) for r in body.manual_ranges] if body.manual_ranges else None
    session = new_session(body.url, body.clip_duration, max_moments=body.num_clips,
                          moment_prompt=body.prompt, manual_ranges=ranges)
    job = get_job_manager().create(session)
    return job.snapshot()


@router.get("/jobs")
def list_jobs() -> Dict[str, Any]:
    """Most recent jobs first (in-memory only - cleared on server restart)."""
    return {"jobs": [j.snapshot() for j in get_job_manager().list()]}


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> Dict[str, Any]:
    """Poll this for status/progress. Includes the full result once status == 'completed'."""
    return get_job_manager().get(job_id).snapshot()


@router.get("/jobs/{job_id}/shorts")
def get_job_shorts(job_id: str) -> Dict[str, Any]:
    """The final vertical, captioned Shorts for a completed job, with download URLs."""
    job = get_job_manager().get(job_id)
    if job.status != STATUS_COMPLETED:
        return {"job_id": job_id, "status": job.status, "shorts": []}
    return {"job_id": job_id, "status": job.status, "shorts": _short_entries(job)}


@router.get("/jobs/{job_id}/clips")
def get_job_clips(job_id: str) -> Dict[str, Any]:
    """The raw (pre-vertical-formatting) clips for a completed job, with download URLs."""
    job = get_job_manager().get(job_id)
    if job.status != STATUS_COMPLETED:
        return {"job_id": job_id, "status": job.status, "clips": []}
    return {"job_id": job_id, "status": job.status, "clips": _clip_entries(job)}


@router.get("/files/shorts/{filename}")
def download_short(filename: str) -> FileResponse:
    """Stream/download one final Short by filename (as returned by /jobs/{id}/shorts)."""
    path = _safe_path_in(get_settings().shorts_dir, filename)
    if not path.is_file():
        raise ResourceNotFoundError("File not found.")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@router.get("/files/clips/{filename}")
def download_clip(filename: str) -> FileResponse:
    """Stream/download one raw clip by filename (as returned by /jobs/{id}/clips)."""
    path = _safe_path_in(get_settings().clips_dir, filename)
    if not path.is_file():
        raise ResourceNotFoundError("File not found.")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@router.get("/jobs/{job_id}/download-all")
def download_all_shorts(job_id: str) -> FileResponse:
    """Zip every Short from a completed job into one download."""
    job = get_job_manager().get(job_id)
    if job.status != STATUS_COMPLETED or job.result is None:
        raise AppError("Job is not completed yet.")
    if not job.result.shorts:
        raise ResourceNotFoundError("This job produced no Shorts to download.")

    settings = get_settings()
    settings.tmp_dir.mkdir(parents=True, exist_ok=True)
    zip_path = settings.tmp_dir / f"{job_id}_shorts.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:  # mp4 is already compressed
        for short_path in job.result.shorts:
            short_path = Path(short_path)
            if short_path.is_file():
                zf.write(short_path, arcname=short_path.name)
    return FileResponse(zip_path, media_type="application/zip", filename=f"shorts_{job_id}.zip")

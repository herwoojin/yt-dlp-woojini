"""Job routes: list, create, fetch detail."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..auth import UserDep
from ..jobs import registry
from ..models import JobCreateRequest, JobInfo

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=list[JobInfo])
async def list_jobs(user=UserDep) -> list[JobInfo]:
    return registry.list(owner_uid=user["uid"])


@router.post("", response_model=JobInfo, status_code=201)
async def create_job(payload: JobCreateRequest, user=UserDep) -> JobInfo:
    job = await registry.submit(
        url=str(payload.url),
        quality=payload.quality,
        video_format=payload.video_format,
        owner_uid=user["uid"],
    )
    return job


@router.get("/{job_id}", response_model=JobInfo)
async def get_job(job_id: str, user=UserDep) -> JobInfo:
    job = registry.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.owner_uid not in (None, user["uid"]) and not user["uid"].startswith("local"):
        raise HTTPException(status_code=403, detail="forbidden")
    return job

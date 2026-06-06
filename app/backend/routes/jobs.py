"""Job routes: list, create, fetch detail."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from ..auth import UserDep
from ..jobs import registry
from ..models import JobCreateRequest, JobInfo

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=list[JobInfo])
async def list_jobs(user=UserDep) -> list[JobInfo]:
    return registry.list(owner_uid=user["uid"])


@router.post("", response_model=JobInfo, status_code=201)
async def create_job(
    payload: JobCreateRequest,
    user=UserDep,
    x_gemini_key: str | None = Header(default=None),
) -> JobInfo:
    # 헤더 우선, 없으면 body의 gemini_api_key 사용
    api_key = x_gemini_key or payload.gemini_api_key
    job = await registry.submit(
        url=str(payload.url),
        quality=payload.quality,
        video_format=payload.video_format,
        owner_uid=user["uid"],
        gemini_api_key=api_key,
        outputs=payload.outputs,
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


@router.post("/{job_id}/cancel", response_model=JobInfo)
async def cancel_job(job_id: str, user=UserDep) -> JobInfo:
    job = registry.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.owner_uid not in (None, user["uid"]) and not user["uid"].startswith("local"):
        raise HTTPException(status_code=403, detail="forbidden")
    ok = await registry.request_cancel(job_id)
    if not ok:
        raise HTTPException(status_code=409, detail="이미 완료/실패/취소된 작업입니다")
    return registry.get(job_id)


@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: str, user=UserDep) -> None:
    job = registry.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.owner_uid not in (None, user["uid"]) and not user["uid"].startswith("local"):
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        ok = await registry.delete(job_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="job not found")

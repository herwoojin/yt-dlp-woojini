"""Serve job artifacts (video, transcript, html outputs) back to the browser.

Restricted to artifacts inside the job's directory; never allows arbitrary paths.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..auth import UserDep
from ..jobs import registry
from ..services.storage import job_dir

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("/{job_id}/{filename}")
async def get_file(job_id: str, filename: str, user=UserDep) -> FileResponse:
    job = registry.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.owner_uid not in (None, user["uid"]) and not user["uid"].startswith("local"):
        raise HTTPException(status_code=403, detail="forbidden")
    jdir = job_dir(job_id)
    target = (jdir / filename).resolve()
    if not str(target).startswith(str(jdir.resolve())):
        raise HTTPException(status_code=400, detail="invalid filename")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(target, filename=Path(filename).name)

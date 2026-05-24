"""Serve job artifacts (video, transcript, html outputs) back to the browser.

Restricted to artifacts inside the job's directory; never allows arbitrary paths.
"""
from __future__ import annotations

import os
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from ..auth import UserDep
from ..jobs import registry
from ..models import JobInfo
from ..services.storage import job_dir

router = APIRouter(prefix="/api/files", tags=["files"])


_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def _safe_title(title: str | None, fallback: str) -> str:
    raw = (title or fallback).strip()
    cleaned = _UNSAFE_FILENAME.sub("_", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(". ")
    return (cleaned[:80] or fallback)


def _download_basename(job: JobInfo) -> str:
    title = _safe_title(job.title, job.id)
    date = datetime.now().strftime("%Y-%m-%d")
    return f"{title}_{date}"


def _check_access(job: JobInfo | None, user: dict) -> JobInfo:
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.owner_uid not in (None, user["uid"]) and not user["uid"].startswith("local"):
        raise HTTPException(status_code=403, detail="forbidden")
    return job


def _safe_unlink(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


@router.get("/{job_id}/_archive.zip")
async def download_archive(job_id: str, user=UserDep) -> FileResponse:
    job = _check_access(registry.get(job_id), user)
    jdir = job_dir(job_id).resolve()

    tmp = tempfile.NamedTemporaryFile(prefix=f"{job_id}_", suffix=".zip", delete=False)
    tmp.close()
    try:
        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
            seen: set[str] = set()
            for art in job.artifacts:
                if art.filename in seen:
                    continue
                seen.add(art.filename)
                target = (jdir / art.filename).resolve()
                if not str(target).startswith(str(jdir)):
                    continue
                if target.exists() and target.is_file():
                    zf.write(target, arcname=art.filename)
    except Exception:
        _safe_unlink(tmp.name)
        raise

    return FileResponse(
        tmp.name,
        filename=f"{_download_basename(job)}.zip",
        media_type="application/zip",
        background=BackgroundTask(_safe_unlink, tmp.name),
    )


@router.get("/{job_id}/{filename}")
async def get_file(job_id: str, filename: str, user=UserDep) -> FileResponse:
    job = _check_access(registry.get(job_id), user)
    jdir = job_dir(job_id).resolve()
    target = (jdir / filename).resolve()
    if not str(target).startswith(str(jdir)):
        raise HTTPException(status_code=400, detail="invalid filename")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(
        target,
        filename=f"{_download_basename(job)}_{Path(filename).name}",
    )

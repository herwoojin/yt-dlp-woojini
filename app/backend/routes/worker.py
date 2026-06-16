"""fly.dev 릴레이 엔드포인트.

회사 보안(Symantec)이 텔레그램을 막고 회사망/VPN이 인바운드 터널을 깨므로,
맥은 "아웃바운드로만" 여기서 작업을 가져가(claim) 가정용 IP로 처리한 뒤
결과(blog_long.html)를 업로드한다. 인증은 공유 시크릿(WORKER_TOKEN) 헤더.
"""
from __future__ import annotations

from fastapi import APIRouter, Form, Header, HTTPException, Response, UploadFile

from .. import config
from ..jobs import registry

router = APIRouter(prefix="/api/worker", tags=["worker"])


def _auth(token: str | None) -> None:
    if not config.WORKER_TOKEN or token != config.WORKER_TOKEN:
        raise HTTPException(status_code=401, detail="invalid worker token")


@router.get("/next")
async def next_job(x_worker_token: str | None = Header(default=None)):
    """가장 오래된 대기 작업을 가져간다(없으면 204)."""
    _auth(x_worker_token)
    job = await registry.claim_remote_job()
    if job is None:
        return Response(status_code=204)
    return {
        "id": job.id,
        "url": job.url,
        "quality": job.quality,
        "video_format": job.video_format,
        "outputs": job.outputs,
    }


@router.post("/{job_id}/result")
async def submit_result(
    job_id: str,
    file: UploadFile,
    title: str = Form(default=""),
    message: str = Form(default="완료"),
    x_worker_token: str | None = Header(default=None),
):
    """맥 워커가 만든 blog_long.html을 받아 저장하고 작업을 완료 처리."""
    _auth(x_worker_token)
    content = await file.read()
    filename = file.filename or "blog_long.html"
    job = await registry.complete_remote_job(job_id, content, filename, title or None, message)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {"ok": True, "id": job_id, "bytes": len(content)}


@router.post("/{job_id}/fail")
async def submit_fail(
    job_id: str,
    error: str = Form(default=""),
    x_worker_token: str | None = Header(default=None),
):
    _auth(x_worker_token)
    job = await registry.fail_remote_job(job_id, error or "unknown error")
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {"ok": True, "id": job_id}

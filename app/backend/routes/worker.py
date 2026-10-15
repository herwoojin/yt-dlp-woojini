"""fly.dev 릴레이 엔드포인트.

회사 보안(Symantec)이 텔레그램을 막고 회사망/VPN이 인바운드 터널을 깨므로,
맥은 "아웃바운드로만" 여기서 작업을 가져가(claim) 가정용 IP로 처리한 뒤
결과(blog_long.html)를 업로드한다. 인증은 공유 시크릿(WORKER_TOKEN) 헤더.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, Header, HTTPException, Response, UploadFile

from .. import config
from ..jobs import registry
from ..services import telegram_bot

log = logging.getLogger(__name__)

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
    resp = {
        "id": job.id,
        "url": job.url,
        "quality": job.quality,
        "video_format": job.video_format,
        "outputs": job.outputs,
        "naver_mode": job.naver_mode,
        "deep_research": job.deep_research,
        "lang_study": job.lang_study,
        "study_lang": job.study_lang,
    }
    # 딥리서치는 검색 그라운딩+장문이라 토큰을 많이 쓴다. 사용자가 텔레그램으로 등록한
    # 본인 Gemini 키가 있으면 워커가 그 키로 처리하도록 함께 전달(없으면 워커 서버 키 사용).
    if job.deep_research:
        user_key = telegram_bot.get_stored_gemini_key()
        if user_key:
            resp["gemini_api_key"] = user_key
    return resp


@router.post("/{job_id}/progress")
async def submit_progress(
    job_id: str,
    status: str = Form(default=""),
    message: str = Form(default=""),
    progress: float = Form(default=-1.0),
    title: str = Form(default=""),
    x_worker_token: str | None = Header(default=None),
):
    """워커 PC가 처리 중인 단계/메시지를 중계 — 텔레그램 실시간 진행 알림용."""
    _auth(x_worker_token)
    job = await registry.update_remote_progress(job_id, status, message, progress, title)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {"ok": True, "id": job_id}


@router.post("/{job_id}/result")
async def submit_result(
    job_id: str,
    file: UploadFile,
    title: str = Form(default=""),
    message: str = Form(default="완료"),
    naver_html: UploadFile | None = File(default=None),
    naver_images: list[UploadFile] = File(default=[]),
    x_worker_token: str | None = Header(default=None),
):
    """맥 워커가 만든 blog_long.html(+네이버 extras)을 받아 저장하고 작업을 완료 처리."""
    _auth(x_worker_token)
    content = await file.read()
    filename = file.filename or "blog_long.html"

    # Collect naver extra files uploaded alongside the main result
    naver_extras: list[tuple[str, bytes]] = []
    if naver_html is not None:
        nh = await naver_html.read()
        if nh:
            naver_extras.append((naver_html.filename or "blog_naver.html", nh))
    for img_upload in naver_images or []:
        img = await img_upload.read()
        if img:
            naver_extras.append((img_upload.filename or "naver_img.jpg", img))

    job = await registry.complete_remote_job(
        job_id, content, filename, title or None, message,
        naver_extras=naver_extras or None,
    )
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    try:
        telegram_bot.notify_job_done(job)
    except Exception as exc:
        log.warning("telegram notify error for job %s: %s", job_id, exc)
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

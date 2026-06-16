"""맥 워커: fly.dev에서 작업을 아웃바운드로 가져와(claim) 가정용 IP로 처리하고
결과(blog_long.html)를 업로드한다.

회사 보안(Symantec)이 텔레그램을 막고 회사망/VPN이 인바운드 터널을 깨는 환경에서도,
맥이 fly.dev로 "나가는" HTTPS만 쓰므로 안정적으로 동작한다(구글/유튜브가 되면 됨).
백엔드 프로세스 안에서 백그라운드 스레드로 돈다.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time

import requests

from .. import config
from ..jobs import registry
from ..models import JobStatus

log = logging.getLogger(__name__)


def _wait_until_done(job_id: str, timeout: int = 60 * 40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = registry.get(job_id)
        if job and job.status in (JobStatus.DONE, JobStatus.FAILED):
            return job
        time.sleep(2)
    return registry.get(job_id)


def _report_fail(base: str, headers: dict, fly_id: str, error: str) -> None:
    try:
        requests.post(f"{base}/api/worker/{fly_id}/fail",
                      headers=headers, data={"error": error[:900]}, timeout=20)
    except Exception:
        log.warning("fail 보고 실패 %s", fly_id)


def _process(job: dict, loop, base: str, headers: dict) -> None:
    fly_id = job["id"]
    url = job["url"]
    log.info("원격 작업 수신 %s: %s", fly_id, url)
    try:
        local = asyncio.run_coroutine_threadsafe(
            registry.submit(
                url=url,
                quality=job.get("quality") or "flash",
                video_format=job.get("video_format") or "best[ext=mp4]/best",
                owner_uid=f"remote:{fly_id}",
                outputs=job.get("outputs"),
            ),
            loop,
        ).result(timeout=15)
    except Exception as exc:  # noqa: BLE001
        _report_fail(base, headers, fly_id, f"로컬 제출 실패: {exc}")
        return

    final = _wait_until_done(local.id)
    if not final or final.status != JobStatus.DONE:
        _report_fail(base, headers, fly_id, (final.error if final else None) or "처리 실패/시간초과")
        return

    blog = next((a for a in final.artifacts if a.kind == "blog_long"), None)
    if not blog:
        _report_fail(base, headers, fly_id, "blog_long.html이 생성되지 않음")
        return

    from .storage import file_path

    path = file_path(final.id, blog.filename)
    if not os.path.exists(path):
        _report_fail(base, headers, fly_id, "blog_long.html 파일 없음")
        return

    try:
        with open(path, "rb") as f:
            resp = requests.post(
                f"{base}/api/worker/{fly_id}/result",
                headers=headers,
                files={"file": (blog.filename, f, "text/html")},
                data={"title": final.title or "", "message": f"완료 (챕터 {len(final.chapters)}개)"},
                timeout=180,
            )
        log.info("결과 업로드 %s → http %s", fly_id, resp.status_code)
    except Exception as exc:  # noqa: BLE001
        log.warning("결과 업로드 실패 %s: %s", fly_id, str(exc)[:160])


def run_polling() -> None:
    base = config.REMOTE_WORKER_URL
    token = config.WORKER_TOKEN
    if not base or not token:
        log.info("remote worker disabled (REMOTE_WORKER_URL/WORKER_TOKEN 미설정)")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    threading.Thread(target=loop.run_forever, daemon=True, name="remote-worker-asyncio").start()

    headers = {"X-Worker-Token": token}
    log.info("remote worker started: %s 에서 작업 폴링", base)

    fail_streak = 0
    while True:
        try:
            r = requests.get(f"{base}/api/worker/next", headers=headers, timeout=35)
            fail_streak = 0
            if r.status_code == 204:
                time.sleep(5)
                continue
            if r.status_code != 200:
                log.warning("worker/next http %s", r.status_code)
                time.sleep(10)
                continue
            _process(r.json(), loop, base, headers)
        except Exception as exc:  # noqa: BLE001
            fail_streak += 1
            if fail_streak <= 3 or fail_streak % 10 == 0:
                log.warning("remote worker 폴링 오류 #%d (재시도): %s", fail_streak, str(exc)[:160])
            time.sleep(5)

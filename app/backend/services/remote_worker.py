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


_TERMINAL = (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED)
_RELAYABLE = (JobStatus.DOWNLOADING, JobStatus.TRANSCRIBING, JobStatus.GENERATING)


def _relay_progress(base: str, headers: dict, fly_id: str, job) -> None:
    """로컬 처리 단계를 fly.dev로 중계 — 텔레그램 실시간 진행 알림용.
    실패해도 처리 자체에는 영향 없음(조용히 무시)."""
    try:
        requests.post(
            f"{base}/api/worker/{fly_id}/progress",
            headers=headers,
            data={
                "status": job.status.value,
                "message": job.message or "",
                "progress": job.progress,
                "title": job.title or "",
            },
            timeout=10,
        )
    except Exception:
        pass


def _wait_and_relay(local_id: str, fly_id: str, base: str, headers: dict,
                    timeout: int = 60 * 40):
    """로컬 작업 완료를 기다리면서, 단계/메시지가 바뀔 때마다 fly.dev로 중계한다."""
    deadline = time.time() + timeout
    last_sig = None
    last_sent = 0.0
    while time.time() < deadline:
        job = registry.get(local_id)
        if job and job.status in _TERMINAL:
            return job
        if job and job.status in _RELAYABLE:
            sig = (job.status, job.message, round(job.progress, 2), job.title)
            now = time.time()
            if sig != last_sig and now - last_sent >= 3:
                _relay_progress(base, headers, fly_id, job)
                last_sig = sig
                last_sent = now
        time.sleep(2)
    return registry.get(local_id)


def _report_fail(base: str, headers: dict, fly_id: str, error: str) -> None:
    try:
        requests.post(f"{base}/api/worker/{fly_id}/fail",
                      headers=headers, data={"error": error[:900]}, timeout=20)
    except Exception:
        log.warning("fail 보고 실패 %s", fly_id)


def _upload_result(final, fly_id: str, base: str, headers: dict) -> None:
    """완료된 로컬 작업의 결과물(blog_long + 네이버 파일들)을 fly.dev에 업로드."""
    from .storage import file_path

    blog = next((a for a in final.artifacts if a.kind == "blog_long"), None)
    if not blog:
        _report_fail(base, headers, fly_id, "blog_long.html이 생성되지 않음")
        return

    path = file_path(final.id, blog.filename)
    if not os.path.exists(path):
        _report_fail(base, headers, fly_id, "blog_long.html 파일 없음")
        return

    try:
        with open(path, "rb") as f:
            upload_files = [("file", (blog.filename, f.read(), "text/html"))]

        # 네이버 모드: blog_naver.html + 이미지 파일들도 함께 업로드
        if getattr(final, "naver_mode", False):
            naver_art = next((a for a in final.artifacts if a.kind == "blog_naver"), None)
            if naver_art:
                np = file_path(final.id, naver_art.filename)
                if os.path.exists(np):
                    with open(np, "rb") as f:
                        upload_files.append(("naver_html", (naver_art.filename, f.read(), "text/html")))
            for img_art in sorted(
                [a for a in final.artifacts if a.kind == "naver_image"],
                key=lambda a: a.filename,
            ):
                ip = file_path(final.id, img_art.filename)
                if os.path.exists(ip):
                    with open(ip, "rb") as f:
                        upload_files.append(("naver_images", (img_art.filename, f.read(), "image/jpeg")))

        resp = requests.post(
            f"{base}/api/worker/{fly_id}/result",
            headers=headers,
            files=upload_files,
            data={"title": final.title or "", "message": f"완료 (챕터 {len(final.chapters)}개)"},
            timeout=300,
        )
        log.info("결과 업로드 %s → http %s (파일 %d개)", fly_id, resp.status_code, len(upload_files))
    except Exception as exc:  # noqa: BLE001
        log.warning("결과 업로드 실패 %s: %s", fly_id, str(exc)[:160])


def _wait_and_upload(local_id: str, fly_id: str, base: str, headers: dict) -> None:
    final = _wait_and_relay(local_id, fly_id, base, headers)
    if not final or final.status != JobStatus.DONE:
        _report_fail(base, headers, fly_id, (final.error if final else None) or "처리 실패/시간초과")
        return
    _upload_result(final, fly_id, base, headers)


def _resume_interrupted(base: str, headers: dict) -> None:
    """백엔드 재시작 시: 이전 실행에서 fly.dev로부터 가져왔지만(claim) 결과 업로드
    전에 중단된 작업을 이어받는다. _requeue_orphans가 로컬 큐에 다시 넣어주므로
    여기서는 완료를 기다렸다가 업로드만 하면 된다. 이게 없으면 중단된 작업이
    fly.dev에서 영원히 '처리 중'으로 남아 텔레그램 사용자가 결과를 못 받는다."""
    _TERMINAL = (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED)
    for j in registry.list():
        owner = j.owner_uid or ""
        if not owner.startswith("remote:") or j.status in _TERMINAL:
            continue
        fly_id = owner.split(":", 1)[1]
        log.info("중단됐던 원격 작업 이어받기: 로컬 %s (fly %s)", j.id, fly_id)
        threading.Thread(
            target=_wait_and_upload, args=(j.id, fly_id, base, headers),
            daemon=True, name=f"resume-{fly_id[:8]}",
        ).start()


def _process(job: dict, loop, base: str, headers: dict) -> None:
    fly_id = job["id"]
    url = job["url"]
    naver_mode = job.get("naver_mode", False)
    deep_research = job.get("deep_research", False)
    lang_study = job.get("lang_study", False)
    study_lang = job.get("study_lang") or None
    user_key = job.get("gemini_api_key") or None
    log.info("원격 작업 수신 %s: %s (네이버=%s, 딥리서치=%s, 언어학습=%s, 사용자키=%s)",
             fly_id, url, naver_mode, deep_research, lang_study, bool(user_key))
    try:
        local = asyncio.run_coroutine_threadsafe(
            registry.submit(
                url=url,
                quality=job.get("quality") or "flash",
                video_format=job.get("video_format") or "best[ext=mp4]/best",
                owner_uid=f"remote:{fly_id}",
                outputs=job.get("outputs"),
                naver_mode=naver_mode,
                deep_research=deep_research,
                lang_study=lang_study,
                study_lang=study_lang,
                gemini_api_key=user_key,
            ),
            loop,
        ).result(timeout=15)
    except Exception as exc:  # noqa: BLE001
        _report_fail(base, headers, fly_id, f"로컬 제출 실패: {exc}")
        return

    final = _wait_and_relay(local.id, fly_id, base, headers)
    if not final or final.status != JobStatus.DONE:
        _report_fail(base, headers, fly_id, (final.error if final else None) or "처리 실패/시간초과")
        return

    _upload_result(final, fly_id, base, headers)


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

    # 이전 실행에서 중단된 원격 작업이 있으면 이어받아 결과를 업로드
    try:
        _resume_interrupted(base, headers)
    except Exception:
        log.exception("중단된 작업 이어받기 실패 (계속 진행)")

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

"""In-memory job registry plus a single asyncio worker that processes jobs sequentially.

Sequential processing avoids saturating the local disk / Gemini quota; if you
want parallelism, swap the asyncio.Queue worker for a TaskGroup.
"""
from __future__ import annotations

import asyncio
import json
import logging
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from . import config
from .models import GeminiQuality, JobArtifact, JobInfo, JobStatus
from .services import downloader, gemini, storage, transcript

log = logging.getLogger(__name__)


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, JobInfo] = {}
        self._queue: asyncio.Queue[tuple[str, str | None]] = asyncio.Queue()
        self._api_keys: dict[str, str] = {}  # job_id -> gemini api key (메모리 only)
        self._lock = asyncio.Lock()
        self._worker_task: asyncio.Task | None = None
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        base = config.get_download_dir()
        for jdir in base.glob("*"):
            meta = jdir / "job.json"
            if not meta.exists():
                continue
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
                job = JobInfo(**data)
                self._jobs[job.id] = job
            except Exception as exc:
                log.warning("failed to load job %s: %s", jdir.name, exc)

    def list(self, owner_uid: str | None = None) -> list[JobInfo]:
        items = list(self._jobs.values())
        if owner_uid:
            items = [j for j in items if j.owner_uid in (None, owner_uid)]
        items.sort(key=lambda j: j.created_at, reverse=True)
        return items

    def get(self, job_id: str) -> JobInfo | None:
        return self._jobs.get(job_id)

    async def submit(
        self,
        url: str,
        quality: GeminiQuality,
        video_format: str,
        owner_uid: str,
        gemini_api_key: str | None = None,
    ) -> JobInfo:
        job_id = uuid.uuid4().hex[:12]
        now = datetime.utcnow()
        job = JobInfo(
            id=job_id,
            url=url,
            status=JobStatus.PENDING,
            quality=quality,
            video_format=video_format,
            created_at=now,
            updated_at=now,
            owner_uid=owner_uid,
        )
        self._jobs[job_id] = job
        if gemini_api_key:
            self._api_keys[job_id] = gemini_api_key
        await self._persist(job)
        await self._queue.put((job_id, gemini_api_key))
        return job

    async def _persist(self, job: JobInfo) -> None:
        jdir = storage.job_dir(job.id)
        (jdir / "job.json").write_text(job.model_dump_json(indent=2), encoding="utf-8")

    async def _update(self, job_id: str, **fields) -> JobInfo:
        async with self._lock:
            job = self._jobs[job_id]
            data = job.model_dump()
            data.update(fields)
            data["updated_at"] = datetime.utcnow()
            new_job = JobInfo(**data)
            self._jobs[job_id] = new_job
            await self._persist(new_job)
            return new_job

    async def start_worker(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker_loop())

    async def _worker_loop(self) -> None:
        while True:
            job_id, gemini_api_key = await self._queue.get()
            try:
                await self._run_job(job_id, gemini_api_key=gemini_api_key)
            except Exception:
                log.exception("worker failed for job %s", job_id)
                await self._update(job_id, status=JobStatus.FAILED, error=traceback.format_exc())
            finally:
                self._api_keys.pop(job_id, None)  # 사용 후 메모리에서 삭제
                self._queue.task_done()

    async def _run_job(self, job_id: str, gemini_api_key: str | None = None) -> None:
        job = self._jobs[job_id]
        jdir = storage.job_dir(job_id)

        # 1) download
        await self._update(job_id, status=JobStatus.DOWNLOADING, progress=0.05, message="영상 다운로드 중")
        info = await asyncio.to_thread(
            downloader.download,
            job.url,
            jdir,
            video_format=job.video_format,
        )
        artifacts: list[JobArtifact] = []
        for kind, path in info["files"].items():
            p = Path(path)
            if p.exists():
                artifacts.append(JobArtifact(kind=kind, filename=p.name, size_bytes=p.stat().st_size))

        await self._update(
            job_id,
            status=JobStatus.TRANSCRIBING,
            progress=0.4,
            title=info.get("title"),
            duration_seconds=info.get("duration"),
            message="자막/스크립트 정리 중",
            artifacts=artifacts,
        )

        # 2) transcript -> txt (written to disk by service)
        transcript_text = await asyncio.to_thread(transcript.build_transcript_txt, jdir, info)
        t_path = jdir / "transcript.txt"
        artifacts.append(JobArtifact(kind="transcript_txt", filename=t_path.name, size_bytes=t_path.stat().st_size))

        has_transcript = bool(transcript_text) and not transcript_text.startswith("[")

        # 3) Gemini outputs (skip gracefully if no transcript)
        if not has_transcript:
            sub_err = info.get("subtitle_error")
            msg = "자막을 가져올 수 없어 요약/목차 생성을 건너뜁니다 (영상은 저장됨)."
            if sub_err:
                msg += f" 사유: {sub_err[:200]}"
            await self._update(
                job_id,
                status=JobStatus.DONE,
                progress=1.0,
                message=msg,
                artifacts=artifacts,
            )
            return

        await self._update(
            job_id,
            status=JobStatus.GENERATING,
            progress=0.6,
            message="Gemini로 목차/요약/HTML 생성 중",
            artifacts=artifacts,
        )
        try:
            results = await asyncio.to_thread(
                gemini.generate_all,
                jdir,
                info.get("title") or "",
                job.quality,
                api_key=gemini_api_key,
            )
        except Exception as exc:
            log.warning("gemini step failed (non-fatal): %s", exc)
            await self._update(
                job_id,
                status=JobStatus.DONE,
                progress=1.0,
                message=f"영상/스크립트는 저장됨. Gemini 단계 건너뜀: {str(exc)[:200]}",
                artifacts=artifacts,
            )
            return

        for fname, content in [
            ("chapters.json", json.dumps(results["chapters"], ensure_ascii=False, indent=2)),
            ("summary_short.html", results["summary_short_html"]),
            ("email_readable.html", results["email_html"]),
            ("blog_long.html", results["blog_html"]),
        ]:
            p = jdir / fname
            p.write_text(content, encoding="utf-8")
            artifacts.append(JobArtifact(kind=fname.split(".")[0], filename=fname, size_bytes=p.stat().st_size))

        await self._update(
            job_id,
            status=JobStatus.DONE,
            progress=1.0,
            message="완료",
            artifacts=artifacts,
            chapters=results["chapters"],
        )


registry = JobRegistry()

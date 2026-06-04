"""In-memory job registry plus a single asyncio worker that processes jobs sequentially.

Sequential processing avoids saturating the local disk / Gemini quota; if you
want parallelism, swap the asyncio.Queue worker for a TaskGroup.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from . import config
from .models import GeminiQuality, JobArtifact, JobInfo, JobStatus
from .services import downloader, gemini, screenshot, storage, transcript

log = logging.getLogger(__name__)


def _wrap_html(title: str, body_fragment: str) -> str:
    """Gemini는 HTML 조각만 반환하므로, charset/스타일이 포함된 완전한 HTML5
    문서로 감싸 디스크에 저장한다. 그러지 않으면 다운로드해서 브라우저로 열 때
    한글이 인코딩 불일치로 깨져 보임."""
    safe_title = (title or "yt-dlp").replace("<", "&lt;").replace(">", "&gt;")
    return (
        "<!doctype html>\n"
        '<html lang="ko">\n'
        "<head>\n"
        '  <meta charset="utf-8" />\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        f"  <title>{safe_title}</title>\n"
        "  <style>\n"
        "    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif; "
        "max-width: 760px; margin: 24px auto; padding: 0 16px; line-height: 1.65; color: #1f2937; }\n"
        "    h1, h2, h3 { line-height: 1.3 }\n"
        "    a { color: #0369a1 }\n"
        "    code, pre { background: #f1f5f9; border-radius: 4px; padding: 2px 6px; font-size: 0.95em }\n"
        "    pre { padding: 12px; overflow-x: auto }\n"
        "    blockquote { border-left: 4px solid #cbd5e1; margin: 0; padding: 6px 14px; color: #475569 }\n"
        "    img { max-width: 100% }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        f"{body_fragment}\n"
        "</body>\n"
        "</html>\n"
    )


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, JobInfo] = {}
        self._queue: asyncio.Queue[tuple[str, str | None]] = asyncio.Queue()
        self._api_keys: dict[str, str] = {}  # job_id -> gemini api key (메모리 only)
        self._cancelled: set[str] = set()  # 사용자가 중지 요청한 job_id
        self._lock = asyncio.Lock()
        self._worker_task: asyncio.Task | None = None
        self._load_from_disk()

    _ACTIVE = (JobStatus.PENDING, JobStatus.DOWNLOADING,
               JobStatus.TRANSCRIBING, JobStatus.GENERATING)

    def is_cancelled(self, job_id: str) -> bool:
        return job_id in self._cancelled

    async def request_cancel(self, job_id: str) -> bool:
        """진행 중인 작업에 중지 플래그를 세우고 즉시 CANCELLED로 표시한다.
        이미 끝난(완료/실패/취소) 작업이면 False."""
        job = self._jobs.get(job_id)
        if not job or job.status not in self._ACTIVE:
            return False
        self._cancelled.add(job_id)
        await self._update(
            job_id,
            status=JobStatus.CANCELLED,
            message="사용자가 중지함",
        )
        return True

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

    async def delete(self, job_id: str) -> bool:
        """job_dir 전체 + 메모리 등록을 영구 삭제. 진행 중인 작업이면 False."""
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job.status in (JobStatus.PENDING, JobStatus.DOWNLOADING,
                              JobStatus.TRANSCRIBING, JobStatus.GENERATING):
                # 진행 중 삭제는 worker와 race condition이 위험하므로 거부
                raise RuntimeError("진행 중인 작업은 삭제할 수 없습니다 (완료/실패 후 삭제하세요)")
            jdir = storage.job_dir(job_id)
            if jdir.exists():
                shutil.rmtree(jdir, ignore_errors=True)
            self._jobs.pop(job_id, None)
            self._api_keys.pop(job_id, None)
            return True

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
            # 중지된 작업은 진행 중이던 단계가 뒤늦게 끝나도 되살아나지 않게 한다.
            # (CANCELLED/FAILED 같은 종료 상태로의 갱신만 허용)
            if job_id in self._cancelled and fields.get("status") not in (
                JobStatus.CANCELLED, JobStatus.FAILED,
            ):
                return job
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
                self._cancelled.discard(job_id)
                self._queue.task_done()

    async def _run_job(self, job_id: str, gemini_api_key: str | None = None) -> None:
        job = self._jobs[job_id]
        jdir = storage.job_dir(job_id)

        # 1) download
        if self.is_cancelled(job_id):
            return
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

        if self.is_cancelled(job_id):
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
            reason = str(exc)
            low = reason.lower()
            if "timeout" in low or "deadline" in low or "timed out" in low:
                hint = (f"Gemini 응답 시간 초과({config.GEMINI_TIMEOUT_SEC}초). "
                        "네트워크 지연/모델 과부하이거나 자막이 너무 길 수 있습니다.")
            elif "api key" in low or "permission" in low or "401" in low or "403" in low:
                hint = "Gemini API 키가 유효하지 않거나 권한이 없습니다. 설정에서 키를 확인하세요."
            elif "429" in low or "quota" in low or "rate" in low:
                hint = "Gemini API 사용량/쿼터 한도에 걸렸습니다. 잠시 후 다시 시도하세요."
            else:
                hint = f"Gemini 단계 실패: {reason[:200]}"
            log.warning("gemini step failed (non-fatal): %s", exc)
            # 중지된 작업이면 CANCELLED 유지 (DONE으로 덮지 않음)
            if self.is_cancelled(job_id):
                return
            await self._update(
                job_id,
                status=JobStatus.DONE,
                progress=1.0,
                message=f"영상/스크립트는 저장됨. {hint}",
                artifacts=artifacts,
            )
            return
        if self.is_cancelled(job_id):
            return

        video_title = info.get("title") or "yt-dlp 산출물"

        # Screenshot capture: blog images + key scenes ZIP
        await self._update(
            job_id,
            status=JobStatus.GENERATING,
            progress=0.8,
            message="영상 스크린샷 캡처 중",
            artifacts=artifacts,
        )
        try:
            artifacts, updated_blog_html = await self._run_screenshots(
                job_id, jdir, info, results, artifacts,
            )
            results["blog_html"] = updated_blog_html
        except Exception as exc:
            log.warning("screenshot step failed (non-fatal): %s", exc)

        for fname, content in [
            ("chapters.json", json.dumps(results["chapters"], ensure_ascii=False, indent=2)),
            ("summary_short.html", _wrap_html(video_title + " — 요약", results["summary_short_html"])),
            ("email_readable.html", _wrap_html(video_title + " — 이메일", results["email_html"])),
            ("blog_long.html", _wrap_html(video_title + " — 블로그", results["blog_html"])),
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

    async def _run_screenshots(
        self,
        job_id: str,
        jdir: Path,
        info: dict,
        results: dict,
        artifacts: list[JobArtifact],
    ) -> tuple[list[JobArtifact], str]:
        """Capture blog images + key scene screenshots. Returns (updated artifacts, updated blog_html)."""
        blog_html = results["blog_html"]
        video_path = self._find_video(jdir)
        if not video_path:
            log.warning("video file not found for screenshots in %s", jdir)
            return artifacts, blog_html

        # 1) Blog images: capture frames at Gemini-specified timestamps
        blog_timestamps = results.get("blog_image_timestamps", [])
        if blog_timestamps:
            captured = await asyncio.to_thread(
                screenshot.capture_blog_images,
                video_path,
                blog_timestamps,
                jdir,
            )
            # Replace img src in blog HTML with API-accessible paths
            for img in captured:
                old_src = f'blog_img_{img["index"]}.jpg'
                new_src = f'/api/files/{job_id}/{img["filename"]}'
                blog_html = blog_html.replace(old_src, new_src)
                artifacts.append(JobArtifact(
                    kind="blog_image",
                    filename=img["filename"],
                    size_bytes=Path(jdir / img["filename"]).stat().st_size,
                ))
            log.info("captured %d/%d blog images", len(captured), len(blog_timestamps))

        # 2) Key scene screenshots (~20 webp) + ZIP
        chapters = results.get("chapters", [])
        duration = info.get("duration")
        scene_results = await asyncio.to_thread(
            screenshot.capture_key_scenes,
            video_path,
            chapters,
            duration,
            jdir,
            20,
        )
        if scene_results:
            zip_path = await asyncio.to_thread(screenshot.create_screenshots_zip, jdir)
            if zip_path and zip_path.exists():
                artifacts.append(JobArtifact(
                    kind="screenshots_zip",
                    filename="screenshots.zip",
                    size_bytes=zip_path.stat().st_size,
                ))
                log.info("screenshots.zip created with %d scenes", len(scene_results))

        return artifacts, blog_html

    @staticmethod
    def _find_video(jdir: Path) -> Path | None:
        """Find the downloaded video file in the job directory."""
        for ext in (".mp4", ".webm", ".mkv"):
            candidate = jdir / f"video{ext}"
            if candidate.exists():
                return candidate
        # Fallback: any video-like file
        for p in jdir.iterdir():
            if p.suffix in (".mp4", ".webm", ".mkv") and p.stem.startswith("video"):
                return p
        return None


registry = JobRegistry()

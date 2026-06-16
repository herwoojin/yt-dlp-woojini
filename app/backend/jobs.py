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
        self._running_job_id: str | None = None  # 워커가 현재 처리 중인 작업
        self._lock = asyncio.Lock()
        self._worker_task: asyncio.Task | None = None
        self._load_from_disk()

    _ACTIVE = (JobStatus.PENDING, JobStatus.DOWNLOADING,
               JobStatus.TRANSCRIBING, JobStatus.GENERATING)

    def is_cancelled(self, job_id: str) -> bool:
        return job_id in self._cancelled

    @staticmethod
    def _filter_artifacts(
        artifacts: list[JobArtifact],
        outputs: list[str] | None,
    ) -> list[JobArtifact]:
        """사용자가 선택한 산출물만 남기는 필터.
        blog_long/blog_image는 항상 유지, info_json/subtitle은 항상 숨김.
        _update에서 자동 호출되어 모든 상태(진행 중 포함)에 일관 적용된다."""
        _ALWAYS_KEEP = {"blog_long", "blog_image"}
        _ALWAYS_HIDE = {"info_json", "subtitle"}
        _KEYMAP = {
            "video": "video",
            "transcript_txt": "transcript",
            "screenshots_zip": "screenshots",
            "chapters": "chapters",
            "summary_short": "summary",
            "email_readable": "email",
        }
        if outputs is None:
            return [a for a in artifacts if a.kind not in _ALWAYS_HIDE]
        wants = set(outputs)

        def _keep(a: JobArtifact) -> bool:
            if a.kind in _ALWAYS_KEEP:
                return True
            if a.kind in _ALWAYS_HIDE:
                return False
            key = _KEYMAP.get(a.kind)
            return True if key is None else key in wants

        return [a for a in artifacts if _keep(a)]

    def _disk_percent(self) -> float:
        try:
            u = shutil.disk_usage(config.get_download_dir())
            return u.used / u.total * 100.0
        except Exception:
            return 0.0

    async def _evict_job(self, job_id: str) -> None:
        """레지스트리 + 디스크에서 작업을 조용히 제거(자동 정리 전용)."""
        async with self._lock:
            self._jobs.pop(job_id, None)
            self._api_keys.pop(job_id, None)
            self._cancelled.discard(job_id)
        jdir = config.get_download_dir() / job_id
        if jdir.exists():
            shutil.rmtree(jdir, ignore_errors=True)

    async def free_space_if_needed(self, protect_job_id: str | None = None) -> None:
        """디스크 사용률이 높으면 오래된 작업부터 자동 삭제해 공간을 확보한다.
        최근 DISK_KEEP_RECENT개와 진행 중/보호 대상 작업은 삭제하지 않는다."""
        pct = self._disk_percent()
        if pct < config.DISK_HIGH_PERCENT:
            return
        log.warning("disk %.0f%% ≥ %.0f%% — 오래된 작업 자동 정리 시작",
                    pct, config.DISK_HIGH_PERCENT)
        ordered = sorted(self._jobs.values(), key=lambda j: j.created_at)  # 오래된 순
        keep = max(0, config.DISK_KEEP_RECENT)
        deletable = ordered[:-keep] if keep and len(ordered) > keep else ordered
        for job in deletable:
            if job.id == protect_job_id or job.status in self._ACTIVE:
                continue
            await self._evict_job(job.id)
            pct = self._disk_percent()
            log.warning("  ↳ 오래된 작업 %s 자동 삭제 → 디스크 %.0f%%", job.id, pct)
            if pct < config.DISK_TARGET_PERCENT:
                break

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
            if job_id == self._running_job_id:
                # 워커가 실제로 처리 중인 작업(취소됐어도)은 삭제 금지 — 디렉터리 race 방지
                raise RuntimeError("처리 중인 작업이라 잠시 후 삭제하세요")
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
        outputs: list[str] | None = None,
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
            outputs=outputs,
        )
        self._jobs[job_id] = job
        if gemini_api_key:
            self._api_keys[job_id] = gemini_api_key
        await self._persist(job)
        await self._queue.put((job_id, gemini_api_key))
        return job

    # --- fly.dev 릴레이용: 맥 워커가 작업을 가져가고/결과를 올리는 메서드 ---
    async def claim_remote_job(self) -> JobInfo | None:
        """가장 오래된 PENDING 작업을 DOWNLOADING으로 표시하고 반환(맥 워커가 가져감)."""
        async with self._lock:
            pending = sorted(
                (j for j in self._jobs.values() if j.status == JobStatus.PENDING),
                key=lambda j: j.created_at,
            )
            if not pending:
                return None
            job = pending[0]
            data = job.model_dump()
            data["status"] = JobStatus.DOWNLOADING
            data["message"] = "맥 워커가 처리 중..."
            data["updated_at"] = datetime.utcnow()
            new = JobInfo(**data)
            self._jobs[job.id] = new
            await self._persist(new)
            return new

    async def complete_remote_job(
        self, job_id: str, content: bytes, filename: str, title: str | None, message: str
    ) -> JobInfo | None:
        """맥 워커가 올린 blog_long.html을 저장하고 작업을 DONE으로 표시."""
        job = self._jobs.get(job_id)
        if job is None:
            return None
        jdir = storage.job_dir(job_id)
        (jdir / filename).write_bytes(content)
        art = JobArtifact(kind="blog_long", filename=filename, size_bytes=len(content))
        return await self._update(
            job_id,
            status=JobStatus.DONE,
            progress=1.0,
            title=title or job.title,
            message=message,
            artifacts=[*job.artifacts, art],
        )

    async def fail_remote_job(self, job_id: str, error: str) -> JobInfo | None:
        return await self._update(
            job_id, status=JobStatus.FAILED, message="원격 워커 처리 실패", error=error[:1000]
        )

    async def _persist(self, job: JobInfo) -> None:
        jdir = storage.job_dir(job.id)
        (jdir / "job.json").write_text(job.model_dump_json(indent=2), encoding="utf-8")

    async def _update(self, job_id: str, **fields) -> JobInfo | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:  # 처리 도중 삭제된 작업 — 조용히 무시(워커가 죽지 않도록)
                return None
            # 중지된 작업은 진행 중이던 단계가 뒤늦게 끝나도 되살아나지 않게 한다.
            # (CANCELLED/FAILED 같은 종료 상태로의 갱신만 허용)
            if job_id in self._cancelled and fields.get("status") not in (
                JobStatus.CANCELLED, JobStatus.FAILED,
            ):
                return job
            data = job.model_dump()
            data.update(fields)
            # 산출물 목록이 갱신될 때마다 사용자 선택에 맞게 필터링
            if "artifacts" in fields:
                data["artifacts"] = self._filter_artifacts(data["artifacts"], data.get("outputs"))
            data["updated_at"] = datetime.utcnow()
            new_job = JobInfo(**data)
            self._jobs[job_id] = new_job
            await self._persist(new_job)
            return new_job

    async def start_worker(self) -> None:
        if config.REMOTE_DISPATCH:
            # fly.dev: 로컬 처리 워커를 띄우지 않는다(데이터센터 IP는 봇차단됨).
            # 맥 워커가 claim해서 처리하므로, 재시작 시 중단된 작업만 PENDING으로 되돌린다.
            for job in list(self._jobs.values()):
                if job.status in (JobStatus.DOWNLOADING, JobStatus.TRANSCRIBING, JobStatus.GENERATING):
                    await self._update(job.id, status=JobStatus.PENDING, progress=0.0,
                                       message="대기 중 (맥 워커 연결 시 처리)")
            return
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker_loop())
        # 재시작으로 큐가 비워지면 pending/중단된 작업이 영원히 멈춘다 → 다시 큐에 넣는다.
        await self._requeue_orphans()

    async def _requeue_orphans(self) -> None:
        """서버 시작 시, 큐에 없는 미완료 작업(pending/중단된 진행 중)을 다시 큐에 넣는다.
        Gemini 키는 메모리에만 있어 재시작 시 사라지므로 서버 키로 처리된다."""
        for job in list(self._jobs.values()):
            if job.status == JobStatus.PENDING:
                await self._queue.put((job.id, None))
            elif job.status in (JobStatus.DOWNLOADING, JobStatus.TRANSCRIBING, JobStatus.GENERATING):
                await self._update(job.id, status=JobStatus.PENDING, progress=0.0,
                                   message="서버 재시작 후 다시 대기 중")
                await self._queue.put((job.id, None))

    async def _worker_loop(self) -> None:
        # 이 루프는 어떤 일이 있어도 죽으면 안 된다(죽으면 이후 모든 작업이 pending에서 멈춤).
        while True:
            try:
                job_id, gemini_api_key = await self._queue.get()
            except Exception:
                log.exception("queue.get 실패 — 1초 후 재시도")
                await asyncio.sleep(1)
                continue
            self._running_job_id = job_id
            try:
                await self._run_job(job_id, gemini_api_key=gemini_api_key)
            except Exception:
                log.exception("worker failed for job %s", job_id)
                try:
                    await self._update(job_id, status=JobStatus.FAILED, error=traceback.format_exc())
                except Exception:
                    log.exception("작업 실패 표시도 실패(이미 삭제됐을 수 있음) %s", job_id)
            finally:
                self._running_job_id = None
                self._api_keys.pop(job_id, None)  # 사용 후 메모리에서 삭제
                self._cancelled.discard(job_id)
                self._queue.task_done()

    def _drop_video_if_unwanted(self, jdir: Path, artifacts: list[JobArtifact],
                                want_video: bool) -> list[JobArtifact]:
        """영상을 선택하지 않았으면 디스크에서 즉시 삭제하고 목록에서도 제거(서버 용량 보호)."""
        if want_video:
            return artifacts
        vp = self._find_video(jdir)
        if vp:
            try:
                vp.unlink()
            except OSError:
                pass
        return [a for a in artifacts if a.kind != "video"]

    def _prune_disk(self, jdir: Path, kept_artifacts: list[JobArtifact]) -> None:
        """작업 폴더에 '보이는 산출물' 파일과 job.json만 남기고 나머지(내부 임시
        파일: transcript_timed, *.vtt, *.info.json 등)는 삭제 — 선택한 것만 남도록."""
        keep = {a.filename for a in kept_artifacts} | {"job.json"}
        try:
            for f in jdir.iterdir():
                if f.is_file() and f.name not in keep:
                    try:
                        f.unlink()
                    except OSError:
                        pass
        except OSError:
            pass

    async def _run_job(self, job_id: str, gemini_api_key: str | None = None) -> None:
        job = self._jobs.get(job_id)
        if job is None:  # 큐에 있던 사이 삭제됨
            return
        jdir = storage.job_dir(job_id)

        # 0) 영상 다운로드 전에 디스크 자동 확보(오래된 작업부터 삭제)
        await self.free_space_if_needed(protect_job_id=job_id)

        # 1) download
        if self.is_cancelled(job_id):
            return
        await self._update(job_id, status=JobStatus.DOWNLOADING, progress=0.05, message="영상 다운로드 중")
        try:
            info = await asyncio.to_thread(
                downloader.download,
                job.url,
                jdir,
                video_format=job.video_format,
            )
        except Exception as exc:
            msg = "영상 다운로드에 실패했습니다."
            exc_str = str(exc).lower()
            if "drm" in exc_str:
                msg = "이 영상은 DRM으로 보호된 유료/저작권 영상이라 다운로드할 수 없습니다."
            elif "sign in" in exc_str or "members-only" in exc_str:
                msg = "이 영상은 로그인이 필요하거나 회원 전용 영상이라 다운로드할 수 없습니다."
            elif "private" in exc_str:
                msg = "이 영상은 비공개 영상이라 다운로드할 수 없습니다."
            
            log.warning("video download failed for job %s: %s", job_id, exc)
            await self._update(job_id, status=JobStatus.FAILED, message=msg, error=traceback.format_exc())
            return
        artifacts: list[JobArtifact] = []
        for kind, path in info["files"].items():
            p = Path(path)
            if p.exists():
                artifacts.append(JobArtifact(kind=kind, filename=p.name, size_bytes=p.stat().st_size))

        wants = set(job.outputs) if job.outputs is not None else None

        def want(k: str) -> bool:
            return wants is None or k in wants

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

        # 2b) 자막을 못 받았으면(429/자막없음) 영상 음성을 맥에서 직접 받아쓰기(Whisper) 폴백.
        # 이미 받은 video.mp4를 이용하므로 YouTube 자막 의존이 사라진다.
        if not has_transcript:
            video_path = self._find_video(jdir)
            if video_path:
                await self._update(
                    job_id,
                    status=JobStatus.TRANSCRIBING,
                    progress=0.45,
                    message="자막이 없어 음성 인식(Whisper)으로 자막 생성 중... (수십 초~수 분)",
                    artifacts=artifacts,
                )
                vtt = await asyncio.to_thread(transcript.transcribe_to_vtt, video_path, jdir)
                if vtt:
                    info.setdefault("files", {})["subtitle"] = str(vtt)
                    transcript_text = await asyncio.to_thread(transcript.build_transcript_txt, jdir, info)
                    has_transcript = bool(transcript_text) and not transcript_text.startswith("[")
                    if has_transcript:
                        log.info("whisper 폴백으로 자막 확보 — 블로그 생성 계속")

        # 3) Gemini outputs (skip gracefully if no transcript)
        if not has_transcript:
            sub_err = info.get("subtitle_error")
            msg = "자막을 가져올 수 없어 요약/목차 생성을 건너뜁니다."
            if sub_err:
                msg += f" 사유: {sub_err[:200]}"
            artifacts = self._drop_video_if_unwanted(jdir, artifacts, want("video"))
            self._prune_disk(jdir, self._filter_artifacts(artifacts, job.outputs))
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
                wants=wants,
            )
        except Exception as exc:
            reason = str(exc)
            low = reason.lower()
            if "timeout" in low or "deadline" in low or "timed out" in low:
                hint = (f"Gemini 응답 시간 초과({config.GEMINI_TIMEOUT_SEC}초). "
                        "네트워크 지연/모델 과부하이거나 자막이 너무 길 수 있습니다.")
            elif "prepay" in low or "credit" in low or "billing" in low:
                hint = ("Gemini API 결제 크레딧이 소진되었습니다. AI Studio(ai.studio/projects)에서 "
                        "크레딧을 충전하세요. 임시로는 Flash가 단가가 훨씬 낮습니다.")
            elif "per day" in low or "daily" in low or "requests per day" in low:
                hint = "Gemini API 일일 한도를 초과했습니다. 내일 다시 시도하거나 결제 등급을 확인하세요."
            elif "api key" in low or "permission" in low or "401" in low or "403" in low:
                hint = "Gemini API 키가 유효하지 않거나 권한이 없습니다. 설정에서 키를 확인하세요."
            elif "429" in low or "quota" in low or "rate" in low:
                hint = "Gemini API 분당 한도(RPM)에 걸렸습니다. 잠시 후 다시 시도하세요."
            else:
                hint = f"Gemini 단계 실패: {reason[:200]}"
            log.warning("gemini step failed (non-fatal): %s", exc)
            # 중지된 작업이면 CANCELLED 유지 (DONE으로 덮지 않음)
            if self.is_cancelled(job_id):
                return
            artifacts = self._drop_video_if_unwanted(jdir, artifacts, want("video"))
            self._prune_disk(jdir, self._filter_artifacts(artifacts, job.outputs))
            await self._update(
                job_id,
                status=JobStatus.DONE,
                progress=1.0,
                message=hint,
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
                want_screenshots=want("screenshots"),
            )
            results["blog_html"] = updated_blog_html
        except Exception as exc:
            log.warning("screenshot step failed (non-fatal): %s", exc)

        # 영상은 블로그용 자막/스크린샷 추출에만 필요 → 선택 안 했으면 사용 직후 즉시 삭제(서버 용량 보호)
        artifacts = self._drop_video_if_unwanted(jdir, artifacts, want("video"))

        # blog_long은 항상 생성. chapters/summary/email은 선택 시에만 파일로 남김.
        to_write: list[tuple[str, str]] = [
            ("blog_long.html", _wrap_html(video_title + " — 블로그", results["blog_html"])),
        ]
        if want("chapters"):
            to_write.append(("chapters.json", json.dumps(results["chapters"], ensure_ascii=False, indent=2)))
        if results.get("summary_short_html"):  # wants에 summary 포함됐을 때만 생성됨
            to_write.append(("summary_short.html", _wrap_html(video_title + " — 요약", results["summary_short_html"])))
        if results.get("email_html"):
            to_write.append(("email_readable.html", _wrap_html(video_title + " — 이메일", results["email_html"])))
        for fname, content in to_write:
            p = jdir / fname
            p.write_text(content, encoding="utf-8")
            artifacts.append(JobArtifact(kind=fname.split(".")[0], filename=fname, size_bytes=p.stat().st_size))

        # 선택한 산출물 + 블로그 필수만 남기고 내부 임시 파일 정리
        self._prune_disk(jdir, self._filter_artifacts(artifacts, job.outputs))

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
        want_screenshots: bool = True,
    ) -> tuple[list[JobArtifact], str]:
        """Capture blog images (always, for blog) + optional key-scene ZIP.
        blog 이미지는 블로그에 필요해 항상 캡처. 키 장면 ZIP은 want_screenshots일 때만."""
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
            # Replace img src in blog HTML with self-contained base64 data URIs
            # so the blog HTML renders everywhere (텔레그램 다운로드/Tistory 붙여넣기/웹)
            # without depending on the backend /api/files origin being reachable.
            import base64

            for img in captured:
                fpath = jdir / img["filename"]
                old_src = f'blog_img_{img["index"]}.jpg'
                try:
                    b64 = base64.b64encode(fpath.read_bytes()).decode("ascii")
                    new_src = f"data:image/jpeg;base64,{b64}"
                except Exception as exc:
                    log.warning("base64 embed failed for %s: %s", img["filename"], exc)
                    new_src = f'/api/files/{job_id}/{img["filename"]}'
                blog_html = blog_html.replace(old_src, new_src)
                artifacts.append(JobArtifact(
                    kind="blog_image",
                    filename=img["filename"],
                    size_bytes=fpath.stat().st_size,
                ))
            log.info("captured %d/%d blog images", len(captured), len(blog_timestamps))

        # 2) Key scene screenshots (~20 webp) + ZIP — 선택했을 때만 작업 수행
        if not want_screenshots:
            return artifacts, blog_html
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

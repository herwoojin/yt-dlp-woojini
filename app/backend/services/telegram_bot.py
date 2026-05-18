"""Telegram bot that mirrors bot.py functionality, but uses the unified job
pipeline (download + Gemini outputs) and runs as a background thread inside
the FastAPI process.

The bot replies with a status link to the web UI for full results. If the
video is under 50MB it also uploads the video file to Telegram, matching the
original bot.py behavior.
"""
from __future__ import annotations

import asyncio
import logging
import os

import telebot

from .. import config
from ..jobs import registry
from ..models import JobStatus

log = logging.getLogger(__name__)


def run_polling() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN not set; bot disabled")
        return

    bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    @bot.message_handler(commands=["start", "help"])
    def _welcome(message):
        bot.reply_to(
            message,
            "안녕하세요! yt-dlp 통합 봇입니다. 🚀\n"
            "유튜브 URL을 보내주시면 다운로드 + 자막 + 요약 + HTML(이메일/블로그) 까지 생성합니다.\n"
            "(50MB 이하 영상은 텔레그램으로도 전송)",
        )

    @bot.message_handler(func=lambda m: True)
    def _handle(message):
        url = (message.text or "").strip()
        if not url.startswith("http"):
            bot.reply_to(message, "올바른 URL을 입력해주세요. (http... 로 시작)")
            return
        bot.reply_to(message, "작업 등록 중... ⏳")
        owner = f"tg:{message.from_user.id}" if message.from_user else "tg:unknown"
        try:
            job = asyncio.run_coroutine_threadsafe(
                registry.submit(url=url, quality="flash", video_format="best[ext=mp4][filesize<50M]/best[filesize<50M]/best", owner_uid=owner),
                loop,
            ).result(timeout=10)
        except Exception as exc:
            bot.reply_to(message, f"작업 등록 실패: {exc}")
            return

        bot.reply_to(
            message,
            f"작업 ID: `{job.id}`\n진행 상황은 웹앱에서 확인하실 수 있습니다.",
            parse_mode="Markdown",
        )

        # poll until done, then push video back if small enough
        try:
            final = _wait_until_done(job.id, timeout=60 * 30)
            if final and final.status == JobStatus.DONE:
                video_artifact = next((a for a in final.artifacts if a.kind == "video"), None)
                if video_artifact and (video_artifact.size_bytes or 0) <= 50 * 1024 * 1024:
                    from .storage import file_path

                    path = file_path(final.id, video_artifact.filename)
                    if os.path.exists(path):
                        with open(path, "rb") as f:
                            bot.send_video(message.chat.id, f, caption=(final.title or "")[:1024])
                bot.send_message(
                    message.chat.id,
                    f"완료! 📚 챕터 {len(final.chapters)}개 / HTML 산출물 3종 생성됨.",
                )
            elif final and final.status == JobStatus.FAILED:
                bot.send_message(message.chat.id, f"❌ 실패: {(final.error or '')[:500]}")
        except Exception as exc:
            log.exception("telegram post-job notify failed")
            bot.send_message(message.chat.id, f"알림 실패: {exc}")

    # spin a side loop so we can submit to the asyncio registry from sync handlers
    def _bg_loop():
        loop.run_forever()

    import threading

    threading.Thread(target=_bg_loop, daemon=True, name="tg-asyncio").start()

    log.info("telegram bot polling started")
    bot.infinity_polling(skip_pending=True)


def _wait_until_done(job_id: str, timeout: int = 1800):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        job = registry.get(job_id)
        if job and job.status in (JobStatus.DONE, JobStatus.FAILED):
            return job
        time.sleep(2)
    return registry.get(job_id)

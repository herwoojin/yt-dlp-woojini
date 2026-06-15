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
import re
import time

import telebot

from .. import config
from ..jobs import registry
from ..models import JobStatus

log = logging.getLogger(__name__)

START_TS = time.time()


def run_polling() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN not set; bot disabled")
        return

    bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    HELP_TEXT = (
        "안녕하세요! [JINI+US] 유튜브 다운로드 봇입니다. 🚀\n\n"
        "이렇게 쓰시면 됩니다:\n"
        "• 유튜브 URL 붙여넣기 → 자막 + 요약 분석 후 "
        "📝 블로그 HTML(blog_long)을 이 채팅으로 보내드립니다 (영상 파일은 전송 안 함)\n"
        "• \"살아있어?\" · \"서버 상태\" · \"다운로드 돼?\" → 맥 서버 상태 확인\n"
        "• \"재시작\" → 맥 백엔드 다시 시작\n"
        "• \"도움\" → 이 안내 다시 보기\n\n"
        "⚠️ 맥이 꺼져 있으면 이 봇도 응답하지 않습니다. "
        "그땐 맥을 켜면 자동으로 다시 살아납니다."
    )

    def _status_text() -> str:
        up = int(time.time() - START_TS)
        h, m = up // 3600, (up % 3600) // 60
        try:
            active = sum(
                1 for j in registry.list()
                if j.status not in (JobStatus.DONE, JobStatus.FAILED)
            )
        except Exception:
            active = 0
        return (
            "✅ 맥 서버 정상 작동 중입니다.\n"
            "• 다운로드: 가능\n"
            f"• 진행 중 작업: {active}개\n"
            f"• 가동 시간: {h}시간 {m}분\n\n"
            "유튜브 URL을 보내시면 바로 받아드립니다."
        )

    @bot.message_handler(commands=["start", "help"])
    def _welcome(message):
        bot.reply_to(message, HELP_TEXT)

    @bot.message_handler(func=lambda m: True)
    def _handle(message):
        text = (message.text or "").strip()

        # URL 추출 (그냥 붙여넣거나 "이거 받아줘 <url>" 형태 모두 허용)
        m_url = re.search(r"https?://\S+", text)
        if not m_url:
            # 자연어 명령 라우팅
            if re.search(r"재시작|다시\s*시작|리부트|리스타트|restart|재기동", text, re.I):
                bot.reply_to(message, "♻️ 맥 백엔드를 재시작합니다. 10초 뒤 다시 보내보세요.")
                import subprocess
                subprocess.Popen(
                    ["launchctl", "kickstart", "-k",
                     f"gui/{os.getuid()}/com.user.ytdlp-backend"]
                )
                return
            if re.search(r"상태|살아|살았|켜졌|켜져|괜찮|작동|동작|status|헬스|health|ping|핑|되나|돼\?|가능", text, re.I):
                bot.reply_to(message, _status_text())
                return
            if re.search(r"도움|도와|명령|사용법|help|어떻게|뭐\s*해|뭐\s*할", text, re.I):
                bot.reply_to(message, HELP_TEXT)
                return
            bot.reply_to(
                message,
                "유튜브 URL을 보내주세요. 🎬\n"
                "또는 \"살아있어?\"(상태확인) · \"재시작\" · \"도움\" 이라고 하셔도 됩니다.",
            )
            return

        url = m_url.group(0)
        bot.reply_to(message, "작업 등록 중... ⏳")
        owner = f"tg:{message.from_user.id}" if message.from_user else "tg:unknown"
        try:
            job = asyncio.run_coroutine_threadsafe(
                registry.submit(url=url, quality="flash", video_format="best[ext=mp4]/best", owner_uid=owner),
                loop,
            ).result(timeout=10)
        except Exception as exc:
            bot.reply_to(message, f"작업 등록 실패: {exc}")
            return

        bot.reply_to(
            message,
            f"작업 ID: `{job.id}`\n분석 중입니다... ⏳ 완료되면 📝 블로그 HTML을 여기로 보내드립니다. (보통 1~3분)",
            parse_mode="Markdown",
        )

        # poll until done, then push the blog_long HTML back (영상은 전송하지 않음)
        try:
            final = _wait_until_done(job.id, timeout=60 * 30)
            if final and final.status == JobStatus.DONE:
                blog_artifact = next((a for a in final.artifacts if a.kind == "blog_long"), None)
                sent = False
                if blog_artifact:
                    from .storage import file_path

                    path = file_path(final.id, blog_artifact.filename)
                    if os.path.exists(path):
                        with open(path, "rb") as f:
                            bot.send_document(
                                message.chat.id,
                                f,
                                visible_file_name=blog_artifact.filename,
                                caption=(final.title or "블로그")[:1024],
                            )
                        sent = True
                if sent:
                    bot.send_message(
                        message.chat.id,
                        f"완료! 📝 블로그 HTML 전송 완료 (챕터 {len(final.chapters)}개).",
                    )
                else:
                    bot.send_message(
                        message.chat.id,
                        "완료됐지만 blog_long.html을 찾지 못했습니다. 웹앱에서 확인해주세요.",
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

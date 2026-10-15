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
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import telebot

from .. import config
from ..jobs import registry
from ..models import JobStatus

log = logging.getLogger(__name__)

START_TS = time.time()

# Persistent cookies file location (fly.dev /data volume or env override)
_COOKIES_PATH = Path(os.getenv("YT_DLP_COOKIES_FILE") or "/data/youtube_cookies.txt")

_COOKIE_GUIDE = (
    "🍪 유튜브 쿠키 설정 방법\n\n"
    "1️⃣ Chrome/Edge에 확장 프로그램 설치:\n"
    "   「Get cookies.txt LOCALLY」 검색 후 설치\n\n"
    "2️⃣ YouTube (youtube.com) 에 로그인\n\n"
    "3️⃣ YouTube 탭에서 확장 프로그램 클릭\n"
    "   → Export As → 「Netscape」 선택 → 다운로드\n\n"
    "4️⃣ 다운로드된 .txt 파일을\n"
    "   이 채팅에 그대로 전송해주세요!\n\n"
    "⚠️ 쿠키는 내 YouTube 로그인 세션입니다.\n"
    "   다른 사람과 공유하지 마세요."
)

# 사용자가 텔레그램으로 등록한 Gemini API 키 저장 위치(딥리서치용, fly.dev /data 볼륨).
_GEMINI_KEY_PATH = Path(os.getenv("GEMINI_KEY_FILE") or "/data/gemini_api_key.txt")

# Gemini API 키 형식: "AIza" + 35자([A-Za-z0-9_-])
_GEMINI_KEY_RE = re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")

_GEMINI_KEY_GUIDE = (
    "🔑 딥리서치용 Gemini API 키 등록 방법\n\n"
    "딥리서치(2번) 버전은 웹 검색 + 긴 글 작성으로 토큰을 많이 씁니다.\n"
    "본인 Gemini API 키를 등록하면 그 키로 처리해 한도 걱정이 줄어듭니다.\n"
    "(등록 안 해도 서버 기본 키로 동작은 합니다.)\n\n"
    "1️⃣ https://aistudio.google.com/app/apikey 접속\n"
    "2️⃣ 「Create API key」로 키 생성 (AIza... 로 시작)\n"
    "3️⃣ 그 키를 이 채팅에 그대로 붙여넣어 전송\n\n"
    "• 「키 확인」 → 등록 여부 확인\n"
    "• 「키 삭제」 → 등록된 키 삭제\n\n"
    "⚠️ API 키는 비밀번호와 같습니다. 전송 후 보안을 위해\n"
    "   해당 메시지를 삭제하는 것을 권장합니다."
)


def get_stored_gemini_key() -> str | None:
    """저장된 사용자 Gemini 키를 반환(없으면 None). worker.py가 딥리서치 작업에
    이 키를 실어 워커로 보낸다."""
    try:
        if _GEMINI_KEY_PATH.exists():
            return _GEMINI_KEY_PATH.read_text(encoding="utf-8").strip() or None
    except Exception:
        return None
    return None


# Module-level bot instance — set when run_polling() initialises.
# Used by notify_job_done() so worker.py can push results to Telegram
# without going through the polling thread.
_bot: "telebot.TeleBot | None" = None

# --- 버전 선택(일반/딥리서치) 대기 상태 -------------------------------------
# URL이 오면 즉시 제출하지 않고 "1(일반)/2(딥리서치)?"를 물은 뒤, 10초 안에
# 답이 없으면 일반으로 진행한다. 채팅별로 하나의 대기 상태만 유지한다.
_PENDING_CHOICE_TIMEOUT = 10.0


class _PendingChoice:
    def __init__(self, url: str, naver_mode: bool):
        self.url = url
        self.naver_mode = naver_mode
        self.choice: str | None = None  # None → 미응답, "normal" | "deep" | "study"
        self.event = threading.Event()
        # 언어학습(3번)을 고르면 "무슨 언어를 배우나"를 한 번 더 묻는다. 그때 stage가 "lang"이 되고
        # 같은 대기 객체를 재사용한다(채팅당 대기는 하나만 유지하는 기존 구조 유지).
        self.stage = "version"
        self.lang: str | None = None


# 언어학습에서 고를 수 있는 목표 언어. 번호/언어명 아무거나 받는다.
_STUDY_LANGS: list[tuple[str, str]] = [
    ("1", "일본어"), ("2", "중국어"), ("3", "영어"),
    ("4", "스페인어"), ("5", "베트남어"),
]
_LANG_ALIASES: dict[str, str] = {
    "일본어": "일본어", "일어": "일본어", "japanese": "일본어", "jp": "일본어", "일본": "일본어",
    "중국어": "중국어", "중어": "중국어", "chinese": "중국어", "cn": "중국어", "중국": "중국어",
    "한자": "중국어", "병음": "중국어",
    "영어": "영어", "english": "영어", "en": "영어",
    "스페인어": "스페인어", "스페인": "스페인어", "spanish": "스페인어",
    "베트남어": "베트남어", "베트남": "베트남어", "vietnamese": "베트남어",
    "프랑스어": "프랑스어", "불어": "프랑스어", "french": "프랑스어",
    "독일어": "독일어", "독어": "독일어", "german": "독일어",
    "러시아어": "러시아어", "러시아": "러시아어", "russian": "러시아어",
    "태국어": "태국어", "태국": "태국어", "thai": "태국어",
}


def _parse_study_lang(text: str) -> str | None:
    """'2', '중국어', 'chinese', '일본어 공부' → 표준 언어명. 못 알아들으면 None."""
    t = text.strip().lower()
    for key, name in _LANG_ALIASES.items():
        if key in t:
            return name
    m = re.match(r"^\s*([1-5])\s*(번)?\s*$", t)
    if m:
        return dict(_STUDY_LANGS)[m.group(1)]
    # "기타: 포르투갈어" 처럼 직접 적은 경우 — 'OO어'를 그대로 받는다
    m2 = re.search(r"([가-힣]{2,6}어)", text)
    if m2 and m2.group(1) not in ("한국어", "외국어", "표준어"):
        return m2.group(1)
    return None


_pending: dict[int, _PendingChoice] = {}
_pending_lock = threading.Lock()


def _resolve_pending(chat_id: int, choice: str) -> bool:
    """대기 중인 선택에 답을 설정하고 대기 스레드를 깨운다. 대기가 없으면 False."""
    with _pending_lock:
        p = _pending.get(chat_id)
        if p is None:
            return False
        p.choice = choice
        p.event.set()
        return True


def _resolve_pending_lang(chat_id: int, lang: str) -> bool:
    """'무슨 언어를 배우나' 대기에 답을 설정하고 대기 스레드를 깨운다."""
    with _pending_lock:
        p = _pending.get(chat_id)
        if p is None or p.stage != "lang":
            return False
        p.lang = lang
        p.event.set()
        return True


def _match_deep(text: str) -> bool:
    """'2', '2번', '딥리서치', '리서치', '심층', 'deep' → 딥리서치 버전 선택."""
    return bool(re.search(r"(?<![0-9])2(?![0-9])|2번|②|딥\s*리서치|deep|심층|리서치", text, re.I))


def _match_normal(text: str) -> bool:
    """'1', '1번', '일반', '기본', 'normal' → 일반 버전 선택."""
    return bool(re.search(r"(?<![0-9])1(?![0-9])|1번|①|일반|기본|normal|standard", text, re.I))


def _match_study(text: str) -> bool:
    """'3', '3번', '언어', '언어공부', '언어학습', 'study' → 언어학습 버전 선택."""
    return bool(re.search(r"(?<![0-9])3(?![0-9])|3번|③|언어\s*(공부|학습)?|어학|study|language", text, re.I))

# 결과를 이미 전송한 작업 ID — notify_job_done(워커 업로드 경로)와
# 텔레그램 핸들러(폴링 경로)가 같은 파일을 두 번 보내는 중복을 막는다.
_sent_results: set[str] = set()
_sent_lock = threading.Lock()


def _claim_send(job_id: str) -> bool:
    """이 작업의 결과 전송 권한을 원자적으로 획득. 이미 다른 경로가 보냈으면 False."""
    with _sent_lock:
        if job_id in _sent_results:
            return False
        _sent_results.add(job_id)
        return True


def _unclaim_send(job_id: str) -> None:
    """전송 실패 시 권한 반납 — 다른 경로가 재시도할 수 있게."""
    with _sent_lock:
        _sent_results.discard(job_id)


def _result_filename(title: str | None, tag: str = "", ext: str = ".html") -> str:
    """산출물 파일명: 오늘 날짜(KST) + 영상 제목(핵심 문장).
    예: 260702_한국은 AI 시대의 표준이 되고 있다_네이버.html"""
    kst = timezone(timedelta(hours=9))
    date = datetime.now(kst).strftime("%y%m%d")
    core = re.sub(r'[\\/:*?"<>|#%&{}$!@+`=\r\n]+', " ", title or "")
    core = re.sub(r"\s+", " ", core).strip()[:40].strip(" ._-") or "블로그"
    tag_part = f"_{tag}" if tag else ""
    return f"{date}_{core}{tag_part}{ext}"


def notify_job_done(job) -> None:
    """Send the completed blog HTML to Telegram (called from worker.py result endpoint).

    Works on fly.dev where the bot token is active.  Does nothing if the bot
    is not initialised or the job was not submitted via Telegram.
    """
    if _bot is None:
        return
    owner = getattr(job, "owner_uid", None) or ""
    if not owner.startswith("tg:"):
        return
    chat_id_str = owner[3:]
    if not chat_id_str or chat_id_str == "unknown":
        return
    try:
        chat_id = int(chat_id_str)
    except ValueError:
        return

    blog_artifact = next((a for a in job.artifacts if a.kind == "blog_long"), None)
    if not blog_artifact:
        _bot.send_message(chat_id, "완료됐지만 blog_long.html을 찾지 못했습니다. 웹앱에서 확인해주세요.")
        return

    from .storage import file_path

    path = file_path(job.id, blog_artifact.filename)
    if not os.path.exists(path):
        _bot.send_message(chat_id, "완료됐지만 파일을 찾을 수 없습니다. 웹앱에서 확인해주세요.")
        return

    if not _claim_send(job.id):
        return  # 텔레그램 핸들러(폴링 경로)에서 이미 전송함 — 중복 방지

    try:
        with open(path, "rb") as f:
            _bot.send_document(
                chat_id,
                f,
                visible_file_name=_result_filename(job.title),
                caption=(job.title or "블로그")[:1024],
            )
        done_msg = "🎉 완료! 📝 블로그 HTML 전송 완료"
        if job.chapters:
            done_msg += f" (챕터 {len(job.chapters)}개)"
        _bot.send_message(chat_id, done_msg)

        # 네이버 모드일 때 네이버용 파일도 전송
        if getattr(job, "naver_mode", False):
            _send_naver_files(_bot, chat_id, job)

        log.info("telegram notify sent for job %s to chat %s", job.id, chat_id)
    except Exception as exc:
        _unclaim_send(job.id)  # 실패 시 폴링 경로가 재시도할 수 있게
        log.warning("telegram notify failed for job %s: %s", job.id, exc)


def _send_naver_files(bot, chat_id: int, job) -> None:
    """Send Naver-optimized blog HTML + individual image files via Telegram."""
    from .storage import file_path

    # 1) 네이버용 HTML 파일 전송
    naver_artifact = next((a for a in job.artifacts if a.kind == "blog_naver"), None)
    if naver_artifact:
        naver_path = file_path(job.id, naver_artifact.filename)
        if os.path.exists(naver_path):
            try:
                with open(naver_path, "rb") as f:
                    bot.send_document(
                        chat_id,
                        f,
                        visible_file_name=_result_filename(job.title, tag="네이버"),
                        caption="🌟 네이버 블로그용 HTML",
                    )
            except Exception as exc:
                log.warning("naver html send failed: %s", exc)

    # 2) 네이버용 이미지 파일들 개별 전송 (사진으로 전송 → 네이버 에디터에 드래그 삽입용)
    naver_images = sorted(
        [a for a in job.artifacts if a.kind == "naver_image"],
        key=lambda a: a.filename,
    )
    if naver_images:
        bot.send_message(
            chat_id,
            f"🖼 네이버 블로그용 이미지 {len(naver_images)}장을 전송합니다.\n"
            f"네이버 블로그 에디터에서 글 사이에 이미지를 삽입해주세요.",
        )
        for img_art in naver_images:
            img_path = file_path(job.id, img_art.filename)
            if os.path.exists(img_path):
                try:
                    with open(img_path, "rb") as f:
                        bot.send_photo(
                            chat_id,
                            f,
                            caption=img_art.filename,
                        )
                except Exception as exc:
                    log.warning("naver image send failed for %s: %s", img_art.filename, exc)


def _submit_and_deliver(bot, loop, chat_id: int, url: str, naver_mode: bool,
                        deep_research: bool, owner: str, lang_study: bool = False,
                        study_lang: str | None = None) -> None:
    """작업을 등록하고 완료까지 진행 상황을 실시간 알린 뒤 결과물을 전송한다.
    버전 선택이 끝난 후 백그라운드 스레드에서 호출된다(폴링 루프를 막지 않도록)."""
    mode_bits = []
    if lang_study:
        mode_bits.append("📚 언어학습" + (f"({study_lang})" if study_lang else ""))
    if deep_research:
        mode_bits.append("🔬 딥리서치")
    if naver_mode:
        mode_bits.append("🌟 네이버")
    mode_suffix = (" (" + " + ".join(mode_bits) + ")") if mode_bits else ""

    try:
        job = asyncio.run_coroutine_threadsafe(
            registry.submit(
                url=url, quality="flash",
                video_format="best[ext=mp4]/best",
                owner_uid=owner,
                naver_mode=naver_mode,
                deep_research=deep_research,
                lang_study=lang_study,
                study_lang=study_lang,
            ),
            loop,
        ).result(timeout=10)
    except Exception as exc:
        bot.send_message(chat_id, f"작업 등록 실패: {exc}")
        return

    steps = [
        "  1️⃣ 영상 다운로드       (약 1~3분)",
        "  2️⃣ 자막 추출           (약 30초~2분)",
    ]
    steps.append("  3️⃣ 📚 언어학습 글 작성 (약 1~4분)" if lang_study
                 else "  3️⃣ 딥리서치 심층 작성  (약 3~6분)" if deep_research
                 else "  3️⃣ AI 블로그 생성      (약 1~3분)")
    if naver_mode:
        steps.append(f"  {len(steps) + 1}️⃣ 네이버용 별도 생성  (약 1~2분)")
    total_eta = "보통 5~12분" if deep_research else "보통 3~8분"
    bot.send_message(
        chat_id,
        f"✅ 작업 등록 완료!{mode_suffix}  🆔 `{job.id[:8]}`\n\n"
        f"📋 처리 순서\n" + "\n".join(steps) +
        f"\n\n⏱ 총 예상 시간: {total_eta}\n"
        f"각 단계마다 진행 상황을 알려드릴게요!",
        parse_mode="Markdown",
    )

    try:
        job_start = time.time()
        final = _wait_with_progress(bot, chat_id, job.id)
        total_elapsed = int(time.time() - job_start)
        elapsed_str = (f"{total_elapsed // 60}분 {total_elapsed % 60:02d}초"
                       if total_elapsed >= 60 else f"{total_elapsed}초")

        if final and final.status == JobStatus.DONE:
            blog_artifact = next((a for a in final.artifacts if a.kind == "blog_long"), None)
            sent = False
            if blog_artifact:
                from .storage import file_path

                path = file_path(final.id, blog_artifact.filename)
                if os.path.exists(path):
                    if not _claim_send(final.id):
                        # notify_job_done(워커 업로드 경로)에서 이미 전송함 — 중복 방지
                        return
                    try:
                        tag = "딥리서치" if deep_research else ""
                        with open(path, "rb") as f:
                            bot.send_document(
                                chat_id,
                                f,
                                visible_file_name=_result_filename(final.title, tag=tag),
                                caption=(final.title or "블로그")[:1024],
                            )
                        sent = True
                    except Exception:
                        _unclaim_send(final.id)
                        raise
            if sent:
                version_label = "🔬 딥리서치 블로그" if deep_research else "📝 블로그"
                done_msg = f"🎉 완료!  총 소요: {elapsed_str}\n{version_label} HTML 전송 완료"
                if final.chapters:
                    done_msg += f" (챕터 {len(final.chapters)}개)"
                bot.send_message(chat_id, done_msg)
                if getattr(final, "naver_mode", False):
                    _send_naver_files(bot, chat_id, final)
            else:
                bot.send_message(
                    chat_id,
                    "⚠️ 완료됐지만 blog_long.html을 찾지 못했습니다.\n웹앱에서 확인해주세요.",
                )
        elif final and final.status == JobStatus.FAILED:
            friendly = final.message or "처리 실패"
            raw = (final.error or "").strip()
            last_line = raw.splitlines()[-1][:200] if raw else ""
            detail = f"\n🔧 오류: {last_line}" if last_line else ""
            bot.send_message(chat_id, f"❌ 실패: {friendly}{detail}")
            _is_bot_detect = "봇 탐지" in friendly or "로그인" in friendly or "쿠키" in friendly
            if _is_bot_detect:
                if _COOKIES_PATH.exists():
                    bot.send_message(chat_id,
                        "🍪 쿠키가 설정되어 있지만 여전히 차단됐습니다.\n"
                        "YouTube 세션이 만료됐을 수 있습니다.\n"
                        "쿠키를 새로 내보내서 다시 보내주세요.")
                else:
                    bot.send_message(chat_id,
                        "🍪 쿠키를 설정하면 이 오류를 우회할 수 있습니다!\n\n"
                        "「쿠키 설정」이라고 보내면 방법을 안내해드립니다.")
            else:
                bot.send_message(chat_id, "💡 다시 시도하거나 다른 영상 URL을 보내보세요.")
        else:
            bot.send_message(
                chat_id,
                "⏰ 처리 시간 초과 (30분).\n"
                "서버가 바쁘거나 영상이 너무 깁니다. 잠시 후 다시 시도해주세요.",
            )
    except Exception as exc:
        log.exception("telegram post-job notify failed")
        bot.send_message(chat_id, f"알림 실패: {exc}")


_PENDING_LANG_TIMEOUT = 60.0


def _ask_study_lang(bot, chat_id: int, p: "_PendingChoice") -> str | None:
    """언어학습을 고른 뒤 '무슨 언어를 배우나'를 한 번 더 묻고 기다린다.

    자동 판별로는 안 된다: 한국어 강사가 일본어를 가르치는 영상은 자막이 한국어라
    '한국어 학습글'이 나와 버린다. 목표 언어는 사람이 골라야 확실하다.
    """
    p.stage = "lang"
    p.lang = None
    p.event.clear()
    with _pending_lock:
        _pending[chat_id] = p
    menu = "\n".join(f"   {num}️⃣ {name}" for num, name in _STUDY_LANGS)
    bot.send_message(
        chat_id,
        "🌏 어떤 언어를 공부하시나요?\n\n" + menu
        + "\n   ✏️ 그 외에는 언어명을 직접 적어주세요 (예: 프랑스어)\n\n"
        + "👉 번호나 언어명을 답해주세요.\n"
        + f"⏱ {int(_PENDING_LANG_TIMEOUT)}초 안에 답이 없으면 영상에서 자동 판별합니다.",
    )
    answered = p.event.wait(timeout=_PENDING_LANG_TIMEOUT)
    with _pending_lock:
        if _pending.get(chat_id) is p:
            del _pending[chat_id]
    if answered and p.lang:
        bot.send_message(chat_id, f"👍 {p.lang} 학습 자료로 만들어 드릴게요. (원문 + 읽기 + 한국어 뜻)")
        return p.lang
    bot.send_message(chat_id, "⏱ 응답이 없어 영상에서 학습 언어를 자동 판별합니다.")
    return None


def _run_study_inline(bot, loop, chat_id: int, url: str, naver_mode: bool, owner: str) -> None:
    """메시지에 「언어학습」이 같이 왔지만 어떤 언어인지는 안 적힌 경우 — 언어만 물어보고 진행."""
    p = _PendingChoice(url, naver_mode)
    study_lang = _ask_study_lang(bot, chat_id, p)
    _submit_and_deliver(bot, loop, chat_id, url, naver_mode, False, owner,
                        lang_study=True, study_lang=study_lang)


def _run_after_choice(bot, loop, chat_id: int, p: "_PendingChoice", owner: str) -> None:
    """버전 선택 질문을 보낸 뒤 최대 10초 대기 → 결정된 버전으로 작업 실행."""
    answered = p.event.wait(timeout=_PENDING_CHOICE_TIMEOUT)
    with _pending_lock:
        if _pending.get(chat_id) is p:
            del _pending[chat_id]
    deep = (p.choice == "deep")
    study = (p.choice == "study")
    if not answered:
        bot.send_message(chat_id,
            "⏱ 응답이 없어 [1️⃣ 일반 버전]으로 진행합니다.\n"
            "(다음엔 URL 보낸 뒤 「2」=딥리서치, 「3」=언어학습 이라고 답하세요.)")
    else:
        _label = "📚 언어학습" if study else "🔬 딥리서치" if deep else "1️⃣ 일반"
        bot.send_message(chat_id, f"👍 {_label} 버전으로 진행합니다.")
    study_lang = _ask_study_lang(bot, chat_id, p) if study else None
    _submit_and_deliver(bot, loop, chat_id, p.url, p.naver_mode, deep, owner,
                        lang_study=study, study_lang=study_lang)


def run_polling() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN not set; bot disabled")
        return

    global _bot
    bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)
    _bot = bot
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    HELP_TEXT = (
        "안녕하세요! [JINI+US] 유튜브 다운로드 봇입니다. 🚀\n\n"
        "📌 사용법:\n"
        "• 유튜브 URL → 버전 선택 후 블로그 HTML 생성·전송\n"
        "   1️⃣ 일반 버전 — 영상 길이에 맞춘 표준 블로그\n"
        "   2️⃣ 딥리서치 버전 — 웹 검색 배경 조사 + 2~3배 긴 심층 글\n"
        "   3️⃣ 언어학습 버전 — 목표 언어 원문 + 읽기(병음/가나) + 한국어 뜻\n"
        "   (URL 보내면 물어봄. 10초 무응답 시 자동 일반)\n"
        "• \"네이버\" + URL → 🌟 네이버 블로그 최적화 글 + 이미지 별도 전송\n"
        "• \"살아있어?\" → 서버 상태 확인\n"
        "• \"쿠키 설정 / 확인 / 삭제\" → 봇 탐지 우회 쿠키 관리\n"
        "• \"키 설정 / 확인 / 삭제\" → 딥리서치용 Gemini API 키 관리\n"
        "• \"도움\" → 이 안내 다시 보기\n\n"
        "🔬 딥리서치 사용법:\n"
        "  URL 보낸 뒤 「2」 또는 「딥리서치」라고 답하거나,\n"
        "  URL과 함께 「딥리서치 https://youtu.be/...」로 보내세요.\n\n"
        "🌟 네이버 블로그: URL과 함께 「네이버」 포함해서 전송\n"
        "  (네이버 + 딥리서치 동시 지정도 가능)\n\n"
        "🍪 봇 탐지 오류 시 \"쿠키 설정\", 🔑 딥리서치 한도 걱정되면 \"키 설정\"."
    )

    def _status_text() -> str:
        up = int(time.time() - START_TS)
        h, m = up // 3600, (up % 3600) // 60
        try:
            all_jobs = registry.list()
            active = sum(1 for j in all_jobs if j.status not in (JobStatus.DONE, JobStatus.FAILED))
            pending = sum(1 for j in all_jobs if j.status == JobStatus.PENDING)
        except Exception:
            active = 0
            pending = 0
        mode = "Windows PC 위임 모드" if config.REMOTE_DISPATCH else "서버 직접 처리"
        lines = [
            "✅ 서버 정상 작동 중입니다.",
            f"• 모드: {mode}",
            "• 다운로드: 가능",
            f"• 진행 중 작업: {active}개" + (f" (대기: {pending}개)" if pending else ""),
            f"• 가동 시간: {h}시간 {m}분",
            "",
            "유튜브 URL을 보내시면 바로 받아드립니다.",
        ]
        return "\n".join(lines)

    @bot.message_handler(commands=["start", "help"])
    def _welcome(message):
        bot.reply_to(message, HELP_TEXT)

    @bot.message_handler(content_types=["document"])
    def _handle_document(message):
        """Accept .txt cookies file upload."""
        doc = message.document
        if not doc:
            return
        fname = doc.file_name or ""
        if not fname.lower().endswith(".txt"):
            bot.reply_to(message,
                "❌ .txt 형식의 파일만 받을 수 있습니다.\n"
                "\"쿠키 설정\"을 입력하면 내보내기 방법을 안내해드립니다."
            )
            return
        try:
            file_info = bot.get_file(doc.file_id)
            raw = bot.download_file(file_info.file_path)
            content = raw.decode("utf-8", errors="replace")
            if "youtube.com" not in content:
                bot.reply_to(message,
                    "❌ YouTube 쿠키가 포함되지 않은 파일입니다.\n"
                    "youtube.com 에서 로그인한 상태로 내보낸 쿠키 파일을 보내주세요."
                )
                return
            _COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)
            _COOKIES_PATH.write_bytes(raw)
            bot.reply_to(message,
                "✅ 유튜브 쿠키 저장 완료!\n\n"
                "이제 봇 탐지 오류 없이 다운로드할 수 있습니다.\n"
                "YouTube URL을 다시 보내 시도해보세요."
            )
            log.info("youtube cookies saved to %s (%d bytes)", _COOKIES_PATH, len(raw))
        except Exception as exc:
            log.exception("cookie upload failed")
            bot.reply_to(message, f"❌ 쿠키 저장 실패: {exc}")

    @bot.message_handler(func=lambda m: True)
    def _handle(message):
        text = (message.text or "").strip()
        chat_id = message.chat.id
        owner = f"tg:{message.from_user.id}" if message.from_user else "tg:unknown"

        # 0) Gemini API 키 붙여넣기 감지 → 저장(딥리서치용). URL이 없을 때만.
        key_m = _GEMINI_KEY_RE.search(text)
        if key_m and "http" not in text.lower():
            key = key_m.group(0)
            try:
                _GEMINI_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
                _GEMINI_KEY_PATH.write_text(key, encoding="utf-8")
                bot.reply_to(message,
                    "✅ Gemini API 키 저장 완료!\n"
                    "이제 딥리서치(2번) 버전은 이 키로 처리됩니다.\n\n"
                    "🔒 보안을 위해 방금 키를 보낸 메시지는 삭제해주세요.")
                log.info("gemini api key saved (%d chars)", len(key))
            except Exception as exc:
                log.exception("gemini key save failed")
                bot.reply_to(message, f"❌ 키 저장 실패: {exc}")
            return

        # URL 추출 (그냥 붙여넣거나 "이거 받아줘 <url>" 형태 모두 허용)
        m_url = re.search(r"https?://\S+", text)

        # 1) 버전 선택 대기 중이면, 짧은 응답을 선택으로 해석(URL이 아닐 때)
        with _pending_lock:
            _p = _pending.get(chat_id)
            has_pending, _stage = (_p is not None), (_p.stage if _p else "")
        # 1-a) '무슨 언어를 배우나' 대기 중이면 언어 답변으로만 해석한다.
        #      ('3' 같은 숫자가 버전 선택으로 다시 먹히면 안 되므로 버전 매처보다 먼저.)
        if has_pending and _stage == "lang" and not m_url:
            _lang = _parse_study_lang(text)
            if _lang:
                _resolve_pending_lang(chat_id, _lang)
                return
            bot.reply_to(message, "🌏 언어를 못 알아들었어요. 번호(1~5)나 '일본어'처럼 언어명을 적어주세요.")
            return
        if has_pending and not m_url:
            if _match_study(text):
                _resolve_pending(chat_id, "study")
                return
            if _match_deep(text):
                _resolve_pending(chat_id, "deep")
                return
            if _match_normal(text):
                _resolve_pending(chat_id, "normal")
                return
            # 인식 안 되는 입력이면 아래 명령 라우팅으로 자연스럽게 넘어감

        if not m_url:
            # 자연어 명령 라우팅
            if re.search(r"재시작|다시\s*시작|리부트|리스타트|restart|재기동", text, re.I):
                bot.reply_to(
                    message,
                    "♻️ 원격 자동 재시작은 지원되지 않습니다.\n"
                    "Windows PC에서 start-backend.bat을 다시 실행해 주세요.",
                )
                return
            if re.search(r"쿠키\s*설정|쿠키\s*업로드|cookie.*set|cookies.*upload", text, re.I):
                bot.reply_to(message, _COOKIE_GUIDE)
                return
            if re.search(r"쿠키\s*확인|쿠키\s*상태|cookie.*check|cookie.*status", text, re.I):
                if _COOKIES_PATH.exists():
                    size = _COOKIES_PATH.stat().st_size
                    bot.reply_to(message,
                        f"✅ 쿠키 설정됨 ({size:,} bytes)\n"
                        f"경로: {_COOKIES_PATH}\n\n"
                        "쿠키가 만료되면 다시 내보내서 보내주세요."
                    )
                else:
                    bot.reply_to(message,
                        "❌ 저장된 쿠키 없음\n\n"
                        "\"쿠키 설정\"을 입력하면 방법을 안내해드립니다."
                    )
                return
            if re.search(r"쿠키\s*삭제|쿠키\s*제거|cookie.*delete|cookie.*remove", text, re.I):
                if _COOKIES_PATH.exists():
                    _COOKIES_PATH.unlink()
                    bot.reply_to(message, "🗑 저장된 쿠키를 삭제했습니다.")
                else:
                    bot.reply_to(message, "저장된 쿠키가 없습니다.")
                return
            # 딥리서치용 Gemini API 키 관리
            if re.search(r"키\s*확인|api\s*확인|제미나이\s*확인|gemini.*status|key.*check", text, re.I):
                stored = get_stored_gemini_key()
                if stored:
                    bot.reply_to(message,
                        f"✅ Gemini API 키 등록됨 (…{stored[-6:]})\n"
                        "딥리서치는 이 키로 처리됩니다.\n\n"
                        "「키 삭제」로 제거할 수 있습니다.")
                else:
                    bot.reply_to(message,
                        "❌ 등록된 Gemini API 키 없음\n"
                        "딥리서치는 서버 기본 키로 동작합니다.\n\n"
                        "「키 설정」으로 등록 방법을 안내받으세요.")
                return
            if re.search(r"키\s*삭제|api\s*삭제|제미나이\s*삭제|gemini.*delete|key.*delete", text, re.I):
                if _GEMINI_KEY_PATH.exists():
                    _GEMINI_KEY_PATH.unlink()
                    bot.reply_to(message, "🗑 등록된 Gemini API 키를 삭제했습니다.")
                else:
                    bot.reply_to(message, "등록된 Gemini API 키가 없습니다.")
                return
            if re.search(r"키\s*설정|api\s*설정|api\s*키|제미나이\s*키|gemini.*key|key.*set", text, re.I):
                bot.reply_to(message, _GEMINI_KEY_GUIDE)
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
                "또는 \"살아있어?\" · \"쿠키 설정\" · \"도움\" 이라고 하셔도 됩니다.",
            )
            return

        url = m_url.group(0)
        # "네이버" 키워드 감지 → 네이버 블로그 최적화 모드
        naver_mode = bool(re.search(r"네이버|naver", text, re.I))

        # 같은 메시지에 버전이 '명시적 키워드'로 지정돼 있으면 질문 없이 바로 진행.
        # (문장 속 '2개' 같은 숫자를 딥리서치로 오인하지 않도록 인라인은 키워드만 인식)
        text_wo_url = text.replace(url, " ")
        inline_study = bool(re.search(r"언어\s*(공부|학습)|어학|study|language", text_wo_url, re.I))
        inline_deep = bool(re.search(r"딥\s*리서치|deep|심층|리서치", text_wo_url, re.I))
        inline_normal = bool(re.search(r"일반|기본|normal|standard", text_wo_url, re.I))
        if inline_study or inline_deep or inline_normal:
            study = inline_study
            deep = inline_deep and not inline_normal and not inline_study
            # 「일본어 학습」처럼 목표 언어까지 같이 적었으면 되묻지 않는다.
            inline_lang = _parse_study_lang(text_wo_url) if study else None
            if study and not inline_lang:
                bot.reply_to(message, "⏳ 📚 언어학습 버전으로 진행합니다...")
                threading.Thread(
                    target=_run_study_inline,
                    args=(bot, loop, chat_id, url, naver_mode, owner),
                    daemon=True, name=f"study-{chat_id}",
                ).start()
                return
            _label = ("📚 언어학습" + (f"({inline_lang})" if inline_lang else "")) if study                 else "🔬 딥리서치" if deep else "📝 일반"
            bot.reply_to(message, f"⏳ {_label} 버전으로 바로 진행합니다...")
            threading.Thread(
                target=_submit_and_deliver,
                args=(bot, loop, chat_id, url, naver_mode, deep, owner),
                kwargs={"lang_study": study, "study_lang": inline_lang},
                daemon=True, name=f"job-{chat_id}",
            ).start()
            return

        # 버전 선택 질문 + 10초 대기 (이전 대기가 있으면 일반으로 자동 확정하고 교체)
        _resolve_pending(chat_id, "normal")
        p = _PendingChoice(url, naver_mode)
        with _pending_lock:
            _pending[chat_id] = p
        naver_note = " (🌟 네이버용 포함)" if naver_mode else ""
        bot.reply_to(
            message,
            f"❓ 어떤 버전으로 만들까요?{naver_note}\n\n"
            "1️⃣ 일반 버전 — 영상 길이에 맞춘 표준 블로그 (빠름)\n"
            "2️⃣ 딥리서치 버전 — 웹 검색 배경 조사 + 2~3배 긴 심층 글\n"
            "3️⃣ 언어학습 버전 — 원문 + 읽기(병음/가나) + 한국어 3단 학습카드\n\n"
            "👉 「2」=딥리서치, 「3」=언어학습,\n"
            "   「1」 또는 그냥 두시면 일반으로 진행합니다.\n"
            f"⏱ {int(_PENDING_CHOICE_TIMEOUT)}초 안에 답이 없으면 자동으로 [일반 버전]으로 시작합니다.",
        )
        threading.Thread(
            target=_run_after_choice,
            args=(bot, loop, chat_id, p, owner),
            daemon=True, name=f"choice-{chat_id}",
        ).start()

    # spin a side loop so we can submit to the asyncio registry from sync handlers
    def _bg_loop():
        loop.run_forever()

    threading.Thread(target=_bg_loop, daemon=True, name="tg-asyncio").start()

    # 자가복구 폴링 루프: infinity_polling은 WiFi가 끊겼다 붙으면 죽은 소켓에 물려
    # 멈추는 일이 있다. 바운드 타임아웃 + 예외 시 재시도로 네트워크 복구 시 수초 내
    # 자동 재개되게 직접 제어한다. 매 성공마다 heartbeat 파일을 갱신(감시 에이전트용).
    heartbeat = "/tmp/ytdlp-tg-heartbeat"

    def _hb():
        try:
            with open(heartbeat, "w") as fh:
                fh.write(str(int(time.time())))
        except Exception:
            pass

    # (재)시작 시 밀린 업데이트는 건너뛴다.
    try:
        pending = bot.get_updates(offset=-1, timeout=2, long_polling_timeout=1)
        offset = (pending[-1].update_id + 1) if pending else None
    except Exception:
        offset = None

    _hb()
    log.info("telegram bot polling started (resilient loop, heartbeat=%s)", heartbeat)

    fail_streak = 0
    while True:
        try:
            updates = bot.get_updates(offset=offset, timeout=30, long_polling_timeout=25)
            _hb()
            fail_streak = 0
            for u in updates:
                offset = u.update_id + 1
                try:
                    bot.process_new_updates([u])
                except Exception:
                    log.exception("telegram update 처리 실패")
        except Exception as exc:
            fail_streak += 1
            if fail_streak <= 3 or fail_streak % 10 == 0:
                log.warning("telegram 폴링 일시 오류 #%d (네트워크 끊김?) 재시도: %s",
                            fail_streak, str(exc)[:160])
            time.sleep(3)


def _wait_until_done(job_id: str, timeout: int = 1800):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = registry.get(job_id)
        if job and job.status in (JobStatus.DONE, JobStatus.FAILED):
            return job
        time.sleep(2)
    return registry.get(job_id)


def _wait_with_progress(bot, chat_id: int, job_id: str, timeout: int = 1800):
    """Poll job until done, sending Telegram progress updates at each stage."""
    _TERMINAL = (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED)

    _STAGE = {
        JobStatus.PENDING:     ("⏳", "대기 중",           ""),
        JobStatus.DOWNLOADING: ("⬇️", "영상 다운로드 중",   "약 1~3분"),
        JobStatus.TRANSCRIBING:("📝", "자막 처리 중",       "약 30초~2분"),
        JobStatus.GENERATING:  ("🤖", "AI 블로그 작성 중",  "약 1~3분"),
    }

    def _bar(pct: int, w: int = 10) -> str:
        f = int(w * pct / 100)
        return "█" * f + "░" * (w - f)

    def _elapsed(start: float) -> str:
        e = int(time.time() - start)
        return f"{e // 60}분 {e % 60:02d}초" if e >= 60 else f"{e}초"

    def _send(text: str) -> None:
        try:
            bot.send_message(chat_id, text)
        except Exception as exc:
            log.warning("progress send failed: %s", exc)

    start = time.time()
    deadline = start + timeout
    last_status = None
    last_job_msg = None
    last_notif_time = start
    title_announced = False

    while time.time() < deadline:
        job = registry.get(job_id)
        if not job:
            _send("❌ 작업을 찾을 수 없습니다.")
            return None

        if job.status in _TERMINAL:
            return job

        now = time.time()
        pct = int(job.progress * 100)

        # 영상 제목이 확인되면 한 번만 알림
        if job.title and not title_announced:
            _send(f"📺 영상 확인됨:\n{job.title[:120]}")
            title_announced = True

        # 단계 전환 시 즉시 알림
        if job.status != last_status:
            emoji, label, eta = _STAGE.get(job.status, ("🔄", "처리 중", ""))
            lines = [f"{emoji} {label}"]
            if eta:
                lines.append(f"⏱ 예상 소요: {eta}")
            if pct > 0:
                lines.append(f"[{_bar(pct)}] {pct}%")
            if job.message and job.message != last_job_msg:
                lines.append(f"• {job.message}")
            lines.append(f"경과: {_elapsed(start)}")
            _send("\n".join(lines))
            last_status = job.status
            last_job_msg = job.message
            last_notif_time = now

        # 세부 메시지 변경 시 (예: Whisper 폴백) — 25초 쿨다운
        elif job.message and job.message != last_job_msg and now - last_notif_time >= 25:
            _send(f"💬 {job.message}")
            last_job_msg = job.message
            last_notif_time = now

        # 2분마다 생존 신호
        elif now - last_notif_time >= 120:
            emoji, label, _ = _STAGE.get(job.status, ("🔄", "처리 중", ""))
            _send(
                f"{emoji} 아직 열심히 처리 중입니다!\n"
                f"• 현재 단계: {label}\n"
                f"• [{_bar(pct)}] {pct}%\n"
                f"• 경과 시간: {_elapsed(start)}\n"
                f"조금만 더 기다려주세요 😊"
            )
            last_notif_time = now

        time.sleep(3)

    return registry.get(job_id)

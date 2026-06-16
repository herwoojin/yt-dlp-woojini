"""Runtime configuration loaded from environment variables and a JSON settings file.

The settings file allows the download directory to be changed at runtime
via the web UI without restarting the server.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock
from typing import Any

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
SETTINGS_FILE = BASE_DIR / "runtime_settings.json"
_LOCK = Lock()

DEFAULT_DOWNLOAD_DIR = str(Path.home() / "yt-dlp-downloads")


def _load_settings() -> dict[str, Any]:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_settings(data: dict[str, Any]) -> None:
    SETTINGS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_download_dir() -> Path:
    with _LOCK:
        data = _load_settings()
    raw = data.get("download_dir") or os.getenv("DOWNLOAD_DIR") or DEFAULT_DOWNLOAD_DIR
    path = Path(os.path.expanduser(raw)).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def set_download_dir(new_path: str) -> Path:
    resolved = Path(os.path.expanduser(new_path)).resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        data = _load_settings()
        data["download_dir"] = str(resolved)
        _save_settings(data)
    return resolved


# --- non-mutable env config -------------------------------------------------

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DEFAULT_GEMINI_MODEL = os.getenv("DEFAULT_GEMINI_MODEL", "gemini-2.5-flash")
PRO_GEMINI_MODEL = os.getenv("PRO_GEMINI_MODEL", "gemini-2.5-pro")
# Gemini 호출당 타임아웃(초). 초과 시 예외 → 작업이 60%에서 무한 대기하지 않음.
GEMINI_TIMEOUT_SEC = int(os.getenv("GEMINI_TIMEOUT_SEC", "120"))
# Gemini 429(쿼터/RPM)·5xx 일시 오류 시 백오프 재시도. 무료 등급 분당 한도 대응.
GEMINI_MAX_RETRIES = int(os.getenv("GEMINI_MAX_RETRIES", "4"))
GEMINI_RETRY_BASE_SEC = int(os.getenv("GEMINI_RETRY_BASE_SEC", "15"))

# 디스크 자동 정리: 사용률이 HIGH% 이상이면 영상 다운로드 전에 오래된 작업부터
# TARGET% 아래까지 삭제한다(최근 KEEP개와 진행 중 작업은 항상 보존).
DISK_HIGH_PERCENT = float(os.getenv("DISK_HIGH_PERCENT", "80"))
DISK_TARGET_PERCENT = float(os.getenv("DISK_TARGET_PERCENT", "55"))
DISK_KEEP_RECENT = int(os.getenv("DISK_KEEP_RECENT", "5"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "true").lower() == "true"

# --- fly.dev 릴레이(맥 워커) 구조 ---
# 회사 보안(Symantec)이 텔레그램을 막고, 회사망/VPN이 인바운드 터널을 깨므로,
# fly.dev를 공개 창구로 두고 맥은 "아웃바운드로만" fly.dev에서 작업을 가져가 처리한다.
#   - fly.dev:  REMOTE_DISPATCH=true → 로컬에서 다운로드 처리 안 함(데이터센터 IP 봇차단).
#               제출된 작업은 PENDING으로 두고 /api/worker/* 로 맥에 넘긴다.
#   - 맥:       REMOTE_WORKER_URL=https://ytdlp-25y.fly.dev → fly.dev에서 작업을 폴링해
#               가정용 IP로 다운로드+블로그 생성 후 blog_long.html을 업로드.
WORKER_TOKEN = os.getenv("WORKER_TOKEN", "")
REMOTE_DISPATCH = os.getenv("REMOTE_DISPATCH", "false").lower() == "true"
REMOTE_WORKER_URL = os.getenv("REMOTE_WORKER_URL", "").rstrip("/")

FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "")
FIREBASE_SERVICE_ACCOUNT_PATH = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", "")
ALLOW_INSECURE_AUTH = os.getenv("ALLOW_INSECURE_AUTH", "false").lower() == "true"

ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:8000,http://127.0.0.1:8000,"
        "https://25y.netlify.app",
    ).split(",")
    if o.strip()
]

# Allow any Netlify deploy (including PR previews) and any Cloudflare quick tunnel,
# so changing the tunnel URL or the Netlify site name doesn't break CORS.
ALLOWED_ORIGIN_REGEX = os.getenv(
    "ALLOWED_ORIGIN_REGEX",
    r"https://([a-z0-9-]+\.)*(netlify\.app|trycloudflare\.com)",
)

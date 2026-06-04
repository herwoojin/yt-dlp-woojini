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

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "true").lower() == "true"

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

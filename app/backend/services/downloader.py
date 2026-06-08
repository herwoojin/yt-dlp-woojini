"""yt-dlp wrapper. Two-pass strategy:

1) Download the video itself with conservative retries.
2) Best-effort subtitle pass (ko, en only). Failures here do NOT abort the job
   - YouTube frequently 429s on subtitle endpoints if many languages are
   requested.

If a YT_DLP_COOKIES_FILE env var is set, it is forwarded to yt-dlp - useful
when YouTube starts demanding sign-in for bot-flagged IPs.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yt_dlp

log = logging.getLogger(__name__)

SUB_LANGS = ["ko", "en"]
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"


def _base_opts() -> dict[str, Any]:
    opts: dict[str, Any] = {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,
        "http_headers": {"User-Agent": UA},
    }
    # 쿠키가 있으면 yt-dlp 기본 클라이언트(web 등)가 잘 동작하므로 player_client는 강제하지 않는다.
    # 필요 시 환경변수 YT_DLP_PLAYER_CLIENTS(쉼표구분)로만 지정.
    player_clients = [c.strip() for c in os.getenv("YT_DLP_PLAYER_CLIENTS", "").split(",") if c.strip()]
    if player_clients:
        opts["extractor_args"] = {"youtube": {"player_client": player_clients}}
    cookies = os.getenv("YT_DLP_COOKIES_FILE")
    if cookies and os.path.exists(cookies):
        opts["cookiefile"] = cookies
    return opts


def _download_video(url: str, target_dir: Path, video_format: str) -> dict[str, Any]:
    opts = {
        **_base_opts(),
        "format": video_format,
        "outtmpl": str(target_dir / "video.%(ext)s"),
        "merge_output_format": "mp4",
        "writeinfojson": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=True)


def _download_subtitles(url: str, target_dir: Path) -> None:
    """Best-effort subtitle download. Caller catches exceptions."""
    opts = {
        **_base_opts(),
        "skip_download": True,
        "outtmpl": str(target_dir / "video.%(ext)s"),
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": SUB_LANGS,
        "subtitlesformat": "vtt",
        "sleep_interval_subtitles": 2,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(url, download=True)


def download(url: str, target_dir: Path, video_format: str = "best[ext=mp4]/best") -> dict[str, Any]:
    target_dir.mkdir(parents=True, exist_ok=True)

    info = _download_video(url, target_dir, video_format)

    subtitle_error: str | None = None
    try:
        _download_subtitles(url, target_dir)
    except Exception as exc:
        subtitle_error = str(exc)
        log.warning("subtitle pass failed (non-fatal): %s", exc)

    files: dict[str, str] = {}
    for p in target_dir.iterdir():
        name = p.name
        if name.startswith("video.") and p.suffix in {".mp4", ".webm", ".mkv", ".m4a"}:
            files["video"] = str(p)
        elif name.endswith(".vtt") or name.endswith(".srt"):
            current = files.get("subtitle")
            # prefer ko > en
            if ".ko." in name or current is None:
                files["subtitle"] = str(p)
            elif ".en." in name and ".ko." not in (current or ""):
                files["subtitle"] = str(p)
        elif name.endswith(".info.json"):
            files["info_json"] = str(p)

    return {
        "title": info.get("title"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader"),
        "id": info.get("id"),
        "files": files,
        "subtitle_error": subtitle_error,
    }

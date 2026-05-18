"""Build a compact plain-text transcript from yt-dlp's VTT/SRT subtitle file.

The output is the smallest reasonable TXT representation: one paragraph per
chunk, no timestamps, deduplicated consecutive lines, normalized whitespace.
A timestamped variant is written alongside as transcript_timed.txt for
Gemini chapter generation.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_VTT_TIME = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}")
_SRT_TIME = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}")
_TAG = re.compile(r"<[^>]+>")
_HMS = re.compile(r"^(\d{2}):(\d{2}):(\d{2})")


def _parse_subtitle(path: Path) -> list[tuple[str, str]]:
    """Return list of (HH:MM:SS, text) pairs."""
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    pairs: list[tuple[str, str]] = []
    current_ts: str | None = None
    current_text: list[str] = []

    def flush():
        nonlocal current_text, current_ts
        if current_ts and current_text:
            text = " ".join(current_text).strip()
            text = _TAG.sub("", text)
            if text:
                pairs.append((current_ts, text))
        current_text = []

    for line in lines:
        line = line.strip()
        if not line or line.upper().startswith("WEBVTT") or line.isdigit():
            flush()
            continue
        m = _VTT_TIME.match(line) or _SRT_TIME.match(line)
        if m:
            flush()
            current_ts = line[:8]  # HH:MM:SS
            continue
        if current_ts:
            current_text.append(line)
    flush()

    # dedupe consecutive identical lines (YouTube auto-captions repeat heavily)
    out: list[tuple[str, str]] = []
    for ts, text in pairs:
        if out and out[-1][1] == text:
            continue
        out.append((ts, text))
    return out


def build_transcript_txt(job_dir: Path, info: dict[str, Any]) -> str:
    sub_path_str = info.get("files", {}).get("subtitle")
    if not sub_path_str:
        plain = "[자막을 찾을 수 없음 - 영상에 자막이 제공되지 않습니다.]"
        (job_dir / "transcript.txt").write_text(plain, encoding="utf-8")
        (job_dir / "transcript_timed.txt").write_text(plain, encoding="utf-8")
        return plain

    sub_path = Path(sub_path_str)
    pairs = _parse_subtitle(sub_path)
    if not pairs:
        plain = "[자막 파싱 실패]"
        (job_dir / "transcript.txt").write_text(plain, encoding="utf-8")
        (job_dir / "transcript_timed.txt").write_text(plain, encoding="utf-8")
        return plain

    plain_text = " ".join(text for _, text in pairs)
    plain_text = re.sub(r"\s+", " ", plain_text).strip()
    (job_dir / "transcript.txt").write_text(plain_text, encoding="utf-8")

    timed_lines = [f"[{ts}] {text}" for ts, text in pairs]
    (job_dir / "transcript_timed.txt").write_text("\n".join(timed_lines), encoding="utf-8")

    return plain_text

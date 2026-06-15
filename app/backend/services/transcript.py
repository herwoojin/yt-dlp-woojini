"""Build a compact plain-text transcript from yt-dlp's VTT/SRT subtitle file.

The output is the smallest reasonable TXT representation: one paragraph per
chunk, no timestamps, deduplicated consecutive lines, normalized whitespace.
A timestamped variant is written alongside as transcript_timed.txt for
Gemini chapter generation.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# M4(Apple Silicon)에서 GPU 가속 받아쓰기. 첫 호출 시 모델을 1회 다운로드한다.
WHISPER_MODEL = os.getenv("WHISPER_MLX_MODEL", "mlx-community/whisper-large-v3-turbo")

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


def _sec_to_vtt(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def transcribe_to_vtt(video_path: Path, job_dir: Path) -> Path | None:
    """YouTube 자막을 못 받았을 때(429/자막없음) 영상 음성을 mlx-whisper로
    직접 받아써서 VTT 파일을 만든다. 성공하면 VTT 경로, 실패하면 None.
    이 VTT를 info['files']['subtitle']에 넣으면 기존 파이프라인이 그대로 동작한다."""
    try:
        import mlx_whisper
    except Exception as exc:  # noqa: BLE001
        log.warning("mlx_whisper import 실패 (받아쓰기 폴백 불가): %s", exc)
        return None

    try:
        result = mlx_whisper.transcribe(
            str(video_path),
            path_or_hf_repo=WHISPER_MODEL,
            word_timestamps=False,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("whisper 받아쓰기 실패: %s", exc)
        return None

    segments = result.get("segments") or []
    if not segments:
        log.warning("whisper: 세그먼트 없음")
        return None

    lines = ["WEBVTT", ""]
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"{_sec_to_vtt(seg.get('start', 0.0))} --> {_sec_to_vtt(seg.get('end', 0.0))}")
        lines.append(text)
        lines.append("")

    vtt_path = Path(job_dir) / "whisper.ko.vtt"
    vtt_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("whisper 받아쓰기 완료: %d 세그먼트 → %s", len(segments), vtt_path.name)
    return vtt_path


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
    # 문장이 끝나는 부호(. ! ?) 뒤에 줄바꿈(엔터 2번)을 추가하여 가독성 개선
    plain_text = re.sub(r"([.!?])\s+", r"\1\n\n", plain_text)
    (job_dir / "transcript.txt").write_text(plain_text, encoding="utf-8")

    timed_lines = [f"[{ts}] {text}" for ts, text in pairs]
    (job_dir / "transcript_timed.txt").write_text("\n".join(timed_lines), encoding="utf-8")

    return plain_text

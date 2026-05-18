"""Gemini calls that produce chapters, short summary, email-HTML, and blog-HTML.

Uses google-genai (the unified SDK). Each function returns plain Python data
ready to be persisted by the job runner.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from google import genai

from .. import config

log = logging.getLogger(__name__)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY 미설정 - .env 확인")
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _model(quality: str) -> str:
    return config.PRO_GEMINI_MODEL if quality == "pro" else config.DEFAULT_GEMINI_MODEL


def _call(prompt: str, quality: str) -> str:
    client = _get_client()
    resp = client.models.generate_content(model=_model(quality), contents=prompt)
    return (resp.text or "").strip()


def _read_timed(transcript_text: str, max_chars: int = 60_000) -> str:
    """Caller can pass the timed transcript via file path; this helper
    just truncates to keep token usage in check."""
    if len(transcript_text) <= max_chars:
        return transcript_text
    head = transcript_text[: max_chars // 2]
    tail = transcript_text[-max_chars // 2 :]
    return f"{head}\n\n[... 중략 ...]\n\n{tail}"


def _extract_json(text: str) -> Any:
    """Strip ```json fences and parse. Falls back to regex extraction."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\[[\s\S]*\]|\{[\s\S]*\}", text)
        if m:
            return json.loads(m.group(0))
        raise


def generate_chapters(timed_transcript: str, title: str, quality: str) -> list[dict]:
    prompt = f"""다음은 유튜브 영상 "{title}"의 시간 인덱스 자막입니다.
영상의 흐름과 문맥을 이해해서 시계열 순으로 주요 섹션 목차를 만들어주세요.

요구사항:
- 8~15개 사이의 주요 챕터
- 각 챕터에 시작 시각(HH:MM:SS), 제목, 한 줄 요약을 포함
- 반드시 아래 JSON 형식만 반환 (코드펜스 금지, 설명 금지)

[{{"time": "00:00:00", "title": "도입", "summary": "..."}}, ...]

자막:
{_read_timed(timed_transcript)}
"""
    raw = _call(prompt, quality)
    try:
        data = _extract_json(raw)
        if isinstance(data, list):
            return data
    except Exception as exc:
        log.warning("chapter parse fallback: %s", exc)
    return [{"time": "00:00:00", "title": title or "전체 영상", "summary": raw[:200]}]


def generate_short_summary_html(plain_text: str, title: str, quality: str) -> str:
    prompt = f"""아래 유튜브 영상 "{title}"의 자막을 읽고 한국어로 짧고 명확하게 요약해주세요.

요구사항:
- 3~5문장의 핵심 요약
- 결과는 단일 HTML 조각만 반환 (코드펜스 금지, 설명 금지)
- 인라인 스타일 사용, 외부 CSS/JS 사용 금지
- 구조: <div style="..."> 안에 제목 1개 + 요약 본문

자막:
{_read_timed(plain_text, max_chars=40_000)}
"""
    return _strip_fence(_call(prompt, quality))


def generate_email_html(plain_text: str, title: str, chapters: list[dict], quality: str) -> str:
    chapters_md = "\n".join(f"- [{c.get('time','')}] {c.get('title','')}" for c in chapters)
    prompt = f"""아래 유튜브 영상 "{title}"을 이메일 본문에 붙여넣기 좋은 HTML로 만들어주세요.

요구사항:
- 가독성 우선: 적절한 단락, 굵게 표시, 핵심 포인트 강조
- 모든 스타일은 인라인 (이메일 클라이언트가 외부 CSS 차단)
- 시스템 폰트 스택, 14~16px, 줄간격 1.6
- 구조: 제목 → 한줄 요약 → 챕터 목록 → 본문 요약(3~5단락) → 마무리 한 줄
- 결과는 HTML 조각만 (코드펜스/설명/마크다운 금지, <html>/<body> 태그도 불필요)
- 너비 제한 div: max-width:640px

목차:
{chapters_md}

자막 발췌:
{_read_timed(plain_text, max_chars=30_000)}
"""
    return _strip_fence(_call(prompt, quality))


def generate_blog_html(plain_text: str, title: str, chapters: list[dict], quality: str) -> str:
    chapters_md = "\n".join(f"- [{c.get('time','')}] {c.get('title','')} — {c.get('summary','')}" for c in chapters)
    prompt = f"""아래 유튜브 영상 "{title}"을 블로그/카페에 올릴 한국어 장문 글로 작성해주세요.

요구사항:
- 도입(독자 hook) → 본문(챕터 기반 섹션 6~10개) → 결론/CTA
- 각 섹션마다 소제목(h2), 본문 단락 2~4개, 필요시 불릿
- 인라인 스타일, 가독성 좋은 폰트/크기/간격
- 이미지 자리에는 <figure style="..."><div>📸 이미지 자리</div><figcaption>...</figcaption></figure>
- 결과는 HTML 조각만 (코드펜스/설명 금지, <html>/<body> 불필요)
- 글자수 1500~3000자

목차:
{chapters_md}

자막 발췌:
{_read_timed(plain_text, max_chars=50_000)}
"""
    return _strip_fence(_call(prompt, quality))


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:html)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def generate_all(job_dir: Path, title: str, quality: str) -> dict[str, Any]:
    """Reads plain + timed transcripts from job_dir and produces all four outputs."""
    plain_path = job_dir / "transcript.txt"
    timed_path = job_dir / "transcript_timed.txt"
    plain_text = plain_path.read_text(encoding="utf-8") if plain_path.exists() else ""
    timed_text = timed_path.read_text(encoding="utf-8") if timed_path.exists() else plain_text

    chapters = generate_chapters(timed_text, title, quality)
    summary_short = generate_short_summary_html(plain_text, title, quality)
    email_html = generate_email_html(plain_text, title, chapters, quality)
    blog_html = generate_blog_html(plain_text, title, chapters, quality)
    return {
        "chapters": chapters,
        "summary_short_html": summary_short,
        "email_html": email_html,
        "blog_html": blog_html,
    }

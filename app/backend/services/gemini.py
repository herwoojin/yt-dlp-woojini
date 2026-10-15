"""Gemini calls that produce chapters, short summary, email-HTML, and blog-HTML.

Uses google-genai (the unified SDK). Each function returns plain Python data
ready to be persisted by the job runner.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from .. import config

log = logging.getLogger(__name__)

_client: genai.Client | None = None


def _http_options() -> types.HttpOptions:
    # 타임아웃은 밀리초 단위. 초과 시 SDK가 예외를 던져 무한 대기를 방지한다.
    return types.HttpOptions(timeout=config.GEMINI_TIMEOUT_SEC * 1000)


def _get_client(api_key: str | None = None) -> genai.Client:
    """Return a genai Client. If *api_key* is given, create a throwaway
    client for that key (per-request). Otherwise fall back to the
    server-wide key from config / .env."""
    if api_key:
        return genai.Client(api_key=api_key, http_options=_http_options())
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY 미설정 - .env 확인 또는 프론트엔드에서 API 키를 입력하세요")
        _client = genai.Client(api_key=config.GEMINI_API_KEY, http_options=_http_options())
    return _client


def _model(quality: str) -> str:
    return config.PRO_GEMINI_MODEL if quality == "pro" else config.DEFAULT_GEMINI_MODEL


def _is_transient(err: Exception) -> bool:
    m = str(err).lower()
    # 일일 한도(RPD)·결제 크레딧 소진은 재시도해도 소용없음 → 빠르게 포기
    if any(s in m for s in ("per day", "perday", "/day", "daily limit", "requests per day",
                            "prepay", "credit", "billing")):
        return False
    return any(s in m for s in (
        "429", "quota", "rate", "resource_exhausted",
        "503", "overloaded", "unavailable", "500", "internal",
    ))


def _is_quota_like(err: Exception) -> bool:
    """쿼터/한도/크레딧 소진 계열 오류인지(폴백 대상)."""
    m = str(err).lower()
    return any(s in m for s in (
        "429", "quota", "resource_exhausted", "rate",
        "prepay", "credit", "billing", "per day", "daily",
    ))


def _gen_config(use_search: bool = False,
                max_output_tokens: int | None = None) -> types.GenerateContentConfig:
    """공통 생성 설정.
    - max_output_tokens를 크게 잡아 긴 글이 중간에 잘리지 않게 한다.
    - thinking(추론) 예산을 제한해 추론이 출력 토큰을 잠식하지 않게 한다(빈 응답/잘림 방지).
    - use_search=True면 Google 검색 그라운딩을 켠다(딥리서치 전용).
    """
    cfg = types.GenerateContentConfig(
        max_output_tokens=max_output_tokens or config.GEMINI_MAX_OUTPUT_TOKENS,
        thinking_config=types.ThinkingConfig(thinking_budget=config.GEMINI_THINKING_BUDGET),
    )
    if use_search:
        cfg.tools = [types.Tool(google_search=types.GoogleSearch())]
    return cfg


# 응답이 MAX_TOKENS로 잘렸을 때 이어쓰기를 요청하는 프롬프트.
_CONTINUE_PROMPT = (
    "직전 응답이 분량 한도로 중간에서 끊겼습니다. 마지막 문장에 자연스럽게 이어서 계속 작성해주세요. "
    "이미 작성한 내용을 반복하지 말고, 인사말·설명·코드펜스 없이 이어지는 HTML 조각만 출력하세요."
)


def _finish_reason(resp: Any) -> str:
    try:
        return str(resp.candidates[0].finish_reason)
    except Exception:  # noqa: BLE001
        return ""


def _resp_text(resp: Any) -> str:
    # 차단/빈 후보 등에서 resp.text 접근이 예외를 던질 수 있어 방어적으로 처리.
    try:
        return resp.text or ""
    except Exception:  # noqa: BLE001
        return ""


def _generate_full(client: genai.Client, model: str, prompt: str,
                   gen_config: types.GenerateContentConfig) -> str:
    """generate_content 호출. 응답이 MAX_TOKENS로 잘리면 자동으로 이어쓰기해서
    긴 글이 중간에 끊기지 않게 이어붙인다(1시간+ 영상 심층 글 대응)."""
    convo: list[Any] = [types.Content(role="user", parts=[types.Part(text=prompt)])]
    chunks: list[str] = []
    for _ in range(config.GEMINI_MAX_CONTINUATIONS + 1):
        resp = client.models.generate_content(model=model, contents=convo, config=gen_config)
        text = _resp_text(resp)
        if text:
            chunks.append(text)
        if "MAX_TOKENS" in _finish_reason(resp) and text:
            convo.append(types.Content(role="model", parts=[types.Part(text=text)]))
            convo.append(types.Content(role="user", parts=[types.Part(text=_CONTINUE_PROMPT)]))
            continue
        break
    return "".join(chunks).strip()


def _generate_with_retry(client: genai.Client, model: str, prompt: str,
                         gen_config: types.GenerateContentConfig) -> str:
    last: Exception = RuntimeError("gemini 생성 실패")
    for attempt in range(config.GEMINI_MAX_RETRIES + 1):
        try:
            return _generate_full(client, model, prompt, gen_config)
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < config.GEMINI_MAX_RETRIES and _is_transient(e):
                delay = config.GEMINI_RETRY_BASE_SEC * (attempt + 1)
                log.warning("gemini %s 일시 한도/오류 → %d초 후 재시도 (%d/%d): %s",
                            model, delay, attempt + 1, config.GEMINI_MAX_RETRIES, str(e)[:120])
                time.sleep(delay)
                continue
            raise
    raise last  # pragma: no cover


def _call(prompt: str, quality: str, api_key: str | None = None,
          use_search: bool = False) -> str:
    client = _get_client(api_key)
    model = _model(quality)
    try:
        return _generate_with_retry(client, model, prompt, _gen_config(use_search=use_search))
    except Exception as e:  # noqa: BLE001
        # 검색 그라운딩이 지원되지 않거나 실패하면, 그라운딩 없이 한 번 더 시도(딥리서치도 결과는 나오게).
        if use_search:
            log.warning("검색 그라운딩 실패 → 그라운딩 없이 재시도: %s", str(e)[:120])
            try:
                return _generate_with_retry(client, model, prompt, _gen_config(use_search=False))
            except Exception as e2:  # noqa: BLE001
                e = e2
        # Pro가 쿼터/크레딧 소진으로 실패하면 Flash로 폴백 → 결과물(blog_long 등)은 무조건 나오게.
        flash = config.DEFAULT_GEMINI_MODEL
        if model != flash and _is_quota_like(e):
            log.warning("Pro(%s) 쿼터/크레딧 실패 → Flash(%s) 폴백: %s", model, flash, str(e)[:120])
            return _generate_with_retry(client, flash, prompt, _gen_config(use_search=False))
        raise


def _read_timed(transcript_text: str, max_chars: int | None = None) -> str:
    """자막이 너무 길면 앞/뒤만 남겨 토큰 사용을 제한한다. max_chars 미지정 시
    config.GEMINI_TRANSCRIPT_MAX_CHARS(기본 20만자)를 쓴다 — 1시간+ 영상 자막도 통째로 수용."""
    limit = max_chars if max_chars is not None else config.GEMINI_TRANSCRIPT_MAX_CHARS
    if len(transcript_text) <= limit:
        return transcript_text
    head = transcript_text[: limit // 2]
    tail = transcript_text[-limit // 2 :]
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


def generate_chapters(timed_transcript: str, title: str, quality: str, api_key: str | None = None) -> list[dict]:
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
    raw = _call(prompt, quality, api_key=api_key)
    try:
        data = _extract_json(raw)
        if isinstance(data, list):
            return data
    except Exception as exc:
        log.warning("chapter parse fallback: %s", exc)
    return [{"time": "00:00:00", "title": title or "전체 영상", "summary": raw[:200]}]


def generate_short_summary_html(plain_text: str, title: str, quality: str, api_key: str | None = None) -> str:
    prompt = f"""아래 유튜브 영상 "{title}"의 자막을 읽고 한국어로 짧고 명확하게 요약해주세요.

요구사항:
- 3~5문장의 핵심 요약
- 결과는 단일 HTML 조각만 반환 (코드펜스 금지, 설명 금지)
- 인라인 스타일 사용, 외부 CSS/JS 사용 금지
- 구조: <div style="..."> 안에 제목 1개 + 요약 본문

자막:
{_read_timed(plain_text, max_chars=40_000)}
"""
    return _strip_fence(_call(prompt, quality, api_key=api_key))


def generate_email_html(plain_text: str, title: str, chapters: list[dict], quality: str, api_key: str | None = None) -> str:
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
    return _strip_fence(_call(prompt, quality, api_key=api_key))


def _blog_targets(duration_sec: float | None, n_chapters: int) -> tuple[int, int, int]:
    """영상 길이에 비례한 (최소 글자수, 최대 글자수, 섹션수).
    긴 영상일수록 목표 분량과 섹션 수를 늘려 뒷부분이 잘리지 않고 전체를 커버하게 한다."""
    minutes = min((duration_sec or 0) / 60.0, 80)  # 80분 이상은 상한 고정(과도한 단일 생성 방지)
    mid = int(minutes * 230)  # 대략 분당 230자
    lo = max(1500, int(mid * 0.8))
    hi = max(lo + 1500, int(mid * 1.25))
    sections = max(6, min(max(n_chapters, 6), 18))
    return lo, hi, sections


def _ts_to_sec(ts: str) -> int:
    try:
        parts = [int(p) for p in str(ts).split(":")]
    except ValueError:
        return 0
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[-3] * 3600 + parts[-2] * 60 + parts[-1]


def _series_parts(plain_len: int, is_lang: bool) -> int:
    """영상이 길면 몇 '편'으로 나눌지 결정. 한 편이 너무 길어 잘리지 않도록 원문 길이 기준.
    언어학습은 (원문+번역+표현으로) 출력이 3~4배라 더 잘게 나눈다."""
    per = 5500 if is_lang else 14000   # 편당 소스 자막 글자수 목표
    cap = 6 if is_lang else 4
    n = max(1, -(-plain_len // per))   # ceil
    return min(n, cap)


def _split_into_parts(timed_text: str, plain_text: str, chapters: list[dict],
                      n_parts: int) -> list[tuple[str, list[dict]]]:
    """긴 영상을 n_parts개의 연속 구간으로 나눠 각 구간의 (plain_text, chapters)를 반환.
    타임드 자막을 누적 글자수 기준으로 균등 분할하고, 챕터는 시각으로 각 구간에 배정한다."""
    if n_parts <= 1:
        return [(plain_text, chapters)]
    rows: list[tuple[int, str]] = []
    for line in timed_text.splitlines():
        m = re.match(r"\[(\d{1,2}:\d{2}:\d{2})\]\s*(.*)", line.strip())
        if m and m.group(2).strip():
            rows.append((_ts_to_sec(m.group(1)), m.group(2).strip()))
    if len(rows) < n_parts:
        return [(plain_text, chapters)]  # 분할할 만큼 안 되면 단일
    total = sum(len(t) for _, t in rows)
    target = total / n_parts
    buckets: list[list[tuple[int, str]]] = [[] for _ in range(n_parts)]
    acc, idx = 0, 0
    for sec, txt in rows:
        buckets[idx].append((sec, txt))
        acc += len(txt)
        if idx < n_parts - 1 and acc >= target * (idx + 1):
            idx += 1
    buckets = [b for b in buckets if b]
    out: list[tuple[str, list[dict]]] = []
    for i, seg in enumerate(buckets):
        start = seg[0][0]
        end = buckets[i + 1][0][0] if i + 1 < len(buckets) else 10 ** 9
        seg_plain = re.sub(r"\s+", " ", " ".join(t for _, t in seg)).strip()
        seg_chaps = [c for c in chapters if start <= _ts_to_sec(c.get("time", "0")) < end]
        if not seg_chaps and chapters:  # 최소 1개는 배정
            seg_chaps = [chapters[min(i, len(chapters) - 1)]]
        out.append((seg_plain, seg_chaps))
    return out


def _renumber_figures(html: str, start: int) -> tuple[str, int]:
    """편별 blog_img_N.jpg 번호를 전체에서 연속되도록 다시 매긴다(스크린샷 매칭용)."""
    counter = [start]

    def repl(_m: "re.Match") -> str:
        n = counter[0]
        counter[0] += 1
        return f"blog_img_{n}.jpg"

    return re.sub(r"blog_img_\d+\.jpg", repl, html), counter[0]


def _series_note(idx: int, n: int) -> str:
    """각 편 생성 프롬프트 맨 앞에 붙일 시리즈 안내."""
    tail = ("마지막 편이므로 전체 시리즈를 아우르는 마무리로 끝맺으세요."
            if idx == n else f"이 편 끝에는 다음 편({idx + 1}편) 예고를 한 줄 덧붙이세요.")
    return (f"[시리즈 안내 — 반드시 반영] 이 글은 긴 영상을 {n}편으로 나눈 시리즈의 **{idx}편/{n}편**입니다. "
            f"아래 제공되는 자막은 영상 '전체'가 아니라 이 편에 해당하는 **구간**입니다. "
            f"그 구간의 내용만 충실히 다루고, 다른 구간 내용을 지어내지 마세요. "
            f"도입은 '이번 {idx}편에서는 ~'처럼 짧게 하고, {tail}\n\n")


def _detect_lang(text: str) -> str:
    """자막 텍스트의 '문자 체계'로 학습 대상 언어를 판별한다.

    언어학습(3번) 버전이 중국어/일본어 영상을 영어 학습글로 바꿔버리던 문제 대응.
    문자 종류는 번역문이 섞여도 비교적 확실한 신호라 모델의 추측보다 안전하다.
    라틴 문자면 구체 언어(영어/스페인어 등)는 모델이 판별하도록 빈 문자열을 반환.
    """
    t = text[:20000]
    kana = len(re.findall(r"[぀-ゟ゠-ヿ]", t))      # 히라가나/가타카나
    hangul = len(re.findall(r"[가-힣]", t))                  # 한글
    han = len(re.findall(r"[一-鿿]", t))                     # 한자
    latin = len(re.findall(r"[A-Za-z]", t))
    cyr = len(re.findall(r"[Ѐ-ӿ]", t))                     # 키릴
    total = kana + hangul + han + latin + cyr
    if total < 20:
        return ""
    if kana >= max(15, total * 0.02):   # 가나가 있으면 일본어(한자 섞여도)
        return "일본어"
    if hangul >= total * 0.30:
        return "한국어"
    if han >= total * 0.15:             # 가나 없이 한자 위주 → 중국어
        return "중국어"
    if cyr >= total * 0.30:
        return "러시아어"
    return ""


def generate_blog_html(plain_text: str, title: str, chapters: list[dict], quality: str,
                       api_key: str | None = None, duration: float | None = None,
                       series_note: str = "") -> str:
    chapters_md = "\n".join(f"- [{c.get('time','')}] {c.get('title','')} — {c.get('summary','')}" for c in chapters)
    lo, hi, sections = _blog_targets(duration, len(chapters))
    prompt = f"""아래 유튜브 영상 "{title}"을 블로그/카페에 올릴 한국어 장문 글로 작성해주세요.

요구사항:
- 도입(독자 hook) → 본문(챕터 기반 섹션 {sections}개 내외) → 결론(내용 요약 마무리)
- ⚠️ 영상 전체를 처음부터 끝까지 빠짐없이 다루세요. 목차(아래)의 **모든 챕터를 순서대로** 반영하고,
  영상 뒷부분(후반 챕터)을 절대 생략하거나 대충 넘어가지 마세요. 마지막 챕터까지 반드시 포함.
- ⚠️ '원본 영상 보러 가기', '영상 보기', 유튜브 링크 버튼 같은 CTA/링크는 절대 넣지 마세요(글 끝에 시스템이 별도 링크를 붙입니다).
- 각 섹션마다 소제목(h2), 본문 단락 2~4개, 필요시 불릿
- 인라인 스타일, 가독성 좋은 폰트/크기/간격
- 문맥과 맥락에 맞춰 단락을 자연스럽게 구분하세요(한 단락은 3~5문장 정도, 너무 길지 않게).
- 글의 핵심이 되는 단어·문장은 문맥을 파악해 강조하세요(남발 금지, 한 단락당 1~2곳만):
  · 핵심 키워드/숫자/고유명사: <strong style="color:#2563eb">텍스트</strong>  (굵게+파란색)
  · 글에서 가장 중요한 핵심 문장/주장: <strong style="color:#c2410c"><u>문장</u></strong>  (굵게+주황색+밑줄)
  · 보조 강조가 필요하면: <strong>텍스트</strong> 또는 <u>텍스트</u>
  강조는 정말 중요한 부분에만 — 본문 전체가 강조로 도배되지 않게 절제하세요.
- 각 주요 섹션(최소 3개, 최대 8개)에 영상 캡처 이미지를 삽입하세요:
  <figure style="margin:24px 0;text-align:center" data-timestamp="HH:MM:SS">
    <img src="blog_img_N.jpg" alt="이미지 설명" style="max-width:100%;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
    <figcaption style="margin-top:8px;font-size:13px;color:#64748b">이미지 설명</figcaption>
  </figure>
  여기서 N은 1부터 순서대로, HH:MM:SS는 해당 섹션 내용에 가장 적합한 영상 타임스탬프
  (목차의 시간을 참고하여 해당 섹션 내용이 나오는 시점의 타임스탬프를 정확히 지정)
- 결과는 HTML 조각만 (코드펜스/설명 금지, <html>/<body> 불필요)
- 글자수 {lo}~{hi}자 (영상이 길수록 길게 — 위 분량은 전체 내용을 처음부터 끝까지 담기 위한 기준)

목차:
{chapters_md}

자막:
{_read_timed(plain_text)}
"""
    return _finalize_blog(_strip_fence(_call(series_note + prompt, quality, api_key=api_key)))


# 목표 언어별 '읽기(발음)' 표기 규칙. 초보자가 화면만 보고 바로 따라 읽을 수 있어야 하므로
# 현지 표기 + 로마자/병음 + 한글 음차를 전부 준다.
_READING_RULES: dict[str, str] = {
    "중국어": "한어병음(성조 부호 필수) + 한글 음차  예) 你好 / nǐ hǎo / 니 하오",
    "일본어": "후리가나(히라가나) + 로마자 + 한글 음차  예) 行(い)きます / ikimasu / 이키마스",
    "영어": "발음기호 + 한글 음차  예) water / ˈwɔːtər / 워러",
    "스페인어": "로마자 음절 구분 + 한글 음차  예) gracias / gra-cias / 그라시아스",
    "프랑스어": "발음기호 + 한글 음차",
    "독일어": "발음기호 + 한글 음차",
    "러시아어": "로마자 전사 + 한글 음차",
    "베트남어": "성조 부호 그대로 + 한글 음차",
    "태국어": "로마자 전사(RTGS) + 한글 음차",
}


# ASR이 외국어를 한글로 음차하며 깨뜨린 전형적인 예. 모델에게 '이런 걸 복원하라'고 보여준다.
_GARBLE_EXAMPLES: dict[str, str] = {
    "일본어": "'아노 초또 이이데스카' → 「あの、ちょっといいですか」",
    "중국어": "'니 하오 마' → 「你好吗」, '씨에씨에' → 「谢谢」",
    "영어": "'왓두유민' → \"What do you mean?\"",
    "스페인어": "'그라시아스' → 「gracias」",
}


def _reading_rule(lang: str) -> str:
    return _READING_RULES.get(lang, "로마자 전사 + 한글 음차")


def generate_language_study_html(plain_text: str, title: str, chapters: list[dict], quality: str,
                                 api_key: str | None = None, duration: float | None = None,
                                 series_note: str = "", study_lang: str | None = None) -> str:
    """언어 학습 버전: '목표 언어 원문 + 읽기(병음/가나) + 한국어'의 3단 학습 카드로 만든다.

    *study_lang* 은 사용자가 텔레그램에서 고른 **학습 목표 언어**다. 영상의 음성 언어가 아니다.
    이 구분이 핵심: 한국어 강사가 일본어를 가르치는 영상은 자막이 한국어라서 자동 판별이
    '한국어'로 나오고, 그러면 한국어 학습글이 나와 버린다(실제로 그랬다). 목표 언어가
    주어지면 자동 판별보다 항상 우선한다.
    """
    chapters_md = "\n".join(f"- [{c.get('time','')}] {c.get('title','')}" for c in chapters)
    _, _, sections = _blog_targets(duration, len(chapters))
    spoken = _detect_lang(plain_text)                 # 자막(=영상 음성)의 언어
    chosen = (study_lang or "").strip()               # 사용자가 고른 목표 언어
    # 사용자가 고르지 않았는데 자막이 한국어면 '한국어 학습글'을 만들면 절대 안 된다.
    # 한국인 대상 외국어 강의라는 뜻이므로, 목표 언어를 모델이 제목/내용에서 찾게 한다.
    auto_korean = (not chosen) and spoken == "한국어"
    target = chosen or ("" if auto_korean else spoken)
    reading = _reading_rule(target) if target else "로마자 전사 + 한글 음차"

    if auto_korean:
        lang_block = (
            "- ⚠️ 이 영상은 **한국어로 진행되는 외국어 강의**입니다(자막이 한국어인 이유). "
            "한국어를 가르치는 자료를 만들면 완전히 실패입니다.\n"
            "- 제목과 내용을 보고 **강사가 가르치는 외국어가 무엇인지 먼저 판단**한 뒤, 그 언어를 목표 언어로 삼으세요.\n"
            "- 목표 언어 표현은 그 나라 고유 문자로 적고, 읽기(중국어=한어병음, 일본어=후리가나+로마자, "
            "그 외=로마자 전사)와 한글 음차, 한국어 뜻을 함께 주세요.\n"
            "- 강사의 한국어 설명은 학습 대상이 아닙니다. 번역하지 말고 참고만 하세요."
        )
    elif not target:
        lang_block = (
            "- **학습 대상 언어 = 아래 자막에 실제로 쓰인 외국어**입니다. 임의로 영어 등으로 바꾸지 마세요.\n"
            "- 목표 언어 문장은 그 나라 문자 그대로 쓰고, 읽기(로마자+한글 음차)와 한국어 뜻을 함께 주세요."
        )
    else:
        lang_block = (
            f"- **학습 목표 언어는 '{target}' 입니다. 예외 없습니다.**\n"
            f"- 목표 언어 문장·단어는 반드시 **{target}의 고유 문자 그대로** 적으세요"
            f"(한글로 음차한 것만 적어 두면 학습이 되지 않습니다).\n"
            f"- 읽기 표기는 **{reading}** 형식으로 주세요.\n"
            f"- 설명·뜻·해설은 한국어로 씁니다."
        )
        if spoken and spoken != target:
            eg = _GARBLE_EXAMPLES.get(target, "")
            eg_txt = f" (예: {eg})" if eg else ""
            lang_block += (
                f"\n- ⚠️ **중요**: 이 영상은 {spoken}로 진행되는 {target} 강의입니다. 자막은 {spoken} "
                f"받아쓰기라서, 강사가 말한 {target} 표현이 **한글로 음차되어 들어가 있고 많이 깨져 있습니다**{eg_txt}. "
                f"당신의 가장 중요한 일은 그 깨진 음차를 앞뒤 맥락으로 **{target} 원문으로 복원**하는 것입니다. "
                f"깨진 한글 음차를 그대로 결과물에 남기지 마세요.\n"
                f"- 강사의 {spoken} 잡담·인사·군더더기는 학습 대상이 아닙니다. 그것까지 문장별로 번역하지 말고, "
                f"**강사가 가르친 {target} 표현**을 중심으로 재구성하세요.\n"
                f"- 복원이 불확실하면 그 표현은 빼세요. 확실한 것만 싣습니다(틀린 외국어를 가르치면 안 됩니다)."
            )

    prompt = f"""아래 유튜브 영상 "{title}"을 바탕으로, **한국인 초보자가 {target or '해당 외국어'}를 보고 따라 하며 공부할 수 있는**
한국어 학습 자료(HTML)를 만들어주세요. 요약 글이 아니라 **학습지**입니다.

[언어 규칙 — 가장 중요]
{lang_block}

[각 표현은 반드시 이 '학습 카드' 형식으로]
영상에서 가르치는 표현 하나마다 카드 1개. 카드 안에는 목표어·읽기·뜻이 **항상 3줄 세트**로 들어갑니다.

<div style="border:1px solid #e2e8f0;border-left:4px solid #2563eb;border-radius:8px;padding:14px 16px;margin:18px 0;background:#f8fafc">
  <p style="margin:0 0 6px;font-size:22px;font-weight:700;color:#0f172a">목표어 표현</p>
  <p style="margin:0 0 2px;font-size:15px;color:#2563eb">🔊 읽기: {reading or '읽기 표기'}</p>
  <p style="margin:0 0 10px;font-size:17px;color:#0f172a">🇰🇷 뜻: 한국어 뜻</p>
  <p style="margin:10px 0 4px;font-size:14px;color:#475569"><b>언제 쓰나</b> — 쓰임새 한두 줄</p>
  <p style="margin:8px 0 4px;font-size:14px;color:#475569"><b>예문</b></p>
  <ol style="margin:4px 0 0;padding-left:20px;color:#0f172a">
    <li style="margin-bottom:8px">
      <span style="font-size:17px;font-weight:600">목표어 예문</span><br>
      <span style="color:#2563eb;font-size:14px">읽기</span><br>
      <span style="font-size:15px">한국어 뜻</span>
    </li>
  </ol>
</div>

- 예문은 카드마다 **2~3개**. 예문도 반드시 목표어 / 읽기 / 한국어 3줄을 모두 채우세요.
- 영상에서 강사가 실제로 든 예문을 우선 쓰고, 부족하면 같은 난이도의 쉬운 예문으로 보충하세요.
- 단어를 쪼개 설명하면 좋은 표현은 카드 아래에 한 줄:
  <p style="margin:8px 0 0;font-size:13px;color:#64748b">🧩 쪼개 보기: 조각1(뜻) + 조각2(뜻) → 전체 뜻</p>
- 발음에 함정이 있으면(촉음·성조·연음 등):
  <p style="margin:6px 0 0;font-size:13px;color:#b45309">💡 발음 포인트: ...</p>

[전체 구조]
- 맨 앞: 이 자료로 무엇을 어떻게 공부하면 되는지 2~3문장 + "소리 내어 3번 따라 읽기" 같은 학습법 안내.
- 목차 구간을 소제목(h2)으로 나눠 정리(대략 {sections}개 구간). 영상을 처음부터 끝까지 빠짐없이.
- 각 구간 h2 바로 아래, 그 구간에서 뭘 배우는지 한국어로 1~2문장.
- 각 주요 구간(3~8개)에 영상 캡처 이미지:
  <figure style="margin:20px 0;text-align:center" data-timestamp="HH:MM:SS">
    <img src="blog_img_N.jpg" alt="이미지 설명" style="max-width:100%;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
    <figcaption style="margin-top:8px;font-size:13px;color:#64748b">이미지 설명</figcaption>
  </figure>
  (N은 1부터 순서대로, HH:MM:SS는 목차를 참고한 해당 구간 타임스탬프)
- 맨 끝: **복습표** — 이 글에 나온 표현 전부를 한 번에 훑는 표.
  <table style="width:100%;border-collapse:collapse;margin:18px 0;font-size:15px">
    <thead><tr style="background:#1e293b;color:#fff">
      <th style="padding:8px;text-align:left">{target or '목표어'}</th>
      <th style="padding:8px;text-align:left">읽기</th>
      <th style="padding:8px;text-align:left">뜻</th>
    </tr></thead>
    <tbody><tr style="border-bottom:1px solid #e2e8f0">
      <td style="padding:8px;font-weight:600">표현</td><td style="padding:8px;color:#2563eb">읽기</td><td style="padding:8px">뜻</td>
    </tr></tbody>
  </table>

[금지]
- ⚠️ 한국어만 나열된 글이 되면 완전히 실패입니다. 모든 카드에 목표어 문자가 반드시 들어가야 합니다.
- ⚠️ 강사의 한국어 발화를 문장별로 옮겨 적고 번역하는 식(스크립트 받아쓰기)은 금지입니다.
- ⚠️ '원본 영상 보러 가기' 등 CTA/링크 금지(글 끝에 시스템이 별도 링크를 붙임).
- 결과는 HTML 조각만 (코드펜스/설명 금지, <html>/<body> 불필요).

목차:
{chapters_md}

자막(스크립트):
{_read_timed(plain_text)}
"""
    return _finalize_blog(_strip_fence(_call(series_note + prompt, quality, api_key=api_key)))


def generate_blog_html_deep(plain_text: str, title: str, chapters: list[dict], quality: str,
                            api_key: str | None = None, series_note: str = "") -> str:
    """딥리서치 버전: 일반 버전보다 훨씬 길고 깊이 있는 블로그 글.
    Google 검색 그라운딩으로 영상 밖의 배경지식·통계·관련 사례를 조사해 반영한다."""
    chapters_md = "\n".join(f"- [{c.get('time','')}] {c.get('title','')} — {c.get('summary','')}" for c in chapters)
    prompt = f"""당신은 해당 분야를 깊이 있게 취재하는 전문 칼럼니스트입니다.
아래 유튜브 영상 "{title}"을 바탕으로, 웹 검색으로 배경지식을 추가 조사하여
매우 깊이 있고 긴 한국어 심층 블로그 글(딥리서치 버전)을 작성해주세요.

[리서치 지침 — 매우 중요]
- 영상 내용만 요약하지 말고, 웹 검색을 활용해 다음을 추가로 조사·반영하세요:
  · 영상에서 언급된 핵심 개념·용어·인물·기업·기술의 배경 설명과 정의
  · 관련 최신 통계·수치·사실, 시장/업계 동향, 역사적 맥락
  · 영상 주장에 대한 다른 관점·비교 사례·전문가 시각
- 조사한 사실은 본문에 자연스럽게 녹여 쓰되, 매끄럽게 통합하세요.
- 추측이나 허위 정보는 금지. 검색으로 확인된 내용만 쓰세요.

[글 구조 — 일반 버전보다 훨씬 길고 깊게]
- 도입: 독자의 호기심을 자극하는 문제제기 + 왜 이 주제가 중요한지 배경 (2~3단락)
- 본문: 챕터 기반 섹션 10~16개. 각 섹션은:
  · 소제목(h2)
  · 영상 내용 정리 + 검색으로 조사한 배경/맥락/데이터를 결합한 심층 서술 (단락 3~6개)
  · 필요시 개념 정리나 불릿으로 핵심 정리
- 중간중간 '💡 배경 지식', '📊 관련 데이터', '🔍 더 깊이 보기' 같은 소제목(h3)으로
  영상 밖에서 조사한 내용을 별도 정리하면 좋습니다.
- 결론: 핵심 요약 + 시사점/전망 + 독자에게 남기는 통찰 (2~3단락)
- ⚠️ '원본 영상 보러 가기', '영상 보기', 유튜브 링크 버튼 같은 CTA/링크는 절대 넣지 마세요(글 끝에 시스템이 별도 링크를 붙입니다).

[분량]
- 글자수 5000~9000자 (일반 버전의 2~3배). 절대 짧게 쓰지 마세요. 깊이와 분량을 모두 채우세요.

[형식 — 일반 버전과 동일]
- 인라인 스타일, 가독성 좋은 폰트/크기/간격. 한 단락은 3~6문장.
- 핵심 강조(남발 금지, 한 단락당 1~2곳):
  · 핵심 키워드/숫자/고유명사: <strong style="color:#2563eb">텍스트</strong>
  · 가장 중요한 핵심 문장/주장: <strong style="color:#c2410c"><u>문장</u></strong>
  · 보조 강조: <strong>텍스트</strong> 또는 <u>텍스트</u>
- 각 주요 섹션(최소 4개, 최대 10개)에 영상 캡처 이미지를 삽입:
  <figure style="margin:24px 0;text-align:center" data-timestamp="HH:MM:SS">
    <img src="blog_img_N.jpg" alt="이미지 설명" style="max-width:100%;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
    <figcaption style="margin-top:8px;font-size:13px;color:#64748b">이미지 설명</figcaption>
  </figure>
  N은 1부터 순서대로, HH:MM:SS는 해당 섹션 내용이 나오는 영상 타임스탬프(목차 참고).
- 결과는 HTML 조각만 (코드펜스/설명 금지, <html>/<body> 불필요, 참고문헌 URL 나열 금지)

목차:
{chapters_md}

자막:
{_read_timed(plain_text)}
"""
    return _finalize_blog(_strip_fence(_call(series_note + prompt, quality, api_key=api_key, use_search=True)))


def generate_naver_blog_html(plain_text: str, title: str, chapters: list[dict], quality: str, api_key: str | None = None) -> str:
    """네이버 블로그 에디터에 복사-붙여넣기 최적화된 HTML을 생성한다.
    네이버는 복잡한 인라인 CSS, figure/figcaption, base64 이미지를 제대로 처리하지 못하므로
    최대한 단순한 HTML 구조로 생성한다."""
    chapters_md = "\n".join(f"- [{c.get('time','')}] {c.get('title','')} — {c.get('summary','')}" for c in chapters)
    prompt = f"""아래 유튜브 영상 "{title}"을 네이버 블로그에 복사-붙여넣기 할 수 있는 한국어 장문 글로 작성해주세요.

핵심 규칙 (네이버 블로그 에디터 호환):
- 인라인 스타일은 최소화: font-weight:bold, text-align:center, color 정도만 사용
- 복잡한 CSS(box-shadow, border-radius, max-width 등)는 절대 사용 금지
- <figure>, <figcaption> 태그 금지 → 대신 <p style="text-align:center"><img></p> 사용
- <style> 태그, <head> 태그 금지 → <body> 안의 내용만 HTML 조각으로 반환
- 글자 강조는 <strong>과 <b>만 사용, color 강조는 <span style="color:#색상">텍스트</span>
- 이미지 태그: <img src="naver_img_N.jpg" alt="설명" data-timestamp="HH:MM:SS">
  (N은 1부터 순서대로, HH:MM:SS는 해당 내용에 맞는 영상 타임스탬프)
- 각 주요 섹션(3~8개)에 이미지를 배치
- 단락 구분은 <p>, 줄바꿈은 <br>, 소제목은 <h3>
- <h2>는 주요 섹션 구분에만 사용

글 구조:
- 도입: 독자의 관심을 끄는 1~2문장 + 영상 소개
- 본문: 챕터 기반 섹션 6~10개, 각 섹션에 소제목(h3) + 본문 2~4단락
- 결론: 핵심 요약 + 마무리 한 줄
- ⚠️ '원본 영상 보러 가기', '영상 보기', 유튜브 링크 버튼 같은 CTA/링크는 절대 넣지 마세요(글 끝에 시스템이 별도 링크를 붙입니다).
- 글자수 1500~3000자

핵심 키워드/숫자/고유명사 강조: <b>텍스트</b>
가장 중요한 문장: <span style="color:#e74c3c"><b>문장</b></span>

결과는 HTML 조각만 반환 (코드펜스/설명 금지, <html>/<body>/<head>/<style> 태그 불필요)

목차:
{chapters_md}

자막:
{_read_timed(plain_text)}
"""
    return _finalize_blog(_strip_fence(_call(prompt, quality, api_key=api_key)), naver=True)


def extract_naver_image_timestamps(naver_html: str) -> list[dict]:
    """Parse img[data-timestamp] from Naver blog HTML.
    Returns: [{"index": 1, "timestamp": "00:05:30", "alt": "설명"}, ...]
    """
    results: list[dict] = []
    img_pattern = re.compile(
        r'src=["\']naver_img_(\d+)\.jpg["\']',
        re.IGNORECASE,
    )
    ts_pattern = re.compile(
        r'data-timestamp=["\']([\d:]+)["\']',
        re.IGNORECASE,
    )
    alt_pattern = re.compile(
        r'alt=["\']([^"\']*)["\']',
        re.IGNORECASE,
    )
    for img_m in img_pattern.finditer(naver_html):
        idx = int(img_m.group(1))
        region = naver_html[max(0, img_m.start() - 50):img_m.start() + 300]
        ts_m = ts_pattern.search(region)
        alt_m = alt_pattern.search(region)
        results.append({
            "index": idx,
            "timestamp": ts_m.group(1) if ts_m else "00:00:10",
            "alt": alt_m.group(1) if alt_m else "",
        })
    return results


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:html)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


# 모든 블로그 글 맨 끝에 항상 붙는 고정 푸터(주인장 홈페이지 링크).
HOMEPAGE_URL = "https://25world.netlify.app"
HOMEPAGE_LABEL = "JINI+US 주인장 홈페이지"

# Gemini가 자동으로 넣는 "원본 영상 보러 가기" 류 CTA를 판별하는 문구.
_VIDEO_CTA_PHRASES = (
    "원본 영상", "원본영상", "영상 보러", "영상보러", "영상 보기", "영상보기",
    "전체 영상", "영상 확인", "유튜브에서", "유튜브 영상 보기", "watch on youtube",
    "영상 링크", "원본 링크",
)


def _strip_video_cta(fragment: str) -> str:
    """블로그 HTML 조각에서 '원본 영상 보러 가기' 같은 영상 링크/버튼(<a>)을 제거한다.
    유튜브로 연결되거나 영상보기 문구가 들어간 <a>만 골라 지우고, 그로 인해
    비게 된 <p>/<div>/<figure> 래퍼도 정리한다. 일반 본문 텍스트는 건드리지 않는다."""
    def _repl(m: "re.Match") -> str:
        href = (m.group(1) or "").lower()
        inner_text = re.sub(r"<[^>]+>", "", m.group(2))
        if ("youtube.com/watch" in href or "youtu.be/" in href
                or any(p in inner_text for p in _VIDEO_CTA_PHRASES)):
            return ""
        return m.group(0)

    fragment = re.sub(
        r'<a\s+[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>',
        _repl, fragment, flags=re.IGNORECASE | re.DOTALL,
    )
    # 링크가 사라져 내용이 빈 래퍼 블록 제거
    for tag in ("figure", "p", "div"):
        fragment = re.sub(rf'<{tag}[^>]*>\s*</{tag}>', "", fragment,
                          flags=re.IGNORECASE | re.DOTALL)
    return fragment


def _blog_footer(naver: bool = False) -> str:
    """글 맨 끝에 붙는 주인장 홈페이지 링크. 네이버는 단순 HTML, 그 외엔 버튼 스타일."""
    if naver:
        return (f'<p style="text-align:center">'
                f'<a href="{HOMEPAGE_URL}" target="_blank"><b>{HOMEPAGE_LABEL}</b></a></p>')
    return (
        f'<div style="text-align:center; margin:32px 0;">'
        f'<a href="{HOMEPAGE_URL}" target="_blank" '
        f'style="display:inline-block; padding:12px 24px; background-color:#c2410c; '
        f'color:#fff; text-decoration:none; border-radius:8px; font-weight:bold;">'
        f'{HOMEPAGE_LABEL}</a></div>'
    )


def _finalize_blog(fragment: str, naver: bool = False) -> str:
    """영상 CTA/링크 제거 (모든 블로그 산출물 공통).
    홈페이지 푸터 버튼은 사용자 요청(2026-08-21)으로 더 이상 붙이지 않는다."""
    return _strip_video_cta(fragment).rstrip() + "\n"


def extract_blog_image_timestamps(blog_html: str) -> list[dict]:
    """Parse figure[data-timestamp] from blog HTML.

    Returns a list of dicts:
      [{"index": 1, "timestamp": "00:05:30", "alt": "설명"}, ...]
    """
    results: list[dict] = []
    # Match <figure ... data-timestamp="HH:MM:SS" ...>
    fig_pattern = re.compile(
        r'<figure[^>]*data-timestamp=["\']([\d:]+)["\'][^>]*>',
        re.IGNORECASE,
    )
    img_pattern = re.compile(
        r'src=["\']blog_img_(\d+)\.jpg["\']',
        re.IGNORECASE,
    )
    alt_pattern = re.compile(
        r'alt=["\']([^"\']*)["\']',
        re.IGNORECASE,
    )

    for fig_match in fig_pattern.finditer(blog_html):
        ts = fig_match.group(1)
        # Search for img tag near this figure
        region = blog_html[fig_match.start():fig_match.start() + 500]
        img_m = img_pattern.search(region)
        alt_m = alt_pattern.search(region)
        idx = int(img_m.group(1)) if img_m else len(results) + 1
        alt = alt_m.group(1) if alt_m else ""
        results.append({
            "index": idx,
            "timestamp": ts,
            "alt": alt,
        })

    # Fallback: if Gemini didn't include data-timestamp, try to match img tags
    if not results:
        for img_m in img_pattern.finditer(blog_html):
            idx = int(img_m.group(1))
            alt_m = alt_pattern.search(blog_html[img_m.start():img_m.start() + 200])
            results.append({
                "index": idx,
                "timestamp": "00:00:10",  # default fallback
                "alt": alt_m.group(1) if alt_m else "",
            })

    return results


def generate_all(job_dir: Path, title: str, quality: str, api_key: str | None = None,
                 wants: set[str] | None = None, naver: bool = False,
                 deep_research: bool = False, lang_study: bool = False,
                 study_lang: str | None = None,
                 duration: float | None = None) -> dict[str, Any]:
    """Reads plain + timed transcripts and produces outputs.
    *wants* 가 None이면 전부 생성(하위호환). 집합이면 chapters/blog는 항상 생성하고
    summary/email은 wants에 포함될 때만 생성(불필요한 Gemini 호출/크레딧 절약).
    *naver* 가 True이면 네이버 블로그 최적화 HTML도 추가 생성.
    blog_html 버전 선택: *lang_study*=True면 언어학습 버전, *deep_research*=True면 딥리서치 버전,
    둘 다 아니면 일반 버전(길이는 *duration*에 비례해 자동 조정)."""
    plain_path = job_dir / "transcript.txt"
    timed_path = job_dir / "transcript_timed.txt"
    plain_text = plain_path.read_text(encoding="utf-8") if plain_path.exists() else ""
    timed_text = timed_path.read_text(encoding="utf-8") if timed_path.exists() else plain_text

    def want(k: str) -> bool:
        return wants is None or k in wants

    chapters = generate_chapters(timed_text, title, quality, api_key=api_key)  # 블로그에 필요 → 항상
    summary_short = (generate_short_summary_html(plain_text, title, quality, api_key=api_key)
                     if want("summary") else None)
    email_html = (generate_email_html(plain_text, title, chapters, quality, api_key=api_key)
                  if want("email") else None)
    def _gen_part(seg_plain: str, seg_chaps: list[dict], note: str, seg_dur: float | None) -> str:
        if lang_study:
            return generate_language_study_html(seg_plain, title, seg_chaps, quality,
                                                 api_key=api_key, duration=seg_dur, series_note=note,
                                                 study_lang=study_lang)
        if deep_research:
            return generate_blog_html_deep(seg_plain, title, seg_chaps, quality,
                                           api_key=api_key, series_note=note)
        return generate_blog_html(seg_plain, title, seg_chaps, quality,
                                  api_key=api_key, duration=seg_dur, series_note=note)

    # 아주 긴 영상은 1편/2편/3편 시리즈로 나눠 각 편을 '별도 Gemini 호출'로 생성(한 번에 다
    # 쓰려다 뒷부분이 잘리는 문제 방지). 짧으면 n=1로 기존과 동일.
    n = len(_split_into_parts(timed_text, plain_text, chapters, _series_parts(len(plain_text), lang_study)))
    if n <= 1:
        blog_html = _gen_part(plain_text, chapters, "", duration)
    else:
        segments = _split_into_parts(timed_text, plain_text, chapters, n)
        n = len(segments)
        seg_dur = (duration / n) if duration else None
        pieces: list[str] = []
        fig_i = 1
        for i, (seg_plain, seg_chaps) in enumerate(segments, 1):
            ph = _gen_part(seg_plain, seg_chaps, _series_note(i, n), seg_dur)
            ph, fig_i = _renumber_figures(ph, fig_i)
            banner = (f'<h1 style="margin:8px 0 16px;padding:10px 16px;border-radius:8px;'
                      f'background:#1e293b;color:#fff;font-size:22px">📖 {i}편 / 총 {n}편</h1>')
            pieces.append(banner + "\n" + ph)
        blog_html = '\n<hr style="border:none;border-top:2px dashed #cbd5e1;margin:44px 0">\n'.join(pieces)
    blog_image_timestamps = extract_blog_image_timestamps(blog_html)

    # 네이버 블로그 최적화 HTML (요청 시에만 생성)
    naver_blog_html = None
    naver_image_timestamps = []
    if naver:
        naver_blog_html = generate_naver_blog_html(plain_text, title, chapters, quality, api_key=api_key)
        naver_image_timestamps = extract_naver_image_timestamps(naver_blog_html)

    return {
        "chapters": chapters,
        "summary_short_html": summary_short,
        "email_html": email_html,
        "blog_html": blog_html,
        "blog_image_timestamps": blog_image_timestamps,
        "naver_blog_html": naver_blog_html,
        "naver_image_timestamps": naver_image_timestamps,
    }

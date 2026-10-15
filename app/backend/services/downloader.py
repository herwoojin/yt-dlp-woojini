"""yt-dlp wrapper. Two-pass strategy:

1) Download the video itself with conservative retries.
2) Best-effort subtitle pass (ko, en only). Failures here do NOT abort the job
   - YouTube frequently 429s on subtitle endpoints if many languages are
   requested.

If a YT_DLP_COOKIES_FILE env var is set, it is forwarded to yt-dlp - useful
when YouTube starts demanding sign-in for bot-flagged IPs.
"""
from __future__ import annotations

import contextlib
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yt_dlp

log = logging.getLogger(__name__)

# 자막 언어 기본 후보. 실제로는 _preferred_sub_langs()가 영상의 '원어'를 최우선으로 계산한다.
SUB_LANGS = ["ko-orig", "ko", "en"]


def _preferred_sub_langs(info: dict[str, Any] | None) -> list[str]:
    """이 영상에서 받을 자막 언어를 '원어 우선' 순서로 계산한다.

    언어학습(3번) 버전은 원어 스크립트가 반드시 필요하다. 예전에는 ko(한국어 자동번역)가
    먼저 잡혀서 중국어/일본어 영상도 한국어 번역문만 남아 학습글이 엉뚱하게 나왔다.
    우선순위: (1) '-orig'(원어 자동자막) → (2) 메타데이터상 영상 언어 → (3) ko → en.
    """
    info = info or {}
    auto = info.get("automatic_captions") or {}
    manual = info.get("subtitles") or {}
    avail = list(manual.keys()) + [k for k in auto if k not in manual]
    langs: list[str] = [k for k in avail if k.endswith("-orig")]
    vid_lang = info.get("language")
    if vid_lang and vid_lang not in langs:
        langs.append(vid_lang)
    # 원어가 확인되면 그 언어의 번역 아닌 기본 코드도 함께(원어 파일명이 -orig가 아닐 수 있음)
    for k in list(langs):
        base = k[:-5] if k.endswith("-orig") else None
        if base and base in avail and base not in langs:
            langs.append(base)
    for k in ("ko", "en"):
        if k not in langs:
            langs.append(k)
    return langs[:6]


# YouTube는 progressive(영상+음성이 한 파일) mp4 제공을 사실상 중단했다. 그래서
# 'best[ext=mp4]/best' 같은 단일파일 선택자는 format 18(360p)만 노리다가
# 'Requested format is not available' 또는 재생URL 403으로 실패한다.
# DASH(영상/음성 분리 → ffmpeg 병합)를 앞에 붙이고 원래 선택자는 폴백으로 남긴다.
# fly.dev가 옛 기본값을 그대로 보내와도 워커에서 교정되도록 여기서 일괄 정규화한다.
# 화질 상한. 예전 기본값(progressive format 18)은 사실상 360p였는데, DASH로 바꾸면
# 상한이 없을 때 1080p Premium(f616) 같은 초고비트레이트가 잡혀 47분 영상이 1GB를 넘는다.
# 이 앱의 산출물(자막/블로그/스크린샷)엔 720p면 충분하다. 더 좋은 화질이 필요하면
# YT_DLP_MAX_HEIGHT=1080 처럼 올리면 된다(0 또는 빈 값이면 상한 없음).
def _max_height() -> int:
    try:
        return int(os.getenv("YT_DLP_MAX_HEIGHT", "720") or 0)
    except ValueError:
        return 720


def _normalize_format(fmt: str | None) -> str:
    fmt = (fmt or "").strip() or "best[ext=mp4]/best"
    if "+" in fmt:  # 이미 영상+음성 병합을 지정한 선택자는 그대로 둔다
        return fmt
    cap = f"[height<={_max_height()}]" if _max_height() > 0 else ""
    return f"bv*{cap}[ext=mp4]+ba[ext=m4a]/bv*{cap}+ba/{fmt}"


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"


class _YdlLog:
    """yt-dlp 로그를 콘솔에서 조용히 흡수하되, '쿠키 만료(로테이션)' 경고만 감지한다.
    이 경고는 no_warnings로 억제되던 것이라, 감지해서 상위에 명확한 사유로 올려준다."""

    def __init__(self) -> None:
        self.cookies_invalid = False

    def debug(self, msg: str) -> None:  # noqa: D401
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        low = msg.lower()
        if "no longer valid" in low or ("cookie" in low and "rotat" in low):
            self.cookies_invalid = True
        log.debug("yt-dlp: %s", msg)

    def error(self, msg: str) -> None:
        log.debug("yt-dlp error: %s", msg)


def _resolve_master_cookiefile() -> str | None:
    """설정된 마스터 쿠키 파일 경로(존재하는 것)를 반환. 없으면 None."""
    cookies = os.getenv("YT_DLP_COOKIES_FILE") or ""
    if not cookies or not os.path.exists(cookies):
        # fly.dev 볼륨 기본 경로 폴백
        _default = "/data/youtube_cookies.txt"
        cookies = _default if os.path.exists(_default) else ""
    return cookies or None


@contextlib.contextmanager
def _cookie_copy():
    """마스터 쿠키 파일의 임시 복사본 경로를 yield 한다.

    yt-dlp는 cookiefile을 실행 후 되쓰기(save)하는데, 봇차단/실패 응답을 받으면
    세션 인증쿠키가 스트립되어 원본이 점점 망가진다(→ 이후 전부 403). 그래서 항상
    사본을 넘기고 사본만 버려서 마스터는 절대 건드리지 않는다. 마스터가 없으면 None.
    """
    master = _resolve_master_cookiefile()
    if not master:
        yield None
        return
    fd, tmp = tempfile.mkstemp(prefix="ytck_", suffix=".txt")
    os.close(fd)
    try:
        shutil.copyfile(master, tmp)
        yield tmp
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp)


def _base_opts(cookiefile: str | None = None) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 10,
        "fragment_retries": 10,
        "file_access_retries": 5,
        "extractor_retries": 5,
        "http_headers": {"User-Agent": UA},
        # VPN/보안 프록시가 HTTPS를 가로채(self-signed cert) 인증서 검증이 실패하는 환경 대응.
        # 환경변수 YT_DLP_NO_CHECK_CERT=0 으로 끌 수 있음.
        "nocheckcertificate": os.getenv("YT_DLP_NO_CHECK_CERT", "1") != "0",
    }
    # YouTube는 이제 서명/n-sig 챌린지 해결에 JavaScript 런타임을 요구한다(EJS 시스템).
    # yt-dlp 기본값은 'deno' 전용이라, deno 미설치 환경에서는 챌린지를 못 풀고
    # android_vr 폴백으로 빠져 'unable to download video data: HTTP Error 403: Forbidden'이 난다.
    # 이 PC에는 Node가 설치돼 있으므로 node를 런타임으로 활성화한다(deno가 있으면 deno 우선 사용).
    # node는 기본적으로 PATH에서 찾으며, YT_DLP_NODE_PATH로 바이너리/폴더 경로를 직접 지정할 수 있다.
    # 참고: https://github.com/yt-dlp/yt-dlp/wiki/EJS
    node_cfg: dict[str, Any] = {}
    _node_path = os.getenv("YT_DLP_NODE_PATH")
    if _node_path:
        node_cfg["path"] = _node_path
    opts["js_runtimes"] = {"deno": {}, "node": node_cfg}
    # player_client는 강제하지 않는다(기본값이 정상 포맷을 줌). 강제하면 일부 영상이
    # 'DRM protected'/'No video formats'로 잘못 나옴. 필요 시 YT_DLP_PLAYER_CLIENTS로만 지정.
    player_clients = [c.strip() for c in os.getenv("YT_DLP_PLAYER_CLIENTS", "").split(",") if c.strip()]
    if player_clients:
        opts.setdefault("extractor_args", {})["youtube"] = {"player_client": player_clients}
    # bgutil PO 토큰 HTTP 프로바이더 사용(봇차단 우회). YT_DLP_POT_BASE_URL=http://127.0.0.1:4416
    pot_base = os.getenv("YT_DLP_POT_BASE_URL")
    if pot_base:
        opts.setdefault("extractor_args", {})["youtubepot-bgutilhttp"] = {"base_url": [pot_base]}
    # 쿠키: YT_DLP_COOKIES_FROM_BROWSER가 설정되면 브라우저에서 매번 최신 쿠키를 직접
    # 읽는다(로테이션/만료 걱정 없음 — 자동화에 가장 안정적). 예: "firefox", "chrome",
    # "firefox:프로필경로". Firefox는 실행 중에도 읽히지만 Chrome은 종료해야 읽힌다.
    # 그 외에는 마스터 쿠키의 임시 사본을 쓴다(_cookie_copy — yt-dlp가 되쓰기해도 마스터 안전).
    cfb = os.getenv("YT_DLP_COOKIES_FROM_BROWSER", "").strip()
    if cfb:
        _br, _, _prof = cfb.partition(":")
        opts["cookiesfrombrowser"] = (_br, _prof or None, None, None)
        log.debug("using cookies from browser: %s", cfb)
    elif cookiefile and os.path.exists(cookiefile):
        opts["cookiefile"] = cookiefile
        log.debug("using cookies (temp copy) %s", cookiefile)
    # 거주용(residential) 프록시: fly.dev 데이터센터 IP 차단 우회. 예: http://user:pass@host:port
    proxy = os.getenv("YT_DLP_PROXY")
    if proxy:
        opts["proxy"] = proxy
    return opts


# bgutil PO Token '스크립트' 공급자의 콜드 스타트 함정.
# generate_once.js는 첫 실행에 node 모듈 350여 개를 읽느라 ~18초가 걸리는데 플러그인의
# 버전확인 타임아웃은 15초다. 게다가 이 확인은 yt-dlp가 공급자를 훑는 *제너레이터* 안에서
# 호출돼(_get_providers), 예외가 _get_po_token의 try/except를 그대로 빠져나가 작업 전체를
# 죽인다(플러그인 1.3.1/2.0.1 공통). 평소에는 POT HTTP 서버(4416)가 우선순위 130으로 먼저
# 응답해 스크립트까지 가지도 않지만, 서버가 꺼져 있으면 여기로 떨어진다.
# 한 번 돌고 나면 파일 캐시가 더워져 ~4초면 끝나므로 1회 재시도로 복구된다.
def _is_pot_cold_timeout(exc: BaseException) -> bool:
    msg = str(exc)
    return "timed out" in msg and "generate_once" in msg


def _download_video(url: str, target_dir: Path, video_format: str) -> dict[str, Any]:
    with _cookie_copy() as ck:
        ydl_log = _YdlLog()
        opts = {
            **_base_opts(cookiefile=ck),
            "format": video_format,
            "outtmpl": str(target_dir / "video.%(ext)s"),
            "merge_output_format": "mp4",
            "writeinfojson": True,
            # 커스텀 로거로 콘솔은 조용히 유지하되 쿠키 만료 경고를 감지. warning()이
            # 호출되려면 no_warnings를 꺼야 한다(로거가 메시지를 흡수하므로 콘솔은 깔끔).
            "logger": ydl_log,
            "no_warnings": False,
        }
        try:
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.extract_info(url, download=True)
            except Exception as first:
                if not _is_pot_cold_timeout(first):
                    raise
                # 콜드 스타트 1회 실패 → 캐시가 더워진 상태로 즉시 재시도
                log.warning("PO Token 스크립트 콜드 스타트 타임아웃 — 재시도합니다: %s", first)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.extract_info(url, download=True)
        except Exception as e:
            # 주의: 예전에는 '쿠키가 있는데 403이면 곧 쿠키 만료'로 단정했는데, 이는 오진이었다.
            # 실제 403의 대부분은 PO Token 미발급 / progressive 포맷 소멸 / SABR 강제 때문이고,
            # 쿠키를 아무리 재발급해도 해결되지 않는다(쿠키 없이도 똑같이 403). 그래서 yt-dlp가
            # 쿠키 무효를 '명시적으로 경고한 경우'에만 쿠키 사유로 올리고, 나머지 403은
            # 원래 예외 그대로 올려 jobs.py가 실제 원인으로 분류하게 한다.
            if ydl_log.cookies_invalid:
                raise RuntimeError(
                    "YouTube account cookies are no longer valid - 쿠키가 만료/로테이션되어 "
                    "무효화되었습니다. 시크릿(Incognito) 창에서 쿠키를 재발급해 주세요.") from e
            raise


def _download_subtitles(url: str, target_dir: Path, langs: list[str] | None = None) -> None:
    """Best-effort subtitle download. Caller catches exceptions.
    *langs*는 _preferred_sub_langs()가 계산한 '원어 우선' 목록(없으면 기본값)."""
    with _cookie_copy() as ck:
        opts = {
            **_base_opts(cookiefile=ck),
            "skip_download": True,
            "outtmpl": str(target_dir / "video.%(ext)s"),
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": list(langs or SUB_LANGS),
            "subtitlesformat": "vtt",
            "sleep_interval_subtitles": 2,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)


def download(url: str, target_dir: Path, video_format: str = "best[ext=mp4]/best") -> dict[str, Any]:
    target_dir.mkdir(parents=True, exist_ok=True)

    video_format = _normalize_format(video_format)
    log.info("영상 포맷 선택자: %s", video_format)
    info = _download_video(url, target_dir, video_format)

    # 영상의 '원어' 자막을 최우선으로 받는다(언어학습 버전이 원어 스크립트를 써야 하므로).
    sub_langs = _preferred_sub_langs(info)
    log.info("자막 언어 우선순위: %s", sub_langs)

    subtitle_error: str | None = None
    try:
        _download_subtitles(url, target_dir, sub_langs)
    except Exception as exc:
        subtitle_error = str(exc)
        log.warning("subtitle pass failed (non-fatal): %s", exc)

    files: dict[str, str] = {}
    # 자막 파일 선택: sub_langs(원어 우선) 순서가 앞설수록 높은 점수.
    best_sub_rank = -1
    for p in target_dir.iterdir():
        name = p.name
        if name.startswith("video.") and p.suffix in {".mp4", ".webm", ".mkv", ".m4a"}:
            files["video"] = str(p)
        elif name.endswith(".vtt") or name.endswith(".srt"):
            n = name.lower()
            rank = -1
            for i, lang in enumerate(sub_langs):
                if f".{lang.lower()}." in n:
                    rank = len(sub_langs) - i  # 앞쪽 언어일수록 큰 값
                    break
            if rank > best_sub_rank:
                files["subtitle"] = str(p)
                best_sub_rank = rank
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

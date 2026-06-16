# [JINI+US] 유튜브 → 블로그 봇 — 개인 컴퓨터 설치 가이드

> 회사 보안(Symantec 등)이 깔린 PC에서는 텔레그램이 차단됩니다.
> **회사 보안이 없는 개인 컴퓨터**(가정용 인터넷)에서 아래대로 설치하세요.

## 동작 요약
모바일 텔레그램에 유튜브 URL 전송 → 이 컴퓨터가 다운로드 + 자막/요약 →
**`blog_long.html`(이미지 base64 내장)을 텔레그램으로 회신**. 영상 파일은 안 보냄.

---

## 1. 미리 설치할 것
- **Python 3.11+**  (`python3 --version`)
- **ffmpeg**
  - 맥:      `brew install ffmpeg`
  - 윈도우:  `choco install ffmpeg`  (또는 ffmpeg.org에서 받아 PATH 등록)
  - 리눅스:  `sudo apt install ffmpeg`
- **git**

## 2. 코드 받기
```bash
git clone https://github.com/herwoojin/yt-dlp-woojini.git
cd yt-dlp-woojini
```

## 3. 파이썬 환경 + 의존성
```bash
python3 -m venv .venv
# 맥/리눅스:
source .venv/bin/activate
# 윈도우(PowerShell):  .venv\Scripts\Activate.ps1

pip install -r app/requirements.txt
```
> `mlx-whisper`는 Apple Silicon 맥에서만 설치됩니다(다른 OS는 자동 건너뜀).
> 맥이 아니어도 유튜브 자막이 있으면 정상 동작합니다.

## 4. 환경설정(.env)
```bash
cp app/.env.example app/.env
```
`app/.env` 를 열어 **두 개만** 채우면 됩니다:
- `TELEGRAM_BOT_TOKEN=` → @BotFather에서 받은 토큰 (기존 `@jini_youtube_bot` 토큰 재사용 가능)
- `GEMINI_API_KEY=` → https://aistudio.google.com/apikey 의 키 (`AIza...`)

`TELEGRAM_ENABLED=true`, `ALLOW_INSECURE_AUTH=true`는 그대로 두세요.

## 5. 실행
```bash
cd app
../.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
# (가상환경 활성화 상태면 그냥)  python -m uvicorn backend.main:app --port 8000
```
로그에 `telegram bot polling started (resilient loop ...)` 가 보이면 봇이 켜진 것입니다.

## 6. 사용
모바일 텔레그램에서 봇(`@jini_youtube_bot`)에게:
- 유튜브 URL 전송 → 1~3분 뒤 `blog_long.html` 도착
- `살아있어?` → 서버 상태 확인
- `도움` → 사용법

---

## 항상 켜두기 (선택)
- **맥**: `app/scripts/` 의 LaunchAgent 방식 참고 (또는 그냥 터미널에서 5번 명령 실행 후 켜둠)
- 컴퓨터가 켜져 있고 인터넷이 되면 봇이 동작합니다. 자거나 꺼지면 봇도 멈춥니다.
- WiFi가 잠깐 끊겨도 자가복구 폴링이 수초 내 자동 재개합니다.

## 자주 막히는 것
| 증상 | 원인 / 해결 |
|---|---|
| 봇이 응답 없음 | 컴퓨터가 꺼졌거나, 네트워크가 텔레그램 차단(회사망/보안SW). 개인망에서 실행. |
| "blog_long.html 못 찾음" | `GEMINI_API_KEY`가 비었거나 무효 → .env 확인 |
| 다운로드 5%에서 실패 | 데이터센터/VPN IP 봇차단. 가정용 인터넷에서 실행하거나 `YT_DLP_COOKIES_FILE` 설정 |
| 자막 429 | (맥이면) Whisper로 자동 폴백. 그 외 OS는 잠시 후 재시도 |

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

## PO Token 공급자 (YouTube 403 방지 — 필수)

YouTube는 재생 URL에 **PO Token**을 요구한다. 없으면 영상/자막이 **403 Forbidden**으로 전부 실패한다.
`pip install bgutil-ytdlp-pot-provider`는 **파이썬 플러그인만** 깔고, 토큰을 실제로 만드는
**Node 생성기는 따로 받아야 한다**. (이게 빠져 있으면 403이 계속 난다.)

```bash
# pip으로 깔린 플러그인과 같은 버전 태그로 받아야 한다 (현재 1.3.1)
git clone --depth 1 --branch 1.3.1   https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git ~/bgutil-ytdlp-pot-provider
cd ~/bgutil-ytdlp-pot-provider/server
npm install --ignore-scripts   # --ignore-scripts: canvas 네이티브 빌드(Visual C++) 회피용
node ./node_modules/typescript/bin/tsc
```

경로는 반드시 `~/bgutil-ytdlp-pot-provider/server` 여야 한다 — 플러그인이 여기를 기본값으로 찾는다.
빌드되면 `server/build/generate_once.js`가 생기고 추가 설정 없이 자동으로 쓰인다.

확인:
```bash
node ~/bgutil-ytdlp-pot-provider/server/build/generate_once.js -c dQw4w9WgXcQ
# {"poToken":"...","expiresAt":"..."} 가 나오면 정상
# (stderr의 "Not implemented: HTMLCanvasElement's getContext()" 경고는 무시해도 된다)
```

> **반드시 HTTP 서버 모드로 쓸 것.** `start-backend.bat`이 4416 포트에 자동으로 띄운다.
> 수동 기동: `node ~/bgutil-ytdlp-pot-provider/server/build/main.js`
>
> 서버 없이 '스크립트' 공급자만 남으면 **콜드 스타트에 ~18초**가 걸리는데 플러그인의
> 버전확인 타임아웃이 15초라 터진다. 게다가 이 확인은 yt-dlp가 공급자를 훑는
> *제너레이터* 안에서 호출돼 예외가 `try/except`를 빠져나가 **작업 전체를 죽인다**
> (플러그인 1.3.1 / 2.0.1 공통 버그). 증상: `generate_once.js ... timed out after 15.0 seconds`.
> HTTP 공급자는 우선순위가 130(스크립트는 10/20)이라, 서버만 떠 있으면 스크립트는
> 호출조차 되지 않는다.

---

## yt-dlp는 자주 올려야 한다

YouTube가 PO Token/SABR/포맷 정책을 수시로 바꾸기 때문에, yt-dlp가 몇 달만 묵어도
`Requested format is not available` 또는 403으로 전부 실패한다. 증상이 보이면 먼저:

```bash
.venv/Scripts/python.exe -m pip install -U "yt-dlp[default]" yt-dlp-ejs
```

---

## 자주 막히는 것
| 증상 | 원인 / 해결 |
|---|---|
| 봇이 응답 없음 | 컴퓨터가 꺼졌거나, 네트워크가 텔레그램 차단(회사망/보안SW). 개인망에서 실행. |
| "blog_long.html 못 찾음" | `GEMINI_API_KEY`가 비었거나 무효 → .env 확인 |
| 다운로드 5%에서 실패 | 데이터센터/VPN IP 봇차단. 가정용 인터넷에서 실행하거나 `YT_DLP_COOKIES_FILE` 설정 |
| 전부 403 Forbidden | 쿠키 문제가 **아닐** 가능성이 높다. ① yt-dlp 업그레이드 ② PO Token 공급자(위 항목) 설치 확인 |
| `Requested format is not available` | yt-dlp가 낡음. progressive mp4가 사라져서 생김 → 업그레이드 |
| 자막 429 | (맥이면) Whisper로 자동 폴백. 그 외 OS는 잠시 후 재시도 |

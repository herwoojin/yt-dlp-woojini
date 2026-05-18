# yt-dlp web app

YouTube URL → 로컬에 영상/자막/스크립트(TXT) 저장 + Gemini로 시계열 목차, 짧은 요약, 이메일용 HTML, 블로그/카페용 장문 HTML 생성. 텔레그램 봇도 같은 파이프라인 사용.

```
[Netlify 프론트엔드 React]
        ↓ HTTPS (Firebase ID 토큰)
[로컬 FastAPI + 텔레그램 봇 스레드] ── yt-dlp ──→ 로컬 디스크
                                  └ Gemini API ─→ chapters.json / *.html / transcript.txt
```

## 폴더 구조

```
app/
├── backend/                   FastAPI (uvicorn으로 로컬 실행)
│   ├── main.py
│   ├── config.py             환경변수 + runtime_settings.json
│   ├── auth.py               Firebase ID 토큰 검증
│   ├── jobs.py               in-memory 작업 큐 + 단일 워커
│   ├── models.py
│   ├── routes/               /api/jobs, /api/settings, /api/files
│   └── services/             downloader / transcript / gemini / storage / telegram_bot
├── frontend/                  React + Vite + TS + Tailwind (Netlify 배포 대상)
├── frontend-html/             단일 파일 HTML 대안 (Firebase 없이 동작)
├── requirements.txt
├── .env.example
└── netlify.toml
```

## 1. 백엔드 (로컬 맥) 실행

```bash
cd app
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# .env 열어서 GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, FIREBASE_* 채우기
# 처음에는 ALLOW_INSECURE_AUTH=true 로 두고 동작 확인 후 false 로 전환 권장

uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

- 다운로드 경로 기본값: `~/yt-dlp-downloads/<job_id>/`
- 웹앱 ⚙️ 설정에서 경로 변경 가능 → `runtime_settings.json` 으로 저장됨

### Firebase Admin 키

Firebase Console → 프로젝트 설정 → 서비스 계정 → "새 비공개 키 생성" → JSON 다운로드.
`app/firebase-admin.json` 로 저장 후 `.env` 의 `FIREBASE_SERVICE_ACCOUNT_PATH=./firebase-admin.json`.

### Cloudflare Tunnel (Netlify 프론트가 백엔드를 찾을 수 있게)

```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:8000
# → https://xxx-xxx.trycloudflare.com 발급
```

이 URL을 Netlify의 `VITE_API_BASE_URL` 환경변수에 넣습니다.
백엔드 `.env`의 `ALLOWED_ORIGINS`에는 Netlify 도메인을 포함해야 CORS가 통과합니다.

## 2. 프론트엔드 로컬 개발

```bash
cd app/frontend
cp .env.example .env
# VITE_API_BASE_URL=http://localhost:8000
# VITE_ALLOW_INSECURE_AUTH=true   ← 로컬 개발은 우회
npm install
npm run dev    # http://localhost:5173
```

## 3. Netlify 배포

1. GitHub 레포에 `app/` 푸시 (이 레포의 루트가 `app/`이 아니면 `netlify.toml`의 `base`를 그대로 사용)
2. Netlify → New site → GitHub 연결
3. **Site settings → Environment variables**:
   - `VITE_API_BASE_URL` = `https://xxx-xxx.trycloudflare.com`
   - `VITE_FIREBASE_API_KEY` / `AUTH_DOMAIN` / `PROJECT_ID` / `APP_ID`
   - `VITE_ALLOW_INSECURE_AUTH=false`
4. Deploy

## 4. 텔레그램 봇

`.env` 에 `TELEGRAM_BOT_TOKEN` 만 채우면 FastAPI 기동 시 자동으로 백그라운드 스레드에서 polling 시작.
50MB 이하 영상은 텔레그램으로도 전송, 모든 산출물은 항상 로컬 디스크에 저장.

## 5. 단일 파일 HTML 대안 사용

`app/frontend-html/index.html`를 그대로 브라우저로 열거나, Netlify에 별도 사이트로 올려도 됩니다.
ALLOW_INSECURE_AUTH=true 일 때만 동작합니다.

## 산출물 (각 job 디렉토리)

| 파일                    | 설명 |
|------------------------|------|
| `video.mp4`            | yt-dlp가 받은 영상 본체 |
| `*.vtt`                | 자막 (한/영/일/중 자동) |
| `transcript.txt`       | 가장 작은 원본 스크립트 (타임스탬프 제거, 중복 제거) |
| `transcript_timed.txt` | 타임스탬프 포함 (Gemini 챕터 생성용) |
| `chapters.json`        | 시계열 목차 (Gemini 생성) |
| `summary_short.html`   | 짧은 요약 HTML |
| `email_readable.html`  | 이메일 본문에 붙여넣기 좋은 가독성 HTML |
| `blog_long.html`       | 블로그/카페용 장문 HTML |
| `job.json`             | 작업 메타데이터 |

## 모델 선택

- 기본: `gemini-2.5-flash` (빠르고 저렴)
- "Pro" 선택 시: `gemini-2.5-pro` (고품질, 느림)
- `.env` 의 `DEFAULT_GEMINI_MODEL` / `PRO_GEMINI_MODEL` 로 교체 가능

## 자주 묻는 것

- **자막이 없는 영상은?** Gemini 단계가 "[자막 없음]" 상태로 마무리됩니다. 추후 Whisper 연동 가능.
- **여러 작업 동시 처리?** 현재 워커는 1개 (디스크/quota 보호). asyncio.Queue → TaskGroup으로 바꾸면 병렬화 가능.
- **Firestore 메타 저장은?** 현재는 로컬 `job.json` 만. 필요하면 `jobs.py._persist`에서 firestore admin도 호출하도록 확장.

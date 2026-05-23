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

## 6. 상시 운영 (언제 어디서든 접근)

맥이 켜져 있는 한 어디서든 접속 가능하도록 launchd로 uvicorn을 부팅 시 자동 시작합니다.
공개 URL 발급 방식은 둘 중 선택:

| 옵션 | 영구 URL | sudo 필요 | 가입 | 추천 |
|------|:--:|:--:|------|------|
| **A. cloudflared quick tunnel** | ❌ 재시작 시 변경 | ❌ | 불필요 | 즉시 동작 (스크립트로 자동) |
| **B. Tailscale Funnel** | ✅ 고정 `*.ts.net` | ✅ 설치 시 1회 | Tailscale 계정 (Google/GitHub) | Netlify 환경변수 안 바꿔도 됨 |

### 옵션 A — Cloudflared (즉시 동작, sudo 없음)

```bash
brew install cloudflared              # 1회, sudo 불필요
bash app/scripts/setup-cloudflared.sh # launchd 등록 + URL 발급
bash app/scripts/get-url.sh           # 현재 URL 확인 (필요시마다)
```

이 스크립트가:
- `~/Library/LaunchAgents/com.user.ytdlp-backend.plist` (uvicorn)
- `~/Library/LaunchAgents/com.user.ytdlp-tunnel.plist` (cloudflared)
- 부팅·로그인·크래시 시 자동 재시작 (KeepAlive)

⚠️ **URL이 재시작 시 바뀜.** Netlify의 `VITE_API_BASE_URL`을 그때마다 업데이트해야 합니다.
이게 번거로우면 옵션 B로 가세요.

### 옵션 B — Tailscale Funnel (영구 URL, 사용자 1회 설정)

### 사용자가 직접 해야 할 1회 단계

```bash
# 1) Tailscale 설치 (비밀번호 1회 입력)
brew install --cask tailscale-app

# 2) /Applications/Tailscale.app 실행 → 메뉴바 → "Log in..."
#    브라우저에서 Tailscale 계정 로그인 (Google/GitHub 가능, 개인 사용 무료)

# 3) Funnel 활성화 (admin 콘솔, 1회)
#    https://login.tailscale.com/admin/dns      → HTTPS Certificates Enable
#    https://login.tailscale.com/admin/acls/file → ACL에 아래 추가:
#      "nodeAttrs": [{"target": ["autogroup:member"], "attr": ["funnel"]}]
```

### 자동 설정 스크립트

```bash
bash app/scripts/setup-anywhere.sh
```

이 스크립트가 자동으로:
- launchd plist (`~/Library/LaunchAgents/com.user.ytdlp-backend.plist`) 생성
- 부팅 시 uvicorn 자동 시작 + 크래시 시 자동 재시작
- Tailscale Funnel을 `--bg`로 영구 활성화 (재부팅 후 자동 복원)
- 공개 URL 출력 (Netlify의 `VITE_API_BASE_URL`에 넣을 값)

### 상태 확인 / 해제

```bash
bash app/scripts/status-anywhere.sh    # backend + funnel + 외부 도달 테스트
bash app/scripts/stop-anywhere.sh      # 자동시작 해제 (데이터는 보존)
```

### 맥 절전 설정 권장

맥이 sleep으로 빠지면 백엔드가 멈춥니다. 데스크톱이거나 전원 연결 중이면:

```bash
# 전원 연결 시 절대 sleep 안 함
sudo pmset -c sleep 0 disksleep 0 displaysleep 30

# 배터리 사용 시는 평소처럼 (옵션)
sudo pmset -b sleep 10 displaysleep 5
```

### 한계 및 대안

- **맥을 꺼야 할 때** (출장, 정전 등) → 그 시간 동안은 접속 불가. 더 강한 24/7이 필요하면
  옵션 C (클라우드 큐 + 맥 워커 하이브리드)로 확장 필요.
- **Tailscale Free 플랜 제한** — Funnel은 무료, 모든 기기에서 접근 가능.
- **로그 위치** — `~/Library/Logs/ytdlp-backend.{out,err}.log`

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

# TRD — yt-dlp web app

> Technical Requirements Document
> 마지막 갱신: 2026-05-20

## 1. 아키텍처 개요

```
┌─────────────────────────────────────────────────────────────┐
│  외부 (휴대폰 / 다른 PC)                                      │
└──────────────────┬──────────────────────┬──────────────────┘
                   │                      │
                   ▼                      ▼
        ┌──────────────────┐    ┌──────────────────┐
        │   Netlify CDN    │    │  텔레그램 클라이언트 │
        │  (React 정적 호스팅)│    │                  │
        └─────────┬────────┘    └─────────┬────────┘
                  │ HTTPS                  │
                  ▼                        │
        ┌────────────────────────────┐    │
        │ cloudflared / Tailscale     │    │
        │ Funnel (공개 URL)            │    │
        └─────────┬───────────────────┘    │
                  │ 127.0.0.1:8000          │
                  ▼                         │
┌─────────────────────────────────────────┐ │
│  맥북 (사용자 PC)                          │ │
│  ┌────────────────────────────────────┐ │ │
│  │ FastAPI (uvicorn)                  │ │ │
│  │  ├─ /api/jobs, /api/settings, etc. │ │ │
│  │  ├─ Telegram bot thread ◄──────────┼─┘ │
│  │  └─ Job worker (asyncio.Queue)     │   │
│  └──────────────┬─────────────────────┘   │
│                 │                          │
│    ┌────────────┴───────────────┐         │
│    ▼            ▼               ▼         │
│  yt-dlp     Gemini API      Firebase      │
│  + ffmpeg   (google-genai)  Admin SDK     │
│                                            │
│  로컬 디스크: ~/yt-dlp-downloads/<job_id>/ │
│    ├─ video.mp4                            │
│    ├─ transcript.txt                       │
│    ├─ chapters.json                        │
│    ├─ summary_short.html                   │
│    ├─ email_readable.html                  │
│    ├─ blog_long.html                       │
│    └─ job.json                             │
└────────────────────────────────────────────┘
```

## 2. 기술 스택

| 계층 | 선택 | 이유 |
|------|------|------|
| **프론트엔드** | React 18 + Vite + TypeScript + Tailwind CSS | 모바일 반응형 + 빠른 빌드 + Netlify 친화 |
| **백엔드** | Python 3.12+ FastAPI + uvicorn | yt-dlp가 Python 라이브러리, async I/O 친화 |
| **잡 큐** | `asyncio.Queue` (in-memory, 단일 워커) | 가벼움, 디스크/쿼터 보호. Redis/Celery 오버킬 |
| **영상 다운로드** | yt-dlp 2026.x | 가장 활발한 유튜브 다운로더 |
| **자막→텍스트** | yt-dlp `writesubtitles` + 자체 VTT 파서 | 추가 의존성 없음. Whisper는 향후 옵션 |
| **LLM** | google-genai SDK + Gemini 2.5 Flash / 3 Pro | 무료 quota 충분, JSON 출력 안정 |
| **인증** | Firebase Authentication (Google OAuth) | 무료, 간단, ID 토큰 표준 |
| **DB** | 로컬 JSON 파일 (`job.json`) | 단일 사용자 가정 → DB 불필요. Firestore는 옵션 |
| **터널** | cloudflared quick tunnel (기본) / Tailscale Funnel (영구 URL) | 양쪽 다 무료, 도메인 구매 불요 (후자) |
| **봇** | pyTelegramBotAPI (telebot) | 동기 polling, FastAPI와 스레드 격리 |
| **자동 시작** | macOS launchd (사용자 LaunchAgent) | sudo 불필요, KeepAlive 내장 |
| **정적 호스팅** | Netlify | 무료, GitHub 자동 빌드, 환경변수 UI |
| **컨테이너** | (없음) | 개인 맥 직접 실행. 다중 인스턴스 불필요 |

## 3. 모듈 구조

```
app/
├── backend/
│   ├── main.py                # FastAPI 진입점 + lifespan (텔레그램 스레드 부팅)
│   ├── config.py              # 환경변수 + runtime_settings.json (저장 경로)
│   ├── auth.py                # Firebase ID 토큰 검증 (UserDep)
│   ├── models.py              # Pydantic: JobCreate, JobInfo, Settings
│   ├── jobs.py                # JobRegistry: in-memory 큐 + 단일 워커
│   ├── routes/
│   │   ├── jobs.py            # GET/POST /api/jobs, GET /api/jobs/{id}
│   │   ├── settings.py        # GET/PUT /api/settings
│   │   └── files.py           # GET /api/files/{job_id}/{filename}
│   └── services/
│       ├── downloader.py      # yt-dlp 래퍼 (2패스: 영상 → 자막 best-effort)
│       ├── transcript.py      # VTT/SRT → transcript.txt + transcript_timed.txt
│       ├── gemini.py          # 4종 호출: chapters/summary/email/blog
│       ├── storage.py         # 디렉토리/파일 헬퍼
│       └── telegram_bot.py    # 별도 스레드 polling, 같은 JobRegistry 사용
│
├── frontend/
│   └── src/
│       ├── main.tsx           # React 진입
│       ├── App.tsx            # 라우팅, 헤더, 모달 토글
│       ├── firebase.ts        # Google OAuth + ID 토큰 fetch
│       ├── api.ts             # fetch 래퍼 (자동 Bearer 헤더)
│       └── components/
│           ├── Login.tsx
│           ├── UrlForm.tsx
│           ├── JobList.tsx
│           ├── JobDetail.tsx
│           ├── SettingsPanel.tsx
│           └── HelpPanel.tsx  # 6단계 셋업 가이드
│
├── frontend-html/index.html   # 단일 파일 HTML 대안 (Firebase 없이)
│
├── scripts/
│   ├── install.sh             # 새 사용자용 1줄 셋업
│   ├── setup-cloudflared.sh   # quick tunnel + launchd 등록
│   ├── setup-anywhere.sh      # Tailscale Funnel + launchd 등록
│   ├── status-anywhere.sh     # 전체 상태 점검
│   ├── stop-anywhere.sh       # 자동시작 해제
│   └── get-url.sh             # 현재 활성 공개 URL
│
└── dist/
    └── yt-dlp\ webapp.app/    # 더블클릭 런처 (Info.plist + launcher 셸 스크립트)
```

## 4. 외부 API 의존

| 서비스 | 용도 | 비용 | 비고 |
|-------|------|------|------|
| **Gemini API** | 목차/요약/HTML 생성 | 무료 (관대한 quota) | https://aistudio.google.com/app/apikey |
| **Firebase Auth** | Google 로그인 + ID 토큰 | 무료 (50k MAU 까지) | 서비스 계정 JSON 필요 (백엔드) |
| **Telegram Bot API** | 봇 polling, 메시지/파일 전송 | 무료 | @BotFather에서 토큰 발급, 50MB 업로드 제한 |
| **Cloudflare Tunnel** | 공개 URL (quick) | 무료 | 도메인 등록 시 영구 URL 가능 |
| **Tailscale Funnel** | 공개 URL (영구) | 무료 (Personal Plan) | 1회 가입 + ACL 설정 |
| **Netlify** | 프론트 정적 호스팅 | 무료 (월 100GB) | GitHub 자동 빌드 |

## 5. 백엔드 API 스펙

| Method | Path | 설명 | 인증 |
|--------|------|------|------|
| GET | `/health` | 헬스체크 | 없음 |
| GET | `/api/jobs` | 현재 사용자의 잡 목록 | Firebase ID 토큰 |
| POST | `/api/jobs` | 새 잡 등록 `{url, quality, video_format?}` | 동일 |
| GET | `/api/jobs/{id}` | 잡 상세 (진행상황/산출물/챕터) | 동일 |
| GET | `/api/settings` | 저장 경로 + 모델 + 텔레그램 상태 | 동일 |
| PUT | `/api/settings` | 저장 경로 변경 `{download_dir}` | 동일 |
| GET | `/api/files/{job_id}/{filename}` | 산출물 파일 다운로드 | 동일 |

응답 모델은 [models.py](../backend/models.py) 참고.

## 6. 잡 처리 파이프라인 상세

```
[POST /api/jobs] → JobRegistry.submit() → asyncio.Queue.put()
        ↓
[worker_loop] → run_job():
  1. status=DOWNLOADING (progress 0.05)
     → downloader.download() (2-pass: 영상 → 자막 best-effort)
  2. status=TRANSCRIBING (progress 0.4)
     → transcript.build_transcript_txt() (VTT 파싱, 중복 제거)
  3. 자막 없으면 → status=DONE (early return, 영상만 보존)
  4. status=GENERATING (progress 0.6)
     → gemini.generate_all():
       - generate_chapters (timed transcript 기반)
       - generate_short_summary_html
       - generate_email_html (목차 + 자막 발췌)
       - generate_blog_html (도입/본문/결론)
  5. Gemini 실패 시 → status=DONE (영상/스크립트는 보존, Gemini 산출물만 없음)
  6. status=DONE (progress 1.0)
        ↓
[디스크에 job.json 갱신 + JobInfo in-memory 캐시]
```

## 7. 실패 처리

| 실패 지점 | 처리 |
|----------|------|
| YouTube 429 (자막) | 잡 죽이지 않음. 자막 없는 상태로 진행 후 Gemini 건너뜀 |
| YouTube 403 (영상) | 잡 `failed` 마킹. 사용자가 쿠키 등록 후 재시도 |
| Gemini 400 (잘못된 키) | 잡 `done` 마킹 (영상/스크립트는 보존). 메시지로 사유 표시 |
| 백엔드 크래시 | launchd가 10초 ThrottleInterval 후 재시작 |
| 터널 크래시 | launchd가 KeepAlive로 즉시 재시작 (단, quick tunnel URL은 새로 발급) |
| 디스크 풀 | yt-dlp가 IOError 던짐 → 잡 `failed` |

## 8. 보안 고려사항

1. **백엔드는 127.0.0.1 only 바인딩** → 같은 네트워크의 다른 기기는 직접 접근 불가
2. **모든 외부 접근은 터널을 통해서만** + **Firebase ID 토큰 검증** (`ALLOW_INSECURE_AUTH=true`일 땐 우회 → 개발 전용)
3. **파일 다운로드 엔드포인트** → `job_id`로 디렉토리 격리 + path traversal 차단 (`startswith` 체크)
4. **CORS** → `ALLOWED_ORIGINS` 화이트리스트만 허용
5. **`.env`/`firebase-admin.json`/`runtime_settings.json`** 모두 `.gitignore`로 git 차단
6. **텔레그램 봇** → 누구나 메시지 가능. 사용자 ID 화이트리스트는 MVP 밖 (향후 추가)

## 9. 환경변수 정리

### 백엔드 (`app/.env`)

| Key | 기본값 | 용도 |
|-----|--------|------|
| `GEMINI_API_KEY` | (빈 값) | Gemini API 호출. 비우면 Gemini 단계 건너뜀 |
| `DEFAULT_GEMINI_MODEL` | `gemini-2.5-flash` | Flash 모드 기본 |
| `PRO_GEMINI_MODEL` | `gemini-3-pro-preview` | Pro 모드 |
| `DOWNLOAD_DIR` | `~/yt-dlp-downloads` | 저장 루트 (UI에서 변경 가능) |
| `YT_DLP_COOKIES_FILE` | (빈 값) | 봇 탐지 회피용 쿠키 경로 |
| `TELEGRAM_BOT_TOKEN` | (빈 값) | BotFather 토큰. 비우면 봇 미가동 |
| `TELEGRAM_ENABLED` | `true` | 명시적 비활성화 시 `false` |
| `FIREBASE_PROJECT_ID` | (빈 값) | Firebase 프로젝트 ID |
| `FIREBASE_SERVICE_ACCOUNT_PATH` | `./firebase-admin.json` | 서비스 계정 JSON |
| `ALLOW_INSECURE_AUTH` | `true` (dev) / `false` (prod) | 인증 우회 (개발용) |
| `ALLOWED_ORIGINS` | `http://localhost:5173,...` | CORS 화이트리스트 |

### 프론트 (`app/frontend/.env` → Netlify env vars)

| Key | 기본값 | 용도 |
|-----|--------|------|
| `VITE_API_BASE_URL` | `http://localhost:8000` | 백엔드 주소 (Netlify는 터널 URL) |
| `VITE_FIREBASE_API_KEY` | (빈 값) | Firebase Web SDK |
| `VITE_FIREBASE_AUTH_DOMAIN` | (빈 값) | 동일 |
| `VITE_FIREBASE_PROJECT_ID` | (빈 값) | 동일 |
| `VITE_FIREBASE_APP_ID` | (빈 값) | 동일 |
| `VITE_ALLOW_INSECURE_AUTH` | `true` (dev) / `false` (prod) | 우회 모드 |

## 10. 자동 시작 (launchd)

- `~/Library/LaunchAgents/com.user.ytdlp-backend.plist` → uvicorn
- `~/Library/LaunchAgents/com.user.ytdlp-tunnel.plist` → cloudflared
- 옵션: `KeepAlive` (SuccessfulExit=false, Crashed=true)
- 옵션: `ThrottleInterval: 10` (재시작 폭주 방지)
- 옵션: `RunAtLoad: true` (등록 즉시 시작)

## 11. 빌드 / 배포

| 대상 | 빌드 | 배포 |
|------|------|------|
| **프론트엔드** | `npm run build` → `dist/` | Netlify 자동 (GitHub push 트리거, [netlify.toml](../netlify.toml)) |
| **백엔드** | (없음, 인터프리터) | 로컬 실행. `pip install -r requirements.txt` |
| **`.app` 런처** | 디렉토리 구조 + plist + 셸 스크립트 수동 작성 | `cp -R app/dist/yt-dlp\ webapp.app /Applications/` |

## 12. 테스트 전략 (MVP는 수동)

| 레벨 | 방법 |
|------|------|
| **백엔드 단위** | (없음, MVP). 향후 pytest |
| **백엔드 통합** | `curl http://localhost:8000/health`, `bash scripts/status-anywhere.sh` |
| **E2E** | 실제 YouTube URL ("Me at the zoo")로 잡 등록 → 산출물 검증 |
| **프론트** | `npm run build` (TS 컴파일 검증) + 수동 브라우저 테스트 |

## 13. 모니터링 / 로그

- `~/Library/Logs/ytdlp-backend.{out,err}.log` — uvicorn stdout/stderr
- `~/Library/Logs/ytdlp-tunnel.{out,err}.log` — cloudflared
- `~/Library/Logs/ytdlp-launcher.log` — .app 런처 한정
- 잡별 로그는 `~/yt-dlp-downloads/<id>/job.json` 의 `error` 필드

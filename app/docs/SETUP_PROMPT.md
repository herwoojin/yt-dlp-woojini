# SETUP_PROMPT — AI에게 똑같이 만들어달라고 줄 프롬프트

> 이 파일 내용 전체를 복사해서 Claude Code / Antigravity / Cursor 등 AI 에이전트에게 붙여넣으면, 이 프로젝트와 동일한 구조를 처음부터 다시 만들어줍니다.
> 마지막 갱신: 2026-05-20

---

## 사용 방법

1. AI 에이전트의 채팅창에 아래 "프롬프트 시작" 이후 전체를 복사해서 붙여넣기
2. AI가 단계별로 파일을 생성/수정
3. 중간에 자기 환경(GEMINI_API_KEY, 텔레그램 토큰 등)을 채워넣으라는 안내가 나옴

---

## 프롬프트 시작

---

당신은 **yt-dlp 기반 풀스택 웹앱**을 처음부터 구축해주는 시니어 풀스택 엔지니어입니다.

이 프로젝트의 **목적**:
- YouTube URL 하나 → 영상 다운로드 + Gemini로 시계열 목차/짧은 요약/이메일 HTML/블로그 HTML 생성
- 모든 결과물은 사용자 맥에 로컬 저장
- 모바일 반응형 웹페이지 (Netlify 호스팅) + 텔레그램 봇 둘 다 같은 백엔드 사용
- 휴대폰에서도 어디서든 접근 (cloudflared 터널)
- 맥 부팅 시 자동 시작 (launchd)

### 사용자 컴퓨터 환경
- macOS 12 이상 (Apple Silicon 또는 Intel)
- Python 3.12+, Node 22+, Homebrew, ffmpeg, git, brew install 가능
- 사용자가 직접 발급해야 할 외부 키: Gemini API, (옵션) 텔레그램 봇 토큰, (옵션) Firebase 프로젝트

### 만들어야 할 디렉토리 구조

```
app/
├── backend/
│   ├── __init__.py
│   ├── main.py              FastAPI 진입 + lifespan에서 텔레그램 봇 스레드 부팅
│   ├── config.py            환경변수 + runtime_settings.json (저장 경로 동적 변경)
│   ├── auth.py              Firebase ID 토큰 검증 (ALLOW_INSECURE_AUTH 우회 옵션)
│   ├── jobs.py              JobRegistry (in-memory dict + asyncio.Queue 단일 워커)
│   ├── models.py            Pydantic v2: JobInfo, JobArtifact, JobCreateRequest, SettingsResponse
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── jobs.py          GET/POST /api/jobs, GET /api/jobs/{id}
│   │   ├── settings.py      GET/PUT /api/settings
│   │   └── files.py         GET /api/files/{job_id}/{filename} (path traversal 차단)
│   └── services/
│       ├── __init__.py
│       ├── downloader.py    yt-dlp 2-pass: 영상 본체 → 자막 best-effort (실패해도 잡 안 죽임)
│       ├── transcript.py    VTT/SRT 파싱 → transcript.txt + transcript_timed.txt
│       ├── gemini.py        google-genai: chapters/short/email/blog 4종 생성. Pro 모드 = Gemini 3 Pro
│       ├── storage.py       디렉토리 헬퍼
│       └── telegram_bot.py  pyTelegramBotAPI, 별도 스레드, run_coroutine_threadsafe로 메인 루프와 통신
│
├── frontend/                React + Vite + TypeScript + Tailwind CSS
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json        반드시 noEmit: true (tsc는 타입체크 전용)
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── index.html           viewport-fit=cover, 모바일 반응형
│   ├── .env.example
│   └── src/
│       ├── main.tsx
│       ├── App.tsx          헤더(가이드/설정/로그아웃) + 라우팅
│       ├── index.css        Tailwind imports + Pretendard/Noto Sans KR
│       ├── vite-env.d.ts    ImportMetaEnv 타입 선언 (없으면 npm run build 실패)
│       ├── firebase.ts      Google OAuth + ID 토큰 fetch, INSECURE_AUTH 모드 지원
│       ├── api.ts           fetch 래퍼 (Bearer 자동 첨부)
│       └── components/
│           ├── Login.tsx
│           ├── UrlForm.tsx     URL 입력 + Flash/Pro 토글 + 등록
│           ├── JobList.tsx     모바일 카드 UI, 진행상황 바
│           ├── JobDetail.tsx   목차 + 산출물 다운로드 + HTML 미리보기 모달
│           ├── SettingsPanel.tsx  저장 경로 + 모델 정보
│           └── HelpPanel.tsx   6단계 셋업 가이드 (Gemini/텔레그램/.env 편집/재시작/Netlify/문제해결), 복사 버튼 + 외부 링크
│
├── frontend-html/index.html   단일 파일 HTML 대안 (Firebase 없이, dialog 기반)
│
├── scripts/
│   ├── install.sh           macOS용 한 줄 설치 (brew + venv + pip + .env 스캐폴드 + 선택 launchd)
│   ├── setup-cloudflared.sh launchd plist 2개 작성 → uvicorn + cloudflared quick tunnel
│   ├── setup-anywhere.sh    Tailscale Funnel 영구 URL 옵션 (사용자 수동 사전 설정 필요)
│   ├── status-anywhere.sh   launchd + /health + 공개 URL + 외부 도달 테스트
│   ├── stop-anywhere.sh     자동시작 해제 (데이터 보존)
│   └── get-url.sh           현재 활성 cloudflared URL 추출
│
├── dist/
│   └── yt-dlp\ webapp.app/   macOS .app 번들 (Info.plist + Contents/MacOS/launcher 셸 스크립트)
│                             더블클릭 시 osascript dialog로 친절한 안내
│
├── docs/
│   ├── PRD.md               제품 요구사항
│   ├── TRD.md               기술 요구사항
│   ├── ERD.md               데이터 모델
│   ├── TASKS.md             단계별 체크리스트
│   ├── GUIDE.md             사용자 가이드
│   └── SETUP_PROMPT.md      (이 파일 자체)
│
├── requirements.txt         fastapi, uvicorn[standard], python-dotenv, pydantic, yt-dlp,
│                            pyTelegramBotAPI, google-genai, firebase-admin
├── .env.example
├── .gitignore               .env, firebase-admin.json, runtime_settings.json, node_modules/, dist/, .venv/, *.tsbuildinfo, src/**/*.js
├── netlify.toml             base=app/frontend, command="npm install && npm run build", publish=app/frontend/dist, SPA redirect
└── README.md
```

### 핵심 동작 명세

**파이프라인** (`jobs.py` worker_loop):
1. `status=DOWNLOADING` → `downloader.download()` (영상 다운로드)
2. `status=TRANSCRIBING` → `transcript.build_transcript_txt()` (자막 → txt)
3. 자막 없으면 → `status=DONE` (영상만 보존, Gemini 건너뜀, **잡은 success로 마감**)
4. `status=GENERATING` → `gemini.generate_all()` (4종 HTML/JSON)
5. Gemini 실패해도 → `status=DONE` (graceful fallback, 영상/스크립트는 보존)

**자막 다운로드 전략** (중요):
- 1패스: 영상만 (실패 시 잡 fail)
- 2패스: 자막 (`ko`, `en` 만, `sleep_interval_subtitles=2`, 실패해도 잡 진행)
- 이유: 5개 언어 자막을 자동+수동 모두 받으면 YouTube가 429 자주 뱉음

**Gemini 모델 기본값**:
- DEFAULT_GEMINI_MODEL=gemini-2.5-flash
- PRO_GEMINI_MODEL=gemini-3-pro-preview (모델 ID는 변경 가능, .env에서)

**자동 시작** (launchd, sudo 불필요, 사용자 LaunchAgent):
- `~/Library/LaunchAgents/com.user.ytdlp-backend.plist` → uvicorn
- `~/Library/LaunchAgents/com.user.ytdlp-tunnel.plist` → cloudflared
- 옵션: `RunAtLoad=true`, `KeepAlive={SuccessfulExit:false, Crashed:true}`, `ThrottleInterval=10`

**보안**:
- 백엔드는 `127.0.0.1` only 바인딩
- 외부 접근은 터널 + Firebase ID 토큰 검증
- 파일 엔드포인트는 path traversal 차단 (`resolve().startswith()` 체크)
- `.env`, `firebase-admin.json`, `runtime_settings.json` 모두 `.gitignore`

**`.app` 런처 동작**:
- 이미 떠 있으면 → 상태 dialog (URL 복사 / 브라우저 열기 / 로그 보기 / 종료)
- 안 떠 있으면 → "시작" 버튼 → setup-cloudflared.sh 실행 → 성공 dialog
- 의존성 없으면 → 친절한 에러 dialog

### 작업 순서 (이 순서대로 만들어주세요)

1. **디렉토리 구조 생성**
2. **백엔드 코어** — config, models, auth, jobs (사용자에게 디자인 결정 보고)
3. **백엔드 services** — downloader, transcript, gemini, storage, telegram_bot
4. **백엔드 routes** — jobs, settings, files
5. **백엔드 설정** — requirements.txt, .env.example, .gitignore, main.py
6. **프론트엔드 스캐폴드** — package.json, vite/ts/tailwind 설정
7. **프론트엔드 컴포넌트** — App, Login, UrlForm, JobList, JobDetail, SettingsPanel, HelpPanel
8. **단일 HTML 대안** — frontend-html/index.html
9. **스크립트** — install.sh, setup-cloudflared.sh, status-anywhere.sh, get-url.sh, stop-anywhere.sh
10. **.app 런처** — dist/yt-dlp\ webapp.app/ (Info.plist + launcher)
11. **문서** — PRD, TRD, ERD, TASKS, GUIDE, SETUP_PROMPT (이 파일)
12. **Netlify 설정** — netlify.toml
13. **검증** — backend 구문/임포트 점검, `npm run build` 통과, E2E 잡 1개 등록

### 검증 기준

- `cd app && python3 -m compileall -q backend` → 에러 없음
- `python -c "from backend import main; print(main.app.title)"` → "yt-dlp web app"
- `cd app/frontend && npm install && npm run build` → 성공, `dist/` 생성
- `curl http://localhost:8000/health` → `{"status":"ok"}`
- 짧은 YouTube 영상 (예: `jNQXAC9IVRw`, 19초)으로 잡 등록 → `done` 상태 + 영상/transcript 파일 존재

### 마지막 단계 — 사용자 안내 출력

모든 파일 생성 끝나면 다음 안내를 한국어로 명확하게 출력:

```
✅ 구축 완료. 다음 단계:

1. Gemini API 키 발급
   https://aistudio.google.com/app/apikey → Create API key → 키 복사

2. app/.env 편집
   open -a TextEdit app/.env
   - GEMINI_API_KEY=발급받은_키
   - TELEGRAM_BOT_TOKEN=BotFather에서_받은_토큰 (선택)

3. 백엔드 시작
   bash app/scripts/setup-cloudflared.sh
   → 출력 마지막 줄에 공개 URL 표시됨

4. 검증
   bash app/scripts/status-anywhere.sh

5. Netlify 배포
   docs/GUIDE.md 의 "4. 웹페이지 사용" 섹션 참고

6. 더블클릭 런처 사용
   cp -R "app/dist/yt-dlp webapp.app" /Applications/
   → Spotlight에서 "yt-dlp" 검색
```

### 주의사항

- 코드 사이닝은 안 함 (Apple Developer 멤버십 없는 사용자 가정). .app 첫 실행 시 우클릭→열기 안내 필수.
- 다른 사람한테 그대로 배포 불가능 — 경로/키 자기 환경에 맞게 채워야 함. 그래서 install.sh를 만든 것.
- 영상/Gemini 산출물은 **로컬에만** 저장. 클라우드 저장 추가하면 PRD 요구사항 위반.
- 백엔드는 `--reload` 없이 운영용 plist로 띄움. 개발 중에는 따로 `uvicorn ... --reload`.

---

## 프롬프트 끝

---

## 사용 후 점검 체크리스트

AI가 작업을 끝낸 후 사용자가 직접 확인할 것:

- [ ] `app/` 디렉토리 구조가 위 명세와 일치
- [ ] `app/.gitignore`에 `.env`, `firebase-admin.json`, `node_modules/` 등 모두 포함
- [ ] `python3 -m compileall -q app/backend` → 에러 없음
- [ ] `cd app/frontend && npm run build` → 에러 없음
- [ ] `app/scripts/*.sh` 모두 `+x` 권한
- [ ] `app/dist/yt-dlp webapp.app/Contents/MacOS/launcher` `+x` 권한
- [ ] `docs/` 안에 6개 문서 모두 존재
- [ ] 첫 잡 (`curl -X POST http://localhost:8000/api/jobs -d '{"url":"https://youtu.be/jNQXAC9IVRw","quality":"flash"}'`) 정상 `done`

---

## 트러블슈팅 (AI가 자주 헤매는 부분)

1. **`tsc -b`가 `.tsx` 옆에 `.js`를 토함** → `tsconfig.json`에 `noEmit: true` 필수
2. **`import.meta.env` TS 에러** → `src/vite-env.d.ts` 파일에 `ImportMetaEnv` 인터페이스 선언
3. **자막 429로 잡 전체 실패** → downloader.py를 2패스로 (영상 1번 호출, 자막 2번째 호출, 자막 실패는 catch)
4. **Gemini 호출 모든 잡 실패** → API 키 없을 때 graceful fallback (잡 상태 done + 메시지로 사유 표시)
5. **set -e + pipefail + launchctl list | grep**의 SIGPIPE → status 스크립트에서 `LIST=$(launchctl list)` 후 변수 grep
6. **Pydantic v1 vs v2** → `model_dump_json()`, `model_dump()` 등 v2 메서드 사용

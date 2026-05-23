# TASKS — yt-dlp web app 구축/설치 작업 분해

> 단계별 체크리스트. 처음부터 끝까지 따라가면 완전한 환경이 구성됩니다.
> 마지막 갱신: 2026-05-20

## Phase 0 — 사전 준비 (5분)

- [ ] **0.1** macOS 12 이상 확인 (`sw_vers`)
- [ ] **0.2** Homebrew 설치 — `which brew` 또는 https://brew.sh
- [ ] **0.3** Git 설치 — `which git` (보통 Xcode CLT가 같이 제공)
- [ ] **0.4** Google 계정 (Gemini API 키 발급용)
- [ ] **0.5** GitHub 계정 (Netlify 연동용)
- [ ] **0.6** (선택) Cloudflare 계정 (영구 URL 원할 때)
- [ ] **0.7** (선택) Tailscale 계정 (영구 URL 원할 때)
- [ ] **0.8** (선택) 텔레그램 계정 (봇 사용 시)

## Phase 1 — 코드/의존성 (10분)

- [ ] **1.1** 레포 clone
  ```bash
  git clone https://github.com/herwoojin/yt-dlp-woojini.git ~/yt-dlp
  cd ~/yt-dlp
  ```
- [ ] **1.2** install.sh 한 줄 실행 (모든 의존성 자동)
  ```bash
  bash app/scripts/install.sh
  ```
  자동 처리되는 것:
  - `brew install ffmpeg cloudflared`
  - `python3 -m venv .venv` + `pip install -r requirements.txt`
  - `app/.env`, `app/frontend/.env` 스캐폴드 (있으면 보존)
  - (선택) 프론트 `npm install`
  - (선택) launchd 자동시작 등록
- [ ] **1.3** 설치 검증
  ```bash
  source .venv/bin/activate
  python -c "import fastapi, yt_dlp, telebot; print('OK')"
  ffmpeg -version | head -1
  cloudflared --version
  ```

## Phase 2 — 외부 서비스 키 발급 (15분)

### 2A. Gemini API 키 (필수, 무료)
- [ ] **2.1** https://aistudio.google.com/app/apikey 접속
- [ ] **2.2** Google 로그인 → "Create API key"
- [ ] **2.3** 발급된 `AIzaSy...` 키 복사
- [ ] **2.4** `app/.env`의 `GEMINI_API_KEY=` 뒤에 붙여넣기

### 2B. 텔레그램 봇 토큰 (선택, 무료)
- [ ] **2.5** 텔레그램에서 `@BotFather` 검색 → 채팅 시작
- [ ] **2.6** `/newbot` 입력
- [ ] **2.7** 봇 이름 입력 (예: `My yt-dlp helper`)
- [ ] **2.8** 봇 username 입력 (`_bot` 끝, 예: `woojini_ytdlp_bot`)
- [ ] **2.9** 토큰 `1234567890:AAA...` 복사 → `app/.env` `TELEGRAM_BOT_TOKEN=`

### 2C. Firebase (정식 운영 시)
- [ ] **2.10** https://console.firebase.google.com → "프로젝트 추가"
- [ ] **2.11** Authentication → Sign-in method → Google 활성화
- [ ] **2.12** Authentication → Settings → Authorized domains에 Netlify 도메인 추가 (`*.netlify.app`)
- [ ] **2.13** 프로젝트 설정 → 일반 → 내 앱 → "웹" 앱 추가 → SDK 설정 복사
  - `apiKey`, `authDomain`, `projectId`, `appId` → `frontend/.env` 및 Netlify 환경변수
- [ ] **2.14** 프로젝트 설정 → 서비스 계정 → "새 비공개 키 생성" → JSON 다운로드
  - `app/firebase-admin.json` 으로 저장
- [ ] **2.15** `app/.env` 에 `FIREBASE_PROJECT_ID`, `FIREBASE_SERVICE_ACCOUNT_PATH=./firebase-admin.json`, `ALLOW_INSECURE_AUTH=false`

> 정식 운영 전에는 `ALLOW_INSECURE_AUTH=true`로 우회해서 동작 확인부터 권장.

## Phase 3 — 백엔드 기동 (5분)

### 3A. 일회성 실행 (테스트)
- [ ] **3.1** uvicorn 직접 실행
  ```bash
  cd app
  ../.venv/bin/python -m uvicorn backend.main:app --reload --port 8000
  ```
- [ ] **3.2** 다른 터미널에서 검증
  ```bash
  curl http://localhost:8000/health           # → {"status":"ok"}
  curl http://localhost:8000/api/settings     # → 설정 JSON
  ```

### 3B. 영구 자동시작 (launchd)
- [ ] **3.3** 자동시작 셋업 (cloudflared quick tunnel 포함)
  ```bash
  bash app/scripts/setup-cloudflared.sh
  ```
  출력 끝에 공개 URL 나옴 (`https://xxx.trycloudflare.com`)
- [ ] **3.4** 상태 확인
  ```bash
  bash app/scripts/status-anywhere.sh
  ```

### 3C. 영구 URL 원할 때 (Tailscale)
- [ ] **3.5** `brew install --cask tailscale-app` (sudo 1회)
- [ ] **3.6** Tailscale 앱 실행 → 로그인
- [ ] **3.7** https://login.tailscale.com/admin/dns → HTTPS Certificates Enable
- [ ] **3.8** `bash app/scripts/stop-anywhere.sh` (cloudflared 해제)
- [ ] **3.9** `bash app/scripts/setup-anywhere.sh` (Tailscale Funnel)

## Phase 4 — 프론트엔드 로컬 테스트 (5분)

- [ ] **4.1** Vite dev 서버
  ```bash
  cd app/frontend
  npm install        # 1회만
  npm run dev        # → http://localhost:5173
  ```
- [ ] **4.2** 브라우저에서 http://localhost:5173 → "로컬 개발자 모드로 시작" → URL 입력 → 잡 동작 확인

## Phase 5 — GitHub + Netlify 배포 (10분)

- [ ] **5.1** GitHub 레포 생성 (이미 있으면 skip)
- [ ] **5.2** 푸시
  ```bash
  git remote add origin <your-repo-url>
  git push -u origin master
  ```
- [ ] **5.3** Netlify → New site → Import an existing project → GitHub 연결 → 레포 선택
- [ ] **5.4** Build settings는 [netlify.toml](../netlify.toml)이 자동 인식 (base: `app/frontend`)
- [ ] **5.5** Site settings → Environment variables (자세한 값은 [GUIDE.md](./GUIDE.md) 참고)
  - `VITE_API_BASE_URL` = (cloudflared/Tailscale URL)
  - `VITE_FIREBASE_*`
  - `VITE_ALLOW_INSECURE_AUTH=true` (테스트) 또는 `false` (정식)
- [ ] **5.6** Deploys → Trigger deploy → Clear cache and deploy site
- [ ] **5.7** Netlify URL 외부에서 접속 검증

## Phase 6 — 데스크톱 런처 (선택, 3분)

- [ ] **6.1** `.app` 응용 프로그램 폴더로 복사
  ```bash
  cp -R "app/dist/yt-dlp webapp.app" /Applications/
  ```
- [ ] **6.2** 첫 실행 (Gatekeeper 우회)
  - Finder에서 우클릭 → 열기 → "열기" 클릭
- [ ] **6.3** Spotlight에서 "yt-dlp" 검색해 더블클릭 → 상태 dialog 확인

## Phase 7 — 텔레그램 봇 활성화 (선택, 2분)

- [ ] **7.1** `app/.env`의 `TELEGRAM_BOT_TOKEN` 채움 (Phase 2B 참고)
- [ ] **7.2** 백엔드 재시작
  ```bash
  launchctl kickstart -k gui/$UID/com.user.ytdlp-backend
  ```
- [ ] **7.3** `curl http://localhost:8000/api/settings` → `"telegram_enabled": true` 확인
- [ ] **7.4** 봇 채팅 열고 YouTube URL 전송 → 응답 + 처리 알림 확인

## Phase 8 — 운영 (지속)

- [ ] **8.1** 잡 상태 모니터
  ```bash
  bash app/scripts/status-anywhere.sh
  ```
- [ ] **8.2** 로그 실시간 보기
  ```bash
  tail -f ~/Library/Logs/ytdlp-backend.err.log
  tail -f ~/Library/Logs/ytdlp-tunnel.err.log
  ```
- [ ] **8.3** cloudflared 터널 재시작으로 URL 변경 시
  - `bash app/scripts/get-url.sh` 로 새 URL 확인
  - Netlify 환경변수 갱신 → Clear cache and deploy
- [ ] **8.4** (선택) 맥 절전 차단
  ```bash
  sudo pmset -c sleep 0 disksleep 0 displaysleep 30
  ```

## Phase 9 — 트러블슈팅 빠른 점검

| 증상 | 1차 점검 |
|------|---------|
| 잡이 `failed` | `~/yt-dlp-downloads/<id>/job.json` 의 `error` 필드 |
| 외부에서 접속 안 됨 | `bash app/scripts/status-anywhere.sh` → tunnel/health 확인 |
| 백엔드 안 뜸 | `tail ~/Library/Logs/ytdlp-backend.err.log` |
| Netlify 화면 빈 채로 멈춤 | 브라우저 DevTools Console → CORS/Firebase 에러 확인 |
| 텔레그램 봇 응답 없음 | `.env` 토큰, 백엔드 재시작, `/api/settings` 의 `telegram_enabled` |
| 빌드 실패 (Netlify) | 로컬에서 `cd app/frontend && npm run build` 재현 |

## Phase 10 — 제거 (clean uninstall)

- [ ] **10.1** 자동시작 해제
  ```bash
  bash app/scripts/stop-anywhere.sh
  ```
- [ ] **10.2** .app 삭제
  ```bash
  rm -rf "/Applications/yt-dlp webapp.app"
  ```
- [ ] **10.3** 로그 삭제 (선택)
  ```bash
  rm ~/Library/Logs/ytdlp-*.log
  ```
- [ ] **10.4** 다운로드 데이터 삭제 (주의 — 영상도 같이 지워짐)
  ```bash
  rm -rf ~/yt-dlp-downloads
  ```
- [ ] **10.5** brew 의존성 (옵션)
  ```bash
  brew uninstall cloudflared ffmpeg
  ```
- [ ] **10.6** 레포 디렉토리 삭제
  ```bash
  rm -rf ~/yt-dlp
  ```

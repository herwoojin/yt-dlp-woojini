# GUIDE — yt-dlp web app 사용 가이드

> 처음 받은 사람도 따라할 수 있는 자세한 셋업 + 일상 사용 안내
> 마지막 갱신: 2026-05-20

## 1. 이게 뭔가요?

YouTube URL 하나 보내면 자동으로:
- 영상을 본인 맥에 다운로드
- 자막 추출 → `transcript.txt` (가장 작은 원본 스크립트)
- Gemini AI가 4종 산출물 생성:
  - 시계열 목차 (`chapters.json`)
  - 짧은 요약 HTML (`summary_short.html`)
  - 이메일용 가독성 HTML (`email_readable.html`)
  - 블로그/카페용 장문 HTML (`blog_long.html`)
- 모바일에서도 어디서든 접근 가능 (Netlify + 터널)
- 텔레그램 봇으로도 사용 가능

영상과 결과물은 **본인 맥에만 저장** (클라우드 X). 맥이 켜져 있는 한 어디서든 접근.

---

## 2. 누가 쓰면 좋을까

- 유튜브 영상 정리해서 블로그/카페에 자주 올리는 분
- 영상 내용을 텍스트로 보관하고 싶은 분
- 휴대폰에서 발견한 영상을 손쉽게 큐에 던지고 싶은 분

---

## 3. 셋업 (처음 1회만)

### 3.1 무엇이 필요한가
- **맥 (macOS 12 이상)**
- **Homebrew** (https://brew.sh)
- **Google 계정** (Gemini API 키 발급)
- (선택) **GitHub + Netlify 계정** — 웹페이지를 외부에서 쓰려면
- (선택) **Firebase 프로젝트** — 정식 운영 시 로그인용
- (선택) **텔레그램** — 봇 사용 시

### 3.2 설치 — 한 줄

터미널 열고:

```bash
git clone https://github.com/herwoojin/yt-dlp-woojini.git ~/yt-dlp
cd ~/yt-dlp
bash app/scripts/install.sh
```

이 한 줄이 자동으로:
- Homebrew 의존성 (ffmpeg, cloudflared) 설치
- Python venv + 패키지 설치
- `.env` 파일 스캐폴드
- (선택 질문) launchd 자동시작 등록

### 3.3 API 키 발급 (필수: Gemini 1개)

#### Gemini API 키 (무료, 5분)

1. https://aistudio.google.com/app/apikey 접속
2. Google 로그인
3. **"Create API key"** 클릭
4. 발급된 `AIzaSy...` 형태의 키 복사

#### `.env`에 키 넣기

```bash
open -a TextEdit ~/yt-dlp/app/.env
```

`GEMINI_API_KEY=` 뒤에 발급받은 키를 붙여넣고 저장.

### 3.4 백엔드 시작

#### 방법 A — 명령어 한 줄

```bash
bash ~/yt-dlp/app/scripts/setup-cloudflared.sh
```

출력 끝에 공개 URL이 표시됨 (`https://xxxx-xxxx.trycloudflare.com`).

#### 방법 B — 더블클릭 (.app)

```bash
cp -R "~/yt-dlp/app/dist/yt-dlp webapp.app" /Applications/
```

이후 Spotlight (⌘+Space) → "yt-dlp" 검색 → 더블클릭 → "시작" 버튼.

> 처음 더블클릭 시 "확인되지 않은 개발자" 경고 → 우클릭 → 열기 → "열기" 클릭.

### 3.5 동작 확인

브라우저에서 화면에 출력된 공개 URL + `/health` 열기:

```
https://xxxx-xxxx.trycloudflare.com/health
```

`{"status":"ok"}` 응답이 보이면 성공.

---

## 4. 웹페이지 사용 (모바일/외부 PC)

### 4.1 Netlify 배포 (1회)

#### A. 레포 푸시 (이미 GitHub에 있다면 skip)
```bash
cd ~/yt-dlp
git remote add origin <your-repo-url>
git push -u origin master
```

#### B. Netlify 연결
1. https://app.netlify.com → **"Add new site"** → **"Import an existing project"**
2. GitHub 선택 → 본인 레포 선택
3. Build settings은 자동 인식됨 ([netlify.toml](../netlify.toml))
4. **"Deploy site"** 클릭

#### C. 환경변수 입력

배포된 사이트 → **Site settings → Environment variables → Add a variable**:

| Key | Value (예) |
|-----|-----------|
| `VITE_API_BASE_URL` | `https://xxxx-xxxx.trycloudflare.com` ← 백엔드 공개 URL |
| `VITE_ALLOW_INSECURE_AUTH` | `true` (테스트) 또는 `false` (정식) |
| `VITE_FIREBASE_API_KEY` | (Firebase 사용 시) Firebase Console → 프로젝트 설정 → SDK 설정의 `apiKey` |
| `VITE_FIREBASE_AUTH_DOMAIN` | 같은 곳 `authDomain` |
| `VITE_FIREBASE_PROJECT_ID` | 같은 곳 `projectId` |
| `VITE_FIREBASE_APP_ID` | 같은 곳 `appId` |

#### D. 재배포

**Deploys → Trigger deploy → Clear cache and deploy site**

빌드 끝나면 휴대폰/외부 PC에서 Netlify URL (`https://your-app.netlify.app`) 접속.

### 4.2 사용 흐름

1. Netlify URL 열기
2. (insecure 모드) "로컬 개발자 모드로 시작" / (Firebase) Google 로그인
3. YouTube URL 붙여넣기 → Gemini 품질 선택 (Flash 빠름, Pro 고품질)
4. "다운로드 + 요약 시작" 클릭
5. 잡 목록에 새 항목이 뜨고 진행상황이 실시간 표시 (다운로드 → 자막 → 요약)
6. 완료되면 클릭해서 상세 화면:
   - 시계열 목차 (시간 + 제목)
   - 영상/스크립트/HTML 다운로드 버튼
   - HTML "미리보기" 버튼 → 모달로 표시 + "HTML 복사" 버튼

---

## 5. 텔레그램 봇 (선택)

### 5.1 봇 만들기

1. 텔레그램에서 `@BotFather` 검색 → 채팅 시작
2. `/newbot` 입력
3. 봇 이름 입력 (예: `My yt-dlp helper`)
4. 봇 username 입력 (반드시 `_bot` 끝, 예: `my_ytdlp_bot`)
5. 토큰 `1234567890:AAA...` 복사

### 5.2 토큰 등록 + 백엔드 재시작

```bash
open -a TextEdit ~/yt-dlp/app/.env
# TELEGRAM_BOT_TOKEN=1234567890:AAA... 입력 후 저장

launchctl kickstart -k gui/$UID/com.user.ytdlp-backend
```

### 5.3 사용

봇 채팅창 열고 YouTube URL 보내기 → 자동으로 잡 등록 → 처리 완료 시 알림 + (50MB 이하면) 영상도 전송.

---

## 6. 일상 사용

### 6.1 일반 흐름

맥 켜져 있으면 → launchd가 백엔드 + 터널 알아서 가동 → **사용자는 그냥 모바일에서 쓰면 됨**.

### 6.2 .app으로 상태 확인

Spotlight → "yt-dlp" → 더블클릭하면:
- 현재 가동 중인지 dialog로 표시
- 활성 공개 URL 복사 가능
- 로그 보기 / 브라우저 열기 / 종료 옵션

### 6.3 cloudflared URL이 바뀌었을 때

quick tunnel은 재시작 시 URL이 바뀝니다. 새 URL로 Netlify 갱신:

```bash
bash ~/yt-dlp/app/scripts/get-url.sh
```

복사된 URL을 Netlify Environment variables의 `VITE_API_BASE_URL`에 붙여넣고 **Trigger deploy → Clear cache and deploy site**.

> 매번 갱신이 귀찮으면 → Tailscale Funnel 영구 URL로 전환 (`docs/TASKS.md`의 Phase 3C 참고).

### 6.4 잡 결과 어디서 찾나

```
~/yt-dlp-downloads/<job_id>/
├── video.mp4
├── transcript.txt
├── chapters.json
├── summary_short.html
├── email_readable.html
└── blog_long.html
```

또는 웹페이지 잡 상세 화면에서 "다운로드" 버튼 클릭.

### 6.5 이메일에 붙여넣기

웹페이지 잡 상세 → `email_readable.html` 옆 "미리보기" → "HTML 복사" → 이메일 작성 화면 → 붙여넣기 (Gmail이라면 ⌘+V 만 해도 서식 유지).

### 6.6 블로그/카페에 붙여넣기

같은 방식으로 `blog_long.html` 복사. 네이버 블로그/카페는 HTML 편집 모드 켜고 붙여넣어야 인라인 스타일이 유지됩니다.

---

## 7. 트러블슈팅

### 잡이 `failed`로 끝남
- **HTTP 429**: YouTube 레이트 리밋. 5~10분 후 재시도
- **HTTP 403**: IP 차단. Chrome의 "Get cookies.txt" 확장으로 쿠키 export → `.env`의 `YT_DLP_COOKIES_FILE` 에 경로 지정 → 재시작
- **Gemini 400**: API 키 미설정 또는 잘못된 모델 ID. `.env` 점검

### Netlify에서 빈 화면 / 에러
- 브라우저 DevTools (⌘+Option+I) → Console 빨간 메시지 확인
- CORS 에러면 `app/.env`의 `ALLOWED_ORIGINS`에 Netlify 도메인 추가 후 백엔드 재시작
- `auth/unauthorized-domain` 이면 Firebase Console → Authentication → Settings → Authorized domains에 Netlify 도메인 추가

### 백엔드 안 뜸
```bash
tail -50 ~/Library/Logs/ytdlp-backend.err.log
```
에러 메시지 보고 .env, venv 점검.

### 텔레그램 봇 응답 없음
- `.env`의 `TELEGRAM_BOT_TOKEN` 오타 확인
- 백엔드 재시작 (`launchctl kickstart -k gui/$UID/com.user.ytdlp-backend`)
- `curl http://localhost:8000/api/settings` 에서 `"telegram_enabled": true` 확인

### 더블클릭 했는데 .app이 안 열림
- 처음 한 번은 반드시 우클릭 → 열기 → "열기" 클릭 (Gatekeeper)
- 그래도 안 되면 시스템 설정 → 개인정보 보호 및 보안 → "확인되지 않은 개발자" 허용

### 공개 URL이 외부에서 안 됨
- `bash app/scripts/status-anywhere.sh` → tunnel 상태 + /health 응답 확인
- 터널 죽었으면 `launchctl kickstart -k gui/$UID/com.user.ytdlp-tunnel`
- URL이 재발급 됐으면 `bash app/scripts/get-url.sh`로 새 URL 확인 → Netlify 갱신

---

## 8. 유용한 명령 모음

```bash
# 상태 점검
bash ~/yt-dlp/app/scripts/status-anywhere.sh

# 현재 공개 URL
bash ~/yt-dlp/app/scripts/get-url.sh

# 백엔드 재시작
launchctl kickstart -k gui/$UID/com.user.ytdlp-backend

# 터널 재시작
launchctl kickstart -k gui/$UID/com.user.ytdlp-tunnel

# 자동시작 완전 해제 (데이터 보존)
bash ~/yt-dlp/app/scripts/stop-anywhere.sh

# 로그 실시간 보기
tail -f ~/Library/Logs/ytdlp-backend.err.log
tail -f ~/Library/Logs/ytdlp-tunnel.err.log

# 절전 차단 (전원 연결 시)
sudo pmset -c sleep 0 disksleep 0 displaysleep 30

# 깔끔하게 제거 (영상도 같이 지움 주의)
bash ~/yt-dlp/app/scripts/stop-anywhere.sh
rm -rf ~/yt-dlp ~/yt-dlp-downloads "/Applications/yt-dlp webapp.app"
```

---

## 9. 더 알고 싶다면

- 제품 의도/스펙 → [PRD.md](./PRD.md)
- 기술 아키텍처 → [TRD.md](./TRD.md)
- 데이터 모델 → [ERD.md](./ERD.md)
- 단계별 빌드/설치 체크리스트 → [TASKS.md](./TASKS.md)
- AI에게 똑같이 만들어달라고 줄 프롬프트 → [SETUP_PROMPT.md](./SETUP_PROMPT.md)

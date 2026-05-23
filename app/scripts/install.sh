#!/usr/bin/env bash
# install.sh — 새 사용자를 위한 한 줄 셋업 스크립트.
#
# 사용법 (레포 clone 후):
#   bash app/scripts/install.sh
#
# 또는 원격 1줄 (GitHub에서 직접 받으면서 실행):
#   curl -fsSL https://raw.githubusercontent.com/herwoojin/yt-dlp-woojini/master/app/scripts/install.sh | bash
#
# 동작:
#   1) Homebrew 확인/안내
#   2) Python venv 생성 (.venv/)
#   3) brew 의존성 설치 (ffmpeg, cloudflared)
#   4) pip 의존성 설치 (requirements.txt)
#   5) app/.env 스캐폴드 (없을 때만)
#   6) frontend/.env 스캐폴드 (없을 때만)
#   7) launchd plist 등록 (선택)
set -euo pipefail

# ─── 경로 결정 (스크립트 위치 기준) ────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT_DIR="$(cd "$APP_DIR/.." && pwd)"

cat <<EOF
═══════════════════════════════════════════════
 yt-dlp web app — 자동 설치
═══════════════════════════════════════════════
  ROOT_DIR = $ROOT_DIR
  APP_DIR  = $APP_DIR
EOF
echo

# ─── 1. macOS 확인 ───────────────────────────────────────────
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "❌ macOS 전용 스크립트입니다. Linux/Windows는 README의 수동 설치 참고."
  exit 1
fi

# ─── 2. Homebrew ─────────────────────────────────────────────
if ! command -v brew >/dev/null 2>&1; then
  cat <<EOF
❌ Homebrew가 설치되어 있지 않습니다.

다음 명령으로 먼저 설치한 뒤 이 스크립트를 다시 실행하세요:

  /bin/bash -c "\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

EOF
  exit 1
fi
echo "✓ Homebrew 발견: $(brew --version | head -1)"

# ─── 3. brew 의존성 ──────────────────────────────────────────
echo
echo "📦 brew 패키지 설치 (ffmpeg, cloudflared)..."
for pkg in ffmpeg cloudflared; do
  if brew list --formula "$pkg" >/dev/null 2>&1; then
    echo "   ✓ $pkg (이미 설치됨)"
  else
    echo "   ⬇ $pkg 설치 중..."
    brew install "$pkg" >/dev/null
    echo "   ✓ $pkg"
  fi
done

# ─── 4. Python 3 + venv ─────────────────────────────────────
echo
echo "🐍 Python venv 셋업..."
if ! command -v python3 >/dev/null 2>&1; then
  echo "   ⬇ python3 설치 중..."
  brew install python@3.12 >/dev/null
fi
PYTHON="$(command -v python3)"
echo "   ✓ Python: $($PYTHON --version)"

VENV="$ROOT_DIR/.venv"
if [[ ! -x "$VENV/bin/python" ]]; then
  echo "   ⬇ venv 생성: $VENV"
  $PYTHON -m venv "$VENV"
fi
"$VENV/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
"$VENV/bin/python" -m pip install --upgrade pip >/dev/null
echo "   ✓ venv: $VENV"

# ─── 5. pip 의존성 ───────────────────────────────────────────
echo
echo "📦 Python 패키지 설치 (requirements.txt)..."
"$VENV/bin/python" -m pip install -q -r "$APP_DIR/requirements.txt"
echo "   ✓ 완료"

# ─── 6. .env 스캐폴드 ────────────────────────────────────────
echo
echo "📝 .env 파일 점검..."
if [[ ! -f "$APP_DIR/.env" ]]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo "   ✓ app/.env 생성됨 (.env.example 복사)"
  echo "   👉 GEMINI_API_KEY, TELEGRAM_BOT_TOKEN 등을 채워주세요"
else
  echo "   ✓ app/.env 이미 있음 (덮어쓰지 않음)"
fi

FE_ENV="$APP_DIR/frontend/.env"
if [[ ! -f "$FE_ENV" ]]; then
  cp "$APP_DIR/frontend/.env.example" "$FE_ENV"
  echo "   ✓ frontend/.env 생성됨"
else
  echo "   ✓ frontend/.env 이미 있음"
fi

# ─── 7. frontend npm 의존성 (선택) ─────────────────────────
echo
read -p "프론트엔드(React) 의존성도 지금 설치할까요? [y/N] " ans
if [[ "$ans" =~ ^[yY] ]]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "   ⬇ node 설치 중..."
    brew install node >/dev/null
  fi
  (cd "$APP_DIR/frontend" && npm install --silent)
  echo "   ✓ npm install 완료"
fi

# ─── 8. launchd 등록 (선택) ─────────────────────────────────
echo
read -p "지금 백엔드를 launchd로 자동시작 등록할까요? (맥 부팅 시마다 자동 실행) [y/N] " ans
if [[ "$ans" =~ ^[yY] ]]; then
  bash "$SCRIPT_DIR/setup-cloudflared.sh"
fi

# ─── 9. 마무리 ──────────────────────────────────────────────
cat <<EOF

═══════════════════════════════════════════════
✅ 설치 완료
═══════════════════════════════════════════════

다음 단계:

1) .env 편집 (필수):
   open -a TextEdit $APP_DIR/.env
   - GEMINI_API_KEY        (https://aistudio.google.com/app/apikey)
   - TELEGRAM_BOT_TOKEN    (텔레그램 @BotFather 에서 /newbot)
   - FIREBASE_*            (정식 운영 시. 테스트는 ALLOW_INSECURE_AUTH=true 로 우회 가능)

2) 백엔드 시작 (위에서 launchd 등록 안 했다면):
   bash $SCRIPT_DIR/setup-cloudflared.sh

3) 프론트 개발 서버 (로컬 테스트용):
   cd $APP_DIR/frontend && npm run dev    # → http://localhost:5173

4) Netlify 배포:
   docs/GUIDE.md 의 "Netlify 배포" 섹션 참고

상태 확인:
   bash $SCRIPT_DIR/status-anywhere.sh

EOF

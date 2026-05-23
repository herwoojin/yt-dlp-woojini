#!/usr/bin/env bash
# Always-on 설정: launchd로 uvicorn 자동시작 + Tailscale Funnel로 공개 URL.
# 한 번만 실행하면 됩니다. 재부팅해도 자동 복구.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT_DIR="$(cd "$APP_DIR/.." && pwd)"
VENV_PYTHON="$ROOT_DIR/.venv/bin/python"
LOGS_DIR="$HOME/Library/Logs"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_LABEL="com.user.ytdlp-backend"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$PLIST_LABEL.plist"

echo "═══════════════════════════════════════════════"
echo " yt-dlp web app  ―  always-on 설정"
echo "═══════════════════════════════════════════════"
echo "  APP_DIR     = $APP_DIR"
echo "  VENV PYTHON = $VENV_PYTHON"
echo "  PLIST       = $PLIST_PATH"
echo

# ─── 1. 사전 점검 ──────────────────────────────────
[[ -x "$VENV_PYTHON" ]] || { echo "❌ Python venv가 없습니다: $VENV_PYTHON"; echo "   먼저: cd $APP_DIR && python3 -m venv ../.venv && pip install -r requirements.txt"; exit 1; }
[[ -f "$APP_DIR/.env" ]] || { echo "❌ $APP_DIR/.env 가 없습니다 (cp .env.example .env)"; exit 1; }

if ! command -v tailscale >/dev/null 2>&1; then
  cat <<EOF
❌ Tailscale CLI를 찾을 수 없습니다.

다음 1회 단계를 먼저 끝내고 이 스크립트를 다시 실행하세요:

  1) 설치 (관리자 비밀번호 1회 입력):
     brew install --cask tailscale-app

  2) /Applications/Tailscale.app 실행 → 메뉴바 아이콘 → "Log in..."
     → 브라우저에서 Tailscale 계정으로 로그인 (Google/Microsoft/GitHub 가능)

  3) Tailscale admin 콘솔에서 Funnel 활성화 (1회):
     https://login.tailscale.com/admin/dns
     → "HTTPS Certificates" Enable
     https://login.tailscale.com/admin/acls/file
     → ACL 안에 "nodeAttrs"에 다음 추가:
       {"target": ["autogroup:member"], "attr": ["funnel"]}

  4) 다시 실행: bash $0
EOF
  exit 1
fi

# ─── 2. Tailscale 상태 확인 ─────────────────────────
echo "🔍 Tailscale 상태 확인..."
TS_STATE=$(tailscale status --json 2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin).get("BackendState","?"))' 2>/dev/null || echo "Unknown")
if [[ "$TS_STATE" != "Running" ]]; then
  echo "❌ Tailscale이 로그인되어 있지 않습니다 (state: $TS_STATE)"
  echo "   메뉴바 Tailscale 아이콘 → Log in 후 다시 시도하세요."
  exit 1
fi
echo "   ✓ Tailscale running"

TS_DNS=$(tailscale status --json | python3 -c 'import sys,json; d=json.load(sys.stdin); print((d.get("Self") or {}).get("DNSName","").rstrip("."))')
[[ -n "$TS_DNS" ]] || { echo "❌ Tailscale DNS 이름을 가져오지 못했습니다"; exit 1; }
PUBLIC_URL="https://$TS_DNS"
echo "   ✓ 공개 URL이 될 주소: $PUBLIC_URL"
echo

# ─── 3. launchd plist 생성 ─────────────────────────
mkdir -p "$LAUNCH_AGENTS_DIR" "$LOGS_DIR"
echo "📝 launchd plist 작성: $PLIST_PATH"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$PLIST_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$VENV_PYTHON</string>
    <string>-m</string>
    <string>uvicorn</string>
    <string>backend.main:app</string>
    <string>--host</string>
    <string>127.0.0.1</string>
    <string>--port</string>
    <string>8000</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$APP_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>HOME</key>
    <string>$HOME</string>
    <key>LANG</key>
    <string>ko_KR.UTF-8</string>
  </dict>
  <key>StandardOutPath</key>
  <string>$LOGS_DIR/ytdlp-backend.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOGS_DIR/ytdlp-backend.err.log</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
    <key>Crashed</key>
    <true/>
  </dict>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>ProcessType</key>
  <string>Interactive</string>
</dict>
</plist>
PLIST

# ─── 4. launchd 등록 ───────────────────────────────
echo "🔄 launchd 등록..."
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load -w "$PLIST_PATH"

echo "⏳ uvicorn 기동 대기 (최대 20초)..."
for i in {1..20}; do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "   ✓ backend 응답 OK"
    break
  fi
  sleep 1
  [[ $i -eq 20 ]] && { echo "❌ backend 기동 실패. 로그: $LOGS_DIR/ytdlp-backend.err.log"; tail -20 "$LOGS_DIR/ytdlp-backend.err.log" 2>/dev/null; exit 1; }
done
echo

# ─── 5. Tailscale Funnel 활성화 (영구) ─────────────
echo "🌐 Tailscale Funnel 활성화 (영구 설정, 재부팅 후에도 유지)..."
# reset existing serve config and re-add
tailscale serve reset >/dev/null 2>&1 || true
if ! tailscale funnel --bg --https=443 http://127.0.0.1:8000 ; then
  echo "❌ Funnel 활성화 실패. 가능한 원인:"
  echo "   - Admin → DNS에서 HTTPS Certificates를 Enable하지 않음"
  echo "   - Admin → Access controls에 nodeAttrs funnel 권한 미부여"
  echo "   - Tailscale Free 플랜에서 Funnel은 무료 사용 가능 (활성화만 하면 됨)"
  exit 1
fi
echo

# ─── 6. 결과 출력 ─────────────────────────────────
echo "═══════════════════════════════════════════════"
echo "✅ 설정 완료!"
echo "═══════════════════════════════════════════════"
echo
echo "🌍 공개 URL (어디서든 접근 가능):"
echo "   $PUBLIC_URL"
echo
echo "🧪 외부 검증:"
echo "   curl $PUBLIC_URL/health"
echo
echo "📋 Netlify에서 해야 할 일:"
echo "   1) Site settings → Environment variables"
echo "   2) VITE_API_BASE_URL = $PUBLIC_URL"
echo "   3) Trigger deploy → Clear cache and deploy site"
echo
echo "🔧 백엔드 .env 의 ALLOWED_ORIGINS 에 Netlify 도메인 포함됐는지 확인:"
echo "   ALLOWED_ORIGINS=https://your-app.netlify.app,$PUBLIC_URL"
echo
echo "📊 상태 확인:        bash $SCRIPT_DIR/status-anywhere.sh"
echo "🛑 자동시작 해제:    bash $SCRIPT_DIR/stop-anywhere.sh"
echo "📝 로그:             tail -f $LOGS_DIR/ytdlp-backend.err.log"

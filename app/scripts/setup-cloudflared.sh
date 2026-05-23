#!/usr/bin/env bash
# Cloudflared quick tunnel 기반 always-on 설정.
# - sudo 불필요
# - 무료, 즉시 동작
# - URL이 재시작마다 바뀌는 trade-off 있음 (영구 URL 원하면 setup-anywhere.sh의 Tailscale 경로 사용)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT_DIR="$(cd "$APP_DIR/.." && pwd)"
VENV_PYTHON="$ROOT_DIR/.venv/bin/python"
LOGS_DIR="$HOME/Library/Logs"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
BACKEND_PLIST="$LAUNCH_AGENTS_DIR/com.user.ytdlp-backend.plist"
TUNNEL_PLIST="$LAUNCH_AGENTS_DIR/com.user.ytdlp-tunnel.plist"

echo "═══════════════════════════════════════════════"
echo " yt-dlp web app  ―  always-on (cloudflared)"
echo "═══════════════════════════════════════════════"

[[ -x "$VENV_PYTHON" ]] || { echo "❌ venv 없음: $VENV_PYTHON"; exit 1; }
[[ -f "$APP_DIR/.env" ]] || { echo "❌ .env 없음: $APP_DIR/.env"; exit 1; }
command -v cloudflared >/dev/null 2>&1 || { echo "❌ cloudflared 미설치. brew install cloudflared"; exit 1; }
mkdir -p "$LAUNCH_AGENTS_DIR" "$LOGS_DIR"

cat > "$BACKEND_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.user.ytdlp-backend</string>
  <key>ProgramArguments</key>
  <array>
    <string>$VENV_PYTHON</string><string>-m</string><string>uvicorn</string>
    <string>backend.main:app</string>
    <string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>8000</string>
  </array>
  <key>WorkingDirectory</key><string>$APP_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>HOME</key><string>$HOME</string>
    <key>LANG</key><string>ko_KR.UTF-8</string>
  </dict>
  <key>StandardOutPath</key><string>$LOGS_DIR/ytdlp-backend.out.log</string>
  <key>StandardErrorPath</key><string>$LOGS_DIR/ytdlp-backend.err.log</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/><key>Crashed</key><true/></dict>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>ProcessType</key><string>Interactive</string>
</dict>
</plist>
PLIST

CFD_PATH="$(command -v cloudflared)"
cat > "$TUNNEL_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.user.ytdlp-tunnel</string>
  <key>ProgramArguments</key>
  <array>
    <string>$CFD_PATH</string>
    <string>tunnel</string><string>--no-autoupdate</string>
    <string>--url</string><string>http://127.0.0.1:8000</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>HOME</key><string>$HOME</string>
  </dict>
  <key>StandardOutPath</key><string>$LOGS_DIR/ytdlp-tunnel.out.log</string>
  <key>StandardErrorPath</key><string>$LOGS_DIR/ytdlp-tunnel.err.log</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>ProcessType</key><string>Background</string>
</dict>
</plist>
PLIST

plutil -lint "$BACKEND_PLIST" >/dev/null && plutil -lint "$TUNNEL_PLIST" >/dev/null
echo "✓ plist 작성됨"

launchctl unload "$BACKEND_PLIST" 2>/dev/null || true
launchctl unload "$TUNNEL_PLIST" 2>/dev/null || true
launchctl load -w "$BACKEND_PLIST"
launchctl load -w "$TUNNEL_PLIST"
echo "✓ launchd 등록 완료"

echo "⏳ backend 기동 대기..."
for i in {1..20}; do
  curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 && { echo "  ✓ backend OK"; break; }
  sleep 1
done

echo "⏳ tunnel URL 발급 대기..."
URL=""
for i in {1..30}; do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOGS_DIR/ytdlp-tunnel.err.log" 2>/dev/null | tail -1)
  [[ -n "$URL" ]] && break
  sleep 1
done
[[ -n "$URL" ]] || { echo "❌ URL 발급 실패"; tail -20 "$LOGS_DIR/ytdlp-tunnel.err.log"; exit 1; }

echo "⏳ 외부 도달 테스트..."
for i in {1..15}; do
  CODE=$(curl -fsS -o /dev/null -w '%{http_code}' --max-time 6 "$URL/health" 2>/dev/null || echo 000)
  [[ "$CODE" == "200" ]] && { echo "  ✓ 외부 도달 OK"; break; }
  sleep 2
done

echo
echo "═══════════════════════════════════════════════"
echo "🌍 공개 URL: $URL"
echo "═══════════════════════════════════════════════"
echo "📋 Netlify: VITE_API_BASE_URL = $URL"
echo "⚠️  재부팅/터널 재시작 시 URL 변경됨 → bash $SCRIPT_DIR/get-url.sh 로 확인"
echo "💡 영구 URL 원하면 setup-anywhere.sh (Tailscale Funnel) 사용"

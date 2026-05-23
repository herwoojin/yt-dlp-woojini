#!/usr/bin/env bash
# 백엔드 + 터널 상태 한눈에 보기.
set -euo pipefail

echo "═══════════════════════════════════════════════"
echo " yt-dlp web app  ―  always-on 상태"
echo "═══════════════════════════════════════════════"
echo

echo "🔹 launchd 등록 상태:"
LIST=$(launchctl list 2>/dev/null || true)
FOUND=0
for LABEL in com.user.ytdlp-backend com.user.ytdlp-tunnel; do
  LINE=$(printf '%s\n' "$LIST" | grep -F "$LABEL" || true)
  if [[ -n "$LINE" ]]; then
    PID=$(echo "$LINE" | awk '{print $1}')
    EXIT=$(echo "$LINE" | awk '{print $2}')
    printf "   ✓ %-30s PID=%s ExitCode=%s\n" "$LABEL" "$PID" "$EXIT"
    FOUND=1
  else
    echo "   ❌ $LABEL 미등록"
  fi
done
[[ $FOUND -eq 0 ]] && echo "   👉 bash setup-cloudflared.sh 먼저 실행"
echo

echo "🔹 백엔드 (localhost:8000):"
if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
  echo "   ✓ /health OK"
  curl -fsS http://127.0.0.1:8000/api/settings 2>/dev/null | python3 -m json.tool 2>/dev/null | sed 's/^/     /'
else
  echo "   ❌ 응답 없음"
fi
echo

echo "🔹 Cloudflared quick tunnel:"
if launchctl list | grep -q "com.user.ytdlp-tunnel"; then
  launchctl list | grep "com.user.ytdlp-tunnel" | awk '{printf "   PID=%s ExitCode=%s\n", $1, $2}'
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$HOME/Library/Logs/ytdlp-tunnel.err.log" 2>/dev/null | tail -1)
  if [[ -n "$URL" ]]; then
    echo "   현재 URL:    $URL"
    CODE=$(curl -fsS -o /dev/null -w '%{http_code}' --max-time 8 "$URL/health" 2>/dev/null || echo "fail")
    echo "   /health 응답: $CODE"
  else
    echo "   URL 로그에 없음 (아직 발급 중일 수 있음)"
  fi
else
  echo "   미등록"
fi
echo

echo "🔹 Tailscale Funnel (영구 URL 옵션):"
if command -v tailscale >/dev/null 2>&1; then
  STATE=$(tailscale status --json 2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin).get("BackendState","?"))' 2>/dev/null || echo "?")
  echo "   BackendState: $STATE"
  DNS=$(tailscale status --json 2>/dev/null | python3 -c 'import sys,json; d=json.load(sys.stdin); print((d.get("Self") or {}).get("DNSName","").rstrip("."))' 2>/dev/null || echo "")
  [[ -n "$DNS" ]] && echo "   호스트:       https://$DNS"
  tailscale funnel status 2>&1 | head -3 | sed 's/^/   /'
else
  echo "   tailscale 미설치 (영구 URL 원하면 brew install --cask tailscale-app)"
fi
echo

echo "📝 로그: ~/Library/Logs/ytdlp-{backend,tunnel}.{out,err}.log"

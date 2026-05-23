#!/usr/bin/env bash
# 자동시작 해제 (백엔드 + 터널). 데이터는 건드리지 않음.
set -euo pipefail

for LABEL in com.user.ytdlp-backend com.user.ytdlp-tunnel; do
  PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
  echo "🛑 $LABEL 해제..."
  if [[ -f "$PLIST" ]]; then
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "   ✓ 제거"
  else
    echo "   (이미 없음)"
  fi
done

if command -v tailscale >/dev/null 2>&1; then
  echo "🌐 Tailscale Funnel 해제 (있다면)..."
  tailscale serve reset >/dev/null 2>&1 || true
fi

echo
echo "다운로드된 영상/메타데이터(~/yt-dlp-downloads)는 그대로입니다."
echo "다시 켜려면:"
echo "  bash $(dirname "${BASH_SOURCE[0]}")/setup-cloudflared.sh   # 즉시, URL 가변"
echo "  bash $(dirname "${BASH_SOURCE[0]}")/setup-anywhere.sh      # Tailscale 영구 URL (수동 1회 설정 필요)"

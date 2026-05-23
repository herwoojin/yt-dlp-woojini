#!/usr/bin/env bash
# 현재 활성 cloudflared quick tunnel URL을 출력.
# 터널이 재시작될 때마다 URL이 바뀌므로 외부에서 접속하기 전에 확인.
set -euo pipefail

LOG="$HOME/Library/Logs/ytdlp-tunnel.err.log"
[[ -f "$LOG" ]] || { echo "❌ 로그 없음: $LOG"; echo "   bash setup-cloudflared.sh 먼저 실행"; exit 1; }

URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | tail -1)
[[ -n "$URL" ]] || { echo "❌ URL을 찾지 못함. 터널이 살아있나요? launchctl list | grep ytdlp"; exit 1; }

if curl -fsS -o /dev/null --max-time 8 "$URL/health" 2>/dev/null; then
  echo "$URL"
else
  echo "$URL"
  echo "(⚠️  접속 실패 - 터널이 죽었거나 URL이 새로 발급됐을 수 있음. 재실행하세요)" >&2
  exit 2
fi

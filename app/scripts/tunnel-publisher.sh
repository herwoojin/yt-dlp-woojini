#!/usr/bin/env bash
# cloudflared quick tunnel을 띄우고:
#   1) 새 URL이 발급되면 app/frontend-html/tunnel.json에 자동 commit/push → Netlify 리빌드
#   2) 발급된 URL이 외부에서 응답 못 하면 (quick tunnel이 죽었는데 cloudflared는 살아있는
#      경우) cloudflared를 강제 종료 → launchd KeepAlive가 재시작하면서 새 URL 발급
set -u

REPO_DIR="/Users/heoujin/yt-dlp"
URL_FILE="$REPO_DIR/app/frontend-html/tunnel.json"
LOG="$HOME/Library/Logs/ytdlp-tunnel.err.log"
CLOUDFLARED="/opt/homebrew/bin/cloudflared"
REMOTE="woojini"
BRANCH="master"

HEALTH_INTERVAL=60        # 외부 health check 주기 (초)
HEALTH_FAIL_THRESHOLD=3   # 연속 실패 N회면 cloudflared 종료
HEALTH_GRACE=120          # 새 URL 발급 후 N초간은 health check 건너뜀

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

publish() {
  local url="$1"
  log "publishing new tunnel URL: $url"

  cat > "$URL_FILE" <<EOF
{
  "base": "$url",
  "updated": "$(date -u +%FT%TZ)"
}
EOF

  cd "$REPO_DIR" || { log "ERROR: cannot cd to $REPO_DIR"; return 1; }

  git pull --rebase --autostash "$REMOTE" "$BRANCH" 2>&1 | tail -3 | sed 's/^/  pull: /'

  git add "$URL_FILE"
  if git -c user.name='ytdlp-tunnel-bot' -c user.email='tunnel@local' \
       commit -m "auto: tunnel URL → ${url}" 2>&1 | tail -3 | sed 's/^/  commit: /'; then
    if git push "$REMOTE" "$BRANCH" 2>&1 | tail -3 | sed 's/^/  push: /'; then
      log "push OK → Netlify will rebuild"
    else
      log "push failed (URL written locally, frontend won't auto-update until next push)"
    fi
  else
    log "nothing to commit (URL unchanged or commit skipped)"
  fi
}

# Watcher: tail cloudflared log, publish whenever a new URL becomes reachable
watcher() {
  local prev=""
  if [ -f "$URL_FILE" ]; then
    prev=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$URL_FILE" | head -1 || true)
  fi

  while sleep 5; do
    [ -f "$LOG" ] || continue
    local url
    url=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" 2>/dev/null | tail -1)
    if [ -n "$url" ] && [ "$url" != "$prev" ]; then
      if curl -fsS -o /dev/null --max-time 8 "$url/health" 2>/dev/null; then
        publish "$url"
        echo "$(date +%s)" > /tmp/ytdlp-tunnel-published-at
        prev="$url"
      else
        log "URL $url not reachable yet, waiting..."
      fi
    fi
  done
}

# Healthcheck: periodically curl the currently-published URL from outside.
# If it fails HEALTH_FAIL_THRESHOLD times in a row, kill cloudflared so launchd
# restarts the whole script (and a fresh URL gets allocated).
healthcheck() {
  local fail_streak=0
  while sleep "$HEALTH_INTERVAL"; do
    [ -f "$URL_FILE" ] || continue
    local published_at=0
    [ -f /tmp/ytdlp-tunnel-published-at ] && published_at=$(cat /tmp/ytdlp-tunnel-published-at)
    local now elapsed
    now=$(date +%s)
    elapsed=$(( now - published_at ))
    if [ "$elapsed" -lt "$HEALTH_GRACE" ]; then
      # Fresh publish — skip checks during grace window
      continue
    fi
    local url
    url=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$URL_FILE" | head -1)
    [ -z "$url" ] && continue

    if curl -fsS -o /dev/null --max-time 10 "$url/health" 2>/dev/null; then
      fail_streak=0
    else
      fail_streak=$(( fail_streak + 1 ))
      log "health check fail #$fail_streak for $url"
      if [ "$fail_streak" -ge "$HEALTH_FAIL_THRESHOLD" ]; then
        log "URL dead $fail_streak times — killing cloudflared to force fresh tunnel"
        pkill -f "cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8000" 2>/dev/null
        # cloudflared exit will cause the main script to exit, launchd restarts everything
        return
      fi
    fi
  done
}

# Truncate logs so the watcher only sees this run's URLs
: > "$LOG"
: > "$HOME/Library/Logs/ytdlp-tunnel.out.log"
rm -f /tmp/ytdlp-tunnel-published-at

watcher &
WATCHER_PID=$!
healthcheck &
HEALTH_PID=$!
trap "kill $WATCHER_PID $HEALTH_PID 2>/dev/null || true" EXIT

log "starting cloudflared..."
"$CLOUDFLARED" tunnel --no-autoupdate --url http://127.0.0.1:8000 >> "$HOME/Library/Logs/ytdlp-tunnel.out.log" 2>> "$LOG"
log "cloudflared exited, watchers will be killed via trap (launchd will restart us)"

#!/usr/bin/env bash
# cloudflared quick tunnel을 띄우고, 새 URL이 발급되면 app/frontend-html/tunnel.json에
# 자동 커밋/푸시한다. Netlify가 리빌드되어 프론트는 항상 최신 URL을 자동으로 사용한다.
#
# launchd가 이 스크립트를 long-running 프로세스로 관리한다 (cloudflared가 죽으면
# 이 스크립트도 종료되고 KeepAlive로 인해 재시작 → 새 URL 발급 → 자동 게시).
set -u

REPO_DIR="/Users/heoujin/yt-dlp"
URL_FILE="$REPO_DIR/app/frontend-html/tunnel.json"
LOG="$HOME/Library/Logs/ytdlp-tunnel.err.log"
CLOUDFLARED="/opt/homebrew/bin/cloudflared"
REMOTE="woojini"
BRANCH="master"

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

  # Pull first to avoid conflicts with manual commits
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

# Watcher: tail the log, publish whenever a new URL appears
watcher() {
  local prev=""
  # If tunnel.json already has a URL, treat it as the previous so we don't republish on startup
  if [ -f "$URL_FILE" ]; then
    prev=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$URL_FILE" | head -1 || true)
  fi

  while sleep 5; do
    [ -f "$LOG" ] || continue
    local url
    url=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" 2>/dev/null | tail -1)
    if [ -n "$url" ] && [ "$url" != "$prev" ]; then
      # Verify the new URL is actually reachable before publishing
      if curl -fsS -o /dev/null --max-time 8 "$url/health" 2>/dev/null; then
        publish "$url"
        prev="$url"
      else
        log "URL $url not reachable yet, waiting..."
      fi
    fi
  done
}

# Truncate logs so the watcher only sees this run's URLs
: > "$LOG"
: > "$HOME/Library/Logs/ytdlp-tunnel.out.log"

watcher &
WATCHER_PID=$!
trap "kill $WATCHER_PID 2>/dev/null || true" EXIT

log "starting cloudflared..."
"$CLOUDFLARED" tunnel --no-autoupdate --url http://127.0.0.1:8000 >> "$HOME/Library/Logs/ytdlp-tunnel.out.log" 2>> "$LOG"
log "cloudflared exited, watcher will be killed via trap"

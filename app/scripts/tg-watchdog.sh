#!/bin/bash
# 텔레그램 봇 자가복구 백스톱.
# 30초마다 실행(LaunchAgent StartInterval). 다음 경우 백엔드를 재시작한다:
#   1) 백엔드(uvicorn)가 죽었을 때
#   2) 인터넷(api.telegram.org)은 도달 가능한데 봇 heartbeat가 90초 이상 멈췄을 때
#      (= WiFi가 끊겼다 붙었는데 폴링이 굳어버린 상태)
# 인터넷 자체가 끊긴 동안엔 재시작하지 않는다(복구되면 봇이 스스로 재개하거나 여기서 재시작).
export PATH=/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin

HB=/tmp/ytdlp-tg-heartbeat
LOG="$HOME/Library/Logs/ytdlp-tg-watchdog.log"
LABEL="com.user.ytdlp-backend"
UID_=$(id -u)

backend_up=0
curl -fsS --max-time 4 http://127.0.0.1:8000/health >/dev/null 2>&1 && backend_up=1

code=$(curl -s --max-time 8 -o /dev/null -w "%{http_code}" https://api.telegram.org 2>/dev/null)
net_up=0
[ -n "$code" ] && [ "$code" != "000" ] && net_up=1

now=$(date +%s)
hb=$(cat "$HB" 2>/dev/null || echo 0)
age=$(( now - hb ))

restart() {
  echo "$(date '+%F %T') $1 — restarting $LABEL" >> "$LOG"
  launchctl kickstart -k "gui/$UID_/$LABEL"
}

if [ "$backend_up" = "0" ]; then
  restart "backend DOWN"
  exit 0
fi

if [ "$net_up" = "1" ] && [ "$age" -gt 90 ]; then
  restart "net up but bot heartbeat stale ${age}s"
fi

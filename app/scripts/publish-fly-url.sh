#!/usr/bin/env bash
# Fly.io 배포된 백엔드 URL을 tunnel.json에 게시 → Netlify 자동 리빌드 →
# 프론트(25y.netlify.app)가 자동으로 새 URL 사용.
#
# 사용: bash publish-fly-url.sh https://ytdlp-25y.fly.dev
set -euo pipefail

URL="${1:-}"
[ -n "$URL" ] || { echo "usage: $0 <https://your-app.fly.dev>"; exit 1; }
URL="${URL%/}"

REPO_DIR="/Users/heoujin/yt-dlp"
URL_FILE="$REPO_DIR/app/frontend-html/tunnel.json"

echo "checking $URL/health ..."
if ! curl -fsS -m 15 "$URL/health" >/dev/null; then
  echo "❌ $URL/health 응답 없음. 배포 상태 확인하세요."
  exit 1
fi
echo "✓ 백엔드 응답 OK"

cat > "$URL_FILE" <<EOF
{
  "base": "$URL",
  "updated": "$(date -u +%FT%TZ)",
  "source": "fly.io"
}
EOF

cd "$REPO_DIR"
git add "$URL_FILE"
git -c user.name='ytdlp-deploy' -c user.email='deploy@local' \
    commit -m "auto: tunnel URL → $URL (fly.io)" || { echo "변경사항 없음"; exit 0; }
git push woojini master

echo
echo "✅ tunnel.json 업데이트 푸시 완료. 1~2분 후 Netlify가 리빌드되어 프론트가 새 URL 사용."
echo "   확인: open https://25y.netlify.app"

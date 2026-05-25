#!/usr/bin/env bash
# Fly.io 첫 셋업 + 배포 헬퍼.
# 처음 한 번 실행하면 launch → volume 생성 → deploy까지 자동으로 진행.
# 이후엔 `fly deploy` 만 실행해도 됨.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$APP_DIR"

step() { echo; echo "▶ $*"; }
warn() { echo "⚠️  $*" >&2; }
die()  { echo "❌ $*" >&2; exit 1; }

step "1/5 flyctl 설치 확인"
if ! command -v fly >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    echo "flyctl 미설치 → brew install flyctl 시도"
    brew install flyctl
  else
    die "flyctl 미설치. https://fly.io/docs/flyctl/install/ 참고하여 설치 후 재실행"
  fi
fi
fly version

step "2/5 로그인 상태 확인"
if ! fly auth whoami >/dev/null 2>&1; then
  warn "fly.io 로그인 필요. 브라우저가 열립니다."
  echo "   가입/로그인 후 결제 카드 등록까지 완료해주세요 (무료 티어 보호용)."
  fly auth login
fi
echo "logged in as: $(fly auth whoami)"

APP_NAME="$(awk -F\" '/^app = /{print $2}' fly.toml)"
[ -n "$APP_NAME" ] || die "fly.toml에서 app 이름을 못 읽음"

step "3/5 앱 생성 (이미 있으면 건너뜀): $APP_NAME"
if fly status -a "$APP_NAME" >/dev/null 2>&1; then
  echo "이미 존재함"
else
  # --no-deploy: 이미지 빌드는 다음 단계에서. --copy-config: 우리 fly.toml 사용.
  # --generate-name=false: 이름 충돌 시 launch가 알아서 새 이름 제안 → 다른 이름이면 fly.toml 수정 필요
  if ! fly apps create "$APP_NAME" 2>&1 | tee /tmp/fly-create.log; then
    if grep -qi "taken\|unavailable" /tmp/fly-create.log; then
      die "앱 이름 '$APP_NAME' 이 이미 사용 중입니다. fly.toml의 'app = ...' 줄을 다른 이름으로 바꾸고 재실행하세요."
    fi
    die "fly apps create 실패"
  fi
fi

REGION="$(awk -F\" '/^primary_region = /{print $2}' fly.toml)"
[ -n "$REGION" ] || REGION="nrt"

step "4/5 영구 저장소 볼륨 확인/생성 (region=$REGION)"
if fly volumes list -a "$APP_NAME" 2>/dev/null | grep -q "ytdlp_data"; then
  echo "ytdlp_data 볼륨 이미 존재"
else
  fly volumes create ytdlp_data --size 3 --region "$REGION" -a "$APP_NAME" --yes
fi

step "5/5 배포 (이미지 빌드 + push + machine 기동)"
fly deploy -a "$APP_NAME" --ha=false

echo
echo "════════════════════════════════════════════════"
echo "🌍 배포 완료!"
URL="https://${APP_NAME}.fly.dev"
echo "   $URL"
echo "════════════════════════════════════════════════"
echo
echo "다음 단계 후보:"
echo "  • 헬스체크:  curl $URL/health"
echo "  • 로그 보기: fly logs -a $APP_NAME"
echo "  • 시크릿 설정 (선택): fly secrets set GEMINI_API_KEY=AIza... -a $APP_NAME"
echo
echo "프론트엔드(25y.netlify.app)에서 새 URL을 자동으로 쓰게 하려면:"
echo "  bash $SCRIPT_DIR/publish-fly-url.sh $URL"

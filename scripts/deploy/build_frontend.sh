#!/usr/bin/env bash
# 프론트 빌드 산출물을 코드에 맞춘다 — 자동(autopull)·수동(deploy_to_mini) 두 배포 경로가
# **이 스크립트 하나를** 부른다 (#1462).
#
# 왜 하나인가: 2026-07-27 에 수동 경로(deploy_to_mini.sh 4단계)에만 재빌드를 넣고 자동 경로는
# WARN 로그로 사람에게 넘겼다. 사용자는 머지마다 수동 배포를 돌리지 않으므로 실제로 코드를
# 나르는 건 자동 경로다 — 2026-09-08 에 프로덕션이 9일 된 빌드(frontend/ 커밋 25건 · 취약
# 패키지 3개 미반영)를 서빙하고 있었고 헬스는 전부 초록이었다. 그 WARN 은 8/30 이후 17번
# 찍혔고 아무도 안 받았다. #940→#1023 의 데몬 재기동과 같은 비대칭이라 같은 처방을 쓴다:
# 로직은 한 곳에, 두 경로는 호출만.
#   잠금: tests/scripts/test_deploy_bounces_resident_services.py::TestBothPathsBuildTheFrontendTheSameWay
#   동작: tests/scripts/test_build_frontend.py (스크립트를 실행해서 본다)
#
# 판정: frontend/ 최신 커밋 시각 > .next/BUILD_ID mtime 이면 재빌드 (BUILD_ID 없음 = 0).
#       HEAD 가 안 움직여도 밀린·실패한 빌드를 self-heal 한다 — 호출자가 매 주기 불러도 된다.
#       package-lock.json 커밋 시각 > BUILD_ID mtime 이면 npm ci 를 먼저 한다.
#
# 롤백: Next.js 는 기본(cleanDistDir: true)으로 **빌드 시작 때 .next 를 비운다**
#       (next 16.3.3 dist/build/index.js:623 — cache|dev|lock|trace 만 남긴다). 즉 실패하면
#       디스크에 이전 빌드가 없다. 실행 중인 `next start` 는 메모리로 버티지만 KeepAlive 재기동
#       이나 재부팅이 오면 빌드 없는 대시보드가 뜬다. 그래서 .next 를 옆으로 옮겨 두고 빌드하고
#       실패하면 되돌린다. 성공하면 백업은 지운다 — 1.3GB 짜리를 커밋마다 쌓을 수 없다.
#
# 출력: 할 게 없으면 **아무것도 찍지 않는다** (autopull 이 5분마다 부른다).
# exit: 0 = 최신이거나 재빌드+검증 성공 / 1 = 실패 (이전 빌드 복원됨, 또는 재기동 후 무응답)
#
# 사용:
#   bash scripts/deploy/build_frontend.sh

set -u   # set -e 금지 — 실패 경로가 곧 롤백 경로다

REPO="${NURI_REPO:-$(cd "$(dirname "$0")/../.." && pwd)}"
FE="$REPO/frontend"
DASHBOARD_LABEL="com.nuri-quant.dashboard"
# 재기동 후 응답을 기다리는 최대 초. 테스트가 짧게 줄인다.
DASH_WAIT_SECS="${DASH_WAIT_SECS:-40}"
# launchd 도 비대화형 ssh 도 로그인 PATH 를 안 준다 — production 의 node/npm 은 homebrew 다
# (fnm 아님, 2026-07-07 실측). **뒤에** 붙인다: 폴백이지 우선순위가 아니다. 앞에 붙이면 dev
# 머신의 fnm 이나 테스트의 stub 을 homebrew 가 가린다 (실측: 테스트에서 진짜 npm 이 돌았다).
export PATH="$PATH:/opt/homebrew/bin"

cd "$REPO" || { echo "FATAL: $REPO 없음"; exit 1; }

# 파일 mtime (epoch). macOS 는 stat -f, Linux(CI 의 실행 테스트) 는 stat -c.
mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null || echo 0; }

LAST=$(git log -1 --format=%ct -- frontend/ 2>/dev/null)
LAST=${LAST:-0}
BUILT=$(mtime "$FE/.next/BUILD_ID")
if [ "$LAST" -le "$BUILT" ]; then
    exit 0   # 최신 — 조용히
fi

echo "[$(date '+%F %T')] frontend build stale: code $LAST > build $BUILT — rebuilding"

NPM_BIN=$(command -v npm 2>/dev/null || echo "/opt/homebrew/bin/npm")
if [ ! -x "$NPM_BIN" ]; then
    echo "ERROR: npm 을 못 찾음 ($NPM_BIN) — 빌드 불가, 이전 빌드 유지"
    exit 1
fi

cd "$FE" || { echo "FATAL: $FE 없음"; exit 1; }

LOCK=$(git log -1 --format=%ct -- package-lock.json 2>/dev/null)
if [ "${LOCK:-0}" -gt "$BUILT" ]; then
    echo "package-lock newer than build → npm ci"
    if ! "$NPM_BIN" ci --no-audit --no-fund; then
        echo "ERROR: npm ci 실패 — 빌드하지 않는다, 이전 빌드 유지"
        exit 1
    fi
fi

# 이전 실행이 빌드 도중 죽었으면(재부팅 등) 백업은 있고 .next 는 반쪽이다 — 먼저 되돌린다.
if [ -d .next.bak ] && [ ! -f .next/BUILD_ID ]; then
    rm -rf .next
    mv .next.bak .next
fi
# 백업은 고정 이름 하나 — 성공하면 지우고 실패하면 되돌린다.
rm -rf .next.bak
[ -d .next ] && mv .next .next.bak

if "$NPM_BIN" run build && [ -f .next/BUILD_ID ]; then
    rm -rf .next.bak
    echo "next build ok: BUILD_ID $(cat .next/BUILD_ID)"
else
    echo "ERROR: next build 실패 — 이전 빌드 복원"
    rm -rf .next
    [ -d .next.bak ] && mv .next.bak .next
    exit 1
fi

# 대시보드는 prebuilt 를 서빙하므로 재기동해야 새 빌드가 뜬다. launchd 에 없으면(dev 머신) 건너뛴다.
if ! command -v launchctl >/dev/null 2>&1 || ! launchctl list 2>/dev/null | grep -q "${DASHBOARD_LABEL}\$"; then
    echo "dashboard not installed — skip restart"
    exit 0
fi
if ! launchctl kickstart -k "gui/$(id -u)/${DASHBOARD_LABEL}"; then
    echo "ERROR: ${DASHBOARD_LABEL} kickstart 실패 — 새 빌드가 디스크에만 있다"
    exit 1
fi
for _ in $(seq 1 "$DASH_WAIT_SECS"); do
    if curl -sf -o /dev/null -m 3 http://127.0.0.1:3000/login; then
        echo "dashboard restarted: /login ok"
        exit 0
    fi
    sleep 1
done
echo "ERROR: dashboard 재기동 후 :3000 무응답 — data/logs/dashboard.err 확인"
exit 1

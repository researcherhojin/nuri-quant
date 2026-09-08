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
#       HEAD 가 안 움직여도 밀린 빌드를 self-heal 한다 — 호출자가 매 주기 불러도 된다.
#       package-lock.json 커밋 시각 > BUILD_ID mtime 이면 npm ci 를 먼저 한다.
#
# 롤백: Next.js 는 기본(cleanDistDir: true)으로 **빌드 시작 때 .next 를 비운다**
#       (next 16.3.3 dist/build/index.js:623 — cache|dev|lock|trace 만 남긴다). 즉 실패하면
#       디스크에 이전 빌드가 없다. 실행 중인 `next start` 도 안전하지 않다 — 라우트 번들은 첫
#       요청 때 require 되고 .next/static 은 디스크에서 읽으므로, 빌드 중에는 아직 안 밟은
#       라우트가 500/404 이고 그 사이 크래시하면 KeepAlive 재기동이 "no production build" 로
#       돈다. 그래서 .next 를 옆으로 옮겨 두고 빌드하고 실패하면 되돌린다. 성공하면 백업은
#       지운다. .next/cache 는 Next 가 보존하는 것과 같이 새 .next 로 옮겨 빌드가 cold 로
#       시작하지 않게 한다.
#
# 마커 (frontend/ 안, gitignored .next* 패턴):
#   .next.lock/           실행 중 — mkdir 원자 락 (bash 3.2 에 flock 없음). autopull 5분 주기와
#                         ssh 로 도는 deploy_to_mini 가 겹치면 두 번째가 `rm -rf .next.bak` 으로
#                         유일한 이전 빌드를 지운다 — 락 없이는 두 경로 공유가 오히려 위험하다.
#                         안의 pid 가 죽었으면(재부팅) 넘겨받는다.
#   .next.failed          빌드 실패한 frontend/ 커밋 sha. 같은 sha 면 **재시도하지 않는다** —
#                         결정적으로 깨진 커밋을 5분마다 다시 빌드하며 24/7 박스를 태울 이유가
#                         없다. 새 frontend/ 커밋이 오거나 `--retry`(deploy_to_mini 가 쓴다 —
#                         사람이 부른 배포는 곧 재시도 의사)면 지운다. 이 파일의 존재가 #1463
#                         감지기의 신호다.
#   .next.restart_pending 빌드는 됐는데 대시보드 재기동/응답 확인이 실패. 다음 주기에 빌드 없이
#                         재기동만 다시 한다 — 이게 없으면 새 BUILD_ID mtime 이 "최신" 으로 읽혀
#                         활성화 실패가 영영 재시도되지 않는다.
#
# 출력: 할 게 없으면 **아무것도 찍지 않는다** (autopull 이 5분마다 부른다).
# exit: 0 = 최신이거나 재빌드+검증 성공 / 1 = 실패 (이전 빌드 복원됨 · 재기동 후 무응답 · 락 점유)
#
# 사용:
#   bash scripts/deploy/build_frontend.sh [--retry]

set -u   # set -e 금지 — 실패 경로가 곧 롤백 경로다

RETRY=0
[ "${1:-}" = "--retry" ] && RETRY=1

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

# 파일 mtime (epoch). GNU(-c) 를 **먼저** 본다: BSD `stat -c` 는 stdout 에 아무것도 안 찍고
# 실패하지만, GNU `stat -f %m` 은 파일시스템 모드라 마운트 포인트("/")를 rc 0 으로 찍는다 —
# 그 순서면 CI(ubuntu) 에서 BUILT="/" 가 되어 모든 비교가 깨진다 (Codex 리뷰 재현, #1462).
mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0; }

LAST=$(git log -1 --format=%ct -- frontend/ 2>/dev/null)
LAST=${LAST:-0}
LAST_SHA=$(git log -1 --format=%H -- frontend/ 2>/dev/null)
BUILT=$(mtime "$FE/.next/BUILD_ID")
FAILED_MARK="$FE/.next.failed"
PENDING_MARK="$FE/.next.restart_pending"
LOCK_DIR="$FE/.next.lock"

NEED_BUILD=0
[ "$LAST" -gt "$BUILT" ] && NEED_BUILD=1
if [ "$NEED_BUILD" = "0" ] && [ ! -f "$PENDING_MARK" ]; then
    exit 0   # 최신 — 조용히
fi
if [ "$NEED_BUILD" = "1" ] && [ "$RETRY" = "0" ] && [ -f "$FAILED_MARK" ] \
    && [ "$(cat "$FAILED_MARK" 2>/dev/null)" = "$LAST_SHA" ]; then
    exit 0   # 같은 커밋에서 이미 실패 — 새 커밋이나 --retry 까지 조용히 둔다
fi

# ── 락 ──
take_lock() {
    if mkdir "$LOCK_DIR" 2>/dev/null; then
        echo $$ > "$LOCK_DIR/pid"
        return 0
    fi
    OTHER=$(cat "$LOCK_DIR/pid" 2>/dev/null || echo "")
    if [ -n "$OTHER" ] && kill -0 "$OTHER" 2>/dev/null; then
        echo "ERROR: 다른 빌드가 진행 중 (pid $OTHER) — 이번 실행은 건너뛴다"
        return 1
    fi
    # 죽은 pid 의 락 — 넘겨받는다 (재부팅 · kill 뒤)
    rm -rf "$LOCK_DIR"
    if mkdir "$LOCK_DIR" 2>/dev/null; then
        echo $$ > "$LOCK_DIR/pid"
        return 0
    fi
    echo "ERROR: 락을 못 잡음 ($LOCK_DIR)"
    return 1
}
take_lock || exit 1
trap 'rm -rf "$LOCK_DIR"' EXIT

cd "$FE" || { echo "FATAL: $FE 없음"; exit 1; }

# ── 빌드 ──
if [ "$NEED_BUILD" = "1" ]; then
    echo "[$(date '+%F %T')] frontend build stale: code $LAST > build $BUILT — rebuilding"
    rm -f "$FAILED_MARK"

    NPM_BIN=$(command -v npm 2>/dev/null || echo "/opt/homebrew/bin/npm")
    if [ ! -x "$NPM_BIN" ]; then
        echo "ERROR: npm 을 못 찾음 ($NPM_BIN) — 빌드 불가, 이전 빌드 유지"
        exit 1
    fi

    # 이전 실행이 빌드 도중 죽었으면(재부팅 등) 백업은 있고 .next 는 반쪽이다 — npm ci 게이트보다
    # **먼저** 되돌린다. npm ci 가 실패해 여기서 끝나도 반쪽을 남기지 않기 위해서다.
    if [ -d .next.bak ] && [ ! -f .next/BUILD_ID ]; then
        rm -rf .next
        mv .next.bak .next
    fi

    LOCK=$(git log -1 --format=%ct -- package-lock.json 2>/dev/null)
    if [ "${LOCK:-0}" -gt "$BUILT" ]; then
        echo "package-lock newer than build → npm ci"
        if ! "$NPM_BIN" ci --no-audit --no-fund; then
            echo "ERROR: npm ci 실패 — 빌드하지 않는다, 이전 빌드 유지"
            echo "$LAST_SHA" > "$FAILED_MARK"
            exit 1
        fi
    fi

    # 백업은 고정 이름 하나 — 성공하면 지우고 실패하면 되돌린다. 빌드 캐시는 새 .next 로 옮긴다
    # (Next 의 cleanDistDir 도 cache 는 남긴다 — 통째로 치우면 매 빌드가 cold 다).
    rm -rf .next.bak
    if [ -d .next ]; then
        mv .next .next.bak
        if [ -d .next.bak/cache ]; then
            mkdir -p .next && mv .next.bak/cache .next/cache
        fi
    fi

    if "$NPM_BIN" run build && [ -f .next/BUILD_ID ]; then
        rm -rf .next.bak
        echo "next build ok: BUILD_ID $(cat .next/BUILD_ID)"
        touch "$PENDING_MARK"
    else
        echo "ERROR: next build 실패 — 이전 빌드 복원 (같은 커밋 $LAST_SHA 은 재시도하지 않는다: 새 frontend 커밋 또는 --retry)"
        echo "$LAST_SHA" > "$FAILED_MARK"
        if [ -d .next.bak ]; then
            # 캐시는 새 .next 쪽에 있다 — 복원본으로 되돌려 다음 빌드도 warm 하게.
            if [ -d .next/cache ]; then
                rm -rf .next.bak/cache && mv .next/cache .next.bak/cache
            fi
            rm -rf .next
            mv .next.bak .next
        else
            rm -rf .next
        fi
        exit 1
    fi
else
    echo "[$(date '+%F %T')] frontend build current but dashboard restart pending — retrying restart"
fi

# ── 재기동 ──
# 대시보드는 prebuilt 를 서빙하므로 재기동해야 새 빌드가 뜬다. launchd 에 없으면(dev 머신) 건너뛴다.
if ! command -v launchctl >/dev/null 2>&1 || ! launchctl list 2>/dev/null | grep -q "${DASHBOARD_LABEL}\$"; then
    echo "dashboard not installed — skip restart"
    rm -f "$PENDING_MARK"
    exit 0
fi
if ! launchctl kickstart -k "gui/$(id -u)/${DASHBOARD_LABEL}"; then
    echo "ERROR: ${DASHBOARD_LABEL} kickstart 실패 — 새 빌드가 디스크에만 있다, 다음 주기에 재기동 재시도"
    exit 1
fi
i=0
while [ "$i" -lt "$DASH_WAIT_SECS" ]; do
    if curl -sf -o /dev/null -m 3 http://127.0.0.1:3000/login; then
        echo "dashboard restarted: /login ok"
        rm -f "$PENDING_MARK"
        exit 0
    fi
    sleep 1
    i=$((i + 1))
done
echo "ERROR: dashboard 재기동 후 :3000 무응답 — data/logs/dashboard.err 확인, 다음 주기에 재기동 재시도"
exit 1

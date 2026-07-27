#!/usr/bin/env bash
# MBP → Mac mini 전체 동기화 (1-command deploy)
#
# 사용법:
#   make deploy-mini                # 권장
#   bash scripts/deploy_to_mini.sh     # 직접
#
# 수행 내역:
#   1. SSH 연결 확인
#   2. 원격 git pull (ff-only)
#   3. config 동기화 (.env, portfolio.yaml, NEXT_SESSION.md — DB 제외)
#   4. frontend 재빌드 (.next 가 frontend/ 최신 커밋보다 오래됐을 때만) + dashboard 재기동
#   5. scheduler unload → uv sync --frozen (항상) → (6에서 load)
#   6. scheduler load (fresh importlib — 신규 패키지 + 코드 변경 모두 반영)
#   7. 최종 검증 (git HEAD, launchctl, scheduler --dry-run)
#
# 전제:
#   - DEV2_HOST 가 ~/.zshrc 에 설정 (e.g. ehbebe@Ehbebeui-Macmini.local)
#   - MBP → Mac mini SSH 키 등록됨
#   - Mac mini 에 ~/workspace/nuri-quant repo 존재
#
# shellcheck disable=SC2029

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# scripts/deploy/.. = scripts/, .. 한 번 더 → repo root.
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${PROJECT_ROOT}"

REMOTE="${DEV2_HOST:-}"
REMOTE_PATH="${DEV2_PATH:-~/workspace/nuri-quant}"
PLIST_NAME="com.nuri-quant.scheduler.plist"

# bare ssh 대신 공용 helper (#827) — ssh -4 강제 + .local 해석 실패 시 dscacheutil IPv4 fallback
SSH="${SCRIPT_DIR}/ssh_dev2.sh"

# ── 색상 ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

step() { echo -e "\n${CYAN}[$1/7]${NC} $2"; }
ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; exit 1; }

# ── 0. 사전 조건 ──
[[ -z "${REMOTE}" ]] && fail "DEV2_HOST 미설정. ~/.zshrc 에 export DEV2_HOST=ehbebe@Ehbebeui-Macmini.local 추가"

echo -e "${CYAN}═══ Nuri-Quant: MBP → Mac mini deploy ═══${NC}"
echo "  remote: ${REMOTE}:${REMOTE_PATH}"
echo "  local HEAD: $(git log -1 --oneline)"

# ── 1. SSH 연결 ──
step 1 "SSH 연결 확인"
if "${SSH}" -o BatchMode=yes -o ConnectTimeout=5 "${REMOTE}" "echo ok" >/dev/null 2>&1; then
    ok "연결 성공"
else
    fail "SSH 연결 실패. 네트워크/키 확인 필요"
fi

# ── 2. 원격 git pull ──
step 2 "원격 git pull (ff-only)"
REMOTE_BEFORE=$("${SSH}" "${REMOTE}" "cd ${REMOTE_PATH} && git rev-parse --short HEAD")
"${SSH}" "${REMOTE}" "cd ${REMOTE_PATH} && git fetch origin main --quiet && git merge --ff-only origin/main --quiet" 2>&1 || true
REMOTE_AFTER=$("${SSH}" "${REMOTE}" "cd ${REMOTE_PATH} && git rev-parse --short HEAD")

if [[ "${REMOTE_BEFORE}" == "${REMOTE_AFTER}" ]]; then
    ok "이미 최신 (${REMOTE_AFTER})"
else
    ok "${REMOTE_BEFORE} → ${REMOTE_AFTER}"
    CHANGED_FILES=$("${SSH}" "${REMOTE}" "cd ${REMOTE_PATH} && git diff --name-only ${REMOTE_BEFORE}..${REMOTE_AFTER}")
    echo "  변경 파일: $(echo "${CHANGED_FILES}" | wc -l | tr -d ' ')개"
fi

# ── 3. config 동기화 (DB 제외) ──
step 3 "config 동기화 (.env, portfolio.yaml, NEXT_SESSION.md)"
SYNC_COUNT=0
for f in .env config/portfolio.yaml NEXT_SESSION.md; do
    if [[ -f "${PROJECT_ROOT}/${f}" ]]; then
        # 원격 디렉토리 보장
        REMOTE_DIR=$(dirname "${REMOTE_PATH}/${f}")
        "${SSH}" "${REMOTE}" "mkdir -p ${REMOTE_DIR}" 2>/dev/null || true
        scp -q -S "${SSH}" "${PROJECT_ROOT}/${f}" "${REMOTE}:${REMOTE_PATH}/${f}"
        ok "${f}"
        SYNC_COUNT=$((SYNC_COUNT + 1))
    else
        warn "${f} 없음 (skip)"
    fi
done
echo "  ${SYNC_COUNT}개 파일 동기화"

# ── 4. frontend 재빌드 ──
# Why: 2026-07-27 실측 — mini 의 `.next` 가 2026-04-13 빌드였고 그 사이 frontend/
# 커밋 108 개가 미반영이었다. 배포 스크립트에 빌드 단계가 아예 없어 3.5 개월간
# 아무도 몰랐다. 증상은 조용하다 — 서버 컴포넌트는 빌드 시점에 인라인된
# NEXT_PUBLIC_API_URL 로 계속 동작하지만, next.config `rewrites()` 는 빌드 산출물
# (routes-manifest.json) 에 구워지므로 rewrite 도입 이전 빌드에서는 /api/* 가 전부
# 404. 즉 읽기 화면만 살고 클라이언트 쓰기·SSE 는 전멸한다.
# 판정: frontend/ 최신 커밋 시각 > .next mtime 이면 재빌드. HEAD 가 안 움직인
# 경우에도 (오늘처럼) 밀린 빌드를 self-heal 한다.
step 4 "frontend 빌드 확인"

DASHBOARD_PLIST_NAME="com.nuri-quant.dashboard.plist"
DASHBOARD_LABEL="${DASHBOARD_PLIST_NAME%.plist}"

BUILD_NEEDED=$("${SSH}" "${REMOTE}" "cd ${REMOTE_PATH} && LAST=\$(git log -1 --format=%ct -- frontend/ 2>/dev/null || echo 0); BUILT=\$(stat -f %m frontend/.next 2>/dev/null || echo 0); [ \"\${LAST:-0}\" -gt \"\${BUILT:-0}\" ] && echo yes || echo no")

if [[ "${BUILD_NEEDED}" == "yes" ]]; then
    warn "frontend 빌드가 코드보다 오래됨 → 재빌드 (수 분 소요)"
    # package-lock 이 빌드보다 새로우면 의존성부터 재설치.
    LOCK_NEWER=$("${SSH}" "${REMOTE}" "cd ${REMOTE_PATH} && LOCK=\$(git log -1 --format=%ct -- frontend/package-lock.json 2>/dev/null || echo 0); BUILT=\$(stat -f %m frontend/.next 2>/dev/null || echo 0); [ \"\${LOCK:-0}\" -gt \"\${BUILT:-0}\" ] && echo yes || echo no")
    if [[ "${LOCK_NEWER}" == "yes" ]]; then
        "${SSH}" "${REMOTE}" "export PATH=/opt/homebrew/bin:\$PATH && cd ${REMOTE_PATH}/frontend && npm ci --no-audit --no-fund" \
            || fail "npm ci 실패 — 'ssh ${REMOTE} \"cd ${REMOTE_PATH}/frontend && npm ci\"' 수동 확인"
        ok "npm ci 완료"
    fi
    "${SSH}" "${REMOTE}" "export PATH=/opt/homebrew/bin:\$PATH && cd ${REMOTE_PATH}/frontend && npm run build" \
        || fail "next build 실패 — 이전 .next 가 그대로 서비스 중이다 (dashboard 는 살아있음). 로그 확인 후 재시도"
    ok "next build 완료"

    "${SSH}" "${REMOTE}" "launchctl kickstart -k gui/\$(id -u)/${DASHBOARD_LABEL}" 2>/dev/null || true
    DASH_OK="no"
    for _ in $(seq 1 40); do
        if "${SSH}" "${REMOTE}" "curl -sf -o /dev/null -m 3 http://127.0.0.1:3000/login" 2>/dev/null; then
            DASH_OK="yes"; break
        fi
        sleep 1
    done
    if [[ "${DASH_OK}" == "yes" ]]; then
        ok "dashboard 재기동 + /login 응답 확인"
    else
        fail "dashboard 재기동 후 :3000 무응답 — 'ssh ${REMOTE} tail data/logs/dashboard.err' 확인"
    fi
else
    ok "frontend 빌드 최신 (재빌드 불필요)"
fi

# ── 5. scheduler bounce + uv sync --frozen (#574 + #576) ──
# 순서: scheduler stop → uv sync → scheduler start.
# Why bounce around sync:
#   1) launchd race (#576): sync 가 .venv 를 mutate 하는 동안 scheduler 가 import
#      하면 partial 상태 노출 가능. unload 로 KeepAlive 잠시 정지.
#   2) importlib stale cache (#576 본체): uv sync 로 신규 패키지 (예: hmmlearn)
#      추가돼도 이미 떠 있는 process 는 못 봄 — restart 가 유일한 정석.
#   3) 매 deploy 마다 fresh process 보장 → 코드 변경 reload 별도 trigger 불필요.
# Why always sync (#574): lock 일치 시 거의 no-op, 불일치 시 명시 abort 해
#   silent drift 차단. transient 인프라 (네트워크) 흡수 위해 1회 retry.
# Verify launchctl 동작 (#576 Codex Round 1 #1 blocker): legacy `launchctl
#   load/unload` 는 실제 stop/start 실패해도 0 반환할 수 있음. PID 확인 polling
#   으로 race 보장 실현. unload 후 PID 사라짐 / load 후 PID 살아남 verify.
# Trade-off (Codex Round 1 #2): 매 deploy 마다 ~수초 downtime. cron miss 가능성
#   있으나 (a) deploy 는 사용자 수동 이벤트 (자동 cron 아님), (b) trading hour 외
#   에 실행, (c) misfire_grace_time=300 가 부분 흡수. acceptable.
PLIST_REMOTE="\$HOME/Library/LaunchAgents/${PLIST_NAME}"
SCHEDULER_LABEL="${PLIST_NAME%.plist}"
SCHEDULER_INSTALLED=$("${SSH}" "${REMOTE}" "[ -f ${PLIST_REMOTE} ] && echo yes || echo no")

# launchctl PID 조회 — running 시 숫자, 미실행/미등록 시 빈 문자열
get_scheduler_pid() {
    "${SSH}" "${REMOTE}" "launchctl list 2>/dev/null | awk -v label='${SCHEDULER_LABEL}' '\$3==label && \$1 ~ /^[0-9]+\$/ { print \$1; exit }'" || true
}

# polling: 20초 동안 0.5초 간격으로 condition (gone|alive) 체크.
# Why 20s: launchd default ThrottleInterval=10s — KeepAlive bounce 시 첫 spawn
# 까지 최대 10s 지연 가능 (Codex Round 2 #1). 안전 margin 포함 20s 채택.
wait_scheduler() {
    local want="$1"  # "gone" | "alive"
    local elapsed=0
    while (( elapsed < 40 )); do
        local pid
        pid=$(get_scheduler_pid)
        if [[ "${want}" == "gone" && -z "${pid}" ]]; then return 0; fi
        if [[ "${want}" == "alive" && -n "${pid}" ]]; then echo "${pid}"; return 0; fi
        sleep 0.5
        elapsed=$((elapsed + 1))
    done
    return 1
}

# health verify: PID 잡힌 후 3초 동안 같은 PID 유지하는지 재확인.
# Why: scheduler 가 import 시 ModuleNotFoundError 로 즉시 die 하면 KeepAlive 가
# 새 PID 로 respawn 반복 (crash-loop). 단일 PID 관찰만으로는 healthy 보장 안 됨
# (Codex Round 2 #2). Stable PID for 3s = import + apscheduler.start() 까지 진행.
verify_stable_pid() {
    local first_pid="$1"
    sleep 3
    local now_pid
    now_pid=$(get_scheduler_pid)
    [[ "${now_pid}" == "${first_pid}" ]]
}

step 5 "scheduler bounce + 의존성 동기화"

# 5a. scheduler unload + verify PID 사라짐
if [[ "${SCHEDULER_INSTALLED}" == "yes" ]]; then
    "${SSH}" "${REMOTE}" "launchctl unload ${PLIST_REMOTE} 2>/dev/null" || true
    if wait_scheduler gone >/dev/null; then
        ok "scheduler unloaded (PID 사라짐 verified)"
    else
        fail "scheduler unload 실패 — PID 가 20초 후에도 살아 있음. 'ssh ${REMOTE} launchctl list | grep ${SCHEDULER_LABEL}' 로 수동 확인 후 재시도"
    fi
else
    warn "scheduler plist 미설치 → 4c 에서 초기 설치"
fi

# 5b. uv sync --frozen (항상 실행, 1회 retry)
# ssh non-interactive shell 은 ~/.zprofile 미로드 → homebrew PATH 누락. 명시 prepend 필수.
SYNC_CMD="export PATH=/opt/homebrew/bin:\$PATH && cd ${REMOTE_PATH} && uv sync --extra dev --frozen --quiet"
if "${SSH}" "${REMOTE}" "${SYNC_CMD}" 2>&1; then
    ok "uv sync --frozen 성공"
elif sleep 5 && "${SSH}" "${REMOTE}" "${SYNC_CMD}" 2>&1; then
    ok "uv sync --frozen 성공 (retry 1회 후)"
else
    # sync 실패 시 scheduler 재가동 시도 (이전 .venv 상태로라도 복구) 후 abort.
    # load + stable check — partial .venv 로 인한 crash-loop 도 감지.
    if [[ "${SCHEDULER_INSTALLED}" == "yes" ]]; then
        "${SSH}" "${REMOTE}" "launchctl load ${PLIST_REMOTE} 2>/dev/null" || true
        if RECOVERY_PID=$(wait_scheduler alive) && verify_stable_pid "${RECOVERY_PID}"; then
            warn "sync 실패 — 이전 .venv 상태로 scheduler 재가동 성공 (PID ${RECOVERY_PID} stable)"
        else
            warn "sync 실패 + scheduler 재가동 실패 또는 crash-loop — production downtime. SSH 로 'tail data/logs/scheduler.err' 확인 + 수동 복구 필요"
        fi
    fi
    fail "uv sync --frozen 실패 (1 retry 후) — uv.lock divergence 또는 transient 인프라 (네트워크/디스크). 로컬에서 'uv lock' 재생성 후 commit/push, 또는 Mac mini 에서 'rm -rf .venv && uv sync' 수동 복구"
fi

# 6a. scheduler load + verify PID 살아남
step 6 "scheduler 재기동"
if [[ "${SCHEDULER_INSTALLED}" == "no" ]]; then
    "${SSH}" "${REMOTE}" "mkdir -p ${REMOTE_PATH}/data/logs && cp ${REMOTE_PATH}/scripts/launchd/${PLIST_NAME} ${PLIST_REMOTE}"
    "${SSH}" "${REMOTE}" "launchctl load ${PLIST_REMOTE}"
else
    "${SSH}" "${REMOTE}" "launchctl load ${PLIST_REMOTE}"
fi

if NEW_PID=$(wait_scheduler alive) && verify_stable_pid "${NEW_PID}"; then
    ok "scheduler reloaded (fresh importlib, PID ${NEW_PID} stable for 3s)"
else
    fail "scheduler load 실패 또는 crash-loop — 20초 안에 stable PID 못 찾음. import error 가능성. 'ssh ${REMOTE} tail data/logs/scheduler.err' 확인 + 'launchctl load ${PLIST_REMOTE}' 수동 실행"
fi

# ── 6. 최종 검증 ──
step 7 "최종 검증"

REMOTE_HEAD=$("${SSH}" "${REMOTE}" "cd ${REMOTE_PATH} && git log -1 --oneline")
LOCAL_HEAD=$(git log -1 --oneline)
if [[ "${REMOTE_HEAD}" == "${LOCAL_HEAD}" ]]; then
    ok "git HEAD 일치: ${LOCAL_HEAD}"
else
    warn "git HEAD 불일치 — local: ${LOCAL_HEAD} / remote: ${REMOTE_HEAD}"
fi

SCHEDULER_PID=$("${SSH}" "${REMOTE}" "launchctl list | grep ${PLIST_NAME%.plist} | awk '{print \$1}'" 2>/dev/null || echo "-")
if [[ "${SCHEDULER_PID}" != "-" && "${SCHEDULER_PID}" != "" ]]; then
    ok "scheduler running (PID ${SCHEDULER_PID})"
else
    warn "scheduler 미실행 상태 — 수동 확인 필요"
fi

AUTOPULL_STATUS=$("${SSH}" "${REMOTE}" "launchctl list | grep autopull | awk '{print \$1}'" 2>/dev/null || echo "-")
ok "autopull: ${AUTOPULL_STATUS:-active}"

echo ""
echo -e "${GREEN}═══ deploy 완료 ═══${NC}"
echo "  git: ${REMOTE_HEAD}"
echo "  scheduler: PID ${SCHEDULER_PID:-unknown}"
echo "  config: ${SYNC_COUNT}개 동기화 (DB 제외)"
echo ""
echo "검증 명령 (Mac mini 에서):"
echo "  .venv/bin/python -m nuri.scheduler --dry-run"
echo "  tail -20 data/logs/scheduler.log"

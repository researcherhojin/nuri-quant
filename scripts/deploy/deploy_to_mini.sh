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
#   4. uv sync 확인 (lock 변경 시)
#   5. scheduler plist 설치 (미설치 시) + reload (scheduler.py 변경 시)
#   6. 최종 검증 (git HEAD, launchctl, scheduler --dry-run)
#
# 전제:
#   - DEV2_HOST 가 ~/.zshrc 에 설정 (e.g. ehbebe@Ehbebeui-Macmini.local)
#   - MBP → Mac mini SSH 키 등록됨
#   - Mac mini 에 ~/workspace/nuri-quant repo 존재
#
# shellcheck disable=SC2029

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

REMOTE="${DEV2_HOST:-}"
REMOTE_PATH="${DEV2_PATH:-~/workspace/nuri-quant}"
PLIST_NAME="com.nuri-quant.scheduler.plist"

# ── 색상 ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

step() { echo -e "\n${CYAN}[$1/6]${NC} $2"; }
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
if ssh -o BatchMode=yes -o ConnectTimeout=5 "${REMOTE}" "echo ok" >/dev/null 2>&1; then
    ok "연결 성공"
else
    fail "SSH 연결 실패. 네트워크/키 확인 필요"
fi

# ── 2. 원격 git pull ──
step 2 "원격 git pull (ff-only)"
REMOTE_BEFORE=$(ssh "${REMOTE}" "cd ${REMOTE_PATH} && git rev-parse --short HEAD")
ssh "${REMOTE}" "cd ${REMOTE_PATH} && git fetch origin main --quiet && git merge --ff-only origin/main --quiet" 2>&1 || true
REMOTE_AFTER=$(ssh "${REMOTE}" "cd ${REMOTE_PATH} && git rev-parse --short HEAD")

if [[ "${REMOTE_BEFORE}" == "${REMOTE_AFTER}" ]]; then
    ok "이미 최신 (${REMOTE_AFTER})"
else
    ok "${REMOTE_BEFORE} → ${REMOTE_AFTER}"
    CHANGED_FILES=$(ssh "${REMOTE}" "cd ${REMOTE_PATH} && git diff --name-only ${REMOTE_BEFORE}..${REMOTE_AFTER}")
    echo "  변경 파일: $(echo "${CHANGED_FILES}" | wc -l | tr -d ' ')개"
fi

# ── 3. config 동기화 (DB 제외) ──
step 3 "config 동기화 (.env, portfolio.yaml, NEXT_SESSION.md)"
SYNC_COUNT=0
for f in .env config/portfolio.yaml NEXT_SESSION.md; do
    if [[ -f "${PROJECT_ROOT}/${f}" ]]; then
        # 원격 디렉토리 보장
        REMOTE_DIR=$(dirname "${REMOTE_PATH}/${f}")
        ssh "${REMOTE}" "mkdir -p ${REMOTE_DIR}" 2>/dev/null || true
        scp -q "${PROJECT_ROOT}/${f}" "${REMOTE}:${REMOTE_PATH}/${f}"
        ok "${f}"
        SYNC_COUNT=$((SYNC_COUNT + 1))
    else
        warn "${f} 없음 (skip)"
    fi
done
echo "  ${SYNC_COUNT}개 파일 동기화"

# ── 4. uv sync --frozen (항상 실행, #574) ──
# 기존 로직: this-deploy 의 diff 에 uv.lock 이 있을 때만 sync — 누적 drift 미감지.
# 예) 이전 deploy 에서 lock 변경이 `|| warn` 으로 silently fail → 다음 deploy 의
# diff 엔 lock 없음 → 영영 미적용. hmmlearn 누락 사례 (2026-05-02).
# 수정: 매 deploy 마다 `uv sync --frozen --extra dev` 강제. lock 일치 시 거의 no-op,
# 불일치 시 명시 abort 해 silent drift 차단. transient 인프라 (네트워크) 흡수 위해
# 1회 retry 추가 (Codex review #584 Round 1 blocker #1).
#
# TODO #576: scheduler 가 launchd 로 동작 중 .venv 가 변경되면 race condition
# 가능성 — sync 전 launchctl unload, sync 후 launchctl load 로 보정 필요. 본 PR
# scope 외, 별 PR 로 해결.
step 4 "의존성 동기화 (uv sync --frozen, 항상 실행)"
SYNC_CMD="cd ${REMOTE_PATH} && uv sync --extra dev --frozen --quiet"
if ssh "${REMOTE}" "${SYNC_CMD}" 2>&1; then
    ok "uv sync --frozen 성공"
elif sleep 5 && ssh "${REMOTE}" "${SYNC_CMD}" 2>&1; then
    ok "uv sync --frozen 성공 (retry 1회 후)"
else
    fail "uv sync --frozen 실패 (1 retry 후) — uv.lock divergence 또는 transient 인프라 (네트워크/디스크). 로컬에서 'uv lock' 재생성 후 commit/push, 또는 Mac mini 에서 'rm -rf .venv && uv sync' 수동 복구"
fi

# ── 5. scheduler reload ──
step 5 "scheduler 관리"
PLIST_REMOTE="\$HOME/Library/LaunchAgents/${PLIST_NAME}"

# 5a. plist 설치 여부 확인
SCHEDULER_INSTALLED=$(ssh "${REMOTE}" "[ -f ${PLIST_REMOTE} ] && echo yes || echo no")
if [[ "${SCHEDULER_INSTALLED}" == "no" ]]; then
    warn "scheduler plist 미설치 → 초기 설치"
    ssh "${REMOTE}" "mkdir -p ${REMOTE_PATH}/data/logs && cp ${REMOTE_PATH}/scripts/${PLIST_NAME} ${PLIST_REMOTE}"
    ssh "${REMOTE}" "launchctl load ${PLIST_REMOTE}"
    ok "scheduler 초기 설치 + 로드 완료"
else
    # 5b. scheduler.py 변경 시에만 reload
    NEED_RELOAD="no"
    if [[ -n "${CHANGED_FILES:-}" ]] && echo "${CHANGED_FILES}" | grep -qE '^(nuri/scheduler\.py|config/agents\.yaml|config/rules\.yaml)$'; then
        NEED_RELOAD="yes"
    fi

    if [[ "${NEED_RELOAD}" == "yes" ]]; then
        ok "scheduler 관련 파일 변경 감지 → reload"
        ssh "${REMOTE}" "launchctl unload ${PLIST_REMOTE} 2>/dev/null; sleep 2; launchctl load ${PLIST_REMOTE}"
        ok "scheduler reloaded"
    else
        ok "scheduler 변경 없음 (reload skip)"
    fi
fi

# ── 6. 최종 검증 ──
step 6 "최종 검증"

REMOTE_HEAD=$(ssh "${REMOTE}" "cd ${REMOTE_PATH} && git log -1 --oneline")
LOCAL_HEAD=$(git log -1 --oneline)
if [[ "${REMOTE_HEAD}" == "${LOCAL_HEAD}" ]]; then
    ok "git HEAD 일치: ${LOCAL_HEAD}"
else
    warn "git HEAD 불일치 — local: ${LOCAL_HEAD} / remote: ${REMOTE_HEAD}"
fi

SCHEDULER_PID=$(ssh "${REMOTE}" "launchctl list | grep ${PLIST_NAME%.plist} | awk '{print \$1}'" 2>/dev/null || echo "-")
if [[ "${SCHEDULER_PID}" != "-" && "${SCHEDULER_PID}" != "" ]]; then
    ok "scheduler running (PID ${SCHEDULER_PID})"
else
    warn "scheduler 미실행 상태 — 수동 확인 필요"
fi

AUTOPULL_STATUS=$(ssh "${REMOTE}" "launchctl list | grep autopull | awk '{print \$1}'" 2>/dev/null || echo "-")
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

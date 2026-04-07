#!/bin/bash
# Mac mini receiver: 5분마다 origin/main을 fetch하고, HEAD가 바뀌면 ff-only merge.
#
# 트리거: ~/Library/LaunchAgents/com.nuri-quant.autopull.plist (StartInterval=300)
# 로그:   ~/Library/Logs/nuri-quant-autopull.log
#
# 동작:
#   1. fetch (실패 시 조용히 retry — 네트워크 끊김 대응)
#   2. 로컬 HEAD vs origin/main 비교
#   3. 변경 없으면 종료 (silent)
#   4. 변경 있으면 ff-only merge → 비-FF면 거부 + 로그 (수동 처리 유도)
#   5. 변경된 파일 분석 → dependency/schema 변경 시 경고
#   6. (선택) 24/7 서비스 재시작 hook — 현재는 placeholder
#
# 수동 테스트:
#   bash scripts/auto_deploy.sh
#
# 설치:
#   cp scripts/com.nuri-quant.autopull.plist ~/Library/LaunchAgents/
#   launchctl load ~/Library/LaunchAgents/com.nuri-quant.autopull.plist
#
# 상태 확인:
#   launchctl list | grep autopull
#   tail -f ~/Library/Logs/nuri-quant-autopull.log

set -u   # set -e 사용 안 함 — 한 단계 실패가 launchd 전체를 멈추게 하면 안 됨

REPO="/Users/ehbebe/workspace/nuri-quant"
LOG="$HOME/Library/Logs/nuri-quant-autopull.log"

mkdir -p "$(dirname "$LOG")"
cd "$REPO" || { echo "[$(date '+%F %T')] FATAL: $REPO 없음" >> "$LOG"; exit 0; }

ts() { date '+%F %T'; }
log() { echo "[$(ts)] $*" >> "$LOG"; }

# 로그 회전 — 1MB 넘으면 백업 후 새로 시작
if [ -f "$LOG" ] && [ "$(stat -f%z "$LOG" 2>/dev/null || echo 0)" -gt 1048576 ]; then
    mv "$LOG" "${LOG}.1"
    log "log rotated"
fi

BEFORE=$(git rev-parse HEAD 2>/dev/null || echo "unknown")

# fetch — non-interactive, git 자체 low-speed timeout (30초간 1KB/s 미만이면 abort)
# macOS 기본에 GNU timeout이 없으므로 git의 내장 timeout 변수 사용
if ! GIT_TERMINAL_PROMPT=0 GIT_HTTP_LOW_SPEED_LIMIT=1000 GIT_HTTP_LOW_SPEED_TIME=30 \
        git fetch origin main >/dev/null 2>&1; then
    log "fetch failed (network/timeout) — will retry next interval"
    exit 0
fi

UPSTREAM=$(git rev-parse origin/main 2>/dev/null || echo "unknown")

if [ "$BEFORE" = "$UPSTREAM" ]; then
    # 변경 없음 — 조용히 종료 (로그 줄이려고)
    exit 0
fi

# 새 커밋 발견
log "new commits detected: ${BEFORE:0:7}..${UPSTREAM:0:7}"
git log --oneline --no-decorate "${BEFORE}..${UPSTREAM}" 2>/dev/null | head -10 | while read -r line; do
    log "  $line"
done

# 로컬에 uncommitted 변경이 있으면 ff-only가 거부됨 — 명시적으로 체크
if ! git diff --quiet HEAD 2>/dev/null; then
    log "ABORT: uncommitted local changes present. Manual resolution needed:"
    log "  cd $REPO && git status"
    exit 0
fi

# ff-only merge
if ! git merge --ff-only origin/main >/dev/null 2>&1; then
    log "ABORT: non-fast-forward. Local diverged from origin/main."
    log "  cd $REPO && git status && git log --oneline -5"
    exit 0
fi

AFTER=$(git rev-parse HEAD)
log "updated to ${AFTER:0:7}"

# ── 변경 분석: 수동 조치가 필요한 변경이면 경고만 로그 ──────────────────
CHANGED=$(git diff --name-only "$BEFORE" "$AFTER" 2>/dev/null)

if echo "$CHANGED" | grep -qE "^(pyproject\.toml|uv\.lock)$"; then
    log "WARN: Python deps changed. Run manually:"
    log "  cd $REPO && uv sync --extra dev"
fi

if echo "$CHANGED" | grep -qE "^frontend/package(-lock)?\.json$"; then
    log "WARN: Frontend deps changed. Run manually:"
    log "  cd $REPO/frontend && npm ci"
fi

if echo "$CHANGED" | grep -qE "^(nuri/core/db\.py|scripts/migrate_db\.py)$"; then
    log "WARN: DB schema may have changed. Run manually:"
    log "  cd $REPO && .venv/bin/python scripts/migrate_db.py"
fi

if echo "$CHANGED" | grep -qE "^config/"; then
    log "INFO: config/ files changed. Verify rules/agents/portfolio still valid."
fi

# ── (B1) 서비스 재시작 hook ─────────────────────────────────────────────
# 현재는 24/7 서비스가 등록되어 있지 않아 no-op.
# API/dashboard/scheduler를 launchd로 띄우게 되면 아래에 추가:
#
#   launchctl kickstart -k "gui/$(id -u)/com.nuri-quant.api" 2>>"$LOG"
#   launchctl kickstart -k "gui/$(id -u)/com.nuri-quant.scheduler" 2>>"$LOG"
#
# 또는 nohup으로 띄우는 패턴이면:
#   pkill -f "uvicorn nuri.api" && nohup .venv/bin/python -m uvicorn nuri.api.main:app --port 8001 >>"$LOG" 2>&1 &
#
# 지금은 코드 변경만 반영하고 종료.
log "deploy hook: no services configured to restart (skipped)"

#!/usr/bin/env bash
# Nuri-Quant: dev↔dev 세션 동기화 헬퍼
#
# scripts/sync_dev.sh 위에 얇은 세션 워크플로 layer:
#   start   = 작업 시작 — 다른 머신 → 이 머신 (pull) + NEXT_SESSION.md
#   end     = 작업 종료 — 이 머신 → 다른 머신 (push) + NEXT_SESSION.md
#   status  = 양쪽 git HEAD + NEXT_SESSION.md 타임스탬프 비교 (read-only)
#
# 사용법 (Makefile 타겟 권장):
#   make sync-start   |  bash scripts/dev_sync.sh start
#   make sync-end     |  bash scripts/dev_sync.sh end
#   make sync-status  |  bash scripts/dev_sync.sh status
#
# DEV2_HOST 는 ~/.zshrc 에 머신마다 다른 값으로 export 되어 있어야 함
# (.env 에 두면 sync 시 cross-pollute 되므로 금지 — sync_dev.sh 헤더 참조).
#
# shellcheck disable=SC2029
# ^ ssh "…${REMOTE_PATH}…" client-side expansion intentional.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

ACTION="${1:-}"
shift || true

REMOTE_HOST="${DEV2_HOST:-}"
REMOTE_PATH="${DEV2_PATH:-~/workspace/nuri-quant}"

if [[ -z "${REMOTE_HOST}" ]]; then
    echo "❌ DEV2_HOST 미설정. ~/.zshrc 에 다음 한 줄 추가:"
    echo "   export DEV2_HOST=<other-mac>.local"
    exit 1
fi

usage() {
    cat <<EOF
사용법: bash scripts/dev_sync.sh {start|end|status} [options]

  start   다른 머신 → 이 머신 (작업 시작 시)
  end     이 머신 → 다른 머신 (작업 종료 시)
  status  양쪽 git HEAD + NEXT_SESSION.md 타임스탬프 비교

추가 옵션은 sync_dev.sh 그대로 통과 (--with-reports / --no-claude).
EOF
}

case "${ACTION}" in
    start)
        echo "=== sync start: pulling from ${REMOTE_HOST} ==="
        bash "${SCRIPT_DIR}/sync_dev.sh" pull "$@"
        if scp -q "${REMOTE_HOST}:${REMOTE_PATH}/NEXT_SESSION.md" ./NEXT_SESSION.md 2>/dev/null; then
            echo "✓ NEXT_SESSION.md synced"
        else
            echo "⚠ NEXT_SESSION.md skipped (not on remote)"
        fi
        echo "=== sync start done ==="
        ;;
    end)
        echo "=== sync end: pushing to ${REMOTE_HOST} ==="
        bash "${SCRIPT_DIR}/sync_dev.sh" push "$@"
        if [[ -f NEXT_SESSION.md ]]; then
            scp -q NEXT_SESSION.md "${REMOTE_HOST}:${REMOTE_PATH}/NEXT_SESSION.md" \
                && echo "✓ NEXT_SESSION.md synced"
        fi
        echo "=== sync end done ==="
        ;;
    status)
        echo "─── local ($(hostname -s)) ───"
        git log -1 --oneline 2>/dev/null || echo "(no git)"
        grep -E "^마지막 업데이트" NEXT_SESSION.md 2>/dev/null | head -1 \
            || echo "(no NEXT_SESSION.md timestamp)"
        echo "─── remote (${REMOTE_HOST}) ───"
        ssh -o BatchMode=yes -o ConnectTimeout=5 "${REMOTE_HOST}" \
            "cd ${REMOTE_PATH} 2>/dev/null && git log -1 --oneline && (grep -E '^마지막 업데이트' NEXT_SESSION.md 2>/dev/null | head -1)" \
            || echo "(remote unreachable)"
        ;;
    ""|-h|--help|help)
        usage
        ;;
    *)
        echo "❌ unknown action: ${ACTION}"
        usage
        exit 1
        ;;
esac

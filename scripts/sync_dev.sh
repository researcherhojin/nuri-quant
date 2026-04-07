#!/bin/bash
# Nuri-Quant: 두 dev 노트북 간 상태 동기화
#
# Git에 없는 파일만 옮긴다 (소스 코드는 git pull로):
#   - .env, config/portfolio.yaml
#   - data/portfolio.db (+ WAL/SHM)
#   - data/reports/ (--with-reports 옵션 시)
#   - ~/.claude/projects/.../ 전체 (대화 기록 + memory + per-session 상태)
#   - ~/.claude/ 전역 설정 (settings.json, skills/, plugins/, plans/, config/)
#     단, 캐시·런타임 상태(paste-cache, sessions, history.jsonl 등)는 제외
#
# 사용법:
#   scripts/sync_dev.sh push              # 이 노트북 → 다른 노트북
#   scripts/sync_dev.sh pull              # 다른 노트북 → 이 노트북
#   scripts/sync_dev.sh push --with-reports
#   scripts/sync_dev.sh push --no-claude     # Claude 상태 제외
#   DEV2_HOST=mybook.local scripts/sync_dev.sh push
#
# 사전 조건:
#   1. 양쪽 Mac 모두 Remote Login 활성화
#   2. ssh-copy-id로 키 등록 완료
#   3. .env에 DEV2_HOST / DEV2_USER / DEV2_PATH 설정 (또는 env var)

set -e

source .env 2>/dev/null || true

REMOTE_HOST="${DEV2_HOST:-}"
REMOTE_USER="${DEV2_USER:-$USER}"
REMOTE_PATH="${DEV2_PATH:-~/workspace/nuri-quant}"

DIRECTION="${1:-}"
WITH_REPORTS=false
SYNC_CLAUDE=true
for arg in "$@"; do
    [[ "$arg" == "--with-reports" ]] && WITH_REPORTS=true
    [[ "$arg" == "--no-claude" ]] && SYNC_CLAUDE=false
done

if [[ -z "$REMOTE_HOST" ]]; then
    echo "❌ DEV2_HOST가 설정되지 않았습니다."
    echo "   .env에 추가하거나 환경변수로 전달하세요:"
    echo "   DEV2_HOST=mybook.local scripts/sync_dev.sh push"
    exit 1
fi

if [[ "$DIRECTION" != "push" && "$DIRECTION" != "pull" ]]; then
    echo "사용법: $0 {push|pull} [--with-reports] [--no-claude]"
    echo "  push: 이 노트북 → ${REMOTE_USER}@${REMOTE_HOST}"
    echo "  pull: ${REMOTE_USER}@${REMOTE_HOST} → 이 노트북"
    exit 1
fi

LOCAL_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Sync ($DIRECTION) — ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH} ==="

# SSH 연결 확인
if ! ssh -o ConnectTimeout=5 "${REMOTE_USER}@${REMOTE_HOST}" "echo ok" >/dev/null 2>&1; then
    echo "❌ SSH 연결 실패: ${REMOTE_USER}@${REMOTE_HOST}"
    echo "   1) System Settings → Sharing → Remote Login 켜졌는지 확인"
    echo "   2) ssh-copy-id ${REMOTE_USER}@${REMOTE_HOST}"
    exit 1
fi

# 원격 $HOME 조회 (Claude 경로 계산용)
REMOTE_HOME="$(ssh "${REMOTE_USER}@${REMOTE_HOST}" 'echo $HOME')"
REMOTE_PATH_ABS="${REMOTE_PATH/#\~/$REMOTE_HOME}"

# Claude 프로젝트 디렉토리 hash (절대경로의 / → -)
LOCAL_PROJECT_HASH="$(echo "$LOCAL_ROOT" | sed 's|/|-|g')"
REMOTE_PROJECT_HASH="$(echo "$REMOTE_PATH_ABS" | sed 's|/|-|g')"
LOCAL_CLAUDE_PROJECT="$HOME/.claude/projects/${LOCAL_PROJECT_HASH}"
REMOTE_CLAUDE_PROJECT="${REMOTE_HOME}/.claude/projects/${REMOTE_PROJECT_HASH}"

# 전역 ~/.claude/ 에서 sync할 항목 (캐시·런타임 상태는 제외)
GLOBAL_CLAUDE_ITEMS=(
    "settings.json"
    "CLAUDE.md"
    "keybindings.json"
    "skills"
    "plugins"
    "plans"
    "config"
    "agents"
)

# DB 동시 수정 경고
echo ""
echo "⚠️  DB 동기화는 단방향 덮어쓰기입니다."
echo "    수신 측 portfolio.db 변경분이 손실될 수 있습니다."
read -p "    계속하시겠습니까? (y/N): " confirm
[[ "$confirm" == "y" || "$confirm" == "Y" ]] || { echo "취소됨"; exit 0; }

# 송신 측 DB WAL 체크포인트 (sqlite3가 있을 때만)
checkpoint_db() {
    local target_host="$1"
    local target_path="$2"
    if [[ "$target_host" == "local" ]]; then
        if command -v sqlite3 >/dev/null && [[ -f "$LOCAL_ROOT/data/portfolio.db" ]]; then
            echo "  로컬 DB WAL 체크포인트..."
            sqlite3 "$LOCAL_ROOT/data/portfolio.db" "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null
        fi
    else
        ssh "${REMOTE_USER}@${REMOTE_HOST}" \
            "command -v sqlite3 >/dev/null && [ -f ${target_path}/data/portfolio.db ] && sqlite3 ${target_path}/data/portfolio.db 'PRAGMA wal_checkpoint(TRUNCATE);' >/dev/null" \
            2>/dev/null || true
    fi
}

# Claude 상태 동기화 (Tier 3: 프로젝트 대화기록 + 전역 설정, 캐시 제외)
sync_claude_push() {
    if [[ -d "$LOCAL_CLAUDE_PROJECT" ]]; then
        echo "  → 프로젝트 Claude 디렉토리 (대화 기록 + memory)"
        ssh "${REMOTE_USER}@${REMOTE_HOST}" "mkdir -p '${REMOTE_CLAUDE_PROJECT}'"
        # --delete 미사용: 양쪽 머신의 대화 기록을 합치기 위해
        rsync -az --partial "${LOCAL_CLAUDE_PROJECT}/" \
            "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_CLAUDE_PROJECT}/"
    fi

    ssh "${REMOTE_USER}@${REMOTE_HOST}" "mkdir -p '${REMOTE_HOME}/.claude'"
    for item in "${GLOBAL_CLAUDE_ITEMS[@]}"; do
        local src="$HOME/.claude/$item"
        if [[ -e "$src" ]]; then
            echo "  → ~/.claude/$item"
            rsync -az --partial "$src" \
                "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_HOME}/.claude/"
        fi
    done
}

sync_claude_pull() {
    if ssh "${REMOTE_USER}@${REMOTE_HOST}" "[ -d '${REMOTE_CLAUDE_PROJECT}' ]" 2>/dev/null; then
        echo "  ← 프로젝트 Claude 디렉토리 (대화 기록 + memory)"
        mkdir -p "$LOCAL_CLAUDE_PROJECT"
        rsync -az --partial \
            "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_CLAUDE_PROJECT}/" \
            "${LOCAL_CLAUDE_PROJECT}/"
    fi

    mkdir -p "$HOME/.claude"
    for item in "${GLOBAL_CLAUDE_ITEMS[@]}"; do
        if ssh "${REMOTE_USER}@${REMOTE_HOST}" "[ -e '${REMOTE_HOME}/.claude/$item' ]" 2>/dev/null; then
            echo "  ← ~/.claude/$item"
            rsync -az --partial \
                "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_HOME}/.claude/$item" \
                "$HOME/.claude/"
        fi
    done
}

# 동기화할 파일 목록 (상대 경로)
FILES=(
    ".env"
    "config/portfolio.yaml"
    "data/portfolio.db"
    "data/portfolio.db-shm"
    "data/portfolio.db-wal"
)

RSYNC_OPTS="-avz --partial --progress --relative"

if [[ "$DIRECTION" == "push" ]]; then
    echo "송신 측 DB 체크포인트..."
    checkpoint_db "local" "$LOCAL_ROOT"

    echo ""
    echo "[1/3] 프로젝트 파일 전송: 이 노트북 → ${REMOTE_HOST}"
    cd "$LOCAL_ROOT"
    EXISTING=()
    for f in "${FILES[@]}"; do [[ -e "$f" ]] && EXISTING+=("$f"); done
    rsync $RSYNC_OPTS "${EXISTING[@]}" \
        "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}/"

    if $WITH_REPORTS && [[ -d data/reports ]]; then
        echo ""
        echo "[2/3] reports/ 전송 (--with-reports)"
        rsync -avz --partial --progress data/reports/ \
            "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}/data/reports/"
    else
        echo ""
        echo "[2/3] reports/ 스킵 (--with-reports 없음)"
    fi

    if $SYNC_CLAUDE; then
        echo ""
        echo "[3/3] Claude 상태 전송 (Tier 3)"
        sync_claude_push
    else
        echo ""
        echo "[3/3] Claude 상태 스킵 (--no-claude)"
    fi
else
    echo "송신 측 DB 체크포인트..."
    checkpoint_db "$REMOTE_HOST" "$REMOTE_PATH"

    echo ""
    echo "[1/3] 프로젝트 파일 수신: ${REMOTE_HOST} → 이 노트북"
    cd "$LOCAL_ROOT"
    rsync $RSYNC_OPTS --ignore-missing-args \
        $(printf "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}/./%s " "${FILES[@]}") \
        ./

    if $WITH_REPORTS; then
        echo ""
        echo "[2/3] reports/ 수신 (--with-reports)"
        mkdir -p data/reports
        rsync -avz --partial --progress \
            "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}/data/reports/" \
            data/reports/
    else
        echo ""
        echo "[2/3] reports/ 스킵 (--with-reports 없음)"
    fi

    if $SYNC_CLAUDE; then
        echo ""
        echo "[3/3] Claude 상태 수신 (Tier 3)"
        sync_claude_pull
    else
        echo ""
        echo "[3/3] Claude 상태 스킵 (--no-claude)"
    fi
fi

echo ""
echo "=== Sync 완료 ==="
echo "다음 단계 (수신 측에서):"
echo "  git pull && make verify-quick"

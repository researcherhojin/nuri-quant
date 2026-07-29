#!/usr/bin/env bash
# scripts/deploy/state_replicator.sh — State-Replicator-DR actor (#529 Phase 1).
#
# Codex Round 5 mandatory #1: Mac mini = single writer (PRIMARY).
# MBP = read-only replica.
#
# 작동 모드:
#   primary    — Mac mini 에서 실행. snapshot 만들고 MBP 에 push (rsync + checksum).
#   replica    — MBP 에서 실행. Mac mini snapshot pull (rsync + checksum 검증).
#   verify     — checksum 비교만, 변경 X.
#
# 호출 예:
#   scripts/state_replicator.sh primary
#   scripts/state_replicator.sh replica
#   scripts/state_replicator.sh verify
#
# 환경 변수:
#   DEV2_HOST          — 상대 머신 hostname (예: Ehbebeui-MacBookPro.local)
#   NURI_DB_PATH       — DB 경로 (default: data/portfolio.db)
#   NURI_REPLICA_PATH  — 복제본 path (default: data/replicas/portfolio_$(hostname).db)
#
# Exit: 0 OK / 1 mismatch (replica) / 2 setup error.

set -euo pipefail

# scripts/deploy/ 에 있으므로 두 단계 올라가야 repo root (#946 — #557 이동 때 안 고쳐졌다).
cd "$(dirname "$0")/../.."

MODE="${1:-verify}"
HOSTNAME=$(hostname -s)
HOSTNAME_LC=$(echo "$HOSTNAME" | tr '[:upper:]' '[:lower:]')
DB_PATH="${NURI_DB_PATH:-data/portfolio.db}"
REPLICAS_DIR="data/replicas"

# 원격 수신 경로 (#947). `host:relative/path` 는 **수신 측 홈** 기준으로 풀린다 —
# 보내는 쪽 cwd 와 무관하다. 그래서 예전 `$DEV2_HOST:$REPLICAS_DIR/...` 은 레포가 아니라
# `~/data/replicas/` 로 떨어졌다. 홈 기준 상대경로로 정규화해 레포 안에 착지시킨다.
REMOTE_REPO="${DEV2_PATH:-~/workspace/nuri-quant}"
REMOTE_REPO="${REMOTE_REPO#\~/}"  # 패턴의 ~ 를 escape — 안 하면 bash 가 홈으로 확장해 매칭 실패
REMOTE_REPLICAS="${REMOTE_REPO}/${REPLICAS_DIR}"
SNAPSHOTS_DIR="data/backups"
TS=$(date +%Y%m%d_%H%M%S)

mkdir -p "$REPLICAS_DIR" "$SNAPSHOTS_DIR"

# 머신 역할 검증
case "$HOSTNAME_LC" in
    *macmini*) MACHINE_ROLE="primary" ;;
    *macbook*|*mbp*) MACHINE_ROLE="replica" ;;
    *) MACHINE_ROLE="unknown" ;;
esac

echo "[state-replicator] mode=$MODE machine=$HOSTNAME role=$MACHINE_ROLE"

# DEV2_HOST 검증 (primary/replica 모드 시 필수)
if [ "$MODE" != "verify" ] && [ -z "${DEV2_HOST:-}" ]; then
    echo " ❌ DEV2_HOST not set — export to ~/.zshrc (NOT .env, sync_dev.sh 가 .env 복사함)"
    exit 2
fi

# Helper: DB 의 SHA256 + schema version + row count digest
db_digest() {
    local path="$1"
    .venv/bin/python -c "
import hashlib
import sqlite3
import sys

p = '$path'
if not __import__('os').path.exists(p):
    print('MISSING', file=sys.stderr); sys.exit(2)

# SHA256 of file bytes
h = hashlib.sha256()
with open(p, 'rb') as f:
    for chunk in iter(lambda: f.read(65536), b''):
        h.update(chunk)
sha = h.hexdigest()[:16]

# Schema version + row count summary
c = sqlite3.connect(p)
v = c.execute('SELECT MAX(version) FROM schema_version').fetchone()[0]
n = c.execute(\"SELECT COUNT(*) FROM sqlite_master WHERE type='table'\").fetchone()[0]
c.close()
print(f'sha={sha} schema={v} tables={n}')
"
}

case "$MODE" in
    primary)
        # PRIMARY: snapshot + push to replica
        if [ "$MACHINE_ROLE" != "primary" ]; then
            echo " ❌ primary mode 는 Mac mini 에서만 실행 (현재: $HOSTNAME)"
            exit 2
        fi
        SNAP="$SNAPSHOTS_DIR/snapshot_${TS}.db"
        echo "[primary] creating snapshot $SNAP"
        .venv/bin/python -c "
import sqlite3
from nuri.core.db import DB_PATH
c = sqlite3.connect(DB_PATH)
c.execute(\"VACUUM INTO '$SNAP'\")
c.close()
"
        DIGEST=$(db_digest "$SNAP")
        echo "[primary] digest: $DIGEST"
        echo "[primary] pushing to $DEV2_HOST"
        # 수신 측 디렉터리를 먼저 만든다 — macOS openrsync 는 목적지 디렉터리를
        # 자동 생성하지 않는다. 없으면 `open: No such file or directory` 로 죽는다 (#947).
        ssh -o BatchMode=yes "$DEV2_HOST" "mkdir -p '$REMOTE_REPLICAS'" || {
            echo " ❌ 원격 $REMOTE_REPLICAS 생성 실패 — SSH/권한 확인"
            exit 2
        }
        rsync -avz --partial "$SNAP" "$DEV2_HOST:$REMOTE_REPLICAS/portfolio_${HOSTNAME}.db" || {
            echo " ❌ rsync push failed"
            exit 2
        }
        echo "[primary] cleanup snapshot >7 days"
        find "$SNAPSHOTS_DIR" -name 'snapshot_*.db' -mtime +7 -delete 2>/dev/null || true
        echo " ✅ primary push OK ($DIGEST)"
        ;;

    replica)
        # REPLICA: verify primary 가 push 한 가장 최근 replica file
        if [ "$MACHINE_ROLE" = "primary" ]; then
            echo " ❌ replica mode 는 Mac mini 외에서 실행 (현재: PRIMARY)"
            exit 2
        fi
        # primary 가 rsync push 시 우리 disk 에 떨어짐 (sshd 수신).
        # 여기서는 가장 최근 replicas/*.db verify.
        # find -newer 로 가장 최근 mtime 추출 (SC2012 회피).
        LATEST_REPLICA=$(find "$REPLICAS_DIR" -name '*.db' -type f -print0 2>/dev/null | xargs -0 ls -t 2>/dev/null | head -1)
        if [ -z "$LATEST_REPLICA" ]; then
            echo " ⚠️  no replica file yet — primary push 대기"
            exit 1
        fi
        DIGEST=$(db_digest "$LATEST_REPLICA")
        echo "[replica] latest: $LATEST_REPLICA"
        echo "[replica] digest: $DIGEST"
        echo " ✅ replica verify OK"
        ;;

    verify)
        # VERIFY: 로컬 DB + 모든 replica file digest 출력
        if [ -f "$DB_PATH" ]; then
            echo "[verify] local DB ($DB_PATH):"
            db_digest "$DB_PATH" || echo "  (digest failed)"
        else
            echo "[verify] local DB ($DB_PATH): MISSING"
        fi
        echo "[verify] replicas in $REPLICAS_DIR:"
        if ls "$REPLICAS_DIR"/*.db >/dev/null 2>&1; then
            for f in "$REPLICAS_DIR"/*.db; do
                echo "  $f:"
                db_digest "$f" | sed 's/^/    /'
            done
        else
            echo "  (none)"
        fi
        ;;

    *)
        echo "usage: $0 {primary|replica|verify}"
        exit 2
        ;;
esac

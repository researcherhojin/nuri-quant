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
#   DEV2_HOST          — 상대 머신 hostname (예: macbook.local)
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
        # 정리는 스냅샷 생성·push 보다 먼저 한다 (#1576) — 로컬 보관 정책은 그 둘의 성공과
        # 무관하다. push 뒤에 있었을 때 push 실패의 `exit 2` 가 정리까지 건너뛰어, #1531 로
        # 3주 실패하는 동안 스냅샷 717개 · 161G 가 쌓였다. VACUUM 뒤여도 같다 — 디스크가
        # 차서 VACUUM 이 죽으면 `set -e` 가 정리를 건너뛰어 디스크가 영영 안 비워진다.
        echo "[primary] cleanup snapshot >7 days"
        find "$SNAPSHOTS_DIR" -name 'snapshot_*.db' -mtime +7 -delete 2>/dev/null || true
        # 48시간이 지난 스냅샷은 날짜별 최신 1개만 둔다. 매시 사본을 7일 내내 두면 개당 ~320MB ×
        # 168 = 54GB 였다(2026-10-27 mini 실측 60.1GB / 192개). 최근 48시간은 매시 그대로.
        # 이름(snapshot_YYYYMMDD_HHMMSS)을 역순 정렬해 날짜가 바뀔 때 처음 본 것(그날 최신)을 남긴다.
        # launchd 의 /bin/bash 는 3.2 라 연관 배열 없이 쓴다.
        echo "[primary] thin snapshots older than 48h to one per day"
        prev_day=""
        while IFS= read -r snap_old; do
            snap_day=$(basename "$snap_old" | cut -c10-17)
            if [ "$snap_day" = "$prev_day" ]; then
                rm -f "$snap_old"
            else
                prev_day="$snap_day"
            fi
        done < <(find "$SNAPSHOTS_DIR" -name 'snapshot_*.db' -mtime +1 2>/dev/null | sort -r)
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
        # 단 레포 자체는 만들지 않는다 (#1870): MBP 레포가 옮겨졌는데 `DEV2_PATH` 가 옛 경로면
        # `mkdir -p` 가 그 경로를 통째로 되살려 push 가 아무도 안 읽는 곳에 "성공" 하고,
        # `.last_push_ok` 가 계속 찍혀 `_detect_replica_stale` 이 울리지 못했다 (75.7 시간).
        # 여기서 실패하면 마커가 멈춰 그 경보가 산다.
        ssh -o BatchMode=yes "$DEV2_HOST" "test -e '$REMOTE_REPO/.git' && mkdir -p '$REMOTE_REPLICAS'" || {
            echo " ❌ 원격 $REMOTE_REPO 가 레포가 아니거나 $REMOTE_REPLICAS 생성 실패 — DEV2_PATH(~/.zshrc) · SSH/권한 확인"
            exit 2
        }
        rsync -avz --partial "$SNAP" "$DEV2_HOST:$REMOTE_REPLICAS/portfolio_${HOSTNAME}.db" || {
            echo " ❌ rsync push failed"
            exit 2
        }
        # 성공 시각 마커 — `_detect_replica_stale` 이 이 mtime 만 본다 (#1531). 로그를 파싱하지
        # 않는 이유: 이 잡은 실패해도 로그에 계속 쓰므로 "최근 줄이 있다" 가 성공을 뜻하지
        # 않는다. 실제로 9 일간 매시간 실패 줄이 쌓였다. rsync 가 0 을 낸 뒤에만 찍는다.
        touch "$REPLICAS_DIR/.last_push_ok"
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

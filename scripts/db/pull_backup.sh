#!/usr/bin/env bash
# 원장 백업 오프머신 사본 — Mac mini → MBP (#835)
#
# §3.11 판정 원장은 Mac mini 단일 SQLite 다. mini 의 `data/backups/` 는 같은
# 디스크·같은 머신이라 머신 자체가 죽으면 원장과 백업이 **함께** 사라진다.
# 이 스크립트가 최신 스냅샷 1벌을 MBP 로 당겨 그 단일 실패점을 없앤다.
#
# 클라우드 금지 (§4.4 sovereignty): 개인 금융 데이터이므로 외부 업로드를 하지
# 않는다. 오프머신 = 사용자가 이미 소유한 두 번째 머신 뿐이다.
#
# 무결성: mini 가 기록한 .sha256 을 같이 받아 **로컬에서 재계산해 대조**한다.
# 전송 중 손상은 물론, mini 쪽 파일이 이미 깨져 있었다면 여기서도 걸린다
# (backup.sh 가 생성 직후 integrity_check 를 하지만 이중 확인).
#
# 사용법:
#   bash scripts/db/pull_backup.sh          # 최신 1벌
#   KEEP=5 bash scripts/db/pull_backup.sh   # 로컬 보관 개수 조정 (기본 3)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
SSH="$PROJECT_DIR/scripts/deploy/ssh_dev2.sh"

REMOTE="${DEV2_HOST:-}"
REMOTE_PATH="${DEV2_PATH:-~/workspace/nuri-quant}"
LOCAL_DIR="$PROJECT_DIR/data/backups/offsite"
KEEP="${KEEP:-3}"

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1" >&2; exit 1; }

[ -z "$REMOTE" ] && fail "DEV2_HOST 미설정 (~/.zshrc 에 export)"
[ -x "$SSH" ] || fail "ssh helper 없음: $SSH"

echo "원장 백업 오프머신 사본 — ${REMOTE} → MBP"

# ── 1. 원격 최신 스냅샷 이름 ──
LATEST=$(bash "$SSH" "$REMOTE" "cd ${REMOTE_PATH} && ls -t data/backups/portfolio_*.db 2>/dev/null | head -1 | xargs -r basename") \
    || fail "원격 조회 실패 (SSH/네트워크 확인)"
[ -z "$LATEST" ] && fail "원격에 백업 없음 — mini 에서 'bash scripts/db/backup.sh' 확인"
ok "최신 스냅샷: $LATEST"

mkdir -p "$LOCAL_DIR"
if [ -f "$LOCAL_DIR/$LATEST" ]; then
    ok "이미 보유 — 전송 생략"
else
    scp -q -S "$SSH" "$REMOTE:${REMOTE_PATH}/data/backups/$LATEST" "$LOCAL_DIR/$LATEST" \
        || fail "스냅샷 전송 실패"
    scp -q -S "$SSH" "$REMOTE:${REMOTE_PATH}/data/backups/$LATEST.sha256" "$LOCAL_DIR/$LATEST.sha256" \
        || fail "체크섬 전송 실패"
    ok "전송 완료 ($(du -h "$LOCAL_DIR/$LATEST" | cut -f1))"
fi

# ── 2. 체크섬 대조 (원격 기록 vs 로컬 재계산) ──
EXPECTED=$(awk '{print $1}' "$LOCAL_DIR/$LATEST.sha256")
ACTUAL=$(shasum -a 256 "$LOCAL_DIR/$LATEST" | awk '{print $1}')
[ "$EXPECTED" = "$ACTUAL" ] || fail "체크섬 불일치 — 전송 손상 또는 원본 손상. 재시도 후에도 같으면 mini 백업 점검"
ok "체크섬 일치"

# ── 3. 실제로 열리는지 (체크섬이 맞아도 논리적으로 깨질 수 있다) ──
PYTHON="$PROJECT_DIR/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"
"$PYTHON" - "$LOCAL_DIR/$LATEST" <<'PY' || fail "무결성 검증 실패 — 이 사본은 복원에 쓸 수 없다"
import sqlite3
import sys

# `mode=ro` 금지 — 스냅샷은 원본의 WAL journal_mode 를 물려받는데, WAL DB 를
# read-only 로 열면 `-shm` 을 만들 수 없어 "unable to open database file" 이 난다.
c = sqlite3.connect(sys.argv[1])
try:
    status = c.execute("PRAGMA integrity_check").fetchone()[0]
    if status != "ok":
        raise SystemExit(f"integrity_check: {status}")
    n = c.execute("SELECT COUNT(*) FROM decision_outcomes").fetchone()[0]
    print(f"  verified: integrity=ok decision_outcomes={n}")
finally:
    c.close()
PY

# ── 4. 로컬 보관 개수 유지 (오프머신 벌은 최신 몇 개면 충분) ──
# shellcheck disable=SC2012  # 파일명은 스크립트가 만든 타임스탬프 패턴이라 안전
ls -t "$LOCAL_DIR"/portfolio_*.db 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
    rm -f "$old" "$old.sha256"
    echo "  정리: $(basename "$old")"
done

HELD=$(find "$LOCAL_DIR" -maxdepth 1 -name 'portfolio_*.db' | wc -l | tr -d ' ')
echo -e "${GREEN}오프머신 사본 완료${NC} → $LOCAL_DIR (${HELD}벌 보관)"

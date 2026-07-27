#!/usr/bin/env bash
# Nuri-Quant DB 백업 — 30일 롤링 + 생성 직후 무결성 검증 (#835)
#
# WAL 안전성: 예전에는 `cp` 였다. WAL 모드에서는 커밋된 트랜잭션이 아직
# `portfolio.db-wal` 에 있을 수 있고 `cp` 는 그 파일을 안 가져간다 — writer 가
# 연결돼 있는 순간에 돌면 최근 커밋이 빠지거나 체크포인트와 경쟁해 찢어진
# 스냅샷이 나온다. 평소엔 사이드카가 없어 우연히 맞았을 뿐 **보장이 아니었다.**
# 이제 SQLite online backup API(`.backup`)를 쓴다 — reader 로 열어 WAL 을 포함한
# 일관된 스냅샷을 만들고, 진행 중인 writer 를 막지도 않는다.
#
# 검증: SHA256 은 "복사 후 파일이 안 바뀜"만 증명한다 — 애초에 깨진 스냅샷을
# 떴는지는 말해주지 않는다(거짓 안심). 그래서 만든 직후 `integrity_check` +
# 원장 테이블 존재/행수를 확인하고, 실패하면 산출물을 지우고 exit 1 한다.
# 조용히 성공한 척하는 백업이 백업 없는 것보다 위험하다.
set -euo pipefail

# scripts/db/ 로 이동 (#557) 후 repo root 는 두 단계 위 (#836 경로 drift fix)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

BACKUP_DIR="$PROJECT_DIR/data/backups"
DB_FILE="${NURI_DB_PATH:-$PROJECT_DIR/data/portfolio.db}"
DATE=$(date +%Y%m%d_%H%M%S)
OUT="$BACKUP_DIR/portfolio_${DATE}.db"

# venv python 우선 (launchd 는 ~/.zprofile 미로드 → PATH 최소)
PYTHON="$PROJECT_DIR/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"

if [ ! -f "$DB_FILE" ]; then
    echo "DB 파일 없음: $DB_FILE" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"

# ── 스냅샷 + 검증 (한 프로세스에서) ──
# 원장 테이블은 §3.11 판정의 근거다. 하나라도 없으면 스냅샷이 쓸모없으므로 실패.
# ⚠ `if !` 로 감싼다. `set -e` 하에서 그냥 호출하면 python 이 실패하는 즉시
# 스크립트가 죽어 아래 정리(rm)에 **도달하지 못하고** 깨진 산출물이 남는다.
# if 조건부 안에서는 set -e 가 유예된다.
if ! "$PYTHON" - "$DB_FILE" "$OUT" <<'PY'
import sqlite3
import sys
from pathlib import Path

src_path, out_path = sys.argv[1], Path(sys.argv[2])
LEDGER_TABLES = ("decision_outcomes", "decisions", "recommendations", "portfolio")

# ⚠ 원본은 read-write 로 연다. WAL DB 를 `mode=ro` 로 열면 `-shm` 공유메모리
# 파일을 만들 수 없어 "unable to open database file" 이 난다 — writer 가 아무도
# 안 붙어 있는 상태(백업 시각의 정상 케이스)에서 정확히 그렇다.
# backup API 는 원본에 쓰지 않으므로 read-write 핸들이어도 안전하다.
src = sqlite3.connect(src_path)
dst = sqlite3.connect(str(out_path))
try:
    src.backup(dst)  # online backup API — WAL 포함 일관 스냅샷
finally:
    dst.close()
    src.close()

# 스냅샷은 원본의 WAL journal_mode 를 물려받으므로 여기서도 `mode=ro` 는 못 쓴다
# (같은 -shm 이유). 검증 전용 연결이라 쓰기는 발생하지 않는다.
check = sqlite3.connect(str(out_path))
try:
    status = check.execute("PRAGMA integrity_check").fetchone()[0]
    if status != "ok":
        raise SystemExit(f"integrity_check 실패: {status}")
    counts = []
    for t in LEDGER_TABLES:
        try:
            n = check.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: S608 (고정 리스트)
        except sqlite3.Error as e:
            raise SystemExit(f"원장 테이블 {t} 읽기 실패: {e}") from e
        counts.append(f"{t}={n}")
finally:
    check.close()
print("  verified: integrity=ok " + " ".join(counts))
PY
then
    # 검증 실패한 산출물은 남기지 않는다 — 나중에 '최신 백업' 으로 집히면
    # 복원 시점에야 깨진 걸 알게 된다.
    rm -f "$OUT"
    echo "백업 검증 실패 → 산출물 삭제. 원장 상태 점검 필요." >&2
    exit 1
fi

shasum -a 256 "$OUT" > "$OUT.sha256"

# 30일 이전 백업 삭제
find "$BACKUP_DIR" -name "portfolio_*.db" -mtime +30 -delete
find "$BACKUP_DIR" -name "portfolio_*.db.sha256" -mtime +30 -delete

echo "Backup complete: portfolio_${DATE}.db (verified + checksum recorded)"

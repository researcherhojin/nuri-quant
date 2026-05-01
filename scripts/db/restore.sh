#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
# Nuri-Quant DB 복원 — 백업에서 portfolio.db 복원
#
# 사용법:
#   bash scripts/restore.sh                    # 최신 백업 복원
#   bash scripts/restore.sh portfolio_20260330_120000.db  # 특정 백업 복원
# ═══════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

BACKUP_DIR="$PROJECT_DIR/data/backups"
DB_FILE="$PROJECT_DIR/data/portfolio.db"

# 백업 파일 선택. backup 파일은 portfolio_YYYYMMDD_HHMMSS.db 포맷이라 파일명
# 사전순 = 시간순. find + sort로 ls 파싱 회피 (SC2012).
if [ -n "${1:-}" ]; then
    BACKUP_FILE="$BACKUP_DIR/$1"
else
    BACKUP_FILE=$(find "$BACKUP_DIR" -maxdepth 1 -name "portfolio_*.db" -type f 2>/dev/null \
        | sort -r | head -1)
fi

if [ -z "$BACKUP_FILE" ] || [ ! -f "$BACKUP_FILE" ]; then
    echo "❌ 백업 파일 없음: $BACKUP_FILE"
    echo "사용 가능한 백업:"
    find "$BACKUP_DIR" -maxdepth 1 -name "portfolio_*.db" -type f 2>/dev/null \
        | sort -r | head -5 \
        | awk '{print "  " $0}' \
        || echo "  (없음)"
    exit 1
fi

echo "복원할 백업: $(basename "$BACKUP_FILE")"

# checksum 검증
CHECKSUM_FILE="${BACKUP_FILE}.sha256"
if [ -f "$CHECKSUM_FILE" ]; then
    if shasum -a 256 -c "$CHECKSUM_FILE" >/dev/null 2>&1; then
        echo "✅ Checksum 검증 통과"
    else
        echo "❌ Checksum 불일치 — 백업 파일 손상 가능"
        exit 1
    fi
else
    echo "⚠️  Checksum 파일 없음 (검증 생략)"
fi

# 현재 DB 백업 (안전장치)
if [ -f "$DB_FILE" ]; then
    SAFE_BACKUP="$BACKUP_DIR/pre_restore_$(date +%Y%m%d_%H%M%S).db"
    cp "$DB_FILE" "$SAFE_BACKUP"
    echo "현재 DB 백업: $(basename "$SAFE_BACKUP")"
fi

# 복원
cp "$BACKUP_FILE" "$DB_FILE"
echo "✅ 복원 완료: $(basename "$BACKUP_FILE") → portfolio.db"

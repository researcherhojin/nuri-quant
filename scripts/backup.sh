#!/usr/bin/env bash
# Nuri-Quant DB 백업 — 30일 롤링
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

BACKUP_DIR="$PROJECT_DIR/data/backups"
DB_FILE="$PROJECT_DIR/data/portfolio.db"
DATE=$(date +%Y%m%d_%H%M%S)

if [ ! -f "$DB_FILE" ]; then
    echo "DB 파일 없음: $DB_FILE"
    exit 1
fi

mkdir -p "$BACKUP_DIR"
cp "$DB_FILE" "$BACKUP_DIR/portfolio_${DATE}.db"

# SHA256 checksum 기록
shasum -a 256 "$BACKUP_DIR/portfolio_${DATE}.db" > "$BACKUP_DIR/portfolio_${DATE}.db.sha256"

# 30일 이전 백업 삭제
find "$BACKUP_DIR" -name "portfolio_*.db" -mtime +30 -delete
find "$BACKUP_DIR" -name "portfolio_*.db.sha256" -mtime +30 -delete

echo "Backup complete: portfolio_${DATE}.db (checksum recorded)"

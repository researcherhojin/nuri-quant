#!/usr/bin/env bash
# Nuri-Quant: Dev Machine → Mac Mini (Production) 배포
#
# shellcheck disable=SC2029
# ^ ssh "… ${REMOTE_PATH} …" — client-side expansion intentional.
set -euo pipefail

# shellcheck disable=SC1091
if [ -f .env ]; then source .env; fi

REMOTE_HOST="${MACMINI_HOST:-macmini.local}"
REMOTE_USER="${MACMINI_USER:-ehbebe}"
REMOTE_PATH="${MACMINI_PATH:-~/nuri-quant}"

echo "=== Deploying Nuri-Quant to Mac Mini ($REMOTE_USER@$REMOTE_HOST) ==="

# SSH 연결 확인
if ! ssh -o ConnectTimeout=5 "${REMOTE_USER}@${REMOTE_HOST}" "echo ok" >/dev/null 2>&1; then
    echo "❌ SSH 연결 실패: ${REMOTE_USER}@${REMOTE_HOST}"
    exit 1
fi

# 자동 백업 (배포 전)
echo "배포 전 DB 백업..."
ssh "${REMOTE_USER}@${REMOTE_HOST}" "cd ${REMOTE_PATH} && bash scripts/db/backup.sh" 2>/dev/null || echo "  (리모트 백업 스킵 — 최초 배포일 수 있음)"

# rsync 코드 (DB, .env, .venv, 개인 설정 제외)
rsync -avz --delete \
    --exclude '.venv' \
    --exclude 'data/portfolio.db' \
    --exclude 'data/backups' \
    --exclude 'data/exports' \
    --exclude '.env' \
    --exclude '__pycache__' \
    --exclude '.git' \
    --exclude '.claude' \
    --exclude 'notebooks' \
    --exclude 'data/reports' \
    --exclude 'ta-lib' \
    --exclude '*.egg-info' \
    --exclude '.pytest_cache' \
    . "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}/"

echo "파일 전송 완료. 리모트 설정 시작..."

# 리모트에서 setup 실행
ssh "${REMOTE_USER}@${REMOTE_HOST}" "cd ${REMOTE_PATH} && bash scripts/dev/setup.sh"

# cron 등록 (crontab.txt 있을 때만)
ssh "${REMOTE_USER}@${REMOTE_HOST}" "cd ${REMOTE_PATH} && [ -f crontab.txt ] && crontab crontab.txt || echo 'crontab.txt 없음 — 스킵'"

echo "=== Deploy complete ==="

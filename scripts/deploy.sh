#!/bin/bash
# Nuri-Quant: Dev Machine → Mac Mini (Production) 배포
set -e

source .env 2>/dev/null || true

REMOTE_HOST="${MACMINI_HOST:-macmini.local}"
REMOTE_USER="${MACMINI_USER:-ehbebe}"
REMOTE_PATH="${MACMINI_PATH:-~/nuri-quant}"

echo "=== Deploying Nuri-Quant to Mac Mini ($REMOTE_USER@$REMOTE_HOST) ==="

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
ssh "${REMOTE_USER}@${REMOTE_HOST}" "cd ${REMOTE_PATH} && bash scripts/setup.sh"

# cron 등록 (crontab.txt 있을 때만)
ssh "${REMOTE_USER}@${REMOTE_HOST}" "cd ${REMOTE_PATH} && [ -f crontab.txt ] && crontab crontab.txt || echo 'crontab.txt 없음 — 스킵'"

echo "=== Deploy complete ==="

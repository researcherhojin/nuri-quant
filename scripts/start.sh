#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
# Nuri-Quant — Backend + Frontend 동시 실행
# ═══════════════════════════════════════════════════════
set -euo pipefail

# Source shared helpers (colors, PYTHON, REPO_ROOT cd).
# shellcheck source=scripts/_common.sh
source "$(dirname "$0")/_common.sh"

banner "Nuri-Quant Service Starting"

API_PORT="${API_PORT:-8001}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

# 포트 충돌 확인
for PORT in $API_PORT $FRONTEND_PORT; do
    if lsof -i ":$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
        PID=$(lsof -i ":$PORT" -sTCP:LISTEN -t 2>/dev/null | head -1)
        echo -e "  ⚠ Port $PORT already in use (PID: $PID). Kill with: make ports-kill"
        exit 1
    fi
done

# Backend (FastAPI)
echo -e "${GREEN}Starting FastAPI backend on :${API_PORT}...${NC}"
$PYTHON -m uvicorn nuri.api.main:app --host 0.0.0.0 --port "$API_PORT" &
API_PID=$!
echo "  API PID: $API_PID"

# Wait for API to be ready
sleep 2
if curl -s "http://localhost:${API_PORT}/api/health" > /dev/null 2>&1; then
    echo -e "  ${GREEN}✓ API ready${NC}"
else
    echo "  Waiting for API..."
    sleep 3
fi

# Frontend (Next.js)
echo -e "${GREEN}Starting Next.js dashboard on :${FRONTEND_PORT}...${NC}"
cd frontend && npm run dev &
NEXT_PID=$!
echo "  Next.js PID: $NEXT_PID"
cd ..

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Services running:${NC}"
echo "    API:       http://localhost:${API_PORT}/docs"
echo "    Dashboard: http://localhost:${FRONTEND_PORT}"
echo ""
echo "  Press Ctrl+C to stop both services"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Trap Ctrl+C to kill both.
# Single quotes so $API_PID / $NEXT_PID expand when the trap fires, not now
# (defensive — makes it safe to reorder the trap earlier in the script).
trap 'echo ""; echo "Stopping services..."; kill "$API_PID" "$NEXT_PID" 2>/dev/null; exit 0' INT TERM

# Wait
wait

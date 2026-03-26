#!/bin/bash
# ═══════════════════════════════════════════════════════
# Nuri-Quant — Backend + Frontend 동시 실행
# ═══════════════════════════════════════════════════════
set -e

GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

cd "$(dirname "$0")/.."

echo -e "${CYAN}"
echo "  ╔══════════════════════════════════════════╗"
echo "  ║     Nuri-Quant Service Starting           ║"
echo "  ╚══════════════════════════════════════════╝"
echo -e "${NC}"

# Backend (FastAPI)
echo -e "${GREEN}Starting FastAPI backend on :8001...${NC}"
.venv/bin/python -m uvicorn nuri.api.main:app --host 0.0.0.0 --port 8001 &
API_PID=$!
echo "  API PID: $API_PID"

# Wait for API to be ready
sleep 2
if curl -s http://localhost:8001/api/health > /dev/null 2>&1; then
    echo -e "  ${GREEN}✓ API ready${NC}"
else
    echo "  Waiting for API..."
    sleep 3
fi

# Frontend (Next.js)
echo -e "${GREEN}Starting Next.js dashboard on :3000...${NC}"
cd frontend && npm run dev &
NEXT_PID=$!
echo "  Next.js PID: $NEXT_PID"
cd ..

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Services running:${NC}"
echo "    API:       http://localhost:8001/docs"
echo "    Dashboard: http://localhost:3000"
echo ""
echo "  Press Ctrl+C to stop both services"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Trap Ctrl+C to kill both
trap "echo ''; echo 'Stopping services...'; kill $API_PID $NEXT_PID 2>/dev/null; exit 0" INT TERM

# Wait
wait

#!/bin/bash
# ═══════════════════════════════════════════════════════
# Nuri-Quant Pre-Deploy Check
# 배포 전 필수 검증: config, DB, API, 의존성
# ═══════════════════════════════════════════════════════
set -e
cd "$(dirname "$0")/.."

PYTHON=${PYTHON:-.venv/bin/python}
PASS=0
FAIL=0
WARN=0

pass()  { echo "  ✅ $1"; ((PASS++)); }
fail()  { echo "  ❌ $1"; ((FAIL++)); }
warn()  { echo "  ⚠️  $1"; ((WARN++)); }

echo "═══════════════════════════════════════════════════════"
echo "  Nuri-Quant Pre-Deploy Check"
echo "═══════════════════════════════════════════════════════"
echo ""

# ── 1. Config 파일 검증 ──
echo "📋 Config files..."
[ -f config/portfolio.yaml ] && pass "portfolio.yaml" || fail "portfolio.yaml missing"
[ -f config/alerts.yaml ]    && pass "alerts.yaml"    || fail "alerts.yaml missing"
[ -f config/rules.yaml ]     && pass "rules.yaml"     || fail "rules.yaml missing"
[ -f .env ] || [ -f .env.local ] && pass ".env exists" || warn ".env not found (using defaults)"

# ── 2. Python 환경 ──
echo ""
echo "🐍 Python environment..."
if [ -f "$PYTHON" ]; then
    pass "venv exists ($PYTHON)"
else
    fail "venv not found (run: make setup)"
fi

if $PYTHON -c "import nuri.core.db" 2>/dev/null; then
    pass "nuri package importable"
else
    fail "nuri package import failed"
fi

if $PYTHON -c "import talib" 2>/dev/null; then
    pass "TA-Lib available"
else
    warn "TA-Lib not installed (pandas fallback will be used)"
fi

# ── 3. DB 검증 ──
echo ""
echo "💾 Database..."
DB_PATH="data/portfolio.db"
if [ -f "$DB_PATH" ]; then
    pass "portfolio.db exists"
    TABLE_COUNT=$($PYTHON -c "
from nuri.core.db import get_connection
conn = get_connection()
tables = conn.execute(\"SELECT COUNT(*) FROM sqlite_master WHERE type='table'\").fetchone()[0]
conn.close()
print(tables)
" 2>/dev/null || echo "0")
    if [ "$TABLE_COUNT" -ge 10 ]; then
        pass "DB has $TABLE_COUNT tables"
    else
        warn "DB has only $TABLE_COUNT tables (expected 10+)"
    fi
else
    fail "portfolio.db not found (run: make setup)"
fi

# ── 4. Gate 상태 ──
echo ""
echo "🚦 Pipeline gates..."
GATE_OUTPUT=$($PYTHON -m nuri.trading.engine.gate 2>&1 || true)
READY_COUNT=$(echo "$GATE_OUTPUT" | grep -c "READY" || true)
BLOCKED_COUNT=$(echo "$GATE_OUTPUT" | grep -c "BLOCKED" || true)
if [ "$BLOCKED_COUNT" -gt 0 ]; then
    warn "$READY_COUNT gates READY, $BLOCKED_COUNT BLOCKED"
else
    pass "All gates READY ($READY_COUNT phases)"
fi

# ── 5. Frontend 빌드 ──
echo ""
echo "🖥️  Frontend..."
if [ -f frontend/package.json ]; then
    if [ -d frontend/node_modules ]; then
        pass "node_modules installed"
    else
        warn "node_modules missing (run: cd frontend && npm ci)"
    fi
    if cd frontend && npx tsc --noEmit 2>/dev/null; then
        pass "TypeScript check passed"
    else
        warn "TypeScript errors found"
    fi
    cd ..
else
    fail "frontend/package.json not found"
fi

# ── 6. 포트 충돌 ──
echo ""
echo "🔌 Port availability..."
for PORT in 8001 3000; do
    if lsof -i ":$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
        PID=$(lsof -i ":$PORT" -sTCP:LISTEN -t 2>/dev/null | head -1)
        warn "Port $PORT in use (PID: $PID)"
    else
        pass "Port $PORT available"
    fi
done

# ── 결과 ──
echo ""
echo "═══════════════════════════════════════════════════════"
TOTAL=$((PASS + FAIL + WARN))
echo "  Results: $PASS passed, $FAIL failed, $WARN warnings ($TOTAL checks)"
echo "═══════════════════════════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
    echo "  ❌ Deploy BLOCKED — fix failures above"
    exit 1
else
    echo "  ✅ Deploy OK"
    exit 0
fi

#!/bin/bash
# Nuri-Quant System Verification — 커밋 전 필수
set -e

# Source shared helpers (colors, PYTHON, REPO_ROOT cd, counters).
source "$(dirname "$0")/_common.sh"

# Local check() that inspects $? from the previous command — distinct from
# _common.sh's check_cmd which takes the command as args. Updates _common.sh's
# PASS/FAIL counters.
check() {
    if [ $? -eq 0 ]; then
        echo -e "  ${GREEN}✓ $1${NC}"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}✗ $1${NC}"
        FAIL=$((FAIL + 1))
    fi
}

banner "Nuri-Quant System Verification"

# 1. Tests (yfinance mocked via conftest.py → ~5s)
echo ""; echo "━━━ 1/5. Unit Tests ━━━"
$PYTHON -m pytest tests/ -q --tb=line 2>&1 | tail -1
check "Unit Tests"

# 2. All-in-one Python check (DB + imports + API + logic + backtest 한 프로세스)
echo ""; echo "━━━ 2/5. Backend (API + Logic + Backtest) ━━━"
$PYTHON -c "
import time
start = time.time()

# DB
from nuri.core.db import query
tables = query(\"SELECT COUNT(*) as c FROM sqlite_master WHERE type='table'\")
prices = query('SELECT COUNT(*) as c FROM prices')
print(f'  DB: {tables[0][\"c\"]} tables, {prices[0][\"c\"]:,} prices')

# Imports (24 modules)
modules = [
    'nuri.core.db', 'nuri.core.rules',
    'nuri.quant.regime.classifier', 'nuri.quant.regime.macro_score',
    'nuri.quant.validation.signal_backtest',
    'nuri.trading.agents.consensus', 'nuri.trading.agents.wallstreet',
    'nuri.trading.strategy.longshort', 'nuri.trading.strategy.ls_backtest',
    'nuri.trading.recommend.candidates', 'nuri.trading.swing.scanner',
    'nuri.trading.engine.gate', 'nuri.trading.engine.conflicts', 'nuri.trading.engine.memory',
    'nuri.llm.report', 'nuri.api.main',
]
for m in modules:
    __import__(m)
print(f'  Imports: {len(modules)} modules OK')

# API (TestClient — no network)
from fastapi.testclient import TestClient
from nuri.api.main import app
c = TestClient(app)
# 가벼운 endpoints만 (consensus/scan은 캐시 의존)
fast_eps = ['/api/health','/api/portfolio','/api/risk','/api/regime','/api/macro',
            '/api/scorecard','/api/gate','/api/memory','/api/tracking','/api/dashboard']
ok = sum(1 for ep in fast_eps if c.get(ep).status_code == 200)
print(f'  API: {ok}/{len(fast_eps)} fast endpoints OK')

# Business Logic
from nuri.quant.regime.classifier import classify_regime
from nuri.trading.engine.gate import check_gate
r = classify_regime()
g = check_gate()
print(f'  Regime: {r.regime if r else \"FAIL\"}, Gate: {g.passed}/{g.total}')

# Backtest
from nuri.trading.strategy.ls_backtest import classify_historical_regimes, run_backtest
regimes = classify_historical_regimes()
bt = run_backtest(regimes)
print(f'  Backtest: {bt.total_return:+.1f}%, Sharpe: {bt.sharpe}, MDD: {bt.max_drawdown:.1f}%')

elapsed = time.time() - start
print(f'  ({elapsed:.1f}s)')

assert r is not None
assert ok == len(fast_eps)
assert bt.sharpe > 0.5
" 2>&1
check "Backend"

# 3. Frontend
echo ""; echo "━━━ 3/5. Frontend Build ━━━"
cd frontend && npm run build 2>&1 | grep -c "ƒ\|○" | xargs -I{} echo "  {} pages"
cd ..
check "Frontend"

# 4. Heavy API (consensus + scan — 캐시 워밍 포함)
echo ""; echo "━━━ 4/5. Heavy Endpoints (cached) ━━━"
$PYTHON -c "
from fastapi.testclient import TestClient
from nuri.api.main import app
c = TestClient(app)
heavy = ['/api/consensus/TSLA','/api/backtest','/api/ticker/TSLA','/api/report/context']
ok = sum(1 for ep in heavy if c.get(ep).status_code == 200)
print(f'  {ok}/{len(heavy)} heavy endpoints OK')
assert ok == len(heavy)
" 2>&1
check "Heavy Endpoints"

# 5. Integrity
echo ""; echo "━━━ 5/5. File Integrity ━━━"
old=$(grep -rn "from nuri\.regime\.\|from nuri\.agents\.\|from nuri\.strategy\.\|from nuri\.recommend\.\|from nuri\.swing\.\|from nuri\.quant\." nuri/ tests/ scripts/ --include="*.py" 2>/dev/null | grep -v __pycache__ | grep -v "nuri.quant.regime" | grep -v "nuri.quant.validation" | grep -v "nuri.analysis.factors" | grep -v "nuri.trading" | wc -l | tr -d ' ')
echo "  Orphan imports: $old"
test "$old" -eq "0"
check "File Integrity"

# Summary
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}  ✓ ALL $PASS/$((PASS + FAIL)) PASSED${NC}"
else
    echo -e "${RED}  ✗ $FAIL FAILED${NC}"
fi
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
exit "$FAIL"

#!/usr/bin/env bash
# Nuri-Quant System Verification — 커밋 전 필수
#
# 실행과 표시를 분리한다. 실패 판정이 필요한 단계는 로그 파일로 돌리고 요약은
# 후처리한다. 옛 구조는 `pytest ... | tail -1` 다음 줄에서 check() 가 ambient `$?`
# 를 읽었는데, 그 `$?` 는 pytest 가 아니라 **`tail` 의 것**이라 1·3단계가 항상
# PASS 였다 — 2026-08-10 에 test_90d_tracking 이 깨진 채로 "ALL 5/5 PASSED" 가
# 찍혔다. 헤더에 적혀 있던 "pipefail 을 켜면 tail 요약이 깨진다"는 절반만 맞다:
# 깨지는 건 요약이 아니라 `set -e` 아래에서 잡히지 않은 non-zero 다. 파이프에서
# 실행을 빼내면 pipefail 이 논쟁거리가 아니게 된다.
#
# PIPESTATUS 로 때우지 않는 이유: 파이프와 캡처 사이에 `cd`/`echo`/대입이 하나만
# 끼어도 조용히 죽는다(옛 3단계의 `cd ..` 가 정확히 그 자리였다).
set -euo pipefail

# Source shared helpers (colors, PYTHON, REPO_ROOT cd, counters).
# shellcheck source=scripts/_common.sh
# (sourced via $(dirname "$0")/../_common.sh — moved to subdir)
source "$(dirname "$0")/../_common.sh"

# Local check() — **명시적 status 인자**를 받는다 (ambient `$?` 금지). distinct
# from _common.sh's check_cmd which takes the command as args. Updates
# _common.sh's PASS/FAIL counters.
check() {
    local status="$1" label="$2"
    if [ "$status" -eq 0 ]; then
        echo -e "  ${GREEN}✓ ${label}${NC}"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}✗ ${label}${NC}"
        FAIL=$((FAIL + 1))
    fi
}

tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/verify_all.XXXXXX")"
trap 'rm -rf "$tmpdir"' EXIT

banner "Nuri-Quant System Verification"

# 1. Tests (yfinance mocked via conftest.py → ~5s)
echo ""; echo "━━━ 1/5. Unit Tests ━━━"
tests_log="$tmpdir/unit_tests.log"
if $PYTHON -m pytest tests/ -q --tb=line >"$tests_log" 2>&1; then
    tests_status=0
else
    tests_status=$?
fi
tail -1 "$tests_log"
check "$tests_status" "Unit Tests"

# 2. All-in-one Python check (DB + imports + API + logic + backtest 한 프로세스)
echo ""; echo "━━━ 2/5. Backend (API + Logic + Backtest) ━━━"
if $PYTHON -c "
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
" 2>&1; then
    backend_status=0
else
    backend_status=$?
fi
check "$backend_status" "Backend"

# 3. Frontend
# `cd frontend && ... ; cd ..` 를 쓰지 않는다 — 서브셸로 감싸면 실패해도 cwd 가
# 돌아오고, cd 가 상태 캡처와 표시 사이에 끼어들 자리 자체가 없어진다.
echo ""; echo "━━━ 3/5. Frontend Build ━━━"
frontend_log="$tmpdir/frontend_build.log"
if (cd frontend && npm run build) >"$frontend_log" 2>&1; then
    frontend_status=0
else
    frontend_status=$?
fi
# grep -c 는 매치 0 건일 때 rc=1 — pipefail 아래에서 스크립트를 죽이므로 || true.
page_count="$(grep -cE 'ƒ|○' "$frontend_log" || true)"
echo "  ${page_count} pages"
check "$frontend_status" "Frontend"

# 4. Heavy API (consensus + scan — 캐시 워밍 포함)
echo ""; echo "━━━ 4/5. Heavy Endpoints (cached) ━━━"
if $PYTHON -c "
from fastapi.testclient import TestClient
from nuri.api.main import app
c = TestClient(app)
heavy = ['/api/consensus/TSLA','/api/backtest','/api/ticker/TSLA','/api/report/context']
ok = sum(1 for ep in heavy if c.get(ep).status_code == 200)
print(f'  {ok}/{len(heavy)} heavy endpoints OK')
assert ok == len(heavy)
" 2>&1; then
    heavy_status=0
else
    heavy_status=$?
fi
check "$heavy_status" "Heavy Endpoints"

# 5. Integrity
echo ""; echo "━━━ 5/5. File Integrity ━━━"
# 예전에는 여기서 **옛 경로를 하드코딩**한 grep 에 제외 목록을 덧대는 방식이었다.
# 그 뒤 생긴 1급 패키지(`nuri/agents/` actor fleet, `nuri/quant/backtest` 등)가 제외
# 목록에 없어 정당한 import 353 건이 orphan 으로 잡혔고, 이 게이트는 **통과 불가**
# 상태로 오래 방치됐다 — 5단계가 항상 빨간불이라 1~4단계의 진짜 신호까지 묻혔다 (#902).
# 이제 "옛 경로인가" 대신 **"그 모듈이 존재하는가"** 를 묻는다. 목록이 없으니 드리프트도 없다.
old=$($PYTHON "$(dirname "$0")/check_orphan_imports.py" -v)
echo "  Orphan imports: $old"
if [ "$old" -eq 0 ]; then
    integrity_status=0
else
    integrity_status=1   # test 의 실패는 항상 1 — `$?` 를 쓰면 SC2319 (조건 참조)
fi
check "$integrity_status" "File Integrity"

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

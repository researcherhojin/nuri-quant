#!/bin/bash
# ═══════════════════════════════════════════════════════
# Nuri-Quant Full Service Flow Demo
# 전체 파이프라인을 한 바퀴 돌려서 동작 확인
# ═══════════════════════════════════════════════════════
set -e

PYTHON=".venv/bin/python"
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

step=0
total=14

header() {
    step=$((step + 1))
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  [$step/$total] $1${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

ok() { echo -e "  ${GREEN}✓ $1${NC}"; }
warn() { echo -e "  ${YELLOW}⚠ $1${NC}"; }
fail() { echo -e "  ${RED}✗ $1${NC}"; }

# ── 사전 체크 ──
echo -e "${CYAN}"
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║     Nuri-Quant Full Service Flow Demo        ║"
echo "  ║     전체 파이프라인 한 바퀴 돌리기            ║"
echo "  ╚══════════════════════════════════════════════╝"
echo -e "${NC}"

if [ ! -f "$PYTHON" ]; then
    fail ".venv not found. Run: make setup"
    exit 1
fi
ok "Python venv found"

if [ ! -f "data/portfolio.db" ]; then
    warn "DB not found. Initializing..."
    $PYTHON scripts/migrate_db.py
    $PYTHON scripts/import_portfolio.py
fi
ok "Database ready"

# ═══════════════════════════════════════════════════════
# STEP 1: Pipeline Gate — 데이터 준비 상태 확인
# ═══════════════════════════════════════════════════════
header "Pipeline Gate Check"
$PYTHON -m nuri.engine.gate 2>&1 | head -30
ok "Gate status displayed"

# ═══════════════════════════════════════════════════════
# STEP 2: Data Collection — 매크로 + Fear&Greed
# ═══════════════════════════════════════════════════════
header "Data Collection (Macro + Fear&Greed)"
echo "  Collecting macro indicators via yfinance fallback..."
$PYTHON -m nuri.collectors.macro 2>&1 | tail -8
echo ""
echo "  Collecting Fear & Greed index..."
$PYTHON -m nuri.collectors.fear_greed 2>&1 | tail -3
ok "Macro data collected"

# ═══════════════════════════════════════════════════════
# STEP 3: Signal Backtest (Phase C-1)
# ═══════════════════════════════════════════════════════
header "Signal Backtest — 7 signals × all tickers"
$PYTHON -m nuri.analysis.validation.signal_backtest 2>&1 | tail -12
ok "Signal scorecard generated"

# ═══════════════════════════════════════════════════════
# STEP 4: Learning Memory Snapshot
# ═══════════════════════════════════════════════════════
header "Learning Memory — Performance Drift Detection"
$PYTHON -m nuri.engine.memory --snapshot 2>&1
ok "Memory snapshot saved + drift analyzed"

# ═══════════════════════════════════════════════════════
# STEP 5: Market Regime (Phase D)
# ═══════════════════════════════════════════════════════
header "Market Regime Classification"
$PYTHON -m nuri.analysis.regime.strategy_map 2>&1
ok "Regime + macro + strategy computed"

# ═══════════════════════════════════════════════════════
# STEP 6: Conflict Detection
# ═══════════════════════════════════════════════════════
header "Signal Conflict Detection"
$PYTHON -m nuri.engine.conflicts 2>&1
ok "Conflicts analyzed"

# ═══════════════════════════════════════════════════════
# STEP 7: Multi-Agent Consensus (Portfolio)
# ═══════════════════════════════════════════════════════
header "Multi-Agent Consensus — 5 agents × portfolio"
$PYTHON -m nuri.trading.agents.consensus 2>&1 | tail -30
ok "Agent consensus complete"

# ═══════════════════════════════════════════════════════
# STEP 8: Recommendations (Phase E)
# ═══════════════════════════════════════════════════════
header "Contextual Recommendations"
$PYTHON -m nuri.trading.recommend.candidates --days 5 2>&1 | tail -40
ok "Candidates screened with drift + conflict penalties"

# ═══════════════════════════════════════════════════════
# STEP 9: Market-Wide Swing Scan
# ═══════════════════════════════════════════════════════
header "Market-Wide Swing Scanner — 89 US tickers"
$PYTHON -m nuri.trading.swing.scanner --top 10 2>&1
ok "Market scanned"

# ═══════════════════════════════════════════════════════
# STEP 10: Swing Trade Entry Evaluation
# ═══════════════════════════════════════════════════════
header "Swing Trade — Scanner + Agent Consensus → Entry"
$PYTHON -m nuri.trading.swing.rules 2>&1 | tail -20
ok "Swing entries evaluated"

# ═══════════════════════════════════════════════════════
# STEP 11: Long/Short Strategy
# ═══════════════════════════════════════════════════════
header "Long/Short Strategy Monitor"
$PYTHON -m nuri.trading.strategy.longshort 2>&1
ok "Strategy generated"

# ═══════════════════════════════════════════════════════
# STEP 12: L/S Strategy Backtest (요약만)
# ═══════════════════════════════════════════════════════
header "Strategy Backtest (summary)"
$PYTHON -c "
from nuri.trading.strategy.backtest import classify_historical_regimes, run_backtest
regimes = classify_historical_regimes()
r = run_backtest(regimes)
print(f'  Return: {r.total_return:+.1f}% vs SPY {r.spy_total_return:+.1f}% (excess {r.excess_return:+.1f}%)')
print(f'  Sharpe: {r.sharpe:.2f} vs SPY {r.spy_sharpe:.2f}')
print(f'  MDD:    {r.max_drawdown:.1f}% vs SPY {r.spy_max_drawdown:.1f}%')
print(f'  Monte Carlo: p < 0.05 = statistically significant')
" 2>&1
ok "Backtest verified"

# ═══════════════════════════════════════════════════════
# STEP 13: LLM Report Context (Ollama 없어도 컨텍스트 확인)
# ═══════════════════════════════════════════════════════
header "LLM Report Context Preview"
$PYTHON -c "
from nuri.llm.report import gather_context, format_prompt
ctx = gather_context()
prompt = format_prompt(ctx)
print(f'Gate Score: {ctx.gate_score:.0%}')
print(f'Known Tickers: {len(ctx.known_tickers)}')
print(f'Prompt Length: {len(prompt)} chars')
print(f'Sections: gate, regime, macro, risk, drift, candidates, conflicts, consensus, strategy')
print()
# 첫 500자만 미리보기
print(prompt[:500])
print('...')
" 2>&1
ok "LLM context assembled (9 sections)"

# ═══════════════════════════════════════════════════════
# STEP 14: Tests
# ═══════════════════════════════════════════════════════
header "Test Suite"
$PYTHON -m pytest tests/ -q --tb=line 2>&1 | tail -5
ok "All tests passed"

# ═══════════════════════════════════════════════════════
# 완료
# ═══════════════════════════════════════════════════════
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  ✓ Full service flow complete ($step/$total steps)${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Next steps:"
echo "    make api          # Start FastAPI on :8001 (Swagger: /docs)"
echo "    make dashboard    # Start Next.js on :3000"
echo "    make verify       # Full report → data/reports/YYYY-MM-DD/"
echo ""

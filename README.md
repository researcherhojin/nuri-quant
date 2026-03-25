# Nuri-Quant

<div align="center">

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![OpenBB v4](https://img.shields.io/badge/OpenBB-v4-5B21B6)](https://openbb.co/)
[![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)

**Open-source quant investment pipeline for collecting, validating, and recommending**

</div>

---

## Overview

Nuri-Quant automates the full investment research workflow: **collect** data from 12 free sources, **diagnose** portfolio health, **visualize** technical analysis with interactive charts, and **recommend** rebalancing actions — all running on a 24/7 scheduler.

### Investment Decision Coverage

```
1. Market environment    ✅  Macro (rates/CPI/VIX) + Fear & Greed
2. Valuation             ✅  PE/PB/PEG/PS ratios
3. Fundamentals          ✅  ROE, margins, revenue growth, debt
4. Technicals            ✅  Candlestick + BB + SMA + RSI + MACD + signals
5. Analyst consensus     ✅  Target price, recommendation, # of analysts
6. Smart money           ✅  Buffett/Gates/Dalio 13F + ARK trades
7. Fund flows            📋  ETF sector rotation (Phase C)
8. Sentiment             ✅  News keyword sentiment scoring
9. Risk                  ✅  VaR, CVaR, Sharpe, correlation, drawdown
```

> Chart signals (▲ BUY / ▼ SELL) are **reference indicators**, not trading orders.
> Actual win rates will be validated in Phase C.

## Quick Start

```bash
# Prerequisites: Python 3.12, uv, brew install ta-lib

git clone https://github.com/researcherhojin/nuri-quant.git && cd nuri-quant
make setup                                    # venv + deps + DB init

# Collect data (first run — 5 years of history)
python -m nuri.collectors.stock --period 5y   # US stocks
python -m nuri.collectors.stock_kr --days 1825 # Korean stocks
python -m nuri.collectors.fundamental         # PE/ROE/margins
python -m nuri.collectors.superinvestors      # Buffett/Gates 13F
python -m nuri.collectors.estimates           # analyst consensus
make collect                                  # macro/technical/fear&greed/ARK/news/events

# Analyze + generate charts
python -m nuri.analysis.sentiment
python -m nuri.analysis.charts --all          # → data/reports/YYYY-MM-DD/charts/

# Full verification report
make verify                                   # → data/reports/YYYY-MM-DD/
```

## Architecture

```
nuri/
├── collectors/     12 data collectors (BaseCollector pattern)
│   ├── stock.py          US stocks — OpenBB (yfinance), 5Y
│   ├── stock_kr.py       Korean stocks — pykrx, 5Y
│   ├── fundamental.py    PE/ROE/margins — OpenBB fundamental.metrics
│   ├── superinvestors.py Buffett/Gates/Dalio 13F — edgartools (SEC EDGAR)
│   ├── estimates.py      Analyst consensus — OpenBB estimates.consensus
│   ├── macro.py          FRED (rates, CPI, oil, FX, VIX)
│   ├── technical.py      TA-Lib (RSI, MACD, BB, SMA)
│   ├── fear_greed.py     CNN Fear & Greed Index
│   ├── ark.py            ARK Invest daily trades
│   ├── news.py           Company news (hourly)
│   ├── events.py         Earnings calendar, FOMC
│   └── institutional.py  Institutional flows (framework)
├── analysis/       8 analysis modules
│   ├── portfolio.py      Holdings, weights, P&L
│   ├── risk.py           VaR, CVaR, Sharpe, Sortino, MDD
│   ├── rebalance.py      MVO / Risk Parity (Riskfolio-Lib)
│   ├── charts.py         Plotly interactive charts + signals
│   ├── sentiment.py      News keyword sentiment
│   ├── sector.py         Sector/region exposure
│   ├── correlation.py    Correlation matrix + heatmap
│   └── performance.py    QuantStats tearsheet
├── quant/
│   ├── factors/          Multi-factor scoring (M/V/Q/S)
│   ├── backtest/         VectorBT backtesting
│   └── validation/       Phase C skeleton (signal/superinvestor/analyst)
├── alerts/               Discord webhook + bot
├── db.py                 Single DB access point (SQLite WAL)
└── scheduler.py          14 cron jobs (APScheduler)
```

### Key Patterns

- **All DB access through `nuri/db.py`** — no other module imports `sqlite3`
- **Collectors inherit `BaseCollector`** — implement `collect()` + `save()`, call `run()`
- **Analysis modules** — `analyze_*()` returns data, `print_*()` for CLI, `__main__` for direct execution
- **Charts compute indicators from prices** — not from `signals` table (which only stores latest-day snapshots)

## Data Sources

All free. No paid API required.

| Source | Data | Frequency |
|--------|------|-----------|
| OpenBB (yfinance) | US OHLCV, fundamentals, estimates, news | 5min / weekly |
| pykrx | Korean OHLCV (KOSPI/KOSDAQ) | 5min |
| SEC EDGAR (edgartools) | 13F superinvestor portfolios | Weekly |
| FRED API | Rates, CPI, oil, FX, VIX | Hourly |
| CNN | Fear & Greed Index | Daily |
| ARK Invest | Daily trades CSV | Daily |
| TA-Lib | RSI, MACD, BB, SMA 20/50/200 | Daily |

## Verification Report

`make verify` generates a dated report directory:

```
data/reports/2026-03-26/
├── portfolio.csv          holdings, weights, P&L
├── risk.json              Sharpe, VaR, MDD, stop-loss alerts
├── sector.csv             sector exposure
├── correlation.csv/.png   correlation matrix + heatmap
├── rebalance_mvo.csv      MVO rebalancing suggestions
├── rebalance_rp.csv       Risk Parity rebalancing suggestions
├── factors.csv            multi-factor scores
├── tearsheet.html         QuantStats performance report
├── summary.txt            overall summary
└── charts/
    ├── TSLA.html          interactive chart (candle+BB+SMA+RSI+MACD+signals)
    ├── NVDA.html
    └── ...
```

## Investment Rules

Enforced as **hard constraints** in code, not guidelines:

| Rule | Limit | Location |
|------|-------|----------|
| Single position | ≤ 15% | `rebalance.py`, `portfolio.py` |
| Sector exposure | ≤ 35% | `sector.py` |
| Leverage ETF ban | TSLL, TQQQ, SQQQ, UPRO, SPXU | `rebalance.py` |
| Per-stock stop loss | -20% | `risk.py` |
| Portfolio stop | -10% drawdown | `risk.py` |

## Roadmap

### Phase A: Foundation ✅
Data collection (8 collectors), portfolio analysis (6 modules), Riskfolio-Lib optimization, VectorBT backtesting, QuantStats tearsheets, Discord alerts, APScheduler.

### Phase B: Information Sources + Visualization ✅
> [docs/PLAN_PHASE_B.md](docs/PLAN_PHASE_B.md)

Fundamentals, superinvestor 13F, analyst consensus, interactive Plotly charts with buy/sell signals, news sentiment, 5-year price history (25K+ data points).

### Phase C: Validation Engine (scaffolded)
> [docs/PLAN_PHASE_C.md](docs/PLAN_PHASE_C.md) | Skeleton: `nuri/quant/validation/`

- **C-1** Signal backtesting — win rate / profit factor for 7 technical signals (ready to implement)
- **C-2** Superinvestor follow — "does copying Buffett actually work?" (needs historical 13F collection)
- **C-3** Analyst validation — target price hit rate (prospective tracking, 90-day wait)
- **C-4** Unified scorecard — HTML dashboard combining C-1~C-3
- **C-5** ETF fund flows — sector rotation tracking

### Phase D: Market Regime
Regime classifier (bull/bear/sideways x high/low volatility), macro scoring, regime-to-strategy mapping.

### Phase E: Contextual Recommendations
Regime-aware rebalancing, validated signal-based candidates, recommendation tracking.

### Phase F: Interface
REST API (FastAPI), web dashboard, LLM-powered reports.

## License

[MIT](LICENSE)

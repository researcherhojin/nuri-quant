# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Nuri-Quant (누리퀀트) — Open-source quant investment platform.
Python 3.12, SQLite, 100% free open-source stack.

6-step pipeline: **Collect → Validate → Classify → Diagnose → Recommend → Track**

2-machine setup: M3 Max MacBook (dev) ↔ M2 Pro Mac Mini (24/7 production).

## Commands

```bash
# Setup
make setup                              # venv + deps + DB init + portfolio import

# Data collection
make collect                            # all collectors
python -m nuri.collectors.stock         # US stocks (OpenBB)
python -m nuri.collectors.stock_kr      # Korean stocks (pykrx)

# Analysis
make analyze                            # portfolio + sector + risk
python -m nuri.analysis.portfolio       # single module
python -m nuri.analysis.performance --html  # QuantStats HTML tearsheet

# Quant
python -m nuri.quant.factors.composite  # multi-factor scores
python -m nuri.quant.backtest.engine    # VectorBT backtest
python -m nuri.analysis.rebalance --method rp  # Risk Parity

# Alerts & scheduling
make report                             # daily Discord report
python -m nuri.scheduler --dry-run      # show registered cron jobs
python -m nuri.scheduler                # start 24/7 scheduler

# Testing & deploy
make test                               # pytest tests/ -v
make deploy                             # rsync to Mac Mini
make backup                             # DB backup (30-day rolling)
```

## Architecture

**Collectors → Analysis → Alerts** with feedback loop.

- **Collectors** (`nuri/collectors/`): All inherit `BaseCollector` (`base.py`). `collect()` → `save()` → `run()` template pattern. Market filtering via `.KS` suffix.
- **Analysis** (`nuri/analysis/`): Portfolio diagnostics, Riskfolio-Lib risk/optimization, QuantStats performance, sector/correlation analysis.
- **Alerts** (`nuri/alerts/`): Discord webhook + bot dual mode. Daily report aggregates all analysis.
- **Quant** (`nuri/quant/`): Multi-factor scoring (momentum/value/quality/sentiment), VectorBT backtesting.
- **Scheduler** (`nuri/scheduler.py`): APScheduler 3.11, 11 cron jobs.

All DB access goes through `nuri/db.py` only — no other module imports `sqlite3`.

## Open-Source Stack

| Tool | Role | License |
|------|------|---------|
| OpenBB Platform v4 | US market data (multi-provider fallback) | AGPL v3 |
| pykrx | Korean market data (KOSPI/KOSDAQ EOD) | MIT |
| Riskfolio-Lib 7.2 | Portfolio optimization (MVO, HRP, CVaR) | BSD 3 |
| VectorBT 0.28 | Vectorized backtesting (Numba JIT) | MIT |
| QuantStats | Performance HTML tearsheet (30+ metrics) | MIT |
| TA-Lib | Technical indicators (RSI, MACD, BB, SMA, EMA) | BSD |
| APScheduler 3.11 | Python-native cron scheduler | MIT |
| FRED API | Macro indicators (rates, CPI, oil, FX) | Public |

Requires `brew install ta-lib` before `pip install`.

## DB Schema (SQLite, WAL mode)

| Table | Key columns | Status |
|-------|-------------|--------|
| `prices` | ticker, date, OHLCV, adj_close | Active |
| `portfolio` | account, ticker, quantity, avg_price, currency, sector | Active |
| `macro` | indicator, date, value, source | Active |
| `signals` | ticker, date, rsi_14, macd, bb_*, sma_*, ema_* | Active |
| `ark` | date, ticker, direction, shares, weight, fund | Active |
| `events` | date, event_type, ticker, description, importance | Active |
| `news` | ticker, date, title, url, source, sentiment | Active |
| `factors` | ticker, date, momentum/value/quality/composite_score | Phase 3 |
| `backtests` | strategy_id, total_return, sharpe, max_drawdown, win_rate | Phase 3 |

## Code Conventions

- Python 3.12 with type hints
- Korean comments (한국어 주석), English variable/function names
- All collectors inherit `BaseCollector`
- Configuration in YAML (`config/`), secrets in `.env` (git-ignored)
- DB never accessed directly — always through `nuri.db` module
- Korean stock tickers use `.KS` suffix (e.g., `005930.KS` for 삼성전자)
- `.KS` tickers are always treated as KRW regardless of account currency

## Investment Rules (코드에 강제 적용)

```yaml
max_single_position: 15%    # portfolio.py, rebalance.py
max_sector_exposure: 35%    # sector.py
stop_loss: -20%             # risk.py (per stock)
portfolio_stop: -10%        # risk.py (total)
leverage_ban: true          # rebalance.py (TSLL, TQQQ, SQQQ, UPRO, SPXU)
no_first_30min: true        # (rule exists, automation TBD)
```

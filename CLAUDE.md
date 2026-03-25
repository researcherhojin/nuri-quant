# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Nuri-Quant (누리퀀트) — Open-source quant investment platform.
Python 3.12, SQLite, 100% free open-source stack.

6-step pipeline: **Collect → Validate → Classify → Diagnose → Recommend → Track**

2-machine setup: M3 Max MacBook (dev) ↔ M2 Pro Mac Mini (24/7 production).

## Commands

```bash
# Setup (requires: brew install ta-lib)
make setup                              # venv + deps + DB init + portfolio import

# Data collection
make collect                            # Phase A 6 collectors only (stock/stock_kr/macro/technical/fear_greed/ark)
python -m nuri.collectors.stock --period 5y  # US stocks 5Y (OpenBB)
python -m nuri.collectors.stock_kr --days 1825  # Korean stocks 5Y (pykrx)
python -m nuri.collectors.fundamental   # PE/ROE/margins (OpenBB metrics)
python -m nuri.collectors.superinvestors  # Buffett/Gates/Dalio 13F (edgartools)
python -m nuri.collectors.estimates     # Analyst consensus (OpenBB)

# Analysis
make analyze                            # portfolio + sector + risk
python -m nuri.analysis.portfolio       # single module
python -m nuri.analysis.performance --html  # QuantStats HTML tearsheet
python -m nuri.analysis.sentiment       # news sentiment (keyword-based)
python -m nuri.analysis.charts --all    # interactive HTML charts (Plotly)
python -m nuri.analysis.charts --ticker TSLA --png  # single ticker + PNG

# Quant
python -m nuri.quant.factors.composite  # multi-factor scores
python -m nuri.quant.backtest.engine    # VectorBT backtest
python -m nuri.analysis.rebalance --method rp  # Risk Parity

# Verification (runs all analyses → data/reports/YYYY-MM-DD/)
make verify                             # full verification with backtest
make verify-fast                        # skip backtest

# Alerts & scheduling
make report                             # daily Discord report
python -m nuri.scheduler --dry-run      # show registered cron jobs (14 jobs)
python -m nuri.scheduler                # start 24/7 scheduler

# Validation (Phase C — skeleton only, NotImplementedError)
make validate                           # run all validation modules

# Testing
make test                               # pytest tests/ -v --cov=nuri (26 pass, 6 skip)
.venv/bin/python -m pytest tests/test_db.py -v          # single test file
.venv/bin/python -m pytest tests/test_db.py::TestUpsertPrices -v  # single class
.venv/bin/python -m pytest tests/test_db.py::TestUpsertPrices::test_insert_and_query -v  # single test

# Deploy & backup
make deploy                             # rsync to Mac Mini
make backup                             # DB backup (30-day rolling)
```

All `make` targets use `.venv/bin/python` — activate the venv or use the full path.

## Architecture

**Collectors → DB → Analysis → Alerts** — three-layer pipeline with feedback loop.

### DB as the sole integration point

`nuri/db.py` is the **only** module that imports `sqlite3`. Every other module reads/writes through its functions (`upsert_prices`, `upsert_portfolio`, `query`, `query_df`, etc.). The DB file lives at `data/portfolio.db` (WAL mode). All upsert functions accept an optional `db_path` parameter — tests use this to inject a `tmp_path` fixture for isolation.

### Collector template pattern

All collectors inherit `BaseCollector` (`nuri/collectors/base.py`). The contract:
1. Implement `collect(**kwargs) -> Any` (fetch data)
2. Implement `save(data) -> int` (persist to DB)
3. External code calls `run()` which does `collect()` → `save()` with logging and timing

`_get_tickers(market=)` filters portfolio tickers: `"us"` excludes `.KS`, `"kr"` includes only `.KS`.

### Analysis module pattern

Each analysis module (`portfolio.py`, `risk.py`, `sector.py`, `rebalance.py`) follows the same shape:
- A main `analyze_*()` function that reads from DB and returns a DataFrame or dict
- A `print_*()` function for CLI output
- A `__main__` block so it can be run as `python -m nuri.analysis.<module>`

`daily_report.py` orchestrates: calls `analyze_portfolio()` + `analyze_risk()` + DB queries, then formats via `formatters.py` and sends to Discord webhook (falls back to stdout if `DISCORD_WEBHOOK_URL` is unset).

### Scheduler ties it all together

`nuri/scheduler.py` defines 14 cron jobs in the `SCHEDULES` list. Each entry maps a name to a collector/report function and a cron expression. All times are KST. The scheduler uses lazy imports inside `_run_collector()` to avoid import-time side effects. Phase B added: `fundamental` (weekly), `superinvestors` (weekly), `estimates` (weekly), news frequency increased to hourly.

### Phase B modules

- **Fundamentals** (`nuri/collectors/fundamental.py`): `obb.equity.fundamental.metrics` (yfinance) → PE, PB, ROE, margins, growth, beta. Works for US and Korean (.KS) stocks.
- **Superinvestors** (`nuri/collectors/superinvestors.py`): `edgartools` → SEC EDGAR 13F. Tracks Buffett, Gates, Dalio, Ackman, Tepper. No API key needed. Ticker-level aggregation with portfolio weight %.
- **Estimates** (`nuri/collectors/estimates.py`): `obb.equity.estimates.consensus` (yfinance) → target price, recommendation, analyst count.
- **Charts** (`nuri/analysis/charts.py`): Plotly interactive HTML. Computes TA-Lib indicators directly from price data (not signals table — signals table only has latest-day snapshots). Includes buy/sell signal detection (RSI bounce, MACD cross, golden/death cross), analyst target overlay, info panel (fundamentals + sentiment + superinvestor holdings), and period selector buttons (1M/3M/6M/1Y/2Y/ALL). Legend items are clickable to toggle layers on/off.
- **Sentiment** (`nuri/analysis/sentiment.py`): Keyword dictionary-based sentiment scoring on news titles. Updates `news.sentiment` column.

### Multi-factor scoring

`nuri/quant/factors/` has individual factor modules (`momentum.py`, `value.py`, `quality.py`) that each return a scored DataFrame. `composite.py` combines them with configurable weights (30/25/25/20) into a single composite score. Sentiment uses the Fear & Greed index as a market-wide proxy.

## Environment Variables

Configured in `.env` (see `.env.example`):
- `FRED_API_KEY` — FRED macro data
- `DISCORD_WEBHOOK_URL` — daily report delivery (optional; falls back to stdout)
- `DISCORD_BOT_TOKEN` — bot mode alerts (optional)
- `FINNHUB_API_KEY` — US institutional flows (optional, B-5)

## DB Schema (SQLite, WAL mode)

| Table | Purpose | Phase |
|-------|---------|-------|
| `prices` | OHLCV 5Y (25K+ rows) | A |
| `portfolio` | Holdings (account, ticker, qty, avg_price) | A |
| `macro` | FRED indicators + Fear&Greed | A |
| `signals` | TA-Lib technical indicators | A |
| `ark` | ARK Invest daily trades | A |
| `events` | Earnings, dividends, FOMC | A |
| `news` | Company news + sentiment score | A+B |
| `llm_bench` | LLM benchmark results | (Phase 2) |
| `fundamentals` | PE, ROE, margins, growth, beta | B |
| `superinvestors` | 13F holdings (Buffett, etc.) | B |
| `estimates` | Analyst consensus + target prices | B |
| `institutional_flows` | Institutional/foreign net buys | B |
| `factors` | Multi-factor composite scores | (Phase 3) |
| `backtests` | Backtest results | (Phase 3) |

## Code Conventions

- Python 3.12 with type hints
- Korean comments (한국어 주석), English variable/function names
- Configuration in YAML (`config/`), secrets in `.env` (git-ignored)
- Korean stock tickers use `.KS` suffix (e.g., `005930.KS` for 삼성전자)
- `.KS` tickers are always treated as KRW regardless of account currency

## Testing patterns

Tests use `tmp_path` pytest fixture to create isolated SQLite databases:
```python
@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path
```
Pass `db_path` to all DB functions in tests. Tests are grouped by module in `tests/test_*.py` using class-based organization.

## Investment Rules (enforced in code)

```yaml
max_single_position: 15%    # portfolio.py, rebalance.py
max_sector_exposure: 35%    # sector.py, rebalance.py (MAX_SECTOR_EXPOSURE)
stop_loss: -20%             # risk.py (STOCK_STOP_LOSS, per stock)
portfolio_stop: -10%        # risk.py (PORTFOLIO_STOP, total)
leverage_ban: true          # rebalance.py (LEVERAGE_ETFS set: TSLL, TQQQ, SQQQ, UPRO, SPXU)
```

These are hardcoded constants, not config — changes require code edits.

## OpenBB Provider Limitations

Not all OpenBB endpoints work with the free `yfinance` provider. Verified status:

| Endpoint | yfinance | Notes |
|----------|----------|-------|
| `obb.equity.price.historical` | ✅ | Primary price data source |
| `obb.equity.fundamental.metrics` | ✅ | PE, PB, ROE, margins, growth, beta (30+ fields) |
| `obb.equity.fundamental.ratios` | ❌ | Requires `fmp` or `intrinio` (paid) |
| `obb.equity.estimates.consensus` | ✅ | Target price, recommendation, analyst count |
| `obb.equity.estimates.price_target` | ❌ | Requires `benzinga` or `fmp` (paid) |
| `obb.equity.ownership.*` | ❌ | Requires `fmp` (paid) |

If `FMP_API_KEY` is set in `.env`, additional endpoints become available.

## Phase C: Validation Engine (scaffolding ready)

`nuri/quant/validation/` contains skeleton modules with dataclass definitions, function signatures, and `NotImplementedError` stubs. Plan: [`docs/PLAN_PHASE_C.md`](docs/PLAN_PHASE_C.md).

- `signal_backtest.py` — C-1: 7 technical signals x all tickers, win rate / profit factor. **Ready to implement** (prices 5Y data available).
- `superinvestor_backtest.py` — C-2: Follow Buffett/Dalio returns. **Blocked**: needs `superinvestors.py` to fetch 8 quarters (currently only latest 1).
- `analyst_backtest.py` — C-3: Target price hit rate. **Blocked**: needs 90+ days of accumulated `estimates` data (prospective tracking).
- `scorecard.py` — C-4: Unified HTML dashboard. Depends on C-1~C-3.

Tests: `tests/test_validation.py` has 6 skipped tests — remove `@pytest.mark.skip` as each module is implemented.

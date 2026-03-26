# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Nuri-Quant (누리퀀트) — Open-source quant investment platform.
Python 3.12, `uv` package manager, SQLite, 100% free open-source stack.
No linter/formatter configured. No CI/CD pipeline.

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
python -m nuri.scheduler --dry-run      # show registered cron jobs (17 jobs)
python -m nuri.scheduler                # start 24/7 scheduler

# Validation (Phase C)
make validate                           # signal + superinvestor + analyst + scorecard

# Market Regime (Phase D)
python -m nuri.quant.regime.classifier             # current regime
python -m nuri.quant.regime.classifier --history   # monthly regime history
python -m nuri.quant.regime.macro_score            # macro health 0~100
python -m nuri.quant.regime.strategy_map           # regime + macro + strategy

# Recommendations (Phase E)
python -m nuri.recommend.candidates                # signal-based buy/sell candidates
python -m nuri.recommend.rebalance --method rp     # regime-aware rebalancing
python -m nuri.recommend.tracker --save            # save today's recs + track past outcomes
python -m nuri.recommend.tracker                   # tracking report only

# Multi-Agent Consensus (6 agents)
make consensus                          # 보유 종목 6-agent analysis
python -m nuri.agents.consensus --ticker TSLA  # 단일 종목

# Wall Street 데이터
make wallstreet                         # 애널리스트 등급 + 실적 + 내부자 수집
make filings                            # SEC 10-K 핵심 지표 파싱

# Swing Trade (market-wide scanning)
make scan                               # 시장 스캔 (89종목 → 시그널 필터)
make swing                              # 스캔 + 에이전트 합의 → 진입 저장
make swing-check                        # 보유 포지션 청산 체크

# Testing
make verify-quick                       # tests + regime (6초)
make test                               # pytest tests/ -v --cov=nuri (105 pass)
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

Key DB access patterns:
- `get_db()` — context manager, auto-commits on success, auto-rollbacks on exception
- `query(sql, params)` → list of `sqlite3.Row` (dict-like access)
- `query_df(sql, params)` → pandas DataFrame
- `upsert_*()` functions for each table (prices, portfolio, fundamentals, etc.)

### Currency handling

Multi-account portfolio mixes USD and KRW. Exchange rate lookup uses a fallback chain: DB `macro` table → OpenBB API → hardcoded default `1450.0` KRW/USD. `.KS` tickers are always treated as KRW regardless of account currency.

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

`nuri/scheduler.py` defines 17 cron jobs in the `SCHEDULES` list. Each entry maps a name to a collector/report function and a cron expression. All times are KST. The scheduler uses lazy imports inside `_run_collector()` to avoid import-time side effects.

### Phase B modules

- **Fundamentals** (`nuri/collectors/fundamental.py`): `obb.equity.fundamental.metrics` (yfinance) → PE, PB, ROE, margins, growth, beta. Works for US and Korean (.KS) stocks.
- **Superinvestors** (`nuri/collectors/superinvestors.py`): `edgartools` → SEC EDGAR 13F. Tracks Buffett, Gates, Dalio, Ackman, Tepper. No API key needed. Ticker-level aggregation with portfolio weight %.
- **Estimates** (`nuri/collectors/estimates.py`): `obb.equity.estimates.consensus` (yfinance) → target price, recommendation, analyst count.
- **Charts** (`nuri/analysis/charts.py`): Plotly interactive HTML. Computes TA-Lib indicators directly from price data (not signals table — signals table only has latest-day snapshots). Includes buy/sell signal detection (RSI bounce, MACD cross, golden/death cross), analyst target overlay, info panel (fundamentals + sentiment + superinvestor holdings), and period selector buttons (1M/3M/6M/1Y/2Y/ALL). Legend items are clickable to toggle layers on/off.
- **Sentiment** (`nuri/analysis/sentiment.py`): Keyword dictionary-based sentiment scoring on news titles. Updates `news.sentiment` column.

### Multi-factor scoring

`nuri/analysis/factors/` has individual factor modules (`momentum.py`, `value.py`, `quality.py`) that each return a scored DataFrame. `composite.py` combines them with configurable weights (30/25/25/20) into a single composite score. Sentiment uses the Fear & Greed index as a market-wide proxy.

### Phase C→D→E data flow

The validation/regime/recommendation pipeline is connected by data, not imports:

1. **C-1** (`signal_backtest`) writes `signal_results.csv` (individual trades) + `signal_scorecard.csv` (aggregates) to `data/reports/YYYY-MM-DD/`
2. **D-3** (`strategy_map.analyze_signal_by_regime()`) reads `signal_results.csv`, labels each trade with the regime active at its `entry_date` using SPY SMA/VIX state, and computes per-regime win rates
3. **E-1** (`candidates`) reads the regime-specific stats from D-3 to calibrate confidence scores
4. **E-3** (`tracker`) saves E-1/E-2 outputs to `recommendations` table for 30/60/90-day tracking

This means re-running C-1 (`python -m nuri.quant.validation.signal_backtest`) updates the data that D-3 and E-1 use. No code changes needed — the pipeline reads the latest CSV on each run.

## Environment Variables

Configured in `.env` (see `.env.example`):
- `FRED_API_KEY` — FRED macro data (optional; yfinance fallback for 10Y/2Y/VIX/Oil/USDKRW)
- `DISCORD_WEBHOOK_URL` — daily report delivery (optional; falls back to stdout)
- `DISCORD_BOT_TOKEN` — bot mode alerts (optional)
- `FINNHUB_API_KEY` — US institutional flows (optional)
- `OLLAMA_HOST` / `OLLAMA_MODEL` — LLM report generation (default: localhost:11434, llama3.1)
- `DASHBOARD_PASSWORD` — Next.js dashboard auth (optional; unset = public)

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
| `etf_flows` | Sector/index ETF AUM, volume, NAV | C |
| `recommendations` | Daily recs + 30/60/90d outcome tracking | E |
| `strategy_memory` | Signal performance snapshots (append-only) | SIEGE |
| `swing_trades` | Market-wide swing trade positions + outcomes | Swing |
| `positions` | Long/Short strategy positions (core + tactical) | L/S |
| `regime_transitions` | Regime change history + actions taken | L/S |
| `analyst_ratings` | Upgrade/downgrade history (560+ records) | WallStreet |
| `earnings_surprises` | EPS actual vs estimate per quarter | WallStreet |
| `insider_trades` | Insider buy/sell transactions | WallStreet |
| `factors` | Multi-factor composite scores | (Phase 3) |
| `backtests` | Backtest results | (Phase 3) |

## Code Conventions

- Python 3.12 with type hints
- Korean comments (한국어 주석), English variable/function names
- Git commit messages in English
- Configuration in YAML (`config/`), secrets in `.env` (git-ignored)
- Korean stock tickers use `.KS` suffix (e.g., `005930.KS` for 삼성전자)

### Config files (`config/`)

- `portfolio.yaml` — 5 accounts (test/demo/sample/pension/irp), 30+ holdings with sectors and flags (e.g., `flag: SELL`), plus bank/real_estate/total_assets summary
- `alerts.yaml` — Thresholds (price swing 3%, Fear&Greed bounds 20/80), report timing (08:00 KST)

### Scripts (`scripts/`)

- `setup.sh` — Creates `.venv` via `uv`, installs deps
- `migrate_db.py` — Creates all DB tables (used in `make setup`)
- `import_portfolio.py` — Syncs `config/portfolio.yaml` → DB portfolio table (skips auto_invest/IRP sections)
- `verify.py` — Master verification orchestrator (Phase A~E + Gate), saves JSON/CSV/PNG to `data/reports/YYYY-MM-DD/`
- `gate_check.py` — Pipeline gate verifier. Called by `make validate/regime/recommend` — exits 1 if gate BLOCKED
- `deploy.sh` — rsync to Mac Mini (excludes DB, .venv, .env, .git)
- `backup.sh` — 30-day rolling DB backup

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

## Investment Rules

Defined in `config/rules.yaml`, loaded via `nuri/rules.py`. All modules import from `nuri.rules`:

```yaml
position_limits:
  max_single_position: 0.15   # 15%
  max_sector_exposure: 0.35   # 35%
stop_loss:
  per_stock: -20              # %
  portfolio: -10              # %
leverage:
  banned_etfs: [TSLL, TQQQ, SQQQ, UPRO, SPXU]
```

To backtest different rules: copy `rules.yaml`, modify values, no code changes needed.

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

## Phase C: Validation Engine (implemented)

`nuri/analysis/validation/`

- `signal_backtest.py` — C-1: 7 technical signals x all tickers, win rate / profit factor. **Implemented.** Uses TA-Lib (with pandas fallback). Outputs `signal_results.csv` + `signal_scorecard.csv`.
- `superinvestor_backtest.py` — C-2: Follow Buffett/Dalio returns. **Implemented.** Requires historical 13F data (collector now fetches 8 quarters). Compares with VOO benchmark.
- `analyst_backtest.py` — C-3: Target price hit rate. **Implemented.** Prospective tracking — returns empty list until 90+ days of `estimates` data accumulates.
- `scorecard.py` — C-4: Unified Plotly HTML dashboard. **Implemented.** Requires C-1 CSV; C-2/C-3 optional.

`superinvestors.py` collector now fetches 8 quarters by default (previously only latest 1). `detect_changes()` compares quarter-over-quarter positions (NEW/INCREASED/DECREASED/CLOSED/UNCHANGED).

Tests: `tests/test_validation.py` — 6 tests, all passing.

## Phase D: Market Regime (implemented)

`nuri/analysis/regime/`

- `classifier.py` — D-1: 6-regime classifier (bull/bear/sideways x high/low vol). SPY SMA50/200 + VIX + Fear&Greed + RSI. **Dynamic thresholds** from 252-day rolling percentiles (not hardcoded). **Hysteresis** via 5-day majority voting to prevent noise-driven regime flips. SPY price data is collected independently of portfolio holdings.
- `macro_score.py` — D-2: Macro health score (0~100). Yield curve, VIX, sentiment, employment, inflation, monetary policy — weighted composite. `macro.py` collector has yfinance fallback (^TNX, ^IRX, ^VIX, CL=F, KRW=X) when FRED_API_KEY is unavailable. `_score_monetary()` falls back to `us_2y_yield` as Fed Funds proxy.
- `strategy_map.py` — D-3: **Data-driven** regime-to-strategy mapping. `analyze_signal_by_regime()` labels each C-1 trade with the active regime at entry, then computes per-regime win rates and profit factors. Signals with PF ≥ 1.5 → recommended; PF ≤ 1.0 → avoid. Falls back to conservative rules when data is insufficient. `SECTOR_TO_ETF` provides explicit sector-to-ETF mapping (11 SPDR sectors).

### C-5: ETF fund flows (`nuri/collectors/etf_flows.py`)
- `obb.etf.info` (yfinance) collects AUM/volume for 11 sector + 5 index ETFs weekly
- `etf_flows` table tracks `total_assets`, `volume_avg`, `nav_price` over time
- `analyze_sector_rotation()` estimates flows from AUM changes

Tests: `tests/test_regime.py` — 10 tests.

## Phase E: Contextual Recommendations (implemented)

`nuri/trading/recommend/`

- `candidates.py` — E-1: Signal-based candidate screener. Scans recent N days for signals. **Confidence** uses regime-specific actual win rate (60%) + PF (40%) when cross-analysis data exists (≥5 trades); falls back to aggregate stats otherwise. Regime-avoided signals penalized 0.4x; BUY in `minimal` mode penalized 0.3x.
- `rebalance.py` — E-2: Regime-aware rebalancing. Wraps existing MVO/RP with regime context — adjusts cash target (0~40% by position sizing), sector tilts via `SECTOR_TO_ETF`, blocks new buys in `minimal` mode. Attaches signal evidence to actions.
- `tracker.py` — E-3: Recommendation tracker. Saves daily recommendations to `recommendations` DB table. Tracks 30/60/90-day outcomes and computes system hit rate.

Tests: `tests/test_recommend.py` — 8 tests.

## SIEGE Engine (Swarm Intelligence patterns applied)

`nuri/engine/` — Inspired by [SIEGE](https://github.com/nutshells3/Swarm-Intelligence-Engine-with-Gated-Execution).

- `gate.py` — **Gated Execution**: 10 data-readiness conditions across 4 phases (collect/validate/regime/recommend). `make validate` and `make recommend` run `scripts/gate_check.py` first — exits 1 if BLOCKED. Each failed condition shows exactly what's missing and how to fix it.
- `conflicts.py` — **Conflict Detection**: Detects BUY+SELL signals on same ticker (direction_conflict), PF disparity (strength_mismatch), regime contradiction. Severity: high/medium/low. High-severity conflicts → candidates get 0.5x confidence penalty; rebalance forces HOLD.
- `memory.py` — **Append-Only Learning Memory**: Weekly snapshots of signal performance (all_time/90d/30d) to `strategy_memory` table. Detects drift: critical (>30% drop) → 0.3x confidence penalty, degrading (>15%) → 0.6x. Scheduled via cron (Sunday 04:00). `make validate` also auto-snapshots.

Confidence scoring pipeline (in `candidates.py`):
```
confidence = regime_win_rate × 60% + regime_pf × 40%   (or fallback to aggregate)
           × drift_multiplier (0.3 ~ 1.1)               ← Learning Memory
           × conflict_penalty (0.5x if high)             ← Conflict Detection
           × regime_fit_penalty (0.4x if avoid)           ← Strategy Map
           × position_penalty (0.3x if minimal BUY)       ← Regime position sizing
```

Tests: `tests/test_engine.py` — 10 tests.

## Phase F: Interface (implemented)

- `nuri/api/` — FastAPI REST API (22 endpoints, 9 route files). Key: `/api/dashboard` (action summary, 5min cache), `/api/consensus` (5min cache), `/api/ticker/{symbol}`, `/api/backtest`, `/api/scan`. Port **8001** (8000 may conflict with Docker). Swagger at `http://localhost:8001/docs`.
- `frontend/` — Next.js 14 + shadcn/ui + Tailwind. **Action-oriented Overview**: hero verdict card with 1-sentence guidance, BUY/SELL/WATCH actions (link to `/ticker/[symbol]`), alerts, regime bar. Heavy endpoints cached 5min.
- `nuri/llm/report.py` — Ollama LLM report with SIEGE Certification. 9-section context.

```bash
make start        # API(:8001) + Dashboard(:3000) simultaneous
make api          # FastAPI only (:8001)
make dashboard    # Next.js only (:3000)
```

Tests: `tests/test_llm.py` — 8 tests.

## Multi-Agent Consensus System

`nuri/trading/agents/` — 6 specialist agents with independent analysis + weighted voting.

| Agent | Data Source | Logic |
|-------|-----------|-------|
| `technical.py` | prices (RSI, MACD, SMA) | Crossover/oversold/overbought scoring |
| `fundamental.py` | fundamentals (PE, ROE, growth, debt) | Value + quality scoring |
| `macro_agent.py` | regime + macro_score + individual momentum | Market-wide + per-ticker momentum |
| `risk_agent.py` | portfolio + prices | Stop-loss, volatility, position concentration |
| `smart_money.py` | superinvestors + estimates + ARK | 13F flow + analyst consensus |
| `wallstreet.py` | yfinance (upgrades, earnings, insider) | Rating changes + EPS surprise + insider activity |

`consensus.py` aggregates via weighted voting (technical 20%, risk 25%, fundamental 15%, macro 15%, smart money 10%, wallstreet 15%). **Risk agent has veto power**: SELL + confidence ≥ 80 overrides all other agents. Non-portfolio tickers use yfinance fallback for real-time data.

Tests: `tests/test_agents.py` — 7 tests.

## Long/Short Strategy + Backtest

`nuri/trading/strategy/`

- `longshort.py` — Regime→direction mapping: bull→long(QQQ/SPY), bear→short(SH/SQQQ), sideways→cash. Generates daily action plan.
- `position.py` — SIEGE Position Certification Gate: 5 checks (regime alignment, agent consensus, concentration, daily limit, drift safety) before any position opens. Tracks P&L.
- `monitor.py` — Regime transition detection + position switch alerts. Daily P&L summary.
- `backtest.py` — Rigorous 5.4-year simulation: real SH prices (decay included), 10-day min hold (trade frequency control), next-day open execution (gap cost), slippage 0.05%. Monte Carlo 1000-run statistical validation (p<0.01). Results: +62% return, Sharpe 0.92, MDD -10% vs SPY -24%.

```bash
make strategy         # regime + transition + actions + positions
make strategy-execute # execute with SIEGE certification
make backtest-ls      # full backtest + Monte Carlo
make positions        # position P&L monitor
```

Tests: `tests/test_strategy.py` — 9 tests, `tests/test_backtest.py` — 6 tests.

## Wall Street Data Collection

`nuri/collectors/wallstreet.py` — Batch yfinance collection (no API key needed):
- Analyst ratings: upgrade/downgrade history + target prices (560+ records)
- Earnings surprise: EPS actual vs estimate per quarter (117 records)
- Insider transactions: buy/sell activity (535 records)

`nuri/collectors/filings.py` — SEC 10-K parser via edgartools. Revenue, net income, assets, liabilities, cash extraction.

`/api/ticker/{symbol}` — Single endpoint returning all data for one ticker: price, fundamentals, 6-agent verdicts, ratings, earnings, insider, superinvestors, signals.

Tests: `tests/test_agents.py` — 7 tests.

## Swing Trade System (Market-Wide Scanning)

`nuri/trading/swing/` — Scans beyond portfolio holdings to find opportunities across the market.

**Pipeline**: `scan_market()` (89 US tickers) → technical filter → `evaluate_entries()` (multi-agent consensus) → `save_entries()` → daily `check_exits()`

- `scanner.py` — Batch yfinance download (50 tickers in ~4s). Filters: volume spike (≥2x avg), momentum (5d return + RSI), BB breakout, BB bounce. Returns scored candidates.
- `rules.py` — Entry: scan score ≥ 20 + agent BUY + confidence ≥ 50. Exit: take profit +10%, stop loss -5%, max hold 7 days, or agent SELL with confidence ≥ 70. Positions tracked in `swing_trades` DB table.

```bash
make scan          # 89종목 스캔 → 시그널 필터
make swing         # 스캔 + 에이전트 합의 → 진입 저장
make swing-check   # 오픈 포지션 청산 체크
```

Tests: `tests/test_swing.py` — 4 tests (90 total across project).

## MCP Integration

`.mcp.json` configures an MCP SQLite server for direct DB queries via Claude Code:
```json
{"mcpServers": {"nuri-db": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-sqlite", "./data/portfolio.db"]}}}
```

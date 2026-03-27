# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Nuri-Quant (누리퀀트) — Open-source quant investment platform.
Python 3.12, `uv` package manager, SQLite, 100% free open-source stack.
Linter: `ruff` (E/F/W/I rules). CI: GitHub Actions (lint + test + frontend type-check).

6-step pipeline: **Collect → Validate → Classify → Diagnose → Recommend → Track**

2-machine setup: M3 Max MacBook (dev) ↔ M2 Pro Mac Mini (24/7 production).

## Commands

```bash
# Setup (requires: brew install ta-lib)
make setup                              # venv + deps + DB init + portfolio import

# Data collection
make collect                            # Phase A 6 collectors (stock/stock_kr/macro/technical/fear_greed/ark)
python -m nuri.collectors.stock --period 5y  # US stocks 5Y (OpenBB)
python -m nuri.collectors.stock_kr --days 1825  # Korean stocks 5Y (pykrx)
python -m nuri.collectors.fundamental   # PE/ROE/margins (OpenBB metrics)
python -m nuri.collectors.superinvestors  # Buffett/Gates/Dalio 13F (edgartools)
python -m nuri.collectors.estimates     # Analyst consensus (OpenBB)

# Analysis
make analyze                            # portfolio + sector + risk
python -m nuri.analysis.portfolio       # single module
python -m nuri.analysis.charts --all    # interactive HTML charts (Plotly)

# Quant pipeline
python -m nuri.quant.factors.composite       # multi-factor scores
python -m nuri.quant.backtest.engine         # VectorBT backtest
python -m nuri.quant.regime.classifier       # current regime
python -m nuri.quant.regime.strategy_map     # regime + macro + strategy

# Validation (Phase C)
make validate                           # signal + superinvestor + analyst + scorecard

# Recommendations (Phase E)
python -m nuri.trading.recommend.candidates  # signal-based buy/sell candidates
python -m nuri.trading.recommend.tracker --save  # save + track outcomes

# Multi-Agent Consensus (7 agents)
make consensus                                         # 보유 종목 7-agent analysis
python -m nuri.trading.agents.consensus --ticker TSLA  # 단일 종목

# Strategies
make strategy         # L/S regime + transition + actions
make backtest-ls      # full backtest + Monte Carlo
make optimize         # grid search parameter tuning
make mean-reversion   # mean-reversion scan + backtest
make pairs            # pairs trading scan + backtest

# Swing Trade
make scan             # 89종목 스캔 → 시그널 필터
make swing            # 스캔 + 에이전트 합의 → 진입 저장

# Lint + Test
make lint             # ruff check
make lint-fix         # ruff check --fix
make test             # pytest tests/ -v --cov=nuri (142 tests)
.venv/bin/python -m pytest tests/test_db.py -v                                    # single file
.venv/bin/python -m pytest tests/test_db.py::TestUpsertPrices -v                  # single class
.venv/bin/python -m pytest tests/test_db.py::TestUpsertPrices::test_insert_and_query -v  # single test

# Interface
make start            # API(:8001) + Dashboard(:3000) simultaneous
make api              # FastAPI only (:8001)
make dashboard        # Next.js only (:3000)

# Deploy & backup
make deploy           # rsync to Mac Mini
make backup           # DB backup (30-day rolling)
```

All `make` targets use `.venv/bin/python` — activate the venv or use the full path.

## Architecture

```
nuri/
├── core/              # DB (sole sqlite3 importer), rules (config/rules.yaml loader)
├── collectors/        # 16 data collectors inheriting BaseCollector
├── analysis/          # Pure analysis: portfolio, risk, sector, charts, sentiment, rebalance
├── quant/             # Quantitative pipeline
│   ├── regime/        # 6-regime classifier, macro score, strategy map
│   ├── validation/    # Signal backtest, superinvestor/analyst backtest, scorecard
│   ├── backtest/      # VectorBT engine, grid search optimizer
│   └── factors/       # Multi-factor scoring (momentum, value, quality, composite)
├── trading/           # Trading execution
│   ├── agents/        # 7 agents + consensus engine
│   ├── engine/        # SIEGE: gate, conflicts, learning memory
│   ├── strategy/      # L/S, mean-reversion, pairs trading
│   ├── recommend/     # Candidates, rebalance, tracker
│   ├── swing/         # Market-wide scanner + rules
│   └── execution/     # Broker interface (Alpaca paper + DryRun)
├── api/               # FastAPI REST API (routes/)
├── alerts/            # Discord daily report + bot
└── llm/               # Ollama LLM report with SIEGE certification
```

### DB as the sole integration point

`nuri/core/db.py` is the **only** module that imports `sqlite3`. Every other module reads/writes through its functions. The DB file lives at `data/portfolio.db` (WAL mode). All upsert functions accept an optional `db_path` parameter — tests use this to inject a `tmp_path` fixture for isolation. Schema versioning via `schema_version` table + `_MIGRATIONS` list for incremental changes.

Key DB access patterns:
- `get_db()` — context manager, auto-commits on success, auto-rollbacks on exception
- `query(sql, params)` → list of `sqlite3.Row` (dict-like access)
- `query_df(sql, params)` → pandas DataFrame
- `upsert_*()` functions for each table (prices, portfolio, fundamentals, etc.)

### Collector template pattern

All collectors inherit `BaseCollector` (`nuri/collectors/base.py`). The contract:
1. Implement `collect(**kwargs) -> Any` (fetch data)
2. Implement `save(data) -> int` (persist to DB)
3. External code calls `run()` which does `collect()` → `save()` with logging and timing

`_get_tickers(market=)` filters portfolio tickers: `"us"` excludes `.KS`, `"kr"` includes only `.KS`.

### C→D→E data flow

The validation/regime/recommendation pipeline is connected by data, not imports:

1. **C-1** (`signal_backtest`) writes `signal_results.csv` + `signal_scorecard.csv` to `data/reports/YYYY-MM-DD/`
2. **D-3** (`strategy_map.analyze_signal_by_regime()`) reads `signal_results.csv`, labels each trade with the regime active at entry
3. **E-1** (`candidates`) reads the regime-specific stats from D-3 to calibrate confidence scores
4. **E-3** (`tracker`) saves E-1/E-2 outputs to `recommendations` table for 30/60/90-day tracking

Re-running C-1 (`python -m nuri.quant.validation.signal_backtest`) updates the data that D-3 and E-1 use.

### Multi-Agent Consensus (7 agents)

`nuri/trading/agents/` — 7 specialist agents with weighted voting:

| Agent | Weight | Data Source |
|-------|--------|-------------|
| `technical.py` | 18% | RSI, MACD, SMA crossovers |
| `fundamental.py` | 14% | PE, ROE, growth, debt |
| `macro_agent.py` | 14% | Regime + macro score + momentum |
| `risk_agent.py` | 22% | Stop-loss, volatility, concentration (**veto power**) |
| `smart_money.py` | 9% | 13F flow + analyst consensus |
| `wallstreet.py` | 13% | Analyst ratings + EPS surprise + insider |
| `korean_market.py` | 10% | KRW/USD FX, foreign flows, KOSPI/KOSDAQ |

Risk agent has veto power: SELL + confidence >= 80 overrides all others. Korean market agent returns neutral HOLD for US tickers.

### SIEGE Engine

`nuri/trading/engine/` — Gated Execution + Conflict Detection + Learning Memory.

Confidence scoring pipeline (in `candidates.py`):
```
confidence = regime_win_rate × 60% + regime_pf × 40%
           × drift_multiplier (0.3 ~ 1.1)        ← Learning Memory
           × conflict_penalty (0.5x if high)      ← Conflict Detection
           × regime_fit_penalty (0.4x if avoid)    ← Strategy Map
           × position_penalty (0.3x if minimal)    ← Regime position sizing
```

### Scheduler

`nuri/scheduler.py` defines 17 cron jobs in the `SCHEDULES` list. All times are KST. Lazy imports inside `_run_collector()` to avoid import-time side effects.

## Environment Variables

Configured in `.env` (see `.env.example`):
- `FRED_API_KEY` — FRED macro data (optional; yfinance fallback)
- `DISCORD_WEBHOOK_URL` — daily report delivery (optional; falls back to stdout)
- `DISCORD_BOT_TOKEN` — bot mode alerts (optional)
- `FINNHUB_API_KEY` — US institutional flows (optional)
- `OLLAMA_HOST` / `OLLAMA_MODEL` — LLM report (default: localhost:11434, llama3.1)
- `DASHBOARD_PASSWORD` — Next.js dashboard auth (optional; unset = public)
- `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` — Paper trading (optional; DryRun fallback)

## DB Schema (SQLite, WAL mode)

| Table | Purpose |
|-------|---------|
| `prices` | OHLCV 5Y (25K+ rows) |
| `portfolio` | Holdings (account, ticker, qty, avg_price) |
| `macro` | FRED indicators + Fear&Greed |
| `signals` | TA-Lib technical indicators |
| `fundamentals` | PE, ROE, margins, growth, beta |
| `superinvestors` | 13F holdings (Buffett, etc.) |
| `estimates` | Analyst consensus + target prices |
| `recommendations` | Daily recs + 30/60/90d outcome tracking |
| `positions` | Long/Short strategy positions |
| `swing_trades` | Market-wide swing trade positions |
| `strategy_memory` | Signal performance snapshots (append-only) |
| `analyst_ratings` | Upgrade/downgrade history |
| `earnings_surprises` | EPS actual vs estimate |
| `insider_trades` | Insider buy/sell transactions |
| `schema_version` | Migration version tracking |

Plus: `ark`, `events`, `news`, `institutional_flows`, `etf_flows`, `regime_transitions`, `factors`, `backtests`, `llm_bench`.

## Code Conventions

- Python 3.12 with type hints
- Korean comments (한국어 주석), English variable/function names
- Git commit messages in English
- Configuration in YAML (`config/`), secrets in `.env` (git-ignored)
- Korean stock tickers use `.KS` suffix (e.g., `005930.KS` for 삼성전자)

### Config files (`config/`)

- `portfolio.yaml` — 5 accounts (test/demo/sample/pension/irp), 30+ holdings
- `alerts.yaml` — Thresholds (price swing 3%, Fear&Greed bounds 20/80), report timing
- `rules.yaml` — Investment rules (position limits, stop-loss, banned ETFs). Loaded via `nuri/core/rules.py`

### Scripts (`scripts/`)

- `setup.sh` — Creates `.venv` via `uv`, installs deps
- `migrate_db.py` — DB schema creation + migration runner
- `import_portfolio.py` — Syncs `config/portfolio.yaml` → DB portfolio table
- `verify.py` — Master verification orchestrator, saves to `data/reports/YYYY-MM-DD/`
- `gate_check.py` — Pipeline gate verifier (exits 1 if BLOCKED)
- `deploy.sh` — rsync to Mac Mini
- `backup.sh` — 30-day rolling DB backup

## Testing

142 tests across 15 files. Tests use `tmp_path` fixture for isolated SQLite databases:
```python
@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path
```

Pass `db_path` to all DB functions in tests. `conftest.py` mocks yfinance globally to eliminate network calls.

## Investment Rules

Defined in `config/rules.yaml`, loaded via `nuri/core/rules.py`:
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

## OpenBB Provider Limitations

| Endpoint | yfinance | Notes |
|----------|----------|-------|
| `obb.equity.price.historical` | OK | Primary price data source |
| `obb.equity.fundamental.metrics` | OK | PE, PB, ROE, margins, growth, beta |
| `obb.equity.estimates.consensus` | OK | Target price, recommendation, analyst count |
| `obb.equity.fundamental.ratios` | No | Requires `fmp` or `intrinio` (paid) |
| `obb.equity.estimates.price_target` | No | Requires `benzinga` or `fmp` (paid) |
| `obb.equity.ownership.*` | No | Requires `fmp` (paid) |

## Currency handling

Multi-account portfolio mixes USD and KRW. Exchange rate fallback chain: DB `macro` table → OpenBB API → hardcoded default `1450.0` KRW/USD. `.KS` tickers are always treated as KRW.

## Interface

- **FastAPI** (`nuri/api/`) — REST API on port **8001**. Swagger at `http://localhost:8001/docs`. SSE at `/api/stream` (30s interval).
- **Next.js 16** (`frontend/`) — shadcn/ui + Tailwind 4. Dark theme. See `frontend/CLAUDE.md` for frontend-specific guidance.
- **Ollama** (`nuri/llm/report.py`) — LLM report with SIEGE certification.

## MCP Integration

`.mcp.json` configures an MCP SQLite server for direct DB queries via Claude Code:
```json
{"mcpServers": {"nuri-db": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-sqlite", "./data/portfolio.db"]}}}
```

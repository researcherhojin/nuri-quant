# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Nuri-Quant (누리퀀트) — Open-source quant investment platform.
Python 3.12, `uv` package manager, SQLite, 100% free open-source stack.
Linter: `ruff` (E/F/W/I rules, line-length 120). CI: GitHub Actions (lint + test + frontend type-check).
Ruff ignores: E402 (lazy imports in scheduler), E501 (existing long lines), E712 (pandas `== True` idiom).
Conventional commits required in PRs: `(feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)(scope)?: message`.

6-step conceptual pipeline: **Collect → Validate → Classify → Diagnose → Recommend → Track**
Operational execution (`make full-scan`) runs 8 phases: collect → analyze → validate → regime+factors → recommend+consensus+scan → targets+rebalance+certify → evidence → notify.

2-machine setup: M3 Max MacBook (dev) ↔ M2 Pro Mac Mini (24/7 production).

## Commands

```bash
# Setup (requires: Python 3.12, uv, brew install ta-lib, Node 22 for frontend)
make setup                              # venv + deps + DB init + portfolio import
cd frontend && npm ci                   # frontend deps (separate from make setup)

# Data collection
make collect                            # Phase A 11 collectors (stock/stock_kr/macro/technical/fear_greed/ark/cboe/coingecko/finviz/reddit/fred_calendar)
python -m nuri.collectors.stock --period 5y  # US stocks 5Y (OpenBB)
python -m nuri.collectors.stock_kr --days 1825  # Korean stocks 5Y (pykrx)
python -m nuri.collectors.fundamental   # PE/ROE/margins (OpenBB metrics)
python -m nuri.collectors.superinvestors  # Buffett/Gates/Dalio 13F (edgartools)
python -m nuri.collectors.estimates     # Analyst consensus (OpenBB)
make wallstreet                         # analyst ratings, earnings, insider trades
make filings                            # SEC filings

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

# Regime classification (Phase D)
make regime                             # 6-regime classifier + strategy map

# Recommendations (Phase E)
make recommend                          # candidates + tracker (signal-based buy/sell)
python -m nuri.trading.recommend.candidates  # signal-based buy/sell candidates
python -m nuri.trading.recommend.tracker --save  # save + track outcomes

# Multi-Agent Consensus (10 agents)
make consensus                                         # 보유 종목 10-agent analysis
python -m nuri.trading.agents.consensus --ticker TSLA  # 단일 종목

# Strategies
make strategy         # L/S regime + transition + actions
make strategy-execute # Execute L/S strategy positions
make positions        # Position status
make backtest-ls      # full backtest + Monte Carlo
make backtest-stress  # stress test scenarios
make backtest-rules   # rules-based backtest
make optimize         # grid search parameter tuning
make mean-reversion   # mean-reversion scan + backtest
make pairs            # pairs trading scan + backtest

# Swing Trade
make scan             # 89종목 스캔 → 시그널 필터
make swing            # 스캔 + 에이전트 합의 → 진입 저장
make swing-check      # 진행중 스윙 트레이드 상태 확인

# Full Pipeline
make full-scan        # 8-phase: collect→analyze→validate→regime→recommend→certify→evidence→notify
make quick-scan       # 빠른 4-step: collect→analyze→consensus→targets (~2분)

# SIEGE Certification
make certify          # 10-condition 규칙 검증 → CERTIFIED / REJECTED
make gate             # Pipeline gate verifier (exits 1 if BLOCKED)

# Price Targets & Rebalance & Evidence
make targets          # 전 종목 매수가/손절가/익절가 계산
make rebalance        # 규칙 위반 감지 + 매도 수량 제시
make evidence         # 5개 Plotly 증거 차트 생성 (data/reports/{date}/evidence/)
make external         # 외부 데이터 요약 (TipRanks, Dataroma, ARK 등)
make report-llm       # Qwen3.5 LLM 리포트 생성 + 자동 저장

# Lint + Test
make lint             # ruff check
make lint-fix         # ruff check --fix
make test             # pytest tests/ -v --cov=nuri
make verify-quick     # fast pre-commit check: tests + regime (~10s, no network)
make verify-all       # full verification with network (커밋 전 필수)
.venv/bin/python -m pytest tests/test_db.py -v                                    # single file
.venv/bin/python -m pytest tests/test_db.py::TestUpsertPrices -v                  # single class
.venv/bin/python -m pytest tests/test_db.py::TestUpsertPrices::test_insert_and_query -v  # single test

# Interface
make start            # API(:8001) + Dashboard(:3000) simultaneous
make api              # FastAPI only (:8001)
make dashboard        # Next.js only (:3000)

# Verification
make verify           # Master verification orchestrator → data/reports/YYYY-MM-DD/

# Deploy & backup
make pre-deploy       # Safety checks before deploy
make deploy           # rsync to Mac Mini
make backup           # DB backup (30-day rolling)

# Utilities
make ports            # show port usage
make ports-kill       # kill conflicting port processes
```

All `make` targets use `.venv/bin/python` — activate the venv or use the full path.

## Architecture

```
nuri/
├── core/              # DB (sole sqlite3 importer), rules (config/rules.yaml loader)
├── collectors/        # 21 data collectors inheriting BaseCollector
├── analysis/          # portfolio, risk, sector, charts, rebalance_advisor, evidence_charts
├── quant/             # Quantitative pipeline
│   ├── regime/        # 10-regime classifier (6 base + 4 special), macro score, strategy map
│   ├── validation/    # Signal backtest, superinvestor/analyst backtest, scorecard
│   ├── backtest/      # VectorBT engine, grid search optimizer
│   └── factors/       # Multi-factor scoring (momentum, value, quality, composite)
├── trading/           # Trading execution
│   ├── agents/        # 10 agents + consensus engine
│   ├── engine/        # SIEGE: gate, conflicts, learning memory
│   ├── strategy/      # L/S, mean-reversion, pairs trading
│   ├── recommend/     # Candidates, rebalance, tracker, price_targets
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

### Signal system (15 signals, detector registry pattern)

`signal_backtest.py` uses a **detector registry** — each signal registers `entry` and optional `exit` functions in `SIGNAL_DEFINITIONS`. Three categories:

- **Price-based** (10): rsi_oversold/overbought, macd_golden/dead, sma_golden/dead, bb_bounce, volume_spike, gap_up, gap_down
- **Macro-based** (3): vix_reversal, pcr_reversal, yield_curve_recovery — require `merge_macro_data()` (DB macro table)
- **Data-dependent** (2): insider_cluster, short_squeeze — require `merge_data_signals()` (insider_trades, external_analysis tables)

Public API: `compute_indicators()`, `detect_signal_entries()`, `compute_exit()`, `merge_macro_data()`, `merge_data_signals()`. Backward-compatible `_` aliases exist.

**Macro data quirk**: `us_3m_yield` (FRED) is absent in yfinance fallback — `^IRX` (13-week T-Bill) is stored as `us_2y_yield`. `merge_macro_data()` has a fallback: queries `us_2y_yield` when `us_3m_yield` is empty.

### C→D→E data flow

The validation/regime/recommendation pipeline is connected by data, not imports:

1. **C-1** (`signal_backtest`) writes `signal_results.csv` + `signal_scorecard.csv` to `data/reports/YYYY-MM-DD/`
2. **D-3** (`strategy_map.analyze_signal_by_regime()`) reads `signal_results.csv`, labels each trade with the regime active at entry
3. **E-1** (`candidates`) reads the regime-specific stats from D-3 to calibrate confidence scores
4. **E-3** (`tracker`) saves E-1/E-2 outputs to `recommendations` table for 30/60/90-day tracking

Re-running C-1 (`python -m nuri.quant.validation.signal_backtest`) updates the data that D-3 and E-1 use.

### Multi-Agent Consensus (10 agents)

`nuri/trading/agents/` — 10 specialist agents with weighted voting. Thresholds externalized to `config/agents.yaml`, loaded via `nuri/core/agent_config.py`. Confidence normalized to 0-100 via `BaseAgent.normalize_confidence()` (config: `confidence_normalization`).

| Agent | Weight | Data Source |
|-------|--------|-------------|
| `technical.py` | 16% | RSI, MACD, SMA crossovers |
| `fundamental.py` | 12% | PE, ROE, growth, debt |
| `macro_agent.py` | 12% | Regime + macro score + momentum |
| `risk_agent.py` | 20% | Stop-loss, volatility, concentration (**veto power**) |
| `smart_money.py` | 8% | 13F flow + analyst consensus |
| `wallstreet.py` | 11% | Analyst ratings + EPS surprise + insider |
| `korean_market.py` | 8% | KRW/USD FX, foreign flows, KOSPI/KOSDAQ |
| `options_agent.py` | 8% | CBOE Put/Call Ratio (contrarian) |
| `crypto_agent.py` | 5% | BTC price/dominance (risk appetite proxy) |
| `retail_agent.py` | 0% | WSB mentions/posts (data stabilization phase) |

Risk agent has veto power: SELL + confidence >= 80 overrides all others. Korean market agent returns neutral HOLD for US tickers. New agents return graceful HOLD when data unavailable.

### Regime classifier (6 base + 4 special)

Base regimes: `{bull,bear,sideways}_{low,high}_vol` — determined by SPY SMA50/200 position + VIX with adaptive hysteresis (5 days normal, 2 days if VIX≥25).

Special regimes (checked in priority order, override base `regime` field):
- **euphoria**: VIX < 12 AND F&G > 80 → position sizing `defensive`
- **stagflation**: CPI > 4% AND GDP < 1% → `minimal` (GDP data rarely available)
- **recovery**: SMA50 < SMA200 200 days ago AND SMA50 >= SMA200 now → `aggressive`
- **sector_rotation**: SPY ±2% (20d) AND any sector ETF > 3% → `normal`

`RegimeState.trend`/`.volatility` always reflect the base classification. `details["special_regime"]` is `None` or the special name. `details["base_regime"]` always has the 6-regime name.

`REGIME_ALLOCATION` includes all 10 regimes (6 base + 4 special). `position.py` uses `REGIME_ALLOCATION` lookup for regime alignment (fallback to substring matching for unknown regimes).

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

### Pipeline Observability (SIEGE Event Journal + Dagster Freshness)

`nuri/core/events.py` — Append-only event journal. `emit_event()` records all state transitions (step_started/completed/failed/blocked). `get_pipeline_status()` returns 6-step status. `get_timeline()` returns event history with causation_id for chain tracing.

`nuri/core/freshness.py` — Data freshness SLA monitoring. `FRESHNESS_POLICIES` defines warn/fail thresholds per data source. `check_freshness(key)` returns PASS/WARN/FAIL status with age. Sources: prices (18h/30h), VIX (24h/72h), F&G (24h/48h), consensus (24h/48h), certification (24h/48h).

`nuri/core/pipeline.py` — Pipeline orchestration. `STEP_DEPENDENCIES` defines the 6-step DAG. `run_step()` wrapper enforces dependency completion + records events.

`nuri/core/timezone.py` — All internal time is KST. `kst_now()`, `today_kst()`, `to_kst()`. DB stores dates as YYYY-MM-DD strings. **Never use `datetime.now()` directly** — always `kst_now()` or `today_kst()`.

`nuri/api/routes/pipeline.py` — Pipeline control API:
- `GET /api/pipeline/status` — 6-step status + record counts
- `POST /api/pipeline/{step}/run` — Execute step (background)
- `GET /api/pipeline/timeline` — Event log
- `GET /api/freshness` — Data freshness report (PASS/WARN/FAIL per source)

`nuri/api/routes/trades.py` — Trade execution tracking:
- `POST /api/trades` — Record trade execution
- `GET /api/trades` — List trades (optional ticker filter)
- `PUT /api/trades/{id}` — Update exit info

### Dashboard API (Projection-based, <5s)

`/api/dashboard` reads pre-computed results from DB instead of running analysis inline. Consensus results come from `recommendations` table (populated by `make consensus`). Response includes `freshness` and `pipeline_status` fields so the UI shows data age.

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

Plus: `ark`, `events`, `news`, `institutional_flows`, `etf_flows`, `regime_transitions`, `factors`, `backtests`, `llm_bench`, `pipeline_events`, `trades`.

## Code Conventions

- Python 3.12 with type hints
- Korean comments (한국어 주석), English variable/function names
- Git commit messages in English
- Configuration in YAML (`config/`), secrets in `.env` (git-ignored)
- Korean stock tickers use `.KS` suffix (e.g., `005930.KS` for 삼성전자)
- **Timezone: always use `kst_now()` or `today_kst()` from `nuri.core.timezone`** — never `datetime.now()`

### Config files (`config/`)

- `portfolio.yaml` — 5 accounts (kakaopay/mirae/toss/pension/irp), 30+ holdings
- `stock_types.yaml` — Manual growth/value override per ticker. Controls stop-loss/take-profit thresholds (growth: -7%/+20%/+40%, value: -10%/+15%/+30%). Swing type is auto-tagged by scanner.
- `agents.yaml` — Agent thresholds (RSI 30/70, PE 15/40, confidence caps, etc.) loaded via `nuri/core/agent_config.py`. Includes `confidence_normalization` scales for uniform 0-100 mapping.
- `alerts.yaml` — Thresholds (price swing 3%, Fear&Greed bounds 20/80), report timing
- `rules.yaml` — Investment rules loaded via `nuri/core/rules.py`. See [Investment Rules](#investment-rules) for full details.

### Scripts (`scripts/`)

- `setup.sh` — Creates `.venv` via `uv`, installs deps
- `migrate_db.py` — DB schema creation + migration runner
- `import_portfolio.py` — Syncs `config/portfolio.yaml` → DB portfolio table
- `verify.py` — Master verification orchestrator, saves to `data/reports/YYYY-MM-DD/`
- `gate_check.py` — Pipeline gate verifier (exits 1 if BLOCKED)
- `deploy.sh` — rsync to Mac Mini
- `backup.sh` — 30-day rolling DB backup

## Data Directory

```
data/
├── portfolio.db      # Main SQLite DB (WAL mode)
├── reports/          # Pipeline outputs: data/reports/YYYY-MM-DD/
│   └── YYYY-MM-DD/   # signal_results.csv, signal_scorecard.csv, portfolio_action_plan.md, evidence/
├── backups/          # 30-day rolling DB backups
└── exports/          # Ad-hoc exports
```

## Testing

792 tests across 43 files (v10 migrations). Tests use `tmp_path` fixture for isolated SQLite databases:
```python
@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path
```

Pass `db_path` to all DB functions in tests. `conftest.py` (autouse) mocks `yfinance.download` → empty DataFrame and `yfinance.Ticker` → stub with None attributes. All tests run network-free.

### DB Migrations

Add incremental schema changes to `_MIGRATIONS` in `nuri/core/db.py`:
```python
_MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "add column foo to prices", "ALTER TABLE prices ADD COLUMN foo TEXT;"),
]
```
`init_db()` auto-applies unapplied migrations and tracks them in `schema_version` table.

### CI (GitHub Actions)

On push/PR to `main`:
1. **Lint** — `ruff check nuri/ tests/ scripts/`
2. **Test** — pytest with coverage, **40% minimum** enforced (currently 58%). TA-Lib compiled from source (cached).
3. **Frontend** — `tsc --noEmit` + vitest with coverage

PR-specific checks (`pr-checks.yml`):
- Merge conflict detection
- Conventional commit validation (warning, not blocking)
- File size limit: 5MB max
- Trivy security scan (CRITICAL severity only)
- Auto-posted PR summary comment

## Investment Rules

Defined in `config/rules.yaml`, loaded via `nuri/core/rules.py`. Rules based on O'Neil (CAN SLIM), Minervini (SEPA), academic research (disposition effect), and 6 external site analysis.

Core principle: **3:1 profit-to-loss ratio** (loss at -7%, profit at +20%).

| Category | Rule | Value |
|----------|------|-------|
| Position | Max single | 15% |
| Position | Max sector | 35% |
| Position | Min cash reserve | 20% |
| Stop-loss | Growth stocks | -7% |
| Stop-loss | Value stocks | -10% |
| Stop-loss | Portfolio MDD | -10% |
| Take-profit | Growth 1st/2nd | +20% (50% sell) / +40% (25% sell) |
| Take-profit | Value 1st/2nd | +15% (50% sell) / +30% (25% sell) |
| Take-profit | Swing | +5% (50%) / +10% (rest) |
| Trailing stop | Growth/Value | -15% from high |
| Trailing stop | Volatile | -20% from high |
| Entry | VIX > 30 | Block new buys |
| Entry | VIX 25-30 | Half position only |
| Entry | Scaling | Max 3 tranches, 5-day interval |
| Leverage | Banned ETFs | TSLL, TQQQ, SQQQ, UPRO, SPXU |

Buy checklist (all must pass): TipRanks >= Moderate Buy, superinvestors >= 3, PE < 100, revenue > $0, factor score top 50%.

### Automated rule enforcement (`price_targets.py`)

- `check_take_profit_signals()` — detects holdings reaching target_1/target_2 with correct sell percentages
- `check_trailing_stop_signals()` — calculates High Water Mark from prices table, triggers at -15% (growth/value) or -20% (swing)
- `check_portfolio_mdd()` — checks portfolio-wide PnL against -10% limit with KRW/USD conversion
- DB migrations v8-v10 added `target_1_price`, `target_2_price`, `high_water_mark` to `positions` table

### External data sources for investment decisions

Before any buy/sell recommendation, verify against 10 external sites:
1. **dataroma.com** — Superinvestor 13F holdings, buy/sell trends
2. **tradingeconomics.com** — GDP, CPI, Fed rate, employment, recession signals
3. **macrotrends.net** — PE ratios, revenue, historical valuations
4. **tipranks.com** — Analyst consensus, price targets, upside %
5. **etf.com** — Fund flows, sector rotation, risk-on/risk-off
6. **ark-funds.com** — Cathie Wood buy/sell activity
7. **shortinterest.com** — Short interest data, short squeeze signals
8. **cboe.com** — VIX term structure, put/call ratios
9. **coingecko.com** — BTC/crypto sentiment as risk appetite proxy
10. **finviz.com** — Screener, sector heatmaps, insider trading

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

Multi-account portfolio mixes USD and KRW. Exchange rate fallback chain: DB `macro` table → OpenBB API → `StaleExchangeRateError` (no hardcoded fallback). Warns if rate > 7 days old. `.KS` tickers are always treated as KRW.

## Interface

- **FastAPI** (`nuri/api/`) — REST API on port **8001**. Swagger at `http://localhost:8001/docs`. SSE at `/api/stream` (30s interval).
- **Next.js 16** (`frontend/`) — shadcn/ui + Tailwind 4. Dark theme. See `frontend/CLAUDE.md` for frontend-specific guidance. **Warning**: Next.js 16 has breaking API changes vs training data — read `node_modules/next/dist/docs/` before writing frontend code.
- **Ollama** (`nuri/llm/report.py`) — LLM report with SIEGE certification.

## Portfolio Action Plan Format

When generating portfolio recommendations, save to `data/reports/YYYY-MM-DD/portfolio_action_plan.md`. Must include:
- Market environment table (regime, VIX, F&G, macro score, S&P 500 status)
- Per-stock verdict with all 6 external data sources cross-referenced
- Execution timeline (day-by-day sell/buy plan)
- Re-entry conditions (VIX/F&G thresholds)
- Buy priority ranked by multi-factor score + external data

### Price targets format

Every buy/sell recommendation **must** include explicit price levels:

```
종목: NVDA
현재가: $168.00
├── 매수가 (진입): $165.00 (지지선 근처 지정가)
├── 손절가: $153.45 (-7%)
├── 1차 익절: $198.00 (+20%) → 보유량 50% 매도
├── 2차 익절: $231.00 (+40%) → 보유량 25% 매도
├── 트레일링 스톱: 고점 대비 -15% 추적 (나머지 25%)
└── TipRanks 목표가: $273.61 (+63%)
```

Growth stocks use -7% stop / +20%/+40% targets. Value stocks use -10% stop / +15%/+30% targets. Always show the TipRanks consensus target for reference.

## MCP Integration

`.mcp.json` configures an MCP SQLite server for direct DB queries via Claude Code:
```json
{"mcpServers": {"nuri-db": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-sqlite", "./data/portfolio.db"]}}}
```

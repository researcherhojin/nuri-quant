# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@docs/STRATEGY.md

## Project

Nuri-Quant (누리퀀트) — Open-source quant investment platform.
Python 3.12, `uv` package manager (`uv.lock` for reproducibility), SQLite, 100% free open-source stack.
Dependencies split: core in `[project.dependencies]`, pytest/ruff in `[project.optional-dependencies].dev`.
Linter: `ruff` (E/F/W/I rules, line-length 120). CI: GitHub Actions (lint + test + frontend type-check).
Ruff ignores: E402 (lazy imports in scheduler), E501 (existing long lines), E712 (pandas `== True` idiom).
Conventional commits required in PRs: `(feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)(scope)?: message`.

6-step conceptual pipeline: **Collect → Validate → Classify → Diagnose → Recommend → Track**
Operational execution (`make full-scan`) runs 8 phases: collect → analyze → validate → regime+factors → recommend+consensus+scan → targets+rebalance+certify → evidence → notify.

2-machine setup: M5 Max MacBook (dev) ↔ M2 Pro Mac Mini (24/7 production).

## Commands

```bash
# Setup (requires: Python 3.12, uv, brew install ta-lib, Node 22 for frontend)
make setup                              # venv + deps (--extra dev) + DB init + portfolio import
cd frontend && npm ci                   # frontend deps (separate from make setup)
uv sync --extra dev                     # manual: install with test/lint tools

# Data collection
make collect                            # Phase A 12 collectors (stock/stock_kr/macro/technical/fear_greed/ark/cboe/coingecko/finviz/reddit/fred_calendar/macro_news)
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
make regime                             # regime classifier (6 base + 4 special) + strategy map

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
make scan             # 88종목 스캔 (UNIVERSE) → 시그널 필터
make swing            # 스캔 + 에이전트 합의 → 진입 저장
make swing-check      # 진행중 스윙 트레이드 상태 확인

# Full Pipeline
make full-scan        # 8-phase: collect→analyze→validate→regime→recommend→certify→evidence→notify
make quick-scan       # 빠른 4-step: collect→analyze→consensus→targets (~2분)

# SIEGE Certification
make certify          # 11-condition 규칙 검증 → CERTIFIED / REJECTED
make remediate        # REJECTED → 진단 + 매도 처방 + post-remediation 예측
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
scripts/sync_dev.sh push      # Dev↔dev 노트북 상태 동기화 (.env, DB, ~/.claude Tier 3)
scripts/sync_dev.sh pull      # 반대 방향 (--with-reports / --no-claude 옵션)
bash scripts/auto_deploy.sh   # Mac mini receiver: fetch + ff-only merge + 변경 분석 (manual test; canonical run is launchd com.nuri-quant.autopull every 5min)

# Utilities
make ports            # show port usage
make ports-kill       # kill conflicting port processes
```

All `make` targets use `.venv/bin/python` — activate the venv or use the full path.

## Architecture

```
nuri/
├── core/              # DB (sole sqlite3 importer), rules, signal_config, timezone, events, freshness
├── collectors/        # 24 collector modules (BaseCollector subclasses + standalone, incl. KIS Open API)
├── analysis/          # portfolio, risk, sector, charts, rebalance_advisor, evidence_charts
├── quant/             # Quantitative pipeline
│   ├── regime/        # 10-regime classifier (6 base + 4 special), macro score, strategy map
│   ├── validation/    # Signal backtest (20 signals), superinvestor/analyst backtest, scorecard
│   ├── backtest/      # VectorBT engine, grid search optimizer
│   ├── factors/       # Multi-factor scoring (momentum, value, quality, composite)
│   └── chart_analysis.py  # 시각 차트 패턴 분석 (BB, MACD turn, 52w, POC, 추세선)
├── trading/           # Trading execution
│   ├── agents/        # 10 agents + consensus engine
│   ├── engine/        # SIEGE: gate, conflicts, learning memory
│   ├── strategy/      # L/S, mean-reversion, pairs trading
│   ├── recommend/     # Candidates, rebalance, tracker, price_targets
│   ├── swing/         # Market-wide scanner + rules
│   └── execution/     # Broker interface (Alpaca paper + DryRun)
├── api/               # FastAPI REST API (routes/)
├── alerts/            # Discord daily report + bot, Telegram alerts
└── llm/               # LLM report (Ollama) + OpenAI wrapper + event classifier
```

### DB as the sole integration point

`nuri/core/db.py` is the **only** module that imports `sqlite3`. Every other module reads/writes through its functions. The DB file lives at `data/portfolio.db` (WAL mode). All upsert functions accept an optional `db_path` parameter — tests use this to inject a `tmp_path` fixture for isolation. Schema versioning via `schema_version` table + `_MIGRATIONS` list for incremental changes.

Key DB access patterns:
- `get_db()` — context manager, auto-commits on success, auto-rollbacks on exception
- `query(sql, params)` → list of `sqlite3.Row` (dict-like access)
- `query_df(sql, params)` → pandas DataFrame
- `upsert_*()` functions for each table (prices, portfolio, fundamentals, etc.)
- `replace_portfolio_account(account, records)` — DELETE+INSERT in one tx for proper yaml→DB sync (removes stale rows when a ticker leaves yaml)

### Collector template pattern

All collectors inherit `BaseCollector` (`nuri/collectors/base.py`). The contract:
1. Implement `collect(**kwargs) -> Any` (fetch data)
2. Implement `save(data) -> int` (persist to DB)
3. External code calls `run()` which does `collect()` → `save()` with logging and timing

`_get_tickers(market=)` filters portfolio tickers: `"us"` excludes `.KS`, `"kr"` includes only `.KS`.

### Signal system (20 signals, YAML-driven registry)

`signal_backtest.py` uses a **detector registry** — Python detector 함수와 메타데이터(임계값/분류/hold_days)를 분리.
메타데이터는 `config/signals.yaml`에 외부화 (`nuri/core/signal_config.py` 로드). 4 카테고리:

- **Price-based** (10): rsi_oversold/overbought, macd_golden/dead, sma_golden/dead, bb_bounce, volume_spike, gap_up, gap_down
- **Macro-based** (3): vix_reversal, pcr_reversal, yield_curve_recovery — `merge_macro_data()` 필요
- **Data-dependent** (2): insider_cluster, short_squeeze — `merge_data_signals()` 필요
- **Chart pattern** (5): macd_bullish_turn, macd_bearish_turn, bb_squeeze_breakout, near_52w_low_bounce, volume_profile_resistance — `nuri/quant/chart_analysis.py`와 동일 컨셉

`SIGNAL_DEFINITIONS`는 `_build_signal_definitions()`이 YAML + detector registry에서 빌드. 임계값 변경 → YAML만 수정 (코드 변경 0).
`BUY_SIGNALS`/`SELL_SIGNALS`는 YAML의 `type` 필드에서 자동 추출.

**Macro data quirk**: `us_3m_yield` (FRED) is absent in yfinance fallback — `^IRX` (13-week T-Bill) is stored as `us_2y_yield`. `merge_macro_data()` has a fallback: queries `us_2y_yield` when `us_3m_yield` is empty.

### C→D→E data flow

The validation/regime/recommendation pipeline is connected by data, not imports:

1. **C-1** (`signal_backtest`) writes `signal_results.csv` + `signal_scorecard.csv` to `data/reports/YYYY-MM-DD/`
2. **D-3** (`strategy_map.analyze_signal_by_regime()`) reads `signal_results.csv`, labels each trade with the regime active at entry
3. **E-1** (`candidates`) reads the regime-specific stats from D-3 to calibrate confidence scores
4. **E-3** (`tracker`) saves E-1/E-2 outputs to `recommendations` table for 30/60/90-day tracking

Re-running C-1 (`python -m nuri.quant.validation.signal_backtest`) updates the data that D-3 and E-1 use.

### Multi-Agent Consensus (10 agents)

`nuri/trading/agents/` — 10 specialist agents with weighted voting. Config in `config/agents.yaml`, loaded via `nuri/core/agent_config.py`. Confidence normalized to 0-100 via `BaseAgent.normalize_confidence()`.

Key behaviors:
- Risk agent (20% weight) has **veto power**: SELL + confidence >= 80 overrides all others
- Korean market agent returns neutral HOLD for US tickers
- Retail agent weight is 0% (data stabilization phase)
- New agents return graceful HOLD when data unavailable

### Regime classifier (6 base + 4 special)

Base regimes: `{bull,bear,sideways}_{low,high}_vol` — determined by SPY SMA50/200 position + VIX with adaptive hysteresis (5 days normal, 2 days if VIX≥25).

Special regimes (priority order, override base `regime` field): euphoria, stagflation, recovery, sector_rotation. See `nuri/quant/regime/classifier.py` for thresholds.

`RegimeState.trend`/`.volatility` always reflect the base classification. `details["special_regime"]` is `None` or the special name. `details["base_regime"]` always has the 6-regime name.

`REGIME_ALLOCATION` includes all 10 regimes (6 base + 4 special). `position.py` uses `REGIME_ALLOCATION` lookup for regime alignment (fallback to substring matching for unknown regimes).

### SIEGE Engine

`nuri/trading/engine/` — Gated Execution + Conflict Detection + Learning Memory. Confidence scoring in `candidates.py` combines regime win rate, profit factor, learning memory drift, conflict penalties, and regime fit. See `docs/STRATEGY.md` §3.3 for formula and §6 for SIEGE 11-Gate specification.

### Pipeline Observability (SIEGE Event Journal + Dagster Freshness)

`nuri/core/events.py` — Append-only event journal. `emit_event()` records all state transitions (step_started/completed/failed/blocked). `get_pipeline_status()` returns 6-step status. `get_timeline()` returns event history with causation_id for chain tracing.

`nuri/core/freshness.py` — Data freshness SLA monitoring. `FRESHNESS_POLICIES` defines warn/fail thresholds per data source. `check_freshness(key)` returns PASS/WARN/FAIL status with age. Sources: prices (48h/120h), VIX (24h/72h), F&G (24h/48h), consensus (24h/48h), certification (24h/48h).

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

`nuri/scheduler.py` defines 21 cron jobs in the `SCHEDULES` list. All times are KST. Lazy imports inside `_run_collector()` to avoid import-time side effects.

## Environment Variables

Configured in `.env` (see `.env.example`):
- `FRED_API_KEY` — FRED macro data (optional; yfinance fallback)
- `DISCORD_WEBHOOK_URL` — daily report delivery (optional; falls back to stdout)
- `DISCORD_TOKEN` — bot mode alerts (optional)
- `FINNHUB_API_KEY` — US institutional flows (optional)
- `OLLAMA_HOST` / `OLLAMA_MODEL` — LLM report (default: localhost:11434, qwen3.5)
- `DASHBOARD_PASSWORD` — Next.js dashboard auth (optional; unset = public)
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — Telegram alerts (optional)
- `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` — Paper trading (optional; DryRun fallback)
- `KIS_PROD_APP_KEY` / `KIS_PROD_APP_SECRET` — KIS Open API live mode (optional; falls back to `~/KIS/config/kis_devlp.yaml`)
- `KIS_PAPER_APP_KEY` / `KIS_PAPER_APP_SECRET` — KIS Open API paper mode (optional)

## DB Schema (SQLite, WAL mode)

29 tables total (13 migrations). Key tables:

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
| `pipeline_events` | Append-only event journal |
| `trades` | Trade execution records |

Additional: `ark`, `events`, `news`, `institutional_flows`, `etf_flows`, `regime_transitions`, `factors`, `backtests`, `audit_log`, `external_analysis`, `macro_events`, `external_llm_calls`.

## Code Conventions

- Python 3.12 with type hints
- Korean comments (한국어 주석), English variable/function names
- Git commit messages in English
- Configuration in YAML (`config/`), secrets in `.env` (git-ignored)
- Korean stock tickers use `.KS` suffix (e.g., `005930.KS` for 삼성전자)
- **Timezone: always use `kst_now()` or `today_kst()` from `nuri.core.timezone`** — never `datetime.now()`

### Config files (`config/`)

- `portfolio.yaml` — 7 accounts (test/demo/sample/pension/irp/test/sample), 30 holdings (test 17 + demo 10 + sample 3)
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
- `deploy.sh` — rsync dev → Mac Mini production
- `sync_dev.sh` — dev↔dev 두 노트북 간 상태 동기화 (gitignore된 파일 + ~/.claude Tier 3, rsync over SSH)
- `auto_deploy.sh` — Mac mini receiver. launchd `com.nuri-quant.autopull` (5분 간격)이 호출. fetch → ff-only merge → dependency/schema drift 경고 → 서비스 재시작 hook (placeholder). 로그: `~/Library/Logs/nuri-quant-autopull.log`
- `com.nuri-quant.autopull.plist` — 위 스크립트의 launchd 템플릿. 설치: `cp ~/Library/LaunchAgents/ && launchctl load`
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

2,524 backend tests across 125 files (`tests/{alerts,analysis,api,collectors,core,llm,quant,scripts,trading/}` subdirs + `test_scheduler.py`) + 594 frontend vitest (45 files) + 21 Playwright E2E (4 spec files). Uses `pytest-xdist` for parallel execution (`-n auto --dist worksteal`). Coverage policy: no fixed minimum — Codecov gates on a 1% relative regression vs prior commit (`codecov.yml` `target: auto`). Tests use `tmp_path` fixture for isolated SQLite databases:
```python
@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path
```

Pass `db_path` to all DB functions in tests. `conftest.py` (autouse) mocks `yfinance.download` → empty DataFrame and `yfinance.Ticker` → stub with None attributes. All tests run network-free.

### Verifying numeric claims

All counts in this doc are verified against code. Re-run after major changes — drift here causes future sessions to make decisions on stale facts.

```bash
# Tests
.venv/bin/python -m pytest tests/ --collect-only -q | tail -1   # backend
find tests -name "test_*.py" -type f | wc -l                     # backend test files (incl. subdirs)
cd frontend && npx vitest run | tail -5                          # frontend (Test Files / Tests)
grep -rhE "^\s*test\(" frontend/e2e/ | wc -l                     # Playwright E2E

# Architectural counts
ls nuri/collectors/*.py | grep -vE 'base|__init__' | wc -l       # collectors
ls nuri/trading/agents/*.py | grep -vE 'base|__init__|consensus|config' | wc -l  # agents
.venv/bin/python -c "from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS; print(len(SIGNAL_DEFINITIONS))"  # signals
.venv/bin/python -c "from nuri.trading.strategy.longshort import REGIME_ALLOCATION; print(len(REGIME_ALLOCATION))"  # regimes
grep -rhE "@router\.(get|post|put|delete|patch)" nuri/api/routes/ | wc -l  # API endpoints
grep -c "CREATE TABLE" nuri/core/db.py                           # DB tables
find frontend/src/app -name "page.tsx" | wc -l                   # frontend routes
```

If any of these disagree with the numbers stated above, **fix the doc** — do not weaken the claim to be drift-immune. Precise numbers are load-bearing for trust.

### DB Migrations

Add incremental schema changes to `_MIGRATIONS` in `nuri/core/db.py`:
```python
_MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "add column foo to prices", "ALTER TABLE prices ADD COLUMN foo TEXT;"),
]
```
`init_db()` auto-applies unapplied migrations and tracks them in `schema_version` table.

### CI/CD Pipeline (`main-ci-cd.yml`)

On push/PR to `main`:
1. **Lint** — `ruff check nuri/ tests/ scripts/`
2. **Test** — pytest with `pytest-xdist` parallel (`-n auto`, sharded into 2). Coverage uploaded to Codecov; no `--cov-fail-under` is set, so the gate is Codecov's 1% relative regression check (`codecov.yml`), not a fixed pytest threshold. TA-Lib compiled from source (cached). Deps installed via `uv sync --frozen` (lockfile: `uv.lock`).
3. **Frontend** — `tsc --noEmit` + vitest with coverage

PR-specific checks (`pr-checks.yml`):
- Merge conflict detection
- Conventional commit validation (warning, not blocking)
- File size limit: 5MB max
- Auto-posted PR summary comment

Security: Trivy vulnerability scan (CRITICAL severity) runs in `main-ci-cd.yml` (not pr-checks).

## Gotchas

- **Next.js 16 breaking changes**: APIs differ from LLM training data — always read `node_modules/next/dist/docs/` first. See `frontend/AGENTS.md`.
- **vi.mock() hoisting** (frontend): `vi.mock("recharts")` affects ALL dynamic imports in the same vitest worker. Keep recharts-dependent and recharts-free tests in separate files. Use `vi.doMock` for per-test control.
- **runpy + mock**: `runpy.run_module()` re-executes module source, invalidating mocks. Use `patch("source.module.function")` for source-level patching.
- **OpenBB local import**: `obb` is imported inside functions (not at module level). `patch("module.obb")` fails — use `patch.dict(sys.modules, {"openbb": mock_module})`.

## Investment Rules

Defined in `config/rules.yaml`, loaded via `nuri/core/rules.py`. Full rule table with academic sources: `docs/STRATEGY.md` §3.4 and §6.

Core principle: **3:1 profit-to-loss ratio** (growth: -7% stop / +20%/+40% targets, value: -10% stop / +15%/+30% targets).

Automated enforcement in `price_targets.py`: take-profit signals, trailing stop (HWM-based), portfolio MDD check. Buy checklist: TipRanks >= Moderate Buy, superinvestors >= 3, PE < 100, revenue > $0, factor score top 50%.

Every recommendation requires 10 external data sources cross-referenced (dataroma, tipranks, tradingeconomics, macrotrends, etf.com, ark-funds, shortinterest, cboe, coingecko, finviz).

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
- **Next.js 16** (`frontend/`) — shadcn/ui + Tailwind 4. Dark-only theme (zinc-950 base). See below.
- **Ollama** (`nuri/llm/report.py`) — LLM report with SIEGE certification.

### Frontend (`frontend/`)

**Next.js 16 + React 19 + Tailwind CSS 4 + shadcn/ui.** APIs differ from LLM training data — always read `node_modules/next/dist/docs/` first.

```bash
cd frontend
npm run dev            # Dev server (:3000)
npm run build          # Production build (type-check + compile)
npm run test           # vitest run (593 tests, 45 files)
npx vitest run src/__tests__/pages/dashboard.test.tsx  # single file
npx vitest run -t "renders verdict"                    # single test by name
```

All pages are **Server Components** with `force-dynamic`. Data fetched server-side via `fetchAPI()` (`src/lib/api.ts`). Two Client Components: `/report` (LLM generation) and `/pipeline` (ReactFlow DAG).

**15 routes**: `/` (dashboard), `/signals`, `/consensus`, `/scan`, `/strategy`, `/rebalance`, `/engine`, `/pipeline`, `/report`, `/evidence`, `/portfolio`, `/targets`, `/advisor`, `/login`, `/ticker/[symbol]`.

**Design system** — 3 shared components enforce visual consistency:
- `DataTable` — Universal table with column config, renderers, `rowClassName`, compact mode
- `StatusBadge` — BUY/SELL/HOLD/WATCH/LONG/SHORT + signal types
- `Metric` — Label + value + sub-text with color

**Conventions**: `async function Section()` in `<Suspense>`, `animate-pulse` skeletons, color semantics (emerald=BUY, red=SELL, amber=warning, blue=WATCH, zinc=HOLD), `text-[10px]` sub-labels.

**Frontend testing** (593 vitest, 45 files): Mock `@/lib/api` + `next/navigation`. Recharts mock hoisting caveat: keep recharts-dependent and recharts-free tests in separate files.

**Auth**: `src/middleware.ts` — SHA256 cookie-based, active only when `DASHBOARD_PASSWORD` is set.

## Portfolio Action Plan Format

Save to `data/reports/YYYY-MM-DD/portfolio_action_plan.md`. Required sections: market environment table (regime, VIX, F&G, macro), per-stock verdict with external data cross-reference, execution timeline, re-entry conditions, buy priority by multi-factor score.

Every recommendation **must** include explicit price levels: entry, stop-loss, target_1, target_2, trailing stop, TipRanks target. Growth: -7%/+20%/+40%. Value: -10%/+15%/+30%.

## MCP Integration

`.mcp.json` configures an MCP SQLite server for direct DB queries via Claude Code:
```json
{"mcpServers": {"nuri-db": {"command": "uvx", "args": ["mcp-server-sqlite", "--db-path", "./data/portfolio.db"]}}}
```

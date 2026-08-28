# Architecture Reference

Detailed reference for Nuri-Quant internals. This file is NOT auto-loaded — agents read it when working on cross-cutting concerns.
## Pipeline Phases (5-step)
README shows the high-level flow. Per-phase orientation table — each row points at the canonical detail section below (or peer doc).
| # | Phase | Inputs | Outputs | Key modules | Detail |
|---|-------|--------|---------|-------------|--------|
| 1 | **Collect** | External APIs (yfinance · OpenBB · pykrx · KIS · Toss · FRED · Wikipedia · GoogleNews RSS · FINVIZ · ARK · Reddit) | `prices` · `fundamentals` · `macro` · `superinvestors` · `estimates` · `analyst_ratings` · `insider_trades` · `news` · `events` tables | `nuri/collectors/` (27 collectors, BaseCollector pattern) | [KIS_INTEGRATION.md](KIS_INTEGRATION.md) · `nuri/collectors/CLAUDE.md` |
| 2 | **Analyze** | Phase 1 tables | `signal_results.csv` + `signal_scorecard.csv` + `regime_transitions` + `factors` tables | `nuri/quant/regime/` · `nuri/quant/validation/` · `nuri/quant/factors/` · `nuri/llm/event_classifier.py` | "Signal System" + "Regime Classifier" below |
| 3 | **Consensus** | Phase 2 outputs + `portfolio` + `macro_events` | `recommendations` table rows with per-agent verdicts + weighted final action | `nuri/trading/agents/` (10 specialists + consensus engine, risk veto) | `nuri/trading/agents/CLAUDE.md` |
| 4 | **Certify** | Phase 3 recommendations + `config/rules.yaml siege_gates` | `Certificate` → CERTIFIED / REJECTED + evidence trace via `pipeline_events` | `nuri/trading/engine/certification.py` | "SIEGE Engine" below + [CERTIFICATION_SPEC.md](CERTIFICATION_SPEC.md) |
| 5 | **Track** | Phase 3 `recommendations.action` + actual prices after N days | `outcome_30d` / `outcome_60d` / `outcome_90d` + `agent_accuracy_snapshots` (feeds Learning Memory back to Phase 3 weights) | `nuri/trading/recommend/tracker.py` + `nuri/trading/engine/learning_memory.py` | "C→D→E Data Flow" below |
The **Serve** layer (FastAPI `:8001` + Next.js `:3000` + Discord/Telegram) is a read-only projection from the DB — not a pipeline phase. See "API (72 endpoints)" and "Dashboard API" sections below.
## DB as the Sole Integration Point
`nuri/core/db/` is the **only** module that imports `sqlite3`. DB file: `data/portfolio.db` (WAL mode). All upsert functions accept optional `db_path` — tests inject `tmp_path` for isolation. Schema versioning via `schema_version` table + `_MIGRATIONS` list.
Key DB access patterns:
- `get_db()` — context manager, auto-commits on success, auto-rollbacks on exception
- `query(sql, params)` → list of `sqlite3.Row` (dict-like access)
- `query_df(sql, params)` → pandas DataFrame
- `upsert_*()` functions for each table (prices, portfolio, fundamentals, etc.)
- `replace_portfolio_account(account, records)` — DELETE+INSERT in one tx for yaml→DB sync
## Signal System (22 signals: 20 actionable + 2 shadow, YAML-driven registry)
`signal_backtest.py` uses a **detector registry** — Python detector functions separated from metadata (thresholds/classification/hold_days). Metadata externalized to `config/signals.yaml` (`nuri/core/signal_config.py` loads); the yaml holds 22 entries — the 20 actionable ones below plus 2 market-wide shadow signals (`actionable: false`, detectors in `nuri/quant/validation/market_signals.py`). 4 categories:
- **Price-based** (10): rsi_oversold/overbought, macd_golden/dead, sma_golden/dead, bb_bounce, volume_spike, gap_up, gap_down
- **Macro-based** (3): vix_reversal, pcr_reversal, yield_curve_recovery — `merge_macro_data()` required
- **Data-dependent** (2): insider_cluster, short_squeeze — `merge_data_signals()` required
- **Chart pattern** (5): macd_bullish_turn, macd_bearish_turn, bb_squeeze_breakout, near_52w_low_bounce, volume_profile_resistance
`SIGNAL_DEFINITIONS` built by `_build_signal_definitions()` from YAML + detector registry. Threshold changes → YAML only (zero code changes).
**Macro data quirk**: `us_3m_yield` (FRED) absent in yfinance fallback — `^IRX` (13-week T-Bill) stored as `us_2y_yield`. `merge_macro_data()` falls back: queries `us_2y_yield` when `us_3m_yield` is empty.
## C→D→E Data Flow
Validation/regime/recommendation pipeline connected by data, not imports:
1. **C-1** (`signal_backtest`) writes `signal_results.csv` + `signal_scorecard.csv` to `data/reports/YYYY-MM-DD/`
2. **D-3** (`strategy_map.analyze_signal_by_regime()`) reads `signal_results.csv`, labels each trade with regime at entry
3. **E-1** (`candidates`) reads regime-specific stats from D-3 to calibrate confidence scores
4. **E-3** (`tracker`) saves E-1/E-2 outputs to `recommendations` table for 30/60/90-day tracking
Re-running C-1 updates the data that D-3 and E-1 use.
## Regime Classifier (6 base + 4 special)
Base regimes: `{bull,bear,sideways}_{low,high}_vol` — SPY SMA50/200 position + VIX with adaptive hysteresis (5 days normal, 2 days if VIX>=25).
Special regimes (priority order, override base `regime` field): euphoria, stagflation, recovery, sector_rotation. See `nuri/quant/regime/classifier.py`.
`RegimeState.trend`/`.volatility` always reflect base classification. `details["special_regime"]` is `None` or the special name. `details["base_regime"]` always has the 6-regime name.
`REGIME_ALLOCATION` includes all 10 regimes. `position.py` uses `REGIME_ALLOCATION` lookup (fallback to substring matching for unknown regimes).
## SIEGE Engine
`nuri/trading/engine/` — Gated Execution + Conflict Detection + Learning Memory. Confidence scoring in `candidates.py` combines regime win rate, profit factor, learning memory drift, conflict penalties, and regime fit.
Full certification architecture + 3-dimensional certification specification: **[`docs/CERTIFICATION_SPEC.md`](CERTIFICATION_SPEC.md)** (canonical). Confidence scoring formula: [`docs/STRATEGY.md` §3.3](STRATEGY.md). Gate policy: [`docs/STRATEGY.md` §6](STRATEGY.md).
## Pipeline Observability
`nuri/core/events.py` — Append-only event journal. `emit_event()` records state transitions and always writes **valid JSON** to `payload` (#935). `get_pipeline_status()` returns 5-stage status. `get_timeline()` returns history with `causation_id` for chain tracing.
`nuri/core/freshness.py` — Data freshness SLA. `check_freshness(key)` returns PASS/WARN/FAIL. Thresholds (`warn_hours`/`fail_hours` per source) live in `config/freshness.yaml` (#1181) — `_load_config()` injects them at import and the key set is cross-checked both ways against `FRESHNESS_POLICIES` (missing or extra config key → ValueError). Queries/labels stay in code. `VERDICT_GATE_KEYS` + `stale_verdict_inputs()` feed the dashboard verdict's stale gate — FAIL only; WARN passes because weekend/holiday age is normal.
`nuri/core/pipeline.py` — Pipeline orchestration. `STEP_DEPENDENCIES` defines the 5-stage DAG (`collect → analyze → consensus → certify → track`). `run_step()` enforces dependency completion + records events.
Pipeline control API (`nuri/api/routes/pipeline.py`):
- `GET /api/pipeline/status` — 5-stage status + record counts
- `POST /api/pipeline/{step}/run` — Execute step (background)
- `GET /api/pipeline/timeline` — Event log
- `GET /api/freshness` — Data freshness report
Trade execution API (`nuri/api/routes/trades.py`):
- `POST /api/trades` — Record trade execution
- `GET /api/trades` — List trades (optional ticker filter)
- `PUT /api/trades/{id}` — Update exit info
## Dashboard API (Projection-based, <5s)
`/api/dashboard` reads pre-computed results from DB instead of running analysis inline. Consensus from `recommendations` table (populated by `make consensus`). Response includes `freshness` and `pipeline_status` for data age display. The one-line `verdict` is stale-gated (#1181): when any `verdict_gate` input (`config/freshness.yaml`) is FAIL-stale, the response carries `verdict_level: "stale"` + `verdict_stale_inputs` and the verdict text names the stale inputs instead of advising.
## API (73 endpoints)
`nuri/api/routes/` — 73 REST endpoints on port **8001** (`@router.get/post/put/delete/patch` decorators counted across 21 route modules; excludes FastAPI's `/docs`, `/redoc`, `/openapi.json`, `/docs/oauth2-redirect`). Swagger at `http://localhost:8001/docs`. SSE at `/api/stream` (30s interval). Includes `/api/coverage` (#297) for Universe + Agent data coverage widget.
### Action-First Dashboard APIs (PR #264-#266)
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/actions` | GET | 우선순위 분류된 오늘의 액션 (🔴urgent/🟡check/🟦portfolio/✅hold). 연금/IRP 제외, 중복 제거. 각 항목에 `decision_id` + `as_of` (same-date `decisions` LEFT JOIN, #1182) — 프론트가 `/decisions/{id}` 증거 체인으로 링크 |
| `/api/opportunities` | GET | 비보유 이슈 종목 탐색 — scan + WSB + events 기반 찬성/반대/판정 |
| `/api/market-context` | GET | 시스템 건강 (SIEGE/regime/macro/freshness) + 매크로 이벤트 (한국어 카테고리) |
| `/api/backtest/equity` | GET | Equity curve + drawdown + metrics (Recharts frontend용 경량 데이터) |
## Scheduler
`nuri/scheduler.py` — 57 cron jobs in `SCHEDULES` list (+ a 1-minute `heartbeat` interval job). All times KST. Lazy imports inside `_run_collector()` to avoid import-time side effects. A daily `self_restart` job (08:40 KST) recycles the process to reclaim leaked yfinance file descriptors; a daily `stock_us_freshness` job (06:10/06:40 KST) keeps the SPY measurement benchmark + SIEGE freshness tickers current (§3.11).
## Environment Variables
Configured in `.env` (see `.env.example`):
- `FRED_API_KEY` — FRED macro data (optional; yfinance fallback)
- `DISCORD_WEBHOOK_URL` — daily report (optional; stdout fallback)
- `DISCORD_TOKEN` — bot mode alerts (optional)
- `FINNHUB_API_KEY` — US institutional flows (optional)
- `OLLAMA_HOST` / `OLLAMA_MODEL` — LLM report (default: localhost:11434, qwen3.5)
- `NURI_DB_PATH` — SQLite DB location override (optional; default: `data/portfolio.db`)
- `DASHBOARD_PASSWORD` — Next.js auth (optional; unset = public)
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — Telegram alerts (optional)
- `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` — Paper trading (optional; DryRun fallback)
- `KIS_PROD_APP_KEY` / `KIS_PROD_APP_SECRET` — KIS Open API live (optional; falls back to `config/kis/kis_devlp.yaml`, gitignored)
- `KIS_PAPER_APP_KEY` / `KIS_PAPER_APP_SECRET` — KIS Open API paper (optional)
- `TOSS_API_KEY` / `TOSS_SECRET_KEY` / `TOSS_ACCOUNT_SEQ` — Toss Open API (optional; IP allowlist — dev machines get 403 and gracefully skip)
- `NURI_ROLE` — `production` gates §3.11 ledger-backed surfacing (the monthly alpha progress report only stages to `#brief` when set). Adjudication runs off the Mac mini DB; the MBP is a read replica, so dev numbers must never reach the brief. Lives in `scripts/launchd/com.nuri-quant.scheduler.plist` `EnvironmentVariables`, **not** `.env` — `make deploy-mini` SCPs the MBP `.env` over the mini's, so an `.env`-resident value is wiped by the next deploy (same trap as `DEV2_HOST`).
- `API_SECRET_KEY` — JWT signing key (**required in production**, optional in dev). Unset, `nuri/api/auth.py` mints a fresh `secrets.token_hex(32)` each boot, so every outstanding JWT dies on restart (dashboard re-login). Generate: `python3 -c "import secrets; print(secrets.token_hex(32))"`. `make deploy-mini` SCPs the local `.env` onto the Mac mini's, so the same value must exist in **both** `.env` files or a deploy reverts production to random-per-boot.
## DB Schema (SQLite, WAL mode)
58 tables total (56 migrations as of 2026-08-25). Key tables:
| Table | Purpose |
|-------|---------|
| `prices` | OHLCV 5Y daily bars per ticker |
| `portfolio` | Holdings (account, ticker, qty, avg_price) |
| `macro` | FRED indicators + Fear&Greed |
| `signals` | TA-Lib technical indicators |
| `fundamentals` | PE, ROE, margins, growth, beta |
| `superinvestors` | 13F holdings (Buffett, etc.) |
| `estimates` | Analyst consensus + target prices |
| `recommendations` | Daily recs + 30/60/90d outcome tracking (E-3, user-facing emit) |
| `decisions` | #178 Decision Intelligence — rich record (regime/macro/event/agent_verdicts/scoring_detail/dissent/pnl_7/30/60/90d) |
| `agent_decisions` | #33 + #529 Phase 2 actor #8 — production state machine (decision_id, action, conviction, inputs_json with run_id, status pending/emitted/blocked/superseded) |
| `decision_evidence` | #178 lineage — per-decision evidence rows for audit reproducibility |
| `decision_outcomes` | #529 Phase 2 actor #11 — Forward-Outcome-Tracker closed-loop (realized return, alpha, hit threshold at 7/14/30d) |
| `positions` | Long/Short strategy positions |
| `swing_trades` | Market-wide swing trade positions |
| `strategy_memory` | Signal performance snapshots (append-only) |
| `analyst_ratings` | Upgrade/downgrade history |
| `earnings_surprises` | EPS actual vs estimate |
| `insider_trades` | Insider buy/sell transactions |
| `schema_version` | Migration version tracking |
| `pipeline_events` | Append-only event journal |
| `trades` | Trade execution records |
Additional: `ark`, `events`, `news`, `institutional_flows`, `etf_flows`, `regime_transitions`, `factors`, `backtests`, `audit_log`, `external_analysis`, `macro_events`, `external_llm_calls`, `agent_audit_ledger`, `agent_messages`, `agent_run_ledger`, `causal_audits`, `certifications`, `collector_runs`, `dr_replicas`, `drift_alerts`, `execution_blocks`, `feature_flags`, `foundation_benchmarks`, `hypotheses`, `incidents`, `regime_posteriors`, `walkforward_runs`.
### Three decision-related tables — intentional, not duplicate
The `recommendations` / `decisions` / `agent_decisions` triplet looks redundant at first glance. It is not — each serves a distinct purpose:
| Table | Era | Role | Cardinality | Lifecycle |
|---|---|---|---|---|
| `recommendations` | E-3 (legacy, pre-#178) | User-facing emit + 30/60/90d outcome backfill. Source of truth for "what we told the user." | 1 row per (date, ticker) emit | `outcome_30d/60d/90d` filled by `tracker.py` |
| `decisions` | #178 Decision Intelligence (2026) | Analytical record with rich features (regime, macro_score, event_score, scoring_detail, dissent, agent_verdicts) for backtest/learning. | 1 row per (date, ticker) decision computation | `outcome` enum + `pnl_7/30/60/90d` |
| `agent_decisions` | #33 + #529 Phase 2 actor #8 | Production state machine with run_id traceability (`inputs_json` references regime_run / hypothesis / causal_audit IDs). Status lifecycle prevents race conditions and tracks block reasons. | N rows per (ticker, date) — one per state transition or revision | `status ∈ {pending, emitted, blocked, superseded}` with `decision_outcomes` closing the loop |
**Why all three coexist**:
- `recommendations` is the user-contract surface — never break this format.
- `decisions` is the research-grade dataset; columns map 1:1 to features the Learning Memory layer studies.
- `agent_decisions` is the auditable production record; `decision_id` joins to `decision_outcomes` for the #529 closed-loop validation.
Cross-validation between `decisions` and `agent_decisions` is intentional. Removing either would lose research expressiveness or production audit-ability.
## DB Migrations
Add incremental schema changes to `_MIGRATIONS` in `nuri/core/db_migrations.py` (extracted from `db.py` in PR #553 P2 Stage 1):
```python
_MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "add column foo to prices", "ALTER TABLE prices ADD COLUMN foo TEXT;"),
]
```
`init_db()` auto-applies unapplied migrations and tracks in `schema_version` table.
## Config Files (`config/`)
- `portfolio.yaml` — accounts + holdings (gitignored; shape ref: `portfolio.example.yaml`)
- `stock_types.yaml` — Growth/value override per ticker. Controls stop-loss/take-profit thresholds.
- `agents.yaml` — Agent thresholds + confidence normalization scales (incl. `smart_money.freshness` per-source max-age, #1187). Loaded via `nuri/core/agent_config.py`.
- `alerts.yaml` — Alert thresholds, report timing
- `freshness.yaml` — Data freshness SLA thresholds (`warn_hours`/`fail_hours` per source) + `verdict_gate` input list. Loaded via `nuri/core/freshness.py` `_load_config()`.
- `rules.yaml` — Investment rules. Loaded via `nuri/core/rules.py`.
- `signals.yaml` — Signal metadata (thresholds, categories, hold_days)
## Scripts (`scripts/`)
Category sub-directories since #557 — full per-script index: `scripts/README.md`.
- `dev/setup.sh` — `.venv` via `uv`, installs deps
- `db/migrate.py` — DB schema creation + migration runner (`db/backup.sh` — 30-day rolling DB backup)
- `ops/import_portfolio.py` — Syncs `config/portfolio.yaml` → DB
- `verify/verify.py` — Master verification orchestrator → `data/reports/YYYY-MM-DD/`
- `verify/gate_check.py` — Pipeline gate verifier (exits 1 if BLOCKED)
- `verify/check_privacy_leak.py` — Privacy scanner (broker names, monetary literals)
- `verify/pre_push_check.sh` — Pre-push gate (drift + lint + tests + privacy + commits)
- `deploy/deploy_remote.sh` — rsync dev → Mac Mini production
- `deploy/sync_dev.sh` — dev↔dev state sync (gitignored files + ~/.claude Tier 3)
- `deploy/autopull_receiver.sh` — Mac mini receiver (launchd 5min auto-pull)
- `launchd/` — 9 plists (incl. `com.nuri-quant.api` / `com.nuri-quant.dashboard` KeepAlive #838) + install/uninstall scripts
## Data Directory
data/
├── portfolio.db      # Main SQLite DB (WAL mode)
├── reports/          # Pipeline outputs: data/reports/YYYY-MM-DD/
│   └── YYYY-MM-DD/   # signal_results.csv, signal_scorecard.csv, portfolio_action_plan.md, evidence/
├── backups/          # 30-day rolling DB backups
└── exports/          # Ad-hoc exports
## Testing
7,567 backend tests across 349 files + 1622 frontend vitest (134 files) + 89 Playwright E2E (10 spec files). Uses `pytest-xdist` (`-n auto --dist worksteal`). Coverage: Codecov 1% relative regression gate. **Backend statement coverage: 99% (2026-08-14, `make ci-cov` on the `#1052` main run)** — 17 of 23,311 statements uncovered across 9 files, 81 partial branches. Full closure (0 uncovered of 22,560) held on 2026-05-06 and again on 2026-07-29 (#926) and has regressed since both times; treat 100% as a state to re-reach, not a standing property. `make ci-cov` (CI artifact combine of all 6 shards, 4 fast + 2 slow) is the ground truth — a local run measures a different statement set.
**Slow marker**: 27 LLM/heavy tests marked `@pytest.mark.slow`. PR CI uses `-m "not slow"`. Use `make test-fast` locally (81.2s, `-n auto --dist worksteal`, M5 Max 2026-08-14).
@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path
Pass `db_path` to all DB functions. `conftest.py` (autouse) mocks `yfinance.download` → empty DataFrame and `yfinance.Ticker` → stub. All tests network-free.
### Verifying Numeric Claims
```bash
# Tests
.venv/bin/python -m pytest tests/ --collect-only -q | tail -1   # backend
find tests -name "test_*.py" -type f | wc -l                     # backend files
cd frontend && npx vitest run | tail -5                          # frontend
cd frontend && npx playwright test --list | tail -1              # Playwright E2E (loop-generated tests included)
# Architecture
ls nuri/collectors/*.py | grep -vE 'base|__init__' | wc -l       # collectors
ls nuri/trading/agents/*.py | grep -vE 'base|__init__|consensus|config' | wc -l  # agents
.venv/bin/python -c "from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS; print(len(SIGNAL_DEFINITIONS))"
.venv/bin/python -c "from nuri.trading.strategy.longshort import REGIME_ALLOCATION; print(len(REGIME_ALLOCATION))"
grep -rhE "@router\.(get|post|put|delete|patch)" nuri/api/routes/ | wc -l
make verify-doc-counts   # DB tables — live init_db count (DDL lives in nuri/core/db_migrations.py)
find frontend/src/app -name "page.tsx" | wc -l
If counts disagree with docs, **fix the doc** — precise numbers are load-bearing for trust.
## CI/CD Pipeline (`main-ci-cd.yml`)
On push/PR to `main`:
1. **Lint** — `ruff check nuri/ tests/ scripts/`
2. **Test** — pytest with xdist parallel (6 shards: 4 fast + 2 slow push-only). TA-Lib cached. Deps via `uv sync --frozen`.
3. **Frontend** — `tsc --noEmit` + vitest with coverage
4. **Privacy** — `check_privacy_leak.py` on all files
5. **Security** — Trivy CRITICAL vulnerability scan
PR-specific (`pr-discipline.yml`): merge conflict detection, conventional commit validation, 5MB file limit, auto PR summary.
## Investment Rules
All investment rules (stop-loss, take-profit, account strategy profiles, VIX gate, execution priority, buy checklist) live in `config/rules.yaml` and are documented canonically in [`docs/STRATEGY.md` §3.4 / §3.5](STRATEGY.md). Source code executes the YAML via `nuri/core/rules.py` (§2.2 mechanical execution — no hardcoded thresholds).
## OpenBB Provider Limitations
| Endpoint | yfinance | Notes |
|----------|----------|-------|
| `obb.equity.price.historical` | OK | Primary price data source |
| `obb.equity.fundamental.metrics` | OK | PE, PB, ROE, margins, growth, beta |
| `obb.equity.estimates.consensus` | OK | Target price, recommendation, analyst count |
| `obb.equity.fundamental.ratios` | No | Requires `fmp` or `intrinio` (paid) |
| `obb.equity.estimates.price_target` | No | Requires `benzinga` or `fmp` (paid) |
| `obb.equity.ownership.*` | No | Requires `fmp` (paid) |
## Currency Handling
Multi-account portfolio mixes USD and KRW. Exchange rate fallback: DB `macro` table → OpenBB API → `StaleExchangeRateError` (no hardcoded fallback). Warns if rate > 7 days old. `.KS` tickers always KRW.
## Portfolio Action Plan Format
Save to `data/reports/YYYY-MM-DD/portfolio_action_plan.md`. Required sections: market environment table (regime, VIX, F&G, macro), per-stock verdict with external data cross-reference, execution timeline, re-entry conditions, buy priority by multi-factor score.
Every recommendation **must** include explicit price levels: entry, stop-loss, target_1, target_2, trailing stop, TipRanks target.
## MCP Integration
`.mcp.json` configures MCP SQLite server for direct DB queries:
```json
{"mcpServers": {"nuri-db": {"command": "uvx", "args": ["mcp-server-sqlite", "--db-path", "./data/portfolio.db"]}}}

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@docs/STRATEGY.md

## Harness Principles

```
1. 모르면 읽는다         — 가정하지 않는다
2. 2번 실패하면 접근을 바꾼다  — 같은 시도 3회 금지
3. 수정 후 실행한다       — 논리적 확신을 신뢰하지 않는다
4. 스코프를 지킨다       — 요청된 것만 한다
5. 숫자를 grep한다       — 한 곳만 고치지 않는다
6. 시스템이 차단한다      — 문서가 아닌 린터/CI/게이트가 강제한다
```

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
make collect                            # Phase A daily collectors (stock/stock_kr/macro/technical/fear_greed/ark/cboe/coingecko/finviz/reddit/fred_calendar/macro_news)
make collect-kis                        # KIS Open API 실시간 잔고/시세
make collect-kis-check                  # KIS 연결 상태 확인
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
make backtest         # VectorBT backtest engine (single run)
make backtest-ls      # full backtest + Monte Carlo
make backtest-stress  # stress test scenarios
make backtest-rules   # rules-based backtest
make optimize         # grid search parameter tuning
make mean-reversion   # mean-reversion scan + backtest
make pairs            # pairs trading scan + backtest

# Swing Trade / Market Scan
make scan             # us_core 스캔 (~85종목, 일일, ~5초)
make scan-extended    # us_core + S&P 500 (~339종목, 주간 풀스캔)
make scan-kr          # KOSPI 200 (~80종목)
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
make report            # Daily report (Discord/stdout)
make report-llm       # Qwen3.5 LLM 리포트 생성 + 자동 저장

# Lint + Test
make lint             # ruff check
make lint-fix         # ruff check --fix
make test             # pytest tests/ -v --cov=nuri (full suite, ~50s local)
make test-fast        # -m "not slow" — slow LLM tests 제외 (~24s, PR CI 기본)
make test-slow        # slow tests only
make verify-quick     # fast pre-commit check: tests + regime (~10s, no network)
make verify-fast      # ~2min pre-deploy (verify.py without backtest)
make verify-all       # full verification with network (커밋 전 필수)
make validate-portfolio  # Verify each ticker in portfolio.yaml has live data
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

# Decision tracking
make track-decisions  # Decision outcome tracking + snapshot

# Utilities
make ports            # show port usage
make ports-kill       # kill conflicting port processes
make update-counts    # Update test/architecture counts in docs
make demo             # Demo mode setup (scripts/demo.sh)
make clean            # Remove build artifacts
make clean-all        # + __pycache__ + token cache
make clean-deep       # + node_modules + uv cache (interactive, requires reinstall)
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
├── api/               # FastAPI REST API (65 endpoints, routes/)
├── alerts/            # Discord daily report + bot, Telegram alerts
└── llm/               # LLM report (Ollama) + OpenAI wrapper + event classifier
```

### Key Design Patterns

- **DB sole integration point**: `nuri/core/db.py` is the ONLY `sqlite3` importer (hook-enforced). See `nuri/core/CLAUDE.md`.
- **Loose coupling via data**: Pipeline phases communicate through DB/CSV, never direct imports. See `docs/ARCHITECTURE.md`.
- **Collector template**: All inherit `BaseCollector` (collect→save→run). See `nuri/collectors/CLAUDE.md`.
- **10-agent consensus**: Weighted voting, risk agent veto. See `nuri/trading/agents/CLAUDE.md`.
- **SIEGE 11-gate**: All recommendations must pass 11 conditions. See `nuri/trading/engine/CLAUDE.md`.
- **20 signals, YAML registry**: `config/signals.yaml` drives `signal_backtest.py`. See `docs/ARCHITECTURE.md`.
- **Regime classifier**: 6 base + 4 special regimes. See `docs/ARCHITECTURE.md`.

## Code Conventions

- Python 3.12 with type hints
- Korean comments (한국어 주석), English variable/function names
- Git commit messages in English
- Configuration in YAML (`config/`), secrets in `.env` (git-ignored)
- Korean stock tickers use `.KS` suffix (e.g., `005930.KS` for 삼성전자)
- **Timezone: always use `kst_now()` or `today_kst()` from `nuri.core.timezone`** — never `datetime.now()`

## API Access Pattern

- **Server Components**: Use `fetchAPI("/api/...")` from `@/lib/api` (absolute URL, server-to-server)
- **Client Components**: Use `fetch("/api/...")` (relative URL, proxied by Next.js `rewrites` in `next.config.ts`)
- **Never** use `${API_BASE}/api/...` in Client Components — breaks on network access (CORS/CSP)
- Backend: FastAPI on `:8001`, Frontend: Next.js on `:3000`. Next.js proxies `/api/*` to backend.

## Gotchas

- **Next.js 16 breaking changes**: APIs differ from LLM training data — always read `node_modules/next/dist/docs/` first. See `frontend/CLAUDE.md`.
- **vi.mock() hoisting** (frontend): `vi.mock("recharts")` affects ALL dynamic imports in the same vitest worker. Keep recharts-dependent and recharts-free tests in separate files. Use `vi.doMock` for per-test control.
- **runpy + mock**: `runpy.run_module()` re-executes module source, invalidating mocks. Use `patch("source.module.function")` for source-level patching.
- **OpenBB local import**: `obb` is imported inside functions (not at module level). `patch("module.obb")` fails — use `patch.dict(sys.modules, {"openbb": mock_module})`.
- **yfinance .KS fundamentals work**: Contrary to some code comments, `yfinance.Ticker("005930.KS").info` returns PE, ROE, margins, growth, debt for Korean individual stocks. ETFs return empty (expected). KIS API is NOT needed for fundamentals.
- **pykrx API instability**: `get_market_fundamental`, `get_index_ohlcv`, `get_market_trading_value_by_date` — all broken (column name changes). KOSPI/KOSDAQ index collection uses yfinance `^KS11`/`^KQ11` fallback. Institutional flows currently unavailable.
- **Macro event pipeline** (PR #249-#253): 15 categories (was 12), stale articles >7d filtered, confidence <0.3 excluded from event_score, recency weighting (today=1.0→3d=0.5), regime_hint requires 3+ events. Korean Market Agent reads `macro_events` table for `export_surge`/`demand_growth`.

## Harness File Map

This project uses layered context files. Root files load every session; directory-scoped files load when working in that directory.

| File | Role | Auto-loaded |
|------|------|-------------|
| `CLAUDE.md` (this file) | Commands, architecture overview, conventions | Always |
| `AGENTS.md` | Cross-tool rules (Cursor/Copilot/Codex) | Not by Claude Code (for other agents) |
| `docs/STRATEGY.md` | Design principles, investment rules, harness theory | Always (@import) |
| `docs/ARCHITECTURE.md` | Detailed architecture, DB schema, env vars, CI/CD, testing | On demand |
| `nuri/core/CLAUDE.md` | db.py rules, timezone, events, freshness | When editing nuri/core/ |
| `nuri/collectors/CLAUDE.md` | BaseCollector contract, OpenBB quirks | When editing nuri/collectors/ |
| `nuri/trading/agents/CLAUDE.md` | Agent system, consensus, veto rules | When editing nuri/trading/agents/ |
| `nuri/trading/engine/CLAUDE.md` | SIEGE gates, confidence formula, v2 spec | When editing nuri/trading/engine/ |
| `docs/SIEGE_V2.md` | 3D certification architecture (Account × Asset Class × Market) | When editing nuri/trading/engine/ |
| `frontend/CLAUDE.md` | Next.js 16, design system, testing gotchas | When editing frontend/ |
| `tests/CLAUDE.md` | Fixtures, mocks, testing gotchas | When editing tests/ |
| `config/CLAUDE.md` | YAML structure, change procedures | When editing config/ |

### Mechanical Enforcement (Hooks + CI)

| What | How | When |
|------|-----|------|
| `import sqlite3` outside db.py | PreToolUse hook (exit 2 block) | Before every Edit/Write |
| `datetime.now()` usage | PostToolUse hook | After every Edit/Write |
| `git push --force`, `git reset --hard`, `git clean -f` | PreToolUse hook (exit 2 block) | Before every Bash |
| Ruff lint violations | PostToolUse hook | After every Edit/Write |
| Privacy leaks (broker names, monetary literals) | CI `privacy-scan` job + `pre_push_check.sh` | Every push + PR |
| Test regression | CI + Codecov 1% gate | Every PR |
| Trivy CRITICAL vulnerabilities | CI `security-scan` job | Every push |

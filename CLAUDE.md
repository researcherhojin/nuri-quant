# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@docs/STRATEGY.md

## Harness Principles

See `docs/STRATEGY.md` §5.8 — seven principles (모르면 읽는다 / 2번 실패하면 접근을 바꾼다 / 사용자 워크플로로 검증한다 / 스코프를 지킨다 / 숫자를 grep한다 / 시스템이 차단한다 / 외부 API는 측정한다). STRATEGY.md is the canonical source; do not duplicate the list here.

## Flow (Think → Plan → Build → Review → Test → Ship → Reflect)

See `docs/STRATEGY.md §2.7`. Every task goes through all 7 phases — don't skip. Each phase has explicit input/action/artifact/gate. Failed gate → regress to prior phase. Trivial chores may inline Think+Plan; everything from Build onward is mandatory. Codex unavailable → self-review + recover in next PR.

**Work status & changelog**: `docs/TODO.md` manages Tier 1 (완료) / Tier 2 (next) / Tier 3 (research) backlog. Permanent policies (자동 매매 deferred, PR discipline) stay in `docs/STRATEGY.md §7`. Historical commits live in `git log` — do not re-document.

**Session start**: read `NEXT_SESSION.md` first (gitignored) — carries the previous session's 10-min checklist and the next work item. Supersedes any stale "next task" recollection in user memory.

## Project

Nuri-Quant (누리퀀트) — Open-source quant investment platform.
Python 3.12, `uv` package manager (`uv.lock` for reproducibility), SQLite, 100% free open-source stack.
Dependencies split: core in `[project.dependencies]`, pytest/ruff in `[project.optional-dependencies].dev`.
Linter: `ruff` (E/F/W/I rules, line-length 120). CI: GitHub Actions (lint + test + frontend type-check).
Ruff ignores: E402 (lazy imports in scheduler), E501 (existing long lines), E712 (pandas `== True` idiom).
Conventional commits required in PRs: `(feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)(scope)?: message`.

5-step canonical pipeline (README §Architecture): **Collect → Analyze → Consensus → Certify → Track**
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

# Universe (#272)
make universe-sync                      # Dry-run US+KR universe sync (Wikipedia S&P 500 + KRX KOSPI 200)
make universe-sync-us                   # US-only dry-run
make universe-sync-kr                   # KR-only dry-run (requires: uv pip install finance-datareader)
make universe-sync-apply                # Apply universe.yaml updates (additions only — manual ETFs preserved)
make collect-universe                   # Collect ALL universe data (prices/fundamentals/wallstreet/estimates for US+KR)
make verify-universe-sync               # Smoke test — catches real universe API breakage

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
make scan             # us_core 스캔 (85종목, 일일, ~5초)
make scan-extended    # us_core + S&P 500 (543종목, 주간 풀스캔)
make scan-kr          # KOSPI 200 (203종목)
make swing            # 스캔 + 에이전트 합의 → 진입 저장
make swing-check      # 진행중 스윙 트레이드 상태 확인

# Full Pipeline
make full-scan        # 8-phase: collect→analyze→validate→regime→recommend→certify→evidence→notify
make quick-scan       # 빠른 4-step: collect→analyze→consensus→targets (~2분)

# SIEGE Certification
make certify          # SIEGE v2 규칙 검증 (asset-class per-expansion, conditions 가변) → CERTIFIED / REJECTED
make remediate        # REJECTED → 진단 + 매도 처방 + post-remediation 예측
make gate             # Pipeline gate verifier (exits 1 if BLOCKED)

# Price Targets & Rebalance & Evidence
make targets          # 전 종목 매수가/손절가/익절가 계산
make rebalance        # 규칙 위반 감지 + 매도 수량 제시
make evidence         # 5개 Plotly 증거 차트 생성 (data/reports/{date}/evidence/)
make external         # 외부 데이터 요약 (TipRanks, Dataroma, ARK 등)
make report            # Daily report (Discord/stdout)
make report-llm       # LLM 리포트 (OpenAI gpt-5.4-nano primary, §4.4.3 Tier 2 — OPENAI_ZDR_APPROVED=1 필수)

# Lint + Test
make lint             # ruff check
make lint-fix         # ruff check --fix
make lint-sh          # shellcheck scripts/*.sh (brew install shellcheck 필요)
make test             # pytest tests/ -v --cov=nuri (full suite, ~50s local)
make test-fast        # -m "not slow" — slow LLM tests 제외 (~24s, PR CI 기본)
make test-slow        # slow tests only
make verify-quick     # fast pre-commit check: tests + regime (~10s, no network)
make verify-fast      # ~2min pre-deploy (verify.py without backtest)
make verify-all       # ~30s pre-push (tests + backend + frontend + file integrity, no network)
make validate-portfolio  # Verify each ticker in portfolio.yaml has live data
# Single test — no make target; invoke pytest directly via .venv/bin/python:
.venv/bin/python -m pytest tests/test_db.py -v                                    # single file
.venv/bin/python -m pytest tests/test_db.py::TestUpsertPrices -v                  # single class
.venv/bin/python -m pytest tests/test_db.py::TestUpsertPrices::test_insert_and_query -v  # single test

# Interface
make start            # API(:8001) + Dashboard(:3000) simultaneous
make api              # FastAPI only (:8001)
make dashboard        # Next.js only (:3000)
# Frontend-only commands (npm run dev/build/test/lint/type-check): see frontend/CLAUDE.md

# Verification
make verify           # Master verification orchestrator → data/reports/YYYY-MM-DD/

# Deploy — 2-Machine Setup (MBP dev ↔ Mac mini 24/7 receiver)
# 일반 워크플로: PR merge 후 `make deploy-mini` 1 커맨드로 Mac mini 동기화 (~30초)
# scripts/deploy_mini.sh 가 6 단계 자동 수행:
#   1. SSH 연결 확인 (fail-fast)
#   2. 원격 git pull --ff-only
#   3. config 동기화: .env + portfolio.yaml + NEXT_SESSION.md (DB 제외 — Mac mini DB 가 production)
#   4. uv sync (lock/pyproject 변경 시에만)
#   5. scheduler reload (nuri/scheduler.py · config/agents.yaml · config/rules.yaml 변경 시에만, 최초 plist 미설치 시 자동 설치)
#   6. 검증: git HEAD 일치 + scheduler PID + autopull 상태
make deploy-mini      # ★ 권장 — MBP → Mac mini 전체 동기화 (위 6단계)
make deploy           # rsync to Mac Mini (레거시, pre-deploy check 포함)
make pre-deploy       # Safety checks before deploy
make backup           # DB backup (30-day rolling)
make sync-start       # Dev↔dev 작업 시작 — 다른 머신 → 이 머신 (pull) + NEXT_SESSION.md
make sync-end         # Dev↔dev 작업 종료 — 이 머신 → 다른 머신 (push, DB 포함 — 확인 prompt)
make sync-status      # 양쪽 git HEAD + NEXT_SESSION timestamp 비교 (read-only)
make scheduler-reload-remote  # Mac mini scheduler 만 reload (scheduler.py 변경 후 단독 사용, DEV2_HOST 필요)
scripts/sync_dev.sh push      # 저수준 — make sync-end 가 wrap. NEXT_SESSION.md 미포함 (별도 scp)
scripts/sync_dev.sh pull      # 저수준 — make sync-start 가 wrap (--with-reports / --no-claude)
bash scripts/auto_deploy.sh   # Mac mini receiver: fetch + ff-only merge + 변경 분석 (launchd com.nuri-quant.autopull 5분 간격)

# Decision tracking
make track-decisions  # Decision outcome tracking + snapshot

# Utilities
make ports            # show port usage
make ports-kill       # kill conflicting port processes
make sync-doc-counts    # Sync numeric claims in docs (collectors/endpoints/tests/e2e) with live code
make verify-doc-counts  # Read-only drift check (exit 1 on drift — wired into PR CI)
make update-counts      # Back-compat alias → sync-doc-counts (legacy, kept for muscle memory)
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
├── collectors/        # 25 collector modules (BaseCollector subclasses + standalone, incl. KIS Open API)
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
├── api/               # FastAPI REST API (69 endpoints, routes/ incl. actions/opportunities/market-context/coverage)
├── alerts/            # Discord daily report + bot, Telegram alerts
└── llm/               # LLM report (OpenAI gpt-5.4-nano primary, §4.4.3 Tier 2; Ollama fallback) + openai_client gateway + event classifier
```

### Key Design Patterns

- **DB sole integration point**: `nuri/core/db.py` is the ONLY `sqlite3` importer (hook-enforced). See `nuri/core/CLAUDE.md`.
- **Loose coupling via data**: Pipeline phases communicate through DB/CSV, never direct imports. See `docs/ARCHITECTURE.md`.
- **Collector template**: All inherit `BaseCollector` (collect→save→run). See `nuri/collectors/CLAUDE.md`.
- **10-agent consensus**: Weighted voting, risk agent veto. See `nuri/trading/agents/CLAUDE.md`.
- **SIEGE v2 certification**: 3D gate (Account × Asset Class × Execution Market). `conditions` count is variable — per-asset-class expansion flattens at `certify()`. 1 error-grade fail → REJECTED. See `nuri/trading/engine/CLAUDE.md` + `docs/SIEGE_V2.md`.
- **Regime-adaptive position cap** (E3-3c, PR #404): `_check_position_limits` applies `siege_gates.regime_overrides[regime].per_position_max_multiplier` per-ticker. Aggressive 1.20× (`bull_low_vol`, `recovery`) / conservative 0.80× (`bear_high_vol`, `bull_high_vol`, `stagflation`, `euphoria`) / neutral 1.0×. Stage 2 paired counterfactual (PR #402) PASS verdict justifies. Hard veto (VIX>30) preserved orthogonally in `volatility_gate`. Sector cap regime override deferred (E3-4 portfolio simulator). Helpers: `_current_regime()`, `_get_position_multiplier(regime)`, `_apply_position_multiplier(base, regime)` — all 1.0 fallback on None/missing-config.
- **SIEGE certification instrumentation** (E4-0a, PR #410): `certifications` table (migration 21) persists every `certify()` run with `(timestamp, certified, score, total_conditions, passed/failed/warnings, regime, portfolio_hash, conditions_json, caller)`. Previously return-only — no historical record for audit. `certify()` signature: `persist=True` (default) + `caller` Literal CallerTag + `swallow_persist_errors` (API opt-in; engine default loud). **Snapshot invariant**: `CertSnapshot` dataclass + `ContextVar[_CERT_SNAPSHOT]` threads `(regime, portfolio_df, portfolio_raw, portfolio_hash, portfolio_error)` through all gate internals without changing 13 gate signatures. Single-source-of-truth: `_compute_portfolio_hash(rows=snapshot.portfolio_raw)` derives from the same raw read that `_check_leverage_ban` + `_group_holdings_by_asset_class` consume. `analyze_portfolio()` failure is stored in `portfolio_error` and re-raised by `_snapshot_portfolio()` → each gate's `try/except` preserves original semantic (position_limit error-fail, sector/stop_loss warning-skip). Hash includes `sector` for asset-class reclassification fingerprint. E4-0b (historical backfill) + E4-0c (predictivity audit) consume these rows.
- **Alpha/portfolio action separation** (PR A #429, 2026-04-21): `recommendations` table has orthogonal `alpha_action` ∈ {LONG, SHORT, FLAT, NULL} and `portfolio_action` ∈ {REBALANCE, TRIM, HEDGE, NONE, NULL}. Migration 22 (forward-only NULL, legacy rows safe). SIEGE `position_limit` / `sector_limit` / `leverage_ban` violations emit only `portfolio_action=REBALANCE` (score unchanged, no alpha signal). Only `stop_loss` breach emits `alpha_action=FLAT` (score −3). Consensus risk-agent veto fires on `risk_v.alpha_action=="FLAT"` (legacy `action=="SELL"` fallback for non-PR-A agents). `/api/actions` 4th `portfolio` bucket — concentration only → "리밸런스 권고" copy, never urgent. See `nuri/core/axis.py` (PR B #434 reader helpers: `is_alpha_flat_sell` / `is_alpha_long_buy` / `derive_alpha_action`). Root cause of 2026-04-20 user -₩7M loss (BAC/TSLA SIEGE REJECT → "매도" surface → next-day rally).
- **SHADOW crash precursor signals** (PR C #436, 2026-04-22): `config/signals.yaml` 2 signals `yield_curve_inversion` (Estrella-Mishkin 1998) + `hy_oas_widening` (Gilchrist-Zakrajsek 2012) with `type: SELL` + `actionable: false` + `scope: market_wide`. `nuri/core/signal_config.py::is_actionable()` + `list_shadow_signals()` helpers. `nuri/quant/validation/market_signals.py` 에서 detector (per-ticker `signal_backtest.py` 와 분리). `candidates.py` 의 SIGNAL_DEFINITIONS loop 가 `is_actionable` guard 로 SHADOW 항상 skip — candidates 에 절대 섞이지 않음 (codex Plan consult Biggest Risk). `premarket_brief.py` 🌑 섹션에서만 surface. Graceful degrade when FRED 데이터 공백.
- **ATR grid validation** (PR F #437, 2026-04-22): `nuri/quant/exits/atr.py` — `K_GRID = (1.5, 2.0, 2.5, 3.0)`, `REGIME_MULTIPLIER` (E3-3c parity: bull_low_vol 0.8 / neutral 1.0 / bear_high_vol 1.3), `AtrStopResult.basis="entry_atr_fixed"` frozen anchor contract. `entry_price` explicit required (no default) — anchor mismatch 재발 차단 (codex Biggest Risk). `scripts/pr_f_atr_validation.py` paired counterfactual (E3-3b #402 재활용) — MARGINAL verdict (top 2 combos CI positive but 6-metric 3/6, walk-forward best-k shift). Shadow surface deferred to PR F2 (안전하게 ship 할 evidence 부족). STRATEGY §3.4 `-7%` 근거를 "O'Neil inheritance" → "inheritance + repo 5Y 자체 검증 통과" 로 dual justification.
- **SIEGE snapshot-native predictivity audit** (E4-0b v2 #439, 2026-04-22): `scripts/siege_predictivity_audit.py` v2 — variant ladder 4 templates × N months (momentum_top10 / equal_weight_sample / sector_concentrated / concentrated_top5). Gate eligibility matrix (codex Biggest Risk): `auditable_now` {position_limit, sector_limit, leverage_ban} (측정 대상) / `audit_incoherent` {freshness/external/volatility/drift/conflict_free} (current DB 의존) / `requires_replayed_state` {stop_loss, rules_loaded, macro_event_alignment} (historical state / replayable-but-unwired). `_deterministic_seed(date, variant)` hashlib.sha256 — Python hash() PYTHONHASHSEED 의존 회피 (codex Round 1). Acceptance: `CI_upper < 0` (NOT `CI_lower`, codex Q5 math correction) — Δ = fired−not_fired 이므로 downside predictivity 는 CI 전체가 0 아래. Pilot 144 snapshots: `position_limit` directional counter-evidence (provisional, CI 0 가로지름). See STRATEGY §3.8.
- **20 signals + 2 SHADOW, YAML registry**: `config/signals.yaml` drives `signal_backtest.py` (20 actionable) + `market_signals.py` (2 SHADOW, scope `market_wide`). See `docs/ARCHITECTURE.md`.
- **Regime classifier**: 6 base + 4 special regimes. See `docs/ARCHITECTURE.md`.
- **External LLM gateway**: `nuri/llm/openai_client.py` is the ONLY external LLM entry point. Direct `import openai` forbidden. `chat_json` (Tier 0 JSON) / `chat_text` (Tier 2 narrative, ZDR-gated). Every call audit-logged to `external_llm_calls` (content never stored). Policy: `docs/STRATEGY.md §4.4.3`.

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

> **Gotcha-Test Pair 원칙** (STRATEGY §5.3.1, PR #307): fix-pattern gotcha 는 반드시 `**Test:**` 로 회귀 테스트를 cite 한다. Test 가 명시되지 않은 gotcha 는 "folklore" — 수 세션 후 defensive code 가 제거돼도 아무도 못 막음 (df.copy() 재발 사례). 단순 facts/quirks 는 Test: 불필요.

Grouped into 4 categories (NEXT_SESSION M3):

### Framework & dependencies

- **Next.js 16 breaking changes**: APIs differ from LLM training data — always read `node_modules/next/dist/docs/` first. See `frontend/CLAUDE.md`. *(facts, no fix)*
- **fastapi < 0.129 pinned** (PR #291, #277): `openbb-core 1.6.7`이 `fastapi<0.129`를 요구하므로 pin됨. Dependabot 0.129+ 제안은 자동 무시 (`dependabot.yml`). openbb 제약 풀릴 때까지 유지.

### Test mocking pitfalls

- **vi.mock() hoisting** (frontend): `vi.mock("recharts")` affects ALL dynamic imports in the same vitest worker. Keep recharts-dependent and recharts-free tests in separate files. Use `vi.doMock` for per-test control.
- **runpy + mock**: `runpy.run_module()` re-executes module source, invalidating mocks. Use `patch("source.module.function")` for source-level patching. **Test:** existing `tests/` runpy cases (source-level patch required to pass).
- **OpenBB local import**: `obb` is imported inside functions (not at module level). `patch("module.obb")` fails — use `patch.dict(sys.modules, {"openbb": mock_module})`. **Test:** `tests/collectors/test_stock.py::TestStockCollectorTickerCollection::test_collect_ticker_success` (uses patch.dict pattern).
- **`pd.DataFrame` in-place mutation + 공유 mock 참조** (PR #294/#295/#306/#307): `_standardize(df, ticker)` 같은 헬퍼가 `df.columns = ...` / `df["new"] = ...` 로 in-place mutation하고 테스트에서 `mock.return_value = df_fixture` (동일 객체)가 병렬 스레드에 공유되면 race → `pandas.errors.InvalidIndexError`. **방어**: 함수 진입 즉시 `df = df.copy()`. **주의**: PR #294/#295 가 commit message 에서 이 defense 를 claim 했지만 실제 `stock.py` 에 적용 안 됐음 → #306 CI 재발 → #307 에서 실제 fix + regression test lock-in (STRATEGY §5.3 phantom fix 사례). **Test:** `tests/collectors/test_stock.py::TestStandardizeThreadSafety::test_standardize_does_not_mutate_input` (mutation 감지) + `::test_concurrent_standardize_calls_do_not_race` (10-worker × 50 calls race simulation).

### Data source quirks

- **yfinance .KS fundamentals work**: Contrary to some code comments, `yfinance.Ticker("005930.KS").info` returns PE, ROE, margins, growth, debt for Korean individual stocks. ETFs return empty (expected). KIS API is NOT needed for fundamentals. **Exception**: `trailingPE` (stored as `pe_ratio`) is NOT provided for KR individual stocks — yfinance provider limit. Use `forward_pe` instead (182/201 KR coverage). *(facts, no fix)*
- **pykrx institutional flow endpoint broken** (#247 investigation 2026-04-15): `get_market_trading_value_by_date` / `get_market_net_purchases_of_equities` return HTTP 400 (silent empty df) — KRX policy change requiring auth. pykrx 1.2.6 added `KRX_ID/KRX_PW` env login but **violates KRX Data Marketplace ToS** (Art. 6② automated collection). **Replacement**: KIS Open API `investor-trade-by-stock-daily` (tr_id=`FHPTJ04160001`) via `nuri/collectors/institutional.py`. `get_market_ohlcv_by_date` still works unauthenticated — keep for `stock_kr.py`. **Test:** `tests/collectors/test_institutional.py::TestCollectKrKisSuccess` (mock 30-row KIS response parse) + `TestCollectKrKisNoCreds::test_returns_empty_and_surfaces_event` (Surface §2.6 rung).
- **KIS investor-trade TIME LIMIT** (#247): `investor-trade-by-stock-daily` rejects today's date before daily settlement (msg_cd=`OPSQ2001`, "TIME LIMIT 00:00 ~ 15:40"). Always query T-1; API returns 30-day history window ending at input date — T-1 covers yesterday back to T-30. Test with date 20260410 (known good) or anything ≥2 business days old.
- **외부 API 동시성 비대칭** (`docs/HARNESS.md §1.2-1.3`, PR #282/#283): yfinance는 10-thread parallel OK. **pykrx/KRX는 sequential + `time.sleep(0.1)` 필수** (rate-limit). `ThreadPoolExecutor.result(timeout=)` 은 future만 cancel — pykrx C-extension call은 계속 실행되어 메모리 leak + slowdown 누적. 새 외부 API 통합 시 동시성 측정 후 결정.
- **OpenBB upstream ImportError — 30+ 엔드포인트 영향** (#274/#349/#351, PR #347/#350/#352, 2026-04-16): `openbb-core 1.6.7` 의 PackageBuilder 가 `OBBject_*` 심볼을 `create_model()` 로 **동적 생성만** 하고 module-level export 누락 → `obb.<namespace>.<method>` attribute access 시점에 `ImportError: cannot import name 'OBBject_XXX'`. Live-verified 깨진 엔드포인트: `obb.news.company` (OBBject_CompanyNews), `obb.etf.info` (OBBject_EtfCountries), `obb.equity.price.historical` / `.fundamental.metrics` / `.fundamental.ratios` / `.estimates.consensus` (OBBject_EquityInfo), `obb.currency.price.historical` (OBBject_CurrencyPairs). Upstream fixes (OpenBB-finance/OpenBB #7381/#7446/#7460) 는 **closed-without-merge** — yfinance 직접 폴백이 장기 경로이며 upstream release 시 OpenBB primary 자연 복원 (stock.py 와 동일). **Test:** `tests/collectors/test_news.py::TestYfinanceFallback::*` + `tests/collectors/test_etf_flows.py::TestEtfFlowsYfinanceFallback::*`.

### Pipeline policies & defenses

> Each entry is a 1-line trigger + `**Test:**` regression cite (or `*facts/policy*`). Full rationale lives in STRATEGY §3.x or Key Design Patterns above; the trigger phrase remains here so readers see the "why this exists" cue and the lock-test together at execution time (§5.3.1 Gotcha-Test Pair).

- **Macro event pipeline** (PR #249-#253): 15 categories, stale articles >7d filtered, confidence <0.3 excluded from `event_score`, recency-weighted, `regime_hint` requires 3+ events. Korean Market Agent reads `macro_events` for `export_surge`/`demand_growth`. *(facts/policy)*
- **OpenAI Tier 2 ZDR gate** (PR #294): `make report-llm` 조용히 실패 → `OPENAI_ZDR_APPROVED=1` 미설정. `NURI_DISABLE_EXTERNAL_LLM=1` 로 전면 opt-out. STRATEGY §4.4.3.
- **Universe coverage 5-check gate** (PR #284/#286/#288/#296/#343/#345): `validate_universe.py` checks prices/fundamentals/analyst/insider/super (≥95/80/70/50/80%); CI `Universe Coverage Validation` is required + always-run (#345). `US_ONLY_TABLES` frozenset shows `n/a (US-only)` for KR — source limit, not failure. *(facts/policy)*
- **JKHY falling knife pattern** (PR #301-#303,#306,#307): TechnicalAgent SELL outweighed by 9 BUY agents → 4-layer defense (universe 1y backfill / `divergence_flag` / UI ⚠ / mechanical penalty: tech conf ≥80 opposite → HOLD). Detail: `docs/HARNESS.md §2`. **Test:** `tests/trading/agents/test_consensus.py::TestConsensusDivergence*` (5) + `::TestConsensusDivergenceMechanicalPenalty` (8) + `::TestPenaltyTelemetryEvent` (5).
- **Commit message privacy scanning** (PR #289): `pre_push_check.sh` Section 4b auto-scans `origin/main..HEAD`. Manual: `.venv/bin/python scripts/check_privacy_leak.py --unpushed-commits`. STRATEGY §4.4.1.
- **Branch protection conditional skip trap** (PR #343→#344→#345): `required_status_checks` 에 `if:` conditional job 등록 시 docs-only/gitignore-only PR 에서 skip → mergeable인데 BLOCKED. 방어: required 등록 전 (1) workflow `if:` 부재 확인, (2) 직전 docs PR Actions 에서 `pass`/`skipping` 검증. *(facts/policy, no Test)*
- **Factors modules must read DB, never external APIs** (#349, PR #350): `quant/factors/{quality,value,momentum,sentiment}.py` 는 `fundamentals`/`prices`/`macro` 만 query (STRATEGY §2.3 + §3.1). 과거 OpenBB 직접 호출 → silent except → 전 유니버스 score=0.5 상수. AST import guard 로 lock. **Test:** `tests/quant/test_factors_quality.py::TestQualityDbRead::test_quality_source_has_no_openbb_import` + `tests/quant/test_factors_value.py::TestValueDbRead::test_value_source_has_no_openbb_import` + `::test_*_score_non_constant_when_fundamentals_vary`.
- **SQLite upsert 반환값은 `cursor.rowcount`, NOT `len(records)`** (#351, PR #352): `INSERT OR IGNORE` (예: `upsert_news`) 에서 `len(records)` 반환 시 IGNORED rows 포함 → 로그/DB drift (§2.4 Observability). `INSERT OR REPLACE` 는 예외 (insert+replace 모두 counting). **Test:** `tests/core/test_db.py::TestUpsertNewsDedupCount::test_returns_actual_insert_count_on_url_dedup`.
- **Sell-path threshold per-account, `<` operator** (Phase 2 A-3, PR #374): `risk_agent.py`/`actions.py` 가 global `STOCK_STOP_LOSS` 사용 → long_term(-20)/pension(-30) 계좌 -7%에서 false urgent. Fix: `nuri/core/rules.py::get_stop_loss_for_account(account)` (holding row 와 같은 account 전달, aggregation mismatch 금지). **Test:** `tests/core/test_rules.py::TestGetStopLossForAccount` (7) + `tests/trading/agents/test_risk.py::TestRiskAgentA3PerAccountThreshold` (4) + `tests/api/test_actions.py::TestBuildActionsLogic` (4).
- **Non-emergency SELL → catalyst gate or advisory downgrade** (Phase 2 A-4, PR #377): signal/consensus SELL 이 catalyst (news 14d / macro 7d, conf≥0.5 |sent|≥0.3) 없으면 `TIER_ADVISORY` + `hold` bucket. Stop-loss breach 는 catalyst 호출조차 안 함 (§2.2 mechanical). STRATEGY §2.6 Soft penalty. **Test:** `tests/core/test_catalyst.py::TestHasRecentCatalyst` (9) + `tests/api/test_actions.py::TestBuildActionsLogic::test_a4_sell_no_breach_no_catalyst_becomes_hold` / `test_a4_sell_no_breach_with_catalyst_goes_to_check` / `test_a4_stop_loss_breach_bypasses_catalyst_check`.
- **Stored T-1 vs live divergence flag** (Phase 2 A-5, PR #379): `prices` 일봉 close 만 저장 → 장중 stale. `nuri/core/live_price.py::fetch_live_price`/`check_divergence(threshold=3.0)`. Threshold 비교는 stored 유지 (flag only) — STRATEGY §2.6 Surface 단계 (A-5b 에 oracle 신뢰도 후 승격). **Test:** `tests/core/test_live_price.py::TestMarketHours` (9) + `TestFetchLivePrice` (4) + `TestCheckDivergence` (6) + `tests/api/test_actions.py::TestBuildActionsLogic::test_a5_*` (3).
- **Multi-account ticker aggregate + worst-pnl row** (Phase 2 A-6, PR #381): `_get_portfolio_map` 이 largest-position row 만 keep → 다른 계좌 stop-loss/divergence silently masked. Fix: aggregate `position_pct`, worst-pnl 기준 `pnl_pct`/`current_price`/`account` (conservative threshold 비교, certification.py 와 semantic 일치). **Test:** `tests/api/test_actions.py::TestGetPortfolioMapAggregation` (4).
- **Concentration-only ≠ SELL** (PR A #429): position_limit/concentration → `portfolio_action=REBALANCE`, `alpha_action=None`. Stop-loss breach 만 `alpha_action=FLAT` + urgent. See **Key Design Patterns** + STRATEGY §3.7. **Test:** `tests/trading/agents/test_risk_alpha_portfolio_split.py::TestConcentrationOnlyDoesNotTriggerSellVeto::test_concentration_alone_emits_portfolio_action_not_sell` + `TestConcentrationHighConfidenceCannotVeto::test_consensus_does_not_veto_on_concentration_only` + `tests/api/test_actions.py::TestPRABucketRouting::test_concentration_violation_goes_to_portfolio_bucket` + `::test_stop_loss_breach_still_urgent`.
- **SIEGE audit snapshot invariant** (E4-0a, PR #410): `CertSnapshot` + `ContextVar` 로 모든 portfolio consumer 동일 상태 공급 (single DB read → hash). See **Key Design Patterns**. **Test:** `tests/trading/engine/test_certification_persist.py::TestSnapshotInvariant` (5) + `TestAnalyzePortfolioFailurePreservesGateSemantics` (3) + `TestRawPortfolioSnapshot` (3) + `TestCertifyPersistFailureLoudDefault` (2) + `TestComputePortfolioHash::test_hash_changes_on_sector_only_mutation`.

## Harness File Map

This project uses layered context files. Root files load every session; directory-scoped files load when working in that directory.

| File | Role | Auto-loaded |
|------|------|-------------|
| `CLAUDE.md` (this file) | Commands, architecture overview, conventions | Always |
| `AGENTS.md` | Cross-tool rules (Cursor/Copilot/Codex) | Not by Claude Code (for other agents) |
| `docs/STRATEGY.md` | Design principles, investment rules, harness theory | Always (@import) |
| `docs/TODO.md` | Work backlog (Tier 1 완료 / Tier 2 next / Tier 3 research, 영구 배경) | On demand (planning/backlog) |
| `docs/HARNESS.md` | Harness case studies (#272 session, JKHY episode) | On demand (debugging similar patterns) |
| `docs/ARCHITECTURE.md` | Detailed architecture, DB schema, env vars, CI/CD, testing | On demand |
| `nuri/core/CLAUDE.md` | db.py rules, timezone, events, freshness | When editing nuri/core/ |
| `nuri/collectors/CLAUDE.md` | BaseCollector contract, OpenBB quirks | When editing nuri/collectors/ |
| `nuri/trading/agents/CLAUDE.md` | Agent system, consensus, veto rules | When editing nuri/trading/agents/ |
| `nuri/trading/engine/CLAUDE.md` | SIEGE gates, confidence formula, v2 spec | When editing nuri/trading/engine/ |
| `docs/SIEGE_V2.md` | 3D certification architecture (Account × Asset Class × Market) | When editing nuri/trading/engine/ |
| `frontend/CLAUDE.md` | Next.js 16, design system, testing gotchas | When editing frontend/ |
| `tests/CLAUDE.md` | Fixtures, mocks, testing gotchas | When editing tests/ |
| `config/CLAUDE.md` | YAML structure, change procedures | When editing config/ |
| `NEXT_SESSION.md` | Session handoff doc — 다음 세션 시작 시 먼저 읽음 | gitignored (personal) |
| `~/.claude/projects/-Users-ehbebe-workspace-nuri-quant/memory/` | User-scoped auto-memory (`MEMORY.md` index + per-topic files) | Always (cross-conversation, not committed) |

**Precedence when sources conflict**: repo truth (code/config) > `NEXT_SESSION.md` > auto-memory. If a recalled memory contradicts what you read now, trust the code and update the stale memory.

### Mechanical Enforcement (Hooks + CI)

| What | How | Enforcement | Where |
|------|-----|------|-------|
| `import sqlite3` outside db.py | PreToolUse hook | **Blocking** (exit 2 + `decision:block`) | `.claude/settings.json` |
| `git push --force`, `git reset --hard`, `git clean -f` | PreToolUse hook (Bash matcher) | **Blocking** (exit 2 + `decision:block`) | `.claude/settings.json` |
| `datetime.now()` usage | PostToolUse hook | **Blocking** (exit 1 + `decision:block` surfaces to Claude) | `.claude/settings.json` |
| Ruff lint violations | PostToolUse hook | **Advisory** (pipes `ruff check` output to `head -10`; no block) | `.claude/settings.json` |
| Privacy leaks (broker names, monetary literals) | CI `privacy-scan` job + `pre_push_check.sh` | Every push + PR | `.github/workflows/main-ci-cd.yml`, `scripts/pre_push_check.sh`, `scripts/check_privacy_leak.py` |
| Test regression | CI + Codecov 1% gate | Every PR | `.github/workflows/main-ci-cd.yml` |
| Trivy CRITICAL vulnerabilities | CI `security-scan` job | Every push | `.github/workflows/main-ci-cd.yml` |

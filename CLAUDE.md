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
├── api/               # FastAPI REST API (65 endpoints, routes/ incl. actions/opportunities/market-context/coverage)
├── alerts/            # Discord daily report + bot, Telegram alerts
└── llm/               # LLM report (Ollama) + OpenAI wrapper + event classifier
```

### Key Design Patterns

- **DB sole integration point**: `nuri/core/db.py` is the ONLY `sqlite3` importer (hook-enforced). See `nuri/core/CLAUDE.md`.
- **Loose coupling via data**: Pipeline phases communicate through DB/CSV, never direct imports. See `docs/ARCHITECTURE.md`.
- **Collector template**: All inherit `BaseCollector` (collect→save→run). See `nuri/collectors/CLAUDE.md`.
- **10-agent consensus**: Weighted voting, risk agent veto. See `nuri/trading/agents/CLAUDE.md`.
- **SIEGE v2 certification**: 3D gate (Account × Asset Class × Execution Market). `conditions` count is variable — per-asset-class expansion flattens at `certify()`. 1 error-grade fail → REJECTED. See `nuri/trading/engine/CLAUDE.md` + `docs/SIEGE_V2.md`.
- **20 signals, YAML registry**: `config/signals.yaml` drives `signal_backtest.py`. See `docs/ARCHITECTURE.md`.
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

- **Macro event pipeline** (PR #249-#253): 15 categories (was 12), stale articles >7d filtered, confidence <0.3 excluded from event_score, recency weighting (today=1.0→3d=0.5), regime_hint requires 3+ events. Korean Market Agent reads `macro_events` table for `export_surge`/`demand_growth`.
- **OpenAI Tier 2 ZDR gate** (PR #294): `make report-llm`이 조용히 실패하면 `OPENAI_ZDR_APPROVED=1` 미설정이 원인. OpenAI ZDR 승인 후 `.env`에 설정. `NURI_DISABLE_EXTERNAL_LLM=1`로 전면 opt-out 가능. 정책: §4.4.3.
- **Universe coverage 5-check gate** (PR #284/#286/#288/#296/#343/#345): `scripts/validate_universe.py` 는 prices/fundamentals/analyst/insider/super 5개 thresholds (≥95/80/70/50/80%) 검사. CI `Universe Coverage Validation` job 은 **required** (PR #343 이후 — `continue-on-error` 제거 + branch protection 등록). PR #345 가 `if:` 조건을 제거해 always-run 으로 변경 — 등록된 required check 가 모든 PR 유형에서 보고되도록 보장 (아래 "Branch protection conditional skip trap" 참조). `US_ONLY_TABLES` frozenset (analyst_ratings/insider_trades/superinvestors) 은 KR 에서 `n/a (US-only)` 표시 — 수집 실패 아닌 소스 한계. 새 테이블을 universe coverage 대상에 넣으려면 `check_universe_coverage.py` + `validate_universe.py` 둘 다 수정.
- **JKHY falling knife pattern** (`docs/HARNESS.md §2`, PR #301-#303 완료 2026-04-15): 원 진단 ("chart_analysis.py 미연결") 은 오독 — TechnicalAgent 가 이미 호출 중. 실제 실패 모드는 "TechnicalAgent SELL 이 9 개 다른 에이전트 BUY 에 outweighted" + "dissent 가 사용자에게 surface/action 영향 없음". **현재 defense (4-layer)**: P1 B universe 1y backfill → P1 A1 `divergence_flag` 감지 → P1 A2 UI `⚠` 배지 → P1 A3 mechanical penalty (tech conf ≥ 80 opposite → HOLD downgrade). Live verified: JKHY 가 이제 action=HOLD. **Test:** `tests/trading/agents/test_consensus.py::TestConsensusDivergence*` (5 cases) + `TestConsensusDivergenceMechanicalPenalty` (8 cases) + `TestPenaltyTelemetryEvent` (5 cases).
- **Commit message privacy scanning** (PR #289): `scripts/pre_push_check.sh` Section 4b가 `origin/main..HEAD` 범위의 unpushed commit message를 자동 스캔. 수동 확인은 `git log -1 --format=%B | .venv/bin/python scripts/check_privacy_leak.py --message` 또는 `.venv/bin/python scripts/check_privacy_leak.py --unpushed-commits`. 잡히는 패턴: broker name + ticker에 인접한 signed % (괄호 안 또는 뒤쪽). 스캐너가 본인의 문서나 PR 본문에서 이 패턴을 의심하면 placeholder (HWM/MDD 같은 false-positive whitelist 단어 또는 구체 티커 제거) 로 변경. 상세 룰: `docs/STRATEGY.md §4.4.1`.
- **Branch protection conditional skip trap** (PR #343 → #344 → #345 cascade, 2026-04-16): `required_status_checks` 에 **conditional job** (workflow `if:` 절을 가진 job) 을 등록하면, 그 조건이 false 인 PR (예: docs-only, gitignore-only) 에서 job skip → required check 미보고 → mergeable 인데 머지 BLOCKED. PR #343 이 universe-check 를 required 로 promote 한 직후 PR #344 (`.gitignore` 만 변경) 가 정확히 이 패턴으로 stuck → PR #345 가 root cause fix (job 의 `if:` 제거 → always-run). 기존 gotcha "required_status_checks 이름이 workflow job 이름과 정확히 일치해야 함" 의 sibling failure mode. **방어**: required check 등록 전 checklist — (1) 해당 job 의 workflow `if:` 부재 확인, (2) docs-only / gitignore-only PR 에서도 trigger 됨 verify (직전 docs PR Actions 페이지에서 해당 job 의 status 가 `pass` 인지 확인 — `skipping` 이면 등록 보류). *(facts/policy, no fix-pattern test)*
- **Factors modules must read DB, never external APIs** (#349, PR #350, 2026-04-16): `quant/factors/{quality,value,momentum,sentiment}.py` 는 `fundamentals` / `prices` / `macro` 테이블 만 query — STRATEGY §2.3 loose coupling + §3.1 DB sole integration point. 과거 quality.py / value.py 가 `obb.equity.fundamental.ratios` 를 직접 호출 → OpenBB 깨짐 → silent `except` → empty df → `composite.py:48-49` 의 0.5 default → **전 유니버스 quality_score = value_score = 0.5 상수** (1536 rows 검증, 투자 판단 가중치 50% dead → composite 가 사실상 momentum-only ranker). Architecture drift 는 AST-based import guard 로 lock (string-match 는 docstring false-positive). **Test:** `tests/quant/test_factors_quality.py::TestQualityDbRead::test_quality_source_has_no_openbb_import` + `tests/quant/test_factors_value.py::TestValueDbRead::test_value_source_has_no_openbb_import` (`ast.walk` → `openbb` import 재도입 시 fail) + `::test_*_score_non_constant_when_fundamentals_vary` (nunique > 1 lock).
- **SQLite upsert 반환값은 `cursor.rowcount`, NOT `len(records)`** (#351, PR #352, 2026-04-16): `INSERT OR IGNORE` 기반 upsert (URL UNIQUE dedup 예: `upsert_news`) 에서 `len(records)` 를 반환하면 IGNORED rows 포함 → "뉴스 120 건 수집" 로그와 DB 실제 106 rows 불일치 (§2.4 Observability 위배). SQLite `cursor.rowcount` 는 `executemany` 에서 실제 affected rows 만 보고. **예외** `INSERT OR REPLACE` (예: `_upsert_etf_flows`): insert + replace 모두 counting → 정상 input (내부 PK dup 없음) 에서는 `len(records) == rowcount`, 따라서 fix 불필요. 새 upsert 함수 작성 시 IGNORE vs REPLACE 구분해 반환값 semantic 선택. **Test:** `tests/core/test_db.py::TestUpsertNewsDedupCount::test_returns_actual_insert_count_on_url_dedup` (input 3 with 1 dup URL → 반환값 == DB row count == 2).
- **Sell-path threshold 는 holding row 의 account 로 resolve, `<` operator 통일** (Phase 2 A-3, PR TBD, 2026-04-18): `risk_agent.py` 와 `actions.py` 는 과거 각각 `STOCK_STOP_LOSS` (-7 global) / `pnl_pct < -7` (하드코딩) 을 썼음 → long_term(-20) / pension(-30) 계좌 보유 ticker 도 -7% 손실에서 "손절선 돌파" / "urgent" 로 잘못 분류. `certification.py` 만 per-account strategy 를 올바르게 참조 → **3곳 threshold drift**. Fix: `nuri/core/rules.py::get_stop_loss_for_account(account)` — account 명 → `get_account_strategy(account)["stop_loss"]` 반환 (None/미매칭 → `STOCK_STOP_LOSS` fallback). Callers 는 **PnL 이 계산된 holding row 와 같은 account** 를 넘김 (aggregation mismatch 금지 — pnl 은 row 의 cost basis 이므로 threshold 도 row 의 account 에서 와야 함). Operator 도 `<` 로 통일 (certification.py:308 과 일치; 이전 risk_agent 는 `<=`). 새 sell-path consumer 를 작성할 때 global 상수 대신 반드시 account-scoped helper 사용 (§2.2 mechanical execution). **Test:** `tests/core/test_rules.py::TestGetStopLossForAccount` (7 cases — None/빈 account/core/long_term/pension/unknown/int type) + `tests/trading/agents/test_risk.py::TestRiskAgentA3PerAccountThreshold` (long_term -10% no-fire, long_term -22% fire, core -8% fire, boundary equality no-fire) + `tests/api/test_actions.py::TestBuildActionsLogic` (long_term -10% not-urgent, long_term -22% urgent, core -10% urgent, boundary equality not-urgent).

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

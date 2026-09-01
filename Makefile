# ═══════════════════════════════════════════════════════════════
# Nuri-Quant Makefile
# ═══════════════════════════════════════════════════════════════
# 모든 target은 .venv/bin/python 사용 — venv 활성화 불필요
# `make help` 로 카테고리별 명령 확인
# ═══════════════════════════════════════════════════════════════

PYTHON = .venv/bin/python

.PHONY: help \
        setup test test-fast test-slow ci-cov ci-cov-detail lint lint-fix verify-quick verify-all verify verify-fast \
        collect collect-kis collect-kis-check wallstreet filings \
        analyze report report-llm \
        validate regime recommend gate consensus certify remediate track-decisions \
        scan scan-extended scan-kr swing swing-check strategy strategy-execute positions \
        backtest backtest-ls backtest-stress backtest-rules \
        optimize mean-reversion pairs \
        targets rebalance evidence external \
        api dashboard start \
        full-scan quick-scan \
        deploy deploy-mini pre-deploy backup scheduler-reload-remote ports ports-kill \
        sync-doc-counts verify-doc-counts update-counts demo


# ═══════════════════════════════════════════════════════════════
# HELP
# ═══════════════════════════════════════════════════════════════
help:
	@echo "Nuri-Quant Makefile — 카테고리별 주요 명령"
	@echo ""
	@echo "  Setup:        make setup"
	@echo "  Test/Lint:    make test, make test-fast, make lint, make lint-fix, make lint-sh"
	@echo "  Verify:       make verify-help    (4 tiers — 사다리가 아니라 서로 다른 것을 본다. 목적으로 고를 것)"
	@echo "  Data:         make collect, make collect-kis, make wallstreet, make filings"
	@echo "  Universe:     make universe-sync[-us/-kr/-apply], make collect-universe[-1y], make validate-universe"
	@echo "  Universe gen: make kr-names (KR 종목명 캐시), make cspell-tickers (cSpell 사전) — sync-apply 가 자동 체이닝"
	@echo "  Analysis:     make analyze, make consensus, make scan, make backtest"
	@echo "  Pipeline:     make full-scan, make quick-scan"
	@echo "  Trading:      make targets, make rebalance, make recommend, make certify, make remediate"
	@echo "  Strategy:     make strategy, make backtest-ls, make optimize, make mean-reversion, make pairs"
	@echo "  Reports:      make report, make report-llm, make evidence, make external"
	@echo "  Server:       make api, make dashboard, make start"
	@echo "  Deploy:       make deploy-mini (★ MBP → Mac mini 1-cmd), make scheduler-reload-remote, make deploy, make backup"
	@echo "  Dev sync:     make sync-start / sync-end / sync-status"
	@echo "  Utility:      make ports, make ports-kill, make sync-doc-counts, make verify-doc-counts, make demo"
	@echo "  Clean:        make clean, make clean-all, make clean-deep"

verify-help:
	@printf '\n'
	@printf '  \033[1;36mNuri-Quant verify tiers\033[0m — 네 티어는 서로 다른 것을 본다. 목적으로 고를 것\n'
	@printf '\n'
	@printf '  \033[1m%-14s %-9s %s\033[0m\n' 'TIER' 'RUNTIME' 'WHAT IT DOES'
	@printf '  \033[2m%s\033[0m\n' '──────────────────────────────────────────────────────────────────'
	@printf '  \033[36m%-14s\033[0m \033[33m%-9s\033[0m %s\n' 'verify-quick' '84.9s' 'pytest + regime classifier (no network)'
	@printf '  \033[36m%-14s\033[0m \033[33m%-9s\033[0m %s\n' 'verify-fast'  '127s'  'scripts/verify/verify.py --skip-backtest'
	@printf '  \033[36m%-14s\033[0m \033[33m%-9s\033[0m %s\n' 'verify'       '213s'  'scripts/verify/verify.py (full backtest run)'
	@printf '  \033[36m%-14s\033[0m \033[33m%-9s\033[0m %s\n' 'verify-all'   '320.8s' 'tests + backend + frontend + file integrity'
	@printf '  \033[2m%s\033[0m\n' 'M5 Max 실측 — quick/all 2026-08-14, fast/verify 2026-08-17. 각 1회'
	@printf '\n'
	@printf '  \033[1mWhen to use:\033[0m\n'
	@printf '    Pre-commit   →  \033[36mmake verify-quick\033[0m\n'
	@printf '    Pre-push     →  \033[36mmake verify-all\033[0m\n'
	@printf '    Pre-deploy   →  \033[36mmake verify-fast\033[0m\n'
	@printf '    Pre-release  →  \033[36mmake verify\033[0m\n'
	@printf '\n'


# ═══════════════════════════════════════════════════════════════
# SETUP
# ═══════════════════════════════════════════════════════════════
setup:
	bash scripts/dev/setup.sh
	$(PYTHON) scripts/db/migrate.py
	$(PYTHON) scripts/ops/import_portfolio.py
	$(MAKE) setup-hooks
	@# KR 종목명 맵 — 없으면 한국어 이름 검색이 동작하지 않는다 (#1255). FDR 네트워크를
	@# 타므로 best-effort: 실패해도 setup 을 막지 않되, 실패는 **보이게** 남긴다.
	-$(MAKE) kr-names

setup-hooks: ## Install repo-tracked git hooks (pre-commit auto-fix). Idempotent.
	bash scripts/dev/install_hooks.sh


# ═══════════════════════════════════════════════════════════════
# TEST / LINT / VERIFY
# ═══════════════════════════════════════════════════════════════
# --cov-branch 는 CI 와 의미를 맞추기 위한 것이다 (#1133). codecov 는 patch
# target 100% / threshold 0% 로 **부분 분기**까지 세므로, 분기 없이 재면 로컬은
# 100% 를 보고하고 codecov 는 미달을 낸다 (실측 PR #1124: 로컬 100% ↔ codecov 85.71%).
test:
	$(PYTHON) -m pytest tests/ -v --cov=nuri --cov-branch -n auto --dist worksteal

# ⚠️ `-m` 은 addopts 의 `-m` 을 **덮어쓴다** (합쳐지지 않는다). pyproject 의
# `addopts = -m "not integration"` 은 여기서 무효가 되므로 **직접 다시 적어야 한다**.
# 안 적으면 실외부 네트워크를 타는 integration 테스트가 fast 게이트에 섞여, KRX 가
# 죽은 날 코드와 무관하게 빨간불이 뜬다 (#1290). CI 샤드는 원래 둘 다 적고 있었다 —
# 로컬만 갈라져 있었다.
test-fast:
	$(PYTHON) -m pytest tests/ -v --cov=nuri --cov-branch -n auto --dist worksteal -m "not slow and not integration"

# ─── CI artifact ground-truth coverage (Issue #616 verification protocol) ───
# 직전 main CI run 의 6 shards (.coverage artifacts) 다운로드 + combine →
# Codecov 와 동일한 측정값 산출. local pytest --cov 는 dev 환경 path 의존
# (config/portfolio.yaml 등) 으로 결과 다를 수 있어 ground truth 아님.
ci-cov:    ## Latest main CI artifact 6 shards combine → coverage report
	@LATEST=$$(gh run list --branch main --workflow main-ci-cd.yml --limit 1 --json databaseId | jq -r '.[0].databaseId'); \
	if [ -z "$$LATEST" ] || [ "$$LATEST" = "null" ]; then echo "❌ no recent main CI run"; exit 1; fi; \
	echo "📥 Downloading shards from run $$LATEST"; \
	rm -rf /tmp/ci-cov-shards && mkdir -p /tmp/ci-cov-shards; \
	cd /tmp/ci-cov-shards && for s in fast-1 fast-2 fast-3 fast-4 slow-1 slow-2; do \
	    gh run download "$$LATEST" --name "coverage-$$s" --dir ./$$s -R researcherhojin/nuri-quant 2>&1 | tail -1; \
	done; \
	cd $(CURDIR); \
	rm -f .coverage.ci .coverage.ci.shard.*; \
	for d in fast-1 fast-2 fast-3 fast-4 slow-1 slow-2; do \
	    [ -f /tmp/ci-cov-shards/$$d/.coverage ] && cp /tmp/ci-cov-shards/$$d/.coverage .coverage.ci.shard.$$d; \
	done; \
	$(PYTHON) -m coverage combine --data-file=.coverage.ci .coverage.ci.shard.* 2>&1 | tail -3; \
	echo ""; echo "═══ CI ground-truth coverage ═══"; \
	$(PYTHON) -m coverage report --data-file=.coverage.ci --skip-covered; \
	rm -f .coverage.ci.shard.*

ci-cov-detail:    ## ci-cov + show-missing for files with gaps
	@$(MAKE) --no-print-directory ci-cov 2>&1 | head -1
	@$(PYTHON) -m coverage report --data-file=.coverage.ci --show-missing --skip-covered

# ─── #529 Phase 2 production verification ────────────────
phase2-chain:    ## Phase 2 4-actor chain end-to-end on real macro + ticker (default NVDA)
	$(PYTHON) scripts/ops/run_phase2_chain.py --ticker $(or $(ticker),NVDA) \
	    --proposed-action $(or $(action),BUY) \
	    --proposed-value $(or $(value),3000)

phase2-chain-dry:    ## Phase 2 chain dry-run (no DB write, validation only)
	$(PYTHON) scripts/ops/run_phase2_chain.py --ticker $(or $(ticker),NVDA) --dry-run

# ─── #529 Phase 2 운영 cron (O2 + O3) ────────────────────
track-forward:    ## ForwardOutcomeTracker scan — emit decision outcome 측정 (closed loop)
	$(PYTHON) -m nuri.agents.actors.forward_outcome_tracker scan

sre-scan:    ## SREIncidentAgent scan — 6 detector (orphan/disk/heartbeat/freshness/...)
	$(PYTHON) -m nuri.agents.actors.sre_incident_agent scan

crons-install:    ## launchd cron 일괄 설치 (모든 plist auto-discover, --only/--exclude 가능)
	bash scripts/launchd/install_crons.sh $(ARGS)

crons-uninstall:    ## launchd cron 일괄 제거
	bash scripts/launchd/uninstall_crons.sh $(ARGS)

crons-status:    ## 설치된 cron 상태 + 로그 위치 표시
	@launchctl list | grep -E "com\.nuri-quant\." || echo "  (none installed)"
	@echo ""
	@echo "  로그: data/logs/"

# ─── #596 Phase 1 — Post-market brief (KR / US) ──────────
postmortem-kr:    ## Post-market brief (KR session, KST 16:00 — KOSPI close + 30min)
	@.venv/bin/python -m nuri.alerts.postmarket_brief --session kr

postmortem-us:    ## Post-market brief (US session, NYSE 16:00 ET + 30min)
	@.venv/bin/python -m nuri.alerts.postmarket_brief --session us

# `not integration` 은 여기도 필요하다 — 같은 이유(위 test-fast 주석). integration 은
# `make test-integration` 으로만 돈다.
test-slow:
	$(PYTHON) -m pytest tests/ -v -n auto --dist worksteal -m "slow and not integration"

lint:
	$(PYTHON) -m ruff check nuri/ tests/ scripts/

lint-fix:
	$(PYTHON) -m ruff check nuri/ tests/ scripts/ --fix

lint-sh: ## Shell script lint via shellcheck (brew install shellcheck)
	@command -v shellcheck >/dev/null 2>&1 || { echo "shellcheck not installed: brew install shellcheck"; exit 1; }
	find scripts -name '*.sh' -exec shellcheck --source-path=SCRIPTDIR --external-sources {} +

typecheck: ## Pyright static type-check across nuri/, tests/, scripts/ (advisory; severity 8 only)
	@command -v npx >/dev/null 2>&1 || { echo "npx not installed: install Node.js"; exit 1; }
	npx --yes -p pyright pyright nuri/ tests/ scripts/ --outputjson 2>/dev/null | \
		.venv/bin/python -c "import json,sys; d=json.load(sys.stdin); diags=[x for x in d.get('generalDiagnostics',[]) if x.get('severity')=='error']; \
		print(f'pyright: {len(diags)} error(s) across {len({x[\"file\"] for x in diags})} files'); \
		[print(f'  {x[\"file\"]}:{x[\"range\"][\"start\"][\"line\"]+1} [{x.get(\"rule\",\"?\")}]: {x[\"message\"].splitlines()[0]}') for x in diags[:50]]; \
		sys.exit(1 if diags else 0)" || true

spellcheck: ## cspell check (uses .cspell.json — add words there for false positives)
	@command -v npx >/dev/null 2>&1 || { echo "npx not installed: install Node.js"; exit 1; }
	@# Excludes gitignored files (NEXT_SESSION.md / SESSION_PROMPT.md may contain personal info)
	@# ⚠️ config/*.yaml 을 여기 넣지 말 것 — glob 이 gitignored config/portfolio.yaml 까지 훑어
	@# 실보유 증권사명을 미등록 단어로 뱉는다. 그걸 "고치려고" .cspell.json 에 넣는 순간
	@# 공개 레포에 증권사명이 박힌다 (§4.4.1 privacy). 이 주석에 그 예시를 적는 것조차
	@# check_privacy_leak.py 가 차단한다 — 2026-08-02 실측, 가드가 정상 동작한 것이다.
	@# IDE 는 열린 파일을 직접 검사하므로 config 경고는 거기서만 보이고,
	@# 추적 중인 config yaml 의 단어는 이미 .cspell.json 에 등재돼 있다.
	npx --yes -p cspell cspell --config .cspell.json --no-progress --no-summary \
		--exclude SESSION_PROMPT.md --exclude NEXT_SESSION.md \
		"nuri/**/*.py" "tests/**/*.py" "scripts/**/*.py" "scripts/**/*.sh" \
		"nuri/**/CLAUDE.md" "tests/**/CLAUDE.md" "scripts/**/*.md" \
		"docs/*.md" "README.md" "CLAUDE.md" "AGENTS.md" "CONTRIBUTING.md" \
		".claude/rules/*.md" ".claude/commands/nuri-*.md" ".claude/agents/nuri-*.md" \
		".claude/skills/nuri-*/**/*.md" ".github/workflows/*.yml" "frontend/e2e/*.ts" \
		"frontend/CLAUDE.md" "frontend/*.ts" "frontend/*.mjs" "frontend/.gitignore" 2>&1 | tail -80 || true

diagnostics: typecheck spellcheck ## Run pyright + cspell — surfaces all IDE-level issues

validate-portfolio: ## Verify each ticker in config/portfolio.yaml has live data (#131)
	$(PYTHON) scripts/doc/validate_portfolio.py

universe-sync:       ## Dry-run sync (US + KR). For --market/--allow-removal flags use `python -m` (#272)
	$(PYTHON) -m nuri.collectors.universe_sync

universe-sync-us:    ## Dry-run US S&P 500 sync only
	$(PYTHON) -m nuri.collectors.universe_sync --market us

universe-sync-kr:    ## Dry-run KR KOSPI 200 sync only (requires: uv pip install finance-datareader)
	$(PYTHON) -m nuri.collectors.universe_sync --market kr

universe-sync-apply: ## Apply universe.yaml updates (additions only — manual ETFs preserved)
	$(PYTHON) -m nuri.collectors.universe_sync --apply
	-$(PYTHON) scripts/ops/gen_kr_names.py  # best-effort: sync 성공 후 KR 종목명 캐시 갱신 (FDR 장애 시 무시)
	$(PYTHON) scripts/ops/gen_cspell_tickers.py  # universe 변경분 cSpell 사전 반영

kr-names:            ## Regenerate config/kr_ticker_names.json (KR 종목명 network-free 캐시)
	$(PYTHON) scripts/ops/gen_kr_names.py

cspell-tickers:      ## Regenerate .cspell/tickers.txt (universe.yaml 기반 cSpell 사전)
	$(PYTHON) scripts/ops/gen_cspell_tickers.py

validate-universe:   ## Universe + agent coverage 검증 (#272 Phase 2c)
	$(PYTHON) scripts/doc/validate_universe.py

validate-universe-cache:  ## DB만 검사 (network fetch skip — CI용)
	$(PYTHON) scripts/doc/validate_universe.py --no-fetch

collect-universe:    ## Collect ALL universe data (US+KR prices, fundamentals, wallstreet, estimates) (#272)
	$(PYTHON) -m nuri.collectors.stock --source universe
	$(PYTHON) -m nuri.collectors.stock_kr --source universe
	$(PYTHON) -m nuri.collectors.fundamental --source universe
	$(PYTHON) -m nuri.collectors.wallstreet --source universe
	$(PYTHON) -m nuri.collectors.estimates --source universe

collect-universe-1y: ## Backfill 1y OHLCV for full universe — prerequisite for P1 A tech analysis (BB/MACD/52w)
	$(PYTHON) -m nuri.collectors.stock --source universe --period 1y
	$(PYTHON) -m nuri.collectors.stock_kr --source universe --days 365

test-integration: ## Integration tests — real external APIs (Wikipedia, FDR, yfinance). Network required.
	$(PYTHON) -m pytest tests/integration/ -m integration -v --no-header

verify-universe-sync: ## Smoke test universe-sync targets — catches real API breakage (#272)
	@echo "=== Integration tests ==="
	$(PYTHON) -m pytest tests/integration/test_universe_sync_real.py -m integration -v --no-header
	@echo "\n=== make universe-sync-us (live) ==="
	@$(PYTHON) -m nuri.collectors.universe_sync --market us 2>&1 | grep -E "fetched|종목" | head -3
	@echo "\n=== make universe-sync-kr (live) ==="
	@$(PYTHON) -m nuri.collectors.universe_sync --market kr 2>&1 | grep -E "fetched|종목|건너뜀" | head -3
	@echo "\n✅ universe-sync smoke passed"

# Verify tiers — fastest to slowest. See `make verify-help` for the full table.

verify-quick:    ## pre-commit smoke test — pytest + regime, no network (84.9s)
	$(PYTHON) -m pytest tests/ -q --tb=line -n auto --dist worksteal
	$(PYTHON) -c "from nuri.core.db import query; from nuri.quant.regime.classifier import classify_regime; r=classify_regime(); print(f'Quick: tests + Regime {r.regime if r else \"N/A\"}')"

verify-all:      ## pre-push — tests + backend + frontend + file integrity (320.8s, 네 티어 중 가장 느리다)
	bash scripts/verify/verify_all.sh

verify-fast:     ## pre-deploy — verify.py without backtest (127s)
	$(PYTHON) scripts/verify/verify.py --skip-backtest

verify:          ## pre-release — verify.py full, includes backtest (213s)
	$(PYTHON) scripts/verify/verify.py


# ═══════════════════════════════════════════════════════════════
# DATA COLLECTION (Phase A)
# ═══════════════════════════════════════════════════════════════
collect:
	$(PYTHON) -m nuri.collectors.stock
	$(PYTHON) -m nuri.collectors.stock --source freshness   # #453 — SIEGE freshness pass (SPY/TLT/GC=F)
	$(PYTHON) -m nuri.collectors.stock_kr
	$(PYTHON) -m nuri.collectors.macro
	$(PYTHON) -m nuri.collectors.technical
	$(PYTHON) -m nuri.collectors.fear_greed
	$(PYTHON) -m nuri.collectors.ark
	$(PYTHON) -m nuri.collectors.cboe
	$(PYTHON) -m nuri.collectors.coingecko
	$(PYTHON) -m nuri.collectors.finviz
	$(PYTHON) -m nuri.collectors.reddit
	$(PYTHON) -m nuri.collectors.fred_calendar
	$(PYTHON) -m nuri.collectors.macro_news

collect-kis:
	$(PYTHON) -m nuri.collectors.kis_realtime

collect-kis-check:
	$(PYTHON) -m nuri.collectors.kis_realtime --check-creds

collect-kis-analyst: ## #418 — KR 애널리스트 투자의견 수집 (KIS invest-opinion REST endpoint)
	$(PYTHON) -m nuri.collectors.kis_analyst_opinion

reconcile-toss: ## Toss 보유 → portfolio diff (dry-run). 반영은 `--apply` 직접 실행
	$(PYTHON) scripts/ops/reconcile_toss.py

wallstreet:
	$(PYTHON) -m nuri.collectors.wallstreet

filings:
	$(PYTHON) -m nuri.collectors.filings


# ═══════════════════════════════════════════════════════════════
# ANALYSIS (Phase B)
# ═══════════════════════════════════════════════════════════════
analyze:
	$(PYTHON) -m nuri.analysis.portfolio
	$(PYTHON) -m nuri.analysis.sector
	$(PYTHON) -m nuri.analysis.risk


# ═══════════════════════════════════════════════════════════════
# VALIDATION (Phase C) — Gate 검증 후 실행
# ═══════════════════════════════════════════════════════════════
validate: ## Full signal validation suite — gate_check + signal/superinvestor/analyst backtest + scorecard + memory snapshot
	$(PYTHON) scripts/verify/gate_check.py validate
	$(PYTHON) -m nuri.quant.validation.signal_backtest
	$(PYTHON) -m nuri.quant.validation.superinvestor_backtest
	$(PYTHON) -m nuri.quant.validation.analyst_backtest
	$(PYTHON) -m nuri.quant.validation.scorecard
	$(PYTHON) -m nuri.trading.engine.memory --snapshot


# ═══════════════════════════════════════════════════════════════
# REGIME CLASSIFICATION (Phase D)
# ═══════════════════════════════════════════════════════════════
regime: ## Macro regime classification (10 regimes) + suggested strategy mix
	$(PYTHON) scripts/verify/gate_check.py regime
	$(PYTHON) -m nuri.quant.regime.strategy_map


# ═══════════════════════════════════════════════════════════════
# RECOMMENDATIONS + AGENTS (Phase E)
# ═══════════════════════════════════════════════════════════════
recommend:
	$(PYTHON) scripts/verify/gate_check.py recommend
	$(PYTHON) -m nuri.trading.recommend.candidates
	$(PYTHON) -m nuri.trading.recommend.tracker --save

consensus:
	$(PYTHON) -m nuri.trading.agents.consensus

# Holdings post-entry technical-divergence monitor.
# Daily 07:10 KST via APScheduler (after consensus 07:05). CLI form for ad-hoc / dry-run.
holdings-monitor: ## Holdings post-entry technical-divergence monitor (live; daily 07:10 KST via APScheduler)
	$(PYTHON) -m nuri.trading.recommend.holdings_monitor

holdings-monitor-dry: ## Holdings monitor dry-run (no DB write)
	$(PYTHON) -m nuri.trading.recommend.holdings_monitor --dry-run

# Dual-LLM consult helper — codex + Qwen3.5 in parallel, archive both verdicts
# to data/llm_consults/ (gitignored). Use for design-ambiguity decisions.
# Usage: make llm-consult slug=<kebab> prompt=<file>
llm-consult:
	@test -n "$(slug)" || (echo "usage: make llm-consult slug=<kebab> prompt=<file>"; exit 1)
	@test -n "$(prompt)" || (echo "usage: make llm-consult slug=<kebab> prompt=<file>"; exit 1)
	$(PYTHON) scripts/dev/llm_consult.py --slug "$(slug)" --prompt-file "$(prompt)"

# Earnings preview (Issue #509) — consensus EPS/revenue + ATM straddle implied move.
# yfinance-based, on-demand. Future: 위스퍼 (Estimize/StockTwits) Phase 2.
# Usage:
#   make earnings-preview ticker=MSFT
#   make earnings-preview watchlist=MSFT,META,AMZN,GOOGL,QCOM
earnings-preview:
	@test -n "$(ticker)$(watchlist)" || (echo "usage: make earnings-preview ticker=<T> | watchlist=<T1,T2,...>"; exit 1)
	$(PYTHON) -m nuri.collectors.earnings_preview $(if $(ticker),--ticker "$(ticker)") $(if $(watchlist),--watchlist "$(watchlist)")

# 투자 논지 원장 (#1083) — 상승/하락 논리를 근거와 함께 기록하고, 결정 상세 화면에
# point-in-time 으로 붙인다. 기본 status 는 draft — active 승격은 파일에 명시할 때만.
# Usage:
#   make thesis-write file=data/reports/theses/drafts/nvda.yaml  # gitignored — 논지는 public repo 에 커밋 금지
#   make thesis-show ticker=NVDA
# 실거래 기록 (#1163) — 매매 직후 1줄. 원장은 mini (§3.11), dev 입력 시 sync_dev push.
#   make trade-log args="--ticker AAPL --side BUY --qty 10 --price 231.50 --account main"
trade-log:
	@test -n "$(args)" || (echo 'usage: make trade-log args="--ticker T --side BUY --qty N --price P --account A"'; exit 1)
	$(PYTHON) -m nuri.core.trade_cli add $(args)

trade-list:
	$(PYTHON) -m nuri.core.trade_cli list $(args)

thesis-write:
	@test -n "$(file)" || (echo "usage: make thesis-write file=<thesis.yaml>"; exit 1)
	$(PYTHON) -m nuri.core.thesis_cli write "$(file)"

thesis-show:
	@test -n "$(ticker)" || (echo "usage: make thesis-show ticker=<T>"; exit 1)
	$(PYTHON) -m nuri.core.thesis_cli show "$(ticker)"

gate: ## Run trading gate engine (signal aggregation + 10-gate filter)
	$(PYTHON) -m nuri.trading.engine.gate

certify:
	$(PYTHON) -m nuri.trading.engine.certification

certify-history:
	@$(PYTHON) scripts/analysis/siege_history.py --limit $(or $(N),10)

certify-diff: ## SIEGE certification last 5 runs detail diff
	@$(PYTHON) scripts/analysis/siege_history.py --limit 5 --detail

remediate:
	$(PYTHON) -m nuri.trading.engine.remediation

strategic-rebalance: ## Strategic Asset Allocation drift advisor (STRATEGY §3.10). usage: make strategic-rebalance STRATEGY=core. rc=0 OK / rc=1 REBALANCE
	$(PYTHON) -m nuri.trading.strategy.strategic_allocation --strategy $(or $(STRATEGY),core)

track-decisions: ## Track decision outcomes + snapshot to memory (closed loop)
	$(PYTHON) -m nuri.trading.engine.decisions --track --snapshot


# ═══════════════════════════════════════════════════════════════
# SCAN / SWING TRADE
# ═══════════════════════════════════════════════════════════════
scan:
	$(PYTHON) -m nuri.trading.swing.scanner

scan-extended:
	$(PYTHON) -m nuri.trading.swing.scanner --extended

scan-kr: ## Swing scan KR market (KOSPI 200)
	$(PYTHON) -m nuri.trading.swing.scanner --market kr

swing: ## Swing rules check (entry/exit signals per config/rules.yaml ladder)
	$(PYTHON) -m nuri.trading.swing.rules

swing-check: ## Swing rules quick health check (--check flag)
	$(PYTHON) -m nuri.trading.swing.rules --check


# ═══════════════════════════════════════════════════════════════
# STRATEGY (Long/Short, Mean Reversion, Pairs)
# ═══════════════════════════════════════════════════════════════
strategy:
	$(PYTHON) -m nuri.trading.strategy.monitor

strategy-execute: ## Long/short strategy execute (paper-only per STRATEGY §7.1)
	$(PYTHON) -m nuri.trading.strategy.longshort --execute

positions: ## Position sizing computation (Kelly + per-position risk cap)
	$(PYTHON) -m nuri.trading.strategy.position

mean-reversion:
	$(PYTHON) -m nuri.trading.strategy.mean_reversion

pairs:
	$(PYTHON) -m nuri.trading.strategy.pairs


# ═══════════════════════════════════════════════════════════════
# BACKTEST
# ═══════════════════════════════════════════════════════════════
backtest:
	$(PYTHON) -m nuri.quant.validation.strategy_walkforward

backtest-ls:
	$(PYTHON) -m nuri.trading.strategy.ls_backtest

backtest-stress: ## Long/short backtest under VIX-stressed regime
	$(PYTHON) -m nuri.trading.strategy.ls_backtest --stress

backtest-rules: ## Long/short backtest with rule-driven exits (config/rules.yaml)
	$(PYTHON) -m nuri.trading.strategy.ls_backtest --rules

optimize:
	$(PYTHON) -m nuri.quant.backtest.optimizer


# ═══════════════════════════════════════════════════════════════
# REPORTS / EVIDENCE / EXTERNAL
# ═══════════════════════════════════════════════════════════════
report:
	$(PYTHON) -m nuri.alerts.daily_report

report-llm:
	$(PYTHON) -m nuri.llm.report

targets:
	$(PYTHON) -m nuri.trading.recommend.price_targets

rebalance:
	$(PYTHON) -m nuri.analysis.rebalance_advisor

evidence:
	$(PYTHON) -m nuri.analysis.evidence_charts

external:
	$(PYTHON) -m nuri.collectors.external --summary


# ═══════════════════════════════════════════════════════════════
# API + DASHBOARD (Phase F)
# ═══════════════════════════════════════════════════════════════
api:
	$(PYTHON) -m nuri.api.main

dashboard:
	cd frontend && npm run dev

start:
	bash scripts/dev/start.sh


# ═══════════════════════════════════════════════════════════════
# FULL PIPELINE (수집→분석→검증→레짐→추천→합의→증거→알림)
# ═══════════════════════════════════════════════════════════════
full-scan:
	@echo "=== Phase A: 데이터 수집 ==="
	$(PYTHON) -m nuri.collectors.stock
	$(PYTHON) -m nuri.collectors.stock_kr
	$(PYTHON) -m nuri.collectors.macro
	$(PYTHON) -m nuri.collectors.technical
	$(PYTHON) -m nuri.collectors.fear_greed
	@echo "\n=== Phase B: 포트폴리오 분석 ==="
	$(PYTHON) -m nuri.analysis.portfolio
	$(PYTHON) -m nuri.analysis.sector
	$(PYTHON) -m nuri.analysis.risk
	@echo "\n=== Phase C: 시그널 검증 ==="
	$(PYTHON) -m nuri.quant.validation.signal_backtest
	$(PYTHON) -m nuri.quant.validation.scorecard
	$(PYTHON) -m nuri.trading.engine.memory --snapshot
	@echo "\n=== Phase D: 레짐 분류 + 전략 ==="
	$(PYTHON) -m nuri.quant.regime.strategy_map
	$(PYTHON) -m nuri.quant.factors.composite
	@echo "\n=== Phase E: 추천 + 합의 ==="
	$(PYTHON) -m nuri.trading.recommend.candidates
	$(PYTHON) -m nuri.trading.agents.consensus
	$(PYTHON) -m nuri.trading.swing.scanner
	$(PYTHON) -m nuri.trading.swing.rules
	@echo "\n=== Phase F: 가격 타겟 + 리밸런스 ==="
	$(PYTHON) -m nuri.trading.recommend.price_targets
	$(PYTHON) -m nuri.analysis.rebalance_advisor
	@echo "\n=== Phase F-2: SIEGE Certification ==="
	$(PYTHON) -m nuri.trading.engine.certification
	@echo "\n=== Phase G: 증거 시각화 ==="
	$(PYTHON) -m nuri.analysis.evidence_charts
	@echo "\n=== Phase H: 알림 발송 ==="
	$(PYTHON) scripts/ops/notify_scan_result.py
	@echo "\n=== 전체 스캔 완료 ==="

quick-scan:
	$(PYTHON) -m nuri.collectors.stock
	$(PYTHON) -m nuri.collectors.stock --source freshness   # SPY/TLT/GC=F — 없으면 classify_regime() 이 계속 None (#1133)
	$(PYTHON) -m nuri.collectors.stock_kr
	$(PYTHON) -m nuri.collectors.macro
	$(PYTHON) -m nuri.collectors.fear_greed
	$(PYTHON) -m nuri.analysis.portfolio
	$(PYTHON) -m nuri.analysis.risk
	$(PYTHON) -m nuri.trading.agents.consensus
	$(PYTHON) -m nuri.trading.recommend.price_targets


# ═══════════════════════════════════════════════════════════════
# DEPLOY / BACKUP / UTILITY
# ═══════════════════════════════════════════════════════════════
pre-deploy:
	bash scripts/deploy/pre_deploy_check.sh

deploy:
	bash scripts/deploy/pre_deploy_check.sh
	bash scripts/deploy/deploy_remote.sh

deploy-mini: ## MBP → Mac mini 7단계 동기화 (git pull + config + frontend 재빌드 + scheduler plist 재설치/reload + 상주 서비스 bounce + 검증)
	bash scripts/deploy/deploy_to_mini.sh

backup:
	bash scripts/db/backup.sh

# ─── Service-grade 15-actor infra (#529 Phase 1) ─────────────────────────
snapshot: ## SQLite VACUUM INTO snapshot to data/backups/snapshot_<ts>.db
	@mkdir -p data/backups
	@TS=$$(date +%Y%m%d_%H%M%S); \
	  OUT="data/backups/snapshot_$${TS}.db"; \
	  .venv/bin/python -c "import sqlite3; from nuri.core.db import DB_PATH; c=sqlite3.connect(DB_PATH); c.execute(\"VACUUM INTO '$$OUT'\"); c.close(); print('snapshot:', '$$OUT')"

restore-drill: ## Restore latest snapshot to /tmp + integrity + schema check (DR rehearsal, prod 무영향)
	@LATEST=$$(ls -t data/backups/snapshot_*.db 2>/dev/null | head -1); \
	  if [ -z "$$LATEST" ]; then echo "no snapshot found — run 'make snapshot' first"; exit 1; fi; \
	  TMP=$$(mktemp /tmp/restore_drill_XXXXXX.db); cp "$$LATEST" "$$TMP"; \
	  .venv/bin/python -c "import sqlite3, sys; \
	  c=sqlite3.connect('$$TMP'); \
	  r=c.execute('PRAGMA integrity_check').fetchone()[0]; \
	  v=c.execute('SELECT MAX(version) FROM schema_version').fetchone()[0]; \
	  c.close(); \
	  print('restored:', '$$LATEST', '->', '$$TMP'); \
	  print('integrity:', r); \
	  print('schema_version:', v); \
	  sys.exit(0 if r=='ok' and v and v >= 27 else 1)" || (rm -f "$$TMP"; echo "❌ DR drill FAIL"; exit 1); \
	  rm -f "$$TMP"; echo "✅ DR drill OK"

rollback: ## Disable a feature flag immediately. usage: make rollback flag=<name> reason=<text>
	@test -n "$(flag)" || (echo "usage: make rollback flag=<name> reason=<text>"; exit 1)
	@test -n "$(reason)" || (echo "usage: make rollback flag=<name> reason=<text>"; exit 1)
	@.venv/bin/python -c "from nuri.core.db import set_feature_flag, is_feature_enabled; \
	  set_feature_flag('$(flag)', enabled=False, disabled_reason='$(reason)', owner='manual-rollback'); \
	  print(f'rolled back: $(flag) -> enabled={is_feature_enabled(\"$(flag)\")}')"

flag-enable: ## Enable a feature flag. usage: make flag-enable flag=<name> scope=<paper|partial|full>
	@test -n "$(flag)" || (echo "usage: make flag-enable flag=<name> scope=<paper|partial|full>"; exit 1)
	@test -n "$(scope)" || (echo "usage: make flag-enable flag=<name> scope=<paper|partial|full>"; exit 1)
	@.venv/bin/python -c "from nuri.core.db import set_feature_flag, is_feature_enabled; \
	  set_feature_flag('$(flag)', enabled=True, canary_scope='$(scope)', owner='manual-enable'); \
	  print(f'enabled: $(flag) (scope=$(scope)) -> {is_feature_enabled(\"$(flag)\")}')"

actor-status: ## Print 15-actor canonical inventory + registration status
	@.venv/bin/python -c "import nuri.agents.actors; from nuri.agents.base import REGISTRY; \
	  reg = REGISTRY.all(); missing = REGISTRY.missing(); \
	  print(f'registered: {len(reg)}/15'); \
	  print(chr(10).join(f'  - {n}' for n in sorted(reg.keys())) if reg else '  (none)'); \
	  print(f'missing ({len(missing)}/15):'); \
	  print(chr(10).join(f'  - {n}' for n in missing))"

actor-rollback: ## ReleaseRollbackManager actor: rollback flag. usage: make actor-rollback flag=<name> reason=<text>
	@test -n "$(flag)" || (echo "usage: make actor-rollback flag=<name> reason=<text>"; exit 1)
	@test -n "$(reason)" || (echo "usage: make actor-rollback flag=<name> reason=<text>"; exit 1)
	@.venv/bin/python -m nuri.agents.actors.release_rollback_manager rollback "$(flag)" --reason "$(reason)"

actor-enable: ## ReleaseRollbackManager actor: enable flag with canary. usage: make actor-enable flag=<name> scope=<paper|partial|full>
	@test -n "$(flag)" || (echo "usage: make actor-enable flag=<name> scope=<paper|partial|full>"; exit 1)
	@test -n "$(scope)" || (echo "usage: make actor-enable flag=<name> scope=<paper|partial|full>"; exit 1)
	@.venv/bin/python -m nuri.agents.actors.release_rollback_manager enable "$(flag)" --scope "$(scope)"

health-check: ## Verify single-writer invariant + DB schema + recent runs (#529 mandatory #1)
	bash scripts/ops/health_check.sh

state-verify: ## State-Replicator-DR — local DB + replicas digest verify (read-only)
	bash scripts/deploy/state_replicator.sh verify

state-push: ## (Mac mini only) snapshot + rsync push to MBP. Requires DEV2_HOST.
	bash scripts/deploy/state_replicator.sh primary

state-pull: ## (MBP only) verify latest replica file received from Mac mini.
	bash scripts/deploy/state_replicator.sh replica

agent-launchd-install: ## Install launchd plists (state-replicator + health-check, USER 자동 치환)
	@USER_NAME=$$(whoami); \
	  for plist in scripts/launchd/com.nuri-quant.state-replicator.plist scripts/launchd/com.nuri-quant.health-check.plist; do \
	    NAME=$$(basename "$$plist"); \
	    DST="$$HOME/Library/LaunchAgents/$$NAME"; \
	    sed "s|/Users/USER/|$$HOME/|g" "$$plist" > "$$DST.tmp" && mv "$$DST.tmp" "$$DST" || { echo "  ❌ install failed: $$NAME (기존 plist 유지)"; exit 1; }; \
	    launchctl unload "$$DST" 2>/dev/null || true; \
	    launchctl load "$$DST"; \
	    echo "  ✅ installed: $$NAME"; \
	  done

agent-launchd-uninstall: ## Uninstall launchd plists.
	@for plist in com.nuri-quant.state-replicator.plist com.nuri-quant.health-check.plist; do \
	    PATH_FULL="$$HOME/Library/LaunchAgents/$$plist"; \
	    if [ -f "$$PATH_FULL" ]; then \
	      launchctl unload "$$PATH_FULL" 2>/dev/null || true; \
	      rm "$$PATH_FULL"; \
	      echo "  ✅ uninstalled: $$plist"; \
	    fi; \
	  done

# ═══════════════════════════════════════════════════════════════
# Discord Bridge (#529 Phase 2 — DiscordBridge: webhook + bot)
# ═══════════════════════════════════════════════════════════════

discord-test: ## Smoke test webhook publish. usage: make discord-test channel=brief msg="hello"
	@test -n "$(channel)" || (echo "usage: make discord-test channel=<brief|ops|incidents|rollout> msg=<text>"; exit 1)
	@test -n "$(msg)" || (echo "usage: make discord-test channel=<brief|ops|incidents|rollout> msg=<text>"; exit 1)
	@.venv/bin/python -m nuri.agents.discord.publisher "$(channel)" "$(msg)"

discord-test-embed: ## Visual smoke test — publish 4 sample embeds (status ok/fail + freshness + actor) to #brief.
	@PYTHONPATH=. .venv/bin/python scripts/ops/discord_embed_smoke.py

discord-sync-commands: ## Register slash commands to guild (no long-running). Requires DISCORD_BOT_TOKEN + DISCORD_GUILD_ID.
	@.venv/bin/python -m nuri.agents.discord.bot --sync-only

discord-bot-install: ## (Mac mini) Install discord-bot launchd plist (long-running gateway).
	@NAME=com.nuri-quant.discord-bot.plist; \
	  DST="$$HOME/Library/LaunchAgents/$$NAME"; \
	  sed "s|/Users/USER/|$$HOME/|g" "scripts/launchd/$$NAME" > "$$DST.tmp" && mv "$$DST.tmp" "$$DST" || { echo "  ❌ install failed: $$NAME (기존 plist 유지)"; exit 1; }; \
	  launchctl unload "$$DST" 2>/dev/null || true; \
	  launchctl load "$$DST"; \
	  echo "  ✅ installed: $$NAME — tail data/logs/discord_bot.log"

discord-bot-uninstall: ## (Mac mini) Uninstall discord-bot launchd plist.
	@NAME=com.nuri-quant.discord-bot.plist; \
	  PATH_FULL="$$HOME/Library/LaunchAgents/$$NAME"; \
	  if [ -f "$$PATH_FULL" ]; then \
	    launchctl unload "$$PATH_FULL" 2>/dev/null || true; \
	    rm "$$PATH_FULL"; \
	    echo "  ✅ uninstalled: $$NAME"; \
	  else echo "  (not installed)"; fi

# ═══════════════════════════════════════════════════════════════
# Walk-Forward Validator (#529 Phase 2 — actor #5)
# ═══════════════════════════════════════════════════════════════

walkforward-history: ## Print recent walk-forward runs. usage: make walkforward-history [limit=N]
	@LIMIT=$${limit:-10}; \
	.venv/bin/python -c "from nuri.core.db import query; \
	  rows = query('SELECT run_id, model_id, n_folds, pit_hash, started_at, finished_at FROM walkforward_runs ORDER BY started_at DESC LIMIT ?', ($$LIMIT,)); \
	  print(f'recent {len(rows)} walk-forward runs:'); \
	  print(chr(10).join(f'  {r[\"started_at\"]:<25} {r[\"model_id\"]:<20} folds={r[\"n_folds\"]:<3} pit={r[\"pit_hash\"]} run={r[\"run_id\"][:8]}' for r in rows))"

walkforward-pit-hash: ## Compute PIT hash for a CSV. usage: make walkforward-pit-hash csv=path/to.csv [model=name]
	@test -n "$(csv)" || (echo "usage: make walkforward-pit-hash csv=path [model=name]"; exit 1)
	@.venv/bin/python -m nuri.agents.actors.walkforward_validator pit_hash --csv "$(csv)" --model-id "$${model:-cli}"

sync-start:
	bash scripts/deploy/dev_sync.sh start

sync-end:
	bash scripts/deploy/dev_sync.sh end

sync-status:
	bash scripts/deploy/dev_sync.sh status

scheduler-reload-remote: ## Reload scheduler on Mac mini (nuri/scheduler.py 변경 반영)
	@test -n "$$DEV2_HOST" || { echo "❌ DEV2_HOST 미설정. ~/.zshrc 에 export DEV2_HOST=ehbebe@Ehbebeui-Macmini.local 추가 필요"; exit 1; }
	@echo "→ Mac mini scheduler reload..."
	@bash scripts/deploy/ssh_dev2.sh "$$DEV2_HOST" '\
		launchctl unload ~/Library/LaunchAgents/com.nuri-quant.scheduler.plist 2>/dev/null; \
		sleep 2; \
		launchctl load ~/Library/LaunchAgents/com.nuri-quant.scheduler.plist && \
		echo "✅ scheduler reloaded" && \
		launchctl list | grep nuri-quant && \
		tail -5 ~/workspace/nuri-quant/data/logs/scheduler.log'

ports:
	bash scripts/ops/ports.sh

ports-kill:
	bash scripts/ops/ports.sh kill

sync-test-durations: ## [deprecated → sync-test-durations-from-ci] M5 직렬 재실측 (CI 런타임을 못 예측함, #1414)
	@echo "⚠️ M5 직렬 실측은 CI 를 못 예측한다 (#1414: 예측 spread 0.0s / 실측 89s)."
	@echo "   정본은 make sync-test-durations-from-ci. 이 타겟은 CI artifact 부재 시 폴백."
	$(PYTHON) -m pytest tests/ -q --tb=line -m "not slow and not integration" \
		--store-durations --durations-path=.test_durations
	@# full-precision float 은 privacy 스캐너의 `\b\d{7,}\b` 에 걸린다 (스크립트 docstring 참조)
	$(PYTHON) scripts/doc/round_test_durations.py .test_durations

# 로직은 전부 scripts/ci/merge_test_durations.py refresh 에 있다 — 이 레시피는
# gh 다운로드 + 스크립트 호출뿐이다 (셸에 로직을 두면 잠글 수 없다, codex P2-2).
# gh run list 는 최신 먼저 반환한다 — refresh 의 "최신 run = membership 앵커" 계약과 일치.
# Test: tests/scripts/test_merge_test_durations.py::TestMakeTargetWiring::test_recipe_delegates_to_refresh
sync-test-durations-from-ci: ## 최근 push-to-main run 3개의 shard 실측으로 .test_durations 재생성 (#1414)
	@set -e; \
	RUNS=$$(gh run list --branch main --workflow main-ci-cd.yml --status success --limit 3 --json databaseId -q '.[].databaseId'); \
	N=$$(echo "$$RUNS" | grep -c . || true); \
	if [ "$$N" -lt 2 ]; then echo "❌ 성공한 main run 이 $$N 개 — median 은 2개 이상 필요"; exit 1; fi; \
	rm -rf /tmp/ci-durations && mkdir -p /tmp/ci-durations; \
	i=0; DIRS=""; \
	for RUN in $$RUNS; do \
	    i=$$((i+1)); DIR=/tmp/ci-durations/run$$i; mkdir -p $$DIR; \
	    echo "📥 run $$RUN shard durations"; \
	    gh run download "$$RUN" --pattern 'durations-fast-*' --dir $$DIR; \
	    DIRS="$$DIRS $$DIR"; \
	done; \
	$(PYTHON) scripts/ci/merge_test_durations.py refresh \
	    --workflow .github/workflows/main-ci-cd.yml --out .test_durations $$DIRS; \
	echo "✅ 검토 후 일반 PR 로 커밋할 것 (bot push 금지)"

sync-doc-counts:
	bash scripts/doc/sync_doc_counts.sh

verify-doc-counts:
	bash scripts/verify/verify_doc_counts.sh

demo:
	bash scripts/dev/demo.sh


# ═══════════════════════════════════════════════════════════════
# CLEAN — 생성 파일 삭제
# ═══════════════════════════════════════════════════════════════
# make clean        : 빌드 산출물 + 캐시 (안전, 자주 실행 가능)
# make clean-all    : clean + 모든 .pyc/__pycache__ + 토큰 캐시
# make clean-deep   : clean-all + uv lock cache + frontend node_modules

.PHONY: clean clean-all clean-deep

clean:
	@echo "=== Cleaning generated artifacts ==="
	@rm -rf nuri_quant.egg-info nuri-quant.egg-info build/ dist/
	@rm -rf .coverage .coverage.* coverage.xml htmlcov/
	@rm -rf .pytest_cache/ .ruff_cache/ .mypy_cache/
	@rm -rf data/.bfg-reports/
	@find . -type d -name "*.egg-info" -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "=== ✓ Clean complete ==="

clean-all: clean
	@echo "=== Clean: __pycache__ + 토큰 캐시 ==="
	@find . -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
	@rm -rf config/kis/cache/token_*.json 2>/dev/null || true
	@rm -rf ~/KIS/cache/token_*.json 2>/dev/null || true  # legacy 위치도 정리
	@echo "=== ✓ Clean-all complete ==="

clean-deep: clean-all
	@echo "⚠ Deep clean: node_modules + uv cache (재설치 필요)"
	@read -p "정말 진행? (y/N) " ans && [ "$$ans" = "y" ] || exit 1
	@rm -rf frontend/node_modules/ frontend/.next/ frontend/.turbo/
	@rm -rf .venv/
	@echo "=== ✓ Deep clean complete — 'make setup' 필요 ==="

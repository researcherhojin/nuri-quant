# ═══════════════════════════════════════════════════════════════
# Nuri-Quant Makefile
# ═══════════════════════════════════════════════════════════════
# 모든 target은 .venv/bin/python 사용 — venv 활성화 불필요
# `make help` 로 카테고리별 명령 확인
# ═══════════════════════════════════════════════════════════════

PYTHON = .venv/bin/python

.PHONY: help \
        setup test test-fast test-slow lint lint-fix verify-quick verify-all verify verify-fast \
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
	@echo "  Verify:       make verify-help    (verify-quick → verify-all → verify-fast → verify, fastest first)"
	@echo "  Data:         make collect, make collect-kis, make wallstreet, make filings"
	@echo "  Universe:     make universe-sync[-us/-kr/-apply], make collect-universe[-1y], make validate-universe"
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
	@printf '  \033[1;36mNuri-Quant verify tiers\033[0m — pick the cheapest one that satisfies your need\n'
	@printf '\n'
	@printf '  \033[1m%-14s %-9s %s\033[0m\n' 'TIER' 'RUNTIME' 'WHAT IT DOES'
	@printf '  \033[2m%s\033[0m\n' '──────────────────────────────────────────────────────────────────'
	@printf '  \033[36m%-14s\033[0m \033[33m%-9s\033[0m %s\n' 'verify-quick' '~10s'  'pytest + regime classifier (no network)'
	@printf '  \033[36m%-14s\033[0m \033[33m%-9s\033[0m %s\n' 'verify-all'   '~30s'  'tests + backend + frontend + file integrity'
	@printf '  \033[36m%-14s\033[0m \033[33m%-9s\033[0m %s\n' 'verify-fast'  '~2min' 'scripts/verify.py --skip-backtest'
	@printf '  \033[36m%-14s\033[0m \033[33m%-9s\033[0m %s\n' 'verify'       '~5min' 'scripts/verify.py (full backtest run)'
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
	bash scripts/setup.sh
	$(PYTHON) scripts/migrate_db.py
	$(PYTHON) scripts/import_portfolio.py
	$(MAKE) setup-hooks

setup-hooks: ## Install repo-tracked git hooks (pre-commit auto-fix). Idempotent.
	bash scripts/install_hooks.sh


# ═══════════════════════════════════════════════════════════════
# TEST / LINT / VERIFY
# ═══════════════════════════════════════════════════════════════
test:
	$(PYTHON) -m pytest tests/ -v --cov=nuri -n auto --dist worksteal

test-fast:
	$(PYTHON) -m pytest tests/ -v --cov=nuri -n auto --dist worksteal -m "not slow"

test-slow:
	$(PYTHON) -m pytest tests/ -v -n auto --dist worksteal -m "slow"

lint:
	$(PYTHON) -m ruff check nuri/ tests/ scripts/

lint-fix:
	$(PYTHON) -m ruff check nuri/ tests/ scripts/ --fix

lint-sh: ## Shell script lint via shellcheck (brew install shellcheck)
	@command -v shellcheck >/dev/null 2>&1 || { echo "shellcheck not installed: brew install shellcheck"; exit 1; }
	shellcheck --source-path=SCRIPTDIR --external-sources scripts/*.sh

validate-portfolio: ## Verify each ticker in config/portfolio.yaml has live data (#131)
	$(PYTHON) scripts/validate_portfolio.py

universe-sync:       ## Dry-run sync (US + KR). For --market/--allow-removal flags use `python -m` (#272)
	$(PYTHON) -m nuri.collectors.universe_sync

universe-sync-us:    ## Dry-run US S&P 500 sync only
	$(PYTHON) -m nuri.collectors.universe_sync --market us

universe-sync-kr:    ## Dry-run KR KOSPI 200 sync only (requires: uv pip install finance-datareader)
	$(PYTHON) -m nuri.collectors.universe_sync --market kr

universe-sync-apply: ## Apply universe.yaml updates (additions only — manual ETFs preserved)
	$(PYTHON) -m nuri.collectors.universe_sync --apply

validate-universe:   ## Universe + agent coverage 검증 (#272 Phase 2c)
	$(PYTHON) scripts/validate_universe.py

validate-universe-cache:  ## DB만 검사 (network fetch skip — CI용)
	$(PYTHON) scripts/validate_universe.py --no-fetch

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

verify-quick:    ## ~10s pre-commit smoke test (pytest + regime, no network)
	$(PYTHON) -m pytest tests/ -q --tb=line -n auto --dist worksteal
	$(PYTHON) -c "from nuri.core.db import query; from nuri.quant.regime.classifier import classify_regime; r=classify_regime(); print(f'Quick: tests + Regime {r.regime if r else \"N/A\"}')"

verify-all:      ## ~30s pre-push (tests + backend + frontend + file integrity)
	bash scripts/verify_all.sh

verify-fast:     ## ~2min pre-deploy (verify.py without backtest)
	$(PYTHON) scripts/verify.py --skip-backtest

verify:          ## ~5min pre-release (verify.py full, includes backtest)
	$(PYTHON) scripts/verify.py


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
validate:
	$(PYTHON) scripts/gate_check.py validate
	$(PYTHON) -m nuri.quant.validation.signal_backtest
	$(PYTHON) -m nuri.quant.validation.superinvestor_backtest
	$(PYTHON) -m nuri.quant.validation.analyst_backtest
	$(PYTHON) -m nuri.quant.validation.scorecard
	$(PYTHON) -m nuri.trading.engine.memory --snapshot


# ═══════════════════════════════════════════════════════════════
# REGIME CLASSIFICATION (Phase D)
# ═══════════════════════════════════════════════════════════════
regime:
	$(PYTHON) scripts/gate_check.py regime
	$(PYTHON) -m nuri.quant.regime.strategy_map


# ═══════════════════════════════════════════════════════════════
# RECOMMENDATIONS + AGENTS (Phase E)
# ═══════════════════════════════════════════════════════════════
recommend:
	$(PYTHON) scripts/gate_check.py recommend
	$(PYTHON) -m nuri.trading.recommend.candidates
	$(PYTHON) -m nuri.trading.recommend.tracker --save

consensus:
	$(PYTHON) -m nuri.trading.agents.consensus

# Holdings post-entry technical-divergence monitor.
# Daily 07:10 KST via APScheduler (after consensus 07:05). CLI form for ad-hoc / dry-run.
holdings-monitor:
	$(PYTHON) -m nuri.trading.recommend.holdings_monitor

holdings-monitor-dry:
	$(PYTHON) -m nuri.trading.recommend.holdings_monitor --dry-run

# Dual-LLM consult helper — codex + Qwen3.5 in parallel, archive both verdicts
# to data/llm_consults/ (gitignored). Use for design-ambiguity decisions.
# Usage: make llm-consult slug=<kebab> prompt=<file>
llm-consult:
	@test -n "$(slug)" || (echo "usage: make llm-consult slug=<kebab> prompt=<file>"; exit 1)
	@test -n "$(prompt)" || (echo "usage: make llm-consult slug=<kebab> prompt=<file>"; exit 1)
	$(PYTHON) scripts/llm_consult.py --slug "$(slug)" --prompt-file "$(prompt)"

# Earnings preview (Issue #509) — consensus EPS/revenue + ATM straddle implied move.
# yfinance-based, on-demand. Future: 위스퍼 (Estimize/StockTwits) Phase 2.
# Usage:
#   make earnings-preview ticker=MSFT
#   make earnings-preview watchlist=MSFT,META,AMZN,GOOGL,QCOM
earnings-preview:
	@test -n "$(ticker)$(watchlist)" || (echo "usage: make earnings-preview ticker=<T> | watchlist=<T1,T2,...>"; exit 1)
	$(PYTHON) -m nuri.collectors.earnings_preview $(if $(ticker),--ticker "$(ticker)") $(if $(watchlist),--watchlist "$(watchlist)")

gate:
	$(PYTHON) -m nuri.trading.engine.gate

certify:
	$(PYTHON) -m nuri.trading.engine.certification

certify-history:
	@$(PYTHON) scripts/siege_history.py --limit $(or $(N),10)

certify-diff:
	@$(PYTHON) scripts/siege_history.py --limit 5 --detail

remediate:
	$(PYTHON) -m nuri.trading.engine.remediation

track-decisions:
	$(PYTHON) -m nuri.trading.engine.decisions --track --snapshot


# ═══════════════════════════════════════════════════════════════
# SCAN / SWING TRADE
# ═══════════════════════════════════════════════════════════════
scan:
	$(PYTHON) -m nuri.trading.swing.scanner

scan-extended:
	$(PYTHON) -m nuri.trading.swing.scanner --extended

scan-kr:
	$(PYTHON) -m nuri.trading.swing.scanner --market kr

swing:
	$(PYTHON) -m nuri.trading.swing.rules

swing-check:
	$(PYTHON) -m nuri.trading.swing.rules --check


# ═══════════════════════════════════════════════════════════════
# STRATEGY (Long/Short, Mean Reversion, Pairs)
# ═══════════════════════════════════════════════════════════════
strategy:
	$(PYTHON) -m nuri.trading.strategy.monitor

strategy-execute:
	$(PYTHON) -m nuri.trading.strategy.longshort --execute

positions:
	$(PYTHON) -m nuri.trading.strategy.position

mean-reversion:
	$(PYTHON) -m nuri.trading.strategy.mean_reversion

pairs:
	$(PYTHON) -m nuri.trading.strategy.pairs


# ═══════════════════════════════════════════════════════════════
# BACKTEST
# ═══════════════════════════════════════════════════════════════
backtest:
	$(PYTHON) -m nuri.quant.backtest.engine

backtest-ls:
	$(PYTHON) -m nuri.trading.strategy.ls_backtest

backtest-stress:
	$(PYTHON) -m nuri.trading.strategy.ls_backtest --stress

backtest-rules:
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
	bash scripts/start.sh


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
	$(PYTHON) scripts/notify_scan_result.py
	@echo "\n=== 전체 스캔 완료 ==="

quick-scan:
	$(PYTHON) -m nuri.collectors.stock
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
	bash scripts/pre-deploy-check.sh

deploy:
	bash scripts/pre-deploy-check.sh
	bash scripts/deploy.sh

deploy-mini: ## MBP → Mac mini 전체 동기화 (git pull + config + scheduler reload)
	bash scripts/deploy_mini.sh

backup:
	bash scripts/backup.sh

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
	bash scripts/health_check.sh

state-verify: ## State-Replicator-DR — local DB + replicas digest verify (read-only)
	bash scripts/state_replicator.sh verify

state-push: ## (Mac mini only) snapshot + rsync push to MBP. Requires DEV2_HOST.
	bash scripts/state_replicator.sh primary

state-pull: ## (MBP only) verify latest replica file received from Mac mini.
	bash scripts/state_replicator.sh replica

agent-launchd-install: ## Install launchd plists (state-replicator + health-check, USER 자동 치환)
	@USER_NAME=$$(whoami); \
	  for plist in scripts/launchd/com.nuri-quant.state-replicator.plist scripts/launchd/com.nuri-quant.health-check.plist; do \
	    NAME=$$(basename "$$plist"); \
	    sed "s|/Users/USER/|$$HOME/|g" "$$plist" > "$$HOME/Library/LaunchAgents/$$NAME"; \
	    launchctl unload "$$HOME/Library/LaunchAgents/$$NAME" 2>/dev/null || true; \
	    launchctl load "$$HOME/Library/LaunchAgents/$$NAME"; \
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
	@PYTHONPATH=. .venv/bin/python scripts/discord_embed_smoke.py

discord-sync-commands: ## Register slash commands to guild (no long-running). Requires DISCORD_BOT_TOKEN + DISCORD_GUILD_ID.
	@.venv/bin/python -m nuri.agents.discord.bot --sync-only

discord-bot-install: ## (Mac mini) Install discord-bot launchd plist (long-running gateway).
	@NAME=com.nuri-quant.discord-bot.plist; \
	  sed "s|/Users/USER/|$$HOME/|g" "scripts/launchd/$$NAME" > "$$HOME/Library/LaunchAgents/$$NAME"; \
	  launchctl unload "$$HOME/Library/LaunchAgents/$$NAME" 2>/dev/null || true; \
	  launchctl load "$$HOME/Library/LaunchAgents/$$NAME"; \
	  echo "  ✅ installed: $$NAME — tail data/logs/discord_bot.log"

discord-bot-uninstall: ## (Mac mini) Uninstall discord-bot launchd plist.
	@NAME=com.nuri-quant.discord-bot.plist; \
	  PATH_FULL="$$HOME/Library/LaunchAgents/$$NAME"; \
	  if [ -f "$$PATH_FULL" ]; then \
	    launchctl unload "$$PATH_FULL" 2>/dev/null || true; \
	    rm "$$PATH_FULL"; \
	    echo "  ✅ uninstalled: $$NAME"; \
	  else echo "  (not installed)"; fi

sync-start:
	bash scripts/dev_sync.sh start

sync-end:
	bash scripts/dev_sync.sh end

sync-status:
	bash scripts/dev_sync.sh status

scheduler-reload-remote: ## Reload scheduler on Mac mini (nuri/scheduler.py 변경 반영)
	@test -n "$$DEV2_HOST" || { echo "❌ DEV2_HOST 미설정. ~/.zshrc 에 export DEV2_HOST=ehbebe@Ehbebeui-Macmini.local 추가 필요"; exit 1; }
	@echo "→ Mac mini scheduler reload..."
	@ssh "$$DEV2_HOST" '\
		launchctl unload ~/Library/LaunchAgents/com.nuri-quant.scheduler.plist 2>/dev/null; \
		sleep 2; \
		launchctl load ~/Library/LaunchAgents/com.nuri-quant.scheduler.plist && \
		echo "✅ scheduler reloaded" && \
		launchctl list | grep nuri-quant && \
		tail -5 ~/workspace/nuri-quant/data/logs/scheduler.log'

ports:
	bash scripts/ports.sh

ports-kill:
	bash scripts/ports.sh kill

sync-doc-counts:
	bash scripts/sync_doc_counts.sh

verify-doc-counts:
	bash scripts/verify_doc_counts.sh

# Back-compat alias — forwards to sync-doc-counts. Scheduled for removal after
# external refs (if any) migrate.
update-counts: sync-doc-counts

demo:
	bash scripts/demo.sh


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

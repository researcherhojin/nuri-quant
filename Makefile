# ═══════════════════════════════════════════════════════════════
# Nuri-Quant Makefile
# ═══════════════════════════════════════════════════════════════
# 모든 target은 .venv/bin/python 사용 — venv 활성화 불필요
# `make help` 로 카테고리별 명령 확인
# ═══════════════════════════════════════════════════════════════

PYTHON = .venv/bin/python

.PHONY: help \
        setup test lint lint-fix verify-quick verify-all verify verify-fast \
        collect collect-kis collect-kis-check wallstreet filings \
        analyze report report-llm \
        validate regime recommend gate consensus certify remediate \
        scan swing swing-check strategy strategy-execute positions \
        backtest backtest-ls backtest-stress backtest-rules backtest-event \
        optimize mean-reversion pairs \
        targets rebalance evidence external \
        event-list event-trades \
        api dashboard start \
        full-scan quick-scan \
        deploy pre-deploy backup ports ports-kill update-counts demo


# ═══════════════════════════════════════════════════════════════
# HELP
# ═══════════════════════════════════════════════════════════════
help:
	@echo "Nuri-Quant Makefile — 카테고리별 주요 명령"
	@echo ""
	@echo "  Setup:        make setup"
	@echo "  Test/Lint:    make test, make lint, make lint-fix"
	@echo "  Verify:       make verify-help    (verify-quick → verify-all → verify-fast → verify, fastest first)"
	@echo "  Data:         make collect, make collect-kis, make wallstreet, make filings"
	@echo "  Analysis:     make analyze, make consensus, make scan, make backtest"
	@echo "  Pipeline:     make full-scan, make quick-scan"
	@echo "  Trading:      make targets, make rebalance, make recommend, make certify, make remediate"
	@echo "  Strategy:     make strategy, make backtest-ls, make optimize, make mean-reversion, make pairs"
	@echo "  Events:       make backtest-event, make event-list, make event-trades"
	@echo "  Reports:      make report, make report-llm, make evidence, make external"
	@echo "  Server:       make api, make dashboard, make start"
	@echo "  Deploy:       make pre-deploy, make deploy, make backup"
	@echo "  Utility:      make ports, make ports-kill, make update-counts, make demo"

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


# ═══════════════════════════════════════════════════════════════
# TEST / LINT / VERIFY
# ═══════════════════════════════════════════════════════════════
test:
	$(PYTHON) -m pytest tests/ -v --cov=nuri -n auto --dist worksteal

lint:
	$(PYTHON) -m ruff check nuri/ tests/ scripts/

lint-fix:
	$(PYTHON) -m ruff check nuri/ tests/ scripts/ --fix

validate-portfolio: ## Verify each ticker in config/portfolio.yaml has live data (#131)
	$(PYTHON) scripts/validate_portfolio.py

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

gate:
	$(PYTHON) -m nuri.trading.engine.gate

certify:
	$(PYTHON) -m nuri.trading.engine.certification

remediate:
	$(PYTHON) -m nuri.trading.engine.remediation


# ═══════════════════════════════════════════════════════════════
# SCAN / SWING TRADE
# ═══════════════════════════════════════════════════════════════
scan:
	$(PYTHON) -m nuri.trading.swing.scanner

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

backtest-event:
	$(PYTHON) -m nuri.quant.event_study.ceasefire --instrument SPY
	$(PYTHON) -m nuri.quant.event_study.ceasefire --instrument SOXX --leverage 3.0

optimize:
	$(PYTHON) -m nuri.quant.backtest.optimizer


# ═══════════════════════════════════════════════════════════════
# EVENT-DRIVEN (휴전, Fed 피봇)
# ═══════════════════════════════════════════════════════════════
event-list:
	$(PYTHON) -m nuri.trading.strategy.event_driven list-events
	$(PYTHON) -m nuri.trading.strategy.event_driven list-trades

event-trades:
	$(PYTHON) -m nuri.trading.strategy.event_driven list-trades


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

backup:
	bash scripts/backup.sh

ports:
	bash scripts/ports.sh

ports-kill:
	bash scripts/ports.sh kill

update-counts:
	bash scripts/update-test-counts.sh

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
	@rm -rf ~/KIS/cache/token_*.json 2>/dev/null || true
	@echo "=== ✓ Clean-all complete ==="

clean-deep: clean-all
	@echo "⚠ Deep clean: node_modules + uv cache (재설치 필요)"
	@read -p "정말 진행? (y/N) " ans && [ "$$ans" = "y" ] || exit 1
	@rm -rf frontend/node_modules/ frontend/.next/ frontend/.turbo/
	@rm -rf .venv/
	@echo "=== ✓ Deep clean complete — 'make setup' 필요 ==="

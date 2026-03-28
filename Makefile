.PHONY: setup test collect analyze report deploy backup backtest verify verify-fast validate regime recommend \
       gate consensus scan swing swing-check strategy strategy-execute positions wallstreet filings \
       backtest-ls backtest-stress optimize mean-reversion pairs api dashboard start lint lint-fix \
       verify-quick verify-all demo pre-deploy ports ports-kill update-counts \
       full-scan quick-scan targets rebalance evidence external report-llm

PYTHON = .venv/bin/python

# ── 초기 설정 ──
setup:
	bash scripts/setup.sh
	$(PYTHON) scripts/migrate_db.py
	$(PYTHON) scripts/import_portfolio.py

# ── 데이터 수집 ──
collect:
	$(PYTHON) -m nuri.collectors.stock
	$(PYTHON) -m nuri.collectors.stock_kr
	$(PYTHON) -m nuri.collectors.macro
	$(PYTHON) -m nuri.collectors.technical
	$(PYTHON) -m nuri.collectors.fear_greed
	$(PYTHON) -m nuri.collectors.ark

# ── 분석 실행 ──
analyze:
	$(PYTHON) -m nuri.analysis.portfolio
	$(PYTHON) -m nuri.analysis.sector
	$(PYTHON) -m nuri.analysis.risk

# ── 일일 리포트 ──
report:
	$(PYTHON) -m nuri.alerts.daily_report

# ── Lint ──
lint:
	$(PYTHON) -m ruff check nuri/ tests/

lint-fix:
	$(PYTHON) -m ruff check nuri/ tests/ --fix

# ── 테스트 ──
test:
	$(PYTHON) -m pytest tests/ -v --cov=nuri

# ── 백테스트 ──
backtest:
	$(PYTHON) -m nuri.quant.backtest.engine

# ── 기능 검증 (전체 Phase A~E + 결과 저장) ──
verify:
	$(PYTHON) scripts/verify.py

verify-fast:
	$(PYTHON) scripts/verify.py --skip-backtest

# ── Phase C: 시그널/슈퍼투자자/애널리스트 검증 (Gate 검증 후 실행) ──
validate:
	$(PYTHON) scripts/gate_check.py validate
	$(PYTHON) -m nuri.quant.validation.signal_backtest
	$(PYTHON) -m nuri.quant.validation.superinvestor_backtest
	$(PYTHON) -m nuri.quant.validation.analyst_backtest
	$(PYTHON) -m nuri.quant.validation.scorecard
	$(PYTHON) -m nuri.trading.engine.memory --snapshot

# ── Phase D: 시장 레짐 분류 (Gate 검증 후 실행) ──
regime:
	$(PYTHON) scripts/gate_check.py regime
	$(PYTHON) -m nuri.quant.regime.strategy_map

# ── Phase E: 매매 추천 + 추적 (Gate 검증 후 실행) ──
recommend:
	$(PYTHON) scripts/gate_check.py recommend
	$(PYTHON) -m nuri.trading.recommend.candidates
	$(PYTHON) -m nuri.trading.recommend.tracker --save

# ── Gate 상태 확인 ──
gate:
	$(PYTHON) -m nuri.trading.engine.gate

# ── Multi-Agent Consensus ──
consensus:
	$(PYTHON) -m nuri.trading.agents.consensus

# ── Swing Trade Scanner ──
scan:
	$(PYTHON) -m nuri.trading.swing.scanner

swing:
	$(PYTHON) -m nuri.trading.swing.rules

swing-check:
	$(PYTHON) -m nuri.trading.swing.rules --check

# ── Long/Short Strategy ──
strategy:
	$(PYTHON) -m nuri.trading.strategy.monitor

strategy-execute:
	$(PYTHON) -m nuri.trading.strategy.longshort --execute

positions:
	$(PYTHON) -m nuri.trading.strategy.position

# ── Wall Street 데이터 수집 ──
wallstreet:
	$(PYTHON) -m nuri.collectors.wallstreet

filings:
	$(PYTHON) -m nuri.collectors.filings

# ── Strategy Backtest ──
backtest-ls:
	$(PYTHON) -m nuri.trading.strategy.ls_backtest

backtest-stress:
	$(PYTHON) -m nuri.trading.strategy.ls_backtest --stress

# ── 파라미터 최적화 + 다중 전략 ──
optimize:
	$(PYTHON) -m nuri.quant.backtest.optimizer

mean-reversion:
	$(PYTHON) -m nuri.trading.strategy.mean_reversion

pairs:
	$(PYTHON) -m nuri.trading.strategy.pairs

# ── Phase F: API + Dashboard ──
api:
	$(PYTHON) -m nuri.api.main

dashboard:
	cd frontend && npm run dev

start:
	bash scripts/start.sh

# ── 빠른 검증 (~10초, 네트워크 호출 없음) ──
verify-quick:
	$(PYTHON) -m pytest tests/ -q --tb=line
	$(PYTHON) -c "from nuri.core.db import query; from nuri.quant.regime.classifier import classify_regime; r=classify_regime(); print(f'Quick: tests + Regime {r.regime if r else \"N/A\"}')"

# ── 전체 검증 (커밋 전 필수) ──
verify-all:
	bash scripts/verify_all.sh

# ── 풀 데모 (전체 파이프라인 한 바퀴) ──
demo:
	bash scripts/demo.sh

# ── 배포 ──
pre-deploy:
	bash scripts/pre-deploy-check.sh

deploy:
	bash scripts/pre-deploy-check.sh
	bash scripts/deploy.sh

# ── 유틸리티 ──
ports:
	bash scripts/ports.sh

ports-kill:
	bash scripts/ports.sh kill

update-counts:
	bash scripts/update-test-counts.sh

# ── 종합 스캔 (전체 파이프라인: 수집→분석→검증→레짐→추천→합의→증거) ──
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
	@echo "\n=== Phase G: 증거 시각화 ==="
	$(PYTHON) -m nuri.analysis.evidence_charts
	@echo "\n=== Phase H: 알림 발송 ==="
	$(PYTHON) scripts/notify_scan_result.py
	@echo "\n=== 전체 스캔 완료 ==="

# ── 빠른 스캔 (수집→분석→합의만, ~2분) ──
quick-scan:
	$(PYTHON) -m nuri.collectors.stock
	$(PYTHON) -m nuri.collectors.stock_kr
	$(PYTHON) -m nuri.collectors.macro
	$(PYTHON) -m nuri.collectors.fear_greed
	$(PYTHON) -m nuri.analysis.portfolio
	$(PYTHON) -m nuri.analysis.risk
	$(PYTHON) -m nuri.trading.agents.consensus
	$(PYTHON) -m nuri.trading.recommend.price_targets

# ── 가격 타겟 (전 종목 매수가/손절가/익절가) ──
targets:
	$(PYTHON) -m nuri.trading.recommend.price_targets

# ── 리밸런스 어드바이저 (규칙 위반 감지 + 매도 수량 제시) ──
rebalance:
	$(PYTHON) -m nuri.analysis.rebalance_advisor

# ── LLM 리포트 (Ollama) ──
report-llm:
	$(PYTHON) -m nuri.llm.report

# ── 외부 데이터 요약 ──
external:
	$(PYTHON) -m nuri.collectors.external --summary

# ── 증거 시각화 (Plotly 차트 생성) ──
evidence:
	$(PYTHON) -m nuri.analysis.evidence_charts

# ── DB 백업 ──
backup:
	bash scripts/backup.sh

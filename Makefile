.PHONY: setup test collect analyze report deploy backup benchmark backtest verify validate regime recommend api dashboard

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

# ── 테스트 ──
test:
	$(PYTHON) -m pytest tests/ -v --cov=nuri

# ── LLM 벤치마크 (Phase 2) ──
benchmark:
	$(PYTHON) -m nuri.llm.benchmark --models all

# ── 백테스트 (Phase 3) ──
backtest:
	$(PYTHON) -m nuri.trading.backtest.engine

# ── 기능 검증 (전체 Phase A~E + 결과 저장) ──
verify:
	$(PYTHON) scripts/verify.py

verify-fast:
	$(PYTHON) scripts/verify.py --skip-backtest

# ── Phase C: 시그널/슈퍼투자자/애널리스트 검증 (Gate 검증 후 실행) ──
validate:
	$(PYTHON) scripts/gate_check.py validate
	$(PYTHON) -m nuri.analysis.validation.signal_backtest
	$(PYTHON) -m nuri.analysis.validation.superinvestor_backtest
	$(PYTHON) -m nuri.analysis.validation.analyst_backtest
	$(PYTHON) -m nuri.analysis.validation.scorecard
	$(PYTHON) -m nuri.engine.memory --snapshot

# ── Phase D: 시장 레짐 분류 (Gate 검증 후 실행) ──
regime:
	$(PYTHON) scripts/gate_check.py regime
	$(PYTHON) -m nuri.analysis.regime.strategy_map

# ── Phase E: 매매 추천 + 추적 (Gate 검증 후 실행) ──
recommend:
	$(PYTHON) scripts/gate_check.py recommend
	$(PYTHON) -m nuri.trading.recommend.candidates
	$(PYTHON) -m nuri.trading.recommend.tracker --save

# ── Gate 상태 확인 ──
gate:
	$(PYTHON) -m nuri.engine.gate

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
	$(PYTHON) -m nuri.trading.strategy.backtest

backtest-stress:
	$(PYTHON) -m nuri.trading.strategy.backtest --stress

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
	$(PYTHON) -c "from nuri.core.db import query; from nuri.analysis.regime.classifier import classify_regime; r=classify_regime(); print(f'Quick: 105 tests + Regime {r.regime if r else \"N/A\"}')"

# ── 전체 검증 (커밋 전 필수) ──
verify-all:
	bash scripts/verify_all.sh

# ── 풀 데모 (전체 파이프라인 한 바퀴) ──
demo:
	bash scripts/demo.sh

# ── 맥미니 배포 ──
deploy:
	bash scripts/deploy.sh

# ── DB 백업 ──
backup:
	bash scripts/backup.sh

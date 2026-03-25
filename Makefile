.PHONY: setup test collect analyze report deploy backup benchmark backtest

PYTHON = .venv/bin/python

# ── 초기 설정 ──
setup:
	bash scripts/setup.sh
	$(PYTHON) scripts/migrate_db.py
	$(PYTHON) scripts/import_portfolio.py

# ── 데이터 수집 ──
collect:
	$(PYTHON) -m iris.collectors.stock
	$(PYTHON) -m iris.collectors.stock_kr
	$(PYTHON) -m iris.collectors.macro
	$(PYTHON) -m iris.collectors.technical
	$(PYTHON) -m iris.collectors.fear_greed
	$(PYTHON) -m iris.collectors.ark

# ── 분석 실행 ──
analyze:
	$(PYTHON) -m iris.analysis.portfolio
	$(PYTHON) -m iris.analysis.sector
	$(PYTHON) -m iris.analysis.risk

# ── 일일 리포트 ──
report:
	$(PYTHON) -m iris.alerts.daily_report

# ── 테스트 ──
test:
	$(PYTHON) -m pytest tests/ -v --cov=iris

# ── LLM 벤치마크 (Phase 2) ──
benchmark:
	$(PYTHON) -m iris.llm.benchmark --models all

# ── 백테스트 (Phase 3) ──
backtest:
	$(PYTHON) -m iris.quant.backtest.engine

# ── 맥미니 배포 ──
deploy:
	bash scripts/deploy.sh

# ── DB 백업 ──
backup:
	bash scripts/backup.sh

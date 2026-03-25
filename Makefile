.PHONY: setup test collect analyze report deploy backup benchmark backtest verify

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
	$(PYTHON) -m nuri.quant.backtest.engine

# ── 기능 검증 (전체 분석 실행 + 결과 저장) ──
verify:
	$(PYTHON) scripts/verify.py

verify-fast:
	$(PYTHON) scripts/verify.py --skip-backtest

# ── 맥미니 배포 ──
deploy:
	bash scripts/deploy.sh

# ── DB 백업 ──
backup:
	bash scripts/backup.sh

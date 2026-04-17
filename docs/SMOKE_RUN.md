# SMOKE_RUN.md — Fresh Clone Setup Smoke Flow

Nuri-Quant 첫 설치 / 재설치 / 신규 기여자 온보딩 용. **PR CI 가 확인하지 않는 end-to-end 시나리오**를 수동으로 검증하기 위한 절차. #272 Phase 5 (2026-04-15) 기준.

> 📌 **언제 돌리나**: fresh clone, 환경 초기화 후, 중대 dependency 업그레이드 후, 분기별 헬스 체크. **PR 마다 X** — 네트워크 20-30분 소요, 비결정적 외부 API 영향 받음.

---

## 1. Prerequisites

| 항목 | 필요 버전 | 설치 방법 |
|------|----------|---------|
| Python | 3.12 | `brew install python@3.12` |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| TA-Lib (C lib) | latest | `brew install ta-lib` |
| Node.js | 22+ | `brew install node@22` |
| Git | any | 이미 있을 것 |

**예상 runtime (M2 Pro 기준)**:
- `make setup`: 2-3분 (deps install + DB init)
- `make universe-sync-us`: 10-20초 (Wikipedia scrape)
- `make universe-sync-kr`: 10-30초 (FDR/KRX fetch, 네트워크 불안정 시 skip)
- `make collect-universe`: **15-20분** (yfinance 746 tickers parallel + pykrx 203 sequential)
- `make validate-universe`: 3-5초 (DB-only)

**총 예상**: 20-25분 (네트워크 + API 상태 의존).

---

## 2. Fresh Clone Commands (정확한 순서)

```bash
# 0. Clone + branch
git clone https://github.com/researcherhojin/nuri-quant.git
cd nuri-quant
git checkout main

# 1. 환경 + DB 초기화
make setup                       # venv + deps + DB schema + portfolio import
cd frontend && npm ci && cd ..   # frontend deps

# 2. Universe 동기화 (선택 — 기본 universe.yaml 이면 skip 가능)
make universe-sync-us            # dry-run: Wikipedia S&P 500 diff 확인
make universe-sync-kr            # dry-run: KOSPI 200 diff (FDR 필요 시 `uv pip install finance-datareader`)
make universe-sync-apply         # 실제 universe.yaml 에 적용 (additions only)

# 3. 데이터 수집
make collect-universe            # US + KR prices/fundamentals/wallstreet/estimates (~15분)
# 선택: 기술분석용 1y OHLCV 확보 (P1 A 이후 필수)
make collect-universe-1y         # 1년치 가격 히스토리 backfill (~10-15분)

# 4. 검증
.venv/bin/python scripts/validate_universe.py             # 5-check coverage gate
.venv/bin/python scripts/validate_universe.py --no-fetch  # CI 용 (네트워크 skip)
make validate-portfolio                                   # portfolio.yaml 각 ticker DB 검증

# 5. 서버 기동 (시각 확인)
make start                       # API :8001 + Dashboard :3000
# 브라우저에서 http://localhost:3000 열기
```

---

## 3. Expected Success Signals

각 스텝 완료 후 나와야 할 signal. 이게 안 나오면 **섹션 4 triage** 로 이동.

| 스텝 | 성공 신호 | 실패 신호 |
|------|----------|----------|
| `make setup` | `=== Sync complete: -N +M ===` (`scripts/import_portfolio.py` 종료 메시지) | ModuleNotFoundError / sqlite 에러 |
| `make universe-sync-us` | `fetched 500+ tickers from Wikipedia` + diff summary | Wikipedia 403 / HTTP error |
| `make universe-sync-kr` | `fetched 200 tickers` 또는 `KR sync skipped (FDR missing)` | 비정상 traceback |
| `make collect-universe` | `prices [universe]: 100%\|` tqdm 완료 + `수집 결과: ... 성공 / ... 실패` summary | silent hang > 5분 / ERROR 500줄 |
| `make collect-universe-1y` | prices table median rows ≥ 200 (`SELECT COUNT(*) FROM prices WHERE ticker='SPY'`) | rows < 50 |
| `validate_universe.py` | `Result: 5/5 PASS → exit 0` | `4/5 PASS` 또는 `exit 1` |

**5/5 PASS 기준값** (2026-04-15 측정):
- prices ≥ 95% (실측 99%)
- fundamentals ≥ 80% (실측 99%)
- analyst_ratings ≥ 70% (실측 97%)
- insider_trades ≥ 50% (실측 97%)
- superinvestors ≥ 80% (실측 97%)

---

## 4. Failure Triage

| 증상 | 가능한 원인 | 해결 |
|------|----------|------|
| `FileNotFoundError: config/universe.yaml 가 없습니다` | `make setup` 스킵 | `git checkout main -- config/universe.yaml` |
| `YAML 파싱 실패` | 수동 편집 오류 | `git checkout main -- config/universe.yaml` |
| Wikipedia 403 / timeout | User-Agent blocked | 10분 기다린 후 재시도, 아니면 `--market kr` 만 실행 |
| pykrx 정지 / 60 tickers 이후 hang | KR rate-limit | 정상. sequential + 0.1s sleep 이미 적용됨. 15-30분 기다리기 |
| yfinance 대량 404 | ticker delisting 정상 | 최대 5-10% 실패 허용. summary 에 표시됨 |
| `validate_universe.py` 4/5 PASS | 특정 테이블 coverage 미달 | 해당 collector 재실행 (`make wallstreet` 등) |
| Dashboard 500 error | API 서버 미기동 | `make api` 독립 기동 + 로그 확인 |
| `make collect-universe-1y` 중 OOM | parallel worker 과다 | 현재 10-thread 기본 — stock.py `max_workers=10` 조정 가능 |

**디버그 시**: `data/reports/YYYY-MM-DD/` 의 최신 리포트 확인. `scripts/validate_universe.py --format=markdown` 상세 테이블 출력 (지원 플래그는 `--no-fetch`, `--format`).

---

## 5. Cleanup / Reset (rerun 준비)

```bash
# Level 1: DB 만 리셋 (빠름)
rm data/portfolio.db
make setup                       # schema + portfolio 재import

# Level 2: build 아티팩트 포함
make clean-all                   # __pycache__ + build + token cache

# Level 3: 완전 초기화 (deps 재설치 필요)
make clean-deep                  # node_modules + uv cache 포함. interactive 확인
# 이후: make setup && cd frontend && npm ci
```

**주의**: `config/portfolio.yaml` 은 gitignored (사용자 실 데이터). 삭제 전 백업.

---

## 참고 — Phase 5 QA Scope

이 문서는 **manual smoke** 용. PR CI 에 포함된 negative tests:

- `tests/collectors/test_universe_sync.py::TestPhase5NegativeGuardrails` — missing/malformed/empty `universe.yaml` graceful error
- `tests/integration/test_universe_sync_real.py` — real network integration (marker `integration`, `make test-integration` 로만 실행)

**out-of-scope** (별도 PR 후보):
- API key 기반 collector 테스트 (현 path 는 모두 keyless)
- 분기별 자동화 live smoke CI job
- Dependency drift 감지

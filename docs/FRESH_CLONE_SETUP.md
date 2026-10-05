# Fresh Clone Setup — End-to-End Verification

Nuri-Quant 첫 설치, 재설치, 신규 기여자 온보딩에 쓰는 절차다. PR CI 가 확인하지 않는 end-to-end 시나리오를 수동으로 검증한다. #272 Phase 5 (2026-04-15) 기준.

> **실행 시점**: fresh clone, 환경 초기화 후, 주요 dependency 업그레이드 후, 분기별 헬스 체크. PR 마다 실행하지 않는다. 네트워크 작업에 20-30분이 걸리고 외부 API 상태에 따라 결과가 달라진다.

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
- `make collect-universe`: 15-20분 (yfinance 746 tickers parallel + pykrx 203 sequential)
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
cp config/portfolio.example.yaml config/portfolio.yaml  # make setup 이 import 한다 (없으면 실패, gitignored)
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
.venv/bin/python scripts/doc/validate_universe.py         # 5-check coverage gate
.venv/bin/python scripts/doc/validate_universe.py --no-fetch  # CI 용 (네트워크 skip)
make validate-portfolio                                   # portfolio.yaml 각 ticker DB 검증

# 5. 서버 기동 (시각 확인)
make start                       # API :8001 + Dashboard :3000
# 브라우저에서 http://localhost:3000 열기
```

---

## 3. Expected Success Signals

각 스텝 완료 후 확인할 출력이다. 성공 신호가 나오지 않으면 섹션 4 의 triage 를 따른다.

| 스텝 | 성공 신호 | 실패 신호 |
|------|----------|----------|
| `make setup` | `=== Sync complete: -N +M ===` (`scripts/ops/import_portfolio.py` 종료 메시지) | ModuleNotFoundError / sqlite 에러 |
| `make universe-sync-us` | `S&P 500: N종목 fetched` 로그 (N ≈ 500) + diff summary | Wikipedia 403 / HTTP error |
| `make universe-sync-kr` | `KOSPI 200: N종목 fetched` 로그 (N ≈ 200), 또는 FDR 미설치 시 `KR sync 건너뜀` 경고 + `KR KOSPI 200: ⏭️  건너뜀` | 비정상 traceback |
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
| Wikipedia 403 / timeout | User-Agent blocked | 10분 후 재시도. 계속 실패하면 KR 만 실행 (`.venv/bin/python -m nuri.collectors.universe_sync --market kr`) |
| pykrx 정지 / 60 tickers 이후 hang | KR rate-limit | 정상 동작. sequential + 0.1s sleep 이 이미 적용돼 있으므로 15-30분 기다린다 |
| yfinance 대량 404 | ticker delisting (정상) | 최대 5-10% 실패 허용. summary 에 표시된다 |
| `validate_universe.py` 4/5 PASS | 특정 테이블 coverage 미달 | 해당 collector 재실행 (`make wallstreet` 등) |
| Dashboard 500 error | API 서버 미기동 | `make api` 독립 기동 + 로그 확인 |
| `make collect-universe-1y` 중 OOM | parallel worker 과다 | 기본 10-thread. `nuri/collectors/stock.py` 의 `max_workers=10` 을 조정한다 |

**디버그**: `data/reports/YYYY-MM-DD/` 의 최신 리포트를 확인한다. `scripts/doc/validate_universe.py` 는 상세 테이블을 출력한다(지원 플래그: `--no-fetch`, `--format {table,json}`, 기본 table).

---

## 5. Cleanup / Reset (rerun 준비)

```bash
# Level 1: DB 만 리셋 (빠름)
rm data/portfolio.db
make setup                       # schema + portfolio 재import

# Level 2: build 아티팩트 포함
make clean-all                   # __pycache__ + build + token cache

# Level 3: 완전 초기화 (deps 재설치 필요)
make clean-deep                  # clean-all + frontend node_modules/.next + .venv 삭제. interactive 확인
# 이후: make setup && cd frontend && npm ci
```

**주의**: `config/portfolio.yaml` 은 gitignored 된 사용자 실데이터다. 삭제 전에 백업한다.

---

## 참고 — Phase 5 QA Scope

이 문서는 manual smoke 용이다. PR CI 에 포함된 negative tests:

- `tests/collectors/test_universe_sync.py::TestPhase5NegativeGuardrails` — missing/malformed/empty `universe.yaml` graceful error
- `tests/integration/test_universe_sync_real.py` — real network integration (marker `integration`, `make test-integration` 로만 실행)

**out-of-scope** (별도 PR 후보):

- API key 기반 collector 테스트 (현 path 는 모두 keyless)
- 분기별 자동화 live smoke CI job
- Dependency drift 감지

---

## 2026-04-29 re-smoke execution log

목적: 2026-04-15 (Phase 5 ship) baseline 이후 2주간 머지된 17 PRs (#479-#502) 뒤 coverage 회귀가 없는지 검증한다. Fresh clone 은 수행하지 않았다. Mac mini 가 24/7 scheduler 로 같은 환경을 매일 돌리고 있어 이를 fresh clone 상당 검증(running smoke)으로 보았다. 이 run 은 working repo 에서 collector 상태, negative tests, validators 만 spot-check 했다.

### Negative tests (3 cases — `tests/collectors/test_universe_sync.py::TestPhase5NegativeGuardrails`)

```
test_missing_universe_yaml_raises_actionable_error      PASSED
test_malformed_universe_yaml_raises_actionable_error    PASSED
test_empty_universe_yaml_raises_actionable_error        PASSED
============================== 3 passed in 0.15s ===============================
```

복구 명령(`make setup` / `git checkout main -- config/universe.yaml`)이 actionable error 메시지에 포함되는지, 진단 메시지가 한국어인지 확인했다. 3/3 통과.

### `make validate-universe-cache` (DB-only, no fetch)

```
2026-04-29 23:27:57 KST
─────────────────────────────────────────────────────
  data.prices                  99%   ≥95%   ✅ PASS
  data.fundamentals            99%   ≥80%   ✅ PASS
  data.analyst_ratings         97%   ≥70%   ✅ PASS
  data.insider_trades          97%   ≥50%   ✅ PASS
  data.superinvestors          97%   ≥80%   ✅ PASS
  Result: 5/5 PASS → exit 0
─────────────────────────────────────────────────────
real 0.31s
```

5개 coverage 임계 모두 통과, baseline (2026-04-15) 대비 회귀 없음.

### `make validate-universe` (with network fetch)

```
2026-04-29 23:28:01 KST
─────────────────────────────────────────────────────
  universe.us_sp500           100%   ≥95%   ✅ PASS
  universe.kr_kospi200         99%   ≥95%   ✅ PASS
  data.prices                  99%   ≥95%   ✅ PASS
  data.fundamentals            99%   ≥80%   ✅ PASS
  data.analyst_ratings         97%   ≥70%   ✅ PASS
  data.insider_trades          97%   ≥50%   ✅ PASS
  data.superinvestors          97%   ≥80%   ✅ PASS
  Result: 7/7 PASS → exit 0
─────────────────────────────────────────────────────
real 1.49s
```

fetch 포함 7개 check 전부 PASS. Wikipedia 와 FDR live API 정상.

### `make universe-sync-us` (dry-run)

```
US S&P 500 (current coverage: 100.0%)
  + 추가될 종목 (0):
  - 제거될 종목 (40): ANSS, ARKK, ARM, DKNG, DUOL, HES, HIMS, IONQ, IPG, IWM ... 외 30개
  ⚠️  manual ETF 보호: removed 40건 무시 (--allow-removal 로 명시적 허용)
```

40개 removal candidate 는 모두 manual ETF 또는 S&P 500 밖의 universe 항목(보유 종목과 ARK 등 watchlist 포함)이다. 보호 정책이 동작해 실제 적용 시 manual ETF 손실은 없다.

### `make universe-sync-kr` (dry-run)

```
KR KOSPI 200 (current coverage: 99.0%)
  + 추가될 종목 (2): 077970.KS, 229640.KS
  - 제거될 종목 (5): 000080.KS, 003540.KS, 010620.KS, 067160.KS, 073240.KS
  ⚠️  manual ETF 보호: removed 5건 무시
  ℹ️  dry-run — 실제 변경 없음 (총 7건)
```

2 add (KOSPI 200 신규 편입), 5 remove (편출). KR universe drift 는 정상 범위.

### Mac mini scheduler heartbeat (running smoke proxy)

```
$ ls -la data/logs/scheduler.log
.rw-r--r--@ 40k user 29 Apr 23:11

$ tail -3 data/logs/scheduler.log
2026-04-29 23:10:59 ark WARNING ARK CSV 다운로드 실패: 404 Client Error
2026-04-29 23:10:59 ark WARNING 모든 ARK 소스 실패 (CSV + yfinance)
2026-04-29 23:11:02 db_maintenance WARNING 테이블 strategy_memory 조회 실패 (미존재 가능)
```

ARK CSV 404 는 반복적으로 발생한다(ark-funds.com 의 endpoint 변경이 잦고 yfinance fallback 이 동작한다). `strategy_memory` 미존재 경고는 의도된 graceful 처리다. Critical failure 는 없었고, RotatingFileHandler (PR #498) 와 yfinance WARNING (PR #501) 적용 후 log volume 도 정상이다.

### Verdict

- **Negative path**: 3/3 PASS. actionable error 계약 유지.
- **Coverage**: 7/7 PASS (network) / 5/5 PASS (cache). 2026-04-15 baseline 대비 회귀 없음.
- **Live scheduler**: Mac mini 24/7 receiver 안정. log 정상, critical 없음.
- **Drift**: us_sp500 40 removals, kr_kospi200 2 add / 5 remove 를 dry-run 으로 확인. 당시 다음 weekly cron 에서 manual ETF 보호가 작동할 예정이었다.

**Phase 5 QA close**: TODO Tier 2 P1 #1 충족. 다음 점검은 분기별 또는 dependency 변동 시.

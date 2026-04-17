# SPEC: Universe Completeness + Agent Data Coverage

**Issue**: [#272](https://github.com/researcherhojin/nuri-quant/issues/272)
**Phase**: 1 (PM Spec)
**Author**: 2026-04-14 audit session
**Status**: **Complete** — #272 epic closed 2026-04-15 via Phase 5 QA PR #304. All 5 phases shipped (Phase 1 PM spec · 2a universe · 2b collectors · 2c CI gate · 3/4/5 agent+scorer+QA).

---

## 1. 문제 정의

### 1.1 발견된 두 가지 통합 결함

#### 결함 A — Universe label vs reality drift

| `config/universe.yaml` 라벨 | 실제 ticker 수 | 약속한 인덱스 | gap |
|----|----|----|----|
| `us_sp500_extended` (us_core 합산) | 339 | S&P 500 = 503종목 | -164 (33% 누락) |
| `kr_kospi200` | 80 | KOSPI 200 = 200종목 | -120 (60% 누락) |

라벨이 약속한 인덱스 커버리지를 충족하지 못하지만 자동 검증 부재.

#### 결함 B — Agent data silo (더 심각)

`BaseCollector._get_tickers()` 가 `SELECT ticker FROM portfolio` 만 반환. 즉 collector는 사용자 보유 종목만 fetch하고, universe의 나머지 종목엔 fundamental/wallstreet/smart_money/insider 데이터 자체가 없음.

**측정 결과 (2026-04-14)**:

| 데이터 소스 | universe 543종목 대비 coverage |
|------------|------------------------------|
| `prices` US ticker | 17/543 = **3%** |
| `fundamentals` | 16/543 = **2%** |
| `analyst_ratings` | 27/543 = **4%** |
| `insider_trades` | ~4% |
| `superinvestors` | 96% (13F filings 이미 광범위) |
| `macro_events` | (system-wide, OK) |

→ 10 agent 중 7개가 universe 종목엔 사실상 무효.

### 1.2 영향

- 신규 종목 발굴 정확도 저하 (consensus 결과 신뢰 불가)
- 사용자에게 잘못된 신뢰감 부여 (\"S&P 500 스캔\" 라벨)
- STRATEGY.md §2.1 \"증거 우선 (Evidence-first)\" 원칙 위반
- KOSPI 200 절반 이상 사각지대

---

## 2. 명확한 정의 (Acceptance Criteria)

### 2.1 Universe completeness

| 라벨 | 기준 source | 일치율 요구 | 측정 빈도 |
|------|------------|-------------|----------|
| `us_sp500_extended` ∪ `us_core` | Wikipedia [List_of_S%26P_500_companies](https://en.wikipedia.org/wiki/List_of_S%26P_500_companies) | ≥ **95%** (≥478/503) | 일 1회 |
| `kr_kospi200` | KRX 정보데이터시스템 또는 FinanceDataReader | ≥ **95%** (≥190/200) | 일 1회 |

**5% 허용 이유**: 신규 IPO 직후 / 상장폐지 직후의 transient state 흡수.

### 2.2 Agent data coverage

각 핵심 데이터 테이블이 universe 종목 대비 다음 비율 이상 채워져야 함:

| 테이블 | 최소 coverage | 최대 stale 허용 |
|--------|--------------|----------------|
| `prices` | ≥ **95%** | 24h |
| `fundamentals` | ≥ **80%** | 7d |
| `analyst_ratings` | ≥ **70%** | 14d |
| `insider_trades` | ≥ **50%** | 30d |
| `superinvestors` | ≥ **80%** | 90d (13F quarterly) |

**80% 기준 이유**: yfinance API 제한 + 일부 종목의 데이터 부재 (특수목적회사 등)는 자연스러움. 100% 요구는 비현실적.

### 2.3 단일 종목 consensus quality

랜덤 universe 종목에 `consensus --ticker X` 호출 시:
- 10 agent 중 **≥ 7개**가 score > 0 (의미 있는 verdict)
- \"데이터 부족\" / \"데이터 없음\" reason 포함 verdict ≤ 3개

---

## 3. 작업 구성 요소 (Phase 2-5)

### 3.1 Phase 2a — `nuri/collectors/universe_sync.py`

**책임**: Wikipedia / KRX (or FinanceDataReader) fetch → universe.yaml diff → diff 출력

**API**:
```python
class UniverseSyncCollector(BaseCollector):
    def collect(self, dry_run: bool = True) -> dict:
        \"\"\"return {'us_added': [...], 'us_removed': [...], 'kr_added': [...], 'kr_removed': [...]}\"\"\"
```

**CLI**: `python -m nuri.collectors.universe_sync [--apply]`
- default: dry-run (diff만 출력)
- `--apply`: universe.yaml에 직접 반영

**Makefile**: `make universe-sync` (cron-able, 매일 자동 실행 권장)

### 3.2 Phase 2b — `BaseCollector` universe 모드

**현재**:
```python
def _get_tickers(self, market: Optional[str] = None) -> list[str]:
    return [...]  # SELECT FROM portfolio only
```

**변경**:
```python
def _get_tickers(
    self,
    market: Optional[str] = None,
    source: str = "portfolio",  # 'portfolio' | 'universe' | 'all'
) -> list[str]:
    if source == "portfolio":
        return [...]  # 기존
    elif source == "universe":
        return _load_universe_tickers(market)
    elif source == "all":
        return list(set([...portfolio...] + _load_universe_tickers(market)))
```

**영향 collector** (확장 모드 지원):
- `nuri.collectors.stock` (가격) — 가장 중요
- `nuri.collectors.fundamental` (PE/ROE/margins)
- `nuri.collectors.wallstreet` (analyst/earnings/insider)

**제외 (portfolio-only로 유지)**:
- `nuri.collectors.kis_realtime` (사용자 잔고만 의미 있음)
- `nuri.collectors.macro` (인덱스 단위, ticker 무관)

**Makefile**: `make collect-universe` 신규 (확장 모드로 collect)

### 3.3 Phase 2c — `scripts/validate_universe.py`

**책임**: 2가지 검증 + CI gate
1. universe.yaml ↔ Wikipedia/KRX 일치율 ≥ 95%
2. Agent data coverage ≥ §2.2 기준

**Exit codes**: 0=PASS, 1=FAIL (CI block)

**CLI**:
```bash
python scripts/validate_universe.py
python scripts/validate_universe.py --no-fetch  # cached comparison only
```

**CI**: `.github/workflows/main-ci-cd.yml` 에 `universe-check` job 추가 (privacy-scan 옆).

### 3.4 Phase 3 — Tests

**파일**:
- `tests/collectors/test_universe_sync.py` — Wikipedia/KRX fetch mock + diff 정확성
- `tests/scripts/test_validate_universe.py` — coverage threshold 검증
- `tests/collectors/test_base_universe_mode.py` — `_get_tickers(source='universe')` 동작

**Coverage targets**: 신규 모듈 ≥ 90%

### 3.5 Phase 4 — UX

`/api/scan` 응답 포맷 확장:
```json
{
  "candidates": [...],
  "coverage": {
    "us_sp500": {"covered": 503, "total": 503, "pct": 100.0},
    "kospi200": {"covered": 198, "total": 200, "pct": 99.0},
    "agent_data": {"prices": 0.97, "fundamentals": 0.84, ...}
  },
  "warnings": []  // coverage <80% 시 추가
}
```

Dashboard ScanWidget:
- \"S&P 500: 503/503 (100%) | KOSPI 200: 198/200 (99%) | Agent data: 87%\" 배지
- 80% 미만 시 빨간 경고 + 누락 종목 hover tooltip

### 3.6 Phase 5 — QA

1. **Negative test**: universe.yaml에서 100종목 제거 → CI fail 검증
2. **Smoke E2E**:
   - `make universe-sync` (자동 갱신)
   - `make collect-universe` (전체 데이터 fetch, ~10분)
   - `python -m nuri.trading.agents.consensus --ticker <random S&P 500 종목>`
   - 검증: ≥ 7 agent score > 0

---

## 4. 변경 절차 (Constituents change)

S&P 500은 분기 리밸런싱, KOSPI 200은 6/12월 리밸런싱.

**자동 흐름** (cron):
1. `make universe-sync` 매일 실행
2. diff 발견 시 GitHub Issue 자동 생성 (또는 PR 자동 생성)
3. 사용자 review + merge
4. CI에서 universe-check 통과 확인

**수동 흐름** (긴급 시):
1. `python -m nuri.collectors.universe_sync --apply`
2. `make validate-universe`
3. `git commit + push`

---

## 5. PR 분할 (≤ 3 commits each)

| PR | Phase | 변경 | 추정 |
|----|-------|------|------|
| 1 | Phase 1 (이 문서) | docs/SPEC_universe_agent_coverage.md | 0.5 세션 |
| 2 | Phase 2a + 2c | universe_sync.py + validate_universe.py | 1 세션 |
| 3 | Phase 2b | BaseCollector universe 모드 | 1 세션 |
| 4 | Phase 3 | Tests | 0.5 세션 |
| 5 | Phase 4 | UX (API + Dashboard) | 0.5 세션 |
| 6 | Phase 5 | QA + smoke E2E | 0.5 세션 |

---

## 6. Out of scope

- OpenBB 30+ packages 호환성 (별도 issue [#274](https://github.com/researcherhojin/nuri-quant/issues/274))
- audit_log + DASHBOARD_PASSWORD (사용자 .env 설정 사항)
- universe.yaml의 Russell 2000 추가 (Tier 3)

---

## 7. Risks + Mitigations

| Risk | Mitigation |
|------|-----------|
| KRX KOSPI 200 fetch 불안정 (CLAUDE.md 알려진 pykrx 이슈) | FinanceDataReader fallback + 마지막 성공 데이터 cache |
| collect-universe 실행시간 (~10분) | 점진적 fetch (변경된 종목만), nightly cron |
| Wikipedia rate limit | User-Agent 헤더 + 10초 간격 backoff |
| `_get_tickers` 변경이 기존 collector 깨뜨림 | Default `source='portfolio'` 유지 (backwards compat) |

---

## 8. Reference

- 발견 세션: 2026-04-14 audit (사용자 portfolio 분석 중)
- `feedback_rigorous_review.md`, `feedback_gan_workflow.md`
- STRATEGY.md §2.1 (증거 우선), §5.3 (느슨한 결합)

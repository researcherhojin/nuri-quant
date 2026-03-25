# Phase C 구현 계획 — Validation Engine

> 핵심 질문: **"이 시그널/정보를 따르면 실제로 돈을 버는가?"**
>
> Phase B에서 수집한 데이터로, 각 정보 소스의 실제 수익률을 백테스트하여
> "쓸모 있는 시그널"과 "노이즈"를 구분한다.

## 데이터 현황 및 제약 (2026-03-26 기준)

| 데이터 | 현황 | 백테스트 가능 여부 |
|--------|------|-------------------|
| `prices` | 25,082건, 23종목, 2021-03-29 ~ 2026-03-25 (5년) | ✅ 즉시 가능 |
| `superinvestors` | 1,154건, 5명, **최신 1분기만** (2026-02) | ❌ 과거 분기 필요 |
| `estimates` | 21건, **오늘 1일분만** | ❌ 과거 목표가 필요 |

### 제약 해결 방안

**C-2 (슈퍼투자자)**: `edgartools`는 과거 13F도 조회 가능. `filings[0]`이 아닌 `filings[:N]`으로 최근 8분기(2년)를 수집하면 분기 간 비교(NEW/INCREASED/DECREASED) + 추종 수익률 계산 가능.

**C-3 (애널리스트)**: 과거 목표가를 소급 수집하는 무료 소스가 없음. 대신 **오늘부터 추적 시작** — 매주 `estimates`를 누적하고, 3~6개월 후 실제 주가와 비교하는 "전향적(prospective) 검증" 방식. 즉시 백테스트는 불가하지만, 스키마와 측정 로직은 미리 구현해둔다.

---

## C-1. 기술적 시그널 백테스트

> 즉시 구현 가능. prices 5년 데이터로 시그널별 승률/수익률 측정.

### 검증 대상 시그널 (7개)

| ID | 시그널 | 진입 조건 | 청산 조건 |
|----|--------|----------|----------|
| `rsi_oversold` | RSI 과매도 반등 | RSI가 30 아래에서 30 위로 크로스 | 20일 보유 |
| `rsi_overbought` | RSI 과매수 이탈 | RSI가 70 위에서 70 아래로 크로스 | 20일 보유 |
| `macd_golden` | MACD 골든크로스 | MACD가 Signal 위로 크로스 | MACD가 Signal 아래로 크로스 |
| `macd_dead` | MACD 데드크로스 | MACD가 Signal 아래로 크로스 | MACD가 Signal 위로 크로스 |
| `sma_golden` | SMA 골든크로스 | SMA50이 SMA200 위로 크로스 | SMA50이 SMA200 아래로 크로스 |
| `sma_dead` | SMA 데드크로스 | SMA50이 SMA200 아래로 크로스 | SMA50이 SMA200 위로 크로스 |
| `bb_bounce` | BB 하단 반등 | 종가가 BB Lower 아래에서 위로 크로스 | 20일 보유 |

### 측정 지표 (시그널 x 종목)

```python
@dataclass
class SignalResult:
    signal_id: str          # "rsi_oversold"
    ticker: str             # "TSLA"
    entry_date: str         # "2024-01-15"
    entry_price: float      # 230.50
    exit_date: str          # "2024-02-14"
    exit_price: float       # 245.80
    return_pct: float       # +6.63
    holding_days: int       # 20
    won: bool               # True
```

```python
@dataclass
class SignalScorecard:
    signal_id: str
    ticker: str | None      # None = 전체 종목 합산
    total_trades: int
    win_rate: float         # 0.0 ~ 1.0
    avg_return: float       # %
    median_return: float    # %
    max_return: float       # %
    max_loss: float         # %
    profit_factor: float    # 총이익 / 총손실
    avg_holding_days: float
```

### 구현

```
nuri/quant/validation/signal_backtest.py
```

**함수 시그니처:**
```python
def backtest_signals(
    ticker: str | None = None,       # None = 전 종목
    signals: list[str] | None = None, # None = 전 시그널
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[SignalResult]:
    """시그널 백테스트 실행. prices 테이블에서 데이터 로드 후 TA-Lib 계산."""

def generate_scorecard(
    results: list[SignalResult],
) -> list[SignalScorecard]:
    """SignalResult → 시그널별 집계 스코어카드."""

def print_scorecard(scorecards: list[SignalScorecard]) -> None:
    """CLI 출력."""
```

**`__main__` 블록:**
```bash
python -m nuri.quant.validation.signal_backtest
python -m nuri.quant.validation.signal_backtest --ticker TSLA
python -m nuri.quant.validation.signal_backtest --signal rsi_oversold
```

**출력 파일:**
- `data/reports/YYYY-MM-DD/signal_results.csv` — 개별 거래 내역
- `data/reports/YYYY-MM-DD/signal_scorecard.csv` — 시그널별 집계

### 검증 테스트

```
tests/test_validation.py::TestSignalBacktest
```
- `test_rsi_oversold_detection`: 알려진 가격 시퀀스에서 RSI 과매도 반등 정확히 감지
- `test_holding_period_exit`: 20일 보유 후 정확한 청산 가격
- `test_scorecard_calculation`: 승률, Profit Factor 계산 정확도
- `test_empty_signals`: 시그널이 없는 종목 처리

---

## C-2. 슈퍼투자자 추종 백테스트

> 선행 작업: `superinvestors.py`를 수정하여 과거 8분기 13F 수집

### Step 1: 과거 13F 수집 확장

현재 `superinvestors.py`는 `filings[0]` (최신 1건)만 수집. 과거 분기 비교를 위해 확장:

```python
# 현재 (변경 전)
latest = filings[0]

# 변경 후
for filing in filings[:8]:  # 최근 8분기 (2년)
    filing_obj = filing.obj()
    ...
```

**분기 간 변화 감지:**
```python
def detect_changes(current_quarter: pd.DataFrame, prev_quarter: pd.DataFrame) -> pd.DataFrame:
    """두 분기 13F 비교 → NEW/INCREASED/DECREASED/CLOSED/UNCHANGED."""
```

**DB 스키마 변경 불필요** — `superinvestors` 테이블은 이미 `(investor, filing_date, ticker)` UNIQUE로 다분기 저장 가능.

### Step 2: 추종 백테스트

```
nuri/quant/validation/superinvestor_backtest.py
```

**전략:**
1. 분기 N에서 "NEW" (신규 매수) 종목 식별
2. 13F 공시일 다음 거래일에 매수
3. N일 후 매도 (N = 60, 120, 252)
4. 동일 기간 VOO 수익률과 비교 → 초과수익률

**함수 시그니처:**
```python
def backtest_superinvestor(
    investor: str | None = None,     # None = 전체
    hold_days: int = 120,
) -> list[FollowResult]:

@dataclass
class FollowResult:
    investor: str
    ticker: str
    filing_date: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    return_pct: float
    benchmark_return_pct: float      # VOO 동기간
    excess_return_pct: float
    change_type: str                 # NEW, INCREASED
```

**출력 파일:**
- `data/reports/YYYY-MM-DD/superinvestor_scorecard.csv`

### 제약

- 과거 8분기 수집 시 SEC EDGAR 요청 ~40건 (5명 x 8분기). rate limit 10 req/sec이므로 ~5초.
- 일부 종목은 `prices` 테이블에 없을 수 있음 (보유하지 않은 종목) → `prices`에 없는 종목은 건너뛰고 로그 남김.

---

## C-3. 애널리스트 목표가 검증 (전향적)

> 즉시 백테스트 불가 (과거 목표가 없음). 추적 인프라 구축 + 스키마 준비.

### 전략: 전향적(prospective) 검증

1. `estimates` 수집기는 이미 주 1회 실행 (스케줄러 등록 완료)
2. 매주 수집되는 데이터가 `(ticker, date)` UNIQUE로 누적됨
3. 3개월 후: "2026-03-26 시점 목표가 $421" vs "2026-06-26 실제 가격 $???" 비교 가능

### 구현

```
nuri/quant/validation/analyst_backtest.py
```

**함수 시그니처:**
```python
def validate_estimates(
    min_elapsed_days: int = 90,  # 최소 경과일
) -> list[EstimateResult]:
    """과거 estimates 데이터와 현재 가격을 비교하여 검증."""

@dataclass
class EstimateResult:
    ticker: str
    estimate_date: str
    target_mean: float
    actual_price: float          # estimate_date + min_elapsed_days 시점
    target_gap_pct: float        # (target - price_at_estimate) / price_at_estimate
    actual_return_pct: float     # 실제 수익률
    target_hit: bool             # actual >= target_mean
    recommendation: str          # buy, strong_buy, etc.
```

**데이터가 부족한 경우:**
```
$ python -m nuri.quant.validation.analyst_backtest
⚠️ 검증 가능한 데이터 없음: 최소 90일 경과된 estimates가 필요합니다.
   현재 가장 오래된 estimate: 2026-03-26 (0일 경과)
   예상 검증 가능 시점: 2026-06-24
   estimates 수집은 매주 자동으로 누적됩니다 (스케줄러 등록 완료).
```

---

## C-4. 통합 스코어카드

> C-1~C-3 결과를 단일 HTML 대시보드로 통합.

```
nuri/quant/validation/scorecard.py
```

**함수 시그니처:**
```python
def generate_validation_report(
    output_dir: Path | None = None,
) -> Path:
    """C-1/C-2/C-3 결과를 통합 HTML로 생성. Plotly 사용."""
```

**HTML 대시보드 섹션:**
1. **시그널 랭킹** — 승률/Profit Factor 기준 정렬 (C-1)
2. **슈퍼투자자 랭킹** — 추종 초과수익률 기준 정렬 (C-2)
3. **애널리스트 적중률** — 목표가 도달률 (C-3, 데이터 누적 후)
4. **현재 활성 시그널** — 오늘 발생한 시그널 + 해당 시그널의 과거 승률
5. **차트 시그널 신뢰도** — B-3 차트의 ▲/▼에 승률 라벨 추가 가능 여부

**출력:**
- `data/reports/YYYY-MM-DD/validation_report.html`

---

## C-5. ETF 자금흐름 수집

> 투자 판단 9단계 중 7번("돈이 몰리나?") 채우기.

### 소스 조사 필요

| 소스 | 데이터 | 무료 여부 | 검증 상태 |
|------|--------|----------|----------|
| OpenBB `obb.etf.*` | ETF 보유종목, 수익률 | yfinance 지원 확인 필요 | ❓ 미검증 |
| etfdb.com | 섹터별 자금흐름 | 스크래핑 가능 여부 확인 필요 | ❓ 미검증 |

**구현 전 검증 필수:**
```python
# 먼저 이것부터 실행하여 어떤 데이터가 나오는지 확인
from openbb import obb
obb.etf.holdings("SPY", provider="yfinance")
obb.etf.info("SPY", provider="yfinance")
```

---

## 구현 순서

```
C-1 시그널 백테스트        ← 바로 구현 (prices 5년 + TA-Lib)
  ↓
C-2a 과거 13F 수집 확장    ← C-1과 병렬 (superinvestors.py 수정)
C-2b 슈퍼투자자 백테스트   ← C-2a 완료 후
  ↓
C-3 애널리스트 추적 인프라  ← C-1과 병렬 (스키마만, 데이터 누적 대기)
  ↓
C-4 통합 스코어카드        ← C-1 + C-2b 완료 후
  ↓
C-5 ETF 자금흐름           ← 독립적 (소스 검증 먼저)
```

### 파일 목록

```
nuri/quant/validation/
  __init__.py                        ← 생성 완료
  signal_backtest.py                 ← C-1
  superinvestor_backtest.py          ← C-2
  analyst_backtest.py                ← C-3
  scorecard.py                       ← C-4
nuri/collectors/etf_flows.py         ← C-5
tests/test_validation.py             ← C-1~C-3 테스트
```

### verify.py 통합

`scripts/verify.py`에 Phase C 검증 단계 추가:
```python
def verify_signal_backtest(report_dir, summary):
    """C-1 시그널 백테스트 결과를 verify 리포트에 포함."""

def verify_superinvestor_backtest(report_dir, summary):
    """C-2 슈퍼투자자 추종 결과를 verify 리포트에 포함."""
```

### Makefile 추가

```makefile
# Phase C
validate:
	$(PYTHON) -m nuri.quant.validation.signal_backtest
	$(PYTHON) -m nuri.quant.validation.superinvestor_backtest
	$(PYTHON) -m nuri.quant.validation.analyst_backtest
	$(PYTHON) -m nuri.quant.validation.scorecard
```

---

## 완료 기준

| 작업 | 완료 조건 |
|------|----------|
| C-1 | 7개 시그널 x 23종목 스코어카드 CSV 생성, 테스트 통과 |
| C-2a | 과거 8분기 13F 수집 완료, DB에 다분기 데이터 존재 |
| C-2b | 5명 투자자 추종 스코어카드 CSV 생성 |
| C-3 | `analyst_backtest.py` 실행 시 "데이터 부족" 메시지 정상 출력, 스키마 준비 |
| C-4 | `validation_report.html` 생성, C-1 + C-2 결과 통합 |
| C-5 | OpenBB ETF 엔드포인트 검증 완료, 수집기 구현 (가능한 경우) |
| 전체 | `make validate` 정상 실행, `make verify`에 통합 |

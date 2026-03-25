# Phase B 구현 계획 — 정보 소스 확장 + 시각화

> 목표: "이 종목을 살까?" 판단에 필요한 9가지 정보 카테고리를 모두 채운다.
>
> 원칙: 100% 무료 오픈소스, 기존 아키텍처(BaseCollector → DB → Analysis) 유지

## 완료 상태 (Phase B 완료 — 2026-03-26)

```
✅ 가격/모멘텀      OpenBB + pykrx + TA-Lib (5년 25,082건)
✅ 매크로           FRED (8개 지표)
✅ 공포/탐욕        CNN Fear & Greed
✅ 스마트머니       ARK + SEC 13F (버핏/게이츠/달리오/애크먼/테퍼, 1,154건)
✅ 뉴스            247건 수집 + 센티먼트 분석 완료
✅ 펀더멘탈         PE/PB/ROE/마진/성장률 (21종목)
✅ 애널리스트       목표가/투자의견 (21종목)
✅ 차트 시각화      23종목 인터랙티브 HTML (시그널 마커 + 정보 패널)
⚠️ 수급            프레임워크 완료 (pykrx KRX API 불안정, finnhub 키 미설정)
```

---

## B-1. 펀더멘탈 수집기

> "이 주식이 비싼가, 싼가?"를 판단하는 기반 데이터

### 수집 데이터
- PER, PBR, PSR, PEG
- ROE, ROA, 영업이익률
- 매출 성장률, EPS 성장률
- 부채비율 (Debt/Equity)
- 시가총액, 배당수익률

### 구현
| 항목 | 내용 |
|------|------|
| 소스 | OpenBB `obb.equity.fundamental.metrics` (yfinance) — `ratios`는 yfinance 미지원, `metrics`로 충분 |
| 비용 | 무료 |
| 파일 | `nuri/collectors/fundamental.py` |
| DB 테이블 | `fundamentals` (신규) |
| 스케줄 | 주 1회 (일요일 00:00) — 분기 실적 기반이라 자주 변하지 않음 |

### 검증 완료 (2026-03-26)
```
TSLA: pe_ratio=361.99, pb=17.69, roe=0.049, revenue_growth=-0.031, debt_to_equity=17.76
005930.KS: forward_pe=6.58, roe=0.108, revenue_growth=0.238, debt_to_equity=5.79
→ 미국/한국 종목 모두 yfinance provider로 30+개 필드 확인
```

### DB 스키마
```sql
CREATE TABLE IF NOT EXISTS fundamentals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    market_cap REAL,
    pe_ratio REAL,
    forward_pe REAL,
    price_to_book REAL,
    peg_ratio REAL,
    roe REAL,
    roa REAL,
    gross_margin REAL,
    operating_margin REAL,
    profit_margin REAL,
    revenue_growth REAL,
    earnings_growth REAL,
    debt_to_equity REAL,
    current_ratio REAL,
    dividend_yield REAL,
    beta REAL,
    UNIQUE(ticker, date)
);
```

### 분석 활용
- `portfolio.py`에 밸류에이션 경고 추가 (PER > 40 고평가 경고 등)
- `verify.py`에 펀더멘탈 요약 추가

---

## B-2. 슈퍼투자자 포트폴리오 (13F)

> "버핏/달리오도 이 종목을 갖고 있나?"

### 수집 데이터
- 분기별 보유 종목 (종목, 수량, 시가총액)
- 분기 대비 변화 (신규매수/매도/증가/감소)
- 포트폴리오 집중도 (상위 10 종목 비중)

### 추적 대상 슈퍼투자자
| 투자자 | 펀드 | SEC CIK |
|--------|------|---------|
| 워런 버핏 | Berkshire Hathaway | 0001067983 |
| 빌 게이츠 | Bill & Melinda Gates Foundation | 0001166559 |
| 레이 달리오 | Bridgewater Associates | 0001350694 |
| 빌 애크먼 | Pershing Square | 0001336528 |
| 데이비드 테퍼 | Appaloosa Management | 0001656456 |
| 캐시 우드 | ARK Invest | 0000895421 |

### 구현
| 항목 | 내용 |
|------|------|
| 소스 | **edgartools** (SEC EDGAR 직접, API 키 불필요) |
| 비용 | 무료 |
| 설치 | `pip install edgartools` |
| 파일 | `nuri/collectors/superinvestors.py` |
| DB 테이블 | `superinvestors` (신규) |
| 스케줄 | 주 1회 (13F는 분기별 공시, 주 1회면 충분) |

### 검증 완료 (2026-03-26)
```
Berkshire Hathaway (버핏): 42종목, 총 $274B
  AAPL 22.6%, AXP 20.5%, BAC 10.4%, KO 10.2%, CVX 7.2%
→ edgartools로 SEC EDGAR 직접 조회, API 키 불필요, 티커+비중+시가총액 모두 포함
```

### DB 스키마
```sql
CREATE TABLE IF NOT EXISTS superinvestors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    investor TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    shares REAL,
    market_value REAL,
    portfolio_pct REAL,
    change_type TEXT,          -- NEW, INCREASED, DECREASED, CLOSED, UNCHANGED
    change_pct REAL,
    UNIQUE(investor, filing_date, ticker)
);
```

### 분석 활용
- "내 보유종목 중 슈퍼투자자도 보유한 종목" 매칭
- "슈퍼투자자가 최근 새로 매수한 종목" 알림
- InvestingPro "주요 아이디어" 화면과 동일한 기능을 무료로 구현

---

## B-3. 기술적 분석 차트 시각화

> 기존 signals 테이블 데이터를 눈으로 확인

### 차트 구성
```
┌─────────────────────────────────────┐
│  캔들스틱 + 볼린저밴드 + SMA/EMA    │  메인 패널
├─────────────────────────────────────┤
│  거래량 (Volume)                     │  서브 패널 1
├─────────────────────────────────────┤
│  RSI (14) + 과매수/과매도 라인       │  서브 패널 2
├─────────────────────────────────────┤
│  MACD + Signal + Histogram          │  서브 패널 3
└─────────────────────────────────────┘
```

### 구현
| 항목 | 내용 |
|------|------|
| 인터랙티브 HTML | **Plotly** (이미 설치됨) — 줌/패닝/호버 지원 |
| 정적 이미지 | **mplfinance** (추가 설치) — Discord 리포트용 PNG |
| 파일 | `nuri/analysis/charts.py` |
| 출력 | `data/reports/YYYY-MM-DD/charts/TICKER.html` + `TICKER.png` |
| 추가 설치 | `pip install mplfinance` |

### 기능
- 종목별 개별 차트 생성: `python -m nuri.analysis.charts --ticker TSLA`
- 전체 보유종목 일괄 생성: `python -m nuri.analysis.charts --all`
- `verify.py`에 통합: 검증 시 전 종목 차트 자동 생성
- 매수/매도 신호 마커 표시 (RSI 과매수/과매도, MACD 크로스)

---

## B-4. 애널리스트 컨센서스

> "전문가들은 이 종목을 어떻게 보나?"

### 수집 데이터
- 컨센서스 투자의견 (Strong Buy ~ Strong Sell)
- 평균/최고/최저 목표가
- 현재가 대비 목표가 괴리율
- 애널리스트 수

### 구현
| 항목 | 내용 |
|------|------|
| 소스 | OpenBB `obb.equity.estimates.consensus` (yfinance) — `price_target`은 yfinance 미지원, `consensus`만 사용 |
| 비용 | 무료 |
| 파일 | `nuri/collectors/estimates.py` |
| DB 테이블 | `estimates` (신규) |
| 스케줄 | 주 1회 |

### 검증 완료 (2026-03-26)
```
TSLA: target_high=$600, target_low=$119, consensus=$421, recommendation=buy, analysts=41
005930.KS: target_high=340000, target_low=110000, consensus=239873, recommendation=strong_buy, analysts=37
→ 미국/한국 종목 모두 yfinance로 동작 확인
```

### DB 스키마
```sql
CREATE TABLE IF NOT EXISTS estimates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    recommendation TEXT,       -- buy, hold, sell
    target_high REAL,
    target_low REAL,
    target_mean REAL,
    target_median REAL,
    num_analysts INTEGER,
    UNIQUE(ticker, date)
);
```

---

## B-5. 기관/외인 수급

> "큰손들은 어느 방향으로 움직이나?"

### 수집 데이터
- 한국: 기관/외국인 순매수 금액 (pykrx)
- 미국: 기관 보유 비중 변화 (finnhub 무료 API)

### 구현
| 항목 | 내용 |
|------|------|
| 소스 (한국) | pykrx `stock.get_market_trading_value_by_date()` |
| 소스 (미국) | finnhub 무료 API (60 calls/min) — OpenBB ownership은 yfinance 미지원(fmp만), finnhub 대체 |
| 비용 | 무료 (finnhub 무료 키 필요) |
| 파일 | `nuri/collectors/institutional.py` |
| DB 테이블 | `institutional_flows` (신규) |
| 스케줄 | 매일 (장 마감 후) |

### DB 스키마
```sql
CREATE TABLE IF NOT EXISTS institutional_flows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    market TEXT NOT NULL,       -- US, KR
    institution_net REAL,      -- 기관 순매수
    foreign_net REAL,          -- 외국인 순매수
    individual_net REAL,       -- 개인 순매수
    source TEXT,
    UNIQUE(ticker, date, market)
);
```

---

## B-6. 뉴스 센티먼트 분석

> "분위기는 긍정적인가 부정적인가?"

### 구현
| 항목 | 내용 |
|------|------|
| 방법 1 | 키워드 기반 (무료, 즉시 가능) — 긍정/부정 단어 사전 매칭 |
| 방법 2 | LLM 기반 (Phase F) — 더 정확하지만 비용/시간 소요 |
| 파일 | `nuri/analysis/sentiment.py` |
| DB | 기존 `news.sentiment` 컬럼 활용 (현재 NULL) |

### 키워드 사전 방식 (방법 1)
```python
POSITIVE = {"surge", "beat", "upgrade", "bullish", "record", "growth", ...}
NEGATIVE = {"crash", "miss", "downgrade", "bearish", "decline", "loss", ...}
# score = (positive_count - negative_count) / total_words
```

---

## B-7. 실시간 뉴스 강화 (SaveTicker 대체)

> SaveTicker가 제공하는 정보를 무료 소스로 대체

SaveTicker(세이브티커)는 공개 API 없이 403 차단하므로 직접 연동 불가.
동일한 정보를 아래 소스로 커버:

| SaveTicker 기능 | 대체 구현 | 소스 |
|-----------------|----------|------|
| 미국 증시 속보 | 뉴스 수집 빈도 증가 (6h → 1h) | OpenBB News |
| 경제지표 캘린더 | events 수집기 확장 | FRED + OpenBB |
| 실적발표 일정 | events 수집기 (이미 있음) | OpenBB Earnings |
| FOMC 일정 | events.py (이미 있음) | 하드코딩 |
| 한국어 요약 | LLM 뉴스 요약 (Phase F) | Ollama/Claude |
| 키워드 알림 | Discord 알림 필터 확장 | 자체 구현 |

### 구현
- `nuri/collectors/news.py` 스케줄 변경: `0 */6 * * *` → `0 */1 * * *`
- `nuri/alerts/formatters.py`에 뉴스 요약 embed 추가
- `config/alerts.yaml`에 키워드 알림 설정 추가:
  ```yaml
  keyword_alerts:
    - "FOMC"
    - "금리"
    - "실적"
    - "테슬라"
  ```

---

## 구현 순서 및 의존성

```
B-1 펀더멘탈        ← 의존성 없음, 바로 시작
B-2 슈퍼투자자      ← 의존성 없음, B-1과 병렬 가능
B-3 차트 시각화     ← signals 테이블 필요 (이미 있음)
B-4 애널리스트      ← 의존성 없음
B-5 기관 수급       ← 의존성 없음
B-6 뉴스 센티먼트   ← news 테이블 필요 (이미 있음)
B-7 뉴스 강화       ← B-6 완료 후
```

### 추가 필요 패키지
```
edgartools          # B-2: SEC EDGAR 13F
mplfinance          # B-3: 정적 차트 이미지
finnhub-python      # B-5: 미국 기관 수급 (선택)
```

### 예상 DB 테이블 추가
```
fundamentals        # B-1
superinvestors      # B-2
estimates           # B-4
institutional_flows # B-5
```

---

## 완료 후 투자 판단 프로세스

```
"이 종목을 살까?"

1. 시장 환경은?     ✅ 매크로 + VIX + Fear&Greed
2. 싸긴 한 건가?    ✅ PER/PBR/PSR + 히스토리 (B-1)
3. 실적은 괜찮나?   ✅ ROE/매출성장/이익률 (B-1)
4. 차트는?          ✅ 캔들스틱 + RSI/MACD/BB (B-3)
5. 전문가들은?      ✅ 목표가/컨센서스 (B-4)
6. 큰손들은?        ✅ 기관수급 + 슈퍼투자자 (B-2, B-5)
7. 돈이 몰리나?     ⬜ ETF 자금흐름 (Phase C)
8. 분위기는?        ✅ 뉴스 센티먼트 (B-6)
9. 리스크는?        ✅ VaR/상관관계/포지션 (이미 있음)
```

9단계 중 8단계를 Phase B에서 채운다.

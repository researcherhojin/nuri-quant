# Phase C 구현 계획 — Validation Engine

> 핵심 질문: **"이 시그널/정보를 따르면 실제로 돈을 버는가?"**
>
> Phase B에서 수집한 데이터를 바탕으로, 각 정보 소스의 실제 수익률을 백테스트하여
> "쓸모 있는 시그널"과 "노이즈"를 구분한다.

## 왜 필요한가

Phase B 차트에는 매수/매도 시그널(▲/▼)이 표시되지만, 이를 기계적으로 따르면
맞을 때도, 틀릴 때도 있다. 현재 상태에서는 **어떤 시그널이 얼마나 신뢰할 수 있는지 모른다.**

Phase C가 답해야 할 질문들:
- RSI 과매도 반등 시그널의 승률은? 평균 수익률은?
- MACD 골든크로스의 승률은? 골든/데드 크로스 중 뭐가 더 유용한가?
- 버핏이 매수한 종목을 따라 사면 1년 후 수익률은?
- ARK가 매수한 종목을 따라 사면?
- 애널리스트 목표가 대비 현재가 괴리가 크면 실제로 오르는가?

---

## C-1. 기술적 시그널 백테스트

> B-3 차트의 ▲BUY/▼SELL 시그널을 역사적으로 검증

### 검증 대상 시그널
| 시그널 | 진입 조건 | 청산 조건 |
|--------|----------|----------|
| RSI 과매도 반등 | RSI < 30 → 30 돌파 | 20일 보유 또는 RSI > 70 |
| RSI 과매수 이탈 | RSI > 70 → 70 이탈 | 20일 보유 (숏 관점) |
| MACD 골든크로스 | MACD > Signal 크로스 | MACD < Signal 크로스 |
| MACD 데드크로스 | MACD < Signal 크로스 | MACD > Signal 크로스 |
| SMA 골든크로스 | SMA50 > SMA200 크로스 | SMA50 < SMA200 크로스 |
| SMA 데드크로스 | SMA50 < SMA200 크로스 | SMA50 > SMA200 크로스 |
| BB 하단 돌파 반등 | 종가 < BB Lower → BB Lower 돌파 | 20일 보유 또는 BB Upper 도달 |

### 측정 지표 (시그널당)
- 발생 횟수
- 승률 (%) — 진입 후 수익 > 0인 비율
- 평균 수익률 (%)
- 중앙값 수익률 (%)
- 최대 수익 / 최대 손실
- 평균 보유 기간 (일)
- Profit Factor — 총 이익 / 총 손실

### 구현
| 항목 | 내용 |
|------|------|
| 파일 | `nuri/quant/validation/signal_backtest.py` |
| 소스 | `prices` 테이블 (5년 25,000+건) + TA-Lib 계산 |
| 출력 | `data/reports/YYYY-MM-DD/signal_scorecard.csv` + `signal_scorecard.html` |

### 출력 예시
```
=== 시그널 스코어카드 (TSLA, 5년) ===
시그널                 횟수   승률    평균수익  Profit Factor
RSI 과매도 반등         12   66.7%    +4.2%      2.31
MACD 골든크로스         28   53.6%    +2.1%      1.45
SMA 골든크로스           3   66.7%   +15.3%      3.82
BB 하단 반등            18   61.1%    +3.8%      2.05
MACD 데드크로스         27   48.1%    -0.5%      0.92  ← 노이즈
RSI 과매수 이탈         14   42.9%    -1.2%      0.78  ← 노이즈
```

---

## C-2. 슈퍼투자자 추종 백테스트

> "버핏/달리오가 산 종목을 따라 사면 수익이 나는가?"

### 검증 방법
1. 13F 공시일 기준으로 "신규 매수(NEW)" 종목을 식별
2. 공시일 다음 거래일에 매수, N일 후 매도 (N = 60, 120, 252일)
3. 벤치마크(VOO) 대비 초과수익률 계산

### 측정 지표 (투자자당)
- 추종 매수 횟수
- 승률 (60일/120일/1년)
- 평균 초과수익률 vs VOO
- 가장 수익률 높은/낮은 종목

### 구현
| 항목 | 내용 |
|------|------|
| 파일 | `nuri/quant/validation/superinvestor_backtest.py` |
| 소스 | `superinvestors` + `prices` 테이블 |
| 출력 | `data/reports/YYYY-MM-DD/superinvestor_scorecard.csv` |

---

## C-3. 애널리스트 목표가 검증

> "목표가 괴리율이 큰 종목이 실제로 오르는가?"

### 검증 방법
1. 목표가 대비 현재가 괴리율 상위 종목을 식별
2. 괴리율 구간별 (>50%, 30-50%, 10-30%) 실제 수익률 비교
3. recommendation(strong_buy/buy/hold/sell)별 실제 수익률 비교

### 구현
| 항목 | 내용 |
|------|------|
| 파일 | `nuri/quant/validation/analyst_backtest.py` |
| 소스 | `estimates` + `prices` 테이블 |
| 출력 | `data/reports/YYYY-MM-DD/analyst_scorecard.csv` |

---

## C-4. 통합 스코어카드

> 모든 검증 결과를 하나의 대시보드로 통합

### 구현
| 항목 | 내용 |
|------|------|
| 파일 | `nuri/quant/validation/scorecard.py` |
| 출력 | `data/reports/YYYY-MM-DD/validation_report.html` (Plotly) |

### 통합 보고서 내용
1. **시그널 랭킹** — 승률/Profit Factor 기준으로 시그널 순위
2. **투자자 랭킹** — 추종 수익률 기준으로 슈퍼투자자 순위
3. **현재 활성 시그널** — 오늘 기준으로 발생한 시그널 + 신뢰도 점수
4. **추천 액션** — 신뢰도 높은 시그널이 발생한 종목 목록

---

## C-5. ETF 자금흐름 수집

> 섹터 로테이션 파악 — Phase B에서 누락된 7번째 정보

### 구현
| 항목 | 내용 |
|------|------|
| 소스 | OpenBB `obb.etf.holdings` 또는 무료 ETF 데이터 |
| 파일 | `nuri/collectors/etf_flows.py` |
| DB 테이블 | `etf_flows` (신규) |
| 검증 | 자금 유입 상위 섹터의 실제 수익률 |

---

## 구현 순서

```
C-1 시그널 백테스트      ← 바로 시작 (prices + TA-Lib만 필요)
C-2 슈퍼투자자 백테스트  ← C-1과 병렬 (superinvestors + prices)
C-3 애널리스트 검증      ← C-1과 병렬 (estimates + prices)
C-4 통합 스코어카드      ← C-1~C-3 완료 후
C-5 ETF 자금흐름         ← 독립적
```

### 추가 필요 파일
```
nuri/quant/validation/           # 신규 디렉토리
  __init__.py
  signal_backtest.py             # C-1
  superinvestor_backtest.py      # C-2
  analyst_backtest.py            # C-3
  scorecard.py                   # C-4
nuri/collectors/etf_flows.py     # C-5
```

---

## 완료 후 기대 효과

Phase C 완료 시:
- 차트의 ▲/▼ 시그널 옆에 **신뢰도 점수**를 표시할 수 있음
- "버핏 추종 전략은 승률 65%, 평균 초과수익 +8%" 같은 근거 제시 가능
- 신뢰도 낮은 시그널 자동 필터링 → 노이즈 제거
- `make verify` 리포트에 validation_report.html 추가

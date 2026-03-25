# 🔬 IRIS — Investment Research & Intelligence System

> **개인 퀀트 투자 분석 플랫폼**  
> M3 Max MacBook (개발) → M2 Pro Mac Mini (프로덕션 24/7)  
> Claude Code → Local LLM → Quant Trading Pipeline

---

## Overview

IRIS는 2.27억원 규모의 다계좌 포트폴리오(5개 계좌, 27종목)를 체계적으로 관리하기 위한 개인 투자 분석 플랫폼입니다. 3단계로 진화하며, 최종적으로 퀀트 트레이딩 수준의 분석 역량을 갖추는 것이 목표입니다.

### 진화 경로

```
Phase 1 (Week 1-3)          Phase 2 (Week 4-6)           Phase 3 (Week 7-12)
───────────────────     ──────────────────────      ──────────────────────────
 Claude Code + MCP       Local LLM Benchmark          Quant Pipeline
 SQLite 데이터 수집        모델별 성능 비교              백테스트 엔진
 Discord 알림 봇           투자 분석 정확도 측정          팩터 모델 / 알파 시그널
 기술적 지표 자동화         최적 모델 선정                자동 리밸런싱 / 리스크관리
                          Ollama 파이프라인 구축         실시간 트레이딩 시그널
```

### 이전 설계(v1)의 문제점과 수정 사항

| 문제 | v1 설계 | v2 수정 |
|------|---------|---------|
| Ghostfolio는 한국 증권사 API 미지원 | Ghostfolio Docker 중심 | portfolio.yaml + SQLite 직접 관리 |
| Streamlit + Ollama가 Claude Code와 기능 중복 | 별도 대시보드 + 별도 LLM | Claude Code가 분석 엔진 역할 (Phase 1) |
| Backtrader를 처음부터 도입하는 건 과잉 | 1주차부터 백테스트 구축 | Phase 3에서 퀀트 파이프라인으로 확장 |
| Local LLM 벤치마크 계획 없음 | Ollama 단순 사용 | Phase 2에서 모델별 체계적 비교 실험 |
| 단일 머신 구조 | 맥미니에서 개발+운영 혼재 | M3 Max(개발) → M2 Pro(프로덕션) 분리 |

---

## Architecture

```
                        ┌─────────────────────────────┐
                        │      사장님 (의사결정자)        │
                        └──────┬──────────────┬───────┘
                               │              │
                 ┌─────────────▼──┐    ┌──────▼──────────────────┐
                 │  Claude Code   │    │  Discord Bot             │
                 │  / Local LLM   │    │  (자동 알림, 24/7)        │
                 │                │    │                          │
                 │ Phase 1: Claude│    │ • Daily Report   08:00   │
                 │ Phase 2: Ollama│    │ • 급등락 알림    ±3%     │
                 │ Phase 3: Quant │    │ • ARK 매매 알림  실시간   │
                 └───────┬────────┘    │ • FOMC/실적 D-1 알림     │
                         │             │ • 리밸런싱 알림  월 1회   │
                         │             └────────────┬─────────────┘
                         │                          │
              ┌──────────▼──────────────────────────▼──────────────┐
              │                  SQLite Database                    │
              │                  (data/portfolio.db)                │
              │                                                    │
              │  prices    : OHLCV 주가 데이터 (5분/일봉)            │
              │  portfolio : 보유 종목 + 평단 + 수량 (전 계좌)        │
              │  macro     : 금리, 유가, 환율, CPI, Fear&Greed      │
              │  ark       : ARK Invest 일일 매매 내역               │
              │  signals   : 기술적 지표 (RSI, MACD, BB, MA)        │
              │  events    : 실적발표, FOMC, 배당 캘린더              │
              │  factors   : [Phase 3] 멀티팩터 스코어               │
              │  backtests : [Phase 3] 전략 백테스트 결과             │
              │  llm_bench : [Phase 2] LLM 벤치마크 결과             │
              └──────────────────────┬─────────────────────────────┘
                                     ▲
                                     │ cron (자동 수집, 24/7)
                                     │
              ┌──────────────────────┴─────────────────────────────┐
              │                 Data Collectors                     │
              │                                                    │
              │  stock_collector.py    yfinance (OHLCV, 재무, 목표가)│
              │  macro_collector.py    FRED API (금리, CPI, 유가)    │
              │  fear_greed.py         CNN Fear&Greed 스크래핑       │
              │  ark_collector.py      ARK Trade 일일 매매           │
              │  technical.py          ta-lib (RSI, MACD, BB, MA)   │
              │  event_collector.py    실적/FOMC 일정 수집            │
              │  news_collector.py     종목별 뉴스 수집               │
              └────────────────────────────────────────────────────┘
```

### 2-Machine 구조

```
┌──────────────────────────────────┐     git push/pull     ┌──────────────────────────────────┐
│   M3 Max MacBook (Development)   │ ◄──────────────────► │   M2 Pro Mac Mini (Production)   │
│                                  │                       │                                  │
│  • Claude Code 개발 환경          │                       │  • 24/7 상시 가동                  │
│  • Local LLM 벤치마크 (Phase 2)   │                       │  • cron 데이터 수집                │
│  • 퀀트 전략 연구 (Phase 3)       │                       │  • Discord 알림 봇                 │
│  • 백테스트 실행                  │                       │  • SQLite DB 운영                  │
│  • 코드 작성 + 테스트             │                       │  • 안정화된 코드만 배포             │
│                                  │                       │                                  │
│  macOS Sonoma                    │                       │  macOS Ventura                   │
│  RAM: 36/48/64GB                 │                       │  RAM: 32GB                       │
│  User: ehbebe                    │                       │  User: ehbebe                    │
└──────────────────────────────────┘                       └──────────────────────────────────┘
```

---

## Project Structure

```
~/Developer/iris/
├── README.md                           # 이 파일
├── CLAUDE.md                           # Claude Code 프로젝트 컨텍스트
├── .mcp.json                           # MCP 서버 설정 (SQLite)
├── .env.example                        # 환경변수 템플릿
├── .env                                # 환경변수 (git 미추적)
├── .gitignore
├── requirements.txt                    # Python 의존성
├── Makefile                            # 빌드/실행 자동화
│
├── config/
│   ├── portfolio.yaml                  # 전 계좌 보유 종목
│   ├── watchlist.yaml                  # 관심 종목 목록
│   ├── alerts.yaml                     # 알림 조건 설정
│   ├── strategy.yaml                   # [Phase 3] 전략 파라미터
│   └── llm_models.yaml                 # [Phase 2] LLM 모델 목록
│
├── data/
│   ├── portfolio.db                    # SQLite 메인 DB
│   ├── backups/                        # 일일 자동 백업 (30일 보관)
│   └── exports/                        # 리포트 출력물
│
├── iris/                               # 메인 패키지
│   ├── __init__.py
│   ├── db.py                           # DB 연결 + 스키마 관리
│   │
│   ├── collectors/                     # Layer 1: 데이터 수집
│   │   ├── __init__.py
│   │   ├── base.py                     # BaseCollector 추상 클래스
│   │   ├── stock.py                    # yfinance 주가 수집
│   │   ├── macro.py                    # FRED 매크로 지표
│   │   ├── fear_greed.py               # CNN Fear&Greed Index
│   │   ├── ark.py                      # ARK Invest 매매 추적
│   │   ├── technical.py                # ta-lib 기술적 지표
│   │   ├── events.py                   # 이벤트 캘린더
│   │   └── news.py                     # 종목별 뉴스
│   │
│   ├── analysis/                       # Layer 2: 분석 엔진
│   │   ├── __init__.py
│   │   ├── portfolio.py                # 포트폴리오 현황 분석
│   │   ├── performance.py              # 수익률 / 기여도 분석
│   │   ├── correlation.py              # 상관관계 매트릭스
│   │   ├── sector.py                   # 섹터 / 지역 노출도
│   │   ├── risk.py                     # VaR, 샤프비율, 드로다운
│   │   └── rebalance.py                # 리밸런싱 제안
│   │
│   ├── alerts/                         # Layer 3: 알림 시스템
│   │   ├── __init__.py
│   │   ├── discord_bot.py              # Discord 봇
│   │   ├── daily_report.py             # 데일리 리포트 생성
│   │   └── formatters.py               # 메시지 포맷터
│   │
│   ├── quant/                          # [Phase 3] 퀀트 파이프라인
│   │   ├── __init__.py
│   │   ├── factors/                    # 팩터 모델
│   │   │   ├── momentum.py             # 모멘텀 팩터
│   │   │   ├── value.py                # 가치 팩터
│   │   │   ├── quality.py              # 퀄리티 팩터
│   │   │   └── composite.py            # 멀티팩터 종합 스코어
│   │   ├── backtest/                   # 백테스트 엔진
│   │   │   ├── engine.py               # Backtrader 래퍼
│   │   │   ├── strategies.py           # 전략 라이브러리
│   │   │   └── report.py               # 백테스트 리포트
│   │   ├── signals/                    # 트레이딩 시그널
│   │   │   ├── generator.py            # 시그널 생성기
│   │   │   ├── scorer.py               # 종합 스코어링
│   │   │   └── rules.py                # 매매 규칙 엔진
│   │   └── risk/                       # 리스크 관리
│   │       ├── position_sizing.py      # 포지션 사이징
│   │       ├── stop_loss.py            # 손절 규칙
│   │       └── portfolio_optimizer.py  # 포트폴리오 최적화
│   │
│   └── llm/                            # [Phase 2] Local LLM
│       ├── __init__.py
│       ├── benchmark.py                # LLM 벤치마크 프레임워크
│       ├── prompts/                    # 투자 분석용 프롬프트 셋
│       │   ├── market_analysis.py      # 시장 분석 프롬프트
│       │   ├── stock_evaluation.py     # 종목 평가 프롬프트
│       │   ├── risk_assessment.py      # 리스크 평가 프롬프트
│       │   └── news_sentiment.py       # 뉴스 감성 분석
│       ├── evaluator.py                # 응답 품질 평가기
│       └── runner.py                   # Ollama 모델 실행기
│
├── scripts/
│   ├── setup.sh                        # 초기 환경 설정
│   ├── setup_macmini.sh                # 맥미니 프로덕션 설정
│   ├── migrate_db.py                   # DB 스키마 생성/마이그레이션
│   ├── import_portfolio.py             # portfolio.yaml → DB 동기화
│   ├── backup.sh                       # DB 백업 (30일 롤링)
│   └── deploy.sh                       # M3 Max → Mac Mini 배포
│
├── tests/
│   ├── test_collectors.py
│   ├── test_analysis.py
│   ├── test_alerts.py
│   └── test_quant.py
│
├── notebooks/                          # 연구/실험용
│   ├── 01_data_exploration.ipynb
│   ├── 02_technical_signals.ipynb
│   ├── 03_llm_benchmark.ipynb          # [Phase 2] LLM 비교 실험
│   ├── 04_factor_research.ipynb        # [Phase 3] 팩터 연구
│   └── 05_backtest_lab.ipynb           # [Phase 3] 전략 백테스트
│
├── docs/
│   ├── ARCHITECTURE.md                 # 아키텍처 상세 문서
│   ├── DB_SCHEMA.md                    # DB 스키마 문서
│   ├── LLM_BENCHMARK.md               # [Phase 2] 벤치마크 결과
│   ├── QUANT_STRATEGIES.md             # [Phase 3] 전략 문서
│   └── DEPLOYMENT.md                   # 배포 가이드
│
└── crontab.txt                         # 맥미니 cron 스케줄
```

---

## CLAUDE.md

```markdown
# IRIS — Claude Code Project Context

## 프로젝트
IRIS (Investment Research & Intelligence System)
개인 퀀트 투자 분석 플랫폼. 총 자산 2.27억원, 5개 계좌, 27종목.

## 핵심 파일
- DB: data/portfolio.db (SQLite) — MCP로 직접 접근 가능
- 포트폴리오: config/portfolio.yaml
- 알림 설정: config/alerts.yaml
- 전략 파라미터: config/strategy.yaml

## 자주 사용하는 명령
### 포트폴리오 분석
- "내 포트폴리오 현황 보여줘" → python -m iris.analysis.portfolio
- "종목별 비중 분석해줘" → portfolio 테이블 + 현재가 조회
- "섹터 노출도 분석해줘" → python -m iris.analysis.sector
- "리밸런싱 필요한 종목" → python -m iris.analysis.rebalance

### 종목 분석
- "테슬라 기술적 분석" → signals 테이블에서 RSI/MACD/BB 조회
- "엔비디아 펀더멘털" → yfinance 실시간 조회
- "오클로 팔아야 해?" → 기술적 + 펀더멘털 + 매크로 + ARK 종합 판단

### 매크로 / 시장
- "공포탐욕지수 추이" → macro 테이블에서 fear_greed 조회
- "유가와 내 포트폴리오 상관관계" → correlation 분석
- "이번 주 ARK 매매 내역" → ark 테이블 조회
- "다음 주 주요 이벤트" → events 테이블 조회

### 퀀트 (Phase 3)
- "모멘텀 상위 10종목" → python -m iris.quant.factors.momentum
- "내 전략 백테스트 돌려줘" → python -m iris.quant.backtest.engine
- "포트폴리오 최적화해줘" → python -m iris.quant.risk.portfolio_optimizer

## 투자 원칙 (분석 시 항상 참고)
1. 단일 종목 비중 15% 이하 유지
2. 레버리지 ETF(TSLL 등) 장기 보유 금지
3. 분할매수 필수 — 한 번에 몰빵 금지
4. 장 초반 30분(9:00~9:30 한국장, 23:30~00:00 미장) 매수 금지
5. 공포탐욕지수 20 이하 = 우량주 매도 금지, 현금 보존
6. 매매 결정 시 기술적 + 펀더멘털 + 매크로 3가지 모두 확인
7. 모든 시그널은 "판단 보조" — 최종 결정은 사람이 한다

## DB 스키마
- prices: ticker, date, open, high, low, close, volume, adj_close
- portfolio: account, ticker, quantity, avg_price, currency, sector
- macro: indicator, date, value
- ark: date, ticker, direction, shares, weight, fund
- signals: ticker, date, rsi_14, macd, macd_signal, macd_hist, bb_upper, bb_middle, bb_lower, sma_20, sma_50, sma_200, ema_12, ema_26
- events: date, event_type, ticker, description, importance
- factors: [Phase 3] ticker, date, momentum_score, value_score, quality_score, composite_score
- backtests: [Phase 3] strategy_id, start_date, end_date, total_return, sharpe, max_drawdown, win_rate
- llm_bench: [Phase 2] model, prompt_type, response, score, latency_ms, timestamp

## 코드 컨벤션
- Python 3.11+, type hints 사용
- 한국어 주석, 영어 변수명/함수명
- 모든 collector는 BaseCollector 상속
- DB 접근은 iris.db 모듈 통해서만
```

---

## .mcp.json

```json
{
  "mcpServers": {
    "iris-db": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-sqlite",
        "./data/portfolio.db"
      ]
    }
  }
}
```

### Claude Code 연동 확인

```bash
# MCP 연결 테스트
cd ~/Developer/iris
claude

# Claude Code 내에서:
> "iris-db에 연결해서 portfolio 테이블 보여줘"
> "SELECT * FROM prices WHERE ticker='TSLA' ORDER BY date DESC LIMIT 5"
```

---

## config/portfolio.yaml

```yaml
# ═══════════════════════════════════════════════════════
# IRIS Portfolio Configuration
# 마지막 업데이트: 2026-03-25
# ═══════════════════════════════════════════════════════

accounts:

  test:
    name: "Brokerage Alpha Cash Account"
    broker: "Brokerage Alpha Securities"
    currency: USD
    total_invested: 1000000  # KRW
    holdings:
      - { ticker: TSLA,     qty: 33.0016, avg: 200.0, sector: SectorA }
      - { ticker: BULL,     qty: 100,     avg: 47.00,  sector: ETF }
      - { ticker: NVDA,     qty: 20.001,  avg: 100.0, sector: Semiconductor }
      - { ticker: NBIS,     qty: 17,      avg: 109.20, sector: AI/Cloud }
      - { ticker: GOOGL,    qty: 5,       avg: 269.91, sector: BigTech }
      - { ticker: TSLL,     qty: 96,      avg: 20.0,  sector: SectorB, flag: SELL }
      - { ticker: OKLO,     qty: 20,      avg: 150.0, sector: SectorC }
      - { ticker: FIG,      qty: 45,      avg: 43.96,  sector: SaaS }
      - { ticker: LLY,      qty: 1,       avg: 1087.10, sector: Pharma }
      - { ticker: AMD,      qty: 4,       avg: 203.02, sector: Semiconductor }
      - { ticker: HOOD,     qty: 10,      avg: 130.35, sector: Fintech }
      - { ticker: RKLB,     qty: 10,      avg: 65.00,  sector: Aerospace }
      - { ticker: IONQ,     qty: 20,      avg: 55.34,  sector: Quantum }
      - { ticker: ORCL,     qty: 3,       avg: 181.79, sector: Cloud }
      - { ticker: PLTR,     qty: 1,       avg: 174.95, sector: AI/Defense }
      - { ticker: TEM,      qty: 3,       avg: 55.64,  sector: AI/Health }
      - { ticker: "005930.KS", qty: 1,    avg: 55000,  sector: Semiconductor }

  demo:
    name: "Brokerage Beta 추가계좌"
    broker: "Brokerage Beta증권"
    currency: USD
    cash_usd: 8500
    holdings:
      - { ticker: TSLA,     qty: 11,  avg: 350.00, sector: SectorA }
      - { ticker: NVDA,     qty: 11,  avg: 140.00, sector: Semiconductor }
      - { ticker: AMD,      qty: 10,  avg: 200.00, sector: Semiconductor }
      - { ticker: RKLB,     qty: 10,  avg: 60.00,  sector: Aerospace }
      - { ticker: VOO,      qty: 1,   avg: 520.00, sector: ETF }
      - { ticker: GOOGL,    qty: 1,   avg: 270.00, sector: BigTech }
      - { ticker: TEM,      qty: 10,  avg: 55.00,  sector: AI/Health }
      - { ticker: AMZN,     qty: 2,   avg: 200.00, sector: BigTech }
      - { ticker: MSFT,     qty: 1,   avg: 420.00, sector: BigTech }
      - { ticker: PL,       qty: 10,  avg: 5.00,   sector: Aerospace }

  sample:
    name: "토스증권"
    broker: "토스증권"
    currency: KRW
    cash_krw: 840000
    holdings:
      - { ticker: "005930.KS", qty: 4,  avg: 200500,  sector: Semiconductor }
      - { ticker: "000660.KS", qty: 1,  avg: 1012000, sector: Semiconductor }
      - { ticker: "138930.KS", qty: 50, avg: 16580,   sector: Finance }

  pension:
    name: "연금저축 (한화투자증권)"
    broker: "한화투자증권"
    currency: KRW
    balance: 20251604
    monthly_invest: 750000
    auto_invest:
      - { name: "TIGER 미국테크TOP10 INDXX",  amount: 150000 }
      - { name: "TIGER 미국나스닥100(H)",       amount: 130000 }
      - { name: "TIGER 미국S&P500(H)",         amount: 130000 }
      - { name: "PLUS 애플채권혼합",            amount: 120000 }
      - { name: "KODEX 골드선물(H)",            amount: 120000 }
      - { name: "TIGER KRX300",               amount: 100000 }

  irp:
    name: "개인형IRP (하나은행 → 한화이전 예정)"
    broker: "하나은행"
    currency: KRW
    balance: 1391743
    status: "원리금보장형 → 한화투자증권 이전 후 ETF 전환 예정"

# ═══ 비투자 자산 ═══
bank:
  kbank_life: 14707844
  kbank_biz: 10000000
  kbank_plus: 10000000
  others: 24552885
  total: 59260729

real_estate:
  home: 100000000

total_assets: 226907436
```

---

## Phase 1: Foundation (Week 1-3)

> **목표:** 데이터 자동 수집 + Claude Code로 즉시 분석 가능한 환경

### Week 1: 환경 설정 + 데이터 파이프라인

```bash
# Day 1: 프로젝트 초기화
cd ~/Developer
mkdir iris && cd iris
git init

# 의존성 설치
brew install python@3.11 ta-lib node
pip install -r requirements.txt

# DB 초기화
python scripts/migrate_db.py
python scripts/import_portfolio.py

# Day 2-3: Collector 개발
python -m iris.collectors.stock      # 27종목 주가 수집 테스트
python -m iris.collectors.macro      # 매크로 지표 수집 테스트
python -m iris.collectors.technical  # RSI, MACD, BB 계산 테스트

# Day 4-5: MCP 연결 + Claude Code 테스트
claude mcp add iris-db -- npx -y @modelcontextprotocol/server-sqlite \
  ~/Developer/iris/data/portfolio.db
```

### Week 2: 분석 모듈 + Discord 알림

```bash
# Day 1-2: 분석 스크립트 개발
python -m iris.analysis.portfolio    # 포트폴리오 요약
python -m iris.analysis.correlation  # 상관관계 분석
python -m iris.analysis.sector       # 섹터 노출도

# Day 3-4: Discord 봇
python -m iris.alerts.discord_bot    # 봇 실행 테스트
python -m iris.alerts.daily_report   # 리포트 생성 테스트

# Day 5: ARK 추적 + 이벤트 캘린더
python -m iris.collectors.ark
python -m iris.collectors.events
```

### Week 3: 통합 테스트 + 맥미니 배포

```bash
# Day 1-2: 전체 통합 테스트
make test

# Day 3: 맥미니 배포
bash scripts/deploy.sh

# Day 4-5: cron 등록 + 모니터링
ssh macmini "cd ~/iris && crontab crontab.txt"
```

---

## Phase 2: Local LLM Benchmark (Week 4-6)

> **목표:** M3 Max에서 투자 분석에 최적화된 Local LLM 모델 선정

### 벤치마크 대상 모델

| 모델 | 파라미터 | M3 Max 예상 속도 | 특징 |
|------|----------|-----------------|------|
| Qwen3-32B | 32B | ~25 tok/s | 다국어 (한/영) 강점 |
| Qwen3-8B | 8B | ~60 tok/s | 빠른 응답, 가벼움 |
| DeepSeek-R1-32B | 32B | ~20 tok/s | 추론/분석 강점 |
| Llama-3.3-70B-Q4 | 70B (Q4) | ~10 tok/s | 최대 성능 |
| Gemma-3-27B | 27B | ~30 tok/s | 코드/분석 강점 |
| Phi-4-14B | 14B | ~45 tok/s | 소형 고성능 |

### 벤치마크 항목

```yaml
evaluation_criteria:
  market_analysis:
    - "현재 S&P500의 기술적 상태를 분석하고 향후 1주 전망을 제시하세요"
    - "WTI $95, Fear&Greed 14, FOMC 동결 상황에서 포트폴리오 전략은?"
  
  stock_evaluation:
    - "테슬라의 현재 밸류에이션이 적정한지 분석하세요 (PER, 매출성장률, 경쟁사 비교)"
    - "오클로(OKLO)의 매도/보유 판단을 기술적+펀더멘털로 분석하세요"
  
  risk_assessment:
    - "현재 포트폴리오에서 가장 큰 리스크 3가지를 식별하세요"
    - "전쟁 장기화 시 포트폴리오 헤지 전략을 제안하세요"
  
  news_sentiment:
    - "[뉴스 텍스트] 이 뉴스가 테슬라 주가에 미칠 영향을 분석하세요"

scoring:
  accuracy: 40      # 사실 정확성 (할루시네이션 체크)
  depth: 25         # 분석 깊이
  actionability: 20 # 실행 가능한 제안
  latency: 15       # 응답 속도
```

### 실행

```bash
# Ollama 설치 + 모델 다운로드
brew install ollama
ollama pull qwen3:32b
ollama pull deepseek-r1:32b
ollama pull llama3.3:70b-instruct-q4_K_M

# 벤치마크 실행
python -m iris.llm.benchmark --models all --output docs/LLM_BENCHMARK.md

# 최적 모델로 일일 분석 파이프라인 구축
python -m iris.llm.runner --model <best_model> --task daily_analysis
```

---

## Phase 3: Quant Pipeline (Week 7-12)

> **목표:** 팩터 기반 투자 전략 + 백테스트 + 리스크 관리 시스템

### 퀀트 구성 요소

```
┌────────────────────────────────────────────────────────┐
│                   Quant Pipeline                        │
│                                                        │
│  ┌──────────┐   ┌──────────┐   ┌──────────────────┐   │
│  │  Factor   │   │ Signal   │   │  Risk Management │   │
│  │  Models   │──▶│ Generator│──▶│                  │   │
│  │           │   │          │   │  Position Sizing  │   │
│  │ Momentum  │   │ 종합점수  │   │  Stop Loss       │   │
│  │ Value     │   │ 매수/매도 │   │  Portfolio Opt.  │   │
│  │ Quality   │   │ /관망    │   │  Max Drawdown    │   │
│  └──────────┘   └──────────┘   └──────────────────┘   │
│        │                                ▲              │
│        ▼                                │              │
│  ┌──────────────────────────────────────┘              │
│  │        Backtest Engine (Backtrader)                  │
│  │                                                     │
│  │  • 전략 검증 (최소 3년 과거 데이터)                    │
│  │  • 수익률, 샤프비율, 최대 드로다운 측정                 │
│  │  • 워크포워드 분석 (과적합 방지)                       │
│  │  • 벤치마크(VOO) 대비 성과 비교                       │
│  └─────────────────────────────────────────────────────┘
└────────────────────────────────────────────────────────┘
```

### 팩터 모델

| 팩터 | 지표 | 비중 |
|------|------|------|
| Momentum | 12개월 수익률, RSI, 52주 고점 대비 % | 30% |
| Value | PER, PBR, PEG, FCF Yield | 25% |
| Quality | ROE, 영업이익률, 부채비율, 매출성장률 | 25% |
| Sentiment | ARK 매매, 애널리스트 컨센서스, Fear&Greed | 20% |

### 리스크 관리 규칙

```yaml
risk_rules:
  max_single_position: 0.15     # 단일 종목 최대 15%
  max_sector_exposure: 0.35     # 단일 섹터 최대 35%
  max_correlation: 0.80         # 종목 간 상관계수 경고
  stop_loss_pct: -0.20          # 종목별 -20% 손절선
  portfolio_stop: -0.10         # 전체 포트폴리오 -10% 방어
  rebalance_threshold: 0.05    # 목표 비중 ±5% 이탈 시 리밸런싱
  leverage_ban: true            # 레버리지 ETF 보유 금지
  no_buy_first_30min: true      # 장 초반 30분 매수 금지
```

---

## Makefile

```makefile
.PHONY: setup test collect analyze report deploy

# ── 초기 설정 ──
setup:
	bash scripts/setup.sh
	python scripts/migrate_db.py
	python scripts/import_portfolio.py

# ── 데이터 수집 ──
collect:
	python -m iris.collectors.stock
	python -m iris.collectors.macro
	python -m iris.collectors.technical
	python -m iris.collectors.fear_greed
	python -m iris.collectors.ark

# ── 분석 실행 ──
analyze:
	python -m iris.analysis.portfolio
	python -m iris.analysis.sector
	python -m iris.analysis.risk

# ── 일일 리포트 ──
report:
	python -m iris.alerts.daily_report

# ── 테스트 ──
test:
	python -m pytest tests/ -v

# ── LLM 벤치마크 (Phase 2) ──
benchmark:
	python -m iris.llm.benchmark --models all

# ── 백테스트 (Phase 3) ──
backtest:
	python -m iris.quant.backtest.engine

# ── 맥미니 배포 ──
deploy:
	bash scripts/deploy.sh

# ── DB 백업 ──
backup:
	bash scripts/backup.sh
```

---

## requirements.txt

```
# ── Core ──
yfinance>=0.2.36
pandas>=2.2.0
numpy>=1.26.0
pyyaml>=6.0
python-dotenv>=1.0.0

# ── Data Collection ──
fredapi>=0.5.1
requests>=2.31.0
beautifulsoup4>=4.12.0

# ── Technical Analysis ──
TA-Lib>=0.4.28
pandas-ta>=0.3.14b1

# ── Visualization ──
matplotlib>=3.8.0
plotly>=5.18.0
seaborn>=0.13.0

# ── Alerts ──
discord.py>=2.3.0
apscheduler>=3.10.0

# ── Database ──
# SQLite is built-in

# ── Testing ──
pytest>=8.0.0
pytest-cov>=4.1.0

# ── Phase 2: LLM ──
# ollama (brew install)
# httpx>=0.27.0  # Ollama Python client

# ── Phase 3: Quant ──
# backtrader>=1.9.78
# scipy>=1.12.0
# scikit-learn>=1.4.0
# cvxpy>=1.4.0  # Portfolio optimization
```

---

## crontab.txt (맥미니 프로덕션용)

```cron
# ═══════════════════════════════════════
# IRIS Production Cron Schedule
# Mac Mini M2 Pro | 24/7 Operation
# ═══════════════════════════════════════

# ── 미국장 주가 수집 (KST 23:30~06:00, 5분 간격) ──
*/5 23 * * 1-5   cd ~/iris && python -m iris.collectors.stock >> /tmp/iris_stock.log 2>&1
*/5 0-6 * * 2-6  cd ~/iris && python -m iris.collectors.stock >> /tmp/iris_stock.log 2>&1

# ── 한국장 주가 수집 (KST 09:00~15:30, 5분 간격) ──
*/5 9-15 * * 1-5 cd ~/iris && python -m iris.collectors.stock --market kr >> /tmp/iris_stock_kr.log 2>&1

# ── 매크로 지표 (1시간 간격) ──
0 * * * *        cd ~/iris && python -m iris.collectors.macro >> /tmp/iris_macro.log 2>&1

# ── 기술적 지표 계산 (미장 마감 후) ──
0 7 * * 2-6      cd ~/iris && python -m iris.collectors.technical >> /tmp/iris_tech.log 2>&1

# ── Fear & Greed Index (매일 08:00) ──
0 8 * * *        cd ~/iris && python -m iris.collectors.fear_greed >> /tmp/iris_fg.log 2>&1

# ── ARK 매매 추적 (미장 마감 후) ──
30 7 * * 2-6     cd ~/iris && python -m iris.collectors.ark >> /tmp/iris_ark.log 2>&1

# ── 이벤트 캘린더 업데이트 (매일 07:00) ──
0 7 * * *        cd ~/iris && python -m iris.collectors.events >> /tmp/iris_events.log 2>&1

# ── Daily Report (매일 아침 08:00) ──
0 8 * * *        cd ~/iris && python -m iris.alerts.daily_report >> /tmp/iris_report.log 2>&1

# ── DB 백업 (매일 자정) ──
0 0 * * *        cd ~/iris && bash scripts/backup.sh >> /tmp/iris_backup.log 2>&1

# ── 뉴스 수집 (6시간 간격) ──
0 */6 * * *      cd ~/iris && python -m iris.collectors.news >> /tmp/iris_news.log 2>&1
```

---

## .gitignore

```
# Environment
.env
*.pyc
__pycache__/
.venv/
venv/

# Data (DB는 로컬에만 보관)
data/portfolio.db
data/backups/
data/exports/

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db

# Logs
*.log
/tmp/

# Notebooks checkpoints
.ipynb_checkpoints/
```

---

## .env.example

```bash
# ═══ API Keys ═══
FRED_API_KEY=your_fred_api_key_here

# ═══ Discord ═══
DISCORD_TOKEN=your_discord_bot_token_here
DISCORD_CHANNEL_ID=your_channel_id_here

# ═══ Ollama (Phase 2) ═══
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen3:32b

# ═══ Paths ═══
IRIS_DB_PATH=./data/portfolio.db
IRIS_CONFIG_PATH=./config

# ═══ Mac Mini (Production) ═══
MACMINI_HOST=macmini.local
MACMINI_USER=ehbebe
MACMINI_PATH=~/iris
```

---

## 리스크 및 대응

| 리스크 | 영향 | 대응 |
|--------|------|------|
| yfinance API 차단/제한 | 주가 수집 중단 | Alpha Vantage 무료 키 확보 + Rate limit 준수 (2초 간격) |
| 맥미니 전원 차단 | 전체 시스템 중단 | UPS 연결 + launchd 자동 재시작 + 재시작 시 자동 수집 재개 |
| SQLite 데이터 손상 | 누적 데이터 손실 | 매일 자정 자동 백업 (30일 롤링) + Git LFS 백업 |
| Discord 봇 다운 | 알림 수신 불가 | launchd 서비스 등록 + 5분 간격 헬스체크 |
| Local LLM 환각 | 잘못된 분석 제공 | 벤치마크 점수 70점 미만 모델 제외 + 항상 "판단 보조"로만 사용 |
| 과적합된 백테스트 | 실전 성과 괴리 | 워크포워드 분석 필수 + OOS(Out-of-Sample) 검증 |
| 과잉 트레이딩 | 수수료 손실 | 시그널 발생 후 24시간 쿨다운 + 월 매매 횟수 제한 |

---

## Quick Start

```bash
# 1. 프로젝트 생성
cd ~/Developer
git clone <repo> iris && cd iris

# 2. 환경 설정
make setup

# 3. API 키 설정
cp .env.example .env
# FRED_API_KEY, DISCORD_TOKEN 입력

# 4. 첫 데이터 수집
make collect

# 5. Claude Code MCP 연결
claude mcp add iris-db -- npx -y @modelcontextprotocol/server-sqlite \
  ~/Developer/iris/data/portfolio.db

# 6. 분석 테스트
make analyze

# 7. Claude Code에서 자연어 분석
claude
> "내 포트폴리오에서 손실 상위 5개 종목과 대응 전략 알려줘"

# 8. (준비되면) 맥미니 배포
make deploy
```

---

## License

Private repository. Personal use only.

---

> *"The goal of a successful investor is to make the best trades. Money is just the byproduct."* — Alexander Elder

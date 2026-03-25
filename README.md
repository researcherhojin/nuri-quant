# Nuri-Quant (누리퀀트)

> **투자 정보를 수집하고, 검증하고, 실행하는 오픈소스 퀀트 투자 파이프라인**
>
> 누리(世) — 세상의 모든 투자 정보를 모아 수익으로 바꾸는 시스템

---

## What is Nuri-Quant?

Nuri-Quant는 개인 투자자를 위한 **정보 기반 퀀트 투자 플랫폼**입니다.

단순한 주가 수집기가 아닙니다. 다양한 투자 정보를 모으고, 그 정보가 **실제로 수익을 만드는지 검증**하고, 검증된 전략을 **현재 시장 상황에 맞게 추천**하는 전 과정을 자동화합니다.

```
수집(Collect) → 검증(Validate) → 시장판독(Classify) → 진단(Diagnose) → 제안(Recommend) → 추적(Track)
     ↑                                                                          │
     └────────────────────────── 피드백 루프 ────────────────────────────────────┘
```

## Core Process

### 1. Collect — 다양한 투자 정보 수집

단일 소스가 아닌, 실전 투자자가 보는 **모든 카테고리**의 정보를 수집합니다.

| 카테고리 | 정보원 | 데이터 |
|----------|--------|--------|
| **슈퍼인베스터** | Dataroma, ARK Invest, 13F 공시 | 버핏/소로스 포트폴리오, ARK 일일 매매 |
| **매크로** | FRED, TradingEconomics | 금리, CPI, 유가, 환율, VIX, 수익률 곡선 |
| **밸류에이션** | Macrotrends, OpenBB | 장기 PER/PBR/ROE, 재무제표 |
| **애널리스트** | TipRanks | 목표가, 투자의견, 애널리스트 성공률 |
| **ETF/자금흐름** | ETF.com | 섹터 ETF 유입출, 구성종목 변동 |
| **센티먼트** | CNN Fear&Greed, Reddit, 뉴스 | 공포탐욕지수, 소셜 감성, 뉴스 감성 |
| **수급** | pykrx, FINRA | 기관/외국인 매매, 공매도, 풋콜 비율 |
| **가격/기술적** | OpenBB, pykrx, TA-Lib | US/KR OHLCV, RSI, MACD, BB, SMA |

### 2. Validate — 정보의 실제 유효성 검증

> "이 정보를 따라 투자했을 때 **진짜로** 수익이 났는가?"

- **시그널 백테스트**: VectorBT로 각 정보원 기반 전략의 과거 성과 검증
- **정보원별 스코어카드**: 승률, 평균 수익률, 최대 손실을 정보원별로 기록
- **팩터 유효성**: 모멘텀/가치/퀄리티 팩터가 현재 시장에서 작동하는지 검증

### 3. Classify — 시장 상황 판독

> "지금이 어떤 시장인지 알아야, 맞는 전략을 쓸 수 있다"

- **시장 레짐 분류**: 강세/약세/횡보 × 고변동/저변동 자동 판별
- **레짐별 전략 매핑**: "고변동 약세장에서는 A 전략이 유효했다"
- **매크로 환경 스코어**: 금리/유가/환율/VIX 종합 시장 온도계

### 4. Diagnose — 포트폴리오 진단

현재 보유 중인 포트폴리오의 건강 상태를 분석합니다.

- Riskfolio-Lib 기반 리스크 분석 (VaR, CVaR, Sharpe, MaxDD)
- 섹터/지역 집중도 경고
- 종목별 손절선 모니터링
- 상관관계 집중 위험 감지

### 5. Recommend — 맥락적 리밸런싱 제안

단순 수학 최적화가 아니라, **시장 상황 + 검증된 정보**를 반영한 제안입니다.

- MVO / Risk Parity 최적화 (Riskfolio-Lib)
- 투자규칙 자동 적용 (종목 15%, 섹터 35%, 레버리지 금지)
- 시장 레짐에 따른 방어적/공격적 전략 전환
- 검증된 시그널 기반 매수/매도 후보 제시

### 6. Track — 성과 추적 + 피드백

> "제안대로 했더니 실제로 수익이 났는가?"

- 모든 제안을 이력으로 저장
- 제안 vs 실제 성과 비교
- 성과 좋은 전략/정보원의 가중치 자동 증가
- QuantStats HTML 티어시트 자동 생성

---

## Tech Stack

100% 무료 오픈소스로 구성되어 있습니다.

| 영역 | 도구 | 역할 |
|------|------|------|
| 데이터 수집 (US) | **OpenBB Platform v4** | 다중 프로바이더, 에러 핸들링 |
| 데이터 수집 (KR) | **pykrx** | KOSPI/KOSDAQ EOD |
| 매크로 | **FRED API** | 금리, CPI, 유가, 환율 |
| 기술적 지표 | **TA-Lib** | RSI, MACD, BB, SMA, EMA |
| 포트폴리오 최적화 | **Riskfolio-Lib** | MVO, HRP, CVaR, 제약조건 |
| 백테스트 | **VectorBT** | 벡터화, Numba JIT, 초고속 |
| 성과 보고 | **QuantStats** | HTML 티어시트, 30+ 지표 |
| 스케줄링 | **APScheduler** | Python 네이티브 cron |
| 알림 | **Discord Webhook** | 일일 리포트, 급등락 알림 |
| DB | **SQLite** | 경량, 파일 기반 |

---

## Roadmap

### Phase A: 기반 강화 (현재)
- [x] 프로젝트 스켈레톤 + DB 레이어
- [x] 주가 수집 (OpenBB + pykrx)
- [x] 매크로/기술적 지표/Fear&Greed/ARK/뉴스/이벤트 수집
- [x] 포트폴리오 진단 (비중, 섹터, 리스크)
- [x] Riskfolio-Lib 리밸런싱
- [x] QuantStats 성과 보고
- [x] VectorBT 백테스트 엔진
- [x] APScheduler 스케줄러
- [x] Discord 알림
- [ ] 패키지명 iris → nuri 리네이밍 ✅
- [ ] 기관/외국인 수급 수집 (pykrx 확장)
- [ ] 공매도/풋콜 비율 수집 (OpenBB)
- [ ] 미국채 수익률 곡선 (FRED 확장)

### Phase B: 정보원 확장
- [ ] Dataroma 슈퍼인베스터 포트폴리오 스크래핑
- [ ] TipRanks 애널리스트 컨센서스 수집
- [ ] Macrotrends 장기 재무 데이터 수집
- [ ] ETF.com 섹터 자금 흐름 수집
- [ ] SEC 내부자 거래 데이터 (OpenBB)

### Phase C: 검증 엔진 (핵심)
- [ ] 정보원별 시그널 백테스트 프레임워크
- [ ] 전략 스코어카드 DB 스키마 + 자동 기록
- [ ] 팩터 유효성 검증 (시장 레짐별)
- [ ] "ARK 따라하기", "Fear&Greed 극단값 매수" 등 가설 검증

### Phase D: 시장 레짐 판독
- [ ] 시장 상태 분류기 (강세/약세/횡보 × 고변동/저변동)
- [ ] 매크로 환경 스코어링 (시장 온도계)
- [ ] 레짐별 최적 전략 매핑 테이블

### Phase E: 맥락적 제안
- [ ] 시장 레짐 반영 리밸런싱 (방어적/공격적 자동 전환)
- [ ] 검증된 시그널 기반 매수/매도 후보 자동 추출
- [ ] 제안 이력 DB + 성과 추적

### Phase F: 인터페이스 확장
- [ ] REST API 서버 (FastAPI)
- [ ] 웹 대시보드
- [ ] LLM 기반 자연어 리포트 ("왜 이 제안인지" 설명)

---

## Quick Start

```bash
# 1. 클론
git clone https://github.com/researcherhojin/nuri-quant.git
cd nuri-quant

# 2. 환경 설정
make setup    # Python 3.12 venv + 의존성 설치 + DB 초기화

# 3. API 키 설정
cp .env.example .env
# FRED_API_KEY, DISCORD_WEBHOOK_URL 입력

# 4. 데이터 수집
make collect

# 5. 포트폴리오 분석
python -m nuri.analysis.portfolio
python -m nuri.analysis.risk
python -m nuri.analysis.performance --html

# 6. 백테스트
python -m nuri.quant.backtest.engine

# 7. 24/7 자동화
python -m nuri.scheduler
```

---

## Investment Rules (투자 원칙)

코드에 강제 적용되는 투자 규칙입니다.

1. 단일 종목 비중 **15% 이하** 유지
2. 단일 섹터 노출 **35% 이하** 유지
3. 레버리지 ETF 장기 보유 **금지**
4. 분할매수 필수 — 한 번에 몰빵 금지
5. 장 초반 30분 매수 금지
6. Fear&Greed ≤ 20: 우량주 매도 금지
7. 매매 결정 시 기술적 + 펀더멘털 + 매크로 **3가지 모두 확인**
8. 모든 시그널은 "판단 보조" — **최종 결정은 사람**

---

## License

MIT License

---

> *"The goal is not to predict the future, but to be prepared for it."*
> — Pericles

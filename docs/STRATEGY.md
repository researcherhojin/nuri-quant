# Nuri-Quant 전략 정의서

## 핵심 문제

현재 Nuri-Quant은 **결과만 보여주고 과정이 보이지 않습니다.**

```
사용자가 보는 것:  "SELL BULL (conf 90)"
사용자가 봐야 하는 것:
  1. 어떤 데이터를 수집했는지 (15 collectors + 6 sites)
  2. 시그널 검증 결과 (3,400+ 트레이드 중 이 시그널의 승률/PF)
  3. 7개 에이전트가 각각 왜 그 판단을 했는지
  4. SIEGE 10-condition 중 어떤 것이 통과/실패했는지
  5. 그래서 최종 추천이 어떻게 나왔는지
```

**과정이 투명하지 않으면 추천을 신뢰할 수 없습니다.**

## 설계 원칙

1. **과정 > 결과** — 각 단계의 입력→처리→출력을 시각화
2. **Why 기반** — "SELL"이 아니라 "왜 SELL인지" 보여주기
3. **인터랙티브** — 클릭하면 상세 데이터 드릴다운
4. **한 화면 요약** — 메인 대시보드에서 전체 상태 한눈에

## 현재 상태 분석

### 백엔드 (50 API endpoints) — ✅ 충분
- 15 collectors, 7 agents, SIEGE engine, certification, external data
- 대부분의 데이터 파이프라인은 구현 완료

### 프론트엔드 (14 pages) — ❌ 부족
| 문제 | 상세 |
|------|------|
| Nav에 5개 페이지 누락 | targets, advisor, evidence, login, ticker |
| 과정 시각화 없음 | 에이전트 판단 과정, SIEGE gate 과정, 백테스트 과정 |
| 메인 대시보드 정보 부족 | 포트폴리오 평가액/손익, SIEGE 인증, 리밸런스 요약 없음 |
| API 7개 프론트 미연결 | external, certify, regime, macro, ticker 등 |

### README — ❌ 설명 부족
| 문제 | 상세 |
|------|------|
| 기능 나열만 | "무엇을 하는지"는 있지만 "왜, 어떻게 쓰는지" 없음 |
| 완료 로드맵 불필요 | 이슈로 이동하면 됨 |
| SIEGE 레퍼런스 불명확 | 원본과의 관계/차이 설명 부족 |

## 작업 정의

### Issue #8: README 리팩토링 — 설명 중심
- 각 기능에 "이것이 무엇이고, 어떻게 사용하는지" 추가
- Completed Roadmap 섹션 제거 (이슈로 이동)
- SIEGE 레퍼런스: 원본 링크 + 우리의 적용 방식 명시
- 오픈소스 레퍼런스 출처 명시 (O'Neil, Minervini 등)

### Issue #9: Nav + 메인 대시보드 강화
- Nav에 누락 페이지 추가 (grouped navigation)
- 메인 대시보드에 포트폴리오 요약 + SIEGE 인증 + 리밸런스 요약
- Nuri-Quant 로고 클릭 → Overview 이동

### Issue #10: 파이프라인 과정 시각화
- 7-Agent 합의 과정 (에이전트별 판단 근거 + 투표 시각화)
- SIEGE 10-Condition Gate 시각화 (각 조건 pass/fail 이유)
- 시그널 백테스트 결과 시각화 (승률/PF 차트)

### Issue #11: 미연결 API 프론트 연동
- /api/external → 외부 데이터 조회 UI
- /api/certify (신규) → SIEGE 인증 API + 대시보드 배지
- /api/ticker/{symbol} → 종목 상세 페이지 개선

## 오픈소스 레퍼런스

### 투자 이론/규칙 출처

| 출처 | 적용 부분 | 우리 코드 |
|------|----------|----------|
| **O'Neil CAN SLIM** | 손절 -7%, 익절 +20%/+40% | `config/rules.yaml` stop_loss/take_profit |
| **Minervini SEPA** | 트레일링 -15%, 8주 규칙 | `config/rules.yaml` trailing_stop, eight_week_hold |
| **처분효과** (Shefrin 1985) | 수익 종목 너무 일찍 파는 편향 경고 | 익절 규칙의 근거 |
| **트레일링 스톱 백테스트** (11년) | 15-20%가 최적 수익 (73.9% 누적) | trailing_stop: -15% 설정 근거 |

### 아키텍처/엔진 출처

| 출처 | 적용 부분 | 우리 코드 |
|------|----------|----------|
| **SIEGE** (nutshells3) | 10-condition gate, certification | `nuri/trading/engine/gate.py`, `certification.py` |
| **Riskfolio-Lib** | MVO/Risk Parity 최적화 | `nuri/analysis/rebalance.py` |
| **VectorBT** | 벡터 기반 백테스트 | `nuri/quant/backtest/engine.py` |

### UX/시각화 참고 프로젝트

| 프로젝트 | 배울 점 | 적용 계획 |
|----------|--------|----------|
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | 에이전트별 판단 과정 스트리밍 | Issue #10: consensus 페이지 에이전트 추론 시각화 |
| [Aragora](https://github.com/synaptent/aragora) | 에이전트 합의/반대 의견 시각화, ELO 신뢰도 | Issue #10: dissent trail, 에이전트 신뢰도 추적 |
| [OpenAlgo Flow](https://github.com/marketcalls/openalgo-flow) | React Flow 노드 기반 파이프라인 시각화 | Issue #10: 6-step pipeline 인터랙티브 그래프 |
| [OpenAlice](https://github.com/TraderAlice/OpenAlice) | Git-like guard gate + SSE 스트리밍 | Issue #10: SIEGE gate 시각화 (이미 SSE 있음) |
| [Ghostfolio](https://github.com/ghostfolio/ghostfolio) | 미니멀 대시보드 + progressive disclosure | Issue #9: 메인 대시보드 UX |
| [FreqUI](https://www.freqtrade.io/en/stable/freq-ui/) | 백테스트 시그널 마커 + 비교 | Issue #10: 백테스트 시각화 |
| [TradeMaster PRUDEX-Compass](https://github.com/TradeMaster-NTU/TradeMaster) | 레이더 차트 다차원 평가 | Issue #10: 시그널 품질 레이더 차트 |

### 적용 우선 기술

| 기술 | 용도 | 라이센스 |
|------|------|---------|
| **React Flow** (xyflow) | 파이프라인 DAG 시각화 | MIT |
| **Recharts** (이미 사용 중) | 차트 | MIT |
| **SSE** (이미 구현) | 실시간 파이프라인 진행 표시 | — |

## 작업 순서

```
1. README 리팩토링 (설명 중심, 완료 로드맵 제거)
2. GitHub Issues 생성 (#8~#11)
3. Nav + 메인 대시보드 강화 (빠른 수정)
4. 미연결 API 프론트 연동
5. 파이프라인 과정 시각화 (큰 작업)
```

# Nuri-Quant 전략 정의서

## 설계 원칙

1. **과정 > 결과** — 각 단계의 입력→처리→출력을 시각화
2. **Why 기반** — "SELL"이 아니라 "왜 SELL인지" 보여주기
3. **인터랙티브** — 클릭하면 상세 데이터 드릴다운
4. **한 화면 요약** — 메인 대시보드에서 전체 상태 한눈에

## 현재 상태

### 백엔드 — ✅ 충분
- 21 collectors, 15 signals (detector registry), 10 regimes (6 base + 4 special)
- 10 agents + consensus engine, SIEGE 10-condition gate
- 투자 규칙 자동화: take-profit, trailing stop, portfolio MDD gate
- Pipeline observability: Event Journal + Freshness SLA + Operator Cockpit
- 53 API endpoints, 27 tables (v11 migrations), 2166 backend + 421 frontend tests

### 프론트엔드 — 진행 중
- 15 pages, dark mode, Palantir-style dashboard
- Signal × Regime 교차분석, Recovery 레짐 표시 확인
- 미구현: 에이전트 reasoning trace, SIEGE 드릴다운, 백테스트 인터랙티브 차트

## 오픈소스 레퍼런스

### 투자 이론/규칙 출처

| 출처 | 적용 부분 | 코드 위치 |
|------|----------|----------|
| **O'Neil CAN SLIM** | 손절 -7%, 익절 +20%/+40% | `config/rules.yaml` stop_loss/take_profit |
| **Minervini SEPA** | 트레일링 -15%, 8주 규칙 | `config/rules.yaml` trailing_stop |
| **처분효과** (Shefrin 1985) | 수익 종목 조기 매도 편향 경고 | 익절 규칙의 이론적 근거 |
| **트레일링 스톱 백테스트** (11년) | 15-20%가 최적 수익 (73.9% 누적) | trailing_stop: -15% 설정 근거 |

### 아키텍처/엔진 출처

| 출처 | 적용 부분 | 코드 위치 |
|------|----------|----------|
| [**SIEGE**](https://github.com/nutshells3/Swarm-Intelligence-Engine-with-Gated-Execution) | 10-condition gate, event journal | `nuri/trading/engine/` |
| [**Palantir Foundry**](https://www.palantir.com/docs/foundry/data-lineage/overview) | Data Health, pipeline monitoring | `nuri/core/freshness.py`, `nuri/core/events.py` |
| [**Dagster**](https://docs.dagster.io/guides/observe/asset-freshness-policies) | Asset freshness PASS/WARN/FAIL | `nuri/core/freshness.py` |
| [**TradingAgents**](https://github.com/TauricResearch/TradingAgents) | 멀티에이전트 합의 패턴 | `nuri/trading/agents/` |
| [**Riskfolio-Lib**](https://riskfolio-lib.readthedocs.io/) | MVO/Risk Parity 최적화 | `nuri/analysis/rebalance.py` |
| [**VectorBT**](https://vectorbt.dev/) | 벡터 기반 백테스트 | `nuri/quant/backtest/engine.py` |

### UX/시각화 참고

| 프로젝트 | 참고 포인트 |
|----------|------------|
| [Ghostfolio](https://github.com/ghostfolio/ghostfolio) | 미니멀 대시보드, progressive disclosure |
| [React Flow](https://reactflow.dev/) | 파이프라인 DAG 시각화 |
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | 에이전트별 판단 과정 스트리밍 |
| [FreqUI](https://www.freqtrade.io/en/stable/freq-ui/) | 백테스트 시그널 마커 |

## TODO (우선순위 순)

### 코드 품질
- [ ] pytest markers (`@pytest.mark.slow`) + CI fast/slow 분리
- [ ] 커버리지 93% → 98% (#71) — `__main__` 블록 + 나머지 분기

### 프론트엔드 기능 — 미구현
- [ ] 에이전트 reasoning trace — consensus 페이지에서 각 에이전트 판단 과정 스트리밍
- [ ] SIEGE 드릴다운 — engine 페이지에서 10개 조건별 상세 클릭
- [ ] 백테스트 인터랙티브 차트 — strategy 페이지에서 파라미터 조절 + 실시간 시뮬레이션
- [ ] 투자 규칙 UI (#42) — 익절 하이라이트, 반포지션 경고, 트레일링 스톱 시각화

### 실전 연동 (#17)
- [ ] Alpaca Paper → Live 전환 (이중 확인: SIEGE CERTIFIED + 수동 승인)
- [ ] 자동 매도 실행 (익절/손절 도달 시 자동 지정가 매도)
- [ ] 멀티 포트폴리오 (계좌별 독립 분석 + Dashboard 계좌 전환)

### 포트폴리오 온보딩 (#25)
- [ ] 브로커 API 연동 (Alpaca/한국 증권사 자동 동기화)

## 관련 이슈

- #17: 실전 연동 — Alpaca live + 멀티 포트폴리오
- #25: 포트폴리오 온보딩 — Dashboard UI 입력
- #71: 커버리지 93% → 98%

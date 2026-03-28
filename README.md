# Nuri-Quant (누리퀀트)

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/Tests-503_passed-26a69a?logo=pytest&logoColor=white)]()
[![Coverage](https://codecov.io/gh/researcherhojin/nuri-quant/graph/badge.svg)](https://codecov.io/gh/researcherhojin/nuri-quant)
[![License](https://img.shields.io/badge/License-AGPL_3.0-blue.svg)](LICENSE)
[![CI](https://img.shields.io/badge/CI-passing-4CAF50?logo=githubactions&logoColor=white)]()

**[API Docs](http://localhost:8001/docs)** · **[Dashboard](http://localhost:3000)** · **[Issues](https://github.com/researcherhojin/nuri-quant/issues)**

</div>

주식을 사거나 팔 때, 근거 없이 감으로 하고 있지 않나요?

Nuri-Quant은 **"왜 이 종목을 사야/팔아야 하는지"를 데이터로 증명**하는 오픈소스 퀀트 투자 플랫폼입니다. 21개 수집기로 데이터를 모으고, 3,400건 이상의 과거 트레이드로 시그널을 검증하고, 7개 전문 에이전트가 독립적으로 분석한 뒤 투표하고, 10개 규칙을 기계적으로 검증해서 — 최종 추천이 나옵니다.

## 파이프라인

```mermaid
graph LR
    A["🔍 수집<br/>21 collectors<br/>+ 11 외부 사이트"] --> B["✅ 검증<br/>3,400+ 트레이드<br/>시그널 백테스트"]
    B --> C["📊 분류<br/>6-레짐 분류<br/>bull/bear/sideways"]
    C --> D["🤖 판단<br/>7 에이전트<br/>가중 투표"]
    D --> E["🔒 인증<br/>SIEGE 10-조건<br/>pass / reject"]
    E --> F["📋 추천<br/>매수가/손절가<br/>익절가 제시"]

    style A fill:#e8eaf6,stroke:#5c6bc0
    style B fill:#e8f5e9,stroke:#66bb6a
    style C fill:#fff3e0,stroke:#ffa726
    style D fill:#e3f2fd,stroke:#42a5f5
    style E fill:#fce4ec,stroke:#ef5350
    style F fill:#f3e5f5,stroke:#ab47bc
```

| 단계 | 설명 |
|------|------|
| **수집** | 미국/한국 주가, 매크로 지표, Fear&Greed, 13F, 애널리스트 목표가 + 11개 외부 사이트 (TipRanks, Dataroma, CBOE, CoinGecko, Reddit/WSB 등) |
| **검증** | 3,400건+ 과거 트레이드로 시그널 백테스트. 최근 성과 급락 시그널은 Learning Memory가 자동 신뢰도 하향 |
| **분류** | SPY 가격, SMA50/200, VIX 기반 6개 레짐 분류. VIX 25+ 시 적응형 히스테리시스로 빠른 전환 |
| **판단** | 7개 에이전트 독립 분석 + 가중 투표. Risk 에이전트 거부권: confidence 80 이상 시 전원 BUY여도 SELL 강제 |
| **인증** | [SIEGE Engine](https://github.com/nutshells3/Swarm-Intelligence-Engine-with-Gated-Execution) — 10개 규칙 기계적 검증. 하나라도 error면 REJECTED |
| **추천** | 매수가, 손절가(-7%), 1차 익절(+20%, 50% 매도), 2차 익절(+40%, 25% 매도), 트레일링 스톱(-15%) |

## Quick Start

```bash
# Prerequisites: Python 3.12, uv, brew install ta-lib
git clone https://github.com/researcherhojin/nuri-quant.git && cd nuri-quant
make setup         # venv + deps + DB init + portfolio import
cp .env.example .env
cp config/portfolio.example.yaml config/portfolio.yaml  # 본인 포트폴리오 편집
make full-scan     # 전체 파이프라인 실행 (수집→검증→분류→판단→인증→추천→시각화→알림)
```

<details>
<summary><b>전체 명령어</b></summary>

| Command | 설명 |
|---------|------|
| `make full-scan` | 전체 파이프라인 8단계 실행 |
| `make quick-scan` | 수집→분석→합의→타겟 (~2분) |
| `make consensus` | 7에이전트 합의 + 가격 타겟 |
| `make certify` | SIEGE 10-condition 인증 |
| `make targets` | 전 종목 매수가/손절가/익절가 |
| `make rebalance` | 규칙 위반 감지 + 매도 수량 |
| `make evidence` | 5개 Plotly 증거 차트 |
| `make report-llm` | Qwen3.5 LLM 증거 기반 리포트 |
| `make start` | API(:8001) + Dashboard(:3000) 동시 실행 |
| `make test` | pytest 503 tests (58% coverage) |

</details>

## 투자 규칙

`config/rules.yaml`에 정의. [O'Neil (CAN SLIM)](https://www.investors.com/) + [Minervini (SEPA)](https://www.minervini.com/) + [처분효과 연구](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1985.tb05002.x) 기반.

| | 성장주 | 가치주 | 스윙 |
|---|--------|-------|------|
| **손절** | -7% | -10% | -5% |
| **1차 익절** | +20% → 50% 매도 | +15% → 50% 매도 | +5% → 50% 매도 |
| **2차 익절** | +40% → 25% 매도 | +30% → 25% 매도 | +10% → 전량 |
| **나머지** | 트레일링 -15% | 트레일링 -15% | — |

**핵심 규칙:**
- VIX > 30 → 신규 매수 금지 (승률 급락 구간)
- 매수 체크리스트: TipRanks ≥ Moderate Buy, 슈퍼투자자 3명+, PE < 100, 매출 > $0, 멀티팩터 상위 50%
- 매도 우선순위: 레버리지 ETF → 손절선 초과 → 슈퍼투자자 0명 → 비중 초과 → 섹터 초과

## Tech Stack

### 1. 수집 (Collect)

[![OpenBB](https://img.shields.io/badge/OpenBB-4.6-00C853?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZD0iTTEyIDJMMiAyMmgyMEwxMiAyeiIgZmlsbD0id2hpdGUiLz48L3N2Zz4=&logoColor=white)]()
[![yfinance](https://img.shields.io/badge/yfinance-0.2-7B1FA2)]()
[![pykrx](https://img.shields.io/badge/pykrx-1.2-1565C0)]()
[![FRED](https://img.shields.io/badge/FRED_API-macro-FF6F00)]()
[![TA--Lib](https://img.shields.io/badge/TA--Lib-0.4-FF5722)]()
[![finvizfinance](https://img.shields.io/badge/finvizfinance-1.3-607D8B)]()
[![edgartools](https://img.shields.io/badge/edgartools-13F-795548)]()

> 21 collectors + 11 외부 사이트 (TipRanks · Dataroma · CBOE · CoinGecko · Reddit/WSB · ARK · ETF.com · Macrotrends · TradingEcon · Short Interest · FINVIZ)

### 2. 분석 (Quant)

[![pandas](https://img.shields.io/badge/pandas-2.2-150458?logo=pandas&logoColor=white)]()
[![scikit--learn](https://img.shields.io/badge/scikit--learn-1.4-F7931E?logo=scikit-learn&logoColor=white)]()
[![Riskfolio](https://img.shields.io/badge/Riskfolio--Lib-7.0-2196F3)]()
[![VectorBT](https://img.shields.io/badge/VectorBT-0.28-9C27B0)]()
[![cvxpy](https://img.shields.io/badge/cvxpy-1.4-00897B)]()

### 3. 백엔드 (API)

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)]()
[![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?logo=sqlite&logoColor=white)]()
[![Pydantic](https://img.shields.io/badge/Pydantic-v2-E92063?logo=pydantic&logoColor=white)]()

> 41 endpoints · 27 tables · SSE stream · JWT + bcrypt + slowapi

### 4. 프론트엔드 (Dashboard)

[![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=next.js&logoColor=white)]()
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)]()
[![Tailwind](https://img.shields.io/badge/Tailwind-4-06B6D4?logo=tailwindcss&logoColor=white)]()
[![shadcn/ui](https://img.shields.io/badge/shadcn/ui-latest-000000)]()

> 13 pages · Dark/Light mode · React Flow 파이프라인 시각화

### 5. LLM

[![Ollama](https://img.shields.io/badge/Ollama-local-000000)]()
[![Qwen](https://img.shields.io/badge/Qwen3.5-35B_MoE-7C3AED)]()

### 6. CI/CD

[![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-CI-2088FF?logo=githubactions&logoColor=white)]()
[![Ruff](https://img.shields.io/badge/Ruff-linter-D7FF64?logo=ruff&logoColor=black)]()
[![Codecov](https://img.shields.io/badge/Codecov-coverage-F01F7A?logo=codecov&logoColor=white)]()
[![Trivy](https://img.shields.io/badge/Trivy-security-1904DA)]()

## 레퍼런스

### 투자 이론

| 출처 | 적용 |
|------|------|
| [O'Neil — CAN SLIM](https://www.investors.com/) | 손절 -7%, 익절 +20%/+40% |
| [Minervini — SEPA](https://www.minervini.com/) | 트레일링 스톱, 3:1 손익비 |
| [Shefrin 1985 — 처분효과](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1985.tb05002.x) | 수익 종목 조기 매도 편향 경고 |

### 아키텍처 & 오픈소스

| 출처 | 적용 |
|------|------|
| [SIEGE Engine](https://github.com/nutshells3/Swarm-Intelligence-Engine-with-Gated-Execution) | 10-condition gate, certification |
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | 멀티에이전트 합의 패턴 |
| [Riskfolio-Lib](https://riskfolio-lib.readthedocs.io/) | MVO/Risk Parity 최적화 |
| [VectorBT](https://vectorbt.dev/) | 벡터 기반 백테스트 |
| [Ghostfolio](https://github.com/ghostfolio/ghostfolio) | 대시보드 UX |
| [React Flow](https://reactflow.dev/) | 파이프라인 DAG 시각화 |

## License

[GNU Affero General Public License v3.0](LICENSE)

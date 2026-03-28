# Nuri-Quant (누리퀀트)

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/Tests-188_passed-26a69a?logo=pytest&logoColor=white)]()
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-3.0.0-orange)]()
[![CI](https://img.shields.io/badge/CI-passing-4CAF50?logo=githubactions&logoColor=white)]()

**[API Swagger](http://localhost:8001/docs)** · **[Dashboard](http://localhost:3000)** · **[Docs](CLAUDE.md)** · **[Issues](https://github.com/researcherhojin/nuri-quant/issues)**

100% 무료 오픈소스 퀀트 투자 플랫폼.<br/>
15개 수집기 + 6개 외부 사이트 → 시그널 백테스트 → 6-레짐 분류 → 7-에이전트 합의 → SIEGE 인증

</div>

## Pipeline

```mermaid
graph LR
    A["🔍 Collect<br/>15 collectors<br/>+ 6 external"] --> B["✅ Validate<br/>3,400+ trades<br/>backtest"]
    B --> C["📊 Classify<br/>6 regimes<br/>dynamic threshold"]
    C --> D["🧠 Diagnose<br/>macro score<br/>signal drift"]
    D --> E["🤖 Recommend<br/>7 agents<br/>weighted vote"]
    E --> F["📋 Certify<br/>SIEGE 10-cond<br/>pass / reject"]

    style A fill:#e8eaf6,stroke:#5c6bc0
    style B fill:#e8f5e9,stroke:#66bb6a
    style C fill:#fff3e0,stroke:#ffa726
    style D fill:#fce4ec,stroke:#ef5350
    style E fill:#e3f2fd,stroke:#42a5f5
    style F fill:#f3e5f5,stroke:#ab47bc
```

## Tech Stack

**Data** (15 collectors)<br/>
[![OpenBB](https://img.shields.io/badge/OpenBB-4.6-6366F1)](https://openbb.co/)
[![yfinance](https://img.shields.io/badge/yfinance-0.2-800080)](https://pypi.org/project/yfinance/)
[![pykrx](https://img.shields.io/badge/pykrx-1.2-FF4081)](https://github.com/sharebook-kr/pykrx)
[![edgartools](https://img.shields.io/badge/edgartools-5.0-4CAF50)](https://github.com/dgunning/edgartools)
[![FRED](https://img.shields.io/badge/FRED-API-1565C0)](https://fred.stlouisfed.org/)
[![TA--Lib](https://img.shields.io/badge/TA--Lib-0.4-FF9800)](https://ta-lib.org/)

**External** (6 sites)<br/>
[![TipRanks](https://img.shields.io/badge/TipRanks-analyst-1E88E5)](https://www.tipranks.com/)
[![Dataroma](https://img.shields.io/badge/Dataroma-13F-43A047)](https://www.dataroma.com/)
[![Macrotrends](https://img.shields.io/badge/Macrotrends-PE/Rev-7B1FA2)](https://www.macrotrends.net/)
[![ARK](https://img.shields.io/badge/ARK-Cathie_Wood-FF6D00)](https://ark-funds.com/)
[![ETF.com](https://img.shields.io/badge/ETF.com-flows-00897B)](https://www.etf.com/)
[![TradingEconomics](https://img.shields.io/badge/TradingEcon-macro-D32F2F)](https://tradingeconomics.com/)

**Quant**<br/>
[![pandas](https://img.shields.io/badge/pandas-2.2-150458?logo=pandas&logoColor=white)](https://pandas.pydata.org/)
[![numpy](https://img.shields.io/badge/numpy-1.26-013243?logo=numpy&logoColor=white)](https://numpy.org/)
[![Riskfolio](https://img.shields.io/badge/Riskfolio--Lib-7.0-E91E63)](https://riskfolio-lib.readthedocs.io/)
[![VectorBT](https://img.shields.io/badge/VectorBT-0.28-FF5722)](https://vectorbt.dev/)
[![scikit--learn](https://img.shields.io/badge/scikit--learn-1.4-F7931E?logo=scikit-learn&logoColor=white)](https://scikit-learn.org/)

**Backend** (14 API routes)<br/>
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![uvicorn](https://img.shields.io/badge/uvicorn-0.32-2196F3)](https://www.uvicorn.org/)
[![Pydantic](https://img.shields.io/badge/Pydantic-v2-E92063?logo=pydantic&logoColor=white)](https://docs.pydantic.dev/)
[![SSE](https://img.shields.io/badge/SSE-stream-607D8B)](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)

**Frontend** (12 pages)<br/>
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=next.js&logoColor=white)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![Tailwind](https://img.shields.io/badge/Tailwind-4-06B6D4?logo=tailwindcss&logoColor=white)](https://tailwindcss.com/)
[![shadcn/ui](https://img.shields.io/badge/shadcn/ui-latest-000000)](https://ui.shadcn.com/)
[![Recharts](https://img.shields.io/badge/Recharts-2.0-8884D8)](https://recharts.org/)

**LLM**<br/>
[![Ollama](https://img.shields.io/badge/Ollama-Qwen3.5-FF6600)](https://ollama.com/)
[![Qwen](https://img.shields.io/badge/Qwen3.5-35B_A3B_MoE-7C4DFF)](https://qwenlm.github.io/)

**Viz** (5 evidence charts)<br/>
[![Plotly](https://img.shields.io/badge/Plotly-5.18-3F4F75?logo=plotly&logoColor=white)](https://plotly.com/)
[![Matplotlib](https://img.shields.io/badge/Matplotlib-3.8-11557C)](https://matplotlib.org/)
[![mplfinance](https://img.shields.io/badge/mplfinance-0.12-2E7D32)](https://github.com/matplotlib/mplfinance)

**DB & Infra**<br/>
[![SQLite](https://img.shields.io/badge/SQLite-WAL_27_tables-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![APScheduler](https://img.shields.io/badge/APScheduler-17_cron-795548)](https://apscheduler.readthedocs.io/)
[![Discord](https://img.shields.io/badge/Discord-Bot-5865F2?logo=discord&logoColor=white)](https://discord.com/)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?logo=telegram&logoColor=white)](https://telegram.org/)

**Security** (5 layers)<br/>
[![JWT](https://img.shields.io/badge/JWT-Auth-000000?logo=jsonwebtokens&logoColor=white)](https://jwt.io/)
[![bcrypt](https://img.shields.io/badge/bcrypt-hash-424242)](https://pypi.org/project/bcrypt/)
[![slowapi](https://img.shields.io/badge/slowapi-rate_limit-FF7043)](https://github.com/laurentS/slowapi)
[![CSP](https://img.shields.io/badge/CSP-HSTS-1B5E20)](https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP)
[![audit](https://img.shields.io/badge/audit-log-37474F)](https://en.wikipedia.org/wiki/Audit_trail)

**CI/CD** (3 jobs)<br/>
[![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-CI-2088FF?logo=githubactions&logoColor=white)](https://github.com/features/actions)
[![ruff](https://img.shields.io/badge/ruff-lint-D7FF64)](https://docs.astral.sh/ruff/)
[![pytest](https://img.shields.io/badge/pytest-188_tests-0A9EDC?logo=pytest&logoColor=white)](https://docs.pytest.org/)
[![Trivy](https://img.shields.io/badge/Trivy-security-1904DA)](https://trivy.dev/)

## Getting Started

```bash
# Prerequisites: Python 3.12, uv, brew install ta-lib
git clone https://github.com/researcherhojin/nuri-quant.git && cd nuri-quant
make setup         # venv + deps + DB init + portfolio import
cp .env.example .env
```

### Commands

> `make full-scan` — 수집부터 증거 시각화 + SIEGE 인증 + 알림까지 한번에.

<details>
<summary><b>전체 명령어</b></summary>

| Command | Description |
|---------|-------------|
| `make full-scan` | 8-phase 전체 파이프라인 |
| `make quick-scan` | 빠른 4-step (~2분) |
| `make consensus` | 7-에이전트 합의 + 가격 타겟 |
| `make targets` | 전 종목 매수가/손절가/익절가 |
| `make rebalance` | 규칙 위반 감지 + 매도 수량 |
| `make certify` | SIEGE 10-condition 인증 |
| `make evidence` | 5개 Plotly 증거 차트 |
| `make report-llm` | Qwen3.5 LLM 리포트 |
| `make external` | 외부 데이터 요약 |
| `make test` | pytest 188 tests |
| `make lint` | ruff check |
| `make start` | API + Dashboard 동시 실행 |

</details>

## Architecture

```mermaid
graph LR
    subgraph Collect["Data Collection"]
        S[16 collectors] --> DB[(SQLite WAL<br/>27 tables)]
        EX[6 external sites] --> DB
    end

    subgraph Quant["Validate + Classify"]
        DB --> BT[Signal Backtest<br/>3,400+ trades]
        DB --> RC[Regime Classifier<br/>6 regimes]
        BT --> XA[signal × regime]
    end

    subgraph Agents["7-Agent Consensus"]
        XA --> AG[Weighted Vote]
        RC --> SM[Strategy Map]
        AG --> REC[Candidates]
        SM --> REC
    end

    subgraph SIEGE["SIEGE Engine"]
        GT[10-Cond Gate] --> REC
        CF[Conflict Detect] --> REC
        LM[Learning Memory] --> REC
        CERT[Certification] --> REC
    end

    subgraph Output["Interface"]
        REC --> API[FastAPI :8001]
        API --> NX[Next.js :3000]
        API --> LLM[Qwen3.5 Report]
        API --> AL[Discord + Telegram]
    end

    style Collect fill:#e8eaf6
    style Quant fill:#e8f5e9
    style Agents fill:#fff3e0
    style SIEGE fill:#fce4ec
    style Output fill:#e3f2fd
```

## SIEGE Engine

[Swarm Intelligence Engine with Gated Execution](https://github.com/nutshells3/Swarm-Intelligence-Engine-with-Gated-Execution) 아키텍처를 투자 도메인에 적용.

| Component | Original SIEGE | Nuri-Quant Implementation |
|-----------|---------------|--------------------------|
| **Planning Gate** | 10-condition machine check | 10개 규칙 기계 검증 (`make certify`) |
| **Multi-Agent** | LLM agent dispatch | 7 domain agents + weighted vote |
| **Conflict Detection** | Code merge conflicts | BUY/SELL direction conflicts |
| **Learning Memory** | Execution failure retry | Signal drift → confidence penalty |
| **Certification** | OAE formal assurance | rules.yaml 기반 pass/reject |

### 10-Condition Certification

```
make certify

═══════════════════════════════════════════════════════
  SIEGE Certificate — CERTIFIED (90%)
═══════════════════════════════════════════════════════
  ✅ 종목 비중 <= 15%
  ✅ 섹터 비중 <= 35%
  ✅ 손절선 준수
  ✅ 데이터 신선도 (72h)
  ✅ 레버리지 ETF 비보유
  ⚠️ VIX > 30 매수 차단
  ✅ 외부 데이터 충분
  ✅ 방향 충돌 해소
  ⚠️ 시그널 drift 안전
  ✅ rules.yaml 완전 로드
═══════════════════════════════════════════════════════
```

## 7-Agent Consensus

| Agent | Weight | Role |
|-------|--------|------|
| Technical | 18% | RSI, MACD, SMA crossovers |
| Fundamental | 14% | PE, ROE, growth, debt |
| Macro | 14% | Regime + macro score |
| **Risk** | **22%** | **Veto power** (conf ≥ 80 → SELL) |
| Smart Money | 9% | 13F + analyst consensus |
| Wall Street | 13% | Ratings + EPS surprise + insider |
| Korean Market | 10% | KRW/USD FX, KOSPI |

## Investment Rules

`config/rules.yaml` — O'Neil (CAN SLIM) + Minervini (SEPA) 기반.

| Category | Growth | Value | Swing |
|----------|--------|-------|-------|
| **Stop Loss** | -7% | -10% | -5% |
| **Target 1** | +20% (50% sell) | +15% (50% sell) | +5% (50% sell) |
| **Target 2** | +40% (25% sell) | +30% (25% sell) | +10% (all) |
| **Trailing** | -15% from high | -15% from high | -20% |

| Gate | Condition |
|------|-----------|
| VIX > 30 | **Block** new buys |
| VIX 25-30 | Half position only |
| F&G < 20 | Cash 60% |
| Position | Max 15% per stock |
| Sector | Max 35% per sector |

<details>
<summary><b>매수 체크리스트 + 매도 우선순위</b></summary>

**Buy checklist**: TipRanks ≥ Moderate Buy · superinvestors ≥ 3 · PE < 100 · revenue > $0 · factor top 50%

**Sell priority**: 1. Leverage ETF → 2. Stop-loss exceeded → 3. No superinvestor + loss → 4. Overweight → 5. Sector overweight

</details>

## Completed Roadmap

보안 감사 (OWASP + STRIDE) 기반 — **17/17 항목 완료**.

<details>
<summary>CRITICAL 5/5 · HIGH 6/6 · MEDIUM 6/6</summary>

**CRITICAL**: JWT auth · bcrypt hashing · rate limiting · CORS · input validation

**HIGH**: Audit log · Monte Carlo block bootstrap · partial fill · DB migration · collection failure guard · CSP/HSTS

**MEDIUM**: Data freshness · adaptive hysteresis · FX calibration · SSE cache · evidence charts · Telegram

</details>

## Next Phase

- [ ] 외부 데이터 수집기 완전 자동화 — TipRanks/Dataroma scraping
- [ ] 백테스트에 신규 익절/손절 규칙 적용 → 성과 검증
- [ ] 대시보드 가격 타겟 + 리밸런스 어드바이저 페이지
- [ ] Alpaca 실전 연동 (paper → live)
- [ ] 멀티 포트폴리오 지원

## License

[Apache License 2.0](LICENSE)

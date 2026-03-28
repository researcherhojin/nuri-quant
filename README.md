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

<div align="center">

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=next.js&logoColor=white)](https://nextjs.org/)
[![Ollama](https://img.shields.io/badge/Ollama-Qwen3.5-FF6600)](https://ollama.com/)
[![Plotly](https://img.shields.io/badge/Plotly-5.18-3F4F75?logo=plotly&logoColor=white)](https://plotly.com/)
[![pandas](https://img.shields.io/badge/pandas-2.2-150458?logo=pandas&logoColor=white)](https://pandas.pydata.org/)
[![Tailwind](https://img.shields.io/badge/Tailwind-4-06B6D4?logo=tailwindcss&logoColor=white)](https://tailwindcss.com/)
[![JWT](https://img.shields.io/badge/JWT-Auth-000000?logo=jsonwebtokens&logoColor=white)](https://jwt.io/)
[![Discord](https://img.shields.io/badge/Discord-Bot-5865F2?logo=discord&logoColor=white)](https://discord.com/)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?logo=telegram&logoColor=white)](https://telegram.org/)

</div>

| Layer | Tools | Count |
|-------|-------|-------|
| **Data** | OpenBB · yfinance · pykrx · edgartools · FRED · TA-Lib | 15 collectors |
| **External** | TipRanks · Dataroma · Macrotrends · ARK · ETF.com · TradingEconomics | 6 sites |
| **Quant** | pandas · Riskfolio-Lib · VectorBT · QuantStats · scikit-learn · cvxpy | — |
| **Backend** | FastAPI · uvicorn · SSE stream · Pydantic | 14 API routes |
| **Frontend** | Next.js 16 · React 19 · shadcn/ui · Tailwind 4 · Recharts | 12 pages |
| **LLM** | Ollama · Qwen3.5 (35B-A3B MoE) · thinking model · auto-save | — |
| **DB** | SQLite WAL · 27 tables · audit_log · external_analysis | 4.1 MB |
| **Security** | JWT · bcrypt · slowapi · CSP/HSTS · audit log · Pydantic | 5 layers |
| **CI/CD** | GitHub Actions · ruff + pytest + tsc · uv cache · Trivy scan | 3 jobs |

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

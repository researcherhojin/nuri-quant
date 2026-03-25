# Nuri-Quant

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![OpenBB](https://img.shields.io/badge/OpenBB-v4-5B21B6)](https://openbb.co/)
[![Riskfolio](https://img.shields.io/badge/Riskfolio--Lib-7.2-FF6F00)](https://riskfolio-lib.readthedocs.io/)
[![VectorBT](https://img.shields.io/badge/VectorBT-0.28-00BCD4)](https://vectorbt.dev/)
[![QuantStats](https://img.shields.io/badge/QuantStats-0.0.81-4CAF50)](https://github.com/ranaroussi/quantstats)

**투자 정보를 수집하고, 검증하고, 실행하는 오픈소스 퀀트 투자 파이프라인**

누리(世) — 세상의 모든 투자 정보를 모아 수익으로 바꾸는 시스템

</div>

## What is Nuri-Quant?

단순한 주가 수집기가 아닙니다. 다양한 투자 정보를 모으고, 그 정보가 **실제로 수익을 만드는지 검증**하고, 검증된 전략을 **현재 시장 상황에 맞게 추천**하는 전 과정을 자동화합니다.

## Core Process

```mermaid
graph LR
    C[Collect<br/>정보 수집] --> V[Validate<br/>검증]
    V --> CL[Classify<br/>시장 판독]
    CL --> D[Diagnose<br/>포폴 진단]
    D --> R[Recommend<br/>제안]
    R --> T[Track<br/>성과 추적]
    T -.->|피드백 루프| C

    style C fill:#E3F2FD,stroke:#1565C0
    style V fill:#FFF3E0,stroke:#E65100
    style CL fill:#F3E5F5,stroke:#6A1B9A
    style D fill:#E8F5E9,stroke:#2E7D32
    style R fill:#FCE4EC,stroke:#C62828
    style T fill:#FFFDE7,stroke:#F57F17
```

| Step | Description | Status |
|------|-------------|--------|
| **Collect** | Aggregate investment data from 7 source categories | ✅ 8 collectors |
| **Validate** | Backtest: "Did following this info actually make money?" | 🔨 Phase C |
| **Classify** | Market regime detection (bull/bear × high/low volatility) | 📋 Phase D |
| **Diagnose** | Portfolio risk, weight, correlation analysis | ✅ 6 modules |
| **Recommend** | Market-aware rebalancing with validated signals | ✅ MVO/RP |
| **Track** | Compare recommendations vs actual performance → feedback | 📋 Phase E |

## Tech Stack

**Data Collection**<br/>
![OpenBB](https://img.shields.io/badge/OpenBB-v4.7-5B21B6)
![pykrx](https://img.shields.io/badge/pykrx-1.2.4-FF5722)
![FRED](https://img.shields.io/badge/FRED_API-Free-1565C0)
![TA-Lib](https://img.shields.io/badge/TA--Lib-0.4-607D8B)

**Analysis & Optimization**<br/>
![Riskfolio](https://img.shields.io/badge/Riskfolio--Lib-7.2-FF6F00)
![QuantStats](https://img.shields.io/badge/QuantStats-0.0.81-4CAF50)
![VectorBT](https://img.shields.io/badge/VectorBT-0.28-00BCD4)
![pandas](https://img.shields.io/badge/pandas-2.2-150458?logo=pandas&logoColor=white)
![NumPy](https://img.shields.io/badge/NumPy-1.26-013243?logo=numpy&logoColor=white)

**Automation & Infra**<br/>
![APScheduler](https://img.shields.io/badge/APScheduler-3.11-795548)
![Discord](https://img.shields.io/badge/Discord-Webhook-5865F2?logo=discord&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?logo=sqlite&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)

## Architecture

```mermaid
graph TB
    subgraph Collectors["Layer 1: Data Collection"]
        Stock["OpenBB<br/>US Stocks"]
        StockKR["pykrx<br/>KR Stocks"]
        Macro["FRED API<br/>Macro"]
        Tech["TA-Lib<br/>Signals"]
        FG["CNN<br/>Fear&Greed"]
        ARK["ARK Invest<br/>Trades"]
        News["OpenBB<br/>News"]
        Events["OpenBB<br/>Calendar"]
    end

    subgraph DB["SQLite (WAL mode)"]
        Tables["prices | portfolio | macro\nsignals | ark | events | news"]
    end

    subgraph Analysis["Layer 2: Analysis"]
        Portfolio["Portfolio<br/>비중/손익"]
        Risk["Riskfolio-Lib<br/>VaR/CVaR/Sharpe"]
        Rebalance["MVO / Risk Parity<br/>리밸런싱"]
        Perf["QuantStats<br/>HTML Tearsheet"]
        Factor["Multi-Factor<br/>M/V/Q/S Scoring"]
        BT["VectorBT<br/>Backtest"]
    end

    subgraph Alerts["Layer 3: Alerts"]
        Discord["Discord<br/>Daily Report"]
        Sched["APScheduler<br/>11 Cron Jobs"]
    end

    Collectors --> DB
    DB --> Analysis
    Analysis --> Alerts

    style Collectors fill:#E3F2FD,stroke:#1565C0
    style DB fill:#FFF3E0,stroke:#E65100
    style Analysis fill:#E8F5E9,stroke:#2E7D32
    style Alerts fill:#FCE4EC,stroke:#C62828
```

## Information Sources

| Category | Source | Data |
|----------|--------|------|
| **Superinvestors** | Dataroma, ARK Invest, 13F | Buffett/Soros portfolios, ARK daily trades |
| **Macro** | FRED, TradingEconomics | Rates, CPI, oil, FX, VIX, yield curve |
| **Valuation** | Macrotrends, OpenBB | Long-term PER/PBR/ROE, financials |
| **Analyst** | TipRanks | Price targets, ratings, success rates |
| **ETF Flows** | ETF.com | Sector ETF inflows/outflows |
| **Sentiment** | CNN Fear&Greed, Reddit, News | Fear/Greed index, social sentiment |
| **Supply/Demand** | pykrx, FINRA | Institutional flows, short interest |

## Getting Started

**Prerequisites**: Python 3.12, [uv](https://docs.astral.sh/uv/), `brew install ta-lib`

```bash
git clone https://github.com/researcherhojin/nuri-quant.git
cd nuri-quant

# Setup (venv + dependencies + DB + portfolio import)
make setup

# Configure API keys
cp .env.example .env
# Edit: FRED_API_KEY, DISCORD_WEBHOOK_URL

# Collect data
make collect

# Analyze portfolio
python -m nuri.analysis.portfolio
python -m nuri.analysis.risk
python -m nuri.analysis.performance --html

# Run backtest
python -m nuri.quant.backtest.engine

# Start 24/7 scheduler
python -m nuri.scheduler
```

## Roadmap

### Phase A: Foundation ✅
- [x] 8 data collectors (OpenBB + pykrx + FRED + TA-Lib + CNN + ARK)
- [x] 6 analysis modules (portfolio, risk, performance, sector, correlation, rebalance)
- [x] Riskfolio-Lib optimization (MVO, Risk Parity, constraints)
- [x] VectorBT backtest engine + multi-factor scoring
- [x] QuantStats HTML tearsheets
- [x] Discord alerts + APScheduler (11 cron jobs)

### Phase B: Information Sources
- [ ] Dataroma superinvestor tracking
- [ ] TipRanks analyst consensus
- [ ] Macrotrends long-term financials
- [ ] ETF.com sector fund flows
- [ ] Institutional/foreign investor flows (pykrx)
- [ ] Short interest + put/call ratio (OpenBB)

### Phase C: Validation Engine
- [ ] Per-source signal backtesting framework
- [ ] Strategy scorecard (win rate, avg return, max loss per source)
- [ ] Hypothesis testing ("Does following ARK actually work?")

### Phase D: Market Regime
- [ ] Regime classifier (bull/bear/sideways × high/low volatility)
- [ ] Macro environment scoring (market thermometer)
- [ ] Regime-to-strategy mapping

### Phase E: Contextual Recommendations
- [ ] Regime-aware rebalancing (defensive ↔ aggressive auto-switch)
- [ ] Validated-signal-based buy/sell candidates
- [ ] Recommendation history + performance tracking

### Phase F: Interface
- [ ] REST API (FastAPI)
- [ ] Web dashboard
- [ ] LLM-powered natural language reports

## Investment Rules

These rules are **enforced in code**, not just guidelines:

| Rule | Constraint | Enforcement |
|------|-----------|-------------|
| Single position limit | ≤ 15% | `rebalance.py`, `portfolio.py` |
| Sector exposure limit | ≤ 35% | `sector.py` |
| Leverage ETF ban | TSLL, TQQQ, etc. | `rebalance.py` (weight → 0) |
| Per-stock stop loss | -20% | `risk.py` |
| Portfolio stop | -10% drawdown | `risk.py` |
| All signals | Decision aid only | Human makes final call |

## License

[MIT](LICENSE)

---

> *"The goal is not to predict the future, but to be prepared for it."* — Pericles

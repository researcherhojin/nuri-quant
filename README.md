# Nuri-Quant

<div align="center">

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/Tests-142_passed-26a69a?logo=pytest&logoColor=white)]()
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)

**[Docs](CLAUDE.md)** | **[API Swagger](http://localhost:8001/docs)** | **[Dashboard](http://localhost:3000)** | **[Issues](https://github.com/researcherhojin/nuri-quant/issues)**

</div>

Open-source quant investment platform. Collects data from 13 free sources, validates signals with backtesting, classifies market regimes, and recommends trades via 7-agent consensus — with a Next.js dashboard and LLM-powered reports.

## Tech Stack

**Data**: OpenBB, yfinance, pykrx, edgartools, TA-Lib
**Quant**: pandas, Riskfolio-Lib, VectorBT, QuantStats, Plotly
**Interface**: FastAPI, Next.js 16, shadcn/ui, Tailwind 4, Ollama
**Infra**: SQLite (WAL), APScheduler, Discord, GitHub Actions CI

## Getting Started

```bash
# Prerequisites: Python 3.12, uv, brew install ta-lib
git clone https://github.com/researcherhojin/nuri-quant.git && cd nuri-quant
make setup                                    # venv + deps + DB init + portfolio import

# Collect 5 years of data
python -m nuri.collectors.stock --period 5y   # US stocks (OpenBB)
python -m nuri.collectors.stock_kr --days 1825 # Korean stocks (pykrx)
make collect                                  # macro/technical/fear&greed/ARK

# Validate + analyze + recommend
make validate                                 # signal backtest + scorecard
make regime                                   # market regime + strategy map
make recommend                                # candidates + tracking
make verify                                   # full report → data/reports/YYYY-MM-DD/
```

### Commands

```bash
# Trading
make consensus      # 7-agent analysis on portfolio
make scan           # market-wide scanner (89 US tickers)
make swing          # scan + agent consensus → entry
make strategy       # L/S strategy + regime monitor
make backtest-ls    # 5.4yr backtest + Monte Carlo
make optimize       # grid search parameter tuning
make mean-reversion # mean-reversion scan + backtest
make pairs          # pairs trading scan + backtest

# Data
make wallstreet     # analyst ratings + earnings + insider
make filings        # SEC 10-K key metrics

# Infrastructure
make lint           # ruff check
make test           # 142 unit tests
make gate           # pipeline readiness check
make start          # API(:8001) + Dashboard(:3000)
```

## Architecture

```
nuri/
├── core/              # DB (sole sqlite3 entry), rules
├── collectors/        # 16 data collectors (BaseCollector pattern)
├── analysis/          # Pure analysis: portfolio, risk, sector, charts, sentiment
├── quant/             # Quantitative pipeline
│   ├── regime/        # 6-regime classifier, macro score, strategy map
│   ├── validation/    # Signal/superinvestor/analyst backtest, scorecard
│   ├── backtest/      # VectorBT engine, grid search optimizer
│   └── factors/       # Multi-factor scoring (momentum, value, quality)
├── trading/           # Trading execution
│   ├── agents/        # 7 agents + weighted consensus
│   ├── engine/        # SIEGE: gate, conflicts, learning memory
│   ├── strategy/      # L/S, mean-reversion, pairs trading
│   ├── recommend/     # Candidates, rebalance, tracker
│   ├── swing/         # Market-wide scanner
│   └── execution/     # Broker interface (Alpaca paper + DryRun)
├── api/               # FastAPI REST + SSE stream
├── alerts/            # Discord daily report
└── llm/               # Ollama LLM report
```

```mermaid
graph LR
    subgraph Data["Data Collection (13 sources)"]
        style Data fill:#e8eaf6
        S[Stock/KR] --> DB[(SQLite WAL)]
        M[Macro/VIX] --> DB
        F[13F/ARK/News] --> DB
    end

    subgraph Quant["Validation + Regime"]
        style Quant fill:#e8f5e9
        DB --> BT[Signal Backtest<br/>3,400+ trades]
        DB --> RC[Regime Classifier<br/>6 regimes]
        BT --> XA[Cross-Analysis<br/>signal × regime]
    end

    subgraph Agents["7-Agent Consensus"]
        style Agents fill:#fff3e0
        XA --> TA[Technical]
        XA --> FA[Fundamental]
        XA --> MA[Macro]
        XA --> RA[Risk]
        XA --> SM[Smart Money]
        XA --> WS[Wall Street]
        XA --> KR[Korean Mkt]
        TA & FA & MA & RA & SM & WS & KR --> CS[Consensus<br/>weighted vote]
    end

    subgraph Engine["SIEGE Engine"]
        style Engine fill:#fce4ec
        GT[Gate] --> CS
        CF[Conflicts] --> CS
        LM[Learning Memory] --> CS
    end

    subgraph Strategy["Long/Short Strategy"]
        style Strategy fill:#f3e5f5
        CS --> LS[L/S Engine<br/>bull→long bear→short]
        LS --> PM[Position Manager<br/>SIEGE Certification]
        PM --> BK[Backtest<br/>Sharpe 0.92 MDD -10%]
    end

    subgraph Interface["Interface"]
        style Interface fill:#e3f2fd
        CS --> API[FastAPI :8001]
        LS --> API
        API --> NX[Next.js :3000<br/>10 pages]
        API --> LLM[Ollama Report]
    end
```

## Key Features

- **7-Agent Consensus** — Technical, Fundamental, Macro, Risk, Smart Money, Wall Street, Korean Market agents. Weighted voting with risk agent veto power
- **Long/Short Strategy** — Regime-based direction switching with SIEGE Certification Gate. Backtest: +62% return, Sharpe 0.92, MDD -10%
- **SIEGE Engine** — Gated Execution (10 conditions), Conflict Detection (BUY+SELL → HOLD), Learning Memory (drift auto-penalty)
- **Parameter Optimization** — Grid search for RSI/MACD/BB thresholds and holding periods
- **Multi-Strategy** — L/S regime switching, Mean-Reversion (BB+RSI), Pairs Trading (correlation Z-score)
- **Dashboard** — Next.js 16 with SSE real-time updates, Recharts price charts, portfolio management, mobile responsive

## Investment Rules

Defined in `config/rules.yaml`, enforced across all modules:

| Rule | Limit |
|------|-------|
| Single position | ≤ 15% |
| Sector exposure | ≤ 35% |
| Per-stock stop loss | -20% |
| Portfolio stop | -10% drawdown |
| Leverage ETF ban | TSLL, TQQQ, SQQQ, UPRO, SPXU |

## Roadmap

- [ ] **차트 고도화** — Recharts에 기술적 지표 오버레이 (RSI, MACD, BB) + 시그널 마커
- [ ] **한국 시장 수집기 확장** — pykrx 기반 외국인/기관 수급, 공매도 잔고
- [ ] **실거래 연동 완성** — Alpaca live trading + 한투 OpenAPI
- [ ] **알림 고도화** — Telegram 봇, 레짐 전환 push 알림

## License

[Apache License 2.0](LICENSE)

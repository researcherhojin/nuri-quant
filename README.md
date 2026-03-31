# Nuri-Quant

<div align="center">

[![CI/CD Pipeline](https://github.com/researcherhojin/nuri-quant/actions/workflows/main-ci-cd.yml/badge.svg)](https://github.com/researcherhojin/nuri-quant/actions/workflows/main-ci-cd.yml)
[![codecov](https://codecov.io/gh/researcherhojin/nuri-quant/graph/badge.svg)](https://codecov.io/gh/researcherhojin/nuri-quant)
[![License](https://img.shields.io/badge/license-AGPL%20v3-blue.svg)](LICENSE)

**[API Docs](http://localhost:8001/docs)** | **[Dashboard](http://localhost:3000)** | **[Issues](https://github.com/researcherhojin/nuri-quant/issues)**

</div>

Open-source quantitative investment platform that **proves why you should buy or sell** — not gut feeling. 21 data collectors, 10 specialist agents, and a 10-condition mechanical gate certify every recommendation before it reaches you.

## Pipeline

```mermaid
graph LR
    A["Collect<br/>21 collectors<br/>+ 11 external sources"] --> B["Validate<br/>8,000+ trades<br/>15 signals backtest"]
    B --> C["Classify<br/>10-regime model<br/>bull/bear/sideways<br/>+ special regimes"]
    C --> D["Diagnose<br/>10 agents<br/>weighted consensus"]
    D --> E["Certify<br/>SIEGE 10-gate<br/>pass / reject"]
    E --> F["Recommend<br/>entry / stop-loss<br/>take-profit targets"]

    style A fill:#e8eaf6,stroke:#5c6bc0
    style B fill:#e8f5e9,stroke:#66bb6a
    style C fill:#fff3e0,stroke:#ffa726
    style D fill:#e3f2fd,stroke:#42a5f5
    style E fill:#fce4ec,stroke:#ef5350
    style F fill:#f3e5f5,stroke:#ab47bc
```

## Tech Stack

**Data Collection**<br/>
![OpenBB](https://img.shields.io/badge/OpenBB-4.7.1-00C853?logoColor=white)
![pykrx](https://img.shields.io/badge/pykrx-1.2.4-1565C0)
![TA-Lib](https://img.shields.io/badge/TA--Lib-0.6.8-FF5722)
![edgartools](https://img.shields.io/badge/edgartools-5.26.0-795548)
![FRED API](https://img.shields.io/badge/FRED_API-0.5.2-FF6F00)
![Beautiful Soup](https://img.shields.io/badge/Beautiful_Soup-4.14.3-43853D)
![finvizfinance](https://img.shields.io/badge/finvizfinance-1.3.0-1E88E5)

> 21 collectors + 11 external sources (TipRanks · Dataroma · CBOE · CoinGecko · Reddit/WSB · ARK · ETF.com · Macrotrends · TradingEconomics · ShortInterest · FINVIZ)

**Quantitative Analysis**<br/>
![pandas](https://img.shields.io/badge/pandas-3.0.1-150458?logo=pandas&logoColor=white)
![NumPy](https://img.shields.io/badge/NumPy-2.4.3-013243?logo=numpy&logoColor=white)
![scikit-learn](https://img.shields.io/badge/scikit--learn-1.8.0-F7931E?logo=scikit-learn&logoColor=white)
![Riskfolio-Lib](https://img.shields.io/badge/Riskfolio--Lib-7.2.1-2196F3)
![VectorBT](https://img.shields.io/badge/VectorBT-0.28.4-9C27B0)
![cvxpy](https://img.shields.io/badge/cvxpy-1.7.5-00897B)
![SciPy](https://img.shields.io/badge/SciPy-1.17.1-8CAAE6?logo=scipy&logoColor=white)

**Backend**<br/>
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.128.8-009688?logo=fastapi&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-2.12.5-E92063?logo=pydantic&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?logo=sqlite&logoColor=white)
![PyJWT](https://img.shields.io/badge/PyJWT-2.12.1-000000?logo=jsonwebtokens&logoColor=white)
![bcrypt](https://img.shields.io/badge/bcrypt-5.0.0-004D40)
![slowapi](https://img.shields.io/badge/slowapi-0.1.9-FF7043)

> 53 endpoints · 28 tables (v11 migrations) · SSE streaming · JWT + bcrypt + slowapi rate limiting

**Frontend**<br/>
![Next.js](https://img.shields.io/badge/Next.js-16.2.1-000000?logo=next.js&logoColor=white)
![React](https://img.shields.io/badge/React-19.2.4-61DAFB?logo=react&logoColor=black)
![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-4-06B6D4?logo=tailwindcss&logoColor=white)
![shadcn/ui](https://img.shields.io/badge/shadcn/ui-latest-000000)

> 15 pages · Dark mode · Palantir-style Operator Cockpit · FreshnessBar · Pipeline Control

**LLM**<br/>
![Ollama](https://img.shields.io/badge/Ollama-local-000000?logo=ollama&logoColor=white)
![Qwen](https://img.shields.io/badge/Qwen3.5-35B_MoE-7C3AED)

**Testing & CI/CD**<br/>
![pytest](https://img.shields.io/badge/pytest-9.0.2-0A9EDC?logo=pytest&logoColor=white)
![pytest-xdist](https://img.shields.io/badge/xdist-3.8.0-0A9EDC)
![Ruff](https://img.shields.io/badge/Ruff-0.13.3-D7FF64?logo=ruff&logoColor=black)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-CI/CD-2088FF?logo=githubactions&logoColor=white)
![Codecov](https://img.shields.io/badge/Codecov-coverage-F01F7A?logo=codecov&logoColor=white)
![Trivy](https://img.shields.io/badge/Trivy-security-1904DA)

## Getting Started

**Prerequisites**: Python 3.12, [uv](https://docs.astral.sh/uv/), `brew install ta-lib`, Node 22 (for frontend)

```bash
git clone https://github.com/researcherhojin/nuri-quant.git && cd nuri-quant
make setup                 # venv + deps + DB init + portfolio import
cp .env.example .env
cp config/portfolio.example.yaml config/portfolio.yaml  # edit your holdings
make full-scan             # 8-phase pipeline: collect → certify → recommend → notify
```

### Useful Commands

```bash
make full-scan             # Full 8-stage pipeline
make quick-scan            # Collect → analyze → consensus → targets (~2 min)
make consensus             # 10-agent consensus + price targets
make certify               # SIEGE 10-condition certification
make start                 # API (:8001) + Dashboard (:3000)
make test                  # pytest (1686 tests, 64 files, parallel via xdist)
make lint                  # ruff check

# Single test
.venv/bin/python -m pytest tests/test_db.py::TestUpsertPrices::test_insert_and_query -v
```

## Key Features

- **Evidence-based decisions** — 8,000+ historical trade backtests across 15 signals validate every recommendation
- **10-regime market classification** — 6 base (bull/bear/sideways × high/low vol) + 4 special (recovery, euphoria, stagflation, sector rotation)
- **10 specialist agents** — Weighted consensus voting. Risk agent holds veto power (SELL + confidence ≥ 80 overrides all)
- **SIEGE certification** — [10-condition mechanical gate](https://github.com/nutshells3/Swarm-Intelligence-Engine-with-Gated-Execution). Single failure → REJECTED
- **Investment rules** — O'Neil (CAN SLIM) + Minervini (SEPA). 3:1 reward-to-risk ratio, -7% stop / +20%/+40% targets
- **Pipeline observability** — [Palantir Foundry](https://www.palantir.com/docs/foundry/data-lineage/overview)-style Data Health + [Dagster](https://docs.dagster.io/guides/observe/asset-freshness-policies) Freshness SLA
- **Superinvestor tracking** — SEC 13F filings (Buffett, Dalio, NPS Korea, Key Square, Strive)
- **Portfolio onboarding** — Dashboard UI for CRUD, CSV import/export, sample portfolio, YAML reverse sync
- **LLM reports** — Qwen3.5 evidence-based analysis with SIEGE certification

## Investment Rules

Defined in `config/rules.yaml`. Based on [O'Neil (CAN SLIM)](https://www.investors.com/) + [Minervini (SEPA)](https://www.minervini.com/) + [Disposition Effect research (Shefrin 1985)](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1985.tb05002.x).

| | Growth | Value | Swing |
|---|--------|-------|-------|
| **Stop-Loss** | -7% | -10% | -5% |
| **Take-Profit 1** | +20% → sell 50% | +15% → sell 50% | +5% → sell 50% |
| **Take-Profit 2** | +40% → sell 25% | +30% → sell 25% | +10% → sell all |
| **Remainder** | Trailing -15% | Trailing -15% | — |

**Core Rules:**
- VIX > 30 → block all new buys (win rate collapses)
- Buy checklist: TipRanks ≥ Moderate Buy, superinvestors ≥ 3, PE < 100, revenue > $0, multi-factor top 50%
- Sell priority: Leveraged ETF → stop-loss breach → no superinvestors → position limit → sector limit

## References

| Source | Application |
|--------|-------------|
| [SIEGE Engine](https://github.com/nutshells3/Swarm-Intelligence-Engine-with-Gated-Execution) | 10-condition gate, certification, event journal |
| [Palantir Foundry](https://www.palantir.com/docs/foundry/data-lineage/overview) | Data Health, pipeline monitoring |
| [Dagster](https://docs.dagster.io/guides/observe/asset-freshness-policies) | Asset freshness PASS/WARN/FAIL |
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | Multi-agent consensus pattern |
| [O'Neil — CAN SLIM](https://www.investors.com/) | Stop-loss -7%, take-profit +20%/+40% |
| [Minervini — SEPA](https://www.minervini.com/) | Trailing stop, 3:1 reward-to-risk |

## License

[GNU Affero General Public License v3.0](LICENSE)

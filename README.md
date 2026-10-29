# Nuri-Quant

<div align="center">

[![CI/CD](https://github.com/researcherhojin/nuri-quant/actions/workflows/main-ci-cd.yml/badge.svg)](https://github.com/researcherhojin/nuri-quant/actions/workflows/main-ci-cd.yml)
[![codecov](https://codecov.io/gh/researcherhojin/nuri-quant/graph/badge.svg)](https://codecov.io/gh/researcherhojin/nuri-quant)
[![License](https://img.shields.io/badge/license-AGPL--3.0--or--later-blue.svg)](LICENSE)

**A quantitative decision-support platform that records and scores the evidence behind each investment recommendation.**

</div>

Each day, Nuri-Quant reviews every holding in a portfolio of US and Korean equities, records a dated BUY, SELL or HOLD recommendation with its evidence, and later grades that recommendation against what the market did.

> [!IMPORTANT]
> - **Recommendations only.** The system never places an order; the operator places every order by hand.
> - **No performance claim.** The project claims no investment edge unless a pre-registered evaluation passes ([`docs/STRATEGY.md`](docs/STRATEGY.md) §3.11).
> - **Not investment advice.** The output is a research record for one operator's own decisions.

## What it produces

| Output | Where |
|--------|-------|
| A dated BUY / SELL / HOLD recommendation per holding, with agent verdicts and price levels | Dashboard `/decisions` |
| Each recommendation's return at 7, 14, 21, 30, 60 and 90 days, once that horizon has passed | `recommendations` table |
| BUY candidates outside the portfolio | US pre-market brief on Discord |
| Market overview: indices, regime, macro score, data freshness | Dashboard `/` |
| US and Korean post-market briefs | Discord |
| Read-only market data for AI clients, without holdings | MCP server (`nuri/mcp`) |

## Quick start

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), TA-Lib and Node.js 22. On macOS: `brew install uv ta-lib fnm && fnm install 22`.

Install:

```bash
git clone https://github.com/researcherhojin/nuri-quant.git && cd nuri-quant
cp config/portfolio.example.yaml config/portfolio.yaml  # your holdings (gitignored)
make setup                                              # dependencies, database, git hooks
cd frontend && npm ci && cd ..
cp .env.example .env                                    # API keys, all optional
```

Run:

```bash
make start        # API on :8001, dashboard on :3000
make full-scan    # collect data, run the consensus, record decisions
make test-fast    # backend tests
make help         # every target
```

- Every API key is optional. A collector without credentials is skipped or falls back to a keyless source.
- Leave the Discord and Telegram environment variables unset on development machines so that only the production host sends messages.
- Full walkthrough: [`docs/FRESH_CLONE_SETUP.md`](docs/FRESH_CLONE_SETUP.md).

## Architecture

```mermaid
flowchart TB
    subgraph INPUTS["Inputs"]
        SRC["External sources"]
        PF[("portfolio")]
    end
    subgraph RESEARCH["Daily research"]
        COL["Collect"]
        TAB[("Collector tables")]
        CON["Consensus"]
        FAC["Analyze"]
        BUY["BUY candidates"]
        DEC[("decisions")]
        REC[("recommendations")]
        TRK["Track"]
    end
    OUT["Delivery"]
    YOU(["Operator trades by hand"])

    SRC --> COL --> TAB
    TAB --> CON
    PF --> CON
    TAB --> FAC --> BUY
    CON ==>|in memory| DEC
    CON --> REC
    BUY --> REC
    REC -.->|agent weights| CON
    DEC --> OUT
    REC --> OUT
    REC --> TRK
    TRK --> REC
    OUT --> YOU

    classDef step  stroke:#3b82f6,stroke-width:2px
    classDef store stroke:#64748b,stroke-width:2px
    classDef human stroke:#f59e0b,stroke-width:2px
    classDef zone  fill:none,stroke:#94a3b8,stroke-width:1px
    class COL,FAC,CON,BUY,TRK,OUT step
    class SRC,TAB,PF,REC,DEC store
    class YOU human
    class INPUTS,RESEARCH zone
```

Boxes are steps, cylinders are tables, and the frames group them for reading only. The thick arrow is an in-memory hand-off and the dashed arrow is the only feedback path. The operator updates `portfolio` by hand, a loop the diagram leaves out.

| Stage | Package | Runs as | Writes |
|-------|---------|---------|--------|
| **Collect** | `nuri/collectors` | Collector jobs, every 5 minutes to weekly | `prices`, `signals`, `fundamentals`, `macro`, … |
| **Analyze** | `nuri/analysis` | `factors` job | `factors` |
| **Consensus** | `nuri/trading/agents` | `consensus` job | `recommendations` |
| **Decide** | `nuri/trading/engine` | Inside the consensus job | `decisions`, `decision_evidence` |
| **Track** | `nuri/trading/recommend` | Outcome and P&L jobs | `recommendations.outcome_*`, `decision_outcomes` |

- **No orchestrator.** `nuri/scheduler.py` registers independent cron jobs; an arrow is a data dependency, not a call.
- **One in-memory hand-off.** The consensus job passes its result straight to `record_decisions()`.
- **One feedback path.** Each agent's recent hit rate sets its weight in the next run.

**Stack:** Python 3.12 · FastAPI · APScheduler · SQLite · Next.js. **Universe:** US equities and the KOSPI 200. Details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Documentation

| Document | Contents |
|----------|----------|
| [`docs/STRATEGY.md`](docs/STRATEGY.md) | Principles, decisions and investment rules (authoritative) |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Pipeline, schedule, data sources, database, deployment, CI/CD |
| [`docs/FRESH_CLONE_SETUP.md`](docs/FRESH_CLONE_SETUP.md) | Setup from a fresh clone |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Workflow, required checks, pull request rules |
| [`SECURITY.md`](SECURITY.md) | Security policy and rules governing data sent to large language models (LLMs) |

Every guide is in [`docs/`](docs/), with Korean editions in [`docs/ko/`](docs/ko/).

## Acknowledgements

- The consensus approach follows [TradingAgents](https://github.com/TauricResearch/TradingAgents), using rule-based specialist agents in place of LLM agents.
- Data freshness policies follow [Dagster](https://docs.dagster.io/guides/observe/asset-freshness-policies).
- Portfolio optimization uses [Riskfolio-Lib](https://riskfolio-lib.readthedocs.io/).
- The investment rules are based on O'Neil (CAN SLIM) and Minervini (SEPA).

## Contributing

Open an issue to agree on scope before submitting a pull request. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

[AGPL-3.0-or-later](LICENSE) · Maintained by [@researcherhojin](https://github.com/researcherhojin)

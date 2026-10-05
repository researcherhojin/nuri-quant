# Nuri-Quant

<div align="center">

[![CI/CD](https://github.com/researcherhojin/nuri-quant/actions/workflows/main-ci-cd.yml/badge.svg)](https://github.com/researcherhojin/nuri-quant/actions/workflows/main-ci-cd.yml)
[![codecov](https://codecov.io/gh/researcherhojin/nuri-quant/graph/badge.svg)](https://codecov.io/gh/researcherhojin/nuri-quant)
[![License](https://img.shields.io/badge/license-AGPL%20v3-blue.svg)](LICENSE)

**An auditable quant research platform that records and scores the evidence behind each investment decision.**

</div>

Nuri-Quant collects market data, evaluates a portfolio with a panel of rule-based agents, and issues dated BUY / SELL / HOLD recommendations together with the evidence that produced them. Each recommendation is later scored against the realized outcome, and those results feed back into the agent weights.

- **Recommendation only.** The system never places orders; the operator executes every trade manually.
- **No claimed edge.** Performance is not claimed until a pre-registered evaluation passes ([`docs/STRATEGY.md`](docs/STRATEGY.md) §3.11).

## Table of Contents

- [Security](#security)
- [Background](#background)
- [Install](#install)
- [Usage](#usage)
- [Project Stats](#project-stats)
- [Documentation](#documentation)
- [Maintainers](#maintainers)
- [Acknowledgements](#acknowledgements)
- [Contributing](#contributing)
- [License](#license)

## Security

The repository is public; the running system operates on a real portfolio. Personal financial data is blocked from commits by a required CI scan, external LLM calls go through a single audited module, and the production API listens on `127.0.0.1` only. Details and vulnerability reporting: [`SECURITY.md`](SECURITY.md).

## Background

### How it works

The daily loop evaluates the holdings already in the portfolio and records the reasoning for each one. A separate scan surfaces candidates outside the portfolio.

```mermaid
flowchart LR
    IN["Your holdings<br/>+ public market data"]
    RUN["Daily, on a schedule:<br/>score every holding, record why"]
    DEC["A dated BUY / SELL / HOLD<br/>per holding, with its evidence"]
    YOU(["You place the order —<br/>the system never does"])
    LED[("The same decision, scored later<br/>against what actually happened")]

    IN --> RUN --> DEC --> YOU
    DEC --> LED
    LED -- "agent weights for the next run" --> RUN

    classDef step  stroke:#3b82f6,stroke-width:2px
    classDef store stroke:#64748b,stroke-width:2px
    classDef human stroke:#f59e0b,stroke-width:2px
    class IN,RUN,DEC step
    class LED store
    class YOU human
```

### Architecture

| Stage | Package | Role |
|-------|---------|------|
| **Collect** | `nuri/collectors` | Prices, fundamentals, macro data and news |
| **Analyze** | `nuri/analysis` | Portfolio, risk and sector analysis; daily factor scores |
| **Consensus** | `nuri/trading/agents` | 10 specialist agents vote on each holding, with a risk veto |
| **Certify** | `nuri/trading/engine` | Policy gates that certify or reject the portfolio state |
| **Track** | `nuri/trading/recommend` | Scores recommendations at 30, 60 and 90 days |

The stages are not chained by an orchestrator: `nuri/scheduler.py` registers 59 independent APScheduler jobs, each reading its inputs from tables written by earlier jobs.

- Scheduling: 59 cron jobs · in-process
- Storage: SQLite WAL · 61 tables
- Analytics: 22 signals · 10 regimes · a 4-factor composite

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the runtime topology and scoring model.

## Install

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), TA-Lib and Node.js 22. On macOS: `brew install uv ta-lib fnm && fnm install 22`.

```bash
git clone https://github.com/researcherhojin/nuri-quant.git && cd nuri-quant
cp config/portfolio.example.yaml config/portfolio.yaml  # holdings (gitignored); make setup imports it
make setup                                              # backend dependencies, database, git hooks
cd frontend && npm ci && cd ..                          # frontend dependencies
cp .env.example .env                                    # API keys (all optional)
```

All API keys are optional; collectors without credentials skip themselves.

## Usage

```bash
make start          # API on :8001 (OpenAPI at /docs), dashboard on :3000
make full-scan      # run every stage in order
make consensus      # agent analysis and decision recording
make test-fast      # backend tests, excluding slow tests
make verify-all     # pre-push checks: tests, lint, frontend
make help           # list all targets
```

Investment rules and thresholds live in [`config/rules.yaml`](config/rules.yaml); the rationale is in [`docs/STRATEGY.md`](docs/STRATEGY.md) §3–§6. The system runs without any LLM; optional integrations are listed in [`docs/STRATEGY.md`](docs/STRATEGY.md) §4.4.3.

## Project Stats

Checked on every pull request by `make verify-doc-counts`.

| Metric | Value |
|--------|-------|
| Backend tests | 8,521 collected across 391 files |
| Frontend tests | 1,746 across 146 vitest files |
| Data collectors | 27 collectors (BaseCollector pattern) |
| Scheduler jobs | 59 cron entries |
| API endpoints | 73 declared in `nuri/api/routes/` |
| Database | SQLite WAL · 61 tables, 65 forward-only migrations |

## Documentation

| Document | Contents |
|----------|----------|
| [`docs/STRATEGY.md`](docs/STRATEGY.md) | Principles, decisions and investment rules (authoritative) |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Runtime topology, database, configuration, CI/CD |
| [`docs/CERTIFICATION_SPEC.md`](docs/CERTIFICATION_SPEC.md) | Certification gates |
| [`docs/FRESH_CLONE_SETUP.md`](docs/FRESH_CLONE_SETUP.md) | End-to-end setup from a fresh clone |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Workflow, required checks, pull request rules |
| [`SECURITY.md`](SECURITY.md) | Security policy and LLM egress rules |

## Maintainers

[@researcherhojin](https://github.com/researcherhojin)

## Acknowledgements

Design patterns from [SIEGE Engine](https://github.com/nutshells3/Swarm-Intelligence-Engine-with-Gated-Execution), [OAE](https://github.com/nutshells3/orchestration-assurance-engine), [TradingAgents](https://github.com/TauricResearch/TradingAgents), [Dagster](https://docs.dagster.io/guides/observe/asset-freshness-policies) and [Riskfolio-Lib](https://riskfolio-lib.readthedocs.io/); investment rules after O'Neil (CAN SLIM) and Minervini (SEPA).

## Contributing

Open an issue to agree on scope before submitting a pull request. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the workflow and required checks.

## License

[AGPL-3.0](LICENSE)

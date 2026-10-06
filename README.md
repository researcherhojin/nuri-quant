# Nuri-Quant

<div align="center">

[![CI/CD](https://github.com/researcherhojin/nuri-quant/actions/workflows/main-ci-cd.yml/badge.svg)](https://github.com/researcherhojin/nuri-quant/actions/workflows/main-ci-cd.yml)
[![codecov](https://codecov.io/gh/researcherhojin/nuri-quant/graph/badge.svg)](https://codecov.io/gh/researcherhojin/nuri-quant)
[![License](https://img.shields.io/badge/license-AGPL--3.0--or--later-blue.svg)](LICENSE)

**A quantitative decision-support platform that records and scores the evidence behind each investment recommendation.**

</div>

Nuri-Quant collects market data, evaluates a portfolio with a panel of rule-based agents, and issues dated BUY / SELL / HOLD recommendations together with the evidence that produced them. Each recommendation is later scored against the realized outcome, and the scores are used to adjust the agent weights.

- **Recommendation only.** The system does not place orders; every trade is executed manually by the operator.
- **No performance claim.** No investment edge is claimed unless a pre-registered evaluation passes ([`docs/STRATEGY.md`](docs/STRATEGY.md) §3.11).

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

The repository is public, while the deployed system operates on a real portfolio. A pre-push hook and a required CI check block personal financial data from entering the repository; all external LLM calls pass through a single module that logs each call; and the production API binds to `127.0.0.1`. See [`SECURITY.md`](SECURITY.md) for the security policy and vulnerability reporting.

## Background

### How it works

The scheduled daily run evaluates each current holding and records the reasoning behind its recommendation. A separate scan identifies candidates outside the portfolio.

```mermaid
flowchart LR
    IN["Your holdings<br/>+ public market data"]
    RUN["Daily, on a schedule:<br/>score every holding, record why"]
    DEC["A dated BUY / SELL / HOLD<br/>per holding, with its evidence"]
    YOU(["Operator places the order<br/>(no automated execution)"])
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
| **Collect** | `nuri/collectors` | Collects prices, fundamentals, macroeconomic data and news |
| **Analyze** | `nuri/analysis` | Analyzes portfolio risk and sector exposure; computes daily factor scores |
| **Consensus** | `nuri/trading/agents` | Combines the weighted verdicts of 10 specialist agents per holding, subject to a risk veto |
| **Decide** | `nuri/trading/engine` | Records each consensus decision with its market context and applies the hard-veto gates (formerly `certify`; the portfolio-wide certification verdict was retired, STRATEGY §6) |
| **Track** | `nuri/trading/recommend` | Measures recommendation outcomes at horizons from 7 to 90 days |

The stages are not chained by an orchestrator. `nuri/scheduler.py` registers 59 independent APScheduler jobs, and each job reads its inputs from database tables written by other jobs.

- Scheduling: 59 cron jobs · in-process
- Storage: SQLite WAL · 61 tables
- Market analytics: 22 trading signals · 10 regimes · a 4-factor composite score

A read-only MCP server (`nuri-read`, stdio) exposes BUY candidates, macro facts, data freshness and live quotes to a local AI client; it never exposes holdings, quantities or account data.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the runtime topology and scoring model.

## Install

Requirements: Python 3.12 or later, [uv](https://docs.astral.sh/uv/), TA-Lib and Node.js 22. On macOS: `brew install uv ta-lib fnm && fnm install 22`.

```bash
git clone https://github.com/researcherhojin/nuri-quant.git && cd nuri-quant
cp config/portfolio.example.yaml config/portfolio.yaml  # holdings (gitignored); make setup imports it
make setup                                              # backend dependencies, database, git hooks
cd frontend && npm ci && cd ..                          # frontend dependencies
cp .env.example .env                                    # API keys (all optional)
```

All API keys are optional; a collector whose credentials are not configured is skipped.

## Usage

```bash
make start          # API on :8001 (OpenAPI at /docs), dashboard on :3000
make full-scan      # run all pipeline stages in sequence
make consensus      # run the agent consensus and record decisions
make test-fast      # backend tests, excluding slow tests
make verify-all     # pre-push checks: tests, lint, frontend
make help           # list all targets
```

Investment rules and thresholds are defined in [`config/`](config/) (primarily `rules.yaml`), and their rationale in [`docs/STRATEGY.md`](docs/STRATEGY.md). The recommendation pipeline does not use an LLM; optional LLM features and their data-egress policy are described in [`docs/STRATEGY.md`](docs/STRATEGY.md) §4.4.3.

## Project Stats

These values are verified against the code by `make verify-doc-counts`, which runs in the pre-push hook and in CI (CI skips the counts that require the Python environment).

| Metric | Value |
|--------|-------|
| Backend tests | 8,265 collected across 389 files |
| Frontend test files | 141 vitest files |
| Data collectors | 27 collectors (BaseCollector pattern) |
| Scheduler jobs | 59 cron entries |
| API endpoints | 68 declared in `nuri/api/routes/` |
| Database | SQLite WAL · 61 tables, 67 forward-only migrations |

## Documentation

| Document | Contents |
|----------|----------|
| [`docs/STRATEGY.md`](docs/STRATEGY.md) | Principles, decisions and investment rules (authoritative) |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Runtime topology, database, configuration, CI/CD |
| [`docs/FRESH_CLONE_SETUP.md`](docs/FRESH_CLONE_SETUP.md) | End-to-end setup from a fresh clone |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Workflow, required checks, pull request rules |
| [`SECURITY.md`](SECURITY.md) | Security policy and LLM egress rules |

## Maintainers

[@researcherhojin](https://github.com/researcherhojin)

## Acknowledgements

Design patterns are adapted from [SIEGE Engine](https://github.com/nutshells3/Swarm-Intelligence-Engine-with-Gated-Execution), [OAE](https://github.com/nutshells3/orchestration-assurance-engine), [TradingAgents](https://github.com/TauricResearch/TradingAgents) and [Dagster](https://docs.dagster.io/guides/observe/asset-freshness-policies). Portfolio optimization uses [Riskfolio-Lib](https://riskfolio-lib.readthedocs.io/). The investment rules are based on O'Neil (CAN SLIM) and Minervini (SEPA).

## Contributing

Open an issue to agree on scope before submitting a pull request. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the workflow and required checks.

## License

[AGPL-3.0-or-later](LICENSE)

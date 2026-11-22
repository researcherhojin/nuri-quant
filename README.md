# Nuri-Quant

<div align="center">

[![CI/CD](https://github.com/researcherhojin/nuri-quant/actions/workflows/main-ci-cd.yml/badge.svg)](https://github.com/researcherhojin/nuri-quant/actions/workflows/main-ci-cd.yml)
[![codecov](https://codecov.io/gh/researcherhojin/nuri-quant/graph/badge.svg)](https://codecov.io/gh/researcherhojin/nuri-quant)
[![License](https://img.shields.io/badge/license-AGPL--3.0--or--later-blue.svg)](LICENSE)

**A quantitative decision-support platform that records and scores the evidence behind each investment recommendation.**

</div>

> **Project status.** This overview follows `main`. GitHub Releases is currently empty. [Releases](https://github.com/researcherhojin/nuri-quant/releases) · [Architecture reference](docs/ARCHITECTURE.md)
>
> **What a green CI badge means.** The linked GitHub Actions run passed the checks selected for that commit. The run details show which jobs exercised code. Production service health and investment evaluation have their own evidence. [CI and testing](docs/ARCHITECTURE.md#cicd-pipeline-main-ci-cdyml) · [Runtime topology](docs/ARCHITECTURE.md#runtime-topology) · [Evaluation policy](docs/STRATEGY.md#311-small-stake--measurement-mode--the-systems-burden-of-proof-for-alpha-824828-2026-07-07)

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

The development setup uses Python 3.12, uv, TA-Lib and Node.js 22. On macOS, run `brew install uv ta-lib fnm && fnm install 22`. [uv documentation](https://docs.astral.sh/uv/)

Install:

```bash
git clone https://github.com/researcherhojin/nuri-quant.git && cd nuri-quant
cp config/portfolio.example.yaml config/portfolio.yaml  # your holdings (gitignored)
make setup                                              # dependencies, database, git hooks
cd frontend && npm ci && cd ..
```

Run:

```bash
make start        # API on :8001, dashboard on :3000
make full-scan    # collect data, run the consensus, record decisions
make test-fast    # backend tests
make help         # every target
```

- `make setup` creates `.env` from the template when needed. Every API key is optional. A collector without credentials is skipped or falls back to a keyless source.
- Leave the Discord and Telegram environment variables unset on development machines so that only the production host sends messages.
- Full walkthrough: [`docs/FRESH_CLONE_SETUP.md`](docs/FRESH_CLONE_SETUP.md).

## Architecture

![Nuri-Quant architecture showing browser traffic, the Mac mini services, SQLite, external data and deployment](.github/assets/architecture.svg)

The browser connects to Next.js on port 3000. Next.js forwards API requests to FastAPI on the same host. The scheduler runs independently and updates the production SQLite ledger, which also holds the queue for Discord briefs and alerts. The operator places every order by hand. [Processes and deployment](docs/ARCHITECTURE.md#processes-and-deployment)

### Research stages

The scheduler registers independent jobs. Consensus passes its result to `record_decisions()` in memory and uses completed recommendation outcomes to weight the agents. The analysis job supplies the US pre-market BUY-candidate screen. [System flow](docs/ARCHITECTURE.md#system-flow)

| Stage | Package | Runs as | Writes |
|-------|---------|---------|--------|
| **Collect** | `nuri/collectors` | Collector jobs, every 5 minutes to weekly | `prices`, `signals`, `fundamentals`, `macro`, … |
| **Analyze** | `nuri/analysis` | `factors` job | `factors` |
| **Consensus** | `nuri/trading/agents` | `consensus` job | `recommendations` |
| **Decide** | `nuri/trading/engine` | Inside the consensus job | `decisions`, `decision_evidence` |
| **Track** | `nuri/trading/recommend` | Outcome and P&L jobs | `recommendations.outcome_*`, `decision_outcomes` |

**Stack** · Python 3.12, FastAPI, APScheduler, SQLite and Next.js. **Universe** · US equities and the KOSPI 200.

## Documentation

| Document | Contents |
|----------|----------|
| [`docs/STRATEGY.md`](docs/STRATEGY.md) | Principles, decisions and investment rules (authoritative) |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Pipeline, schedule, data sources, database, deployment, CI/CD |
| [`docs/FRESH_CLONE_SETUP.md`](docs/FRESH_CLONE_SETUP.md) | Setup from a fresh clone |
| [Dashboard README](frontend/README.md) | Frontend setup, API routing and browser tests |
| [Scripts index](scripts/README.md) | Development, verification and operations commands |
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

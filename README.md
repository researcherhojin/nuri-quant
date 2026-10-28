# Nuri-Quant

<div align="center">

[![CI/CD](https://github.com/researcherhojin/nuri-quant/actions/workflows/main-ci-cd.yml/badge.svg)](https://github.com/researcherhojin/nuri-quant/actions/workflows/main-ci-cd.yml)
[![codecov](https://codecov.io/gh/researcherhojin/nuri-quant/graph/badge.svg)](https://codecov.io/gh/researcherhojin/nuri-quant)
[![License](https://img.shields.io/badge/license-AGPL--3.0--or--later-blue.svg)](LICENSE)

**A quantitative decision-support platform that records and scores the evidence behind each investment recommendation.**

</div>

Nuri-Quant reviews a portfolio of US and Korean equities every day. It issues a dated BUY / SELL / HOLD for each holding together with the evidence behind it, then grades each recommendation against what the market actually did.

- **Recommendation only.** The system never places orders; the operator executes every trade by hand.
- **No performance claim.** No investment edge is claimed unless a pre-registered evaluation passes ([`docs/STRATEGY.md`](docs/STRATEGY.md) §3.11).
- **Not investment advice.** The output is a research record for one operator's own decisions.

## Table of Contents

- [Background](#background)
- [Install](#install)
- [Usage](#usage)
- [Tech Stack](#tech-stack)
- [Project Stats](#project-stats)
- [Documentation](#documentation)
- [Maintainers](#maintainers)
- [Acknowledgements](#acknowledgements)
- [Contributing](#contributing)
- [License](#license)

## Background

### What it does

| Task | Output |
|------|--------|
| Review every holding, every day | A dated BUY / SELL / HOLD per holding with the agent verdicts, market context and price levels behind it, kept in a decision ledger (`/decisions`) |
| Grade past recommendations | The raw return of every recommendation at 7 to 90 days, and for each BUY and SELL the 7-, 14- and 30-day return against a benchmark where one applies; in the next consensus each agent is weighted by its 30-day hit rate within a capped range (by its 21-day rate while 30-day samples are too few, at its default weight while both are), and the weights are then normalized together |
| Screen the universe | BUY candidates outside the portfolio, scored and gated by [`config/buy_signals.yaml`](config/buy_signals.yaml), with the scanner's observations kept separate from the verdict |
| Watch the inputs | A freshness SLA per data source, judged against each source's own schedule; when an input of the dashboard verdict fails it, the verdict is replaced by a stale-data notice |
| Show it on one page | The Overview dashboard (`/`): market indices, regime, macro score, holding reviews, portfolio composition, data freshness and pipeline status, each with its source |
| Send briefs | A US pre-market brief and US and Korean post-market briefs to Discord |
| Answer an AI client | A read-only MCP server with candidates, macro facts, freshness and live quotes, and no holdings |

The universe is US equities and the KOSPI 200. Korean prices come from pykrx, the KOSPI 200 list is approximated by the 200 largest KOSPI listings from FinanceDataReader, and Korean fundamentals come from yfinance. When KIS Open API credentials are set, KIS supplies the Korean P/E, P/B and market cap and the optional real-time quotes ([`docs/KIS_INTEGRATION.md`](docs/KIS_INTEGRATION.md)).

### How it works

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

### Pipeline

| Stage | Package | Role |
|-------|---------|------|
| **Collect** | `nuri/collectors` | Collects prices, fundamentals, macroeconomic data and news |
| **Analyze** | `nuri/analysis` | Analyzes portfolio risk and sector exposure; the daily `factors` job computes factor scores |
| **Consensus** | `nuri/trading/agents` | Combines eligible specialist verdicts per holding, subject to a risk veto; the 10-slot registry retains a retired, always-abstaining retail slot |
| **Decide** | `nuri/trading/engine` | Records each consensus decision with its market context and price levels |
| **Track** | `nuri/trading/recommend` | Measures recommendation outcomes at horizons from 7 to 90 days |

The stages are not chained by an orchestrator. `nuri/scheduler.py` registers 57 independent cron jobs, plus a one-minute heartbeat, and each job reads its inputs from database tables written by other jobs.

- Scheduling: 57 cron jobs · in-process
- Storage: SQLite WAL · 70 tables
- Market analytics: 22 trading signals · 10 regimes · a 4-factor composite score

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the system flow, the runtime topology, the daily schedule and the scoring model.

## Install

Requirements: Python 3.12 or later, [uv](https://docs.astral.sh/uv/), TA-Lib and Node.js 22. On macOS: `brew install uv ta-lib fnm && fnm install 22`.

```bash
git clone https://github.com/researcherhojin/nuri-quant.git && cd nuri-quant
cp config/portfolio.example.yaml config/portfolio.yaml  # holdings (gitignored); make setup imports it
make setup                                              # backend dependencies, database, git hooks
cd frontend && npm ci && cd ..                          # frontend dependencies
cp .env.example .env                                    # API keys (all optional)
```

Every API key is optional; a collector without credentials is skipped or falls back to a keyless source. [`docs/FRESH_CLONE_SETUP.md`](docs/FRESH_CLONE_SETUP.md) walks through the full setup.

## Usage

```bash
make start          # API on :8001 (OpenAPI at /docs), dashboard on :3000
make full-scan      # manual research run: core collectors, signal backtest, consensus, price targets
make migrate        # apply pending database migrations; collect and the scan targets run it first
make consensus      # run the agent consensus and record decisions
make test-fast      # backend tests, excluding slow tests
make verify-all     # pre-push checks: tests, lint, frontend
make help           # list all targets
```

`make full-scan` ends by sending a summary to Discord when `DISCORD_WEBHOOK_URL` is set, and to Telegram when both `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set; leave them unset on a development machine so that only the production host posts.

Discord `/thesis` runs an unscored, local-model analysis with stage progress and an allowlisted final card. It is separate from both public briefing generation and the scheduled research pilot; see [local thesis modes](docs/RESEARCH_BRIEFING.md#local-thesis-modes).

Investment rules and thresholds live in [`config/`](config/) (mainly `rules.yaml`); their rationale is in [`docs/STRATEGY.md`](docs/STRATEGY.md). Optional LLM features and their data-egress rules are described in §4.4.3 of the same document.

## Tech Stack

<!-- Badges show the major version only (major.minor for 0.x); tests/verify/test_readme_badges.py checks them against the installed versions (#1704) -->

**Frontend**<br/>
![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-6-3178C6?logo=typescript&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-4-06B6D4?logo=tailwindcss&logoColor=white)
![Recharts](https://img.shields.io/badge/Recharts-3-22B5BF)
![React Flow](https://img.shields.io/badge/React_Flow-12-FF0072)
![Zod](https://img.shields.io/badge/Zod-4-3E67B1?logo=zod&logoColor=white)

**Backend**<br/>
![FastAPI](https://img.shields.io/badge/FastAPI-0.161-009688?logo=fastapi&logoColor=white)
![Uvicorn](https://img.shields.io/badge/Uvicorn-0.54-2094F3)
![APScheduler](https://img.shields.io/badge/APScheduler-3-4B8BBE)
![MCP](https://img.shields.io/badge/MCP-2-000000?logo=modelcontextprotocol&logoColor=white)
![discord.py](https://img.shields.io/badge/discord.py-2-5865F2?logo=discord&logoColor=white)

**Data & Quant**<br/>
![pandas](https://img.shields.io/badge/pandas-2-150458?logo=pandas&logoColor=white)
![NumPy](https://img.shields.io/badge/NumPy-2-013243?logo=numpy&logoColor=white)
![TA-Lib](https://img.shields.io/badge/TA--Lib-0.8-0B3D91)
![yfinance](https://img.shields.io/badge/yfinance-1-720E9E)
![pykrx](https://img.shields.io/badge/pykrx-1-0046FF)

**Testing & Lint**<br/>
![pytest](https://img.shields.io/badge/pytest-9-0A9EDC?logo=pytest&logoColor=white)
![Vitest](https://img.shields.io/badge/Vitest-5-6E9F18?logo=vitest&logoColor=white)
![Testing Library](https://img.shields.io/badge/Testing_Library-16-E33332?logo=testinglibrary&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-1-2EAD33)
![Ruff](https://img.shields.io/badge/Ruff-0.15-D7FF64?logo=ruff&logoColor=white)
![ESLint](https://img.shields.io/badge/ESLint-9-4B32C3?logo=eslint&logoColor=white)
![oxlint](https://img.shields.io/badge/oxlint-1-32F3E9)

**Infra**<br/>
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Node](https://img.shields.io/badge/Node-22-5FA04E?logo=nodedotjs&logoColor=white)
![uv](https://img.shields.io/badge/uv-Package_Manager-DE5FE9?logo=uv&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-3-003B57?logo=sqlite&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-CI/CD-2088FF?logo=githubactions&logoColor=white)
![Dependabot](https://img.shields.io/badge/Dependabot-Enabled-025E8C?logo=dependabot&logoColor=white)
![Trivy](https://img.shields.io/badge/Trivy-Security_Scan-1904DA?logo=aqua&logoColor=white)
![Codecov](https://img.shields.io/badge/Codecov-Coverage-F01F7A?logo=codecov&logoColor=white)

## Project Stats

These values are verified against the code by `make verify-doc-counts`, which runs in the pre-push hook and in CI (CI skips the counts that need the Python environment).

| Metric | Value |
|--------|-------|
| Backend tests | 9,668 collected across 463 files |
| Frontend test files | 117 vitest files |
| Data collectors | 30 collector modules in `nuri/collectors/` |
| Scheduler jobs | 57 cron entries |
| API endpoints | 70 declared in `nuri/api/routes/` |
| Database | SQLite WAL · 70 tables, 78 forward-only migrations |

## Documentation

| Document | Contents |
|----------|----------|
| [`docs/STRATEGY.md`](docs/STRATEGY.md) | Principles, decisions and investment rules (authoritative) |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System flow, runtime topology and schedule, database, configuration, CI/CD |
| [`docs/THESIS_DISCORD.md`](docs/THESIS_DISCORD.md) | Discord analysis status, model ratings and private local evidence viewer |
| [`docs/OVERVIEW.md`](docs/OVERVIEW.md) | The Overview dashboard: panels, data refresh, responsive layout and verification |
| [`docs/RESEARCH_BRIEFING.md`](docs/RESEARCH_BRIEFING.md) | Ticker research, public briefing prompts, validation and known limitations |
| [`docs/FRESH_CLONE_SETUP.md`](docs/FRESH_CLONE_SETUP.md) | End-to-end setup from a fresh clone |
| [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md) | Pre-push checks and helper scripts for recurring development pitfalls |
| [`docs/KIS_INTEGRATION.md`](docs/KIS_INTEGRATION.md) | Korea Investment & Securities Open API: real-time quotes, investor flows, analyst opinions |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Workflow, required checks, pull request rules |
| [`SECURITY.md`](SECURITY.md) | Security policy and LLM egress rules |

The `docs/` documents above also have Korean editions, with technical terms in English, in [`docs/ko/`](docs/ko/). The English editions are official; for the pre-registered criteria in `docs/STRATEGY.md` §3.11 and §3.12, the Korean text is the record.

## Maintainers

[@researcherhojin](https://github.com/researcherhojin)

## Acknowledgements

- The specialist-agent consensus follows [TradingAgents](https://github.com/TauricResearch/TradingAgents), with rule-based agents in place of LLM agents.
- Data freshness policies follow [Dagster](https://docs.dagster.io/guides/observe/asset-freshness-policies).
- Portfolio optimization uses [Riskfolio-Lib](https://riskfolio-lib.readthedocs.io/).
- The investment rules are based on O'Neil (CAN SLIM) and Minervini (SEPA).
- An earlier portfolio-certification gate adapted from SIEGE Engine was retired in #1619 ([`docs/STRATEGY.md`](docs/STRATEGY.md) §6).

## Contributing

Open an issue to agree on scope before submitting a pull request. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the workflow and required checks.

## License

[AGPL-3.0-or-later](LICENSE)

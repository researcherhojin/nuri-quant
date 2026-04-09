# Nuri-Quant

<div align="center">

[![CI/CD Pipeline](https://github.com/researcherhojin/nuri-quant/actions/workflows/main-ci-cd.yml/badge.svg)](https://github.com/researcherhojin/nuri-quant/actions/workflows/main-ci-cd.yml)
[![codecov](https://codecov.io/gh/researcherhojin/nuri-quant/graph/badge.svg)](https://codecov.io/gh/researcherhojin/nuri-quant)
[![License](https://img.shields.io/badge/license-AGPL%20v3-blue.svg)](LICENSE)

**[Issues](https://github.com/researcherhojin/nuri-quant/issues)** · **[Strategy](docs/STRATEGY.md)**

</div>

Open-source quantitative investment platform that **proves why you should buy or sell** — not gut feeling. 24 data collectors, 10 specialist agents, and an 11-condition mechanical gate certify every recommendation before it reaches you.

## Architecture

```mermaid
graph LR
    subgraph Collect ["A · Collect"]
        D1["24 Collectors<br/>OpenBB · pykrx · FRED<br/>11 External Sources"]
    end
    subgraph Analyze ["B–D · Analyze"]
        D2["Portfolio · Risk · Sector<br/>20 Signal Backtest<br/>10-Regime Classifier"]
    end
    subgraph Decide ["E · Decide"]
        D3["10 Agents Consensus<br/>Decision Intelligence<br/>Learning Loop"]
    end
    subgraph Execute ["F–H · Execute"]
        D4["SIEGE 11-Gate<br/>Price Targets · Rebalance<br/>Evidence · Notify"]
    end

    Collect -->|"DB"| Analyze -->|"CSV"| Decide -->|"DB"| Execute

    style Collect fill:#1e293b,stroke:#5c6bc0,color:#e2e8f0
    style Analyze fill:#1e293b,stroke:#10b981,color:#e2e8f0
    style Decide fill:#1e293b,stroke:#f59e0b,color:#e2e8f0
    style Execute fill:#1e293b,stroke:#ef4444,color:#e2e8f0
```

```
nuri/
├── core/          # DB (sole sqlite3), rules, events, freshness, timezone
├── collectors/    # 24 modules — BaseCollector pattern
├── analysis/      # Portfolio, risk, sector, charts, evidence
├── quant/         # Regime classifier, signal backtest, VectorBT, multi-factor
├── trading/
│   ├── agents/    # 10 specialist agents + weighted consensus
│   ├── engine/    # SIEGE 11-gate, Decision Intelligence, learning memory
│   ├── strategy/  # Long/Short, mean-reversion, pairs trading
│   ├── recommend/ # Candidates, price targets, rebalance, tracker
│   └── execution/ # Alpaca · KIS · DryRun
├── api/           # FastAPI (57 endpoints) + SSE
├── alerts/        # Discord · Telegram
└── llm/           # Ollama (local) + OpenAI wrapper
```

**Design:** DB as sole integration point · Phase isolation (no cross-phase imports) · Config-driven rules (`config/*.yaml`) · Decision Intelligence (outcome tracking + learning loop) · Lean-cost stack (SQLite, Ollama local, ~$3.51/yr OpenAI)

## Key Features

- **Evidence-based decisions** — 8,000+ historical trade backtests across 20 signals validate every recommendation
- **Decision Intelligence** — Every BUY/SELL decision recorded with market context + agent evidence. 7/30/60/90-day outcome tracking feeds back into agent weight adjustment
- **10-regime market classification** — 6 base (bull/bear/sideways × high/low vol) + 4 special (recovery, euphoria, stagflation, sector rotation)
- **10 specialist agents** — Weighted consensus voting with SSE reasoning trace. Risk agent holds veto power (SELL + confidence ≥ 80 overrides all)
- **SIEGE certification** — [11-condition mechanical gate](https://github.com/nutshells3/Swarm-Intelligence-Engine-with-Gated-Execution). Single failure → REJECTED
- **Pipeline observability** — [Palantir Foundry](https://www.palantir.com/docs/foundry/data-lineage/overview)-style Data Health + [Dagster](https://docs.dagster.io/guides/observe/asset-freshness-policies) Freshness SLA

## Tech Stack

**Backend**<br/>
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?logo=sqlite&logoColor=white)

**Frontend**<br/>
![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=next.js&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![Tailwind CSS](https://img.shields.io/badge/Tailwind-4-06B6D4?logo=tailwindcss&logoColor=white)
![shadcn/ui](https://img.shields.io/badge/shadcn/ui-000000)

**Data & Quant**<br/>
![OpenBB](https://img.shields.io/badge/OpenBB-00C853)
![TA-Lib](https://img.shields.io/badge/TA--Lib-FF5722)
![VectorBT](https://img.shields.io/badge/VectorBT-9C27B0)
![pandas](https://img.shields.io/badge/pandas-150458?logo=pandas&logoColor=white)
![Riskfolio](https://img.shields.io/badge/Riskfolio-2196F3)

**LLM**<br/>
![Ollama](https://img.shields.io/badge/Ollama-local-000000?logo=ollama&logoColor=white)
![Qwen](https://img.shields.io/badge/Qwen3.5-35B-7C3AED)

**CI/CD**<br/>
![GitHub Actions](https://img.shields.io/badge/Actions-2088FF?logo=githubactions&logoColor=white)
![pytest](https://img.shields.io/badge/pytest-0A9EDC?logo=pytest&logoColor=white)
![Vitest](https://img.shields.io/badge/Vitest-6E9F18?logo=vitest&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-2EAD33?logo=playwright&logoColor=white)
![Ruff](https://img.shields.io/badge/Ruff-D7FF64?logo=ruff&logoColor=black)
![Codecov](https://img.shields.io/badge/Codecov-F01F7A?logo=codecov&logoColor=white)
![Trivy](https://img.shields.io/badge/Trivy-1904DA)

## Getting Started

### Prerequisites (macOS Apple Silicon)

```bash
# 1. Homebrew (if not installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. System dependencies
brew install uv ta-lib

# 3. Node.js 22 (fnm recommended)
brew install fnm
fnm install 22 && fnm use 22
echo 'eval "$(fnm env --use-on-cd)"' >> ~/.zshrc
```

### Setup

```bash
git clone https://github.com/researcherhojin/nuri-quant.git
cd nuri-quant

make setup                 # uv venv + deps + DB init + portfolio import
cd frontend && npm ci && cd ..

cp .env.example .env                                    # edit API keys (all optional)
cp config/portfolio.example.yaml config/portfolio.yaml  # edit your holdings

make test                  # backend tests (parallel via xdist)
cd frontend && npx vitest run && cd ..  # frontend tests
```

### Run

```bash
make start                 # API (:8001) + Dashboard (:3000)
make full-scan             # 8-phase pipeline: collect → certify → notify
make quick-scan            # Fast 4-step: collect → analyze → consensus → targets (~2 min)
make consensus             # 10-agent consensus + decision recording
make certify               # SIEGE 11-gate certification
```

After `make start`: Dashboard at <http://localhost:3000>, API docs at <http://localhost:8001/docs>.

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

## Multi-machine Workflow

Two patterns for running Nuri-Quant on more than one Mac. Pick whichever fits your hardware setup — they compose freely.

### Migrating state between machines

`scripts/sync_dev.sh` rsyncs everything git can't carry: gitignored project state (`.env`, `config/portfolio.yaml`, `data/portfolio.db`) plus Claude Code state (`~/.claude/projects/...` conversation history + memory + global skills/plugins/settings). Caches and runtime state are excluded.

```bash
# One-time setup on each machine
sudo systemsetup -setremotelogin on             # both Macs
ssh-copy-id <other-mac>.local                   # passwordless SSH (uses $USER)

# Tell the script who the "other" machine is. Put this in ~/.zshrc, NOT .env.
echo 'export DEV2_HOST=<other-mac>.local' >> ~/.zshrc
source ~/.zshrc

# Recurring sync (run on whichever machine has the freshest state)
scripts/sync_dev.sh push                        # this laptop → other
scripts/sync_dev.sh pull                        # other → this laptop
scripts/sync_dev.sh push --with-reports         # include data/reports/ (~136MB)
scripts/sync_dev.sh push --no-claude            # project files only, skip ~/.claude
```

### Auto-pull receiver (portable dev → always-on prod)

```bash
# On the receiver (always-on Mac), one-time setup
cp scripts/com.nuri-quant.autopull.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.nuri-quant.autopull.plist

# Verify
launchctl list | grep nuri-quant.autopull
tail -f ~/Library/Logs/nuri-quant-autopull.log
```

The agent runs `scripts/auto_deploy.sh` every 5 minutes: fetch → ff-only merge → dependency/schema drift warning → deploy hook.

## References

| Source | Application |
|--------|-------------|
| [SIEGE Engine](https://github.com/nutshells3/Swarm-Intelligence-Engine-with-Gated-Execution) | 11-condition gate, certification, event journal |
| [Palantir Foundry](https://www.palantir.com/docs/foundry/data-lineage/overview) | Data Health, pipeline monitoring, Decision Intelligence |
| [Dagster](https://docs.dagster.io/guides/observe/asset-freshness-policies) | Asset freshness PASS/WARN/FAIL |
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | Multi-agent consensus pattern |
| [O'Neil — CAN SLIM](https://www.investors.com/) | Stop-loss -7%, take-profit +20%/+40% |
| [Minervini — SEPA](https://www.minervini.com/) | Trailing stop, 3:1 reward-to-risk |

## License

[GNU Affero General Public License v3.0](LICENSE)

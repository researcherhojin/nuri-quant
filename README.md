# Nuri-Quant

<div align="center">

[![CI/CD](https://github.com/researcherhojin/nuri-quant/actions/workflows/main-ci-cd.yml/badge.svg)](https://github.com/researcherhojin/nuri-quant/actions/workflows/main-ci-cd.yml)
[![codecov](https://codecov.io/gh/researcherhojin/nuri-quant/graph/badge.svg)](https://codecov.io/gh/researcherhojin/nuri-quant)
[![License](https://img.shields.io/badge/license-AGPL%20v3-blue.svg)](LICENSE)

</div>

An open-source quant platform that **proves the evidence behind every investment decision**.

Every BUY/SELL recommendation runs through a **collect → analyze → consensus → certify → track** pipeline. Each decision is recorded with its market context and per-agent reasoning, then automatically scored against actual outcomes after 30/60/90 days. The system gets more accurate as outcomes accumulate — agent weights adjust within a ±30% band based on hit rate.

## Architecture

```mermaid
flowchart LR
    A["<b>Collect</b><br/>24 collectors<br/>419 ticker universe"]
    B["<b>Analyze</b><br/>20 signals · 10 regimes"]
    C["<b>Consensus</b><br/>10 agents weighted vote"]
    D["<b>Certify</b><br/>SIEGE 11-gate"]
    E["<b>Track</b><br/>30/60/90d outcome"]

    A -- DB --> B -- CSV --> C -- DB --> D -- DB --> E
    E -. "weight feedback" .-> C

    style A fill:#1e293b,stroke:#6366f1,color:#e2e8f0
    style B fill:#1e293b,stroke:#10b981,color:#e2e8f0
    style C fill:#1e293b,stroke:#f59e0b,color:#e2e8f0
    style D fill:#1e293b,stroke:#ef4444,color:#e2e8f0
    style E fill:#1e293b,stroke:#8b5cf6,color:#e2e8f0
```

| Layer | Role |
|-------|------|
| `nuri/collectors/` | 24 data collectors (OpenBB, pykrx, FRED, edgartools, FINVIZ, KIS Open API) |
| `nuri/quant/` | Signal backtest (20 signals), regime classifier (10 regimes), multi-factor scoring, VectorBT |
| `nuri/trading/agents/` | 10 specialist agents + weighted consensus (risk agent has SELL veto at confidence ≥ 80) |
| `nuri/trading/engine/` | SIEGE 11-gate certification + Decision Intelligence + learning memory |
| `nuri/api/` | FastAPI REST + SSE streaming on port 8001 |
| `frontend/` | Next.js 16 dashboard (16 pages, dark theme, Tailwind 4 + shadcn/ui) |
| `nuri/core/db.py` | Sole SQLite gateway (31 tables, WAL mode). Every other module reads/writes through here |
| `config/` | All thresholds and rules — `rules.yaml`, `agents.yaml`, `signals.yaml`, `universe.yaml` (419 tickers) |

## Tech Stack

| Layer | Stack |
|-------|-------|
| **Backend** | Python 3.12 · FastAPI · SQLite (WAL) · uv |
| **Frontend** | Next.js 16 · React 19 · Tailwind 4 · shadcn/ui |
| **Quant** | pandas · TA-Lib · VectorBT · OpenBB · Riskfolio-Lib · yfinance |
| **CI/CD** | GitHub Actions · pytest (xdist + shard) · Vitest · Playwright · Ruff · Codecov · Trivy |

### LLM (optional, off by default)

Both LLM integrations are **wired but inactive** unless you set the corresponding environment variable. The system runs without any LLM and falls back to regex/rule-based logic. See [`docs/STRATEGY.md`](docs/STRATEGY.md#443-외부-llm-egress-policy-152) §4.4.3 for the egress policy.

| Provider | Purpose | Activation | Data class |
|----------|---------|------------|------------|
| **Ollama** (local) | Daily LLM report (`make report-llm`) | `OLLAMA_HOST` set + Ollama running locally | Tier 2 (portfolio) — local only, never leaves machine |
| **OpenAI gpt-5.4-nano** | RSS headline classification | `OPENAI_API_KEY` set | Tier 0 (public news only). ~$3.51/yr at 100 headlines/day |

The egress policy is enforced by `nuri/llm/openai_client.py`: a single wrapper logs every external call to the `external_llm_calls` table (timestamp/model/tokens, **no content**), and `NURI_DISABLE_EXTERNAL_LLM=1` raises immediately.

## Getting Started

```bash
# Prerequisites: Python 3.12, uv, ta-lib, Node 22
brew install uv ta-lib fnm && fnm install 22

# Setup
git clone https://github.com/researcherhojin/nuri-quant.git && cd nuri-quant
make setup                                              # backend (uv venv + deps + DB init)
cd frontend && npm ci && cd ..                          # frontend
cp .env.example .env                                    # API keys (all optional)
cp config/portfolio.example.yaml config/portfolio.yaml  # your holdings (gitignored)

# Run
make start          # API (:8001) + Dashboard (:3000)
make full-scan      # 8-phase pipeline end-to-end
make consensus      # 10-agent analysis + decision recording
make certify        # SIEGE 11-gate certification
make scan           # Daily scan (us_core, ~85 tickers)
make scan-extended  # Weekly scan (us_core + S&P 500, ~339 tickers)
```

### Test commands

```bash
make test       # full suite (2,633 backend + 634 frontend)
make test-fast  # backend only, slow tests excluded (~24s, ~52% faster)
make test-slow  # backend slow tests only (LLM gather_context, scheduler)
```

## Investment Rules

Defined in `config/rules.yaml` and loaded via `nuri/core/rules.py`. Sources: O'Neil (CAN SLIM), Minervini (SEPA), Shefrin & Statman (1985, 처분효과 / disposition effect).

### Account strategy profiles

Each account in `config/portfolio.yaml` selects one strategy via the `strategy` field. Stricter strategies cut losses earlier and limit concentration; looser strategies allow winners to grow.

| Strategy | Stop-Loss | Max Single Position | Notes |
|----------|-----------|---------------------|-------|
| `core` | -7% | 15% | Default. Strict O'Neil-style discipline |
| `active` | -10% | 25% | + `trailing_stop_arm: 15` — trailing stop auto-arms at +15% to protect winners |
| `swing` | -15% | 30% | Short-term rotations only |
| `long_term` | -20% | 25% | Buy-and-hold ETFs |
| `pension` | -30% | 40% | Long-horizon retirement allocations |

### Take-profit by stock type

Each ticker is tagged growth/value via `config/stock_types.yaml`. Take-profit and trailing-stop levels apply per type.

| Type | 1st Target | 2nd Target | Trailing |
|------|-----------|-----------|----------|
| Growth | +20% (sell 50%) | +40% (sell 25%) | -15% from HWM |
| Value | +15% (sell 50%) | +30% (sell 25%) | -15% from HWM |

### Hard gates (always-on, no override)

- **VIX > 30** → new buys blocked
- **execution_priority** → stop-loss → take-profit → trailing → new-buy (loss largest first)
- **Buy checklist** → TipRanks ≥ Moderate Buy · superinvestors ≥ 3 · PE < 100 · revenue > $0 · multi-factor top 50%
- **SIEGE 11-gate** → 1 error grade failure = REJECTED, no manual override

## References

| Source | Usage |
|--------|-------|
| [SIEGE Engine](https://github.com/nutshells3/Swarm-Intelligence-Engine-with-Gated-Execution) | 11-gate certification, event journal |
| [Palantir Foundry](https://www.palantir.com/docs/foundry/data-lineage/overview) | Decision Intelligence pattern |
| [Dagster](https://docs.dagster.io/guides/observe/asset-freshness-policies) | Freshness SLA (PASS/WARN/FAIL) |
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | Multi-agent consensus pattern |
| [VectorBT](https://vectorbt.dev/) | Vectorized backtest |
| [Riskfolio-Lib](https://riskfolio-lib.readthedocs.io/) | Portfolio optimization |
| [OpenBB](https://docs.openbb.co/) | Unified financial data abstraction |

## License

[AGPL-3.0](LICENSE)

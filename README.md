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
flowchart TB
    CFG[/"config/*.yaml<br/>policies (YAML loaders in nuri/core)"/]:::source

    subgraph Pipeline["5-phase decision pipeline (DB-only coupling)"]
        direction TB
        A(["① Collect<br/>26 data collectors"]):::pipe
        B(["② Analyze<br/>signals · regimes · factors"]):::pipe
        C(["③ Consensus<br/>10-agent weighted vote"]):::pipe
        D(["④ Certify<br/>SIEGE v2 (3-D gates)"]):::pipe
        E(["⑤ Track<br/>30d / 60d / 90d outcomes"]):::pipe

        A --> B --> C --> D --> E
        E -. "agent weight drift (±30%)" .-> C
    end

    DB[("SQLite WAL · 49 tables<br/>pipeline_events · certifications · audit trail")]:::sink

    CFG -. policies .-> Pipeline
    Pipeline -. persist .-> DB

    classDef source fill:#1e293b,stroke:#64748b,color:#e2e8f0
    classDef pipe   fill:#0f3057,stroke:#3b82f6,color:#dbeafe
    classDef sink   fill:#0f172a,stroke:#334155,color:#cbd5e1
```

**Phase content** (the diagram keeps node text light; full counts here):

| Phase | What it does | Inputs → Outputs |
|-------|--------------|------------------|
| ① **Collect** | 26 collectors — US: yfinance / OpenBB · KR: pykrx · Macro: FRED · News: GoogleNews RSS · 13F: edgartools · KIS Open API | external APIs → `prices` · `fundamentals` · `macro` · `news` · `institutional_flows` |
| ② **Analyze** | 22 signals (20 actionable + 2 SHADOW crash precursors) · 10 regimes (6 base + 4 special) · 3 factor scorers + composite aggregator · 15 macro event categories | DB → `signals` · `factors` · `regime_transitions` · `macro_events` |
| ③ **Consensus** | 10 specialist agents · weighted vote · risk-agent veto fires on `alpha_action==FLAT` only | DB → `recommendations` (incl. `agent_verdicts`, `scoring_detail` JSON columns) |
| ④ **Certify** | SIEGE v2 — Account × Asset Class × Execution Market. 1 error-grade fail → REJECTED, no manual override | DB → `certifications` (incl. `conditions_json` evidence + `portfolio_hash`) |
| ⑤ **Track** | 30 / 60 / 90 d outcomes vs prediction → agent accuracy snapshot → weight drift bounded ±30 % (feedback to ③) | DB → `recommendations.outcome_{30,60,90}d` columns (in-place update); `strategy_memory` rows for agent accuracy snapshots |

Phases never import each other — communication is via SQLite tables / CSV only. Rerun any upstream phase and downstream consumers refresh automatically. Per-phase implementation detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). SIEGE certification spec: [`docs/SIEGE_V2.md`](docs/SIEGE_V2.md).

### Architectural principles

The system rests on five enduring decisions. Recent feature additions and tuning history live in [`docs/STRATEGY.md`](docs/STRATEGY.md) §3 (Architecture decisions) and `git log`.

| # | Principle | What it means in practice |
|---|-----------|---------------------------|
| 1 | **Sole SQLite gateway** | `nuri/core/db.py` is the only `sqlite3` importer (hook-enforced — every other module uses `query()` / `upsert_*()` / `get_db()` with optional `db_path=` for test isolation). 48 tables, WAL mode. |
| 2 | **Config over code** | Stop-loss thresholds, agent weights, signal metadata, SIEGE gate policies — all in `config/*.yaml`. Changing a rule or adding a market means editing YAML, never Python. |
| 3 | **Loose phase coupling** | Pipeline phases communicate via DB tables / CSV only. No cross-phase imports. Re-run any upstream phase and downstream consumers refresh. |
| 4 | **3-D SIEGE certification** | Gates apply per `Account (strategy)` × `Asset Class (us_equity / kr_equity / kr_index / commodity / bond)` × `Execution Market`. 1 error-grade fail → REJECTED, no manual override. Inspired by [nutshells3/SIEGE](https://github.com/nutshells3/Swarm-Intelligence-Engine-with-Gated-Execution). |
| 5 | **Alpha vs portfolio action axes** | `recommendations` carries orthogonal `alpha_action ∈ {LONG, SHORT, FLAT}` and `portfolio_action ∈ {REBALANCE, TRIM, HEDGE, NONE}`. Concentration violations emit `portfolio_action=REBALANCE` only — never urgent SELL. Stop-loss breach is the only mechanical that emits `alpha_action=FLAT`. |

### Code layout (by pipeline phase)

| Phase | Path | Role |
|-------|------|------|
| **Collect** | `nuri/collectors/` | 26 collectors (BaseCollector pattern). US: yfinance / OpenBB. KR: pykrx + KOSPI / KOSDAQ index. Macro: FRED / yfinance. News: GoogleNews RSS. KIS Open API: `kis_realtime` (잔고/시세) + `kis_analyst_opinion` (애널리스트 의견). |
| **Analyze** | `nuri/quant/regime/` | Regime classifier (10 regimes), macro score (9 indicators), event score (15 categories). |
|  | `nuri/quant/validation/` | Signal backtest engine over `config/signals.yaml` (20 actionable + 2 shadow precursors), superinvestor / analyst backtest, scorecard. |
|  | `nuri/quant/factors/` | Multi-factor scoring — momentum / value / quality / composite. |
| **Consensus** | `nuri/trading/agents/` | 10 specialist agents + weighted vote. Risk-agent veto on `alpha_action==FLAT`. Korean Market Agent reads `macro_events`. |
| **Certify** | `nuri/trading/engine/` | SIEGE v2 (3-D) — per-asset-class expansion, conflict detection, evidence trail, learning memory. |
|  | `nuri/trading/recommend/` | Candidates, price targets, rebalance advisor, outcome tracker (30 / 60 / 90d). |
| **Serve** | `nuri/api/` | FastAPI REST + SSE on **:8001** (69 endpoints incl. `/actions`, `/opportunities`, `/market-context`, `/coverage`). Swagger at `/docs`. |
|  | `frontend/` | Next.js 16 + React 19 + Tailwind 4 + shadcn/ui on **:3000** (17 routes, Action-First dashboard, dark theme). |
| **Foundation** | `nuri/core/` | `db.py` (sole SQLite gateway) · `events.py` (journal) · `freshness.py` (SLA) · `timezone.py` (KST) · `rules.py` · `signal_config.py` · `axis.py` (alpha/portfolio helpers). |
|  | `config/*.yaml` | `rules` · `agents` · `signals` · `universe` · `stock_types` · `portfolio` (gitignored) · `kis/` (gitignored credentials). |
| **LLM gateway** | `nuri/llm/` | `openai_client.py` (sole external entry, audit-logged) · event classifier · LLM daily report (OpenAI primary, llama.cpp / Ollama fallback). |

## Dashboard

The dashboard at `:3000/` answers **"what should I do today?"** — Action-First design that surfaces actionable intelligence ahead of raw data. Pension / IRP holdings are filtered out (monthly rebalance cadence ≠ daily decision).

| Section | Purpose |
|---------|---------|
| **Hero** | 4-stat ribbon — 총 자산 · 오늘 P&L · 누적 수익률 · 승률 |
| **System Health** | 4 cards linking to detail pages — SIEGE score · Regime · Macro score · Data freshness |
| **Macro Events** | Deduplicated high-impact headlines with 한국어 category labels (지정학/실적/유가 등) |
| **Action Items** | 🔴 즉시 실행 (SIEGE violations, stop-loss breach) · 🟡 오늘 확인 (take-profit, short squeeze) · 🟦 리밸런스 (concentration, sector cap) · ✅ 유지 |
| **Market Context strip** | VIX · 심리 · 경제 · 실제/권장 비중 |
| **Composition** | Donut chart with 자산 / 섹터 / 계좌 tabs |
| **Holdings table** | Sorted by `positionPct` desc, top 8 + expand toggle |
| **Opportunity Explorer** | Top 3 non-portfolio tickers with pros / cons / verdict + 10-Agent 분석 deep-link |

Korean tickers display as names (삼성전자) instead of codes (005930.KS). Row-level decisions live on `/portfolio` and `/advisor` (17 routes total).

## Tech Stack

| Layer | Stack |
|-------|-------|
| **Backend** | Python 3.12 · FastAPI · SQLite (WAL) · uv |
| **Frontend** | Next.js 16 · React 19 · Tailwind 4 · shadcn/ui |
| **Quant** | pandas · TA-Lib · VectorBT · OpenBB · Riskfolio-Lib · yfinance |
| **CI/CD** | GitHub Actions · pytest (xdist + shard) · Vitest · Playwright · Ruff · Codecov · Trivy |

### LLM (optional, off by default)

All LLM integrations are **wired but inactive** unless you set the corresponding environment variable. The system runs without any LLM and falls back to regex/rule-based logic. See [`docs/STRATEGY.md`](docs/STRATEGY.md#443-외부-llm-egress-policy-152) §4.4.3 for the egress policy.

| Provider | Purpose | Activation | Data class |
|----------|---------|------------|------------|
| **OpenAI gpt-5.4-nano** | RSS headline classification | `OPENAI_API_KEY` set | Tier 0 (public news). ~$3.51/yr at 100 headlines/day |
| **OpenAI gpt-5.4-nano** | Daily LLM report (`make report-llm`) | `OPENAI_API_KEY` + `OPENAI_ZDR_APPROVED=1` | Tier 2 (portfolio) — ZDR required. ~$0.10/yr at 1 call/day |
| **llama.cpp** (local) | Daily LLM report fallback | `LLAMA_MODEL_PATH` set | Tier 2 — local only |
| **Ollama** (local) | Daily LLM report fallback | `OLLAMA_HOST` set + Ollama running | Tier 2 — local only |

The egress policy is enforced by `nuri/llm/openai_client.py`: a single wrapper logs every external call to the `external_llm_calls` table (timestamp/model/tokens, **no content**), and `NURI_DISABLE_EXTERNAL_LLM=1` raises immediately.

## Getting Started

```bash
# Prerequisites: Python 3.12, uv, ta-lib, Node 22
brew install uv ta-lib fnm && fnm install 22

# Setup
git clone https://github.com/researcherhojin/nuri-quant.git && cd nuri-quant
make setup                                              # backend (uv venv + deps + DB init + git hooks)
cd frontend && npm ci && cd ..                          # frontend
cp .env.example .env                                    # API keys (all optional)
cp config/portfolio.example.yaml config/portfolio.yaml  # your holdings (gitignored)

# Run
make start          # API (:8001) + Dashboard (:3000)
make full-scan      # 8-phase pipeline end-to-end
make consensus      # 10-agent analysis + decision recording
make certify        # SIEGE v2 certification (asset-class per-expansion)
make scan           # Daily scan (us_core, 85 tickers)
make scan-extended  # Weekly scan (us_core + S&P 500, 543 tickers)
```

### Test commands

```bash
make test       # full suite — 4,485 backend (187 files) + 989 frontend (81 files) + 8 Playwright e2e specs
make test-fast  # backend only, slow tests excluded (~24s, what PR CI runs)
make test-slow  # backend slow tests only (LLM gather_context, scheduler integration)
```

### Production deployment

The reference operator setup runs across two Apple Silicon Macs (MBP dev → Mac mini 24/7 receiver) with `make deploy-mini` 1-command sync.

## Investment Rules

Rules live in `config/rules.yaml` (loaded via `nuri/core/rules.py`); code never hardcodes them. Sources: O'Neil (CAN SLIM), Minervini (SEPA), Shefrin & Statman (1985, 처분효과 / disposition effect).

| Strategy | Stop-loss | Risk profile |
|----------|-----------|-------|
| `core` | -7% | Default — strict O'Neil discipline |
| `active` | -10% | Cut losses early, auto-trailing-stop arms at +15% |
| `swing` | -15% | Short-term 5–20d rotations |
| `long_term` | -20% | Buy-and-hold ETFs |
| `pension` | -30% | Long-horizon retirement allocations |

Take-profit ladders (growth: +20% / +40% / -15% trailing; value: +15% / +30% / -15%) and hard gates (VIX > 30 blocks new buys, SIEGE v2 certification rejects on any error-grade gate fail) apply on top. Full tables with per-class thresholds and the full rationale: [`docs/STRATEGY.md §3.4-§3.5, §6`](docs/STRATEGY.md) and [`config/rules.yaml`](config/rules.yaml).

## References

| Source | Usage |
|--------|-------|
| [SIEGE Engine](https://github.com/nutshells3/Swarm-Intelligence-Engine-with-Gated-Execution) | Policy-driven gate certification (v2: asset-class expansion), safety lattice, iterative learning |
| [OAE](https://github.com/nutshells3/orchestration-assurance-engine) | Claim trace, evidence lineage, audit pipeline |
| [safeslice](https://github.com/nutshells3/safeslice) | Statistical reliability bounds, witness cliff detection (Phase 4 target) |
| [fwp](https://github.com/nutshells3/fwp) | Protocol seam pattern, governed job lifecycle |
| [Palantir Foundry](https://www.palantir.com/docs/foundry/data-lineage/overview) | Decision Intelligence pattern |
| [Dagster](https://docs.dagster.io/guides/observe/asset-freshness-policies) | Freshness SLA (PASS/WARN/FAIL) |
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | Multi-agent consensus pattern |
| [VectorBT](https://vectorbt.dev/) | Vectorized backtest |
| [Riskfolio-Lib](https://riskfolio-lib.readthedocs.io/) | Portfolio optimization |
| [OpenBB](https://docs.openbb.co/) | Unified financial data abstraction |

## Further Documentation

- [`docs/STRATEGY.md`](docs/STRATEGY.md) — project philosophy, architectural decisions, investment rules, harness theory
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — detailed code/DB layout, schema, env vars, CI/CD
- [`docs/SIEGE_V2.md`](docs/SIEGE_V2.md) — 3-D certification spec (Account × Asset Class × Market)
- [`docs/KIS_INTEGRATION.md`](docs/KIS_INTEGRATION.md) — KIS (Korea Investment & Securities) Open API integration
- [`CLAUDE.md`](CLAUDE.md) — agent guide (Claude Code) — commands, always-on invariants, load triggers
- [`AGENTS.md`](AGENTS.md) — cross-tool agent guide (Cursor / Copilot / Codex CLI)
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — development workflow, PR discipline
- [`SECURITY.md`](SECURITY.md) — security policy, LLM egress rules, credential handling

## License

[AGPL-3.0](LICENSE)

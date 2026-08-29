# Nuri-Quant

<div align="center">

[![CI/CD](https://github.com/researcherhojin/nuri-quant/actions/workflows/main-ci-cd.yml/badge.svg)](https://github.com/researcherhojin/nuri-quant/actions/workflows/main-ci-cd.yml)
[![codecov](https://codecov.io/gh/researcherhojin/nuri-quant/graph/badge.svg)](https://codecov.io/gh/researcherhojin/nuri-quant)
[![License](https://img.shields.io/badge/license-AGPL%20v3-blue.svg)](LICENSE)

**Quant platform that proves the evidence behind every investment decision.**

</div>

Every BUY / SELL recommendation moves through five stages — **collect → analyze → consensus → certify → track** — coupled through SQLite tables rather than chained by an orchestrator. Each decision records its market context and per-agent reasoning, then scores itself against the realized outcome at 30 / 60 / 90 days. Agent weights adjust from the 30-day hit rate, bounded to ±30% of their configured base.

## Table of Contents

- [Security](#security)
- [Background](#background)
- [Install](#install)
- [Usage](#usage)
- [Investment Rules](#investment-rules)
- [LLM Integration](#llm-integration)
- [Deployment](#deployment)
- [Tech Stack](#tech-stack)
- [Project Stats](#project-stats)
- [Documentation](#documentation)
- [Maintainers](#maintainers)
- [Acknowledgements](#acknowledgements)
- [Contributing](#contributing)
- [License](#license)

## Security

The repository is public and the platform reads a real portfolio. Two controls follow — one mechanical, one not, and the difference matters.

**Personal financial data cannot reach the repo — mechanically.** `scripts/verify/check_privacy_leak.py` runs as a pre-push hook and as the required `Privacy Leak Scan` CI job. It blocks Korean broker names and their romanized variants, monetary literals of 7 digits or more sitting near keys like `total_invested` or `cash_balance`, and ticker-with-signed-percentage combinations. `config/portfolio.yaml` is gitignored and never scanned; fixtures use placeholders (`Brokerage Alpha`, round-million values).

**Portfolio data reaching an external model is blocked by convention, not by a hook.** `nuri/llm/openai_client.py` is the single external-LLM entry point, and everything enforced there is real: each call is logged to `external_llm_calls` (timestamp / model / tokens, never content), portfolio-bearing prompts require `OPENAI_ZDR_APPROVED=1`, and `NURI_DISABLE_EXTERNAL_LLM=1` raises before any request leaves the process. But nothing stops a new module from importing `openai` directly — unlike the `sqlite3` sole-importer rule, which an AST sweep in CI enforces, a stray `import openai` passes CI silently and is caught only in review.

In production the API binds `127.0.0.1`, not `0.0.0.0`. The Next.js proxy is the only reachable surface and sits behind a password gate. Reporting, accepted risks, and the full control list: [`SECURITY.md`](SECURITY.md).

## Background

### What this system claims — and what it does not

The point of the project is that a recommendation is auditable, not that it is right. Two constraints follow, and both are enforced rather than aspirational:

- **It recommends; it never trades.** A broker adapter with a working `submit_order` does exist (`nuri/trading/execution/broker.py`), and **no pipeline code path calls it.** Being exact, because this is a safety claim: the module's own `main()` always places a one-share test order when run by hand, and `--live` decides *which broker receives it* — without the flag a `DryRunBroker` that touches no network, with it `AlpacaBroker` against the paper endpoint. Nothing scheduled, and nothing in the decision path, reaches either. The pipeline terminates at a recommendation and an alert; the operator places every order by hand. Wiring execution back in requires a `docs/STRATEGY.md` amendment, not a code change alone (§7.1).
- **No edge is claimed.** `GET /api/alpha` returns `edge_status: "NOT_MEASURABLE"` unconditionally, and it will keep doing so until a pre-registered test passes. The criteria were fixed on 2026-07-08 and cannot be amended before the evaluation date: **a minimum of 200 US BUY decisions, benchmark SPY, ticker-block permutation p below 0.05, evaluated 2027-06-30** (§3.11). Until then, capital following system recommendations is capped inside an experiment sleeve, and the tracking numbers on the dashboard are labeled tracking-completeness, not performance.

If you are looking for a backtested strategy with a published Sharpe ratio, this is not that. It is the measurement apparatus you would need before you could honestly publish one.

### How it works

Start with what the system is for. The daily decision loop scores **the holdings you already own** and records why. A separate scan surfaces non-portfolio candidates (`/api/opportunities`, and the BUY candidates in the morning brief), so the two paths are worth keeping apart in your head. Neither places an order.

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

The loop at the bottom is the point of the project: a recommendation is not finished when it is made, only when reality has graded it.

#### What actually runs it — no orchestrator

There is no pipeline runner. `nuri/scheduler.py` registers 59 independent APScheduler jobs — **59 cron jobs · in-process**, nothing chaining them — and each becomes runnable when its inputs happen to already be in the database. Stages reach each other through SQLite tables, with exactly one exception.

```mermaid
flowchart TB
    CLOCK["APScheduler — 59 registered jobs<br/>no job calls another"]

    subgraph JOBS["What those 59 jobs are"]
        JC["collect · 29"]
        JA["analyze · 1"]
        JD["consensus · 1"]
        JT["track · 5"]
        JO["operate · 23<br/>briefs · dispatchers · watchdogs · backup"]
    end

    DB[("SQLite WAL · 61 tables")]
    RD["record_decisions()<br/>inside the consensus job"]
    CERT["certify() · no job<br/>runs inside its callers"]
    OUT["Discord brief · dashboard"]

    CLOCK --> JOBS
    JC --> DB
    JA --> DB
    DB --> JD
    JD ==> RD
    RD --> DB
    DB --> JT
    JT --> DB
    DB --> JO --> OUT
    JO --> CERT
    CERT --> DB

    classDef step  stroke:#3b82f6,stroke-width:2px
    classDef store stroke:#64748b,stroke-width:2px
    classDef out   stroke:#14b8a6,stroke-width:2px
    classDef zone  fill:none,stroke:#94a3b8,stroke-width:1px
    class CLOCK,JC,JA,JD,JT,JO,RD,CERT step
    class DB store
    class OUT out
    class JOBS zone
```

The counts sum to the whole: 29 + 1 + 1 + 5 + 23 = 59. The **thick arrow is the single exception** to DB coupling — `nuri/scheduler.py` hands the consensus result to `record_decisions()` as a Python object, never through a table. That is why `decisions` sat frozen for three and a half months when automation replaced the CLI path and dropped that one call (#897).

**`certify` is the only stage with no job of its own, and the consensus job does not call it.** `certify()` reads a DB snapshot and is invoked by `premarket_brief`, by `engine/remediation`, by its own CLI, and by three API routes (`/api/certify`, `/api/actions` health and violations). Every such call persists a `certifications` row — including a dashboard health check, which is why the API is not read-only.

| Stage | Scheduled as | Reads | Writes |
|-------|--------------|-------|--------|
| **Collect** | 29 jobs, `*/5` during market hours down to weekly | external APIs | `prices` · `fundamentals` · `macro` · `news` |
| **Analyze** | 1 job — `factors`, `10 8 * * *` | `prices` · `fundamentals` · `macro` (fear & greed) | `factors` |
| **Consensus** | 1 job — `consensus`, `5 7 * * *` | `recommendations.outcome_30d` (for weights) · collector tables | `recommendations` with `agent_verdicts` JSON |
| **Certify** | **no job of its own** — runs inside its callers: `premarket_brief`, `engine/remediation`, its own CLI, and three API routes. **Not** the consensus job | a DB snapshot of portfolio state | `certifications` |
| **Track** | 5 jobs — `decision_pnl` `0 7`, `recommendation_outcomes` `2 7`, `thesis_criteria` `20 8`, `alpha_tracking` `0 17`, `agent_accuracy` weekly | `recommendations` · `prices` · `decisions`; `thesis_criteria` also reads `theses` · `signals` · `factors` · `fundamentals` | `recommendations.outcome_{30,60,90}d` · `decision_outcomes` · `strategy_memory` · `thesis_criteria_checks`; `decision_pnl` writes back into `decisions` |

#### The clock does not follow the reading order

`collect → analyze → consensus → certify → track` is the order the stages are *named*, not the order they *run*. Nothing chains them, so the clock is free to violate it — and does.

```mermaid
flowchart LR
    T0["07:00<br/>decision_pnl<br/>track"]
    T1["07:02<br/>recommendation_outcomes<br/>track"]
    T2["07:05<br/>consensus<br/>consensus"]
    T3["08:10<br/>factors<br/>analyze"]
    T4["08:20<br/>thesis_criteria<br/>track"]
    T5["17:00<br/>alpha_tracking<br/>track"]
    T6["22:00–23:00 KST<br/>premarket_brief<br/>09:00 US/Eastern"]

    RECS[("recommendations")]

    T1 -->|closes| RECS
    RECS -.->|reads| T2
    T2 -->|writes| RECS

    classDef step  stroke:#3b82f6,stroke-width:2px
    classDef store stroke:#64748b,stroke-width:2px
    class T0,T1,T2,T3,T4,T5,T6 step
    class RECS store
```

Read the stage labels left to right: track, track, consensus, analyze, track, track, brief. The sharpest case is the three minutes between 07:02 and 07:05 — outcome tracking runs *before* the consensus job that consumes what it wrote, so consensus reads yesterday's closed windows, not today's. `premarket_brief` is the one job with a timezone override (`US/Eastern`), so its `0 9 * * 1-5` lands late in the Korean evening, after everything else.

Every stage is therefore re-runnable in isolation, which is the property the design is actually buying.

#### Cross-stage isolation holds in one narrow sense

The stages map to `nuri/collectors`, `nuri/analysis`, `nuri/trading/agents`, `nuri/trading/engine` and `nuri/trading/recommend` — a mapping no document stated until #922 wrote it down, which is why the older, stronger claim ("DB tables / CSV only") was not merely false but unfalsifiable. An AST sweep finds 17 imports crossing those boundaries over 15 distinct (file, module) pairs. Every one is a deferred function-body import and none is module-level, which is the only sense in which the rule holds: there is no load-time coupling, but each is a live call path. `certify` and `track` are mutually dependent (`engine/conflicts.py` calls `recommend/candidates.screen_candidates`, which calls `engine/conflicts.detect_conflicts` back) and survive only because of the deferral. `tests/core/test_cross_stage_imports.py` fails on any module-level crossing import, on a crossing pair missing from the allowlist, and on an allowlist entry whose dependency has since been removed, so the list cannot go stale in either direction.

#### What the numbers are made of

The analytical vocabulary is small and fixed: 22 signals · 10 regimes · a 4-factor composite.

The factor composite (`nuri/quant/factors/composite.py`) blends four terms — momentum 0.30, value 0.25, quality 0.25, sentiment 0.20. The first three are per-ticker scorers; sentiment is a single market-wide Fear & Greed value applied to every ticker alike, so it moves the score's level rather than its ranking. It is computed and persisted daily by the `factors` job at 08:10; readers query the `factors` table rather than recomputing.

That composite is one input among several to the BUY-candidate scorer (`config/buy_signals.yaml`), which also weighs 5-day momentum, RSI, and 30-day breakout. Two further channels — cross-sectional relative strength and dollar-volume surge — are wired into that same formula at **weight 0**: computed and surfaced as evidence, contributing nothing to the score, and staying that way until a walk-forward test justifies promoting them.

`config/signals.yaml` holds 22 entries of two deliberately unmerged kinds. 20 are **per-ticker and actionable** — the backtest detector registry. The other 2 — yield-curve inversion and HY-OAS widening — are **market-wide shadow** signals: their metadata carries `actionable: false`, their detectors live in `nuri/quant/validation/market_signals.py`, and they surface as warnings only.

Detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Certification spec: [`docs/CERTIFICATION_SPEC.md`](docs/CERTIFICATION_SPEC.md).

### Two decision axes, never conflated

A rule that fires because a position is too large is not the same as a rule that fires because a thesis broke. Mixing them is what produces a panicked sale of a good position, so the distinction is structural (`nuri/core/axis.py`):

| Axis | Values | Fires on |
|---|---|---|
| **alpha** | `LONG` / `SHORT` / `FLAT` | Thesis change. Stop-loss breach is the **only** mechanical path to `FLAT`. |
| **portfolio** | `REBALANCE` / `TRIM` / `HEDGE` | Sizing. Concentration, sector cap, and experiment-sleeve breaches resolve here — never as an urgent SELL. |

```mermaid
flowchart LR
    TR1["Stop-loss level breached"]
    TR2["Position · sector · sleeve<br/>over its cap"]
    AL["alpha_action<br/>LONG · SHORT · FLAT<br/>Should this position exist?"]
    PO["portfolio_action<br/>REBALANCE · TRIM · HEDGE<br/>Is the book the right shape?"]
    C1["Risk veto may fire —<br/>operator sees a SELL to consider"]
    C2["Rebalance advice —<br/>never an urgent SELL"]

    TR1 --> AL
    TR2 --> PO
    AL -->|FLAT| C1
    PO --> C2

    classDef step  stroke:#3b82f6,stroke-width:2px
    classDef stop  stroke:#dc2626,stroke-width:2px
    classDef calm  stroke:#f59e0b,stroke-width:2px
    class TR1,TR2,AL,PO step
    class C1 stop
    class C2 calm
```

The veto reads `alpha_action` only, so a portfolio-shape violation can never become a sell instruction. That separation is not stylistic — collapsing the two axes is what turns "this position is too big" into "sell this position now".

## Install

```bash
# Prerequisites: Python 3.12, uv, ta-lib, Node 22
brew install uv ta-lib fnm && fnm install 22

git clone https://github.com/researcherhojin/nuri-quant.git && cd nuri-quant
make setup                                              # backend deps + DB init + git hooks
cd frontend && npm ci && cd ..                          # frontend
cp .env.example .env                                    # API keys (all optional)
cp config/portfolio.example.yaml config/portfolio.yaml  # your holdings (gitignored)

make start          # API on :8001 + Dashboard on :3000
```

Visit **`:3000`** for the Action-First dashboard or **`:8001/docs`** for OpenAPI.

Every API key is optional. Collectors whose credentials are absent skip themselves and log the skip; the pipeline completes without them.

## Usage

### Daily commands

```bash
make full-scan      # every stage in order, 9 labelled steps (A-H)
make consensus      # 10-agent analysis + decision recording
make certify        # Certification gates (Account × Asset Class)
make scan           # Daily swing scan (us_core, 85 tickers)
make scan-extended  # Weekly swing scan (us_core + S&P 500 extension, 543 tickers)

make test-fast      # backend, slow tests excluded
make test           # full backend suite (adds 27 slow-marked tests)
make ci-cov         # combine CI shard artifacts — ground-truth coverage

make verify-quick   # pre-commit smoke gate
make verify-all     # pre-push gate: tests + lint + frontend
make help           # full target list with categories
```

### Dashboard

The dashboard at `:3000/` answers **"what should I do today?"** — Action-First design that surfaces actionable intelligence ahead of raw data. Pension / IRP holdings are filtered out, since a monthly rebalance is not a daily decision.

| Section | Purpose |
|---------|---------|
| **Hero** | 4-stat ribbon — 총 자산 · 오늘 P&L · 누적 수익률 · 승률, with a provenance strip labeling the numbers as a **portfolio snapshot** (총 자산 = all accounts + cash; 오늘 · 누적 · 승률 = pension-excluded holdings, unrealized) as distinct from the adjudication ledger |
| **System Health** | Certification score · Regime · Macro score · Data freshness |
| **Action Items** | 🔴 즉시 실행 (stop-loss, Certification veto) · 🟡 오늘 확인 (take-profit, squeeze) · 🟦 리밸런스 · ✅ 유지 — each card links its **evidence chain** (`/decisions/{id}`, dated `as_of`) when a same-date decision record exists |
| **Macro Events** | Deduplicated high-impact headlines with 한국어 categories |
| **Composition** | Donut chart — 자산 / 섹터 / 계좌 tabs |
| **Holdings table** | Sorted by `positionPct` desc · top 8 + expand |
| **Opportunity Explorer** | Top 3 non-portfolio tickers · pros / cons / verdict |

The dashboard's one-line verdict is gated on data freshness: if any input it depends on (prices, VIX, Fear & Greed, market rates, monthly macro, consensus — the `verdict_gate` list in [`config/freshness.yaml`](config/freshness.yaml)) has gone FAIL-stale, the verdict declines to advise and names the stale inputs instead of rendering a judgment on old data.

Korean tickers display as names (삼성전자) instead of codes (005930.KS). 18 routes total.

## Investment Rules

Rules live in [`config/rules.yaml`](config/rules.yaml) (loaded via `nuri/core/rules.py`) — code never hardcodes them. Sources: O'Neil (CAN SLIM), Minervini (SEPA), Shefrin & Statman (1985, 처분효과 / disposition effect).

| Strategy | Stop-loss | Profile |
|----------|-----------|---------|
| `core` | -7% | Default — strict O'Neil discipline |
| `active` | -10% | Cut losses early |
| `swing` | -15% | Short-term rotations (≤ 7 trading days) |
| `long_term` | -20% | Buy-and-hold ETFs |
| `pension` | -30% | Long-horizon retirement allocations |

Take-profit ladders sit on top: growth takes +20% / +40% then trails at -15%; value takes +15% / +30% then trails at -15%. Two hard gates apply regardless of strategy — VIX above 30 blocks new buys (25–30 halves the position), and Certification rejects any error-grade fail with no manual override. Full thresholds and rationale: [`docs/STRATEGY.md §3.4-§3.5, §6`](docs/STRATEGY.md).

Rule changes follow an escalation ladder rather than landing at full strength: **surface** evidence → **soft penalty** (deterministic downgrade) → **hard veto** (action block on downside risk) → **symmetric amplifier**. Promotion between rungs requires a STRATEGY PR with backtest evidence, and a rung has been walked back before — a 50-day-MA leader exit was disabled in #800 after a 197-ticker walk-forward failed to reproduce the 17-ticker result it was built on.

## LLM Integration

LLM integrations are **wired but inactive** unless you set the corresponding env var. The system runs without any LLM and falls back to regex / rule-based logic. Egress policy: [`docs/STRATEGY.md §4.4.3`](docs/STRATEGY.md).

| Provider | Purpose | Activation | Data tier |
|----------|---------|------------|-----------|
| **OpenAI gpt-5.4-nano** | RSS headline classification | `OPENAI_API_KEY` | Tier 0 (public). $3.51/yr at 100 headlines/day |
| **OpenAI gpt-5.4-nano** | Daily LLM report | `OPENAI_API_KEY` + `OPENAI_ZDR_APPROVED=1` | Tier 2 (portfolio). $0.10/yr at 1 report/day |
| **llama.cpp** (local) | Daily LLM report fallback | `LLAMA_MODEL_PATH` | Tier 2 — local only |
| **Ollama** (local) | Daily LLM report fallback | `OLLAMA_HOST` | Tier 2 — local only |

`nuri/llm/openai_client.py` is the only module permitted to import `openai`. Every external call is logged to the `external_llm_calls` table (timestamp / model / tokens — **never content**), portfolio-bearing prompts require the explicit ZDR flag, and `NURI_DISABLE_EXTERNAL_LLM=1` raises before any request leaves the process.

## Deployment

The reference setup is two machines by role: a development host, and an always-on receiver that runs the scheduler. `make deploy-mini` syncs them in one command. The receiver is the sole writer; the development host treats its database as a read replica, so adjudication records have exactly one ledger of record.

The receiver is also watched from outside its own hardware: it force-pushes a dead-man heartbeat ref (`refs/nuri/heartbeat-mini`, an empty-tree commit — no code, no branch) every 10 minutes, and a scheduled GitHub Actions workflow alerts the ops channel when that ref goes silent for 45 minutes. Silence is the alarm; a dead machine cannot be asked to report itself.

Production binds the API to `127.0.0.1`. The dashboard proxy is the only public surface and sits behind a password gate.

## Tech Stack

**Backend**

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?logo=sqlite&logoColor=white)
![uv](https://img.shields.io/badge/uv-package_manager-DE5FE9)

**Frontend**

![Next.js](https://img.shields.io/badge/Next.js-16.3.1-000000?logo=nextdotjs&logoColor=white)
![React](https://img.shields.io/badge/React-19.2.8-61DAFB?logo=react&logoColor=black)
![Tailwind CSS](https://img.shields.io/badge/Tailwind-4.3.3-06B6D4?logo=tailwindcss&logoColor=white)
![shadcn/ui](https://img.shields.io/badge/shadcn%2Fui-000000?logo=shadcnui&logoColor=white)

**Quant**

![pandas](https://img.shields.io/badge/pandas-150458?logo=pandas&logoColor=white)
![TA-Lib](https://img.shields.io/badge/TA--Lib-indicators-2C3E50)
![walk-forward](https://img.shields.io/badge/walk--forward-null--safe_gate-orange)
![OpenBB](https://img.shields.io/badge/OpenBB-data-FFD23F)
![Riskfolio-Lib](https://img.shields.io/badge/Riskfolio--Lib-optimization-lightgrey)
![yfinance](https://img.shields.io/badge/yfinance-market_data-purple)

**CI/CD**

![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?logo=githubactions&logoColor=white)
![pytest](https://img.shields.io/badge/pytest-xdist-0A9EDC?logo=pytest&logoColor=white)
![Vitest](https://img.shields.io/badge/Vitest-6E9F18?logo=vitest&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-2EAD33?logo=playwright&logoColor=white)
![Ruff](https://img.shields.io/badge/Ruff-D7FF64?logo=ruff&logoColor=black)
![Codecov](https://img.shields.io/badge/Codecov-F01F7A?logo=codecov&logoColor=white)
![Trivy](https://img.shields.io/badge/Trivy-1904DA?logo=trivy&logoColor=white)

## Project Stats

Measured against `main` on 2026-08-29. Rows marked ✅ are re-checked on every PR by `make verify-doc-counts`, which fails CI when the number here drifts from the code. Unmarked rows are **not** gated — read them as a dated snapshot, not a guarantee.

| Metric | Value | |
|--------|-------|---|
| **Backend tests** | 7,963 collected across 369 files | ✅ |
| **Backend statement coverage** | 99% — 41 of 24,533 statements uncovered, 96 partial branches (`make test-fast`, 2026-08-29; excludes the 27 slow-marked tests, so it understates. Codecov `backend` flag is the CI ground truth) | |
| **Frontend tests** | 1,648 across 141 vitest files — 99.87% statement coverage (2,393 of 2,396) | ✅ |
| **E2E tests** | 89 across 10 Playwright specs | |
| **Pipeline stages** | 5 as a data model; 1 of them (certify) has no scheduler job of its own | |
| **Data collectors** | 27 collectors (BaseCollector pattern) — 22 are driven by collect-stage cron jobs, the rest run on demand | ✅ |
| **Specialist agents** | 10 (consensus vote, weights sum to 1.0) | |
| **Actor fleet** | 16 registered — 9 with a live caller, 7 dormant (implemented and tested, nothing calls them) + 3 infrastructure helpers | |
| **Scheduler jobs** | 59 cron entries (APScheduler, in-process) — 29 collect · 1 analyze · 1 consensus · 5 track · 23 operate | ✅ |
| **Strategy regimes** | 10 regimes (6 base + 4 special) | ✅ |
| **Trading signals** | 22 — 20 per-ticker (actionable) + 2 market-wide (shadow) | |
| **API endpoints** | 73 declared in `nuri/api/routes/` (76 counting the three declared on the app itself in `main.py`) | ✅ |
| **Frontend routes** | 18 (Next.js on `:3000`) | |
| **DB tables** | SQLite WAL · 61 tables (60 forward-only migrations) | ✅ |
| **DB submodules** | 15 under `nuri/core/db/` — `connection.py` is the sole `sqlite3` importer, enforced by an AST sweep in CI | |

## Documentation

- [`docs/STRATEGY.md`](docs/STRATEGY.md) — project philosophy, architectural decisions, investment rules. Canonical when documents disagree.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — detailed code / DB layout, schema, env vars, CI/CD
- [`docs/CERTIFICATION_SPEC.md`](docs/CERTIFICATION_SPEC.md) — certification spec. It specifies three dimensions; the third (execution market hours) is **spec only** — `execution_markets` appears nowhere in `config/rules.yaml` or in `nuri/`, so what runs today is Account × Asset Class
- [`docs/KIS_INTEGRATION.md`](docs/KIS_INTEGRATION.md) — KIS (Korea Investment & Securities) Open API
- [`docs/UX_REDESIGN_PLAN.md`](docs/UX_REDESIGN_PLAN.md) — Evidence Terminal UI overhaul: phases, responsive spec, gates
- [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md) — session-efficiency scripts, pre-push checklist
- [`docs/FRESH_CLONE_SETUP.md`](docs/FRESH_CLONE_SETUP.md) — fresh-clone end-to-end verification (quarterly / onboarding)
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — development workflow, PR discipline
- [`SECURITY.md`](SECURITY.md) — security policy, LLM egress rules
- [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md) — agent guides (Claude Code / Cursor / Copilot)

## Maintainers

[@researcherhojin](https://github.com/researcherhojin) — sole maintainer. This is a personal investment platform; the contribution rules exist mainly because coding agents work in this repo and need mechanical guardrails.

## Acknowledgements

| Source | Usage |
|--------|-------|
| [SIEGE Engine](https://github.com/nutshells3/Swarm-Intelligence-Engine-with-Gated-Execution) | Policy-driven gate certification (v2: asset-class expansion), safety lattice |
| [OAE](https://github.com/nutshells3/orchestration-assurance-engine) | Claim trace, evidence lineage, audit pipeline |
| [safeslice](https://github.com/nutshells3/safeslice) | Statistical reliability bounds, witness cliff detection |
| [fwp](https://github.com/nutshells3/fwp) | Protocol seam pattern, governed job lifecycle |
| [Palantir Foundry](https://www.palantir.com/docs/foundry/data-lineage/overview) | Decision Intelligence pattern |
| [Dagster](https://docs.dagster.io/guides/observe/asset-freshness-policies) | Freshness SLA (PASS/WARN/FAIL) |
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | Multi-agent consensus pattern |
| [López de Prado](https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086) · [Riskfolio-Lib](https://riskfolio-lib.readthedocs.io/) · [OpenBB](https://docs.openbb.co/) | Walk-forward null-safe gate · optimization · data |

Academic foundations: O'Neil _CAN SLIM_, Minervini _SEPA_, Shefrin & Statman 1985 (disposition effect), Markowitz, Damodaran, Bernstein.

## Contributing

Open an issue before writing code so scope can be agreed first — read [`docs/STRATEGY.md`](docs/STRATEGY.md) before proposing any non-trivial change, since it is canonical when documents disagree. PRs are accepted.

Ten checks are required to merge: `Backend Tests`, `Backend Lint`, `Frontend Tests`, `Frontend Lint`, `Frontend Build`, `Security Scan`, `Shell Lint`, `Universe Coverage Validation`, `Doc Count Drift Check`, and `Privacy Leak Scan`. A commit-count gate (≤ 3), Codecov, CodeQL and Trivy also run, advisory unless separately enforced. One issue per PR and English Conventional Commit subjects are conventions the review enforces, not jobs — see [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full workflow.

Changing an investment rule, or promoting an escalation-ladder rung, additionally requires a `docs/STRATEGY.md` amendment with backtest evidence. A code change alone is not sufficient, and rungs have been walked back on evidence before.

## License

[AGPL-3.0](LICENSE)

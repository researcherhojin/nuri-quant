# AGENTS.md

<!-- DRIFT SYNC: this file (Codex CLI / Cursor / Copilot) ↔ `.claude/rules/invariants.md` (Claude Code, always-on).
     The rules are the same; change both in the same PR. Claude Code does not read this file. -->

Operating rules for AI coding agents other than Claude Code — primarily **Codex CLI**, also Cursor and Copilot.

Codex loads this file (and any nested `AGENTS.md`, e.g. `frontend/AGENTS.md`). It does **not** load `CLAUDE.md` or `.claude/rules/`, so everything an agent must follow is stated here. Canonical detail: `docs/STRATEGY.md` (policy and decisions), `docs/ARCHITECTURE.md` (code, DB, CI/CD).

## Project

Nuri-Quant — quant decision-support platform. Python 3.12, `uv`, SQLite (WAL), Next.js 16. Pipeline (5 stages): `collect → analyze → consensus → decide → track`.

The arrow is reading order, not execution order. Nothing chains the stages: `nuri/scheduler.py` registers independent cron jobs, and `run_step(..., warn_only=True)` records an unmet dependency as a warning and runs anyway (#894). `analyze` has a single job (`factors`); `decide` (named `certify` until #1619) has none — the consensus job hands its result to `record_decisions()` in memory; the portfolio-wide certifier was retired (STRATEGY §6). Outcome tracking (07:02) runs before consensus (07:05), which therefore reads the previous day's results.

## Before editing a directory

Scoped rules and gotchas live in `CLAUDE.md` files next to the code. Codex does not load them automatically — **read the one for the directory you are changing first.**

| Editing | Read first |
|---------|-----------|
| `nuri/core/` | `nuri/core/CLAUDE.md` |
| `nuri/collectors/` | `nuri/collectors/CLAUDE.md` |
| `nuri/trading/{agents,engine,recommend,swing,strategy,execution}/` | the `CLAUDE.md` in that directory |
| `nuri/agents/`, `nuri/api/` | the `CLAUDE.md` in that directory |
| `config/*.yaml` | `config/CLAUDE.md` |
| `tests/` | `tests/CLAUDE.md` |
| `frontend/` | `frontend/CLAUDE.md` and `frontend/AGENTS.md` (Next.js 16 APIs differ from training data) |
| `README.md`, `docs/*.md` | `scripts/verify/verify_doc_counts.sh` (gated phrases) and `tests/verify/test_readme_structure.py` |
| `.github/**`, `uv.lock`, `frontend/package-lock.json` | `.claude/rules/ci-deps.md` |

## Hard rules

Claude Code's edit-time hooks do not run in Codex. A rule marked **review** is enforced only by a human or reviewer reading the diff — check it yourself before committing.

| # | Rule | Enforced by |
|---|------|-------------|
| 1 | **DB access**: `nuri/core/db/connection.py` is the only `sqlite3` importer. Other modules use `query()` / `query_df()` / `upsert_*()` / `get_db()`; catch DB errors via `OperationalError` / `DatabaseError` from `nuri.core.db`. | CI — `tests/core/test_sqlite3_sole_importer.py` |
| 2 | **Forward `db_path`**: a function that accepts `db_path=` must pass it to every DB reader it calls. An unused parameter leaks that call to the default DB while signatures, type checks and tests stay green (21 such sites in #1050–#1052). | CI — `tests/core/test_db_path_forwarding.py` |
| 3 | **Time**: use `kst_now()` / `today_kst()` from `nuri.core.timezone`; never `datetime.now()`. | review (no lint rule or test) |
| 4 | **Config over code**: investment rules and thresholds live in `config/rules.yaml`, `config/agents.yaml`, `config/signals.yaml`. Hardcoding is rejected. | review |
| 5 | **Cross-stage imports** — stages map to `collect`=`nuri/collectors`, `analyze`=`nuri/analysis`, `consensus`=`nuri/trading/agents`, `decide`=`nuri/trading/engine`, `track`=`nuri/trading/recommend` (`nuri/quant`, `nuri/core` are shared libraries). A crossing import must be deferred inside a function body and listed with a reason in the allowlist (#920). | CI — `tests/core/test_cross_stage_imports.py` |
| 6 | **External LLM gateway**: `nuri/llm/openai_client.py` is the only external-LLM entry point; `import openai` elsewhere is forbidden (ZDR + audit log live there, STRATEGY §4.4.3). | review |
| 7 | **Privacy**: never commit personal financial data (broker names, holdings, prices, account ids, ticker + signed %) or personal identifiers (account names, real-name hostnames, `/Users/<account>/`). Use placeholders (`Brokerage Alpha`, `user@macmini.local`, `/Users/USER/`). Never edit `.env` or `config/portfolio.yaml`. | pre-push hook + CI `Privacy Leak Scan` |
| 8 | **Commits**: Conventional Commits with an **English** subject — `(feat\|fix\|docs\|style\|refactor\|test\|chore\|perf\|ci\|build\|revert)(scope)?: msg`. Korean comments in code, English identifiers. | pre-push warning |
| 9 | **PR scope**: 1 issue = 1 PR, ≤ 3 commits. New findings → separate issue. | CI `pr-discipline` (advisory) |
| 10 | **7-phase Flow**: Think → Plan → Build → Review → Test → Ship → Reflect; a failed gate regresses to the prior phase. | review |
| 11 | **Auto trading deferred (permanent)**: the system emits recommendations and alerts only; the user places every order. Reverting requires a STRATEGY PR and re-approval (§7.1). | review |
| 12 | **Measurement mode** (STRATEGY §3.11): the adjudication ledger (`decision_outcomes` etc.) is the production (Mac mini) DB only — the dev DB is a read replica. Criteria were pre-registered 2026-07-08 and are locked. Sleeve cap: `config/rules.yaml measurement_mode.sleeve_max_equity_pct`; raising it requires the pre-registered verdict + STRATEGY PR. | review |
| 13 | **Escalation Ladder** (STRATEGY §2.6): Surface → Soft penalty → Hard veto → Symmetric amplifier. Promotion between rungs requires a STRATEGY PR with evidence or backtest. | review |
| 14 | **Gotcha-Test Pair** (STRATEGY §5.3.1): a saved fix-pattern gotcha must cite a regression test (`**Test:** path::Class::test`) that fails if the fix is reverted; plain facts are marked `*(facts, no fix)*`. | review |

Self-check before committing (covers what the Claude hooks would have caught):

```bash
git diff --cached -U0 | grep -nE '^\+.*(datetime\.now\(|import (sqlite3|openai))'   # rules 1, 3, 6 — expect no output
.venv/bin/python scripts/verify/check_privacy_leak.py <changed files>          # rule 7
```

## Action axes (orthogonal — never conflate)

- `alpha_action ∈ {LONG, SHORT, FLAT}` — expected-return signal. A stop-loss breach is the only mechanical path to `FLAT`.
- `portfolio_action ∈ {REBALANCE, TRIM, HEDGE, NONE}` — portfolio-rule signal (concentration, sector, leverage). Never routes to an urgent SELL.

The risk veto fires on `alpha_action == "FLAT"` only. `/api/actions` buckets: `urgent` / `check` / `hold` / `portfolio`. Helpers: `nuri/core/axis.py`.

## Recommendation boundary (never improvise a trade)

- **No ad-hoc buy/sell calls.** Never invent order sizes, entry prices or allocations — not even when asked "what's your stance?" or "should I sell X?". Surface only what the user's own system produced: certification gate violations, `config/rules.yaml` ladder hits, `buy_candidate_emitter` counts, external facts (VIX, earnings dates, macro), and if-then scenarios.
- **Price levels are a format, not a license.** The entry / stop / TP format applies to system-generated recommendations, not to guessed numbers.
- **Data ≠ recommendation.** A data or analysis task must not slide into a stock recommendation unless the user explicitly asks.
- **"Are you sure?" is the stop signal.** Withdraw the recommendation and leave only the facts.

An LLM has no live prices and no view of the user's cash flow, taxes or holding period; agreement between models is still a sum of guesses.

## Code placement

| Adding | Put it in |
|--------|-----------|
| Data source | `nuri/collectors/` — subclass `BaseCollector`, implement `collect()` + `save()` |
| SQL table / column | new entry in `_MIGRATIONS` (`nuri/core/db_migrations.py`); never edit existing migrations |
| Agent | `nuri/trading/agents/`, registered in `build_all_agents()` (`nuri/trading/agents/consensus/registry.py`), weight in `config/agents.yaml` |
| Investment rule / threshold | `config/rules.yaml` (agent-specific: `config/agents.yaml`) |
| Actionable signal | `config/signals.yaml` with `actionable: true` |
| Shadow (surface-only) signal | `config/signals.yaml` with `actionable: false`, `scope: market_wide`; detector in `nuri/quant/validation/market_signals.py` |
| API endpoint | `nuri/api/routes/` |
| Dashboard page | `frontend/src/app/<route>/page.tsx` |
| External LLM call | through `nuri/llm/openai_client.py` only |

## Commands

```bash
make setup                                   # venv + deps + DB + portfolio import + git hooks
make test-fast                               # backend tests, slow-marked excluded (81.2s)
.venv/bin/python -m pytest <path>::<test> -v # single test
make lint                                    # ruff
make verify-quick                            # pre-commit smoke (84.9s)
make verify-all                              # tests + lint + frontend (320.8s)
make verify-doc-counts                       # README/docs numbers vs code
make spellcheck-ci                           # cspell (required CI check)
make help                                    # every target
```

Push once, after the local gates: run `bash scripts/verify/pre_push_check.sh --skip-tests` plus the affected tests, fold all review findings into one push — every push cancels the running CI and re-queues from the back (19 jobs against a 20-job concurrency limit). Timings: M5 Max, 2026-08-14; no gate checks them. `make setup-hooks` installs the pre-commit (ruff/eslint autofix) and pre-push (`scripts/verify/pre_push_check.sh --skip-tests`) hooks. Use `uv sync --all-extras --all-groups`, not bare `uv sync`.

## When reviewing (Flow phase 4, `/codex review`)

Codex is the cross-model reviewer for Claude-authored changes. Give one binary verdict (e.g. SHIP / NEEDS_REWORK) with findings ranked P1 / P2, each citing `file:line`. Check the hard rules above (especially the **review**-only ones), the action axes, the recommendation boundary, scope creep, and tests that pass without exercising the changed code. Disagree when warranted; do not implement fixes.

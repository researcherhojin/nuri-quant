# AGENTS.md

<!-- DRIFT SYNC: 본 파일 (cross-tool fallback) ↔ `.claude/rules/invariants.md` (Claude Code always-on)
     변경 시 두 곳 동시 갱신. Claude Code 는 `.claude/rules/`, codex CLI / Cursor 등은 본 파일 read. -->

Cross-tool agent instructions for Nuri-Quant. Applies to AI coding agents that don't load Claude Code's `CLAUDE.md` hierarchy directly (Cursor, Copilot, Codex CLI, Gemini CLI, etc.).

**Claude Code reads `CLAUDE.md` (root + scoped) — start there.** This file is a minimal cross-tool fallback so non-Claude agents have the same operating rules without parsing `@import` / scoped-doc structure.

For canonical detail:
- Repo conventions, commands, load triggers → `CLAUDE.md`
- Investment policy, design decisions → `docs/STRATEGY.md`
- Architecture, DB schema, CI/CD → `docs/ARCHITECTURE.md`

## Project

Nuri-Quant — open-source quant investment platform. Python 3.12, `uv`, SQLite (WAL), Next.js 16. Pipeline (5 stages): `collect → analyze → consensus → certify → track`.

## Hard Rules (mechanically enforced — do not violate)

1. **DB**: `nuri/core/db/` is the only `sqlite3` importer (importer module: `nuri/core/db/connection.py`). Other modules use `query()` / `query_df()` / `upsert_*()` / `get_db()`.
2. **Time**: always `kst_now()` / `today_kst()` from `nuri.core.timezone`. Never `datetime.now()`.
3. **Config over code**: rules in `config/rules.yaml`, agents in `config/agents.yaml`, signals in `config/signals.yaml`. Hardcoding is rejected.
4. **Cross-stage imports: deferred only, and frozen**: stages map to `collect`=`nuri/collectors` · `analyze`=`nuri/analysis` · `consensus`=`nuri/trading/agents` · `certify`=`nuri/trading/engine` · `track`=`nuri/trading/recommend` (`nuri/quant` and `nuri/core` are shared libraries, not stages). A crossing import MUST be deferred inside a function body — never at module level — and must be listed with a reason in the allowlist. Measured: 17 crossing statements over 15 pairs, 0 module-level. Same-stage imports OK. The old "DB tables / CSV only" wording was false and is retired (#920). Source: `tests/core/test_cross_stage_imports.py` (fails on new entries and stale ones alike).
5. **Privacy**: never commit personal financial data (real broker names, holdings, prices, account ids, ticker+PnL). Use placeholders. Pre-push hook + CI privacy-scan blocks. Source: `scripts/verify/check_privacy_leak.py`.
6. **Conventional commits (English)**: `(feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)(scope)?: msg`. Korean comments in code, English identifiers.
7. **PR scope**: 1 issue = 1 PR, ≤ 3 commits. New findings → separate issue.
8. **7-phase Flow**: Think → Plan → Build → Review → Test → Ship → Reflect. No phase skipping. Failed gate → regress prior phase. Trivial chores may inline Think+Plan.
9. **External LLM gateway**: `nuri/llm/openai_client.py` is the ONLY external LLM entry point. Direct `import openai` forbidden. ZDR + audit-log enforced. Policy: `docs/STRATEGY.md §4.4.3`.
10. **Auto trading deferred (permanent)**: system emits recommendations + alerts only. User executes orders manually. Reverting requires STRATEGY PR + re-approval.
11. **Measurement mode** (STRATEGY §3.11): the ledger of record for adjudication metrics (`decision_outcomes` etc.) is the production (Mac mini) DB only — dev DB is a read-replica; verdicts/reports cite ledger queries only. Adjudication criteria are pre-registered (2026-07-08, locked — no post-hoc amendment before the evaluation date). Sleeve cap canonical location: `config/rules.yaml measurement_mode.sleeve_max_equity_pct`; raising it requires the pre-registered verdict + STRATEGY PR (lowering/freezing always allowed).
12. **Escalation Ladder** (STRATEGY §2.6): **Surface** exposes evidence only (no action change) → **Soft penalty** deterministic downgrade/cap (config-tunable) → **Hard veto** action-block on downside (risk-of-ruin) → **Symmetric amplifier** post-veto upside sizing (multi-condition, never single-trigger). Promotion between rungs requires STRATEGY PR + evidence/backtest.
13. **Gotcha-Test Pair** (STRATEGY §5.3.1): every fix-pattern gotcha (saved defensive code) MUST cite a regression test (`**Test:** path::TestClass::test_name`) that fails if the fix is reverted. Plain facts/quirks need no test — mark as `*(facts, no fix)*`.

## Code Placement

| Adding... | Put it in |
|-----------|-----------|
| New data source | `nuri/collectors/` — subclass `BaseCollector`, implement `collect()` + `save()` |
| SQL table / column | `_MIGRATIONS` list in `nuri/core/db_migrations.py` — never edit existing migrations |
| New agent | `nuri/trading/agents/` + register via `build_all_agents()` in `nuri/trading/agents/consensus/registry.py` + weight in `config/agents.yaml` |
| Investment rule / threshold | `config/rules.yaml` (or `config/agents.yaml` for agent-specific) — never hardcode |
| Actionable signal | `config/signals.yaml` with `actionable: true` — consumed by `signal_backtest.py` |
| SHADOW signal (surface-only) | `config/signals.yaml` with `actionable: false` + `scope: market_wide` — detector in `nuri/quant/validation/market_signals.py`, excluded from candidates by `is_actionable` guard |
| API endpoint | `nuri/api/routes/` |
| Dashboard page | `frontend/src/app/<route>/page.tsx` |
| External LLM call | `nuri/llm/openai_client.py` only (wrapper) |

## Action Axes (orthogonal, never conflate)

- `alpha_action ∈ {LONG, SHORT, FLAT}` — agents' expected-return signal. Only stop-loss breach emits FLAT.
- `portfolio_action ∈ {REBALANCE, TRIM, HEDGE, NONE}` — SIEGE portfolio-rule signal (concentration / sector / leverage). Never routes to urgent SELL.

Risk-agent veto fires on `alpha_action=="FLAT"` only. `/api/actions` 4 buckets: `urgent` / `check` / `hold` / `portfolio`. Helpers in `nuri/core/axis.py`.

## Key Commands

```bash
make setup                   # venv + deps + DB init
make test                    # full pytest (xdist parallel)
make test-fast               # exclude slow LLM tests (~24s, PR CI)
make verify-quick            # ~10s pre-commit smoke
make verify-all              # ~30s pre-push (tests + lint + frontend)
make start                   # API(:8001) + Dashboard(:3000)
```

Full make-target catalog: `CLAUDE.md`.

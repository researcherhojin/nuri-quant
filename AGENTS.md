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

Nuri-Quant — open-source quant investment platform. Python 3.12, `uv`, SQLite (WAL), Next.js 16. Pipeline (5 phases, DB-coupling only): `collect → analyze → consensus → certify → track`.

## Hard Rules (mechanically enforced — do not violate)

1. **DB**: `nuri/core/db.py` is the only `sqlite3` importer. Other modules use `query()` / `query_df()` / `upsert_*()` / `get_db()`.
2. **Time**: always `kst_now()` / `today_kst()` from `nuri.core.timezone`. Never `datetime.now()`.
3. **Config over code**: rules in `config/rules.yaml`, agents in `config/agents.yaml`, signals in `config/signals.yaml`. Hardcoding is rejected.
4. **Cross-phase isolation**: pipeline phases communicate via DB tables / CSV only, not direct imports. Same-phase imports OK.
5. **Privacy**: never commit personal financial data (real broker names, holdings, prices, account ids, ticker+PnL). Use placeholders. Pre-push hook + CI privacy-scan blocks. Source: `scripts/check_privacy_leak.py`.
6. **Conventional commits (English)**: `(feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)(scope)?: msg`. Korean comments in code, English identifiers.
7. **PR scope**: 1 issue = 1 PR, ≤ 3 commits. New findings → separate issue.
8. **7-phase Flow**: Think → Plan → Build → Review → Test → Ship → Reflect. No phase skipping. Failed gate → regress prior phase. Trivial chores may inline Think+Plan.
9. **External LLM gateway**: `nuri/llm/openai_client.py` is the ONLY external LLM entry point. Direct `import openai` forbidden. ZDR + audit-log enforced. Policy: `docs/STRATEGY.md §4.4.3`.
10. **Auto trading deferred (permanent)**: system emits recommendations + alerts only. User executes orders manually. Reverting requires STRATEGY PR + re-approval.

## Code Placement

| Adding... | Put it in |
|-----------|-----------|
| New data source | `nuri/collectors/` — subclass `BaseCollector`, implement `collect()` + `save()` |
| SQL table / column | `_MIGRATIONS` list in `nuri/core/db.py` — never edit existing migrations |
| New agent | `nuri/trading/agents/` + register in `consensus.py` `ALL_AGENTS` + weight in `config/agents.yaml` |
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

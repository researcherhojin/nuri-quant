# AGENTS.md

Universal agent instructions for Nuri-Quant. Applies to all AI coding agents (Claude Code, Cursor, Copilot, Codex, Gemini CLI).

For Claude Code-specific features (hooks, @imports, skills), see `CLAUDE.md`.

## Project

Nuri-Quant — open-source quant investment platform. Python 3.12, uv, SQLite, Next.js 16.
8-phase pipeline: collect → analyze → validate → regime → recommend → certify → evidence → notify.

## Hard Rules

These are enforced by hooks, CI, and pre-push scripts. Violations are blocked mechanically.

1. **DB access**: `nuri/core/db.py` is the ONLY module that imports `sqlite3`. All others use `query()`, `query_df()`, `upsert_*()`, `get_db()`.
2. **Timezone**: Always `kst_now()` or `today_kst()` from `nuri.core.timezone` — never `datetime.now()`.
3. **Config over code**: Rules in `config/rules.yaml`, thresholds in `config/agents.yaml`, signals in `config/signals.yaml`. Never hardcode.
4. **Cross-phase isolation**: Pipeline phases communicate via DB tables and CSV files, not direct imports. Same-phase imports are OK.
5. **Privacy**: No real broker names, holdings, quantities, prices, or account identifiers in git (commits, PRs, issues, tests, comments). Use placeholders: `Brokerage Alpha`, `Brokerage Beta`, round-million values.
6. **Conventional commits**: `type(scope): message` — types: feat, fix, docs, style, refactor, test, chore, perf, ci, build, revert. English.
7. **Scope discipline**: One issue = one PR, max 3 commits. Unrelated findings go to separate issues.
8. **Flow (7-phase)**: Every task runs Think → Plan → Build → Review → Test → Ship → Reflect (`docs/STRATEGY.md §2.7`). Failed gate → regress to prior phase. No skipping. Trivial chores may inline Think+Plan; Build+ mandatory.

## Code Placement

| Adding... | Put it in |
|-----------|-----------|
| Data source | `nuri/collectors/` — subclass `BaseCollector`, implement `collect()` + `save()` |
| SQL table | `_MIGRATIONS` list in `nuri/core/db.py` — never edit existing migrations |
| Agent | `nuri/trading/agents/` + register in `consensus.py` `ALL_AGENTS` + weight in `config/agents.yaml` |
| Investment rule | `config/rules.yaml` — never hardcode |
| API endpoint | `nuri/api/routes/` |
| Dashboard page | `frontend/src/app/<route>/page.tsx` |
| LLM call | `nuri/llm/` only — external calls through `nuri/llm/openai_client.py` wrapper only |

## Testing

- Backend: `make test` (pytest, xdist parallel). `tmp_path` fixture for DB isolation.
- Frontend: `cd frontend && npm test` (vitest).
- All tests run **network-free**. `conftest.py` mocks yfinance globally.
- Coverage: Codecov 1% relative regression gate (no fixed minimum).

## Key Commands

```bash
make setup                   # Python venv + deps + DB init
make test                    # Full backend test suite
make test-fast               # Exclude slow LLM tests
make lint                    # ruff check
make verify-quick            # ~10s pre-commit smoke test
make verify-all              # ~30s pre-push (tests + backend + frontend + file integrity)
make start                   # API(:8001) + Dashboard(:3000)
make deploy-mini             # MBP → Mac mini 전체 동기화 (git pull + config + scheduler reload, ~30s)
make scheduler-reload-remote # Mac mini scheduler 단독 reload (scheduler.py 변경 후)
```

2-machine setup details: `CLAUDE.md` §Deploy. Both targets require `DEV2_HOST` env var.

## Architecture Reference

Detailed architecture, DB schema, environment variables, and CI/CD documentation: `docs/ARCHITECTURE.md`.
Design principles and investment rules: `docs/STRATEGY.md`.

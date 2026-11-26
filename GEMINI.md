# GEMINI.md

Antigravity (`agy`) workspace guide for **Nuri-Quant (누리퀀트)**.

Core project invariants, action axes, recommendation boundaries, and code placement are defined in [`AGENTS.md`](AGENTS.md) (always loaded alongside this file). Do not duplicate them here.

## Antigravity Environment

- **Session start**: read `NEXT_SESSION.md` first if present (gitignored handoff), and check `git status -sb`.
- **Scoped rules before editing**: consult [`.claude/rules/load-triggers.md`](.claude/rules/load-triggers.md) and read the directory-local `CLAUDE.md` (and `frontend/AGENTS.md` for Next.js 16) before changing files in any module.
- **Lifecycle hooks (`.agents/hooks.json`)**: `PreToolUse` runs [`scripts/hooks/agy_pre_tool_guard.py`](scripts/hooks/agy_pre_tool_guard.py) to block destructive `git` commands, `.env` / `config/portfolio.yaml` edits, `import sqlite3` outside `nuri/core/db/connection.py`, `import openai` outside `nuri/llm/openai_client.py`, `datetime.now(` in `nuri/`, and privacy leaks.
- **MCP read model (`.agents/mcp_config.json`)**: configures `nuri-read` (`python -m nuri.mcp.server`, stdio, `readonly=True`).
- **`.env` protection**: never read or edit `.env` or `config/portfolio.yaml`. For template changes, update `.env.example` or write `.env.new` for manual swap by the user.
- **Frontend toolchain**: if `node` is not in default `PATH`, prepend `/opt/homebrew/opt/node@24/bin` before running `cd frontend && npm test && npm run lint`, `make typecheck`, or `make spellcheck`.
- **Verification before commit/push**:
  - `make lint` and `make typecheck` (0 errors)
  - Affected `pytest` suites (or `make test-fast`) and `cd frontend && npm test && npm run lint` when touching `frontend/`
  - `bash scripts/verify/pre_push_check.sh --skip-tests` (checks drift, ruff, shellcheck, doc counts, CSpell, pyright on changed lines, and privacy)
  - Never commit or push directly to `main` (branch protection requires PR + CI checks); use a feature branch and `gh pr create`.

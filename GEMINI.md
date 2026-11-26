# GEMINI.md

Antigravity (`agy`) workspace guide for **Nuri-Quant (누리퀀트)**.

Follow [`AGENTS.md`](AGENTS.md) for project invariants, action axes, recommendation boundaries, and code placement.

## CLI setup

From the repository root, sync the locked dependencies, then start Antigravity. Follow the workspace trust prompt if it appears. [uv sync reference](https://docs.astral.sh/uv/reference/cli/#uv-sync) · [Antigravity workspace discovery](https://antigravity.google/docs/customization-discovery/)

```sh
uv sync --locked --all-extras --all-groups
agy
```

- In the CLI, use `/hooks` to check that `nuri-invariants` is active. [Antigravity hooks](https://antigravity.google/docs/hooks)
- In the CLI, use `/mcp` to check that `nuri-read` is connected. The workspace config starts it over stdio with `uv run --no-sync python -m nuri.mcp.server`. It exposes `buy_candidates`, `data_freshness`, `live_quote`, and `macro_facts` as read-only tools. [Antigravity MCP](https://antigravity.google/docs/mcp?tab=cli)

## Antigravity Environment

- **Session start**: read `NEXT_SESSION.md` first if present (gitignored handoff), and check `git status -sb`.
- **Scoped rules before editing**: consult [`.claude/rules/load-triggers.md`](.claude/rules/load-triggers.md) and read the directory-local `CLAUDE.md` (and `frontend/AGENTS.md` for Next.js 16) before changing files in any module.
- **Lifecycle hooks (`.agents/hooks.json`)** run [`scripts/hooks/agy_pre_tool_guard.py`](scripts/hooks/agy_pre_tool_guard.py) with `python3`. The hook checks selected destructive Git commands from `run_command` and applies the protected-file, import, time, and privacy rules to `write_to_file`, `replace_file_content`, and `multi_replace_file_content`.
- **`.env` protection**: never read or edit `.env` or `config/portfolio.yaml`. For template changes, update `.env.example`.
- **Frontend toolchain**: if `node` is not in default `PATH`, prepend `/opt/homebrew/opt/node@24/bin` before running `cd frontend && npm test && npm run lint`, `make typecheck`, or `make spellcheck`.
- **Verification before commit/push**:
  - `make lint` and `make typecheck` (0 errors)
  - Affected `pytest` suites (or `make test-fast`) and `cd frontend && npm test && npm run lint` when touching `frontend/`
  - `bash scripts/verify/pre_push_check.sh --skip-tests` (checks drift, ruff, shellcheck, doc counts, CSpell, pyright on changed lines, and privacy)
  - Never commit or push directly to `main` (branch protection requires PR + CI checks); use a feature branch and `gh pr create`.

Run the hook tests and the MCP stdio test locally with this command.

```sh
.venv/bin/python -m pytest tests/scripts/test_agy_pre_tool_guard.py tests/mcp_server/test_server_stdio_live.py -q
```

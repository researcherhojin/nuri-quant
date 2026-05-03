# Cross-scope Gotchas

Most gotchas live in scoped CLAUDE.md or in code lock-tests (Gotcha-Test Pair, see `.claude/rules/invariants.md`). Cross-scope ones:

- **fastapi < 0.129 pinned** (`openbb-core 1.6.7` constraint, dependabot.yml ignores 0.129+)
- **Korean stock tickers**: `.KS` suffix (e.g., `005930.KS`). yfinance returns most fundamentals but **`trailingPE` is missing for KR individuals** — use `forward_pe`. ETFs return empty `info`. Full quirks: `nuri/collectors/CLAUDE.md` "Korean Ticker `.KS` Suffix Convention".
- **Concurrency asymmetry**: yfinance 10-thread OK; pykrx/KRX **must be sequential** + `time.sleep(0.1)`. New external APIs require concurrency measurement before integration.

For framework / test-mocking / data-source / pipeline-policy gotchas → scoped CLAUDE.md or `/nuri-harness-debug` skill.

## Reference

- `docs/STRATEGY.md` — canonical policy (load on demand): 8 sections + §5.10 frontier alignment
- `docs/ARCHITECTURE.md` — code/DB layout (env vars, CI/CD, schema)
- `docs/SIEGE_V2.md` — 3D certification spec
- `docs/KIS_INTEGRATION.md` — KIS Open API integration
- `AGENTS.md` — cross-tool rules (Cursor / Copilot / Codex CLI), not auto-loaded by Claude Code

Local-only (gitignored — internal infra / audit / map):
- `docs/OPERATIONS.md` — operator runbook (2-machine deploy / scheduler / recovery)
- `docs/SOURCE_OF_TRUTH.md` — file-ownership map
- `docs/HARNESS_AUDIT.md` — audit snapshot (overwrite each audit, history in git log)
- `docs/TRADING_AUDIT.md` — `nuri/trading/` internal audit (#552)
- `docs/TODO.md` — forward-only backlog
- `NEXT_SESSION.md` — handoff
- `~/.claude/projects/-Users-ehbebe-workspace-nuri-quant/memory/` — user-scoped auto-memory

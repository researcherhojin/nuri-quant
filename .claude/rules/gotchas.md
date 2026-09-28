# Cross-scope Gotchas

Most gotchas live in scoped CLAUDE.md or in code lock-tests (Gotcha-Test Pair, see `.claude/rules/invariants.md`). Cross-scope ones:

- **의존성·CI 게이트 gotcha 는 `.claude/rules/ci-deps.md`** (path-scoped: `.github/**` · lock 파일 · `pyproject.toml` · `check_lock_major_bump.py` 편집 시 자동 로드) — override 하한이 부모 핀을 지우는 문제, dependabot semver 가 lock major 를 못 보는 문제, venv 캐시 인터프리터 동반 문제. 여기 없다고 없는 게 아니다.
- **Korean stock tickers**: `.KS` suffix (e.g., `005930.KS`). yfinance returns most fundamentals but **`trailingPE` is missing for KR individuals** — use `forward_pe`. ETFs return empty `info`. Full quirks: `nuri/collectors/CLAUDE.md` "Korean Ticker `.KS` Suffix Convention".
- **Concurrency asymmetry**: yfinance 10-thread OK; pykrx/KRX **must be sequential** + `time.sleep(0.1)`. New external APIs require concurrency measurement before integration.

For framework / test-mocking / data-source / pipeline-policy gotchas → scoped CLAUDE.md or `/nuri-harness-debug` skill.

## Reference

- `docs/STRATEGY.md` — canonical policy (load on demand): 8 sections + §5.10 frontier alignment
- `docs/ARCHITECTURE.md` — code/DB layout (env vars, CI/CD, schema)
- `docs/CERTIFICATION_SPEC.md` — 3D certification spec (SIEGE v2)
- `docs/KIS_INTEGRATION.md` — KIS Open API integration
- `AGENTS.md` — cross-tool rules (Cursor / Copilot / Codex CLI), not auto-loaded by Claude Code

Local-only (gitignored — internal infra / audit / map):
- `docs/OPERATIONS.md` — operator runbook (2-machine deploy / scheduler / recovery)
- `docs/SOURCE_OF_TRUTH.md` — file-ownership map
- `docs/HARNESS_AUDIT.md` — audit snapshot (overwrite each audit, history in git log)
- `docs/TRADING_AUDIT.md` — `nuri/trading/` internal audit (#552)
- `docs/TODO.md` — forward-only backlog
- `NEXT_SESSION.md` — handoff
- `~/.claude/projects/<sanitized-cwd>/memory/` — user-scoped auto-memory

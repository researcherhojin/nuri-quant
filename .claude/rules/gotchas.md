# Cross-scope Gotchas

Most gotchas live in scoped CLAUDE.md or in code lock-tests (Gotcha-Test Pair, see `.claude/rules/invariants.md`). Cross-scope ones:

- **의존성·CI 게이트 gotcha 는 `.claude/rules/ci-deps.md`** (path-scoped: `.github/**` · lock 파일 · `pyproject.toml` · `check_lock_major_bump.py` 편집 시 자동 로드) — override 하한이 부모 핀을 지우는 문제, dependabot semver 가 lock major 를 못 보는 문제, venv 캐시 인터프리터 동반 문제. 여기 없다고 없는 게 아니다.
- **Korean stock tickers**: `.KS` suffix (e.g., `005930.KS`). yfinance returns most fundamentals but **`trailingPE` is missing for KR individuals** — use `forward_pe`. ETFs return empty `info`. Full quirks: `nuri/collectors/CLAUDE.md` "Korean Ticker `.KS` Suffix Convention".
- **Concurrency asymmetry**: yfinance 10-thread OK; pykrx/KRX **must be sequential** + `time.sleep(0.1)`. New external APIs require concurrency measurement before integration.

- **CI 의 `Doc Count Drift Check` 는 반쪽이다** *(facts, no fix)*: 그 job 에는 `.venv` 가 없어 `verify_doc_counts.sh` 의 Python 기반 수치(백엔드 테스트 수 · DB 테이블 수 · 레짐 수)가 빈 값으로 **건너뛰어진다.** 이 셋은 pre-push 훅(`pre_push_check.sh` 2c, 로컬 `.venv`)에서만 검사된다 — 훅을 우회한 push 는 CI 초록이어도 이 수치가 틀릴 수 있다.
- **`make verify-all` Backend 단계의 환경 의존 실패** *(facts, no fix)*: dev DB 의 SPY 가 freshness 임계를 넘으면 레짐 분류가 차단돼 `classify_regime()` 이 `None` 을 돌려주고 `assert r is not None` 이 터진다(`Regime: FAIL`). 코드 회귀가 아니다 — `make collect` 로 데이터를 갱신한 뒤 다시 돌릴 것.

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

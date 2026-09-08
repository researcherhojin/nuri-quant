# Cross-scope Gotchas

Most gotchas live in scoped CLAUDE.md or in code lock-tests (Gotcha-Test Pair, see `.claude/rules/invariants.md`). Cross-scope ones:

- **override 하한은 부모의 정확 핀을 지운다** — `[tool.uv] override-dependencies` 에 `fastapi>=0.133` 처럼 하한만 두면 하위 패키지의 `==` 핀이 통째로 사라진다. 그렇게 dependabot #1369(2026-09-01)가 fastapi 를 0.141 로 올렸고 `openbb-core` 의 `fastapi==0.136.3` 핀이 무력화돼 `from openbb import obb` 가 모든 머신에서 조용히 죽었다(4 호출 지점이 전부 yfinance 폴백으로 7일). openbb 는 #1477 로 제거했고 fastapi/starlette 는 보통 의존성이다. 남은 override 는 부모가 `any` 제약인 `aiohttp` 뿐 — 라이브러리 내부 결합이 있는 패키지에는 상한 없는 override 를 두지 말 것. *(facts, no fix)*
- **Korean stock tickers**: `.KS` suffix (e.g., `005930.KS`). yfinance returns most fundamentals but **`trailingPE` is missing for KR individuals** — use `forward_pe`. ETFs return empty `info`. Full quirks: `nuri/collectors/CLAUDE.md` "Korean Ticker `.KS` Suffix Convention".
- **dependabot 의 semver 는 manifest 변화만 본다** — `numpy>=1.26.0` 같은 하한 제약 아래서는 lock 의 major 이동이 `update-type` 에 **아예 안 나타나고** `dependency-names` 에 이름조차 없다. `pip`→`uv` 전환(#1352)이 연 축이다: pip 은 `uv.lock` 을 쓰는 코드 경로가 없어 불가능했다. #1355 가 그 사고 — 제목 "bump scipy 1.17.1→1.18.1 (minor)" 로 **numpy 1.26.4→2.5.2 가 무인 자동 머지**됐고, `numba`/`llvmlite` 는 pyproject 에 아예 없어 manifest 기반 검사로는 영영 안 보인다. 그래서 `dependabot-auto-merge.yml` 은 fetch-metadata 가 아니라 **실제 lock diff** 를 본다 (`scripts/verify/check_lock_major_bump.py`). 0.x minor 도 경계로 친다(lock 의 24% 가 0.x — fastapi/uvicorn/httpx/vectorbt/ta-lib). CalVer(`tzdata 2025.3`, `pywin32 312`)는 제외 — 안 그러면 매년 오탐. **Test:** `tests/scripts/test_check_lock_major_bump.py::TestMajorBoundary::test_the_1355_lock_diff_is_refused` (동작) + `::TestWorkflowWiring::test_the_gate_script_is_invoked` (배선 — 함수 테스트는 호출부를 안 잠근다)
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
- `~/.claude/projects/-Users-ehbebe-workspace-nuri-quant/memory/` — user-scoped auto-memory

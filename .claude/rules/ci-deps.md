---
paths:
  - ".github/**"
  - "scripts/verify/check_lock_major_bump.py"
  - "pyproject.toml"
  - "uv.lock"
  - "frontend/package-lock.json"
---

# CI + Dependency Gotchas (path-scoped)

`gotchas.md` / `enforcement.md` 에서 옮겨왔다 (2026-09-28 /doctor) — 의존성·CI 파일을 만질 때만 필요한 내용이라 항상 로드하지 않는다. Required check 목록과 훅이 무엇을 막는지는 여전히 `enforcement.md` 에 있다.

- **override 하한은 부모의 정확 핀을 지운다** — `[tool.uv] override-dependencies` 에 `fastapi>=0.133` 처럼 하한만 두면 하위 패키지의 `==` 핀이 통째로 사라진다. 그렇게 dependabot #1369(2026-09-01)가 fastapi 를 0.141 로 올렸고 `openbb-core` 의 `fastapi==0.136.3` 핀이 무력화돼 `from openbb import obb` 가 모든 머신에서 조용히 죽었다(4 호출 지점이 전부 yfinance 폴백으로 7일). openbb 는 #1477 로 제거했고 fastapi/starlette 는 보통 의존성이다. 남은 override 는 부모가 `any` 제약인 `aiohttp` 뿐 — 라이브러리 내부 결합이 있는 패키지에는 상한 없는 override 를 두지 말 것. *(facts, no fix)*
- **dependabot 의 semver 는 manifest 변화만 본다** — `numpy>=1.26.0` 같은 하한 제약 아래서는 lock 의 major 이동이 `update-type` 에 **아예 안 나타나고** `dependency-names` 에 이름조차 없다. `pip`→`uv` 전환(#1352)이 연 축이다: pip 은 `uv.lock` 을 쓰는 코드 경로가 없어 불가능했다. #1355 가 그 사고 — 제목 "bump scipy 1.17.1→1.18.1 (minor)" 로 **numpy 1.26.4→2.5.2 가 무인 자동 머지**됐고, `numba`/`llvmlite` 는 pyproject 에 아예 없어 manifest 기반 검사로는 영영 안 보인다. 그래서 `dependabot-auto-merge.yml` 은 fetch-metadata 가 아니라 **실제 lock diff** 를 본다 (`scripts/verify/check_lock_major_bump.py`). 0.x minor 도 경계로 친다(lock 의 24% 가 0.x — fastapi/uvicorn/httpx/vectorbt/ta-lib). CalVer(`tzdata 2025.3`, `pywin32 312`)는 제외 — 안 그러면 매년 오탐. **Test:** `tests/scripts/test_check_lock_major_bump.py::TestMajorBoundary::test_the_1355_lock_diff_is_refused` (동작) + `::TestWorkflowWiring::test_the_gate_script_is_invoked` (배선 — 함수 테스트는 호출부를 안 잠근다)
- **uv 의존성 그래프(= pip Dependabot alert 전부)는 `uv.lock` 정적 파싱이 아니라 Dependabot 동적 워크플로 `Dependency Graph`(`dynamic/dependabot/update-graph`, "Configured Graph Update: uv in /.") 가 만든다.** GitHub 문서의 생태계 표에는 uv 가 없다 — 관측 사실이다. 10-19 까지는 lock·pyproject 를 바꾸는 default-branch push 마다(소유자 push 포함) 돌았는데, 10-19T00:30Z 이후 멈춰 10-22 의 lock push 3건이 반영되지 않았고 이미 패치된 버전에 alert 37건이 남았다(#1899). 그래프가 낡았다고 의심되면 lock 내용을 고치기 전에 이 job 의 실행 기록부터 볼 것: `gh api "repos/{owner}/{repo}/actions/workflows" --jq '.workflows[]|select(.name=="Dependency Graph").id'` → `.../runs?per_page=3`. `uv.lock` 의 `revision` 3↔5 는 원인이 아니었다(#1900 실험). 그래프가 멈춘 동안 남은 alert 는 **경보마다** main `uv.lock` 버전이 그 경보의 first patched version 과 같은지 확인한 뒤에만 `inaccurate` 로 dismiss 하고 근거 댓글에 이슈를 단다(2026-10-23 37건, 다르면 건너뜀). 그래프 정지 이슈는 열어 둔다 — 정지 중에는 10-19 이후 바뀐 패키지에 새로 나온 advisory 를 **놓칠** 수 있다. *(facts, no fix)*

**venv 캐시는 인터프리터까지 담는다** (#1534): `ubuntu-26.04` 에는 시스템 python3.12 가 없어 uv 가 받아오는 인터프리터가 `$RUNNER_TEMP` 아래 생기고, `setup-uv` 는 그 경로를 잡지만 캐시하지 않는다. `.venv` 만 캐시하면 복원본의 `bin/python` 이 dangling 이라 **cache-hit 인데 모든 샤드가 죽는다** — `cache-hit` 은 "복원됐다" 지 "쓸 수 있다" 가 아니다. `setup-backend-env` 는 `UV_PYTHON_INSTALL_DIR` 를 `$RUNNER_TEMP/uv-python` 로 고정해 venv 와 함께 캐시하고, `uv sync` 는 `cache-hit != true` **또는** 복원본 python 실행 실패면 돈다(AND 로 바꾸면 부분 복원이 옛 lock 으로 테스트한다 — Codex P0). **Test:** `tests/scripts/test_ci_venv_cache.py::TestInstallGate::test_the_two_conditions_are_or_ed_not_and_ed` + `::TestVenvCacheIsSelfContained::test_cache_covers_the_interpreter_too`

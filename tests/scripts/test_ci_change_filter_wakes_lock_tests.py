"""잠금 테스트가 있는 파일은 `changes` 필터의 backend 경로에 있어야 한다 (#1562).

CI 는 PR 이 건드린 경로로 `Backend Tests` 를 켜고 끈다. 그런데 어떤 루트 파일은 `.py` 가
아니면서 백엔드 테스트가 잠근다 — `.cspell.json` 의 ASCII 정렬, `.gitignore` 의 개인 파생물
커버. (`CODEOWNERS` 는 #1559 가 잠금과 함께 추가한다.) 그 파일만 바꾼 PR 이 필터를 못 깨우면 잠금이 **그 PR 에선
안 돌고** main 이 빨간 채 남아 다음 무관한 PR 이 대신 죽는다 (#1556 → #1558, 2026-09-28).
`.test_durations` 가 #1419 에서 같은 이유로 들어갔다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "main-ci-cd.yml"

# (필터에 있어야 하는 경로, 그 파일을 잠그는 테스트) — 테스트 쪽도 존재를 확인해 낡은 항목을 잡는다
LOCKED = [
    (".cspell.json", "tests/verify/test_diagnostics_gate.py"),
    (".gitignore", "tests/test_gitignore_covers_private_derivatives.py"),
    (".test_durations", "tests/scripts/test_ci_shard_balance.py"),
]


def _backend_filter() -> list[str]:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in data["jobs"]["changes"]["steps"]:
        filters = (step.get("with") or {}).get("filters")
        if filters:
            return yaml.safe_load(filters)["backend"]
    raise AssertionError("`changes` job 의 paths-filter 스텝을 못 찾았다")


class TestChangeFilterWakesLockTests:
    @pytest.mark.parametrize(("path", "locking_test"), LOCKED, ids=[p for p, _ in LOCKED])
    def test_locked_file_is_a_backend_trigger(self, path, locking_test):
        assert path in _backend_filter(), (
            f"{path} 는 {locking_test} 가 잠그는데 backend 필터에 없다 — 그 파일만 바꾼 PR 에서 "
            "잠금이 안 돌고 main 이 빨간 채 남는다 (#1562)."
        )

    @pytest.mark.parametrize(("path", "locking_test"), LOCKED, ids=[p for p, _ in LOCKED])
    def test_the_cited_lock_test_exists(self, path, locking_test):
        """`LOCKED` 가 낡지 않게 — 잠금 테스트가 이사하면 여기서 보인다."""
        assert (REPO_ROOT / locking_test).is_file(), f"{locking_test} 가 없다 — {path} 의 잠금이 사라졌나?"

"""필수 CI 체크가 fail-open 하지 않는지 잠근다.

GitHub 은 **skipped 된 required check 를 만족으로 센다.** 그래서 `needs: <job>` 만
걸고 `if: ${{ !cancelled() }}` 를 빼면, 의존 잡이 실패했을 때 required check 가
조용히 건너뛰어지고 머지가 열린다 — 무엇을 테스트할지 결정하는 잡이 깨진 바로 그
순간에 게이트가 열리는 최악의 조합이다.

2026-08-10 감사에서 `Universe Coverage Validation` 이 유일하게 둘 다 빠져 있었다.
주석에는 "Always run — required gate" 라고 적혀 있었지만 실제로는 아니었다.

Gotcha-Test Pair (STRATEGY §5.3.1): 어느 required 잡에서든 `if: !cancelled()` 나
`changes.result` 검사를 빼면 이 테스트가 FAIL 한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "main-ci-cd.yml"

# branch protection 의 required_status_checks 사본.
#   gh api repos/researcherhojin/nuri-quant/branches/main/protection \
#     --jq '.required_status_checks.contexts'
# 로 실측 갱신할 것. 여기 목록이 낡으면 이 테스트는 조용히 범위가 줄어든다.
REQUIRED_CHECKS = {
    "Backend Tests",
    "Backend Lint",
    "Frontend Tests",
    "Frontend Build",
    "Security Scan",
    "Universe Coverage Validation",
    "Shell Lint",
    "Doc Count Drift Check",
    "Privacy Leak Scan",
    "Frontend Lint",
}


def _jobs() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def _needs(job: dict) -> list[str]:
    n = job.get("needs")
    if n is None:
        return []
    return [n] if isinstance(n, str) else list(n)


def _validates_dep_result(job: dict, dep: str) -> bool:
    """잡이 의존 잡의 result 를 스스로 검사하는가.

    스텝 *이름* 으로 찾지 않는다 — `Backend Tests` 애그리게이터는 "Guard" 가 아니라
    "Aggregate shard + slow results" 안에서 같은 검사를 한다. 이름으로 찾으면 오탐.
    """
    blob = " ".join(str(s.get("run", "")) + str(s.get("if", "")) for s in job.get("steps", []))
    return f"needs.{dep}.result" in blob


class TestRequiredChecksFailClosed:
    def test_workflow_parses_and_required_names_exist(self):
        """정규식/목록이 조용히 눈멀면 아래 테스트가 공허하게 통과한다."""
        names = {j.get("name", jid) for jid, j in _jobs().items()}
        # matrix 잡은 이름에 ${{ }} 가 남으므로 prefix 매칭 허용
        missing = [c for c in REQUIRED_CHECKS if not any(n.startswith(c) for n in names)]
        assert not missing, f"required check 인데 워크플로에 해당 잡이 없음: {missing}"

    def test_every_required_job_with_needs_runs_when_its_dep_fails(self):
        """required + `needs:` 면 `!cancelled()` 와 dep result 검사가 **둘 다** 있어야 한다."""
        offenders = []
        for jid, job in _jobs().items():
            name = job.get("name", jid)
            if name not in REQUIRED_CHECKS:
                continue
            deps = _needs(job)
            if not deps:
                continue
            cond = str(job.get("if", ""))
            if "cancelled()" not in cond:
                offenders.append(f"{name}: `if: !cancelled()` 없음 (if={cond!r})")
                continue
            if not any(_validates_dep_result(job, d) for d in deps):
                offenders.append(f"{name}: 의존 잡 {deps} 의 result 를 검사하지 않음")
        assert not offenders, (
            "skipped required check 는 GitHub 에서 '성공' 으로 계산된다 — "
            "아래 잡은 의존 잡이 실패하면 fail-open 한다:\n  " + "\n  ".join(offenders)
        )

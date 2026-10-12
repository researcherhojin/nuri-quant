"""main HEAD 에 CI 런이 없을 때만 main-ci-cd 를 dispatch 하는가 — 스크립트를 stub `gh` 로 실행해서 본다 (#1812).

**막으려는 것**: GITHUB_TOKEN 이 한 머지(dependabot auto-merge)는 워크플로를 시작하지 않아 main CI 가
없고, autopull 의 CI 게이트(#1809)는 그 커밋을 "no-run" 으로 보류한다. 2026-10-12 실측으로 6건의 머지
커밋이 main CI 0회였다. catch-up 이 런을 띄워야 하고, 이미 런이 있거나(빨간 런 포함) 커밋이 막 생긴
때에는 띄우면 안 된다 — push 런과 같은 concurrency 그룹이라 서로 취소한다.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "main_ci_catchup.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "main-ci-catchup.yml"
SHA = "a" * 40
NOW = 2_000_000_000


@pytest.fixture()
def gh(tmp_path: Path):
    """argv 를 기록하고 정해진 응답을 내는 가짜 gh."""
    binz = tmp_path / "bin"
    binz.mkdir()
    calls, heads = tmp_path / "calls.txt", tmp_path / "heads.txt"
    (binz / "gh").write_text(
        "#!/bin/sh\n"
        f'printf \'%s\\n\' "$*" >> "{calls}"\n'
        'case "$*" in\n'
        # HEAD 조회는 부를 때마다 heads.txt 의 다음 줄을 낸다 (마지막 줄에서 멈춘다) — 확인 뒤 main 이 움직이는 경우.
        '    "api repos/o/r/commits/main "*) [ "${STUB_HEAD_RC:-0}" = 0 ] || exit "$STUB_HEAD_RC"; '
        f'h=$(grep -c "commits/main" "{calls}"); line=$(sed -n "${{h}}p" "{heads}"); '
        f'[ -n "$line" ] || line=$(tail -1 "{heads}"); printf \'%s\\n\' "$line" ;;\n'
        '    "api repos/o/r/actions/workflows/main-ci-cd.yml/runs?"*) printf \'%s\\n\' "$STUB_RUNS" ;;\n'
        '    "workflow run "*) exit 0 ;;\n'
        "    *) exit 97 ;;\n"
        "esac\n"
    )
    (binz / "gh").chmod(0o755)

    def run(committed: int, runs: int | str, later_head: str | None = None, head: str | None = None, **env_extra: str):
        first = head if head is not None else f"{SHA} {committed}"
        heads.write_text(first + "\n" + (f"{later_head} {committed}\n" if later_head else ""))
        env = {
            **os.environ,
            "PATH": f"{binz}:{os.environ['PATH']}",
            "GITHUB_REPOSITORY": "o/r",
            "CATCHUP_NOW": str(NOW),
            "STUB_RUNS": str(runs),
            **env_extra,
        }
        r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30)
        return r, (calls.read_text().splitlines() if calls.exists() else [])

    return run


def _dispatches(calls: list[str]) -> list[str]:
    return [c for c in calls if c.startswith("workflow run")]


class TestCatchupDispatchesOnlyAnUntestedHead:
    def test_an_old_head_without_runs_gets_one_dispatch_on_main(self, gh):
        r, calls = gh(committed=NOW - 3600, runs=0)
        assert r.returncode == 0, r.stderr
        assert _dispatches(calls) == ["workflow run main-ci-cd.yml --ref main -R o/r"]

    def test_it_asks_about_main_head_and_that_exact_sha_on_main(self, gh):
        _, calls = gh(committed=NOW - 3600, runs=0)
        assert calls[0].startswith("api repos/o/r/commits/main --jq "), calls
        assert any(
            c.startswith(f"api repos/o/r/actions/workflows/main-ci-cd.yml/runs?head_sha={SHA}&branch=main&")
            for c in calls
        ), calls

    def test_a_head_that_already_has_a_run_is_left_alone(self, gh):
        """빨간 런도 런이다 — 다시 돌릴지는 사람이 정한다."""
        r, calls = gh(committed=NOW - 3600, runs=1)
        assert r.returncode == 0, r.stderr
        assert _dispatches(calls) == []
        assert "already has 1 main-ci-cd run" in r.stdout

    def test_a_fresh_head_is_left_alone(self, gh):
        """방금 생긴 커밋은 push 런이 아직 안 보일 수 있다 — dispatch 하면 그 push 런과 서로 취소한다."""
        r, calls = gh(committed=NOW - 120, runs=0)
        assert r.returncode == 0, r.stderr
        assert _dispatches(calls) == []

    def test_an_unreadable_head_fails_without_dispatching(self, gh):
        r, calls = gh(committed=NOW - 3600, runs=0, STUB_HEAD_RC="1")
        assert r.returncode != 0
        assert _dispatches(calls) == []

    def test_a_head_that_moves_before_the_dispatch_is_left_alone(self, gh):
        """dispatch 는 SHA 가 아니라 main ref 에 걸린다 — 확인한 커밋이 아닌 새 커밋에 걸면 그 커밋의 판단(나이 · 기존 런)을 건너뛴다."""
        r, calls = gh(committed=NOW - 3600, runs=0, later_head="b" * 40)
        assert r.returncode == 0, r.stderr
        assert _dispatches(calls) == []
        assert "main moved" in r.stdout

    @pytest.mark.parametrize("runs", ["null", "", "1 2"])
    def test_a_malformed_run_count_fails_without_dispatching(self, gh, runs):
        """if 조건 안의 비교 오류는 set -e 로 안 멈춘다 — 형식을 먼저 확인하지 않으면 "런 없음" 으로 떨어져 dispatch 했다."""
        r, calls = gh(committed=NOW - 3600, runs=runs)
        assert r.returncode != 0
        assert _dispatches(calls) == []

    @pytest.mark.parametrize("head", ["zzz 123", "null null"])
    def test_a_malformed_head_fails_without_dispatching(self, gh, head):
        """ "zzz 123" 은 산술이 성립해서 형식 검사가 없으면 그대로 dispatch 까지 간다 — 우연한 실패에 기대지 않는 케이스."""
        r, calls = gh(committed=NOW - 3600, runs=0, head=head)
        assert r.returncode != 0
        assert _dispatches(calls) == []


class TestWorkflowWiring:
    def test_the_workflow_runs_the_script_hourly_with_actions_write(self):
        wf = yaml.safe_load(WORKFLOW.read_text())
        on = wf.get("on", wf.get(True))
        assert on["schedule"] and "workflow_dispatch" in on
        assert wf["permissions"]["actions"] == "write"
        steps = wf["jobs"]["catchup"]["steps"]
        run = [s for s in steps if "run" in s]
        assert run and run[-1]["run"].strip() == "bash scripts/ci/main_ci_catchup.sh"
        assert run[-1]["env"]["GH_TOKEN"] == "${{ github.token }}"

    def test_dispatch_runs_never_cancel_push_runs(self):
        """push 런과 dispatch 런이 한 concurrency 그룹이면 catch-up 이 사람 머지의 push CI 를 취소할 수 있다."""
        ci = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "main-ci-cd.yml").read_text())
        assert "${{ github.event_name }}" in ci["concurrency"]["group"]

    def test_dispatched_runs_also_run_the_slow_tests(self):
        """dispatch 런이 push 런보다 덜 검사하면 bot 머지 커밋은 slow 테스트를 영영 안 거친다."""
        ci = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "main-ci-cd.yml").read_text())
        assert ci["jobs"]["backend-tests-slow"]["if"] == "github.event_name != 'pull_request'"

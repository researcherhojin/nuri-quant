"""닫힌 PR 의 캐시만 지우는가 — 스크립트를 stub `gh` 로 실행해서 본다 (#1812).

**막으려는 것**: PR 이 닫힐 때의 즉시 삭제(cache-cleanup.yml)는 GITHUB_TOKEN 이 머지한 PR 에서 시작되지
않는다. 2026-10-12 에 그렇게 남은 4개 PR 의 캐시가 4.8GB 로 repo 한도 10GB 의 절반을 넘었다. 정기 청소는
닫힌 PR 의 `refs/pull/N/merge` 캐시만 지우고, 열린 PR 과 main 의 캐시는 건드리면 안 된다.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "sweep_closed_pr_caches.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "cache-cleanup.yml"


@pytest.fixture()
def gh(tmp_path: Path):
    """argv 를 기록하는 가짜 gh — 캐시 ref 목록과 PR 별 상태를 파일로 받는다."""
    binz, states = tmp_path / "bin", tmp_path / "states"
    binz.mkdir()
    states.mkdir()
    calls, refs = tmp_path / "calls.txt", tmp_path / "refs.txt"
    (binz / "gh").write_text(
        "#!/bin/sh\n"
        f'printf \'%s\\n\' "$*" >> "{calls}"\n'
        'case "$*" in\n'
        f'    "api --paginate repos/o/r/actions/caches?per_page=100 "*) cat "{refs}" ;;\n'
        f'    "api repos/o/r/pulls/"*) n="${{2##*/}}"; [ -f "{states}/$n" ] || exit 1; cat "{states}/$n" ;;\n'
        '    "cache delete "*) exit 0 ;;\n'
        "    *) exit 97 ;;\n"
        "esac\n"
    )
    (binz / "gh").chmod(0o755)

    def run(cache_refs: list[str], pr_states: dict[int, str]):
        refs.write_text("".join(f"{r}\n" for r in cache_refs))
        for n, st in pr_states.items():
            (states / str(n)).write_text(f"{st}\n")
        env = {**os.environ, "PATH": f"{binz}:{os.environ['PATH']}", "GITHUB_REPOSITORY": "o/r"}
        r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30)
        return r, (calls.read_text().splitlines() if calls.exists() else [])

    return run


def _deletes(calls: list[str]) -> list[str]:
    return [c for c in calls if c.startswith("cache delete")]


class TestSweepDeletesOnlyClosedPrCaches:
    def test_a_closed_prs_caches_go_and_an_open_prs_stay(self, gh):
        r, calls = gh(["refs/pull/5/merge", "refs/pull/6/merge"], {5: "closed", 6: "open"})
        assert r.returncode == 0, r.stderr
        assert _deletes(calls) == ["cache delete --all --ref refs/pull/5/merge -R o/r --succeed-on-no-caches"]

    def test_branch_caches_are_never_looked_up_or_deleted(self, gh):
        r, calls = gh(["refs/heads/main", "refs/heads/feature"], {})
        assert r.returncode == 0, r.stderr
        assert _deletes(calls) == []
        assert not [c for c in calls if c.startswith("api repos/o/r/pulls/")], calls

    def test_each_pr_ref_is_checked_and_deleted_once(self, gh):
        """ref 하나에 캐시가 여러 개여도(venv · uv-tool · node) PR 조회와 삭제는 한 번이다."""
        r, calls = gh(["refs/pull/7/merge"] * 3, {7: "closed"})
        assert r.returncode == 0, r.stderr
        assert [c for c in calls if c.startswith("api repos/o/r/pulls/")] == ["api repos/o/r/pulls/7 --jq .state"]
        assert len(_deletes(calls)) == 1

    def test_no_caches_is_a_quiet_success(self, gh):
        r, calls = gh([], {})
        assert r.returncode == 0, r.stderr
        assert _deletes(calls) == []
        assert "swept 0" in r.stdout

    def test_an_unreadable_pr_state_fails_without_deleting(self, gh):
        r, calls = gh(["refs/pull/8/merge"], {})
        assert r.returncode != 0
        assert _deletes(calls) == []


class TestWorkflowWiring:
    def test_the_sweep_runs_daily_and_the_close_trigger_stays(self):
        wf = yaml.safe_load(WORKFLOW.read_text())
        on = wf.get("on", wf.get(True))
        assert on["pull_request"]["types"] == ["closed"]
        assert on["schedule"] and "workflow_dispatch" in on
        assert wf["permissions"]["actions"] == "write"
        sweep = wf["jobs"]["sweep"]
        assert sweep["if"] == "github.event_name != 'pull_request'"
        run = [s for s in sweep["steps"] if "run" in s]
        assert run and run[-1]["run"].strip() == "bash scripts/ci/sweep_closed_pr_caches.sh"
        assert wf["jobs"]["cleanup"]["if"] == "github.event_name == 'pull_request'"

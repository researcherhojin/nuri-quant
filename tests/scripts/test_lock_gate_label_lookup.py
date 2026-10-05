"""lock Major Boundary 게이트의 `lock-bump-reviewed` 조회를 **실행해서** 잠근다 (#1592).

## 무엇이 문제였나

두 required check(`uv.lock Major Boundary` / `package-lock.json Major Boundary`)는 라벨을
이벤트 페이로드(`github.event.pull_request.labels.*.name`)에서 읽었다. 실측(#1586,
2026-10-05): 라벨 03:12, 실패 런 03:01 시작 — RED 가 남았다. `gh run rerun` 은 원래
페이로드를 재생하고, 이미 최신인 브랜치에 `@dependabot rebase` 는 push 하지 않는다.
`@dependabot recreate` 로 새 런을 만들었더니 그 force-push 가 **auto-merge 를 해제**했다.
`pr-discipline` 에서 #1552 가 고친 것과 같은 결함이다.

## 왜 실행하나

`test_pr_discipline_label_lookup.py` 와 같은 이유 — 스텝 텍스트를 긁는 테스트는 반복해서
뚫렸다. `git` / `python3` / `gh` 를 PATH 앞단의 가짜로 바꿔 스텝 본문을 실제 셸로 돌리고
exit code 를 본다. 가짜 `python3` 는 항상 "경계를 넘는다"(rc=1)를 돌려 라벨 분기까지 간다.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "main-ci-cd.yml"
JOBS = ["lock-gate", "npm-lock-gate"]


def _job(name: str) -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"][name]


def _gate_step(name: str) -> dict:
    steps = [s for s in _job(name)["steps"] if "check_lock_major_bump.py" in str(s.get("run", ""))]
    assert len(steps) == 1, f"{name}: 게이트 스텝이 1개가 아니다 ({len(steps)})"
    return steps[0]


def _run_step(
    tmp_path: Path, job: str, *, labels: list[str] | None, dependabot: bool = True, gh_fails: bool = False
) -> tuple[int, str]:
    """스텝 본문을 셸로 돌리고 `(exit code, gh 에 넘어간 argv)` 를 돌려준다. 네트워크·토큰 미사용."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    argv_log = tmp_path / "argv"

    def _fake(name: str, body: str) -> None:
        f = fake_bin / name
        f.write_text("#!/bin/sh\n" + body)
        f.chmod(0o755)

    _fake("git", "exit 0\n")
    _fake("python3", "exit 1\n")  # 항상 경계를 넘는다 → 라벨 분기까지 간다
    if gh_fails:
        gh_body = "echo 'gh: API 실패' >&2\nexit 1\n"
    else:
        gh_body = "".join(f"echo {name}\n" for name in (labels or []))
    _fake("gh", f'printf \'%s\\n\' "$@" > "{argv_log}"\n' + gh_body)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "BASE_REF": "main",
        "IS_DEPENDABOT": "true" if dependabot else "false",
        "GH_TOKEN": "x",
        "REPO": "owner/repo",
        "PR_NUMBER": "1",
    }
    script = tmp_path / "step.sh"
    script.write_text(_gate_step(job)["run"])
    result = subprocess.run(["bash", "-e", str(script)], capture_output=True, text=True, env=env, timeout=30)
    return result.returncode, (argv_log.read_text() if argv_log.exists() else "")


@pytest.mark.parametrize("job", JOBS)
class TestReviewedLabelLookup:
    def test_the_label_is_read_from_the_api_not_the_event_payload(self, job):
        """페이로드로 되돌리면 FAIL — rerun 이 나중에 붙인 라벨을 못 보는 상태로 회귀한다."""
        step = _gate_step(job)
        assert "gh api" in step["run"], f"{job}: 라벨을 API 로 조회하지 않는다"
        payload_refs = [k for k, v in (step.get("env") or {}).items() if "pull_request.labels" in str(v)]
        assert not payload_refs, f"{job}: 이벤트 페이로드의 labels 를 다시 읽는다: {payload_refs} (#1592)"

    def test_the_label_present_passes(self, tmp_path, job):
        rc, _ = _run_step(tmp_path, job, labels=["dependencies", "lock-bump-reviewed"])
        assert rc == 0

    def test_no_label_blocks(self, tmp_path, job):
        rc, _ = _run_step(tmp_path, job, labels=["dependencies", "backend"])
        assert rc == 1

    @pytest.mark.parametrize("label", ["lock-bump-reviewed-v2", "not-lock-bump-reviewed", "lock-bump"])
    def test_a_similar_label_does_not_pass(self, tmp_path, job, label):
        rc, _ = _run_step(tmp_path, job, labels=[label])
        assert rc == 1, f"{label!r} 가 게이트를 열었다"

    def test_a_failed_lookup_blocks_instead_of_passing(self, tmp_path, job):
        """조회 실패는 통과가 아니다 — required check 라 여기가 뚫리면 major 가 무인 머지된다."""
        rc, _ = _run_step(tmp_path, job, labels=None, gh_fails=True)
        assert rc == 1

    def test_it_queries_this_pr_by_number_with_a_label_jq(self, tmp_path, job):
        """엉뚱한 PR 의 라벨로 통과하면 안 된다 — PR 번호·jq 까지 잠근다 (#1552 교차리뷰 교훈)."""
        _, argv = _run_step(tmp_path, job, labels=["backend"])
        args = argv.split("\n")
        assert "api" in args and "repos/owner/repo/pulls/1" in args, f"{job}: 이 PR 을 조회하지 않는다: {args}"
        assert "--jq" in args and "labels" in args[args.index("--jq") + 1], f"{job}: 라벨 jq 가 아니다: {args}"

    def test_a_human_pr_passes_without_a_lookup(self, tmp_path, job):
        """사람 PR 은 조회 없이 통과 — push 이벤트에는 PR 번호가 없어 조회가 앞서면 안 된다."""
        rc, argv = _run_step(tmp_path, job, labels=[], dependabot=False)
        assert rc == 0 and not argv, f"{job}: 사람 PR 에서 라벨을 조회했다: {argv!r}"

    @pytest.mark.parametrize("binding", ["GH_TOKEN", "REPO", "PR_NUMBER"])
    def test_the_step_declares_every_env_binding_it_uses(self, job, binding):
        """하네스가 세 값을 주입하므로 워크플로에서 지워도 실행 테스트는 모른다 — 형태로 따로 잠근다."""
        assert binding in (_gate_step(job).get("env") or {}), f"{job}: `env:` 에 {binding} 이 없다"

    def test_the_job_can_read_pull_requests(self, job):
        """워크플로 기본 권한은 `contents: read` 뿐 — job 권한이 없으면 조회가 403 → 영구 차단."""
        assert (_job(job).get("permissions") or {}).get("pull-requests") == "read"

    def test_the_lookup_is_not_piped_into_grep(self, job):
        """`set -euo pipefail` 아래 `gh | grep -q` 는 SIGPIPE 로 라벨이 있어도 막힌다."""
        run = _gate_step(job)["run"]
        piped = [ln for ln in run.splitlines() if "gh api" in ln and "|" in ln.replace("||", "")]
        assert not piped, f"{job}: gh 출력을 파이프로 넘긴다: {piped}"

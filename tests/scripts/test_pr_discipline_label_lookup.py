"""`Commit count gate` 의 escape 라벨 조회를 **실행해서** 잠근다 (#1552).

## 무엇이 문제였나

게이트는 `scope-expand-approved` 를 이벤트 페이로드
(`github.event.pull_request.labels.*.name`)에서 읽었다. 그래서 라벨을 **나중에** 붙인
PR 에 영구히 빨간 체크가 남았다:

- 라벨 이전 `synchronize` 런의 실패가 PR 의 check rollup 에 그대로 남는다
- `gh run rerun` 은 **원래 이벤트 페이로드를 재생**하므로 새 라벨을 못 본다

실측(#1550, 2026-09-28):

    09:32:07 synchronize  failure   ← 4번째 커밋 push, 라벨 아직 없음
    09:37:37 rerun        failure   ← 페이로드 재생, 라벨 못 봄
    09:38:31 unlabeled    failure
    09:38:34 labeled      success   ← 라벨 보고 skip

이 게이트는 required check 이 **아니라서** 머지를 막지 않는다. 그래서 피해는 "막힘" 이
아니라 **빨간불의 의미가 닳는 것**이다 — escape 를 정당하게 쓸 때마다 무해한 빨간 체크가
남으면 빨간 체크를 무시하는 습관이 생긴다.

## 왜 실행하나

이 레포에서 워크플로 스텝을 텍스트로 긁는 테스트는 반복해서 뚫렸다 (#1549 의 정책 테스트가
if/else 체인 **뒤에** 붙은 후처리 가드 한 줄에 7개 전부 통과했다). 스텝 본문을 실제 셸로
돌리고 `$GITHUB_OUTPUT` 을 읽으면 그 형태와 무관하게 결과를 본다 —
`tests/test_hook_guard_execution.py` · `tests/test_pre_push_hook.py` 와 같은 방식이다.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr-discipline.yml"


def _label_step() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text())
    steps = data["jobs"]["commit-count"]["steps"]
    for step in steps:
        if step.get("id") == "label":
            return step
    raise AssertionError("`id: label` 스텝을 못 찾았다 — 게이트가 옮겨졌나?")


def _run_step(tmp_path: Path, *, labels: list[str] | None, gh_fails: bool = False) -> str:
    """스텝 본문을 셸로 돌리고 `skip=` 출력을 돌려준다.

    `gh` 를 PATH 앞단의 가짜로 바꿔 라벨 응답을 통제한다. 네트워크도 토큰도 안 쓴다.
    """
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    if gh_fails:
        body = "echo 'gh: API 실패' >&2\nexit 1\n"
    else:
        body = "".join(f"echo {name}\n" for name in (labels or []))
    gh = fake_bin / "gh"
    gh.write_text("#!/bin/sh\n" + body)
    gh.chmod(0o755)

    output = tmp_path / "gh_output"
    output.write_text("")

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(output),
        "GH_TOKEN": "x",
        "REPO": "owner/repo",
        "PR_NUMBER": "1",
    }
    script = tmp_path / "step.sh"
    script.write_text(_label_step()["run"])
    result = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env, timeout=30)
    assert result.returncode == 0, f"스텝이 죽었다:\n{result.stderr}"
    return output.read_text()


class TestEscapeHatchLabelLookup:
    def test_the_label_is_read_from_the_api_not_the_event_payload(self):
        """페이로드로 되돌리면 FAIL — rerun 이 새 라벨을 못 보는 상태로 회귀한다."""
        step = _label_step()
        run = step["run"]
        env = step.get("env") or {}

        assert "gh api" in run, f"라벨을 API 로 조회하지 않는다:\n{run}"
        payload_refs = [k for k, v in env.items() if "pull_request.labels" in str(v)]
        assert not payload_refs, (
            f"이벤트 페이로드의 labels 를 다시 읽는다: {payload_refs} — 라벨을 나중에 "
            "붙인 PR 에 영구히 빨간 체크가 남는다 (#1552)."
        )

    def test_the_label_present_skips_the_gate(self, tmp_path):
        out = _run_step(tmp_path, labels=["backend", "scope-expand-approved", "ci"])
        assert "skip=true" in out, out

    def test_no_label_runs_the_gate(self, tmp_path):
        out = _run_step(tmp_path, labels=["backend", "ci"])
        assert "skip=false" in out, out

    def test_no_labels_at_all_runs_the_gate(self, tmp_path):
        out = _run_step(tmp_path, labels=[])
        assert "skip=false" in out, out

    @pytest.mark.parametrize(
        "label",
        ["scope-expand-approved-v2", "not-scope-expand-approved", "scope-expand"],
        ids=["suffix", "prefix", "truncated"],
    )
    def test_a_similar_label_does_not_open_the_escape_hatch(self, tmp_path, label):
        """부분 일치로 열리면 안 된다 — `grep -qx` 가 아니라 `grep -q` 면 뚫린다."""
        out = _run_step(tmp_path, labels=[label])
        assert "skip=false" in out, f"{label!r} 가 escape 를 열었다:\n{out}"

    def test_a_failed_lookup_runs_the_gate_instead_of_skipping(self, tmp_path):
        """조회 실패는 **통과가 아니다** (#910/#953 계열).

        "라벨을 확인 못 했다" 를 "라벨이 있다" 로 보고하면, `gh` 가 죽는 날 커밋 수
        검사가 통째로 무력해진다. 그 상태는 초록이라 아무 신호가 없다.
        """
        out = _run_step(tmp_path, labels=None, gh_fails=True)
        assert "skip=false" in out, out

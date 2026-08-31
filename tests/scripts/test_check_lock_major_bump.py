"""`scripts/verify/check_lock_major_bump.py` 회귀 — #1364.

**막으려는 사고** (2026-08-31 실측): PR #1355 는 제목이 "bump scipy from 1.17.1 to
1.18.1 in the python-data group" 이었고 fetch-metadata 가 `dependency-names=scipy` /
`update-type=version-update:semver-minor` / `group=python-data` 를 내놨다.
`dependabot-auto-merge.yml` 은 "grouped minor update" 로 판정해 **무인 머지**했다.
실제 `uv.lock` 은 numpy 를 1.26.4 -> 2.5.2 로 옮겼다.

`pyproject.toml` 이 `numpy>=1.26.0` 이라 2.5.2 도 제약을 만족해 manifest 가 안 바뀌고,
dependabot 은 manifest 변화로 semver 를 분류하므로 numpy 는 "업데이트" 로 분류조차 안 됐다.
`numba`/`llvmlite` 는 pyproject 에 아예 없다. manifest 를 보는 검사로는 영영 안 보인다.

**왜 세 축을 나누는가**: 함수 테스트는 **호출 배선을 잠그지 않는다**. 워크플로에서 게이트
스텝을 지워도 Axis 1·2 는 전부 초록이다 — 그래서 Axis 3 이 따로 있다.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "dependabot-auto-merge.yml"


def _lock(*packages: tuple[str, str], root_version: str | None = None) -> str:
    """최소한이지만 **진짜** uv.lock TOML — 실제 파일과 같은 모양이어야 파서를 잠근다."""
    body = 'version = 1\nrevision = 3\nrequires-python = ">=3.12"\n'
    if root_version is not None:
        body += textwrap.dedent(f"""
            [[package]]
            name = "nuri-quant"
            version = "{root_version}"
            source = {{ editable = "." }}
            """)
    for name, version in packages:
        body += textwrap.dedent(f"""
            [[package]]
            name = "{name}"
            version = "{version}"
            source = {{ registry = "https://pypi.org/simple" }}
            """)
    return body


@pytest.fixture()
def run(tmp_path: Path):
    """두 lock 텍스트를 파일로 떨구고 `main()` 을 **실행**해 (rc, 출력) 을 준다."""
    from scripts.verify.check_lock_major_bump import main

    def _run(base_text: str, head_text: str, capsys) -> tuple[int, str]:
        (tmp_path / "base.lock").write_text(base_text, encoding="utf-8")
        (tmp_path / "head.lock").write_text(head_text, encoding="utf-8")
        rc = main(["--base", str(tmp_path / "base.lock"), "--head", str(tmp_path / "head.lock")])
        return rc, capsys.readouterr().out

    return _run


class TestMajorBoundary:
    """실제 lock 텍스트로 `main()` 을 돌려 rc **와** 메시지를 둘 다 본다."""

    def test_the_1355_lock_diff_is_refused(self, run, capsys):
        """사고 그 자체 — 이 케이스가 통과하면 게이트가 존재할 이유가 없다."""
        before = _lock(
            ("llvmlite", "0.46.0"),
            ("numba", "0.64.0"),
            ("numpy", "1.26.4"),
            ("pykrx", "1.2.4"),
            ("scipy", "1.17.1"),
        )
        after = _lock(
            ("llvmlite", "0.49.0"),
            ("numba", "0.67.0"),
            ("numpy", "2.5.2"),
            ("pykrx", "1.2.8"),
            ("scipy", "1.18.1"),
        )
        rc, out = run(before, after, capsys)
        assert rc == 1, f"#1355 diff 를 통과시켰다:\n{out}"
        assert "numpy 1.26.4 -> 2.5.2" in out and "(major)" in out, out

    def test_the_scipy_and_pykrx_rows_alone_are_allowed(self, run, capsys):
        """제목이 말하던 그 두 줄만이면 통과해야 한다 — 게이트가 전부 막으면 꺼진다."""
        before = _lock(("pykrx", "1.2.4"), ("scipy", "1.17.1"))
        after = _lock(("pykrx", "1.2.8"), ("scipy", "1.18.1"))
        rc, out = run(before, after, capsys)
        assert rc == 0, out

    def test_a_zero_x_minor_is_refused(self, run, capsys):
        """이 테스트가 곧 0.x 정책이다 — 지우면 그 규칙은 folklore 가 된다.

        lock 의 24% 가 0.x 고 fastapi/uvicorn/httpx/vectorbt/ta-lib 가 전부 거기 있다.
        major-only 규칙은 이 트리에서 사실상 numpy 밖에 못 잡는다.
        """
        rc, out = run(_lock(("numba", "0.64.0")), _lock(("numba", "0.67.0")), capsys)
        assert rc == 1, out
        assert "0.x minor" in out, out

    def test_a_zero_x_patch_is_allowed(self, run, capsys):
        """slowapi 0.1.9 -> 0.1.10 은 #1357 로 깨끗하게 나갔다 — 막으면 오탐이다."""
        rc, out = run(_lock(("slowapi", "0.1.9")), _lock(("slowapi", "0.1.10")), capsys)
        assert rc == 0, out

    def test_calendar_versions_do_not_cross(self, run, capsys):
        """CalVer 예외가 없으면 tzdata 는 매년, pywin32 는 매 릴리스 오탐한다."""
        before = _lock(
            ("tzdata", "2025.3"),
            ("pywin32", "312"),
            ("certifi", "2026.2.25"),
            ("astropy-iers-data", "0.2026.3.30.0.54.34"),
        )
        after = _lock(
            ("tzdata", "2026.1"),
            ("pywin32", "313"),
            ("certifi", "2027.1.1"),
            ("astropy-iers-data", "0.2027.1.1.0.0.0"),
        )
        rc, out = run(before, after, capsys)
        assert rc == 0, out

    def test_a_versioning_scheme_change_is_refused(self, run, capsys):
        rc, out = run(_lock(("rpds-py", "0.30.0")), _lock(("rpds-py", "2026.5.1")), capsys)
        assert rc == 1, out
        assert "scheme change" in out, out

    def test_an_unparseable_version_is_refused_not_passed(self, run, capsys):
        """'해석 못 했다' 를 '경계 없음' 으로 보고하지 않는다 (#910/#911 계열)."""
        rc, out = run(_lock(("weird", "1.2.3")), _lock(("weird", "v1.2.3")), capsys)
        assert rc == 1, out

    def test_a_malformed_lock_is_refused_not_passed(self, run, capsys):
        rc, out = run(_lock(("numpy", "1.26.4")), "this is not toml [[[", capsys)
        assert rc == 1, out

    def test_a_resolution_marker_fork_is_refused(self, run, capsys):
        """같은 이름이 두 번 나오면 단일 버전으로 못 줄인다 — 조용히 덮어쓰지 않는다."""
        forked = _lock(("numpy", "1.26.4"), ("numpy", "2.5.2"))
        rc, out = run(_lock(("numpy", "1.26.4")), forked, capsys)
        assert rc == 1, out
        assert "fork" in out, out

    def test_added_and_removed_packages_do_not_block(self, run, capsys):
        """openbb 4.7.1 -> 4.7.2 (#1356) 가 frozendict 를 지웠다 — 통상 patch bump 다."""
        before = _lock(("openbb", "4.7.1"), ("frozendict", "2.4.7"))
        after = _lock(("openbb", "4.7.2"))
        rc, out = run(before, after, capsys)
        assert rc == 0, out
        assert "removed" in out, out

    def test_the_editable_root_entry_is_ignored(self, run, capsys):
        """루트를 판정하면 레포 자체 버전 bump 마다 major 로 잡힌다 (e752a116 실제 사례)."""
        before = _lock(("numpy", "1.26.4"), root_version="0.1.0")
        after = _lock(("numpy", "1.26.4"), root_version="0.2.0")
        rc, out = run(before, after, capsys)
        assert rc == 0, out


class TestParserIsNotBlind:
    """카나리아 — 파서가 `{}` 를 돌려주면 위 클래스 전체가 공허하게 통과한다."""

    def test_the_repo_lock_parses(self):
        from scripts.verify.check_lock_major_bump import parse_lock

        pkgs = parse_lock((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
        assert len(pkgs) >= 200, f"registry 패키지를 {len(pkgs)}개만 읽었다 — 파서가 눈이 멀었다"
        assert "numpy" in pkgs
        assert "nuri-quant" not in pkgs, "editable 루트가 판정 대상에 들어왔다"

    def test_every_version_in_the_repo_lock_is_parseable(self):
        """`_RELEASE` 를 `^\\d+\\.\\d+\\.\\d+$` 로 조이면 13개 이상한 모양이 한꺼번에 차단된다."""
        from scripts.verify.check_lock_major_bump import parse_lock, release

        pkgs = parse_lock((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
        bad = sorted(f"{n}=={v}" for n, v in pkgs.items() if release(v) is None)
        assert not bad, f"해석 못 하는 버전 (전부 fail-closed 된다): {bad}"

    def test_the_repo_lock_does_not_cross_against_itself(self, tmp_path):
        from scripts.verify.check_lock_major_bump import main

        lock = REPO_ROOT / "uv.lock"
        assert main(["--base", str(lock), "--head", str(lock)]) == 0


class TestWorkflowWiring:
    """게이트가 **실제로 배선돼 있는지** — 함수 테스트는 이걸 잠그지 않는다."""

    @staticmethod
    def _steps() -> list[dict]:
        wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        return wf["jobs"]["enable-auto-merge"]["steps"]

    def test_the_job_and_its_steps_exist(self):
        """카나리아 — 잡 이름이 바뀌면 아래 전부가 공허해진다."""
        assert len(self._steps()) >= 5

    def test_the_gate_script_is_invoked(self):
        hits = [s for s in self._steps() if "check_lock_major_bump.py" in str(s.get("run", ""))]
        assert hits, "워크플로가 게이트 스크립트를 부르지 않는다 — 스크립트만 있고 배선이 없다"
        assert hits[0].get("id"), "게이트 스텝에 id 가 없으면 정책이 결과를 못 읽는다"

    def test_the_policy_consumes_the_gate_verdict(self):
        steps = self._steps()
        gate_id = next(s["id"] for s in steps if "check_lock_major_bump.py" in str(s.get("run", "")))
        policy = next(s for s in steps if "shouldMerge" in str(s.get("with", {}).get("script", "")))
        wanted = f"steps.{gate_id}.outputs.verdict"
        env = policy.get("env", {})
        key = next((k for k, v in env.items() if wanted in str(v)), None)
        assert key, f"정책 스텝이 {wanted} 를 env 로 안 받는다: {env}"
        assert key in str(policy["with"]["script"]), f"env {key} 를 받아만 놓고 안 쓴다"

    def test_the_policy_asserts_clean_positively(self):
        """`!== "clean"` 이어야 한다. `=== "blocked"` 면 빈 문자열이 통과한다 — 스텝이

        죽거나 스킵되면 output 이 비고, 그때 fail-open 이 된다. 이 레포가 두 번 데인 축이다.
        """
        script = str(
            next(s for s in self._steps() if "shouldMerge" in str(s.get("with", {}).get("script", "")))["with"][
                "script"
            ]
        )
        assert '!== "clean"' in script, "게이트 판정을 positive assertion 으로 안 읽는다"
        assert '=== "blocked"' not in script, "fail-open 반전 — 빈 판정이 통과한다"

    def test_no_step_checks_out_pr_head(self):
        """보안 잠금: `pull_request_target` 에서 head 체크아웃은 금지다.

        actions/checkout 의 `allow-unsafe-pr-checkout` 가드는 여기서 **무력하다** —
        fork PR 에서만 발동하는데 dependabot 브랜치는 same-repo 라 early-return 한다.
        """
        for step in self._steps():
            with_ = step.get("with") or {}
            assert "ref" not in with_, f"checkout 에 ref 가 붙었다: {step}"
            assert "pull_request.head" not in str(with_), f"head 를 참조한다: {step}"

    def test_the_gate_step_is_not_conditional_or_soft(self):
        gate = next(s for s in self._steps() if "check_lock_major_bump.py" in str(s.get("run", "")))
        assert "if" not in gate, "게이트에 if 가 붙으면 조용히 안 돌 수 있다"
        assert not gate.get("continue-on-error"), "continue-on-error 는 게이트를 무력화한다"

    def test_auto_merge_is_revoked_when_the_policy_says_no(self):
        """게이트가 막아도 **이전 run 이 켜둔** auto-merge 가 남아 있으면 그대로 머지된다.

        dependabot 이 rebase 로 force-push 하면 opened 시점의 판정이 살아남는다.
        """
        steps = self._steps()
        revoke = [s for s in steps if "disablePullRequestAutoMerge" in str(s.get("with", {}).get("script", ""))]
        assert revoke, "정책이 거부해도 기존 auto-merge 를 해제하지 않는다"
        assert "!= 'true'" in str(revoke[0].get("if", "")), f"해제 조건이 없다: {revoke[0].get('if')}"

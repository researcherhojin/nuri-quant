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

    def test_a_version_with_trailing_garbage_is_refused(self, run, capsys):
        """`1.2.3garbage` 가 조용히 `1.2.3` 으로 읽히면 fail-closed 규칙이 거짓이 된다.

        prefix 매칭 정규식이면 통과한다 — codex 리뷰가 잡은 축.
        """
        rc, out = run(_lock(("weird", "1.2.3")), _lock(("weird", "1.2.3garbage")), capsys)
        assert rc == 1, out
        assert "unparseable" in out, out

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
        checkouts = [s for s in self._steps() if str(s.get("uses", "")).startswith("actions/checkout")]
        assert checkouts, "checkout 스텝이 없다 — 이 잠금이 공허해진다"
        for step in checkouts:
            with_ = step.get("with") or {}
            assert "ref" not in with_, f"checkout 에 ref 가 붙었다: {step}"
            assert "pull_request.head" not in str(with_), f"checkout 이 head 를 참조한다: {step}"

    def test_the_head_sha_is_only_ever_read_as_data(self):
        """head SHA 를 **읽는** 것은 안전하다 — 그 코드를 **실행**하는 것이 금지다.

        lock fetch 는 head SHA 로 파일 내용을 가져오고, enable 은 그 SHA 에 auto-merge 를
        묶는다. 둘 다 데이터 사용이다. 금지선은 위 `test_no_step_checks_out_pr_head` 다.
        """
        for step in self._steps():
            run = str(step.get("run", ""))
            for danger in ("uv sync", "uv lock", "uv run", "pip install"):
                assert danger not in run, f"가져온 lock 을 대상으로 {danger} 를 돌린다: {step}"

    def test_the_gate_step_is_not_conditional_or_soft(self):
        gate = next(s for s in self._steps() if "check_lock_major_bump.py" in str(s.get("run", "")))
        assert "if" not in gate, "게이트에 if 가 붙으면 조용히 안 돌 수 있다"
        assert not gate.get("continue-on-error"), "continue-on-error 는 게이트를 무력화한다"

    def test_enabling_is_bound_to_the_gated_head(self):
        """`expectedHeadOid` 없이 켜면 게이트가 판정하지 않은 head 에 무장될 수 있다."""
        enable = next(
            s for s in self._steps() if "enablePullRequestAutoMerge" in str(s.get("with", {}).get("script", ""))
        )
        script = str(enable["with"]["script"])
        assert "expectedHeadOid" in script, "enable 이 판정한 head 에 묶이지 않는다"
        assert "pull_request.head.sha" in script, "expectedHeadOid 에 실제 head SHA 를 안 넘긴다"

    def test_revocation_does_not_swallow_every_error(self):
        """모든 에러를 삼키면 fail-open 이다 — 인증/권한/네트워크 실패가 '해제됨' 이 된다.

        앞선 clean run 이 켜둔 auto-merge 가 살아남아 차단된 head 가 그대로 머지된다.
        """
        revoke = next(
            s for s in self._steps() if "disablePullRequestAutoMerge" in str(s.get("with", {}).get("script", ""))
        )
        script = str(revoke["with"]["script"])
        assert "core.setFailed" in script, "해제 실패를 조용히 넘긴다 — fail-open"
        assert "not enabled" in script, "'애초에 안 켜져 있었다' 만 통과시키는 분기가 없다"

    def test_revocation_runs_even_when_an_earlier_step_failed(self):
        """`if:` 에 상태 함수가 없으면 `success()` 가 암묵 포함된다 — 게이트가 죽으면

        해제 스텝이 통째로 스킵되고 앞선 run 이 켜둔 auto-merge 가 살아남는다.
        판정 부재는 통과가 아니다.
        """
        revoke = next(
            s for s in self._steps() if "disablePullRequestAutoMerge" in str(s.get("with", {}).get("script", ""))
        )
        assert "always()" in str(revoke.get("if", "")), (
            f"해제가 success() 에 묶여 있다 — 게이트 실패 시 스킵된다: {revoke.get('if')}"
        )

    def test_auto_merge_is_revoked_when_the_policy_says_no(self):
        """게이트가 막아도 **이전 run 이 켜둔** auto-merge 가 남아 있으면 그대로 머지된다.

        dependabot 이 rebase 로 force-push 하면 opened 시점의 판정이 살아남는다.
        """
        steps = self._steps()
        revoke = [s for s in steps if "disablePullRequestAutoMerge" in str(s.get("with", {}).get("script", ""))]
        assert revoke, "정책이 거부해도 기존 auto-merge 를 해제하지 않는다"
        assert "!= 'true'" in str(revoke[0].get("if", "")), f"해제 조건이 없다: {revoke[0].get('if')}"


class TestBlockingCiGate:
    """진짜 차단선 — auto-merge 워크플로는 '안 돌면 머지' 극성이라 그것만으로는 부족하다."""

    @staticmethod
    def _job() -> dict:
        wf = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "main-ci-cd.yml").read_text(encoding="utf-8"))
        return wf["jobs"]["lock-gate"]

    def test_the_job_exists_and_runs_the_gate(self):
        job = self._job()
        runs = " ".join(str(s.get("run", "")) for s in job["steps"])
        assert "check_lock_major_bump.py" in runs, "차단선 잡이 게이트를 안 부른다"

    def test_the_job_is_not_gated_on_changed_paths(self):
        """`needs: changes` 를 걸면 문서-only PR 에서 스킵돼 required check 가 불안정해진다.

        같은 함정을 privacy-scan 이 이미 피하고 있다.
        """
        assert "needs" not in self._job(), "경로 필터에 걸리면 required check 로 못 쓴다"

    def test_a_human_can_still_adopt_a_major_deliberately(self):
        """사람 PR 을 하드 블록하면 numpy 2 를 의도적으로 채택할 경로가 사라진다."""
        runs = " ".join(str(s.get("run", "")) for s in self._job()["steps"])
        assert "IS_DEPENDABOT" in runs, "dependabot 여부로 분기하지 않는다"
        assert "lock-bump-reviewed" in runs, "사람 검토 후 통과시킬 라벨 경로가 없다"

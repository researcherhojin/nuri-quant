"""CI-sourced duration ledger 병합의 fail-closed 성질을 잠근다 (#1414).

M5 직렬 실측 ledger 는 CI 런타임을 못 예측한다 (예측 spread 0.0s vs 실측 89s).
CI 실측으로 갈아타는 파이프라인에서 병합이 fail-open 이면 — shard 하나 누락,
snapshot 중복, 부분 실행 — 낡거나 빠진 값이 **조용히** ledger 가 되고, 그 결과는
빨간불이 아니라 다시 벌어지는 shard 불균형이라 아무도 눈치채지 못한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci.merge_test_durations import main

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestMergeFailClosed:
    def test_happy_path_merges_disjoint_shards(self, tmp_path, capsys):
        a = _write(tmp_path / "a.json", {"t::a": 1.0, "t::b": 2.0})
        b = _write(tmp_path / "b.json", {"t::c": 3.0})
        out = tmp_path / "out.json"

        assert main(["merge", "--expect-shards", "2", str(out), str(a), str(b)]) == 0

        assert json.loads(out.read_text()) == {"t::a": 1.0, "t::b": 2.0, "t::c": 3.0}

    def test_missing_shard_fails(self, tmp_path):
        """shard 하나가 빠지면 그 그룹 테스트 전체가 ledger 에서 사라진다 — 통과 금지."""
        a = _write(tmp_path / "a.json", {"t::a": 1.0})
        out = tmp_path / "out.json"

        with pytest.raises(SystemExit, match="누락"):
            main(["merge", "--expect-shards", "2", str(out), str(a)])
        assert not out.exists()

    def test_duplicate_node_id_fails(self, tmp_path):
        """중복 = --clean-durations 누락으로 stale snapshot 이 섞인 시그니처."""
        a = _write(tmp_path / "a.json", {"t::a": 1.0, "t::x": 5.0})
        b = _write(tmp_path / "b.json", {"t::x": 0.1})
        out = tmp_path / "out.json"

        with pytest.raises(SystemExit, match="중복"):
            main(["merge", "--expect-shards", "2", str(out), str(a), str(b)])
        assert not out.exists()

    def test_count_mismatch_fails(self, tmp_path):
        a = _write(tmp_path / "a.json", {"t::a": 1.0})
        b = _write(tmp_path / "b.json", {"t::b": 2.0})
        out = tmp_path / "out.json"

        with pytest.raises(SystemExit, match="union"):
            main(["merge", "--expect-shards", "2", "--expect-count", "3", str(out), str(a), str(b)])

    def test_empty_shard_file_fails(self, tmp_path):
        """빈 파일 = 부분 실행/손상. 0개 관측을 정상 shard 로 받으면 안 된다."""
        a = _write(tmp_path / "a.json", {})
        b = _write(tmp_path / "b.json", {"t::b": 2.0})
        out = tmp_path / "out.json"

        with pytest.raises(SystemExit, match="비어"):
            main(["merge", "--expect-shards", "2", str(out), str(a), str(b)])


class TestMedian:
    def test_median_across_runs(self, tmp_path):
        r1 = _write(tmp_path / "r1.json", {"t::a": 1.0, "t::b": 10.0})
        r2 = _write(tmp_path / "r2.json", {"t::a": 3.0, "t::b": 20.0})
        r3 = _write(tmp_path / "r3.json", {"t::a": 2.0})
        out = tmp_path / "out.json"

        assert main(["median", str(out), str(r1), str(r2), str(r3)]) == 0

        result = json.loads(out.read_text())
        assert result["t::a"] == 2.0
        assert result["t::b"] == 15.0  # 표본 2개면 평균 = median

    def test_single_run_is_refused(self, tmp_path):
        """단일 run 은 러너 노이즈를 그대로 싣는다 (codex consult 2026-09-02)."""
        r1 = _write(tmp_path / "r1.json", {"t::a": 1.0})

        with pytest.raises(SystemExit, match="2개 이상"):
            main(["median", str(tmp_path / "out.json"), str(r1)])

    def test_membership_is_anchored_to_the_newest_run(self, tmp_path):
        """삭제·개명된 테스트가 옛 run 을 타고 좀비로 남으면 안 된다 (codex P3-c).

        pytest-split 은 ledger 의 존재하지 않는 항목에도 시간을 배정한다 — stale
        node 는 값이 아니라 **불균형**으로 돌아온다.
        """
        newest = _write(tmp_path / "r1.json", {"t::kept": 1.0})
        old = _write(tmp_path / "r2.json", {"t::kept": 3.0, "t::renamed_away": 99.0})
        out = tmp_path / "out.json"

        main(["median", str(out), str(newest), str(old)])

        result = json.loads(out.read_text())
        assert "t::renamed_away" not in result, "옛 run 의 stale node 가 ledger 에 살아남았다"
        assert result["t::kept"] == 2.0


def _make_rundir(base: Path, name: str, shards: list[dict]) -> Path:
    rundir = base / name
    for i, data in enumerate(shards, 1):
        d = rundir / f"durations-fast-{i}"
        d.mkdir(parents=True)
        _write(d / ".test_durations", data)
    return rundir


class TestRefresh:
    """Makefile 레시피의 실행부를 종단으로 잠근다 (codex P2-2 — 셸 로직은 잠글 수 없다)."""

    def test_end_to_end_merges_medians_and_rounds(self, tmp_path):
        wf = _write_text(tmp_path / "wf.yml", "run: pytest --splits 2 --group 1\nrun: pytest --splits 9 slow\n")
        r1 = _make_rundir(tmp_path, "run1", [{"t::a": 1.23456789}, {"t::b": 2.0}])
        r2 = _make_rundir(tmp_path, "run2", [{"t::a": 3.0}, {"t::b": 4.0}])
        out = tmp_path / "ledger.json"

        assert main(["refresh", "--workflow", str(wf), "--out", str(out), str(r1), str(r2)]) == 0

        result = json.loads(out.read_text())
        assert result["t::a"] == pytest.approx(2.1173, abs=1e-4)
        # 4자리 반올림이 실제로 적용됐는지 — full-precision 은 privacy 스캐너에 걸린다
        assert all(len(str(v).split(".")[-1]) <= 4 for v in result.values()), result

    def test_newest_run_must_match_current_splits(self, tmp_path):
        """최신 run 이 현재 --splits 와 다르면 fail-closed — 누락 artifact 시그니처."""
        wf = _write_text(tmp_path / "wf.yml", "--splits 2")
        r1 = _make_rundir(tmp_path, "run1", [{"t::a": 1.0}])  # shard 1개뿐
        r2 = _make_rundir(tmp_path, "run2", [{"t::a": 2.0}, {"t::b": 1.0}])

        with pytest.raises(SystemExit, match="누락"):
            main(["refresh", "--workflow", str(wf), "--out", str(tmp_path / "o.json"), str(r1), str(r2)])

    def test_older_run_with_different_shard_count_still_contributes(self, tmp_path):
        """shard 수 전환기(6→8)에 refresh 가 마비되면 안 된다 (codex P3-b).

        membership 은 최신 run 이 정하므로 옛 run 의 수는 값 표본에만 영향을 준다.
        """
        wf = _write_text(tmp_path / "wf.yml", "--splits 2")
        r1 = _make_rundir(tmp_path, "run1", [{"t::a": 1.0}, {"t::b": 5.0}])
        r2 = _make_rundir(tmp_path, "run2", [{"t::a": 3.0, "t::b": 7.0}])  # 옛 1-shard run
        out = tmp_path / "o.json"

        main(["refresh", "--workflow", str(wf), "--out", str(out), str(r1), str(r2)])

        result = json.loads(out.read_text())
        assert result == {"t::a": 2.0, "t::b": 6.0}


def _write_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


class TestMakeTargetWiring:
    """Makefile 레시피가 refresh 로 위임하는지 잠근다 — 레시피에 로직이 돌아오면 잠금 밖이다.

    **Test:** tests/scripts/test_merge_test_durations.py::TestMakeTargetWiring::test_recipe_delegates_to_refresh
    """

    def test_recipe_delegates_to_refresh(self):
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        recipe = makefile.split("sync-test-durations-from-ci:")[1].split("\n\n")[0]

        assert "merge_test_durations.py refresh" in recipe, "레시피가 refresh 서브커맨드로 위임하지 않는다"
        assert "--workflow .github/workflows/main-ci-cd.yml" in recipe, (
            "expect-shards 출처가 워크플로가 아니다 — 다운로드 개수 도출(fail-open)이나 하드코딩(#1413)으로 회귀"
        )
        assert "-R " not in recipe, "repo 를 한쪽만 하드코딩하면 list/download 가 다른 repo 를 볼 수 있다 (codex P2-1)"


class TestWorkflowWiring:
    """스크립트 단위 테스트는 배선을 안 잠근다 — 워크플로가 실제로 기록하는지를 본다.

    **Test:** tests/scripts/test_merge_test_durations.py::TestWorkflowWiring::test_shards_record_and_upload_durations_on_push
    """

    def test_shards_record_and_upload_durations_on_push(self):
        text = (REPO_ROOT / ".github" / "workflows" / "main-ci-cd.yml").read_text(encoding="utf-8")

        assert "STORE_DURATION_FLAGS=--store-durations --clean-durations" in text, (
            "duration 기록 arm step 이 사라졌다 — CI 실측 ledger 의 공급이 끊긴다. "
            "--clean-durations 가 빠지면 shard 가 full snapshot 을 써서 병합의 중복 검증이 그걸 잡는다"
        )
        # 텍스트 전체 검색은 안 된다 — 같은 문자열이 주석에도 있어 명령에서 빠져도
        # 통과한다 (뮤테이션 실측: 명령에서만 제거 시 PASS). YAML 을 파싱해 실제
        # run 명령만 본다.
        import yaml

        wf = yaml.safe_load(text)
        steps = wf["jobs"]["backend-tests-shard"]["steps"]
        pytest_cmds = [s.get("run", "") for s in steps if s.get("name") == "Run fast tests with coverage"]
        assert len(pytest_cmds) == 1, "fast shard pytest step 을 못 찾았다"
        assert "$STORE_DURATION_FLAGS" in pytest_cmds[0], (
            "pytest 명령이 arm 된 플래그를 실제로 쓰지 않는다 — 기록이 조용히 no-op (주석의 언급은 배선이 아니다)"
        )
        assert "durations-fast-${{ matrix.shard }}" in text, "shard duration artifact 업로드가 사라졌다"

    def test_upload_is_push_only_and_success_only(self):
        """PR 에서 업로드하면 브랜치 상태가, 빨간 run 이면 부분 실행이 ledger 에 섞인다.

        `!= 'pull_request'` 가 아니라 `== 'push'` 다 — 전자는 workflow_dispatch 도
        기록해 "push-to-main 실측" 이라는 계약과 어긋난다 (codex P3-e).
        """
        text = (REPO_ROOT / ".github" / "workflows" / "main-ci-cd.yml").read_text(encoding="utf-8")
        upload_block = text.split("Upload shard durations")[1][:400]

        assert "github.event_name == 'push'" in upload_block
        assert "success()" in upload_block

"""`scripts/ci/patch_coverage_gate.py` — CI 안에서 codecov.yml 의 patch target 을 강제한다 (#1766).

함수를 import 하지 않고 **스크립트를 실행**한다. 임시 git 레포에 base·head 커밋을 만들고, Codecov 가 받는
것과 같은 모양의 입력 — coverage.py Cobertura XML(`<source>nuri</source>` 기준 파일명) · vitest v8 lcov
(BRDA 포함) — 을 써서 exit code 와 출력을 본다.

셈은 Codecov 와 같아야 한다. 실데이터 재생(#1735 → 1621 hit / 208 miss / 161 partial, 81.45% · #1758 ·
#1762 · #1765)에서 줄 단위까지 맞춘 규칙 둘을 여기서 잠근다:

- Cobertura 파일명은 `<source>` 기준이다. 이어 붙이지 않으면 어떤 줄도 매칭되지 않아 "영향 없음" 으로
  **통과한다** — 게이트가 조용히 죽는 형태다.
- lcov 의 분기 줄은 분기 비율이 결정한다. DA 가 0 이어도 탄 분기가 있으면 partial 이다.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "scripts" / "ci" / "patch_coverage_gate.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "main-ci-cd.yml"

POLICY = """coverage:
  status:
    patch:
      default:
        target: {target}
        threshold: 0%
ignore:
  - "frontend/src/__tests__/**"
  - "tests/**"
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=gate@example.com", "-c", "user.name=gate", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """base 커밋: nuri/mod.py 10줄 · frontend/src/view.ts 6줄. 테스트가 head 커밋에서 줄을 바꾼다."""
    root = tmp_path / "repo"
    (root / "nuri").mkdir(parents=True)
    (root / "frontend" / "src").mkdir(parents=True)
    (root / "codecov.yml").write_text(POLICY.format(target="100%"))
    (root / "nuri" / "mod.py").write_text("".join(f"value_{i} = {i}\n" for i in range(1, 11)))
    (root / "frontend" / "src" / "view.ts").write_text("".join(f"export const v{i} = {i};\n" for i in range(1, 7)))
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


def _head(repo: Path, changes: dict[str, list[int]]) -> None:
    """head 커밋 — 주어진 파일의 줄 번호를 고쳐 쓴다. 그 줄들이 patch 다."""
    for rel, numbers in changes.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = path.read_text().splitlines(keepends=True) if path.exists() else []
        for number in numbers:
            lines.extend(["\n"] * (number - len(lines)))
            lines[number - 1] = f"changed_{number} = 0\n"
        path.write_text("".join(lines))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "head")


def _cobertura(repo: Path, states: dict[int, str], *, filename: str = "mod.py", source: str = "nuri") -> Path:
    """coverage.py 모양의 XML — 파일명은 `<source>` 기준이다 (`--cov=nuri` 와 같다)."""
    rows = []
    for number in range(1, 11):
        state = states.get(number, "hit")
        if state == "miss":
            rows.append(f'<line number="{number}" hits="0"/>')
        elif state == "partial":
            rows.append(f'<line number="{number}" hits="1" branch="true" condition-coverage="50% (1/2)"/>')
        else:
            rows.append(f'<line number="{number}" hits="1"/>')
    out = repo.parent / "coverage.xml"
    out.write_text(
        '<?xml version="1.0" ?><coverage><sources>'
        f'<source>{source}</source></sources><packages><package name="."><classes>'
        f'<class name="{filename}" filename="{filename}"><methods/><lines>{"".join(rows)}</lines></class>'
        "</classes></package></packages></coverage>"
    )
    return out


def _lcov(
    repo: Path, hits: dict[int, int], branches: dict[int, list[str]] | None = None, *, sf: str = "frontend/src/view.ts"
) -> Path:
    """vitest v8 모양의 lcov — SF 는 CI 가 고쳐 쓴 레포 기준 경로다."""
    rows = ["TN:", f"SF:{sf}"]
    rows += [f"DA:{number},{hits.get(number, 1)}" for number in range(1, 7)]
    for number, taken in (branches or {}).items():
        rows += [f"BRDA:{number},0,{index},{count}" for index, count in enumerate(taken)]
    rows.append("end_of_record")
    out = repo.parent / "lcov.info"
    out.write_text("\n".join(rows) + "\n")
    return out


def _gate(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATE), "--base", "HEAD^1", *args], cwd=repo, capture_output=True, text=True
    )


class TestBackendCoverage:
    def test_every_changed_line_hit_passes(self, repo):
        _head(repo, {"nuri/mod.py": [3, 4]})
        result = _gate(repo, "--coverage-xml", str(_cobertura(repo, {})))
        assert result.returncode == 0, result.stdout
        assert "100.00% — 2 hit, 0 miss, 0 partial of 2 lines" in result.stdout

    def test_a_missed_changed_line_fails_and_is_annotated(self, repo):
        """파일명을 `<source>` 와 이어 붙여야 이 miss 가 보인다 — 안 붙이면 "영향 없음" 으로 통과한다."""
        _head(repo, {"nuri/mod.py": [3, 4]})
        result = _gate(repo, "--coverage-xml", str(_cobertura(repo, {4: "miss"})))
        assert result.returncode == 1, result.stdout
        assert "50.00% — 1 hit, 1 miss, 0 partial of 2 lines" in result.stdout
        assert "::error file=nuri/mod.py,line=4::changed line not covered (miss)" in result.stdout

    def test_a_partial_branch_is_not_a_hit(self, repo):
        _head(repo, {"nuri/mod.py": [3]})
        result = _gate(repo, "--coverage-xml", str(_cobertura(repo, {3: "partial"})))
        assert result.returncode == 1, result.stdout
        assert "::error file=nuri/mod.py,line=3::changed line not covered (partial)" in result.stdout

    def test_an_absolute_source_maps_back_to_the_repo_path(self, repo):
        """`relative_files` 를 끄면 coverage.py 가 절대 경로 source 를 쓴다 — 그래도 레포 경로로 맞춘다."""
        _head(repo, {"nuri/mod.py": [5]})
        report = _cobertura(repo, {5: "miss"}, source=str(repo / "nuri"))
        result = _gate(repo, "--coverage-xml", str(report))
        assert result.returncode == 1, result.stdout
        assert "::error file=nuri/mod.py,line=5::" in result.stdout

    def test_uncovered_lines_outside_the_patch_do_not_count(self, repo):
        _head(repo, {"nuri/mod.py": [3]})
        result = _gate(repo, "--coverage-xml", str(_cobertura(repo, {8: "miss", 9: "partial"})))
        assert result.returncode == 0, result.stdout
        assert "1 hit, 0 miss, 0 partial of 1 lines" in result.stdout

    def test_ignored_paths_do_not_count(self, repo):
        """codecov.yml 의 `ignore` 를 따른다 — Codecov 가 리포트에서 지우는 경로는 patch 에도 없다."""
        _head(repo, {"tests/test_mod.py": [2]})
        report = _cobertura(repo, {2: "miss"}, filename="tests/test_mod.py", source=".")
        result = _gate(repo, "--coverage-xml", str(report))
        assert result.returncode == 0, result.stdout
        assert "patch coverage not affected" in result.stdout


class TestFrontendCoverage:
    def test_a_branch_line_with_a_taken_branch_is_partial_even_when_da_is_zero(self, repo):
        """#1735 재생에서 어긋났던 13줄의 모양 — DA 0, 분기 하나가 12번 탔다. Codecov 는 partial 로 센다."""
        _head(repo, {"frontend/src/view.ts": [2]})
        result = _gate(repo, "--lcov", str(_lcov(repo, {2: 0}, {2: ["0", "12", "0", "0"]})))
        assert result.returncode == 1, result.stdout
        assert "0 hit, 0 miss, 1 partial of 1 lines" in result.stdout
        assert "::error file=frontend/src/view.ts,line=2::changed line not covered (partial)" in result.stdout

    def test_a_branch_line_with_no_branch_taken_is_a_miss(self, repo):
        _head(repo, {"frontend/src/view.ts": [2]})
        result = _gate(repo, "--lcov", str(_lcov(repo, {2: 1}, {2: ["-", "0"]})))
        assert result.returncode == 1, result.stdout
        assert "0 hit, 1 miss, 0 partial of 1 lines" in result.stdout

    def test_a_branch_line_with_every_branch_taken_is_a_hit(self, repo):
        _head(repo, {"frontend/src/view.ts": [2]})
        result = _gate(repo, "--lcov", str(_lcov(repo, {2: 0}, {2: ["3", "2"]})))
        assert result.returncode == 0, result.stdout
        assert "1 hit, 0 miss, 0 partial of 1 lines" in result.stdout

    def test_an_added_line_that_starts_with_plus_plus_is_not_a_file_header(self, repo):
        """`++ counter;` 를 더하면 diff 에 `+++ counter;` 로 찍힌다 — 헤더로 읽으면 뒤 hunk 의 miss 가 빠진다."""
        path = repo / "frontend" / "src" / "view.ts"
        lines = path.read_text().splitlines(keepends=True)
        lines[1], lines[4] = "++ counter;\n", "export const changed = 5;\n"
        path.write_text("".join(lines))
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "two hunks, the first adds a ++ line")
        result = _gate(repo, "--lcov", str(_lcov(repo, {5: 0})))
        assert result.returncode == 1, result.stdout
        assert "1 hit, 1 miss, 0 partial of 2 lines" in result.stdout
        assert "::error file=frontend/src/view.ts,line=5::" in result.stdout

    @pytest.mark.parametrize(
        "decoy",
        [
            "// \x00 a NUL makes git call the file binary",
            "//\x0bdiff --git a/decoy.ts b/decoy.ts",
            "//\rdiff --git a/decoy.ts b/decoy.ts",
        ],
        ids=[
            "NUL byte (binary detection)",
            "vertical tab (splitlines boundary)",
            "bare carriage return (text-mode newline translation)",
        ],
    )
    def test_content_that_could_hide_a_later_hunk_does_not(self, repo, decoy):
        """본문의 NUL 은 파일을 바이너리로 접고, \\x0b 는 splitlines() 경계가 된다 — 둘 다 뒤 hunk 의 miss 를 지웠다."""
        path = repo / "frontend" / "src" / "view.ts"
        lines = path.read_text().splitlines(keepends=True)
        lines[1], lines[4] = decoy + "\n", "export const changed = 5;\n"
        path.write_text("".join(lines))
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "a decoy line before an uncovered hunk")
        result = _gate(repo, "--lcov", str(_lcov(repo, {5: 0})))
        assert result.returncode == 1, result.stdout
        assert "::error file=frontend/src/view.ts,line=5::" in result.stdout

    def test_a_plain_line_follows_its_da_count(self, repo):
        _head(repo, {"frontend/src/view.ts": [4, 5]})
        result = _gate(repo, "--lcov", str(_lcov(repo, {4: 0, 5: 7})))
        assert result.returncode == 1, result.stdout
        assert "1 hit, 1 miss, 0 partial of 2 lines" in result.stdout

    @pytest.mark.parametrize(
        "name",
        ["caf\u00e9.ts", 'quo"te.ts', "with space.ts", "line\u2028sep.ts"],
        ids=[
            "non-ascii (git quotes it by default)",
            "double quote (quoted even with quotePath=false)",
            "space (git appends a delimiter tab to the +++ line)",
            "U+2028 (a splitlines boundary inside the lcov SF path)",
        ],
    )
    def test_a_filename_git_would_quote_still_matches_the_report(self, repo, name):
        """인용된 경로를 그대로 비교하면 그 파일의 miss 가 통째로 빠진다 — 거짓 초록 (Codex 리뷰)."""
        path = f"frontend/src/{name}"
        (repo / path).write_text("".join(f"export const w{i} = {i};\n" for i in range(1, 7)))
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "add a file git quotes")
        _head(repo, {path: [3]})
        result = _gate(repo, "--lcov", str(_lcov(repo, {3: 0}, sf=path)))
        assert result.returncode == 1, result.stdout
        assert f"::error file={path},line=3::" in result.stdout


class TestPolicyAndInputs:
    def test_backend_and_frontend_reports_are_counted_together(self, repo):
        _head(repo, {"nuri/mod.py": [1], "frontend/src/view.ts": [1]})
        result = _gate(repo, "--coverage-xml", str(_cobertura(repo, {1: "miss"})), "--lcov", str(_lcov(repo, {1: 3})))
        assert result.returncode == 1, result.stdout
        assert "1 hit, 1 miss, 0 partial of 2 lines" in result.stdout

    def test_a_change_outside_the_coverage_report_is_not_affected(self, repo):
        _head(repo, {"README.md": [1]})
        result = _gate(repo, "--coverage-xml", str(_cobertura(repo, {1: "miss"})))
        assert result.returncode == 0, result.stdout
        assert "✓ no changed line is in the coverage report — patch coverage not affected" in result.stdout

    def test_the_target_comes_from_codecov_yml(self, repo):
        (repo / "codecov.yml").write_text(POLICY.format(target="50%"))
        _head(repo, {"nuri/mod.py": [3, 4]})
        result = _gate(repo, "--coverage-xml", str(_cobertura(repo, {4: "miss"})))
        assert result.returncode == 0, result.stdout
        assert "(target 50%, threshold 0%)" in result.stdout

    def test_a_non_numeric_target_is_refused(self, repo):
        """`target: auto` 는 base 커버리지가 필요하다 — 조용히 100% 로 바꿔 읽지 않고 거부한다."""
        (repo / "codecov.yml").write_text(POLICY.format(target="auto"))
        _head(repo, {"nuri/mod.py": [3]})
        result = _gate(repo, "--coverage-xml", str(_cobertura(repo, {})))
        assert result.returncode != 0
        assert "patch target must be a percentage" in result.stdout + result.stderr

    def test_coverage_is_rounded_down_like_codecov(self, repo):
        """Codecov 기본값(round: down, precision 2) — #1735 는 81.457% 를 81.45% 로 보고했다."""
        _head(repo, {"nuri/mod.py": [1, 2, 3]})
        result = _gate(repo, "--coverage-xml", str(_cobertura(repo, {3: "miss"})))
        assert "patch coverage 66.66%" in result.stdout

    def test_a_missing_coverage_file_fails_closed_even_when_the_other_side_is_fine(self, repo):
        """한쪽 입력이 없으면 남은 쪽만으로 세지 않는다 — 반쪽 입력의 "통과" 는 판정이 아니다."""
        _head(repo, {"frontend/src/view.ts": [2]})
        result = _gate(repo, "--coverage-xml", str(repo.parent / "absent.xml"), "--lcov", str(_lcov(repo, {})))
        assert result.returncode == 1
        assert "::error::backend coverage file missing" in result.stdout
        assert "patch coverage" not in result.stdout

    def test_no_coverage_input_fails_closed(self, repo):
        _head(repo, {"nuri/mod.py": [3]})
        result = _gate(repo)
        assert result.returncode == 1
        assert "::error::no coverage input" in result.stdout


class TestWorkflowWiring:
    """스크립트 테스트는 배선을 잠그지 않는다 — 잡을 지우거나 입력 경로가 어긋나면 위는 전부 초록이다."""

    @staticmethod
    def _jobs() -> dict:
        return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]

    @staticmethod
    def _step(job: dict, needle: str) -> tuple[int, dict]:
        for index, step in enumerate(job["steps"]):
            if needle in str(step):
                return index, step
        raise AssertionError(f"no step mentions {needle!r}")

    def test_the_gate_job_runs_after_both_producers_even_when_they_are_skipped(self):
        job = self._jobs()["patch-coverage"]
        assert job["name"] == "Patch Coverage"
        assert {"changes", "frontend-tests", "backend-tests", "backend-coverage-merge"} <= set(job["needs"])
        assert "!cancelled()" in str(job["if"])

    def test_the_frontend_lcov_is_kept_after_its_paths_are_rewritten(self):
        """SF 를 레포 기준으로 고치기 **전에** 올리면 어떤 줄도 매칭되지 않아 게이트가 조용히 통과한다."""
        job = self._jobs()["frontend-tests"]
        rewrite, _ = self._step(job, "SF:frontend/src/")
        upload, step = self._step(job, "frontend-lcov")
        assert rewrite < upload
        assert step["with"]["path"] == "frontend/coverage/lcov.info"

    def test_the_backend_coverage_xml_is_kept_after_it_is_combined(self):
        job = self._jobs()["backend-coverage-merge"]
        combine, _ = self._step(job, "coverage xml -o coverage.xml")
        upload, step = self._step(job, "backend-coverage-xml")
        assert combine < upload
        assert step["with"]["path"] == "coverage.xml"

    def test_the_gate_reads_what_the_producers_keep(self):
        job = self._jobs()["patch-coverage"]
        _, frontend = self._step(job, "frontend-lcov")
        _, backend = self._step(job, "backend-coverage-xml")
        _, run = self._step(job, "patch_coverage_gate.py")
        assert f"--lcov {frontend['with']['path']}/lcov.info" in run["run"]
        assert f"--coverage-xml {backend['with']['path']}/coverage.xml" in run["run"]

    def test_measurement_is_limited_to_pull_requests_that_produced_coverage(self):
        """MEASURE 를 false 로 굳히면 모든 PR 이 skip notice 로 통과한다 — 조건의 세 축을 잠근다."""
        job = self._jobs()["patch-coverage"]
        measure = job["env"]["MEASURE"]
        for term in (
            "github.event_name == 'pull_request'",
            "needs.changes.outputs.run_backend == 'true'",
            "needs.changes.outputs.run_frontend == 'true'",
        ):
            assert term in measure, term
        _, check = self._step(job, "patch_coverage_gate.py")
        assert check["if"].startswith("env.MEASURE == 'true'")

    PRODUCER_CASES = {
        "both sides ran and succeeded": ("true", "true", "success", "success", "success", 0),
        # Codex 리뷰: Aggregate 는 남은 artifact 로 합쳐 성공한다 — 샤드 결과는 Backend Tests 에만 있다
        "a backend shard failed while the aggregate merged the rest": (
            "false",
            "true",
            "skipped",
            "failure",
            "success",
            1,
        ),
        "the aggregate itself failed": ("false", "true", "skipped", "success", "failure", 1),
        "frontend tests failed": ("true", "false", "failure", "success", "skipped", 1),
        "frontend-only PR with backend skipped": ("true", "false", "success", "success", "skipped", 0),
        "backend-only PR with the frontend skip notice": ("false", "true", "success", "success", "success", 0),
    }

    @pytest.mark.parametrize("case", list(PRODUCER_CASES))
    def test_the_producer_guard_refuses_partial_coverage(self, case):
        """가드 스텝 본문을 실제로 돌린다 — `${{ }}` 를 값으로 바꾸고 GitHub 처럼 `bash -e` 로."""
        run_frontend, run_backend, frontend, backend_tests, aggregate, expected = self.PRODUCER_CASES[case]
        values = {
            "needs.changes.outputs.run_frontend": run_frontend,
            "needs.changes.outputs.run_backend": run_backend,
            "needs.frontend-tests.result": frontend,
            "needs.backend-tests.result": backend_tests,
            "needs.backend-coverage-merge.result": aggregate,
        }
        _, step = self._step(self._jobs()["patch-coverage"], "Require the coverage producers to succeed")
        script = re.sub(r"\$\{\{\s*([^}]+?)\s*\}\}", lambda match: values[match.group(1)], step["run"])
        result = subprocess.run(["bash", "-e", "-c", script], capture_output=True, text=True)
        assert result.returncode == expected, result.stdout + result.stderr

    def test_the_checkout_keeps_the_merge_commits_first_parent(self):
        """기본 diff 기준이 HEAD^1 이다 — 깊이 1 로 받으면 부모가 없어 git diff 가 죽는다."""
        job = self._jobs()["patch-coverage"]
        _, checkout = self._step(job, "actions/checkout")
        assert checkout["with"]["fetch-depth"] >= 2

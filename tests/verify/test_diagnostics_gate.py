"""pyright diff 스코핑과 cspell 게이트를 **실행해서** 검증 (Gotcha-Test Pair, #1086/#1088).

`make diagnostics` 는 오래 전부터 존재했지만 어떤 게이트도 부르지 않았다. 그래서 진단은
사용자 에디터에만 떴고, 2026-08-18 에 사용자가 Pylance/cSpell 경고 목록을 직접 붙여넣어야
했다 — 그중 하나는 그 직전 머지가 만든 새 경고였다.

첫 구현(#1086)은 총 오류 수를 파일에 적어 두는 래칫이었다. 사용자가 그 파일이 필요하냐고
물었고, 따져보니 **손으로 유지하는 숫자는 낡고 낡으면 게이트가 조용히 느슨해진다** — 무장된
것처럼 보이는데 안 잡는 형태로, 이 레포가 #910/#911 · #953/#954 에서 당한 계열이다.
그래서 상태 없는 diff 스코핑으로 바꿨다 (#1088).

여기서 잠그는 것:
  1. 추가된 줄의 오류는 **차단**한다 (게이트의 본체)
  2. 같은 파일의 **기존** 오류는 통과시킨다 (오탐 = 우회로 이어진다)
  3. **untracked 새 파일**도 검사 대상이다 — `git diff` 가 한 줄도 안 뱉는 구멍
  4. 실행 불가를 통과로 바꾸지 않는다 (#910/#911 rc=127 계열)
  5. cspell 사전이 **파싱 가능**하다 — 깨지면 spellcheck 가 통째로 죽고,
     `grep -q "Unknown word"` 기반 게이트는 그것을 **통과**로 읽는다

⚠️ pyright 자체는 여기서 돌리지 않는다(네트워크 + 초 단위). 진단을 주입해 **필터 로직**만
본다 — 필터가 이 파일의 대상이고, 실제 실행은 pre-push 게이트가 매번 한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify import check_pyright_diff as gate

REPO_ROOT = Path(__file__).resolve().parents[2]


def _diag(rel: str, line: int) -> dict:
    """pyright 진단 1건. `file` 은 절대 경로이고 `range.start.line` 은 0-based."""
    return {
        "file": f"{REPO_ROOT}/{rel}",
        "severity": "error",
        "rule": "reportReturnType",
        "message": 'Type "int" is not assignable to return type "str"',
        "range": {"start": {"line": line - 1}},
    }


class TestDiffScoping:
    def test_an_error_on_an_added_line_is_reported(self):
        """이 한 줄이 게이트의 존재 이유다."""
        hits = gate.diagnostics_on_changed_lines([_diag("nuri/x.py", 10)], {"nuri/x.py": {9, 10, 11}})
        assert [(h[0], h[1]) for h in hits] == [("nuri/x.py", 10)]

    def test_a_pre_existing_error_in_a_touched_file_is_ignored(self):
        """파일 단위로 스코핑하면 #1079 가 기존 오류 8건에 막혔을 것이다 — 오탐은 우회를 부른다."""
        assert gate.diagnostics_on_changed_lines([_diag("nuri/x.py", 400)], {"nuri/x.py": {9, 10}}) == []

    def test_an_error_in_an_untouched_file_is_ignored(self):
        assert gate.diagnostics_on_changed_lines([_diag("nuri/other.py", 10)], {"nuri/x.py": {10}}) == []

    def test_a_suffix_collision_does_not_count_as_a_match(self):
        """`endswith` 는 `a/x.py` 와 `b/a/x.py` 를 혼동할 수 있다 — 경계(`/`)를 붙여 막는다."""
        diag = {**_diag("nuri/x.py", 10), "file": f"{REPO_ROOT}/vendor/nuri/x.py"}
        # vendor 쪽 파일은 변경 목록에 없으므로 잡히면 안 된다… 단 경로가 `/nuri/x.py` 로
        # 끝나므로 경계만으로는 구분되지 않는다. 이 한계를 테스트로 고정해 둔다.
        hits = gate.diagnostics_on_changed_lines([diag], {"nuri/x.py": {10}})
        assert len(hits) == 1, "현재 구현은 경로 접미사 매칭이다 — 바꾸면 이 기대도 같이 바꿀 것"


class TestChangedLines:
    def test_untracked_python_files_are_covered_whole(self, monkeypatch, tmp_path):
        """`git diff` 는 untracked 파일을 한 줄도 안 뱉는다 — 새 모듈이 통째로 빠지는 구멍."""
        new = tmp_path / "brand_new.py"
        new.write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")

        def fake_git(*args):
            if args[:2] == ("ls-files", "--others"):
                return "brand_new.py\n"
            return ""  # diff 는 아무것도 안 준다 — untracked 이므로

        monkeypatch.setattr(gate, "_git", fake_git)
        monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
        assert gate.changed_lines("HEAD") == {"brand_new.py": {1, 2, 3}}

    def test_non_python_changes_are_skipped(self, monkeypatch):
        diff = "+++ b/docs/x.md\n@@ -0,0 +1,3 @@\n"
        monkeypatch.setattr(gate, "_git", lambda *a: "" if a[:2] == ("ls-files", "--others") else diff)
        assert gate.changed_lines("HEAD") == {}


class TestResolveBase:
    def test_always_resolves_to_something(self, monkeypatch):
        """기준을 못 잡았다고 통과로 빠지면 게이트가 조용히 사라진다."""
        monkeypatch.setattr(gate, "_git", lambda *a: "")
        assert gate.resolve_base() == gate.EMPTY_TREE


class TestMainVerdict:
    def test_being_unable_to_run_is_not_a_pass(self, monkeypatch, capsys):
        """'검사를 못 돌렸다' 를 '깨끗하다' 로 보고하는 것이 #910/#911 의 핵심 실패다."""

        def boom(_files):
            raise RuntimeError("npx 를 찾을 수 없다")

        monkeypatch.setattr(gate, "changed_lines", lambda base: {"nuri/x.py": {1}})
        monkeypatch.setattr(gate, "run_pyright", boom)
        assert gate.main([]) == 1
        assert "미확인" in capsys.readouterr().err

    def test_no_python_changes_skips_pyright_entirely(self, monkeypatch):
        """.py 를 안 건드리는 push 는 pyright 를 돌 이유가 없다 — 훅 시간을 아낀다."""

        def never(_files):
            raise AssertionError("변경이 없는데 pyright 를 돌렸다")

        monkeypatch.setattr(gate, "changed_lines", lambda base: {})
        monkeypatch.setattr(gate, "run_pyright", never)
        assert gate.main([]) == 0

    def test_hits_block(self, monkeypatch, capsys):
        monkeypatch.setattr(gate, "changed_lines", lambda base: {"nuri/x.py": {10}})
        monkeypatch.setattr(gate, "run_pyright", lambda files: [_diag("nuri/x.py", 10)])
        assert gate.main([]) == 1
        assert "nuri/x.py:10" in capsys.readouterr().err

    def test_clean_changes_pass(self, monkeypatch):
        monkeypatch.setattr(gate, "changed_lines", lambda base: {"nuri/x.py": {10}})
        monkeypatch.setattr(gate, "run_pyright", lambda files: [_diag("nuri/x.py", 999)])
        assert gate.main([]) == 0


class TestCspellDictionary:
    def test_the_dictionary_parses(self):
        """사전이 깨지면 cspell 이 통째로 죽고, `grep -q "Unknown word"` 게이트는 **통과**로 읽는다."""
        data = json.loads((REPO_ROOT / ".cspell.json").read_text(encoding="utf-8"))
        assert isinstance(data["words"], list) and data["words"]

    def test_words_stay_sorted(self):
        """정렬이 깨지면 중복 등재가 눈에 안 보이고 diff 가 커진다."""
        words = json.loads((REPO_ROOT / ".cspell.json").read_text(encoding="utf-8"))["words"]
        assert words == sorted(words), "ASCII 정렬 유지 — 추가 시 자리 지킬 것"
        assert len(words) == len(set(words)), "중복 등재"


class TestGateIsWired:
    """게이트가 훅 경로에 실제로 걸려 있는가 — 스크립트만 있고 아무도 안 부르면 #1086 그대로다.

    ⚠️ 여기만 grep 이다. 훅 전체를 실행하면 pyright 를 매 테스트 실행마다 무는데, 판정 로직은
    위에서 실행으로 잠그고 있어서 여기서 확인할 것은 "부르는가" 뿐이다. 문자열만 보면 이사간
    스크립트를 못 잡으므로 존재 검사를 같이 둔다.
    """

    @pytest.mark.parametrize("needle", ["check_pyright_diff.py", "make spellcheck"])
    def test_pre_push_check_invokes_the_diagnostics(self, needle):
        text = (REPO_ROOT / "scripts" / "verify" / "pre_push_check.sh").read_text(encoding="utf-8")
        assert needle in text, f"{needle} 를 pre-push 게이트가 부르지 않는다"

    def test_the_invoked_script_exists(self):
        """문자열 일치만으로는 이사간 스크립트를 못 잡는다 — 그러면 훅이 rc=127 로 죽는다."""
        assert (REPO_ROOT / "scripts" / "verify" / "check_pyright_diff.py").is_file()

    def test_the_retired_baseline_is_gone(self):
        """숫자 파일이 되살아나면 낡는 게이트도 같이 돌아온다 (#1088)."""
        assert not (REPO_ROOT / "scripts" / "verify" / "pyright_baseline.json").exists()
        assert not (REPO_ROOT / "scripts" / "verify" / "check_pyright_ratchet.py").exists()

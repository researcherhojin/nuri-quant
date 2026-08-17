"""pyright 래칫과 cspell 게이트를 **실행해서** 검증 (Gotcha-Test Pair, #1086).

`make diagnostics` 는 오래 전부터 존재했지만 어떤 게이트도 부르지 않았다. 그래서 진단은
사용자 에디터에만 떴고, 2026-08-18 에 사용자가 Pylance/cSpell 경고 목록을 직접 붙여넣어야
했다 — 그중 하나는 그 직전 머지가 만든 새 경고였다.

여기서 잠그는 것:
  1. 래칫이 **넘으면 차단**한다 (회귀 방지의 본체)
  2. 래칫이 **같거나 적으면 통과**한다 (상시 red 는 곧 우회다)
  3. 래칫이 **실행 불가를 통과로 바꾸지 않는다** (#910/#911 rc=127 계열)
  4. baseline 파일이 실제 측정값과 형식을 갖추고 있다
  5. cspell 사전이 **파싱 가능**하다 — 깨지면 spellcheck 가 통째로 죽고,
     `grep -q "Unknown word"` 기반 게이트는 그것을 **통과**로 읽는다

⚠️ pyright 자체는 여기서 돌리지 않는다(9.3s + 네트워크). `run_pyright` 를 대체해
래칫의 **판정 로직**만 본다 — 판정이 이 파일의 대상이고, pyright 실행은 pre-push 게이트가
매번 한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify import check_pyright_ratchet as ratchet

REPO_ROOT = Path(__file__).resolve().parents[2]


def _diags(n: int) -> list[dict]:
    return [{"file": f"{REPO_ROOT}/nuri/x{i % 3}.py", "severity": "error"} for i in range(n)]


class TestRatchetVerdict:
    def test_more_than_baseline_blocks(self, monkeypatch, capsys):
        """이 한 줄이 게이트의 존재 이유다 — 늘리면 막힌다."""
        monkeypatch.setattr(ratchet, "_load_baseline", lambda: 172)
        monkeypatch.setattr(ratchet, "run_pyright", lambda: _diags(173))
        assert ratchet.main([]) == 1
        assert "1건 늘렸다" in capsys.readouterr().err

    def test_equal_to_baseline_passes(self, monkeypatch):
        """상시 red 는 우회를 부른다 — 소음 바닥 그대로면 통과해야 한다."""
        monkeypatch.setattr(ratchet, "_load_baseline", lambda: 172)
        monkeypatch.setattr(ratchet, "run_pyright", lambda: _diags(172))
        assert ratchet.main([]) == 0

    def test_fewer_than_baseline_passes_and_says_how_to_lock_it_in(self, monkeypatch, capsys):
        """줄었을 때 FAIL 시키지 않는 대신, 되돌림을 막는 방법을 크게 찍는다."""
        monkeypatch.setattr(ratchet, "_load_baseline", lambda: 172)
        monkeypatch.setattr(ratchet, "run_pyright", lambda: _diags(170))
        assert ratchet.main([]) == 0
        out = capsys.readouterr().out
        assert "2건 감소" in out
        assert "pyright_baseline.json" in out

    def test_being_unable_to_run_is_not_a_pass(self, monkeypatch, capsys):
        """'검사를 못 돌렸다' 를 '깨끗하다' 로 보고하는 것이 #910/#911 의 핵심 실패다."""

        def boom():
            raise RuntimeError("npx 를 찾을 수 없다")

        monkeypatch.setattr(ratchet, "_load_baseline", lambda: 172)
        monkeypatch.setattr(ratchet, "run_pyright", boom)
        assert ratchet.main([]) == 1
        assert "미확인" in capsys.readouterr().err


class TestBaselineFile:
    def test_baseline_is_a_measured_number_with_its_provenance(self):
        """숫자만 있으면 다음 사람이 '이게 목표치인가 바닥인가' 를 못 판단한다."""
        data = json.loads(ratchet.BASELINE_PATH.read_text(encoding="utf-8"))
        assert isinstance(data["errors"], int) and data["errors"] >= 0
        assert data["measured_on"], "언제 잰 값인지 없으면 낡았는지 알 수 없다"
        assert data["note"], "왜 0 이 아닌지 적혀 있지 않으면 다음 사람이 목표치로 오해한다"


class TestCspellDictionary:
    def test_the_dictionary_parses(self):
        """사전이 깨지면 cspell 이 통째로 죽고, `grep -q "Unknown word"` 게이트는 **통과**로 읽는다.

        게이트가 조용히 무력해지는 경로라 사전 자체를 잠근다.
        """
        data = json.loads((REPO_ROOT / ".cspell.json").read_text(encoding="utf-8"))
        assert isinstance(data["words"], list) and data["words"]

    def test_words_stay_sorted(self):
        """정렬이 깨지면 중복 등재가 눈에 안 보이고 diff 가 커진다."""
        words = json.loads((REPO_ROOT / ".cspell.json").read_text(encoding="utf-8"))["words"]
        assert words == sorted(words), "ASCII 정렬 유지 — 추가 시 자리 지킬 것"
        assert len(words) == len(set(words)), "중복 등재"


class TestGateIsWired:
    """게이트가 훅 경로에 실제로 걸려 있는가 — 스크립트만 있고 아무도 안 부르면 #1086 그대로다.

    ⚠️ 여기만 grep 이다. 훅 전체를 실행하면 pyright 9.3s 를 매 테스트 실행마다 무는데,
    래칫의 **판정**은 위 `TestRatchetVerdict` 가 실행으로 잠그고 있어서 여기서 확인할 것은
    "부르는가" 뿐이다. grep 이 조용히 눈이 머는 경우(경로 이름이 바뀌는 것)는 아래
    존재 검사가 잡는다 — 문자열만 보면 이름을 바꿔도 통과한다.
    """

    @pytest.mark.parametrize("needle", ["check_pyright_ratchet.py", "make spellcheck"])
    def test_pre_push_check_invokes_the_diagnostics(self, needle):
        text = (REPO_ROOT / "scripts" / "verify" / "pre_push_check.sh").read_text(encoding="utf-8")
        assert needle in text, f"{needle} 를 pre-push 게이트가 부르지 않는다"

    def test_the_invoked_script_exists(self):
        """문자열 일치만으로는 이사간 스크립트를 못 잡는다 — 그러면 훅이 rc=127 로 죽는다."""
        assert ratchet.BASELINE_PATH.is_file()
        assert (REPO_ROOT / "scripts" / "verify" / "check_pyright_ratchet.py").is_file()

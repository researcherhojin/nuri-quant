"""논지 원장 CLI — 쓰기 진입점이 실제로 원장에 닿는지 (#1083).

이 파일이 있는 이유는 커버리지가 아니라 **도달 가능성**이다. `upsert_thesis` 만 있으면
원장은 파이썬을 여는 사람만 쓸 수 있고, 그게 이 레포가 반복해 온 "배선은 됐는데 프로덕션
0행" 의 형태다.

⚠️ `main(argv=None)` 을 테스트할 땐 반드시 `main([...])` 로 argv 를 명시한다. 생략하면
pytest 자신의 `sys.argv` 를 파싱해 죽는데, `-n auto` 는 워커마다 argv 가 달라 **병렬
실행에서 통과**한다 (#1078 에서 실제로 그렇게 통과했다). 그래서 이 파일은 단독 실행으로도
확인한다.
"""

import pytest

from nuri.core.db import get_thesis_history, init_db
from nuri.core.thesis_cli import main

_YAML = """
ticker: zzzz
author: user
stance: bullish
status: active
effective_date: "2026-05-01"
bull_case: 가속기 수요가 공급을 앞선다
bear_case: 고객사 자체 칩 전환이 점유율을 깎는다
evidence:
  - side: bull
    claim: 데이터센터 매출 증가
    source_type: filing
"""


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _write_file(tmp_path, body=_YAML, name="t.yaml"):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


class TestWrite:
    def test_a_yaml_file_reaches_the_ledger(self, tmp_path, db_path, capsys):
        rc = main(["--db-path", str(db_path), "write", str(_write_file(tmp_path))])
        assert rc == 0
        rows = get_thesis_history("ZZZZ", db_path=db_path)
        assert len(rows) == 1, "CLI 가 돌았는데 원장에 행이 없다 — 도달 불가"
        assert rows[0]["status"] == "active"
        assert "ZZZZ" in capsys.readouterr().out, "티커가 대문자로 정규화되지 않았다"

    def test_status_defaults_to_draft(self, tmp_path, db_path):
        """명시하지 않으면 초안이다 — LLM 산출물이 사람 손 없이 화면에 실리면 안 된다."""
        body = _YAML.replace("status: active\n", "")
        rc = main(["--db-path", str(db_path), "write", str(_write_file(tmp_path, body))])
        assert rc == 0
        assert get_thesis_history("ZZZZ", db_path=db_path)[0]["status"] == "draft"

    def test_missing_keys_are_reported_together(self, tmp_path, db_path, capsys):
        """하나씩 뱉으면 사용자가 파일을 여러 번 고친다."""
        body = "ticker: zzzz\nauthor: user\n"
        rc = main(["--db-path", str(db_path), "write", str(_write_file(tmp_path, body))])
        assert rc == 2
        err = capsys.readouterr().err
        for key in ("stance", "bull_case", "bear_case", "evidence"):
            assert key in err, f"{key} 누락이 보고되지 않았다"
        assert get_thesis_history("ZZZZ", db_path=db_path) == []

    def test_validation_failure_is_a_message_not_a_traceback(self, tmp_path, db_path, capsys):
        """내용 거부는 사용자 입력 문제지 버그가 아니다 — 종료 코드로 구분한다."""
        body = _YAML.replace(
            "bear_case: 고객사 자체 칩 전환이 점유율을 깎는다",
            "bear_case: 가속기 수요가 공급을 앞선다",
        )
        rc = main(["--db-path", str(db_path), "write", str(_write_file(tmp_path, body))])
        assert rc == 1, "검증 실패(1)와 파일 문제(2)가 구분되지 않는다"
        assert "동일" in capsys.readouterr().err

    def test_a_non_mapping_file_is_rejected(self, tmp_path, db_path):
        rc = main(["--db-path", str(db_path), "write", str(_write_file(tmp_path, "- a\n- b\n"))])
        assert rc == 2

    def test_a_missing_file_is_rejected(self, tmp_path, db_path):
        rc = main(["--db-path", str(db_path), "write", str(tmp_path / "nope.yaml")])
        assert rc == 2


class TestModuleEntryPoint:
    """`python -m nuri.core.thesis_cli` 가 실제로 도는지 — `pragma: no cover` 대신 runpy.

    이 레포는 진입 가드에 pragma 를 붙이는 것을 coverage gaming 으로 본다
    (`tests/quant/test_main_runpy.py` docstring). 실행해서 확인한다.
    """

    def test_running_as_a_module_works(self, monkeypatch, capsys):
        import io
        import runpy
        import sys

        monkeypatch.setattr(sys, "argv", ["thesis_cli", "show", "ZZZZ"])
        monkeypatch.setattr(sys, "stdout", io.StringIO())
        with pytest.raises(SystemExit) as exc:
            runpy.run_module("nuri.core.thesis_cli", run_name="__main__")
        assert exc.value.code == 0


class TestShow:
    def test_reports_absence_rather_than_crashing(self, db_path, capsys):
        assert main(["--db-path", str(db_path), "show", "zzzz"]) == 0
        assert "논지 없음" in capsys.readouterr().out

    def test_a_draft_only_ticker_says_nothing_is_in_force(self, tmp_path, db_path, capsys):
        """이력에는 보이되 "유효" 로는 안 보여야 한다 — 초안과 확정을 화면이 섞으면 안 된다."""
        body = _YAML.replace("status: active", "status: draft")
        main(["--db-path", str(db_path), "write", str(_write_file(tmp_path, body))])
        capsys.readouterr()

        assert main(["--db-path", str(db_path), "show", "zzzz"]) == 0
        out = capsys.readouterr().out
        assert "1개 버전" in out
        assert "현재 유효한 논지 없음" in out

    def test_shows_both_sides_of_an_active_thesis(self, tmp_path, db_path, capsys):
        main(["--db-path", str(db_path), "write", str(_write_file(tmp_path))])
        capsys.readouterr()

        assert main(["--db-path", str(db_path), "show", "zzzz"]) == 0
        out = capsys.readouterr().out
        assert "상승: 가속기 수요가 공급을 앞선다" in out
        assert "하락: 고객사 자체 칩 전환이 점유율을 깎는다" in out
        assert "근거 1건" in out

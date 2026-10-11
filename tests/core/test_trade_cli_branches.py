"""실거래 기록 CLI 의 `list` 출력과 `-m` 진입점 잠금 (#1163)."""

from __future__ import annotations

import io
import runpy
import sys

import pytest

from nuri.core.db import init_db
from nuri.core.trade_cli import add_trade, main


@pytest.fixture
def default_db(tmp_path, monkeypatch):
    """CLI 는 db_path 를 받지 않는다 — 기본 DB 를 격리 사본으로 돌린다."""
    import nuri.core.db as db_mod

    path = tmp_path / "t.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


class TestListOutput:
    def test_each_trade_is_one_line_with_the_side_price_and_account(self, default_db, capsys):
        """BUY 는 진입가, SELL 은 청산가를 찍고, 계좌가 비면 `-` 로 — 월 필터 밖 거래는 빠진다."""
        add_trade("AAA", "BUY", 10, 50.5, "Brokerage Alpha", date="2026-08-03")
        add_trade("BBB", "SELL", 4, 120.0, "", date="2026-08-20")
        add_trade("CCC", "BUY", 1, 9.0, "Brokerage Beta", date="2026-07-31")

        assert main(["list", "--month", "2026-08"]) == 0

        assert capsys.readouterr().out.splitlines() == [
            "2026-08-20 SELL BBB        4.0 @ 120.0 (-)",
            "2026-08-03 BUY  AAA        10.0 @ 50.5 (Brokerage Alpha)",
        ]

    def test_an_empty_ledger_says_so(self, default_db, capsys):
        assert main(["list"]) == 0
        assert capsys.readouterr().out.strip() == "기록 없음"


def test_the_module_entry_point_exits_with_the_cli_code(default_db, monkeypatch):
    add_trade("AAA", "BUY", 2, 10.0, "Brokerage Alpha", date="2026-08-03")
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "argv", ["trade_cli", "list"])
    monkeypatch.setattr(sys, "stdout", stdout)

    with pytest.raises(SystemExit) as exc:
        runpy.run_module("nuri.core.trade_cli", run_name="__main__")

    assert exc.value.code == 0
    assert stdout.getvalue().splitlines() == ["2026-08-03 BUY  AAA        2.0 @ 10.0 (Brokerage Alpha)"]

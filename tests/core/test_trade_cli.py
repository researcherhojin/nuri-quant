"""실거래 기록 CLI (#1163) — 회전율(W4)·논지 귀속의 데이터 입구를 잠근다."""

from __future__ import annotations

import pytest

from nuri.core.db import init_db, query
from nuri.core.timezone import today_kst
from nuri.core.trade_cli import add_trade, list_trades, main


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "t.db"
    init_db(p)
    return p


class TestAddTrade:
    def test_buy_maps_to_entry_price_with_account(self, db):
        tid = add_trade("aapl", "buy", 10, 231.5, "Brokerage Alpha", db_path=db)
        row = query("SELECT * FROM trades WHERE id = ?", (tid,), db_path=db)[0]
        assert row["ticker"] == "AAPL"
        assert row["action"] == "BUY"
        assert row["entry_price"] == 231.5
        assert row["exit_price"] is None
        assert row["account"] == "Brokerage Alpha"
        assert row["executed_at"] == today_kst()

    def test_sell_maps_to_exit_price_and_date(self, db):
        tid = add_trade("MSFT", "SELL", 5, 500.0, "Brokerage Beta", date="2026-08-01", db_path=db)
        row = query("SELECT * FROM trades WHERE id = ?", (tid,), db_path=db)[0]
        assert row["exit_price"] == 500.0
        assert row["exit_date"] == "2026-08-01"
        assert row["entry_price"] is None

    def test_invalid_side_and_nonpositive_rejected(self, db):
        with pytest.raises(ValueError, match="BUY/SELL"):
            add_trade("AAPL", "HOLD", 1, 1.0, "a", db_path=db)
        with pytest.raises(ValueError, match="양수"):
            add_trade("AAPL", "BUY", 0, 1.0, "a", db_path=db)
        with pytest.raises(ValueError, match="양수"):
            add_trade("AAPL", "BUY", 1, -1.0, "a", db_path=db)

    def test_month_filter(self, db):
        add_trade("AAPL", "BUY", 1, 1.0, "a", date="2026-07-15", db_path=db)
        add_trade("AAPL", "BUY", 1, 1.0, "a", date="2026-08-15", db_path=db)
        assert len(list_trades(month="2026-08", db_path=db)) == 1
        assert len(list_trades(db_path=db)) == 2


class TestCliEntry:
    def test_add_via_argv(self, db, monkeypatch, capsys):
        import nuri.core.db as db_mod

        monkeypatch.setattr(db_mod, "DB_PATH", db)
        rc = main(["add", "--ticker", "NVDA", "--side", "BUY", "--qty", "3", "--price", "190.5", "--account", "main"])
        assert rc == 0
        assert "NVDA BUY 3.0 @ 190.5" in capsys.readouterr().out
        assert query("SELECT COUNT(*) AS n FROM trades", db_path=db)[0]["n"] == 1

    def test_add_rejects_bad_input_with_rc1(self, db, monkeypatch, capsys):
        import nuri.core.db as db_mod

        monkeypatch.setattr(db_mod, "DB_PATH", db)
        rc = main(["add", "--ticker", "NVDA", "--side", "BUY", "--qty", "0", "--price", "1", "--account", "main"])
        assert rc == 1

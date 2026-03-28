"""스윙 트레이드 규칙 엔진 테스트."""
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_prices


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


# ═══════════════════════════════════════════════════════
# SwingEntry / SwingExit 데이터 클래스
# ═══════════════════════════════════════════════════════

class TestSwingEntry:
    def test_create(self):
        from nuri.trading.swing.rules import SwingEntry
        e = SwingEntry("AAPL", 150.0, "rsi_oversold", 30.0, "BUY", 65.0, 0.8, True, "ok")
        assert e.ticker == "AAPL"
        assert e.approved is True

    def test_rejected(self):
        from nuri.trading.swing.rules import SwingEntry
        e = SwingEntry("AAPL", 150.0, "rsi_oversold", 30.0, "HOLD", 30.0, 0.5, False, "에이전트 HOLD")
        assert e.approved is False


class TestSwingExit:
    def test_create(self):
        from nuri.trading.swing.rules import SwingExit
        x = SwingExit("AAPL", 150.0, 165.0, 10.0, 5, "take_profit", True)
        assert x.should_exit is True
        assert x.exit_reason == "take_profit"

    def test_hold(self):
        from nuri.trading.swing.rules import SwingExit
        x = SwingExit("AAPL", 150.0, 152.0, 1.3, 2, "hold", False)
        assert x.should_exit is False


# ═══════════════════════════════════════════════════════
# save_entries
# ═══════════════════════════════════════════════════════

class TestSaveEntries:
    def test_save_approved(self, db_path):
        from nuri.core.db import query
        from nuri.trading.swing.rules import SwingEntry, save_entries

        entries = [
            SwingEntry("AAPL", 150.0, "rsi_oversold", 30.0, "BUY", 65.0, 0.8, True, "ok"),
            SwingEntry("MSFT", 300.0, "macd_golden", 25.0, "HOLD", 30.0, 0.5, False, "rejected"),
        ]
        n = save_entries(entries, db_path=db_path)
        assert n == 1  # 승인된 1건만

        rows = query("SELECT * FROM swing_trades", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["ticker"] == "AAPL"

    def test_save_empty(self, db_path):
        from nuri.trading.swing.rules import save_entries
        n = save_entries([], db_path=db_path)
        assert n == 0

    def test_save_all_rejected(self, db_path):
        from nuri.trading.swing.rules import SwingEntry, save_entries
        entries = [
            SwingEntry("AAPL", 150.0, "rsi_oversold", 30.0, "HOLD", 30.0, 0.5, False, "no"),
        ]
        n = save_entries(entries, db_path=db_path)
        assert n == 0


# ═══════════════════════════════════════════════════════
# check_exits
# ═══════════════════════════════════════════════════════

class TestCheckExits:
    def test_no_open_trades(self, db_path):
        from nuri.trading.swing.rules import check_exits
        exits = check_exits(db_path=db_path)
        assert exits == []

    def test_take_profit(self, db_path):
        """수익률 +10% 이상 → take_profit."""
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO swing_trades (ticker, entry_date, entry_price, entry_signal, status) "
                "VALUES (?, ?, ?, ?, 'open')",
                ("AAPL", today, 100.0, "rsi_oversold"),
            )

        # 현재가 115 → +15%
        prices = pd.DataFrame([{
            "ticker": "AAPL", "date": today,
            "open": 114, "high": 116, "low": 113, "close": 115.0,
            "volume": 1000000, "adj_close": 115.0,
        }])
        upsert_prices(prices, db_path)

        from nuri.trading.swing.rules import check_exits
        exits = check_exits(db_path=db_path)
        assert len(exits) == 1
        assert exits[0].exit_reason == "take_profit"
        assert exits[0].should_exit is True

    def test_stop_loss(self, db_path):
        """수익률 -5% 이하 → stop_loss."""
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO swing_trades (ticker, entry_date, entry_price, entry_signal, status) "
                "VALUES (?, ?, ?, ?, 'open')",
                ("BAD", today, 100.0, "bb_bounce"),
            )

        prices = pd.DataFrame([{
            "ticker": "BAD", "date": today,
            "open": 93, "high": 94, "low": 92, "close": 93.0,
            "volume": 1000000, "adj_close": 93.0,
        }])
        upsert_prices(prices, db_path)

        from nuri.trading.swing.rules import check_exits
        exits = check_exits(db_path=db_path)
        assert len(exits) == 1
        assert exits[0].exit_reason == "stop_loss"

    def test_max_hold(self, db_path):
        """보유일 >= 7일 → max_hold."""
        from datetime import datetime, timedelta
        entry_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO swing_trades (ticker, entry_date, entry_price, entry_signal, status) "
                "VALUES (?, ?, ?, ?, 'open')",
                ("HOLD", entry_date, 100.0, "momentum"),
            )

        prices = pd.DataFrame([{
            "ticker": "HOLD", "date": today,
            "open": 101, "high": 102, "low": 100, "close": 101.0,
            "volume": 1000000, "adj_close": 101.0,
        }])
        upsert_prices(prices, db_path)

        from nuri.trading.swing.rules import check_exits
        exits = check_exits(db_path=db_path)
        assert len(exits) == 1
        assert exits[0].exit_reason == "max_hold"


# ═══════════════════════════════════════════════════════
# 출력 함수
# ═══════════════════════════════════════════════════════

class TestPrintEntries:
    def test_empty(self, capsys):
        from nuri.trading.swing.rules import print_entries
        print_entries([])
        output = capsys.readouterr().out
        assert "없음" in output

    def test_with_entries(self, capsys):
        from nuri.trading.swing.rules import SwingEntry, print_entries
        entries = [
            SwingEntry("AAPL", 150.0, "rsi_oversold", 30.0, "BUY", 65.0, 0.8, True, "ok"),
            SwingEntry("MSFT", 300.0, "macd_golden", 25.0, "HOLD", 30.0, 0.5, False, "no"),
        ]
        print_entries(entries)
        output = capsys.readouterr().out
        assert "APPROVED" in output
        assert "REJECTED" in output


class TestPrintExits:
    def test_empty(self, capsys):
        from nuri.trading.swing.rules import print_exits
        print_exits([])
        output = capsys.readouterr().out
        assert "없음" in output

    def test_with_exits(self, capsys):
        from nuri.trading.swing.rules import SwingExit, print_exits
        exits = [SwingExit("AAPL", 150.0, 165.0, 10.0, 5, "take_profit", True)]
        print_exits(exits)
        output = capsys.readouterr().out
        assert "AAPL" in output


# ═══════════════════════════════════════════════════════
# 상수/파라미터
# ═══════════════════════════════════════════════════════

class TestConstants:
    def test_thresholds(self):
        from nuri.trading.swing.rules import (
            MAX_HOLD_DAYS,
            MIN_AGENT_CONFIDENCE,
            MIN_SCAN_SCORE,
            STOP_LOSS_PCT,
            TAKE_PROFIT_PCT,
        )
        assert TAKE_PROFIT_PCT == 10.0
        assert STOP_LOSS_PCT == -5.0
        assert MAX_HOLD_DAYS == 7
        assert MIN_SCAN_SCORE == 20
        assert MIN_AGENT_CONFIDENCE == 50

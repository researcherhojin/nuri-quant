"""Tests for nuri.trading.swing.rules.

Extracted from the former tests/test_trading_strategy_all.py.
Shared fixtures live in conftest.py for this directory.
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd

from nuri.core.db import get_db, query, upsert_prices


class TestSwingRules:
    """From test_swing.py — basic rules."""

    def test_entry_evaluation(self, db_path):
        from nuri.trading.swing.rules import evaluate_entries
        entries = evaluate_entries(scan_results=[], db_path=db_path)
        assert entries == []

    def test_exit_no_positions(self, db_path):
        from nuri.trading.swing.rules import check_exits
        exits = check_exits(db_path=db_path)
        assert exits == []

    def test_save_entry(self, db_path):
        from nuri.trading.swing.rules import SwingEntry, save_entries
        entries = [SwingEntry(
            ticker="TEST", price=100.0, scan_signal="volume_spike",
            scan_score=30, agent_action="BUY", agent_confidence=70,
            agent_agreement=0.6, approved=True, reason="test",
        )]
        n = save_entries(entries, db_path=db_path)
        assert n == 1
        rows = query("SELECT * FROM swing_trades WHERE ticker='TEST'", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["status"] == "open"


class TestSwingEntry:
    """From test_swing_rules.py — SwingEntry dataclass."""

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
    """From test_swing_rules.py — SwingExit dataclass."""

    def test_create(self):
        from nuri.trading.swing.rules import SwingExit
        x = SwingExit("AAPL", 150.0, 165.0, 10.0, 5, "take_profit", True)
        assert x.should_exit is True
        assert x.exit_reason == "take_profit"

    def test_hold(self):
        from nuri.trading.swing.rules import SwingExit
        x = SwingExit("AAPL", 150.0, 152.0, 1.3, 2, "hold", False)
        assert x.should_exit is False


class TestSaveEntries:
    """From test_swing_rules.py — save_entries."""

    def test_save_approved(self, db_path):
        from nuri.trading.swing.rules import SwingEntry, save_entries
        entries = [
            SwingEntry("AAPL", 150.0, "rsi_oversold", 30.0, "BUY", 65.0, 0.8, True, "ok"),
            SwingEntry("MSFT", 300.0, "macd_golden", 25.0, "HOLD", 30.0, 0.5, False, "rejected"),
        ]
        n = save_entries(entries, db_path=db_path)
        assert n == 1
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


class TestCheckExits:
    """From test_swing_rules.py — check_exits."""

    def test_no_open_trades(self, db_path):
        from nuri.trading.swing.rules import check_exits
        exits = check_exits(db_path=db_path)
        assert exits == []

    def test_take_profit(self, db_path):
        today = datetime.now().strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO swing_trades (ticker, entry_date, entry_price, entry_signal, status) "
                "VALUES (?, ?, ?, ?, 'open')",
                ("AAPL", today, 100.0, "rsi_oversold"),
            )
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


class TestCheckExits_R18:
    """From test_coverage_round18.py — check_exits with rich data."""

    def test_take_profit_exit(self, rich_db):
        from nuri.trading.swing.rules import check_exits
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO swing_trades (ticker, entry_date, entry_price, status) "
                "VALUES ('AAPL', '2024-10-01', 100.0, 'open')")
        exits = check_exits(rich_db)
        assert len(exits) >= 1
        tp = [e for e in exits if e.exit_reason == "take_profit"]
        assert len(tp) >= 1

    def test_no_open_trades(self, rich_db):
        from nuri.trading.swing.rules import check_exits
        exits = check_exits(rich_db)
        assert exits == []


class TestPrintEntries:
    """From test_swing_rules.py — print_entries."""

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
    """From test_swing_rules.py — print_exits."""

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


class TestConstants:
    """From test_swing_rules.py — constants."""

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


class TestEvaluateEntries:
    """From test_coverage_round18.py — evaluate_entries with mocked consensus."""

    def test_approved_entry(self, rich_db):
        from nuri.trading.swing.rules import evaluate_entries
        from nuri.trading.swing.scanner import ScanResult
        scan_results = [
            ScanResult("AAPL", 180.0, 2.0, 8.0, 3.0, 55.0, 0.6, "volume_spike", 40.0),
        ]
        mock_consensus = MagicMock(
            final_action="BUY", final_confidence=75.0, agreement_rate=0.6,
        )
        with patch("nuri.trading.agents.consensus.analyze_ticker", return_value=mock_consensus):
            entries = evaluate_entries(scan_results=scan_results, db_path=rich_db)
        assert len(entries) == 1
        assert entries[0].approved is True

    def test_rejected_low_confidence(self, rich_db):
        from nuri.trading.swing.rules import evaluate_entries
        from nuri.trading.swing.scanner import ScanResult
        scan_results = [
            ScanResult("NVDA", 900.0, 3.0, 10.0, 2.0, 60.0, 0.5, "momentum", 30.0),
        ]
        mock_consensus = MagicMock(
            final_action="BUY", final_confidence=30.0, agreement_rate=0.3,
        )
        with patch("nuri.trading.agents.consensus.analyze_ticker", return_value=mock_consensus):
            entries = evaluate_entries(scan_results=scan_results, db_path=rich_db)
        assert len(entries) == 1
        assert entries[0].approved is False

    def test_low_score_skipped(self, rich_db):
        from nuri.trading.swing.rules import evaluate_entries
        from nuri.trading.swing.scanner import ScanResult
        scan_results = [
            ScanResult("AAPL", 180.0, 1.0, 3.0, 1.5, 50.0, 0.5, "none", 10.0),
        ]
        entries = evaluate_entries(scan_results=scan_results, db_path=rich_db)
        assert len(entries) == 0

    def test_empty_scan_results(self, rich_db):
        from nuri.trading.swing.rules import evaluate_entries
        entries = evaluate_entries(scan_results=[], db_path=rich_db)
        assert entries == []


class TestSaveEntries_R18:
    """From test_coverage_round18.py — save_entries."""

    def test_saves_approved(self, rich_db):
        from nuri.trading.swing.rules import SwingEntry, save_entries
        entries = [
            SwingEntry("AAPL", 180.0, "volume_spike", 40.0, "BUY", 75.0, 0.6, True, "approved"),
            SwingEntry("NVDA", 900.0, "momentum", 50.0, "HOLD", 40.0, 0.3, False, "rejected"),
        ]
        n = save_entries(entries, rich_db)
        assert n == 1

    def test_no_approved_returns_zero(self, rich_db):
        from nuri.trading.swing.rules import SwingEntry, save_entries
        entries = [
            SwingEntry("NVDA", 900.0, "momentum", 50.0, "HOLD", 40.0, 0.3, False, "rejected"),
        ]
        n = save_entries(entries, rich_db)
        assert n == 0


class TestSwingPrintHelpers:
    """From test_coverage_round18.py — print helpers."""

    def test_print_entries_approved(self, capsys):
        from nuri.trading.swing.rules import SwingEntry, print_entries
        entries = [
            SwingEntry("AAPL", 180.0, "volume_spike", 40.0, "BUY", 75.0, 0.6, True, "approved"),
            SwingEntry("NVDA", 900.0, "momentum", 50.0, "HOLD", 40.0, 0.3, False, "rejected: low conf"),
        ]
        print_entries(entries)
        out = capsys.readouterr().out
        assert "APPROVED" in out
        assert "REJECTED" in out

    def test_print_exits(self, capsys):
        from nuri.trading.swing.rules import SwingExit, print_exits
        exits = [
            SwingExit("AAPL", 170.0, 185.0, 8.82, 3, "hold", False),
            SwingExit("NVDA", 900.0, 800.0, -11.11, 5, "stop_loss", True),
        ]
        print_exits(exits)
        out = capsys.readouterr().out
        assert "STOP_LOSS" in out


class TestSwingRulesDeep:
    """From test_coverage_round11.py — deeper rules."""

    def test_evaluate_entries(self, rich_db):
        from nuri.trading.swing.rules import evaluate_entries
        entries = evaluate_entries(db_path=rich_db)
        assert isinstance(entries, list)

    def test_check_exits(self, rich_db):
        from nuri.trading.swing.rules import check_exits
        exits = check_exits(db_path=rich_db)
        assert isinstance(exits, list)


class TestSwingAgentSellExit:
    """From test_coverage_round18.py — agent SELL exit path."""

    def test_agent_sell_triggers_exit(self, rich_db):
        from nuri.trading.swing.rules import check_exits
        latest = query(
            "SELECT close FROM prices WHERE ticker='AAPL' ORDER BY date DESC LIMIT 1",
            db_path=rich_db,
        )[0]["close"]
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO swing_trades (ticker, entry_date, entry_price, status) "
                "VALUES ('AAPL', ?, ?, 'open')",
                (datetime.now().strftime("%Y-%m-%d"), latest),
            )
        mock_consensus = MagicMock(final_action="SELL", final_confidence=85.0)
        with patch("nuri.trading.agents.consensus.analyze_ticker", return_value=mock_consensus):
            exits = check_exits(rich_db)
        agent_sells = [e for e in exits if e.exit_reason == "agent_sell"]
        assert len(agent_sells) >= 1
        assert agent_sells[0].should_exit is True


class TestSwingScanner_R8:
    """From test_coverage_round8.py — swing scanner/rules combo."""

    def test_scan(self, rich_db):
        from nuri.trading.swing.scanner import scan_market
        results = scan_market()
        assert isinstance(results, list)

    def test_evaluate_entries(self, rich_db):
        from nuri.trading.swing.rules import evaluate_entries
        entries = evaluate_entries(db_path=rich_db)
        assert isinstance(entries, list)

    def test_check_exits(self, rich_db):
        from nuri.trading.swing.rules import check_exits
        exits = check_exits(db_path=rich_db)
        assert isinstance(exits, list)

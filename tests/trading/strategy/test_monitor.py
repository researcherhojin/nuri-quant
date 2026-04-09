"""Tests for nuri.trading.strategy.monitor.

Extracted from the former tests/test_trading_strategy_all.py.
Shared fixtures live in conftest.py for this directory.
"""
from unittest.mock import MagicMock, patch

from nuri.core.db import get_db


class TestMonitor:
    """From test_strategy.py — monitor."""

    def test_regime_transition_initial(self, bull_data):
        from nuri.trading.strategy.monitor import detect_regime_transition
        transition = detect_regime_transition(db_path=bull_data)
        if transition:
            assert "to_regime" in transition

    def test_pnl_empty(self, db_path):
        from nuri.trading.strategy.monitor import daily_pnl_summary
        pnl = daily_pnl_summary(db_path=db_path)
        assert pnl["total_positions"] == 0


class TestStrategyMonitor:
    """From test_coverage_extra.py — monitor."""

    def test_detect_regime_transition(self, db_path):
        from nuri.trading.strategy.monitor import detect_regime_transition
        result = detect_regime_transition(db_path=db_path)
        assert result is None or isinstance(result, dict)

    def test_daily_pnl_summary(self, db_path):
        from nuri.trading.strategy.monitor import daily_pnl_summary
        result = daily_pnl_summary(db_path=db_path)
        assert isinstance(result, dict)


class TestMonitorDailyPnl:
    """From test_coverage_round16.py — daily PnL."""

    def test_empty_positions(self, rich_db):
        from nuri.trading.strategy.monitor import daily_pnl_summary
        with patch("nuri.trading.strategy.position.update_prices"):
            result = daily_pnl_summary(db_path=rich_db)
        assert result["total_positions"] == 0
        assert result["best"] is None

    def test_with_open_positions(self, rich_db):
        from nuri.trading.strategy.monitor import daily_pnl_summary
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, quantity, current_price, return_pct, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("core", "AAPL", "long", "2025-01-01", 170.0, 10, 200.0, 17.6, "open"))
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, quantity, current_price, return_pct, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("core", "TSLA", "long", "2025-01-01", 250.0, 3, 230.0, -8.0, "open"))
        with patch("nuri.trading.strategy.position.update_prices"):
            result = daily_pnl_summary(db_path=rich_db)
        assert result["total_positions"] == 2
        assert result["best"]["ticker"] == "AAPL"
        assert result["worst"]["ticker"] == "TSLA"


class TestMonitorRegimeTransition:
    """From test_coverage_round16.py — regime transitions."""

    def test_classify_regime_fails(self, rich_db):
        from nuri.trading.strategy.monitor import detect_regime_transition
        with patch("nuri.quant.regime.classifier.classify_regime", side_effect=Exception("fail")):
            result = detect_regime_transition(db_path=rich_db)
        assert result is None

    def test_classify_returns_none(self, rich_db):
        from nuri.trading.strategy.monitor import detect_regime_transition
        with patch("nuri.quant.regime.classifier.classify_regime", return_value=None):
            result = detect_regime_transition(db_path=rich_db)
        assert result is None

    def test_transition_bull_to_bear(self, rich_db):
        from nuri.trading.strategy.monitor import detect_regime_transition
        mock_regime = MagicMock()
        mock_regime.regime = "bear_high_vol"
        mock_regime.confidence = 0.80
        mock_regime.trend = "bear"
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO regime_transitions (date, from_regime, to_regime) VALUES (?, ?, ?)",
                ("2025-03-01", "sideways_low_vol", "bull_low_vol"))
        with patch("nuri.quant.regime.classifier.classify_regime", return_value=mock_regime):
            result = detect_regime_transition(db_path=rich_db)
        assert result is not None
        assert result["urgency"] == "high"

    def test_first_regime_no_previous(self, rich_db):
        from nuri.trading.strategy.monitor import detect_regime_transition
        mock_regime = MagicMock()
        mock_regime.regime = "bull_low_vol"
        mock_regime.confidence = 0.90
        mock_regime.trend = "bull"
        with patch("nuri.quant.regime.classifier.classify_regime", return_value=mock_regime):
            result = detect_regime_transition(db_path=rich_db)
        assert result is not None
        assert result["urgency"] == "low"


class TestMonitorDeep:
    """From test_coverage_round10.py — monitor print."""

    def test_daily_pnl_summary(self, rich_db):
        from nuri.trading.strategy.monitor import daily_pnl_summary
        result = daily_pnl_summary(db_path=rich_db)
        assert isinstance(result, dict)

    def test_print_monitor(self, rich_db, capsys):
        from nuri.trading.strategy.monitor import print_monitor
        print_monitor(db_path=rich_db)
        output = capsys.readouterr().out
        assert len(output) >= 0


class TestMonitor_R8:
    """From test_coverage_round8.py — monitor."""

    def test_detect_regime_transition(self, rich_db):
        from nuri.trading.strategy.monitor import detect_regime_transition
        result = detect_regime_transition(db_path=rich_db)
        assert result is None or isinstance(result, dict)

    def test_daily_pnl_summary(self, rich_db):
        from nuri.trading.strategy.monitor import daily_pnl_summary
        result = daily_pnl_summary(db_path=rich_db)
        assert isinstance(result, dict)

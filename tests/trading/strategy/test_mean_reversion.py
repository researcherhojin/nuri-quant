"""Tests for nuri.trading.strategy.mean_reversion.

Extracted from the former tests/test_trading_strategy_all.py.
Shared fixtures live in conftest.py for this directory.
"""

import pandas as pd

from nuri.core.db import init_db, upsert_portfolio, upsert_prices


class TestMeanReversion:
    """From test_new_features.py — mean reversion basics."""

    def test_scan_returns_list(self, market_data):
        from nuri.trading.strategy.mean_reversion import scan_mean_reversion
        signals = scan_mean_reversion(db_path=market_data)
        assert isinstance(signals, list)

    def test_backtest(self, market_data):
        from nuri.trading.strategy.mean_reversion import backtest_mean_reversion
        result = backtest_mean_reversion(db_path=market_data)
        assert "total_trades" in result


class TestMeanReversion_Extra:
    """From test_coverage_extra.py — mean reversion."""

    def test_import(self):
        from nuri.trading.strategy.mean_reversion import scan_mean_reversion
        assert callable(scan_mean_reversion)

    def test_empty_db(self, db_path):
        from nuri.trading.strategy.mean_reversion import scan_mean_reversion
        results = scan_mean_reversion(db_path=db_path)
        assert isinstance(results, list)

    def test_with_data(self, rich_db):
        from nuri.trading.strategy.mean_reversion import scan_mean_reversion
        results = scan_mean_reversion(db_path=rich_db)
        assert isinstance(results, list)


class TestMeanReversionBacktest:
    """From test_coverage_round16.py — backtest."""

    def test_no_trades(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        path = tmp_path / "flat.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        upsert_portfolio([{"account": "t", "ticker": "FLAT", "quantity": 1,
                           "avg_price": 100, "currency": "USD", "sector": "Tech"}], path)
        dates = pd.bdate_range("2024-01-01", periods=80, freq="B")
        rows = [{"ticker": "FLAT", "date": d.strftime("%Y-%m-%d"),
                 "open": 100, "high": 101, "low": 99, "close": 100,
                 "volume": 1_000_000, "adj_close": 100} for d in dates]
        upsert_prices(pd.DataFrame(rows), path)

        from nuri.trading.strategy.mean_reversion import backtest_mean_reversion
        result = backtest_mean_reversion(db_path=path)
        assert result["total_trades"] == 0

    def test_backtest_with_rich_data(self, rich_db):
        from nuri.trading.strategy.mean_reversion import backtest_mean_reversion
        result = backtest_mean_reversion(db_path=rich_db)
        assert "total_trades" in result

"""Tests for nuri.trading.strategy.pairs.

Extracted from the former tests/test_trading_strategy_all.py.
Shared fixtures live in conftest.py for this directory.
"""

from nuri.core.db import init_db, upsert_portfolio


class TestPairs:
    """From test_new_features.py — pairs trading basics."""

    def test_find_pairs(self, market_data):
        from nuri.trading.strategy.pairs import find_pairs
        pairs = find_pairs(min_corr=0.5, db_path=market_data)
        assert isinstance(pairs, list)

    def test_backtest(self, market_data):
        from nuri.trading.strategy.pairs import backtest_pairs
        result = backtest_pairs(db_path=market_data)
        assert "pairs_found" in result


class TestPairsTrading:
    """From test_coverage_extra.py — pairs trading."""

    def test_find_pairs(self):
        from nuri.trading.strategy.pairs import find_pairs
        assert callable(find_pairs)

    def test_find_pairs_empty(self, db_path):
        from nuri.trading.strategy.pairs import find_pairs
        results = find_pairs(db_path=db_path)
        assert isinstance(results, list)

    def test_find_pairs_with_data(self, rich_db):
        from nuri.trading.strategy.pairs import find_pairs
        results = find_pairs(db_path=rich_db)
        assert isinstance(results, list)


class TestFindPairs:
    """From test_coverage_round21.py — find_pairs deeper tests."""

    def test_finds_correlated_pairs(self, rich_db):
        from nuri.trading.strategy.pairs import find_pairs
        pairs = find_pairs(min_corr=0.5, db_path=rich_db)
        assert isinstance(pairs, list)
        if pairs:
            assert hasattr(pairs[0], "ticker_a")
            assert pairs[0].correlation >= 0.5

    def test_empty_when_no_prices(self, tmp_path):
        path = tmp_path / "no_prices.db"
        init_db(path)
        upsert_portfolio([
            {"account": "t", "ticker": "AAPL", "quantity": 1,
             "avg_price": 100, "currency": "USD", "sector": "Tech"},
            {"account": "t", "ticker": "MSFT", "quantity": 1,
             "avg_price": 100, "currency": "USD", "sector": "Tech"},
        ], path)
        from nuri.trading.strategy.pairs import find_pairs
        assert find_pairs(db_path=path) == []

    def test_pairs_sorted_by_zscore(self, rich_db):
        from nuri.trading.strategy.pairs import find_pairs
        pairs = find_pairs(min_corr=0.3, db_path=rich_db)
        if len(pairs) >= 2:
            assert abs(pairs[0].current_z) >= abs(pairs[1].current_z)


class TestScanPairSignals:
    """From test_coverage_round21.py — scan pair signals."""

    def test_scan_returns_signals_or_empty(self, rich_db):
        from nuri.trading.strategy.pairs import scan_pair_signals
        signals = scan_pair_signals(db_path=rich_db)
        assert isinstance(signals, list)


class TestBacktestPairs:
    """From test_coverage_round21.py — backtest pairs."""

    def test_backtest_runs(self, rich_db):
        from nuri.trading.strategy.pairs import backtest_pairs
        result = backtest_pairs(max_hold=10, db_path=rich_db)
        assert isinstance(result, dict)
        assert "pairs_found" in result

    def test_backtest_empty_db(self, tmp_path):
        path = tmp_path / "empty.db"
        init_db(path)
        from nuri.trading.strategy.pairs import backtest_pairs
        result = backtest_pairs(db_path=path)
        assert result["total_trades"] == 0

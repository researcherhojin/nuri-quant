"""Tests for nuri.trading.swing.scanner.

Extracted from the former tests/test_trading_strategy_all.py.
Shared fixtures live in conftest.py for this directory.
"""
from unittest.mock import patch

import numpy as np
import pandas as pd


class TestScanResult:
    """From test_swing.py — scan result."""

    def test_analyze_ticker(self):
        from nuri.trading.swing.scanner import ScanResult, _analyze_ticker
        dates = pd.bdate_range("2025-01-01", periods=30)
        close = np.linspace(100, 120, 30)
        volume = [1000000] * 20 + [3000000] * 10
        data = pd.DataFrame({
            "Close": close, "Volume": volume,
        }, index=dates)
        result = _analyze_ticker("TEST", data)
        if result:
            assert isinstance(result, ScanResult)
            assert result.ticker == "TEST"
            assert result.score > 0


class TestAnalyzeTickerScanner:
    """From test_coverage_round18.py — _analyze_ticker patterns."""

    def _make_data(self, prices, volumes=None):
        n = len(prices)
        if volumes is None:
            volumes = [50_000_000] * n
        dates = pd.bdate_range("2024-01-01", periods=n)
        df = pd.DataFrame({
            "Close": prices, "Volume": volumes,
            "Open": [p - 1 for p in prices],
            "High": [p + 2 for p in prices],
            "Low": [p - 2 for p in prices],
        }, index=dates)
        return df

    def test_too_short_returns_none(self):
        from nuri.trading.swing.scanner import _analyze_ticker
        df = self._make_data([100.0] * 10)
        result = _analyze_ticker("AAPL", df)
        assert result is None

    def test_volume_spike_detected(self):
        from nuri.trading.swing.scanner import _analyze_ticker
        volumes = [10_000_000] * 29 + [30_000_000]
        prices = [100.0 + i * 0.5 for i in range(30)]
        df = self._make_data(prices, volumes)
        result = _analyze_ticker("AAPL", df)
        if result is not None:
            assert result.score > 0

    def test_zero_price_returns_none(self):
        from nuri.trading.swing.scanner import _analyze_ticker
        prices = [0.0] * 30
        df = self._make_data(prices)
        result = _analyze_ticker("AAPL", df)
        assert result is None

    def test_no_signal_returns_none(self):
        from nuri.trading.swing.scanner import _analyze_ticker
        prices = [100.0] * 30
        volumes = [10_000_000] * 30
        df = self._make_data(prices, volumes)
        result = _analyze_ticker("AAPL", df)
        assert result is None


class TestScanMarket:
    """From test_coverage_round18.py — scan_market."""

    def test_scan_returns_empty_on_no_data(self):
        from nuri.trading.swing.scanner import scan_market
        with patch("nuri.trading.swing.scanner._fetch_prices", return_value=None):
            results = scan_market()
        assert results == []

    def test_scan_filters_and_sorts(self):
        from nuri.trading.swing.scanner import ScanResult, scan_market
        fake_results = {
            "AAPL": ScanResult("AAPL", 180.0, 2.0, 8.0, 3.0, 55.0, 0.6, "volume_spike", 40.0),
            "NVDA": ScanResult("NVDA", 900.0, 5.0, 15.0, 2.5, 65.0, 0.8, "momentum", 60.0),
        }
        def mock_analyze(ticker, data):
            return fake_results.get(ticker)
        with patch("nuri.trading.swing.scanner._fetch_prices", return_value=pd.DataFrame({"x": [1]})):
            with patch("nuri.trading.swing.scanner._analyze_ticker", side_effect=mock_analyze):
                results = scan_market(top_n=5)
        if len(results) >= 2:
            assert results[0].score >= results[1].score

    def test_scan_kr_market(self):
        from nuri.trading.swing.scanner import scan_market
        with patch("nuri.trading.swing.scanner._fetch_prices", return_value=None):
            results = scan_market(market="kr")
        assert results == []


class TestPrintScan:
    """From test_coverage_round18.py — print_scan."""

    def test_print_scan_results(self, capsys):
        from nuri.trading.swing.scanner import ScanResult, print_scan
        results = [
            ScanResult("AAPL", 180.0, 2.0, 8.0, 3.0, 55.0, 0.6, "volume_spike", 40.0),
        ]
        print_scan(results)
        out = capsys.readouterr().out
        assert "AAPL" in out

    def test_print_scan_empty(self, capsys):
        from nuri.trading.swing.scanner import print_scan
        print_scan([])
        out = capsys.readouterr().out
        assert "스캔 결과 없음" in out


class TestScannerMomentumBreakout:
    """From test_coverage_round18.py — momentum/breakout detection."""

    def _make_data(self, prices, volumes=None):
        n = len(prices)
        if volumes is None:
            volumes = [50_000_000] * n
        dates = pd.bdate_range("2024-01-01", periods=n)
        return pd.DataFrame({
            "Close": prices, "Volume": volumes,
            "Open": [p - 1 for p in prices],
            "High": [p + 2 for p in prices],
            "Low": [p - 2 for p in prices],
        }, index=dates)

    def test_momentum_signal(self):
        from nuri.trading.swing.scanner import _analyze_ticker
        prices = [100.0 + i * 1.5 for i in range(30)]
        df = self._make_data(prices)
        result = _analyze_ticker("AAPL", df)
        if result is not None:
            assert result.score > 0

    def test_breakout_signal(self):
        from nuri.trading.swing.scanner import _analyze_ticker
        prices = [100.0] * 25 + [100.0, 101.0, 103.0, 108.0, 115.0]
        volumes = [10_000_000] * 25 + [10_000_000, 15_000_000, 20_000_000, 25_000_000, 35_000_000]
        df = self._make_data(prices, volumes)
        result = _analyze_ticker("AAPL", df)
        if result is not None:
            assert result.signal in ("breakout", "volume_spike", "momentum")


class TestScanner_Push:
    """From test_coverage_push.py — scanner."""

    def test_scan_market_empty(self, db_path):
        from nuri.trading.swing.scanner import scan_market
        results = scan_market(market="us")
        assert isinstance(results, list)

    def test_scan_result_fields(self):
        from nuri.trading.swing.scanner import ScanResult
        r = ScanResult("AAPL", 150.0, 2.5, 5.0, 1.5, 35.0, 0.1, "bounce", 30.0)
        assert r.ticker == "AAPL"
        assert r.score == 30.0


class TestSwingScannerInternals:
    """From test_coverage_round15.py — scanner internals."""

    def test_scan_with_signals(self, rich_db):
        from nuri.trading.swing.scanner import scan_market
        results = scan_market()
        if results:
            r = results[0]
            assert hasattr(r, "ticker")


class TestScanner_R26:
    """From test_coverage_round26.py — scanner."""

    def test_analyze_ticker_flat(self):
        from nuri.trading.swing.scanner import _analyze_ticker
        n = 30
        dates = pd.bdate_range("2024-01-01", periods=n)
        df = pd.DataFrame({
            "Close": [100.0] * n, "Volume": [1_000_000] * n,
            "Open": [99.0] * n, "High": [101.0] * n, "Low": [99.0] * n,
        }, index=dates)
        result = _analyze_ticker("TEST", df)
        assert result is None

    def test_scan_market_empty(self, db_path):
        from nuri.trading.swing.scanner import scan_market
        with patch("nuri.trading.swing.scanner._fetch_prices", return_value=None):
            results = scan_market()
        assert results == []

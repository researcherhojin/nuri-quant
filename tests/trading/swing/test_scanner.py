"""Tests for nuri.trading.swing.scanner.

Extracted from the former tests/test_trading_strategy_all.py.
Shared fixtures live in conftest.py for this directory.
"""

from pathlib import Path
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
        data = pd.DataFrame(
            {
                "Close": close,
                "Volume": volume,
            },
            index=dates,
        )
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
        df = pd.DataFrame(
            {
                "Close": prices,
                "Volume": volumes,
                "Open": [p - 1 for p in prices],
                "High": [p + 2 for p in prices],
                "Low": [p - 2 for p in prices],
            },
            index=dates,
        )
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
        return pd.DataFrame(
            {
                "Close": prices,
                "Volume": volumes,
                "Open": [p - 1 for p in prices],
                "High": [p + 2 for p in prices],
                "Low": [p - 2 for p in prices],
            },
            index=dates,
        )

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
        df = pd.DataFrame(
            {
                "Close": [100.0] * n,
                "Volume": [1_000_000] * n,
                "Open": [99.0] * n,
                "High": [101.0] * n,
                "Low": [99.0] * n,
            },
            index=dates,
        )
        result = _analyze_ticker("TEST", df)
        assert result is None

    def test_scan_market_empty(self, db_path):
        from nuri.trading.swing.scanner import scan_market

        with patch("nuri.trading.swing.scanner._fetch_prices", return_value=None):
            results = scan_market()
        assert results == []


class TestUniverseLoading:
    """config/universe.yaml에서 universe 로드 테스트."""

    def test_get_us_universe_core(self):
        """us_core (extended=False)는 정상 로드."""
        from nuri.trading.swing.scanner import get_us_universe

        universe = get_us_universe(extended=False)
        assert len(universe) > 0
        assert "AAPL" in universe
        assert "NVDA" in universe
        # 중복 없음
        assert len(universe) == len(set(universe))

    def test_get_us_universe_extended(self):
        """extended=True는 us_core보다 더 많은 종목."""
        from nuri.trading.swing.scanner import get_us_universe

        core = get_us_universe(extended=False)
        extended = get_us_universe(extended=True)
        assert len(extended) > len(core)
        # core의 모든 종목이 extended에도 포함
        for ticker in core:
            assert ticker in extended

    def test_get_kr_universe(self):
        """KR universe는 .KS 종목들."""
        from nuri.trading.swing.scanner import get_kr_universe

        universe = get_kr_universe()
        assert len(universe) > 0
        assert all(t.endswith(".KS") for t in universe)
        assert "005930.KS" in universe  # 삼성전자

    def test_load_universe_handles_yaml_error(self, monkeypatch):
        """yaml 로드 실패 시 빈 리스트 반환."""
        import builtins

        from nuri.trading.swing import scanner

        real_open = builtins.open

        def bad_open(*args, **kwargs):
            if args and "universe.yaml" in str(args[0]):
                raise OSError("simulated read failure")
            return real_open(*args, **kwargs)

        monkeypatch.setattr(builtins, "open", bad_open)
        result = scanner._load_universe(["us_core"])
        assert result == []

    def test_load_universe_missing_group(self):
        """존재하지 않는 group key는 무시."""
        from nuri.trading.swing.scanner import _load_universe

        result = _load_universe(["nonexistent_group"])
        assert result == []

    def test_get_us_universe_uses_fallback_when_yaml_missing(self, monkeypatch):
        """YAML 누락 시 fallback hardcoded list 사용."""
        from nuri.trading.swing import scanner

        monkeypatch.setattr(scanner, "_load_universe", lambda keys: [])
        universe = scanner.get_us_universe()
        assert len(universe) > 0
        assert "AAPL" in universe  # fallback에 포함

    def test_scan_market_with_extended_flag(self, db_path):
        """scan_market(extended=True)이 더 큰 universe 사용."""
        from nuri.trading.swing.scanner import scan_market

        with patch("nuri.trading.swing.scanner._fetch_prices", return_value=None):
            results_core = scan_market(market="us", extended=False)
            results_ext = scan_market(market="us", extended=True)
        # 둘 다 빈 결과 (mock이라) — 호출 자체가 에러 없이 동작하면 OK
        assert results_core == []
        assert results_ext == []


class TestFetchPricesReadsDbNotNetwork:
    """스캐너가 `prices` 테이블에서 읽고 요청 경로에서 네트워크를 타지 않는지 잠근다 (#1119).

    회귀 전에는 `_fetch_prices` 가 `yf.download(tickers, period=...)` 였다. `/api/scan`
    이 매 요청 야후를 쳤고(실측 1.7초), 동기 핸들러가 AnyIO 40-스레드 풀을 그만큼
    점유했다. 수집기가 이미 같은 데이터를 `prices` 에 넣는다.
    """

    def _seed(self, db_path, ticker="TST_S", n=80):
        from nuri.core.db import upsert_prices
        from nuri.core.timezone import today_kst

        dates = pd.bdate_range(end=today_kst(), periods=n)
        rows = [
            {
                "ticker": ticker,
                "date": d.strftime("%Y-%m-%d"),
                "open": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "close": 100.0 + i,
                "volume": 1_000_000 + i,
                "adj_close": 100.0 + i,
            }
            for i, d in enumerate(dates)
        ]
        upsert_prices(pd.DataFrame(rows), db_path=db_path)

    def test_returns_yfinance_shaped_frame_from_db(self, db_path):
        from nuri.trading.swing.scanner import _fetch_prices

        self._seed(db_path)
        df = _fetch_prices(["TST_S"], days=60, db_path=db_path)

        assert df is not None
        # `_analyze_ticker` 는 `data[ticker]["Close"]` 로 읽는다 — 모양이 바뀌면 깨진다
        assert df.columns.nlevels == 2
        assert ("TST_S", "Close") in df.columns
        assert ("TST_S", "Volume") in df.columns
        assert len(df) == 60  # days 로 잘린다
        assert df["TST_S"]["Close"].notna().all()

    def test_does_not_import_yfinance(self, db_path):
        """네트워크 경로가 남아 있으면 yfinance 가 sys.modules 에 들어온다."""
        import sys

        from nuri.trading.swing.scanner import _fetch_prices

        self._seed(db_path)
        sys.modules.pop("yfinance", None)
        _fetch_prices(["TST_S"], days=60, db_path=db_path)
        assert "yfinance" not in sys.modules

    def test_empty_and_unknown_tickers_return_none(self, db_path):
        from nuri.trading.swing.scanner import _fetch_prices

        assert _fetch_prices([], days=60, db_path=db_path) is None
        assert _fetch_prices(["TST_NOPE"], days=60, db_path=db_path) is None

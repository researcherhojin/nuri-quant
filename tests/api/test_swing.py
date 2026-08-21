"""Tests for swing — split from test_api_all.py."""

import asyncio
import json
import time as _time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from tests.api._helpers import _csv_file  # noqa: F401


class TestSwing:
    def test_swing_positions(self, client):
        r = client.get("/api/swing/positions")
        assert r.status_code == 200
        data = r.json()
        assert "positions" in data

    def test_swing_entries(self, client):
        r = client.get("/api/swing/entries")
        assert r.status_code == 200

    def test_scan(self, client):
        r = client.get("/api/scan")
        assert r.status_code == 200


class TestBacktestEndpoint:
    """Tests for GET /api/backtest (lines 59-68)."""

    @patch("nuri.trading.strategy.ls_backtest.classify_historical_regimes")
    def test_empty_regimes_returns_error(self, mock_classify, client):
        mock_classify.return_value = pd.DataFrame()
        r = client.get("/api/backtest")
        assert r.status_code == 200
        assert r.json().get("error") == "SPY data insufficient"

    @patch("nuri.trading.strategy.ls_backtest.stress_test")
    @patch("nuri.trading.strategy.ls_backtest.analyze_entry_timing")
    @patch("nuri.trading.strategy.ls_backtest.analyze_per_regime")
    @patch("nuri.trading.strategy.ls_backtest.run_backtest")
    @patch("nuri.trading.strategy.ls_backtest.classify_historical_regimes")
    def test_full_backtest_runs(
        self,
        mock_classify,
        mock_run,
        mock_per_regime,
        mock_timing,
        mock_stress,
        client,
    ):
        mock_classify.return_value = pd.DataFrame({"regime": ["bull"], "return": [0.01]})

        @dataclass
        class FakeRes:
            total_return: float = 25.0
            annual_return: float = 8.0
            sharpe: float = 1.3
            max_drawdown: float = -10.0
            win_rate: float = 0.55
            total_days: int = 200
            regime_changes: int = 3
            transaction_costs: float = 0.4
            spy_total_return: float = 18.0
            spy_annual_return: float = 6.0
            spy_sharpe: float = 0.9
            spy_max_drawdown: float = -15.0
            excess_return: float = 7.0

        @dataclass
        class FakePerf:
            regime: str = "bull"
            total_return: float = 5.0
            sharpe: float = 1.0
            n_days: int = 50

        @dataclass
        class FakeTiming:
            best_lag: int = 1
            score: float = 0.7

        mock_run.return_value = FakeRes()
        mock_per_regime.return_value = [FakePerf()]
        mock_timing.return_value = FakeTiming()
        mock_stress.return_value = {"shock": "ok"}

        r = client.get("/api/backtest")
        assert r.status_code == 200
        data = r.json()
        assert "result" in data
        assert "regimes" in data
        assert "timing" in data
        assert "stress" in data
        assert data["timing"] is not None

    @patch("nuri.trading.strategy.ls_backtest.stress_test")
    @patch("nuri.trading.strategy.ls_backtest.analyze_entry_timing")
    @patch("nuri.trading.strategy.ls_backtest.analyze_per_regime")
    @patch("nuri.trading.strategy.ls_backtest.run_backtest")
    @patch("nuri.trading.strategy.ls_backtest.classify_historical_regimes")
    def test_backtest_timing_none(
        self,
        mock_classify,
        mock_run,
        mock_per_regime,
        mock_timing,
        mock_stress,
        client,
    ):
        mock_classify.return_value = pd.DataFrame({"regime": ["bull"], "return": [0.01]})

        @dataclass
        class FakeRes:
            total_return: float = 1.0
            annual_return: float = 1.0
            sharpe: float = 0.0
            max_drawdown: float = 0.0
            win_rate: float = 0.5
            total_days: int = 1
            regime_changes: int = 0
            transaction_costs: float = 0.0
            spy_total_return: float = 1.0
            spy_annual_return: float = 1.0
            spy_sharpe: float = 0.0
            spy_max_drawdown: float = 0.0
            excess_return: float = 0.0

        mock_run.return_value = FakeRes()
        mock_per_regime.return_value = []
        mock_timing.return_value = None
        mock_stress.return_value = {}

        r = client.get("/api/backtest")
        assert r.status_code == 200
        assert r.json()["timing"] is None


class TestStrategyStatus:
    """Tests for GET /api/strategy/status (lines 149-173)."""

    def test_strategy_status_with_regime(self, client, monkeypatch):
        @dataclass
        class FakeRegime:
            regime: str = "bull_low_vol"
            trend: str = "bull"
            volatility: str = "low"
            confidence: float = 0.8
            details: dict | None = None

            def __post_init__(self):
                if self.details is None:
                    self.details = {}

        @dataclass
        class FakeAction:
            ticker: str = "AAPL"
            action: str = "BUY"

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda: FakeRegime(),
        )
        monkeypatch.setattr(
            "nuri.trading.strategy.longshort.generate_strategy",
            lambda: [FakeAction()],
        )
        monkeypatch.setattr(
            "nuri.trading.strategy.longshort.REGIME_ALLOCATION",
            {"bull_low_vol": {"long": 1.0, "short": 0.0}},
        )
        monkeypatch.setattr(
            "nuri.trading.strategy.position.get_positions_summary",
            lambda: {"open": 0},
        )
        monkeypatch.setattr(
            "nuri.trading.strategy.monitor.daily_pnl_summary",
            lambda: {"pnl": 0.0},
        )
        r = client.get("/api/strategy/status")
        assert r.status_code == 200
        data = r.json()
        assert data["regime"]["regime"] == "bull_low_vol"
        assert data["actions"][0]["ticker"] == "AAPL"

    def test_strategy_status_regime_none(self, client, monkeypatch):
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda: None)
        monkeypatch.setattr("nuri.trading.strategy.longshort.generate_strategy", lambda: [])
        monkeypatch.setattr("nuri.trading.strategy.position.get_positions_summary", lambda: {})
        monkeypatch.setattr("nuri.trading.strategy.monitor.daily_pnl_summary", lambda: {})
        r = client.get("/api/strategy/status")
        assert r.status_code == 200
        assert r.json()["regime"] is None


class TestBacktestEquity:
    """Tests for GET /api/backtest/equity (#89)."""

    @pytest.fixture(autouse=True)
    def clear_interactive_backtest_cache(self):
        from nuri.api.routes import swing

        swing._interactive_backtest_cache.clear()
        yield
        swing._interactive_backtest_cache.clear()

    @patch("nuri.trading.strategy.ls_backtest.classify_historical_regimes")
    def test_returns_error_when_no_spy(self, mock_classify, client):
        mock_classify.return_value = pd.DataFrame()
        r = client.get("/api/backtest/equity")
        assert r.status_code == 200
        assert r.json().get("error") == "SPY data insufficient"

    @patch("nuri.trading.strategy.ls_backtest.run_interactive_backtest")
    @patch("nuri.trading.strategy.ls_backtest.classify_historical_regimes")
    def test_returns_equity_and_metrics(self, mock_classify, mock_bt, client):
        mock_classify.return_value = pd.DataFrame({"regime": ["bull"], "return": [0.01]})

        @dataclass
        class FakeResult:
            total_return: float = 50.0
            annual_return: float = 15.0
            sharpe: float = 1.5
            max_drawdown: float = -12.0
            win_rate: float = 0.58
            total_days: int = 500
            regime_changes: int = 10
            transaction_costs: float = 0.5
            spy_total_return: float = 30.0
            spy_annual_return: float = 10.0
            spy_sharpe: float = 1.0
            spy_max_drawdown: float = -18.0
            excess_return: float = 20.0
            equity_curve: list | None = None

            def __post_init__(self):
                self.equity_curve = self.equity_curve or [
                    {"date": "2024-01-01", "strategy": 0, "spy": 0, "drawdown": 0},
                    {"date": "2024-06-01", "strategy": 25.5, "spy": 15.0, "drawdown": -3.2},
                    {"date": "2025-01-01", "strategy": 50.0, "spy": 30.0, "drawdown": -1.0},
                ]

        mock_bt.return_value = FakeResult()
        r = client.get("/api/backtest/equity?sma=100&period=1Y&sl=-10&tp=30")
        assert r.status_code == 200
        data = r.json()

        # Structure checks
        assert "equity" in data
        assert "drawdown" in data
        assert "metrics" in data
        assert len(data["equity"]) == 3
        assert len(data["drawdown"]) == 3

        # Metrics
        m = data["metrics"]
        assert m["total_return"] == 50.0
        assert m["sharpe"] == 1.5
        assert m["spy_total_return"] == 30.0
        assert m["excess_return"] == 20.0
        mock_classify.assert_called_once_with(sma_period=100)
        mock_bt.assert_called_once()
        args, kwargs = mock_bt.call_args
        pd.testing.assert_frame_equal(args[0], mock_classify.return_value.tail(252).reset_index(drop=True))
        assert kwargs == {"stop_loss_pct": -10, "take_profit_pct": 30}

    @patch("nuri.trading.strategy.ls_backtest.run_interactive_backtest")
    @patch("nuri.trading.strategy.ls_backtest.classify_historical_regimes")
    def test_drawdown_computed_from_equity(self, mock_classify, mock_bt, client):
        mock_classify.return_value = pd.DataFrame({"regime": ["bull"], "return": [0.01]})

        @dataclass
        class FakeResult:
            total_return: float = 10.0
            annual_return: float = 5.0
            sharpe: float = 1.0
            max_drawdown: float = -5.0
            win_rate: float = 0.55
            total_days: int = 100
            regime_changes: int = 2
            transaction_costs: float = 0.1
            spy_total_return: float = 8.0
            spy_annual_return: float = 4.0
            spy_sharpe: float = 0.8
            spy_max_drawdown: float = -6.0
            excess_return: float = 2.0
            equity_curve: list | None = None

            def __post_init__(self):
                self.equity_curve = self.equity_curve or [
                    {"date": "2024-01-01", "strategy": 0, "spy": 0, "drawdown": 0},
                    {"date": "2024-03-01", "strategy": 10, "spy": 8, "drawdown": 0},
                    {"date": "2024-06-01", "strategy": 5, "spy": 6, "drawdown": -5},
                ]

        mock_bt.return_value = FakeResult()
        r = client.get("/api/backtest/equity")
        data = r.json()
        # Drawdown should be computed from equity field
        assert len(data["drawdown"]) == 3
        # All drawdown entries have date and drawdown keys
        for dd in data["drawdown"]:
            assert "date" in dd
            assert "drawdown" in dd

    @patch("nuri.trading.strategy.ls_backtest.run_interactive_backtest")
    @patch("nuri.trading.strategy.ls_backtest.classify_historical_regimes")
    def test_empty_equity_curve(self, mock_classify, mock_bt, client):
        mock_classify.return_value = pd.DataFrame({"regime": ["bull"], "return": [0.01]})

        @dataclass
        class FakeResult:
            total_return: float = 0.0
            annual_return: float = 0.0
            sharpe: float = 0.0
            max_drawdown: float = 0.0
            win_rate: float = 0.0
            total_days: int = 0
            regime_changes: int = 0
            transaction_costs: float = 0.0
            spy_total_return: float = 0.0
            spy_annual_return: float = 0.0
            spy_sharpe: float = 0.0
            spy_max_drawdown: float = 0.0
            excess_return: float = 0.0
            equity_curve: list | None = None

        mock_bt.return_value = FakeResult()
        r = client.get("/api/backtest/equity")
        data = r.json()
        assert data["equity"] == []
        assert data["drawdown"] == []

    @patch("nuri.trading.strategy.ls_backtest.run_interactive_backtest")
    @patch("nuri.trading.strategy.ls_backtest.classify_historical_regimes")
    def test_returns_cached_response_for_same_params(self, mock_classify, mock_bt, client):
        mock_classify.return_value = pd.DataFrame({"regime": ["bull"], "return": [0.01]})

        @dataclass
        class FakeResult:
            total_return: float = 12.0
            annual_return: float = 5.0
            sharpe: float = 1.1
            max_drawdown: float = -4.0
            win_rate: float = 0.52
            total_days: int = 20
            regime_changes: int = 1
            transaction_costs: float = 0.1
            spy_total_return: float = 8.0
            spy_annual_return: float = 4.0
            spy_sharpe: float = 0.8
            spy_max_drawdown: float = -6.0
            excess_return: float = 4.0
            equity_curve: list | None = None

            def __post_init__(self):
                self.equity_curve = self.equity_curve or [
                    {"date": "2024-01-01", "strategy": 0, "spy": 0, "drawdown": 0},
                    {"date": "2024-01-02", "strategy": 1, "spy": 0.5, "drawdown": 0},
                ]

        mock_bt.return_value = FakeResult()

        first = client.get("/api/backtest/equity?sma=50&period=3Y&sl=-7&tp=20")
        second = client.get("/api/backtest/equity?sma=50&period=3Y&sl=-7&tp=20")

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json() == second.json()
        mock_classify.assert_called_once_with(sma_period=50)
        mock_bt.assert_called_once()

    @patch("nuri.trading.strategy.ls_backtest.run_interactive_backtest")
    @patch("nuri.trading.strategy.ls_backtest.classify_historical_regimes")
    def test_cache_expires_after_ttl_and_re_runs(self, mock_classify, mock_bt, client, monkeypatch):
        """Expired TTL entry triggers re-run (swing.py monotonic branch)."""
        mock_classify.return_value = pd.DataFrame({"regime": ["bull"], "return": [0.01]})

        @dataclass
        class FakeResult:
            total_return: float = 15.0
            annual_return: float = 6.0
            sharpe: float = 1.2
            max_drawdown: float = -5.0
            win_rate: float = 0.55
            total_days: int = 30
            regime_changes: int = 2
            transaction_costs: float = 0.2
            spy_total_return: float = 9.0
            spy_annual_return: float = 4.5
            spy_sharpe: float = 0.9
            spy_max_drawdown: float = -7.0
            excess_return: float = 6.0
            equity_curve: list | None = None

            def __post_init__(self):
                self.equity_curve = self.equity_curve or [
                    {"date": "2024-02-01", "strategy": 0, "spy": 0, "drawdown": 0},
                ]

        mock_bt.return_value = FakeResult()

        from nuri.api.routes import swing

        swing._interactive_backtest_cache.clear()

        clock = [0.0]
        monkeypatch.setattr(swing, "monotonic", lambda: clock[0])

        first = client.get("/api/backtest/equity?sma=200&period=5Y&sl=-10&tp=25")
        assert first.status_code == 200
        assert mock_bt.call_count == 1

        clock[0] = swing._BACKTEST_CACHE_TTL_SECONDS + 1.0
        second = client.get("/api/backtest/equity?sma=200&period=5Y&sl=-10&tp=25")
        assert second.status_code == 200
        assert mock_bt.call_count == 2  # re-invoked after TTL


class TestScanCacheSingleFlight:
    """`/scan` 이 요청마다 yfinance 85종목 라이브 왕복을 물던 것을 잠근다 (#1119).

    read 핸들러 안의 서드파티 네트워크 호출 — 캐시 미스 동시 요청이 전부
    scan_market() 을 부르면 스레드풀이 초 단위 네트워크 대기로 잠식된다.
    """

    def _reset(self):
        import nuri.api.routes.swing as swing_mod

        swing_mod._scan_cache.clear()

    def test_concurrent_requests_scan_once(self):
        import threading
        import time as _t

        import nuri.api.routes.swing as swing_mod

        self._reset()
        calls = []
        barrier = threading.Barrier(4)

        def _slow_scan(market="us", top_n=20):
            calls.append(1)
            _t.sleep(0.3)
            return []

        def _worker():
            barrier.wait(timeout=5)
            swing_mod.get_scan()

        with patch("nuri.trading.swing.scanner.scan_market", side_effect=_slow_scan):
            threads = [threading.Thread(target=_worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)

        assert len(calls) == 1, f"동시 4요청이 {len(calls)}회 스캔했다 — single-flight 락이 없다"
        self._reset()

    def test_warm_cache_serves_without_scanning(self):
        import nuri.api.routes.swing as swing_mod

        self._reset()
        with patch("nuri.trading.swing.scanner.scan_market", return_value=[]) as m:
            swing_mod.get_scan()
            swing_mod.get_scan()
        assert m.call_count == 1, "TTL 내 재요청이 다시 스캔했다"
        self._reset()

    def test_cache_key_includes_params(self):
        """market/top 이 다르면 다른 결과 — 키 없이 캐시하면 us 결과가 kr 로 나간다."""
        import nuri.api.routes.swing as swing_mod

        self._reset()
        with patch("nuri.trading.swing.scanner.scan_market", return_value=[]) as m:
            swing_mod.get_scan(market="us", top=20)
            swing_mod.get_scan(market="kr", top=20)
        assert m.call_count == 2
        self._reset()

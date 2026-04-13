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


class TestBacktestEquity:
    """Tests for GET /api/backtest/equity (#89)."""

    @patch("nuri.trading.strategy.ls_backtest.classify_historical_regimes")
    def test_returns_error_when_no_spy(self, mock_classify, client):
        mock_classify.return_value = pd.DataFrame()
        r = client.get("/api/backtest/equity")
        assert r.status_code == 200
        assert r.json().get("error") == "SPY data insufficient"

    @patch("nuri.trading.strategy.ls_backtest.run_backtest")
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
        r = client.get("/api/backtest/equity")
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

    @patch("nuri.trading.strategy.ls_backtest.run_backtest")
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

    @patch("nuri.trading.strategy.ls_backtest.run_backtest")
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

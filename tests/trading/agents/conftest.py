"""Shared fixtures for tests/trading/agents/.

Auto-loaded by pytest. Helpers live in _helpers.py to be importable.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from tests.trading.agents._helpers import _seed_macro, _seed_portfolio, _seed_prices, _seed_ticker  # noqa: F401


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture
def agent_data(db_path):
    """에이전트 테스트용 데이터 (포트폴리오 + 가격)."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("test", "TEST", 100, 50.0, "USD", "Technology"),
        )

    dates = pd.bdate_range("2024-01-01", periods=250)
    close = np.linspace(40, 80, 250) + np.random.normal(0, 1, 250)
    df = pd.DataFrame({
        "ticker": "TEST",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.99, "high": close * 1.01,
        "low": close * 0.98, "close": close,
        "volume": [1000000] * 250, "adj_close": close,
    })
    upsert_prices(df, db_path)
    return db_path


@pytest.fixture
def rich_db(db_path):
    """풍부한 테스트 데이터."""
    from nuri.core.timezone import today_kst
    today = today_kst()

    with get_db(db_path) as conn:
        for t, q, p, s in [("AAPL", 10, 150, "Technology"), ("MSFT", 5, 300, "Software"),
                            ("TSLA", 8, 340, "EV/AI"), ("SPY", 50, 450, "Index")]:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)", ("test", t, q, p, "USD", s))

    dates = pd.date_range(end=today, periods=300)
    for ticker, base in [("SPY", 400), ("AAPL", 140), ("MSFT", 280), ("TSLA", 300)]:
        close = np.linspace(base, base * 1.2, 300) + np.random.normal(0, 1, 300)
        df = pd.DataFrame({
            "ticker": ticker, "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.99, "high": close * 1.01,
            "low": close * 0.98, "close": close,
            "volume": [1000000] * 300, "adj_close": close,
        })
        upsert_prices(df, db_path)

    with get_db(db_path) as conn:
        for d in dates[-50:]:
            ds = d.strftime("%Y-%m-%d")
            conn.execute("INSERT OR IGNORE INTO signals (ticker, date, rsi_14, sma_20, sma_50, sma_200) "
                         "VALUES (?, ?, ?, ?, ?, ?)", ("SPY", ds, 55.0, 480.0, 470.0, 440.0))

    upsert_macro([
        {"indicator": "vix", "date": today, "value": 18.0, "source": "test"},
        {"indicator": "fear_greed", "date": today, "value": 55.0, "source": "test"},
        {"indicator": "sp500_yoy", "date": today, "value": 15.0, "source": "test"},
        {"indicator": "gdp_growth", "date": today, "value": 2.5, "source": "test"},
        {"indicator": "unemployment", "date": today, "value": 3.8, "source": "test"},
    ], db_path)
    return db_path

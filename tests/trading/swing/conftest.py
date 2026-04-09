"""Shared fixtures for tests/trading/swing/.

Extracted from the former tests/test_trading_strategy_all.py.
Auto-loaded by pytest for this directory.
"""
import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_prices
from nuri.core.timezone import today_kst


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture
def bull_data(db_path):
    """상승장 데이터: SPY 상승 + VIX 낮음."""
    dates = pd.date_range(end=today_kst(), periods=300)
    close = np.linspace(100, 200, 300) + np.random.normal(0, 1, 300)

    for ticker in ["SPY", "QQQ", "TEST"]:
        df = pd.DataFrame({
            "ticker": ticker,
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.99, "high": close * 1.01,
            "low": close * 0.98, "close": close,
            "volume": [50000000] * 300, "adj_close": close,
        })
        upsert_prices(df, db_path)

    upsert_macro([{
        "indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"),
        "value": 15.0, "source": "test",
    }], db_path)

    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test", "TEST", 100, 150.0, "USD"),
        )
    return db_path


@pytest.fixture
def rich_db(db_path):
    """풍부한 테스트 데이터 — 포트폴리오 + 300일 가격 + 매크로."""
    today = today_kst()

    with get_db(db_path) as conn:
        for t, q, p, s in [("AAPL", 10, 150, "Technology"), ("MSFT", 5, 300, "Software"),
                            ("TSLA", 8, 340, "SectorA"), ("NVDA", 3, 130, "Semiconductor"),
                            ("SPY", 50, 450, "Index")]:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)", ("test", t, q, p, "USD", s))

    dates = pd.date_range(end=today, periods=300)
    for ticker, base in [("SPY", 400), ("AAPL", 140), ("MSFT", 280), ("TSLA", 300), ("NVDA", 110)]:
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
        {"indicator": "usd_krw", "date": today, "value": 1380.0, "source": "test"},
    ], db_path)
    return db_path

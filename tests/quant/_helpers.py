"""Test helper functions for tests/quant/.

Imported explicitly by test files (conftest.py only auto-loads fixtures).
"""
from datetime import timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from nuri.core.timezone import kst_now, today_kst


def _insert_spy_data(db_path, close_array, dates=None):
    """SPY helper (from test_regime_special)."""
    n = len(close_array)
    if dates is None:
        dates = pd.date_range(end=today_kst(), periods=n)
    df = pd.DataFrame({
        "ticker": "SPY",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close_array * 0.999,
        "high": close_array * 1.01,
        "low": close_array * 0.99,
        "close": close_array,
        "volume": [50_000_000] * n,
        "adj_close": close_array,
    })
    upsert_prices(df, db_path)
    return dates


def _insert_spy_data_trend(db_path, n_days=300, trend="bull", last_date=None):
    """SPY helper (from test_data_integrity)."""
    if last_date is None:
        last_date = today_kst()
    dates = pd.date_range(end=last_date, periods=n_days, freq="D")

    if trend == "bull":
        close = np.linspace(100, 200, n_days) + np.random.default_rng(42).normal(0, 0.5, n_days)
    elif trend == "bear":
        up = np.linspace(150, 200, n_days // 3 * 2)
        down = np.linspace(200, 130, n_days - len(up))
        close = np.concatenate([up, down]) + np.random.default_rng(42).normal(0, 0.3, n_days)
    else:  # sideways
        close = np.full(n_days, 150.0) + np.random.default_rng(42).normal(0, 1, n_days)

    df = pd.DataFrame({
        "ticker": "SPY",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.99,
        "high": close * 1.01,
        "low": close * 0.98,
        "close": close,
        "volume": [50000000] * n_days,
        "adj_close": close,
    })
    upsert_prices(df, db_path)
    return [d.strftime("%Y-%m-%d") for d in dates]


def _seed_spy_data(db_path, days=300, start_price=400.0):
    """Seed SPY price data (from test_coverage_round27)."""
    dates = pd.bdate_range(end="2025-03-28", periods=days)
    with get_db(db_path) as conn:
        for i, d in enumerate(dates):
            price = start_price + i * 0.5 + np.sin(i / 20) * 10
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                ("SPY", d.strftime("%Y-%m-%d"), price - 1, price + 2, price - 2, price, 1000000),
            )


def _seed_portfolio(db_path, tickers=None):
    """Seed portfolio (from test_coverage_round27)."""
    if tickers is None:
        tickers = [("AAPL", 100.0, 10), ("TSLA", 200.0, 5), ("NVDA", 150.0, 8)]
    with get_db(db_path) as conn:
        for ticker, avg_price, qty in tickers:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, sector, currency) "
                "VALUES (?,?,?,?,?,?)",
                ("test", ticker, qty, avg_price, "Technology", "USD"),
            )


def _seed_prices(db_path, ticker="AAPL", days=60, start_price=150.0):
    """Seed price data (from test_coverage_round27)."""
    dates = pd.bdate_range(end="2025-03-28", periods=days)
    with get_db(db_path) as conn:
        for i, d in enumerate(dates):
            price = start_price + np.sin(i / 10) * 10
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                (ticker, d.strftime("%Y-%m-%d"), price - 1, price + 2, price - 2, price, 500000 + i * 10000),
            )


def _seed_macro(db_path):
    """Seed macro data (from test_coverage_round27)."""
    with get_db(db_path) as conn:
        conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)", ("vix", "2025-03-28", 18.5))
        conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)", ("put_call_ratio", "2025-03-28", 0.85))
        conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)", ("us_10y_yield", "2025-03-28", 4.2))
        conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)", ("us_3m_yield", "2025-03-28", 4.5))
        conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)", ("fear_greed", "2025-03-28", 45))
        conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)", ("usd_krw", "2025-03-28", 1400.0))

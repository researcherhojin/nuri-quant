"""Test helper functions for tests/trading/agents/.

Imported explicitly by test files (conftest.py only auto-loads fixtures).
"""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices


def _seed_portfolio(db_path, tickers=None):
    """Insert sample portfolio rows."""
    tickers = tickers or [("test", "AAPL", 10, 150.0, "USD", "Technology"),
                          ("test", "MSFT", 5, 300.0, "USD", "Technology"),
                          ("test", "JNJ", 20, 160.0, "USD", "Health")]
    with get_db(db_path) as conn:
        for account, ticker, qty, avg_price, currency, sector in tickers:
            conn.execute(
                "INSERT OR REPLACE INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (account, ticker, qty, avg_price, currency, sector),
            )


def _seed_prices(db_path, ticker="AAPL", close=170.0, high=180.0, days=5):
    """Insert sample price rows."""
    with get_db(db_path) as conn:
        for i in range(days):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ticker, date_str, close - 2, high, close - 5, close, 1000000),
            )


def _seed_macro(db_path, indicator="vix", value=20.0, days=1):
    """Insert sample macro rows."""
    with get_db(db_path) as conn:
        for i in range(days):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT OR REPLACE INTO macro (indicator, date, value, source) VALUES (?, ?, ?, ?)",
                (indicator, date_str, value, "test"),
            )


def _seed_ticker(db_path, ticker, n=70, base_price=50.0):
    """Seed price data for a ticker."""
    dates = pd.bdate_range(end="2025-03-28", periods=n).strftime("%Y-%m-%d").tolist()
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO portfolio (account, ticker, quantity, avg_price) "
            "VALUES (?, ?, ?, ?)",
            ("test", ticker, 10, base_price),
        )
        for i, d in enumerate(dates):
            price = base_price + np.sin(i / 5) * 5 + i * 0.02
            conn.execute(
                "INSERT OR IGNORE INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ticker, d, price - 0.3, price + 0.5, price - 0.5, price, 100000),
            )

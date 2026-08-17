"""Test helper functions for tests/trading/recommend/.

Imported explicitly by test files (conftest.py only auto-loads fixtures).
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, query, upsert_macro, upsert_portfolio, upsert_prices
from nuri.core.timezone import kst_now, today_kst


def _seed_recommendation(db_path, date, ticker, action, entry_price, confidence=70.0):
    """추천 레코드 삽입."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO recommendations (date, ticker, action, confidence, entry_price) VALUES (?, ?, ?, ?, ?)",
            (date, ticker, action, confidence, entry_price),
        )


def _seed_portfolio_r23(db_path, tickers=None):
    """Insert sample portfolio rows (from test_coverage_round23)."""
    tickers = tickers or [
        ("test", "AAPL", 10, 150.0, "USD", "Technology"),
        ("test", "MSFT", 5, 300.0, "USD", "Technology"),
        ("test", "JNJ", 20, 160.0, "USD", "Health"),
    ]
    with get_db(db_path) as conn:
        for account, ticker, qty, avg_price, currency, sector in tickers:
            conn.execute(
                "INSERT OR REPLACE INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (account, ticker, qty, avg_price, currency, sector),
            )


def _seed_prices_r23(db_path, ticker="AAPL", close=170.0, high=180.0, days=5):
    """Insert sample price rows (from test_coverage_round23)."""
    with get_db(db_path) as conn:
        for i in range(days):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ticker, date_str, close - 2, high, close - 5, close, 1000000),
            )


def _seed_macro_r23(db_path, indicator="vix", value=20.0, days=1):
    """Insert sample macro rows (from test_coverage_round23)."""
    with get_db(db_path) as conn:
        for i in range(days):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT OR REPLACE INTO macro (indicator, date, value, source) VALUES (?, ?, ?, ?)",
                (indicator, date_str, value, "test"),
            )


def _seed_portfolio_nm(db_path, holdings=None):
    """테스트 포트폴리오 데이터 삽입 (from test_new_modules)."""
    if holdings is None:
        holdings = [
            ("test", "TSLA", 33, 200.0, "USD", "SectorA"),
            ("test", "NVDA", 20, 100.0, "USD", "Semiconductor"),
            ("test", "GOOGL", 5, 269.91, "USD", "BigTech"),
            ("test", "BBB", 96, 20.0, "USD", "SectorB"),
            ("test", "LLY", 1, 1087.10, "USD", "Pharma"),
        ]
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            holdings,
        )


def _seed_prices_nm(db_path, prices=None):
    """테스트 가격 데이터 삽입 (from test_new_modules)."""
    if prices is None:
        prices = [
            ("2026-03-27", "TSLA", 355.0, 365.0, 350.0, 360.17, 1000000),
            ("2026-03-27", "NVDA", 165.0, 170.0, 163.0, 167.99, 2000000),
            ("2026-03-27", "GOOGL", 270.0, 278.0, 268.0, 274.26, 500000),
            ("2026-03-27", "BBB", 11.0, 12.0, 10.5, 11.44, 300000),
            ("2026-03-27", "LLY", 880.0, 895.0, 875.0, 888.34, 100000),
        ]
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO prices (date, ticker, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            prices,
        )


def _seed_fundamentals_nm(db_path, data=None):
    """펀더멘탈 데이터 삽입 (from test_new_modules)."""
    if data is None:
        data = [
            ("2026-03-27", "TSLA", 327.0),
            ("2026-03-27", "NVDA", 37.0),
            ("2026-03-27", "GOOGL", 22.0),
            ("2026-03-27", "LLY", 43.0),
        ]
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO fundamentals (date, ticker, pe_ratio) VALUES (?, ?, ?)",
            data,
        )


def _seed_estimates_nm(db_path, data=None):
    """애널리스트 목표가 삽입 (from test_new_modules)."""
    if data is None:
        data = [
            ("2026-03-27", "TSLA", 393.51),
            ("2026-03-27", "NVDA", 273.61),
            ("2026-03-27", "GOOGL", 376.57),
        ]
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO estimates (date, ticker, target_mean) VALUES (?, ?, ?)",
            data,
        )

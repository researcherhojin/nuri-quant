"""Shared fixtures for tests/trading/recommend/.

Auto-loaded by pytest. Helpers live in _helpers.py to be importable.
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
from tests.trading.recommend._helpers import (  # noqa: F401
    _seed_estimates_nm,
    _seed_fundamentals_nm,
    _seed_macro_r23,
    _seed_portfolio_nm,
    _seed_portfolio_r23,
    _seed_prices_nm,
    _seed_prices_r23,
    _seed_recommendation,
)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def db_path_with_dbmod(tmp_path, monkeypatch):
    """db_path + monkeypatch DB_PATH for modules that use default path."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture
def market_data(db_path):
    """포트폴리오 + 가격 데이터 (from test_recommend)."""
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("test", "TEST1", 100, 50.0, "USD", "Technology"),
                ("test", "TEST2", 50, 80.0, "USD", "Health Care"),
            ],
        )

    dates = pd.bdate_range("2025-01-01", periods=60)
    prices_down = np.linspace(100, 70, 30)
    prices_up = np.linspace(70, 110, 30)
    close1 = np.concatenate([prices_down, prices_up])
    close2 = np.concatenate([np.linspace(80, 60, 30), np.linspace(60, 90, 30)])

    for ticker, close in [("TEST1", close1), ("TEST2", close2)]:
        df = pd.DataFrame(
            {
                "ticker": ticker,
                "date": [d.strftime("%Y-%m-%d") for d in dates],
                "open": close * 0.99,
                "high": close * 1.02,
                "low": close * 0.98,
                "close": close,
                "volume": [1000000] * 60,
                "adj_close": close,
            }
        )
        upsert_prices(df, db_path)

    return db_path


@pytest.fixture
def rich_db(tmp_path, monkeypatch):
    """Full DB with portfolio, prices (SPY + tickers), macro (from test_coverage_round18)."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    upsert_portfolio(
        [
            {
                "account": "test",
                "ticker": "AAPL",
                "quantity": 10,
                "avg_price": 190,
                "currency": "USD",
                "sector": "Tech",
            },
            {
                "account": "test",
                "ticker": "NVDA",
                "quantity": 5,
                "avg_price": 130,
                "currency": "USD",
                "sector": "Semiconductor",
            },
        ],
        path,
    )

    # 윈도우 끝을 오늘에 고정한다. 소비 테스트가 `now - N일` 로 행을 찾으므로
    # 시작일을 못박으면 캘린더가 지나가는 순간 조용히 조회 범위 밖이 된다 —
    # `test_90d_tracking` 이 2026-08-05 부터 그렇게 깨졌다(구간 끝 2026-05-01
    # vs now-95d = 2026-05-07). 문서-only PR 은 `run_backend` 경로 필터에
    # 걸려 백엔드 수트를 안 돌리므로 CI 가 5일간 초록인 채였다.
    dates = pd.bdate_range(end=today_kst(), periods=500, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA"]:
        base = {"SPY": 450, "AAPL": 170, "NVDA": 120}[t]
        for i, d in enumerate(dates):
            p = base + i * 0.2 + np.sin(i / 20) * 5
            rows.append(
                {
                    "ticker": t,
                    "date": d.strftime("%Y-%m-%d"),
                    "open": p,
                    "high": p + 3,
                    "low": p - 2,
                    "close": p + 1,
                    "volume": 50_000_000,
                    "adj_close": p + 1,
                }
            )
    upsert_prices(pd.DataFrame(rows), path)

    macro = []
    for i, d in enumerate(dates):
        ds = d.strftime("%Y-%m-%d")
        macro.append({"indicator": "vix", "date": ds, "value": 15 + np.sin(i / 30) * 8, "source": "test"})
        macro.append({"indicator": "fear_greed", "date": ds, "value": 50 + np.sin(i / 25) * 30, "source": "test"})
    upsert_macro(macro, path)
    return path


@pytest.fixture
def rich_db_full(tmp_path, monkeypatch):
    """Full DB with fundamentals, estimates, superinvestors (from test_coverage_round20)."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    upsert_portfolio(
        [
            {
                "account": "test",
                "ticker": "AAPL",
                "quantity": 10,
                "avg_price": 150.0,
                "currency": "USD",
                "sector": "Technology",
            },
            {
                "account": "test",
                "ticker": "NVDA",
                "quantity": 5,
                "avg_price": 120.0,
                "currency": "USD",
                "sector": "Semiconductor",
            },
            {
                "account": "test",
                "ticker": "005930.KS",
                "quantity": 100,
                "avg_price": 70000.0,
                "currency": "KRW",
                "sector": "반도체",
            },
        ],
        path,
    )

    dates = pd.date_range("2024-01-01", periods=500, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA", "005930.KS"]:
        base = {"SPY": 450, "AAPL": 150, "NVDA": 120, "005930.KS": 70000}[t]
        for i, d in enumerate(dates):
            p = base + i * 0.3 + np.sin(i / 20) * 5
            rows.append(
                {
                    "ticker": t,
                    "date": d.strftime("%Y-%m-%d"),
                    "open": p,
                    "high": p + 4,
                    "low": p - 3,
                    "close": p + 1,
                    "volume": 50_000_000,
                    "adj_close": p + 1,
                }
            )
    upsert_prices(pd.DataFrame(rows), path)

    macro_records = []
    for i, d in enumerate(dates):
        ds = d.strftime("%Y-%m-%d")
        macro_records.append({"indicator": "vix", "date": ds, "value": 15 + np.sin(i / 30) * 8, "source": "test"})
        macro_records.append(
            {"indicator": "fear_greed", "date": ds, "value": 50 + np.sin(i / 25) * 30, "source": "test"}
        )
        macro_records.append({"indicator": "usd_krw", "date": ds, "value": 1350.0, "source": "test"})
    upsert_macro(macro_records, path)

    with get_db(path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO fundamentals (ticker, date, pe_ratio, roe, revenue_growth, market_cap, beta, debt_to_equity)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("AAPL", "2025-01-01", 28.0, 0.35, 0.08, 3e12, 1.2, 1.5),
        )
        conn.execute(
            "INSERT OR REPLACE INTO fundamentals (ticker, date, pe_ratio, roe, revenue_growth, market_cap, beta, debt_to_equity)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("NVDA", "2025-01-01", 55.0, 0.45, 0.25, 2e12, 1.8, 0.5),
        )
        conn.execute(
            "INSERT OR REPLACE INTO estimates (ticker, date, recommendation, target_high, target_low, target_mean, target_median, num_analysts, current_price)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("AAPL", "2025-01-01", "buy", 250.0, 180.0, 220.0, 215.0, 30, 200.0),
        )
        conn.execute(
            "INSERT OR REPLACE INTO estimates (ticker, date, recommendation, target_high, target_low, target_mean, target_median, num_analysts, current_price)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("NVDA", "2025-01-01", "strong_buy", 300.0, 200.0, 270.0, 265.0, 35, 250.0),
        )

    return path


@pytest.fixture
def full_db(tmp_path, monkeypatch):
    """풍부한 가격 + 시그널 + 매크로 (from test_sixty_percent)."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    today = today_kst()

    with get_db(path) as conn:
        for t, q, p, s in [("AAPL", 10, 150, "Technology"), ("MSFT", 5, 300, "Software"), ("TSLA", 8, 340, "SectorA")]:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test", t, q, p, "USD", s),
            )

    dates = pd.date_range(end=today, periods=400)
    for ticker, base in [("SPY", 400), ("AAPL", 140), ("MSFT", 280), ("TSLA", 300)]:
        np.random.seed(42)
        close = np.linspace(base, base * 1.2, 400)
        noise = np.random.normal(0, base * 0.01, 400)
        close = close + noise
        high = close * 1.01
        low = close * 0.99
        volume = np.random.randint(500000, 2000000, 400)

        df = pd.DataFrame(
            {
                "ticker": ticker,
                "date": [d.strftime("%Y-%m-%d") for d in dates],
                "open": close * 0.998,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "adj_close": close,
            }
        )
        upsert_prices(df, path)

    with get_db(path) as conn:
        for i, d in enumerate(dates[-100:]):
            ds = d.strftime("%Y-%m-%d")
            for ticker in ["AAPL", "MSFT", "TSLA", "SPY"]:
                rsi = 30 + (i % 40)
                sma20 = 155 + i * 0.1
                sma50 = 150 + i * 0.08
                sma200 = 145 + i * 0.05
                bb_upper = sma20 * 1.04
                bb_lower = sma20 * 0.96
                macd = 0.5 * np.sin(i / 10) + np.random.normal(0, 0.2)
                macd_signal = 0.5 * np.sin((i - 3) / 10)

                conn.execute(
                    "INSERT OR IGNORE INTO signals "
                    "(ticker, date, rsi_14, sma_20, sma_50, sma_200, "
                    "bb_upper, bb_lower, bb_middle, macd, macd_signal) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (ticker, ds, rsi, sma20, sma50, sma200, bb_upper, bb_lower, sma20, macd, macd_signal),
                )

    upsert_macro(
        [
            {"indicator": "vix", "date": today, "value": 18.0, "source": "test"},
            {"indicator": "fear_greed", "date": today, "value": 55.0, "source": "test"},
            {"indicator": "sp500_yoy", "date": today, "value": 15.0, "source": "test"},
            {"indicator": "usd_krw", "date": today, "value": 1380.0, "source": "test"},
        ],
        path,
    )

    return path

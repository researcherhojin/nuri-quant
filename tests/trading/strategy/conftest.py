"""Shared fixtures for tests/trading/strategy/.

Extracted from the former tests/test_trading_strategy_all.py.
Auto-loaded by pytest for this directory.
"""
import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
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


@pytest.fixture
def backtest_data(db_path):
    """5년 SPY + SH + VIX 시뮬레이션 데이터."""
    dates = pd.bdate_range("2020-01-01", periods=1200)

    phase1 = np.linspace(300, 450, 400)
    phase2 = np.linspace(450, 350, 200)
    phase3 = np.linspace(350, 500, 600)
    spy_close = np.concatenate([phase1, phase2, phase3]) + np.random.normal(0, 2, 1200)

    sh_close = 40 - (spy_close - 400) * 0.08 + np.random.normal(0, 0.5, 1200)

    for ticker, close in [("SPY", spy_close), ("SH", sh_close)]:
        df = pd.DataFrame({
            "ticker": ticker,
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.999, "high": close * 1.005,
            "low": close * 0.995, "close": close,
            "volume": [50000000] * 1200, "adj_close": close,
        })
        upsert_prices(df, db_path)

    vix = np.concatenate([
        np.full(400, 15) + np.random.normal(0, 2, 400),
        np.full(200, 30) + np.random.normal(0, 3, 200),
        np.full(600, 16) + np.random.normal(0, 2, 600),
    ]).clip(10, 80)

    records = [{"indicator": "vix", "date": dates[i].strftime("%Y-%m-%d"),
                "value": float(vix[i]), "source": "test"} for i in range(1200)]
    upsert_macro(records, db_path)
    return db_path


@pytest.fixture
def market_data(db_path):
    """가격 + 포트폴리오 테스트 데이터."""
    prices = []
    for i in range(200):
        date = f"2025-{(i // 30 + 1):02d}-{(i % 28 + 1):02d}"
        prices.append({
            "ticker": "AAPL", "date": date,
            "open": 150 + i * 0.1, "high": 152 + i * 0.1,
            "low": 148 + i * 0.1, "close": 150 + i * 0.1,
            "volume": 1000000, "adj_close": 150 + i * 0.1,
        })
        prices.append({
            "ticker": "MSFT", "date": date,
            "open": 300 + i * 0.15, "high": 303 + i * 0.15,
            "low": 298 + i * 0.15, "close": 300 + i * 0.15,
            "volume": 800000, "adj_close": 300 + i * 0.15,
        })
    upsert_prices(pd.DataFrame(prices), db_path)
    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10,
         "avg_price": 150, "currency": "USD", "sector": "Tech"},
        {"account": "test", "ticker": "MSFT", "quantity": 5,
         "avg_price": 300, "currency": "USD", "sector": "Tech"},
    ], db_path)
    return db_path

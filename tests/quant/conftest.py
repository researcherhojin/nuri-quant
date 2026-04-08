"""Shared fixtures for tests/quant/.

Auto-loaded by pytest. Helpers live in _helpers.py to be importable.
"""
from datetime import timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from nuri.core.timezone import kst_now, today_kst
from tests.quant._helpers import (  # noqa: F401
    _insert_spy_data,
    _insert_spy_data_trend,
    _seed_macro,
    _seed_portfolio,
    _seed_prices,
    _seed_spy_data,
)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def db_path_mp(tmp_path, monkeypatch):
    """db_path with DB_PATH monkeypatched (for modules that use the global)."""
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture
def bull_market(db_path):
    dates = pd.date_range(end=today_kst(), periods=300)
    close = np.linspace(100, 200, 300) + np.random.normal(0, 1, 300)
    df = pd.DataFrame({
        "ticker": "SPY",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.99, "high": close * 1.01,
        "low": close * 0.98, "close": close,
        "volume": [50000000] * 300, "adj_close": close,
    })
    upsert_prices(df, db_path)
    upsert_macro([
        {"indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"), "value": 15.0, "source": "test"},
        {"indicator": "fear_greed", "date": dates[-1].strftime("%Y-%m-%d"), "value": 65.0, "source": "test"},
    ], db_path)
    return db_path


@pytest.fixture
def bear_market(db_path):
    dates = pd.date_range(end=today_kst(), periods=300)
    up = np.linspace(150, 200, 200)
    down = np.linspace(200, 130, 100)
    close = np.concatenate([up, down]) + np.random.normal(0, 0.5, 300)
    df = pd.DataFrame({
        "ticker": "SPY",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.99, "high": close * 1.01,
        "low": close * 0.98, "close": close,
        "volume": [50000000] * 300, "adj_close": close,
    })
    upsert_prices(df, db_path)
    upsert_macro([
        {"indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"), "value": 32.0, "source": "test"},
        {"indicator": "fear_greed", "date": dates[-1].strftime("%Y-%m-%d"), "value": 20.0, "source": "test"},
    ], db_path)
    return db_path


@pytest.fixture
def euphoria_market(db_path):
    close = np.linspace(100, 200, 300) + np.random.normal(0, 0.5, 300)
    dates = _insert_spy_data(db_path, close)
    upsert_macro([
        {"indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"), "value": 10.0, "source": "test"},
        {"indicator": "fear_greed", "date": dates[-1].strftime("%Y-%m-%d"), "value": 85.0, "source": "test"},
    ], db_path)
    return db_path


@pytest.fixture
def recovery_market(db_path):
    phase1 = np.full(100, 180.0) + np.random.normal(0, 0.3, 100)
    phase2 = np.linspace(180, 130, 100) + np.random.normal(0, 0.3, 100)
    phase3 = np.linspace(130, 190, 100) + np.random.normal(0, 0.3, 100)
    close = np.concatenate([phase1, phase2, phase3])
    dates = _insert_spy_data(db_path, close)
    upsert_macro([
        {"indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"), "value": 18.0, "source": "test"},
        {"indicator": "fear_greed", "date": dates[-1].strftime("%Y-%m-%d"), "value": 55.0, "source": "test"},
    ], db_path)
    return db_path


@pytest.fixture
def factor_data(db_path_mp):
    """Factor tests: prices + signals + macro."""
    dates = pd.bdate_range("2024-01-01", periods=60)
    for ticker, base in [("AAPL", 150), ("MSFT", 300), ("GOOG", 140)]:
        close = np.linspace(base, base * 1.2, 60) + np.random.normal(0, 1, 60)
        df = pd.DataFrame({
            "ticker": ticker,
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.99, "high": close * 1.02,
            "low": close * 0.97, "close": close,
            "volume": [1000000] * 60, "adj_close": close,
        })
        upsert_prices(df, db_path_mp)
    with get_db(db_path_mp) as conn:
        for ticker in ["AAPL", "MSFT", "GOOG"]:
            conn.execute("INSERT INTO signals (ticker, date, rsi_14) VALUES (?, ?, ?)",
                         (ticker, dates[-1].strftime("%Y-%m-%d"), 55.0))
    upsert_macro([{
        "indicator": "fear_greed",
        "date": dates[-1].strftime("%Y-%m-%d"),
        "value": 60.0, "source": "test",
    }], db_path_mp)
    with get_db(db_path_mp) as conn:
        for ticker in ["AAPL", "MSFT", "GOOG"]:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test", ticker, 10, 100.0, "USD", "Technology"),
            )
    return db_path_mp


@pytest.fixture
def sample_prices(db_path):
    """60-day V-shape prices (from test_validation)."""
    dates = pd.bdate_range("2025-01-01", periods=60)
    prices_down = np.linspace(100, 70, 30)
    prices_up = np.linspace(70, 110, 30)
    close = np.concatenate([prices_down, prices_up])
    df = pd.DataFrame({
        "ticker": "TEST",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.99, "high": close * 1.02,
        "low": close * 0.98, "close": close,
        "volume": [1000000] * 60, "adj_close": close,
    })
    upsert_prices(df, db_path)
    return db_path


@pytest.fixture
def long_prices(db_path):
    """300-day SMA cross prices (from test_validation)."""
    dates = pd.bdate_range("2024-01-01", periods=300)
    phase1 = np.linspace(100, 180, 150)
    phase2 = np.linspace(180, 120, 80)
    phase3 = np.linspace(120, 160, 70)
    close = np.concatenate([phase1, phase2, phase3]) + np.random.normal(0, 0.5, 300)
    df = pd.DataFrame({
        "ticker": "LONG",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.99, "high": close * 1.01,
        "low": close * 0.98, "close": close,
        "volume": [1000000] * 300, "adj_close": close,
    })
    upsert_prices(df, db_path)
    return db_path


@pytest.fixture
def full_db(db_path_mp):
    """Rich DB with prices + signals + macro (from test_sixty_percent)."""
    today = today_kst()
    with get_db(db_path_mp) as conn:
        for t, q, p, s in [("AAPL", 10, 150, "Technology"), ("MSFT", 5, 300, "Software"),
                            ("TSLA", 8, 340, "EV/AI")]:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)", ("test", t, q, p, "USD", s))
    dates = pd.date_range(end=today, periods=400)
    for ticker, base in [("SPY", 400), ("AAPL", 140), ("MSFT", 280), ("TSLA", 300)]:
        np.random.seed(42)
        close = np.linspace(base, base * 1.2, 400)
        noise = np.random.normal(0, base * 0.01, 400)
        close = close + noise
        high = close * 1.01
        low = close * 0.99
        volume = np.random.randint(500000, 2000000, 400)
        df = pd.DataFrame({
            "ticker": ticker, "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.998, "high": high, "low": low,
            "close": close, "volume": volume, "adj_close": close,
        })
        upsert_prices(df, db_path_mp)
    with get_db(db_path_mp) as conn:
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
                    (ticker, ds, rsi, sma20, sma50, sma200,
                     bb_upper, bb_lower, sma20, macd, macd_signal),
                )
    upsert_macro([
        {"indicator": "vix", "date": today, "value": 18.0, "source": "test"},
        {"indicator": "fear_greed", "date": today, "value": 55.0, "source": "test"},
        {"indicator": "sp500_yoy", "date": today, "value": 15.0, "source": "test"},
        {"indicator": "usd_krw", "date": today, "value": 1380.0, "source": "test"},
    ], db_path_mp)
    return db_path_mp


@pytest.fixture
def rich_db(tmp_path, monkeypatch):
    """Rich DB: portfolio + 500 day prices + macro (from test_coverage_round19)."""
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10,
         "avg_price": 190, "currency": "USD", "sector": "Tech"},
        {"account": "test", "ticker": "NVDA", "quantity": 5,
         "avg_price": 130, "currency": "USD", "sector": "Semiconductor"},
        {"account": "test", "ticker": "005930.KS", "quantity": 4,
         "avg_price": 60000, "currency": "KRW", "sector": "Semiconductor"},
    ], path)
    dates = pd.date_range("2024-01-02", periods=500, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA", "005930.KS", "VOO",
              "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLU", "XLY", "XLC", "XLRE"]:
        base = {"SPY": 450, "AAPL": 170, "NVDA": 120, "005930.KS": 58000,
                "VOO": 440}.get(t, 100)
        for i, d in enumerate(dates):
            p = base + i * 0.2 + np.sin(i / 20) * 3
            rows.append({"ticker": t, "date": d.strftime("%Y-%m-%d"),
                         "open": p - 0.5, "high": p + 3, "low": p - 2,
                         "close": p + 1, "volume": 50_000_000, "adj_close": p + 1})
    upsert_prices(pd.DataFrame(rows), path)
    macros = []
    for i, d in enumerate(dates):
        ds = d.strftime("%Y-%m-%d")
        macros.append({"indicator": "vix", "date": ds, "value": 15 + np.sin(i / 30) * 8, "source": "test"})
        macros.append({"indicator": "fear_greed", "date": ds, "value": 50 + np.sin(i / 25) * 30, "source": "test"})
        macros.append({"indicator": "us_10y_yield", "date": ds, "value": 4.2 + np.sin(i / 40) * 0.5, "source": "test"})
        macros.append({"indicator": "us_3m_yield", "date": ds, "value": 5.0 - np.sin(i / 40) * 0.3, "source": "test"})
        macros.append({"indicator": "put_call_ratio", "date": ds, "value": 0.8 + np.sin(i / 15) * 0.4, "source": "test"})
    macros.append({"indicator": "cpi_yoy", "date": dates[-1].strftime("%Y-%m-%d"), "value": 3.0, "source": "test"})
    macros.append({"indicator": "gdp_growth", "date": dates[-1].strftime("%Y-%m-%d"), "value": 2.5, "source": "test"})
    upsert_macro(macros, path)
    return path


@pytest.fixture
def volume_spike_prices(db_path):
    dates = pd.date_range("2025-01-01", periods=60)
    close = np.linspace(100, 120, 60) + np.random.normal(0, 0.3, 60)
    volume = np.full(60, 1_000_000, dtype=float)
    volume[40] = 4_000_000
    df = pd.DataFrame({
        "ticker": "VSPK",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.999, "high": close * 1.01,
        "low": close * 0.99, "close": close,
        "volume": volume, "adj_close": close,
    })
    upsert_prices(df, db_path)
    return db_path


@pytest.fixture
def gap_prices(db_path):
    dates = pd.date_range("2025-01-01", periods=80)
    close = np.linspace(100, 110, 80).copy()
    open_prices = close * 0.999
    open_prices[30] = close[29] * 1.05
    close[30] = close[29] * 1.04
    open_prices[45] = close[44] * 0.95
    close[45] = close[44] * 0.96
    df = pd.DataFrame({
        "ticker": "GAPTEST",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": open_prices,
        "high": np.maximum(close, open_prices) * 1.01,
        "low": np.minimum(close, open_prices) * 0.99,
        "close": close,
        "volume": [1_000_000] * 80, "adj_close": close,
    })
    upsert_prices(df, db_path)
    return db_path


@pytest.fixture
def vix_reversal_data(db_path):
    dates = pd.date_range("2025-01-01", periods=60)
    close = np.linspace(100, 120, 60)
    df = pd.DataFrame({
        "ticker": "SPY",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.999, "high": close * 1.01,
        "low": close * 0.99, "close": close,
        "volume": [1_000_000] * 60, "adj_close": close,
    })
    upsert_prices(df, db_path)
    macro_records = []
    for i, d in enumerate(dates):
        if 21 <= i <= 23:
            vix = 35.0
        elif i == 24:
            vix = 24.0
        else:
            vix = 18.0
        macro_records.append({"indicator": "vix", "date": d.strftime("%Y-%m-%d"), "value": vix, "source": "test"})
    upsert_macro(macro_records, db_path)
    return db_path


@pytest.fixture
def pcr_reversal_data(db_path):
    dates = pd.date_range("2025-01-01", periods=60)
    close = np.linspace(100, 115, 60)
    df = pd.DataFrame({
        "ticker": "SPY",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.999, "high": close * 1.01,
        "low": close * 0.99, "close": close,
        "volume": [1_000_000] * 60, "adj_close": close,
    })
    upsert_prices(df, db_path)
    macro_records = []
    for i, d in enumerate(dates):
        if i == 30:
            pcr = 1.3
        elif i == 40:
            pcr = 0.7
        elif i < 30:
            pcr = 0.9
        else:
            pcr = 0.9 - (i - 30) * 0.02
        macro_records.append({"indicator": "put_call_ratio", "date": d.strftime("%Y-%m-%d"), "value": pcr, "source": "test"})
    upsert_macro(macro_records, db_path)
    return db_path


@pytest.fixture
def yield_curve_data(db_path):
    dates = pd.date_range("2025-01-01", periods=60)
    close = np.linspace(100, 115, 60)
    df = pd.DataFrame({
        "ticker": "SPY",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.999, "high": close * 1.01,
        "low": close * 0.99, "close": close,
        "volume": [1_000_000] * 60, "adj_close": close,
    })
    upsert_prices(df, db_path)
    macro_records = []
    for i, d in enumerate(dates):
        date_str = d.strftime("%Y-%m-%d")
        macro_records.append({"indicator": "us_3m_yield", "date": date_str, "value": 5.0, "source": "test"})
        if i <= 30:
            yield_10y = 4.5
        elif i <= 49:
            yield_10y = 5.2
        else:
            yield_10y = 4.5
        macro_records.append({"indicator": "us_10y_yield", "date": date_str, "value": yield_10y, "source": "test"})
    upsert_macro(macro_records, db_path)
    return db_path


@pytest.fixture
def insider_cluster_data(db_path):
    dates = pd.date_range("2025-01-01", periods=60)
    close = np.linspace(100, 115, 60)
    df = pd.DataFrame({
        "ticker": "INSD",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.999, "high": close * 1.01,
        "low": close * 0.99, "close": close,
        "volume": [1_000_000] * 60, "adj_close": close,
    })
    upsert_prices(df, db_path)
    with get_db(db_path) as conn:
        for day_offset in [30, 32, 33, 35]:
            conn.execute(
                "INSERT OR REPLACE INTO insider_trades (ticker, date, insider_name, position, transaction_type, shares, value) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("INSD", dates[day_offset].strftime("%Y-%m-%d"), f"Insider{day_offset}", "CEO", "P-Purchase", 1000, 100000),
            )
    return db_path


@pytest.fixture
def short_squeeze_data(db_path):
    dates = pd.date_range("2025-01-01", periods=60)
    close = np.concatenate([np.linspace(100, 95, 30), np.linspace(95, 110, 30)])
    df = pd.DataFrame({
        "ticker": "SQZZ",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.999, "high": close * 1.01,
        "low": close * 0.99, "close": close,
        "volume": [1_000_000] * 60, "adj_close": close,
    })
    upsert_prices(df, db_path)
    with get_db(db_path) as conn:
        for i, d in enumerate(dates):
            conn.execute(
                "INSERT OR REPLACE INTO external_analysis (date, source, ticker, data_type, value, numeric_value, collected_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (d.strftime("%Y-%m-%d"), "shortinterest", "SQZZ", "short_interest", "15%", 15.0, "2025-01-01"),
            )
    return db_path

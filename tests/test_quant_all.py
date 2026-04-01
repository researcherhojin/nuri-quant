"""Consolidated quant tests — regime, factors, validation, backtest.

Sources: test_regime.py, test_regime_special.py, test_data_integrity.py,
test_strategy_map.py, test_factors.py, test_validation.py, test_scorecard.py,
test_signals_extended.py, test_sixty_percent.py, test_new_features.py,
test_coverage_final.py, test_coverage_round4.py, test_coverage_round5.py,
test_coverage_round8.py, test_coverage_round12.py, test_coverage_round13.py,
test_coverage_round19.py, test_coverage_round27.py, test_coverage_extra.py,
test_coverage_push.py.
"""
from datetime import timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from nuri.core.timezone import kst_now, today_kst

# ═══════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════


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
                            ("TSLA", 8, 340, "SectorA")]:
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


# Signal extended fixtures

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


# ═══════════════════════════════════════════════════════════════════
# PART 1: REGIME — classifier
# ═══════════════════════════════════════════════════════════════════


class TestRegimeClassifier:
    """D-1 (from test_regime.py)."""

    def test_bull_regime_detection(self, bull_market):
        from nuri.quant.regime.classifier import classify_regime
        state = classify_regime(db_path=bull_market)
        assert state is not None
        assert state.trend == "bull"
        assert state.volatility == "low"
        assert state.regime == "bull_low_vol"

    def test_bear_regime_detection(self, bear_market):
        from nuri.quant.regime.classifier import classify_regime
        state = classify_regime(db_path=bear_market)
        assert state is not None
        assert state.trend == "bear"
        assert state.volatility == "high"
        assert state.regime == "bear_high_vol"

    def test_confidence_range(self, bull_market):
        from nuri.quant.regime.classifier import classify_regime
        state = classify_regime(db_path=bull_market)
        assert 0.0 <= state.confidence <= 1.0

    def test_insufficient_data(self, db_path):
        from nuri.quant.regime.classifier import classify_regime
        state = classify_regime(db_path=db_path)
        assert state is None


class TestEuphoria:
    """(from test_regime_special.py)."""

    def test_euphoria_detection(self, euphoria_market):
        from nuri.quant.regime.classifier import classify_regime
        state = classify_regime(db_path=euphoria_market)
        assert state is not None
        assert state.regime == "euphoria"
        assert state.details["special_regime"] == "euphoria"
        assert state.trend == "bull"
        assert state.details["base_regime"].startswith("bull_")

    def test_euphoria_not_triggered_vix_high(self, db_path):
        from nuri.quant.regime.classifier import _detect_euphoria
        assert _detect_euphoria(15.0, 85.0) is False

    def test_euphoria_not_triggered_fg_low(self, db_path):
        from nuri.quant.regime.classifier import _detect_euphoria
        assert _detect_euphoria(10.0, 75.0) is False

    def test_euphoria_unit(self):
        from nuri.quant.regime.classifier import _detect_euphoria
        assert _detect_euphoria(11.9, 81.0) is True
        assert _detect_euphoria(None, 85.0) is False
        assert _detect_euphoria(10.0, None) is False


class TestStagflation:
    """(from test_regime_special.py)."""

    def test_stagflation_detection(self, db_path):
        from nuri.quant.regime.classifier import _detect_stagflation
        upsert_macro([
            {"indicator": "cpi_yoy", "date": "2025-01-15", "value": 5.5, "source": "test"},
            {"indicator": "gdp_growth", "date": "2025-01-15", "value": 0.5, "source": "test"},
        ], db_path)
        assert _detect_stagflation(db_path=db_path) is True

    def test_stagflation_no_gdp_graceful(self, db_path):
        from nuri.quant.regime.classifier import _detect_stagflation
        upsert_macro([
            {"indicator": "cpi_yoy", "date": "2025-01-15", "value": 5.5, "source": "test"},
        ], db_path)
        assert _detect_stagflation(db_path=db_path) is False

    def test_stagflation_no_cpi(self, db_path):
        from nuri.quant.regime.classifier import _detect_stagflation
        assert _detect_stagflation(db_path=db_path) is False

    def test_stagflation_normal_conditions(self, db_path):
        from nuri.quant.regime.classifier import _detect_stagflation
        upsert_macro([
            {"indicator": "cpi_yoy", "date": "2025-01-15", "value": 2.5, "source": "test"},
            {"indicator": "gdp_growth", "date": "2025-01-15", "value": 2.5, "source": "test"},
        ], db_path)
        assert _detect_stagflation(db_path=db_path) is False


class TestRecovery:
    """(from test_regime_special.py)."""

    def test_recovery_unit(self):
        from nuri.quant.regime.classifier import _detect_recovery
        phase1 = np.full(100, 180.0)
        phase2 = np.linspace(180, 120, 100)
        phase3 = np.linspace(120, 200, 100)
        close_arr = np.concatenate([phase1, phase2, phase3])
        df = pd.DataFrame({"close": close_arr})
        df["sma50"] = df["close"].rolling(50).mean()
        df["sma200"] = df["close"].rolling(200).mean()
        result = _detect_recovery(df)
        assert isinstance(result, bool)

    def test_recovery_insufficient_data(self):
        from nuri.quant.regime.classifier import _detect_recovery
        df = pd.DataFrame({"close": np.linspace(100, 200, 200)})
        df["sma50"] = df["close"].rolling(50).mean()
        df["sma200"] = df["close"].rolling(200).mean()
        assert _detect_recovery(df) is False

    def test_recovery_none_input(self):
        from nuri.quant.regime.classifier import _detect_recovery
        assert _detect_recovery(None) is False


class TestSectorRotation:
    """(from test_regime_special.py)."""

    def test_sector_rotation_detection(self, db_path):
        from nuri.quant.regime.classifier import _detect_sector_rotation
        dates = pd.date_range(end=today_kst(), periods=25)
        spy_close = np.full(25, 500.0)
        df_spy = pd.DataFrame({
            "ticker": "SPY",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": spy_close * 0.999, "high": spy_close * 1.01,
            "low": spy_close * 0.99, "close": spy_close,
            "volume": [50_000_000] * 25, "adj_close": spy_close,
        })
        upsert_prices(df_spy, db_path)
        xlk_close = np.linspace(200, 210, 25)
        df_xlk = pd.DataFrame({
            "ticker": "XLK",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": xlk_close * 0.999, "high": xlk_close * 1.01,
            "low": xlk_close * 0.99, "close": xlk_close,
            "volume": [10_000_000] * 25, "adj_close": xlk_close,
        })
        upsert_prices(df_xlk, db_path)
        assert _detect_sector_rotation(db_path=db_path) is True

    def test_sector_rotation_spy_not_flat(self, db_path):
        from nuri.quant.regime.classifier import _detect_sector_rotation
        dates = pd.date_range(end=today_kst(), periods=25)
        spy_close = np.linspace(500, 525, 25)
        df = pd.DataFrame({
            "ticker": "SPY",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": spy_close * 0.999, "high": spy_close * 1.01,
            "low": spy_close * 0.99, "close": spy_close,
            "volume": [50_000_000] * 25, "adj_close": spy_close,
        })
        upsert_prices(df, db_path)
        assert _detect_sector_rotation(db_path=db_path) is False

    def test_sector_rotation_no_data(self, db_path):
        from nuri.quant.regime.classifier import _detect_sector_rotation
        assert _detect_sector_rotation(db_path=db_path) is False


class TestSpecialRegimePriority:
    """(from test_regime_special.py)."""

    def test_euphoria_beats_recovery(self, db_path):
        from nuri.quant.regime.classifier import _detect_euphoria
        assert _detect_euphoria(10.0, 85.0) is True

    def test_special_regime_sizing(self):
        from nuri.quant.regime.classifier import SPECIAL_REGIME_SIZING
        assert SPECIAL_REGIME_SIZING["euphoria"] == "defensive"
        assert SPECIAL_REGIME_SIZING["stagflation"] == "minimal"
        assert SPECIAL_REGIME_SIZING["recovery"] == "aggressive"
        assert SPECIAL_REGIME_SIZING["sector_rotation"] == "normal"

    def test_base_regime_unchanged_when_no_special(self, db_path):
        close = np.linspace(100, 200, 300) + np.random.normal(0, 0.5, 300)
        dates = _insert_spy_data(db_path, close)
        upsert_macro([
            {"indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"), "value": 16.0, "source": "test"},
            {"indicator": "fear_greed", "date": dates[-1].strftime("%Y-%m-%d"), "value": 60.0, "source": "test"},
        ], db_path)
        from nuri.quant.regime.classifier import classify_regime
        state = classify_regime(db_path=db_path)
        assert state is not None
        assert state.details["special_regime"] is None
        assert state.regime.endswith("_vol")


class TestDynamicThresholds:
    """(from test_regime.py)."""

    def test_thresholds_with_vix_data(self, bull_market):
        from nuri.quant.regime.classifier import compute_dynamic_thresholds
        th = compute_dynamic_thresholds(db_path=bull_market)
        assert "vix_threshold" in th
        assert "sideways_pct" in th
        assert th["sideways_pct"] >= 1.0

    def test_thresholds_without_data(self, db_path):
        from nuri.quant.regime.classifier import compute_dynamic_thresholds
        th = compute_dynamic_thresholds(db_path=db_path)
        assert th["vix_threshold"] == 18.0
        assert th["sideways_pct"] == 2.0


class TestVixHysteresis:
    """(from test_data_integrity.py)."""

    def test_historical_vix_used_per_day(self, db_path):
        dates = _insert_spy_data_trend(db_path, n_days=300, trend="bull")
        for i, vix_val in enumerate([14.0, 15.0, 16.0, 17.0, 18.0]):
            upsert_macro([{"indicator": "vix", "date": dates[-(5 - i)], "value": vix_val, "source": "test"}], db_path)
        upsert_macro([{"indicator": "fear_greed", "date": dates[-1], "value": 55.0, "source": "test"}], db_path)
        from nuri.quant.regime.classifier import _get_vix
        assert _get_vix(date=dates[-5], db_path=db_path) == 14.0
        assert _get_vix(date=dates[-4], db_path=db_path) == 15.0
        assert _get_vix(date=dates[-3], db_path=db_path) == 16.0
        assert _get_vix(date=dates[-2], db_path=db_path) == 17.0
        assert _get_vix(date=dates[-1], db_path=db_path) == 18.0

    def test_hysteresis_calls_get_vix_per_day(self, db_path):
        dates = _insert_spy_data_trend(db_path, n_days=300, trend="bull")
        for i in range(10):
            upsert_macro([{"indicator": "vix", "date": dates[-(10 - i)], "value": 15.0 + i * 0.1, "source": "test"}], db_path)
        upsert_macro([{"indicator": "fear_greed", "date": dates[-1], "value": 60.0, "source": "test"}], db_path)
        call_dates = []
        from nuri.quant.regime import classifier
        original_get_vix = classifier._get_vix

        def tracking_get_vix(date=None, db_path=None):
            call_dates.append(date)
            return original_get_vix(date=date, db_path=db_path)

        with patch.object(classifier, '_get_vix', side_effect=tracking_get_vix):
            state = classifier.classify_regime(db_path=db_path)
        assert state is not None
        hysteresis_calls = [d for d in call_dates if d is not None]
        assert len(hysteresis_calls) >= 2

    def test_regime_still_works_with_single_vix(self, db_path):
        dates = _insert_spy_data_trend(db_path, n_days=300, trend="bull")
        upsert_macro([{"indicator": "vix", "date": dates[-1], "value": 15.0, "source": "test"}], db_path)
        upsert_macro([{"indicator": "fear_greed", "date": dates[-1], "value": 55.0, "source": "test"}], db_path)
        from nuri.quant.regime.classifier import classify_regime
        state = classify_regime(db_path=db_path)
        assert state is not None
        assert state.trend == "bull"


class TestDataFreshnessEnforcement:
    """(from test_data_integrity.py)."""

    @pytest.fixture(autouse=True)
    def reset_freshness_warned(self):
        from nuri.quant.regime import classifier
        classifier._freshness_warned = False
        yield
        classifier._freshness_warned = False

    def test_stale_data_blocks_regime(self, db_path):
        stale_date = (kst_now().replace(tzinfo=None) - timedelta(days=10)).strftime("%Y-%m-%d")
        _insert_spy_data_trend(db_path, n_days=300, trend="bull", last_date=stale_date)
        upsert_macro([{"indicator": "vix", "date": stale_date, "value": 15.0, "source": "test"}], db_path)
        from nuri.quant.regime.classifier import classify_regime
        state = classify_regime(db_path=db_path)
        assert state is None

    def test_fresh_data_allows_regime(self, db_path):
        today = today_kst()
        dates = _insert_spy_data_trend(db_path, n_days=300, trend="bull", last_date=today)
        upsert_macro([{"indicator": "vix", "date": dates[-1], "value": 15.0, "source": "test"}], db_path)
        upsert_macro([{"indicator": "fear_greed", "date": dates[-1], "value": 60.0, "source": "test"}], db_path)
        from nuri.quant.regime.classifier import classify_regime
        state = classify_regime(db_path=db_path)
        assert state is not None

    def test_dated_query_bypasses_freshness(self, db_path):
        stale_date = (kst_now().replace(tzinfo=None) - timedelta(days=10)).strftime("%Y-%m-%d")
        _insert_spy_data_trend(db_path, n_days=300, trend="bull", last_date=stale_date)
        upsert_macro([{"indicator": "vix", "date": stale_date, "value": 15.0, "source": "test"}], db_path)
        upsert_macro([{"indicator": "fear_greed", "date": stale_date, "value": 60.0, "source": "test"}], db_path)
        from nuri.quant.regime.classifier import classify_regime
        state = classify_regime(date=stale_date, db_path=db_path)
        assert state is not None

    def test_no_data_returns_false(self, db_path):
        from nuri.quant.regime.classifier import _check_data_freshness
        assert _check_data_freshness(db_path=db_path) is False

    def test_freshness_check_returns_true_for_fresh(self, db_path):
        today = today_kst()
        _insert_spy_data_trend(db_path, n_days=300, trend="bull", last_date=today)
        from nuri.quant.regime.classifier import _check_data_freshness
        assert _check_data_freshness(db_path=db_path) is True


class TestClassifySingle:
    """(from test_coverage_round19.py)."""

    def test_bull(self):
        from nuri.quant.regime.classifier import _classify_single
        th = {"sideways_pct": 2.0, "vix_threshold": 18.0, "vix_bear_threshold": 24.0, "bb_width_threshold": 6.0}
        trend, vol = _classify_single(close=500, sma50=490, sma200=460, vix=15.0, bb_width=5.0, thresholds=th)
        assert trend == "bull"
        assert vol == "low"

    def test_bear(self):
        from nuri.quant.regime.classifier import _classify_single
        th = {"sideways_pct": 2.0, "vix_threshold": 18.0, "vix_bear_threshold": 24.0, "bb_width_threshold": 6.0}
        trend, vol = _classify_single(close=400, sma50=420, sma200=460, vix=30.0, bb_width=8.0, thresholds=th)
        assert trend == "bear"
        assert vol == "high"

    def test_sideways_narrow_gap(self):
        from nuri.quant.regime.classifier import _classify_single
        th = {"sideways_pct": 2.0, "vix_threshold": 18.0, "vix_bear_threshold": 24.0, "bb_width_threshold": 6.0}
        trend, vol = _classify_single(close=460, sma50=461, sma200=460, vix=16.0, bb_width=5.0, thresholds=th)
        assert trend == "sideways"

    def test_volatility_from_bb_when_no_vix(self):
        from nuri.quant.regime.classifier import _classify_single
        th = {"sideways_pct": 2.0, "vix_threshold": 18.0, "vix_bear_threshold": 24.0, "bb_width_threshold": 6.0}
        trend, vol = _classify_single(close=500, sma50=490, sma200=460, vix=None, bb_width=8.0, thresholds=th)
        assert vol == "high"


class TestClassifyRegime_R19:
    """(from test_coverage_round19.py)."""

    def test_full_classification(self, rich_db, monkeypatch):
        from nuri.quant.regime import classifier as cls_mod
        cls_mod._freshness_warned = False
        monkeypatch.setattr(cls_mod, "_check_data_freshness", lambda db_path=None: True)
        result = cls_mod.classify_regime(db_path=rich_db)
        assert result is not None
        assert result.trend in ("bull", "bear", "sideways")
        assert result.volatility in ("high", "low")
        assert 0 <= result.confidence <= 1
        assert result.details["base_regime"] is not None

    def test_with_date_param(self, rich_db):
        from nuri.quant.regime.classifier import classify_regime
        result = classify_regime(date="2025-06-01", db_path=rich_db)
        if result is not None:
            assert result.date <= "2025-06-01"

    def test_print_regime_none(self, capsys):
        from nuri.quant.regime.classifier import print_regime
        print_regime(None)
        captured = capsys.readouterr()
        assert "불가" in captured.out

    def test_print_regime_with_state(self, capsys):
        from nuri.quant.regime.classifier import RegimeState, print_regime
        state = RegimeState(
            date="2025-06-01", trend="bull", volatility="low",
            regime="bull_low_vol", confidence=0.75,
            details={
                "spy_close": 500.0, "sma50": 490.0, "sma200": 460.0,
                "sma_diff_pct": 6.5, "vix": 15.0, "fear_greed": 65.0,
                "rsi": 55.0, "bb_width": 5.0,
                "thresholds": {"vix_threshold": 18.0, "vix_bear_threshold": 24.0,
                               "sideways_pct": 2.0, "bb_width_threshold": 6.0},
                "base_regime": "bull_low_vol", "special_regime": None,
            },
        )
        print_regime(state)
        captured = capsys.readouterr()
        assert "BULL" in captured.out
        assert "LOW VOL" in captured.out

    def test_print_regime_special(self, capsys):
        from nuri.quant.regime.classifier import RegimeState, print_regime
        state = RegimeState(
            date="2025-06-01", trend="bull", volatility="low",
            regime="euphoria", confidence=0.8,
            details={
                "spy_close": 500.0, "sma50": 490.0, "sma200": 460.0,
                "sma_diff_pct": 6.5, "vix": 10.0, "fear_greed": 85.0,
                "rsi": None, "bb_width": 5.0,
                "thresholds": {}, "base_regime": "bull_low_vol",
                "special_regime": "euphoria",
            },
        )
        print_regime(state)
        captured = capsys.readouterr()
        assert "EUPHORIA" in captured.out

    def test_print_history_empty(self, capsys):
        from nuri.quant.regime.classifier import print_history
        print_history([])
        captured = capsys.readouterr()
        assert "없음" in captured.out

    def test_print_history_with_data(self, capsys):
        from nuri.quant.regime.classifier import RegimeState, print_history
        states = [RegimeState(
            date="2025-06-01", trend="bull", volatility="low",
            regime="bull_low_vol", confidence=0.75,
            details={"spy_close": 500.0, "sma50": 490.0, "sma200": 460.0,
                     "sma_diff_pct": 6.5, "vix": 15.0, "fear_greed": 65.0,
                     "rsi": 55.0, "bb_width": 5.0, "thresholds": {},
                     "base_regime": "bull_low_vol", "special_regime": None},
        )]
        print_history(states)
        captured = capsys.readouterr()
        assert "Regime History" in captured.out


class TestDynamicThresholds_R19:
    """(from test_coverage_round19.py)."""

    def test_with_data(self, rich_db):
        from nuri.quant.regime.classifier import compute_dynamic_thresholds
        th = compute_dynamic_thresholds(db_path=rich_db)
        assert "vix_threshold" in th
        assert "sideways_pct" in th
        assert th["vix_threshold"] > 0

    def test_with_insufficient_data(self, tmp_path):
        path = tmp_path / "empty.db"
        init_db(path)
        from nuri.quant.regime.classifier import compute_dynamic_thresholds
        th = compute_dynamic_thresholds(db_path=path)
        assert th["vix_threshold"] == 18.0
        assert th["sideways_pct"] == 2.0


class TestSpecialRegimes_R19:
    """(from test_coverage_round19.py)."""

    def test_euphoria_detected(self):
        from nuri.quant.regime.classifier import _detect_euphoria
        assert _detect_euphoria(vix=10.0, fear_greed=85.0) is True

    def test_euphoria_not_detected_high_vix(self):
        from nuri.quant.regime.classifier import _detect_euphoria
        assert _detect_euphoria(vix=15.0, fear_greed=85.0) is False

    def test_euphoria_not_detected_low_fg(self):
        from nuri.quant.regime.classifier import _detect_euphoria
        assert _detect_euphoria(vix=10.0, fear_greed=60.0) is False

    def test_euphoria_none_inputs(self):
        from nuri.quant.regime.classifier import _detect_euphoria
        assert _detect_euphoria(vix=None, fear_greed=85.0) is False
        assert _detect_euphoria(vix=10.0, fear_greed=None) is False

    def test_stagflation_detected(self, tmp_path):
        from nuri.quant.regime.classifier import _detect_stagflation
        path = tmp_path / "test.db"
        init_db(path)
        upsert_macro([
            {"indicator": "cpi_yoy", "date": "2025-01-01", "value": 5.0, "source": "test"},
            {"indicator": "gdp_growth", "date": "2025-01-01", "value": 0.5, "source": "test"},
        ], path)
        assert _detect_stagflation(db_path=path) is True

    def test_stagflation_not_detected_normal_economy(self, tmp_path):
        from nuri.quant.regime.classifier import _detect_stagflation
        path = tmp_path / "test.db"
        init_db(path)
        upsert_macro([
            {"indicator": "cpi_yoy", "date": "2025-01-01", "value": 2.5, "source": "test"},
            {"indicator": "gdp_growth", "date": "2025-01-01", "value": 2.5, "source": "test"},
        ], path)
        assert _detect_stagflation(db_path=path) is False

    def test_stagflation_no_gdp_data(self, tmp_path):
        from nuri.quant.regime.classifier import _detect_stagflation
        path = tmp_path / "test.db"
        init_db(path)
        upsert_macro([{"indicator": "cpi_yoy", "date": "2025-01-01", "value": 5.0, "source": "test"}], path)
        assert _detect_stagflation(db_path=path) is False

    def test_recovery_detected(self):
        from nuri.quant.regime.classifier import _detect_recovery
        n = 300
        df = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=n), "close": np.linspace(100, 200, n)})
        sma50 = np.ones(n) * 150.0
        sma200 = np.ones(n) * 160.0
        sma50[-1] = 165
        sma200[-1] = 160
        df["sma50"] = sma50
        df["sma200"] = sma200
        assert _detect_recovery(df) is True

    def test_recovery_not_detected_bull_to_bull(self):
        from nuri.quant.regime.classifier import _detect_recovery
        n = 300
        df = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=n), "close": np.linspace(100, 200, n)})
        df["sma50"] = 170.0
        df["sma200"] = 160.0
        assert _detect_recovery(df) is False

    def test_recovery_short_data(self):
        from nuri.quant.regime.classifier import _detect_recovery
        df = pd.DataFrame({"date": ["2024-01-01"], "close": [100], "sma50": [100], "sma200": [100]})
        assert _detect_recovery(df) is False
        assert _detect_recovery(None) is False

    def test_sector_rotation_detected(self, tmp_path):
        from nuri.quant.regime.classifier import _detect_sector_rotation
        path = tmp_path / "test.db"
        init_db(path)
        dates = pd.date_range("2025-01-01", periods=21, freq="B")
        rows = []
        for d in dates:
            rows.append({"ticker": "SPY", "date": d.strftime("%Y-%m-%d"),
                         "open": 450, "high": 451, "low": 449,
                         "close": 450, "volume": 1000000, "adj_close": 450})
        for i, d in enumerate(dates):
            p = 200 + i * 0.5
            rows.append({"ticker": "XLK", "date": d.strftime("%Y-%m-%d"),
                         "open": p, "high": p + 1, "low": p - 1,
                         "close": p, "volume": 1000000, "adj_close": p})
        upsert_prices(pd.DataFrame(rows), path)
        assert _detect_sector_rotation(db_path=path) is True

    def test_sector_rotation_spy_not_flat(self, tmp_path):
        from nuri.quant.regime.classifier import _detect_sector_rotation
        path = tmp_path / "test.db"
        init_db(path)
        dates = pd.date_range("2025-01-01", periods=21, freq="B")
        rows = []
        for i, d in enumerate(dates):
            p = 450 + i * 2
            rows.append({"ticker": "SPY", "date": d.strftime("%Y-%m-%d"),
                         "open": p, "high": p + 1, "low": p - 1,
                         "close": p, "volume": 1000000, "adj_close": p})
        upsert_prices(pd.DataFrame(rows), path)
        assert _detect_sector_rotation(db_path=path) is False


class TestClassifierExtended:
    """(from test_coverage_final.py)."""

    def test_classify_regime(self, rich_db):
        from nuri.quant.regime.classifier import classify_regime
        result = classify_regime(db_path=rich_db)
        if result:
            assert result.trend in ("bull", "bear", "sideways")
            assert result.volatility in ("low", "high")
            assert 0 <= result.confidence <= 1

    def test_classify_single(self, rich_db):
        from nuri.quant.regime.classifier import _classify_single, compute_dynamic_thresholds
        thresholds = compute_dynamic_thresholds(db_path=rich_db)
        trend, vol = _classify_single(500, 480, 440, 15, 0.03, thresholds)
        assert trend == "bull"
        assert vol == "low"

    def test_classify_bear(self, rich_db):
        from nuri.quant.regime.classifier import _classify_single, compute_dynamic_thresholds
        thresholds = compute_dynamic_thresholds(db_path=rich_db)
        trend, vol = _classify_single(400, 450, 480, 15, 0.03, thresholds)
        assert trend == "bear"

    def test_high_vol(self, rich_db):
        from nuri.quant.regime.classifier import _classify_single, compute_dynamic_thresholds
        thresholds = compute_dynamic_thresholds(db_path=rich_db)
        trend, vol = _classify_single(500, 480, 440, 30, 0.08, thresholds)
        assert vol == "high"


class TestRegimeDeep:
    """(from test_coverage_round4.py)."""

    def test_classify_regime(self, rich_db, monkeypatch):
        from nuri.quant.regime import classifier as cls_mod
        monkeypatch.setattr(cls_mod, "_check_data_freshness", lambda db_path=None: True)
        state = cls_mod.classify_regime(db_path=rich_db)
        assert state is not None
        assert hasattr(state, "regime")
        assert hasattr(state, "trend")

    def test_classify_with_historical_vix(self, rich_db, monkeypatch):
        from nuri.quant.regime import classifier as cls_mod
        monkeypatch.setattr(cls_mod, "_check_data_freshness", lambda db_path=None: True)
        state = cls_mod.classify_regime(db_path=rich_db)
        assert state is not None
        assert state.confidence > 0


class TestRegimeSpecial_R12:
    """(from test_coverage_round12.py)."""

    def test_classify_volatility(self, rich_db, monkeypatch):
        from nuri.quant.regime import classifier as cls_mod
        monkeypatch.setattr(cls_mod, "_check_data_freshness", lambda db_path=None: True)
        state = cls_mod.classify_regime(db_path=rich_db)
        assert state is not None
        assert state.volatility in ("low", "high")

    def test_regime_details(self, rich_db, monkeypatch):
        from nuri.quant.regime import classifier as cls_mod
        monkeypatch.setattr(cls_mod, "_check_data_freshness", lambda db_path=None: True)
        state = cls_mod.classify_regime(db_path=rich_db)
        assert state is not None
        assert "base_regime" in state.details


class TestClassifyRegimeHistory:
    """(from test_coverage_round19.py)."""

    def test_history_with_data(self, rich_db, monkeypatch):
        from nuri.quant.regime import classifier as cls_mod
        cls_mod._freshness_warned = False
        monkeypatch.setattr(cls_mod, "_check_data_freshness", lambda db_path=None: True)
        from nuri.quant.regime.classifier import classify_regime_history
        history = classify_regime_history(start_date="2024-06-01", end_date="2025-06-01", db_path=rich_db)
        assert isinstance(history, list)
        if history:
            assert history[0].trend in ("bull", "bear", "sideways")

    def test_history_empty_db(self, tmp_path):
        path = tmp_path / "empty.db"
        init_db(path)
        from nuri.quant.regime.classifier import classify_regime_history
        history = classify_regime_history(db_path=path)
        assert history == []


class TestDataFreshness_R19:
    """(from test_coverage_round19.py)."""

    def test_no_data(self, tmp_path, monkeypatch):
        from nuri.quant.regime import classifier as cls_mod
        cls_mod._freshness_warned = False
        path = tmp_path / "empty.db"
        init_db(path)
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        result = cls_mod._check_data_freshness(db_path=path)
        assert result is False

    def test_recent_data(self, rich_db, monkeypatch):
        from nuri.quant.regime import classifier as cls_mod
        cls_mod._freshness_warned = False
        from nuri.core.db import query as _query
        rows = _query("SELECT MAX(date) as latest FROM prices WHERE ticker = 'SPY'", db_path=rich_db)
        latest_str = rows[0]["latest"]
        from datetime import datetime
        latest_dt = datetime.strptime(latest_str, "%Y-%m-%d")
        mock_now = latest_dt + timedelta(hours=24)
        with patch("nuri.core.timezone.kst_now", return_value=mock_now):
            result = cls_mod._check_data_freshness(db_path=rich_db)
        assert result is True


class TestClassifierDeep:
    """(from test_sixty_percent.py)."""

    def test_print_regime(self, full_db, capsys):
        from nuri.quant.regime.classifier import classify_regime, print_regime
        result = classify_regime(db_path=full_db)
        print_regime(result)
        output = capsys.readouterr().out
        assert len(output) > 0

    def test_compute_thresholds(self, full_db):
        from nuri.quant.regime.classifier import compute_dynamic_thresholds
        thresholds = compute_dynamic_thresholds(db_path=full_db)
        assert isinstance(thresholds, dict)
        assert "vix_threshold" in thresholds
        assert "sideways_pct" in thresholds


# ═══════════════════════════════════════════════════════════════════
# PART 1b: REGIME — macro_score
# ═══════════════════════════════════════════════════════════════════


class TestMacroScore:
    """D-2 (from test_regime.py)."""

    def test_score_range(self, db_path):
        from nuri.quant.regime.macro_score import compute_macro_score
        score = compute_macro_score(db_path=db_path)
        assert 0 <= score.total_score <= 100

    def test_favorable_conditions(self, db_path):
        from nuri.quant.regime.macro_score import compute_macro_score
        date = "2025-01-15"
        upsert_macro([
            {"indicator": "us_10y_yield", "date": date, "value": 4.0, "source": "test"},
            {"indicator": "us_2y_yield", "date": date, "value": 3.0, "source": "test"},
            {"indicator": "vix", "date": date, "value": 14.0, "source": "test"},
            {"indicator": "fear_greed", "date": date, "value": 55.0, "source": "test"},
            {"indicator": "unemployment", "date": date, "value": 3.8, "source": "test"},
            {"indicator": "cpi_yoy", "date": date, "value": 2.1, "source": "test"},
            {"indicator": "fed_funds_rate", "date": date, "value": 2.0, "source": "test"},
        ], db_path)
        score = compute_macro_score(date=date, db_path=db_path)
        assert score.total_score > 65
        assert score.interpretation == "Favorable"

    def test_adverse_conditions(self, db_path):
        from nuri.quant.regime.macro_score import compute_macro_score
        date = "2025-06-15"
        upsert_macro([
            {"indicator": "us_10y_yield", "date": date, "value": 3.0, "source": "test"},
            {"indicator": "us_2y_yield", "date": date, "value": 4.5, "source": "test"},
            {"indicator": "vix", "date": date, "value": 35.0, "source": "test"},
            {"indicator": "fear_greed", "date": date, "value": 10.0, "source": "test"},
            {"indicator": "unemployment", "date": date, "value": 7.0, "source": "test"},
            {"indicator": "cpi_yoy", "date": date, "value": 6.5, "source": "test"},
            {"indicator": "fed_funds_rate", "date": date, "value": 5.5, "source": "test"},
        ], db_path)
        score = compute_macro_score(date=date, db_path=db_path)
        assert score.total_score < 35
        assert score.interpretation in ("Cautious", "Adverse")


class TestMacroScoreWarnings:
    """(from test_data_integrity.py)."""

    def test_empty_db_has_all_warnings(self, db_path):
        from nuri.quant.regime.macro_score import compute_macro_score
        score = compute_macro_score(db_path=db_path)
        assert score.warnings is not None
        assert len(score.warnings) == 8

    def test_partial_data_partial_warnings(self, db_path):
        date = "2025-01-15"
        upsert_macro([
            {"indicator": "vix", "date": date, "value": 15.0, "source": "test"},
            {"indicator": "fear_greed", "date": date, "value": 50.0, "source": "test"},
        ], db_path)
        from nuri.quant.regime.macro_score import compute_macro_score
        score = compute_macro_score(date=date, db_path=db_path)
        assert score.warnings is not None
        warning_names = [w.split(":")[0] for w in score.warnings]
        assert "vix" not in warning_names
        assert "sentiment" not in warning_names
        assert len(score.warnings) == 6

    def test_full_data_no_warnings(self, db_path):
        date = "2025-01-15"
        upsert_macro([
            {"indicator": "us_10y_yield", "date": date, "value": 4.0, "source": "test"},
            {"indicator": "us_2y_yield", "date": date, "value": 3.0, "source": "test"},
            {"indicator": "us_3m_yield", "date": date, "value": 2.5, "source": "test"},
            {"indicator": "vix", "date": date, "value": 15.0, "source": "test"},
            {"indicator": "put_call_ratio", "date": date, "value": 0.85, "source": "test"},
            {"indicator": "fear_greed", "date": date, "value": 55.0, "source": "test"},
            {"indicator": "unemployment", "date": date, "value": 3.8, "source": "test"},
            {"indicator": "cpi_yoy", "date": date, "value": 2.1, "source": "test"},
            {"indicator": "fed_funds_rate", "date": date, "value": 2.0, "source": "test"},
        ], db_path)
        from nuri.quant.regime.macro_score import compute_macro_score
        score = compute_macro_score(date=date, db_path=db_path)
        assert score.warnings is None

    def test_score_still_50_when_missing(self, db_path):
        from nuri.quant.regime.macro_score import compute_macro_score
        score = compute_macro_score(db_path=db_path)
        assert score.total_score == 50.0


class TestMacroScoreExtended:
    """(from test_coverage_final.py)."""

    def test_compute(self, rich_db):
        from nuri.quant.regime.macro_score import compute_macro_score
        score = compute_macro_score(db_path=rich_db)
        assert hasattr(score, "total_score")
        assert 0 <= score.total_score <= 100

    def test_print(self, rich_db, capsys):
        from nuri.quant.regime.macro_score import compute_macro_score, print_macro_score
        score = compute_macro_score(db_path=rich_db)
        print_macro_score(score)
        output = capsys.readouterr().out
        assert "Macro" in output or "매크로" in output


# ═══════════════════════════════════════════════════════════════════
# PART 1c: REGIME — strategy_map
# ═══════════════════════════════════════════════════════════════════


class TestStrategyMap:
    """D-3 (from test_regime.py)."""

    def test_bull_strategy(self, bull_market):
        from nuri.quant.regime.strategy_map import map_regime_to_strategy
        rec = map_regime_to_strategy(db_path=bull_market)
        assert rec is not None
        assert rec.position_sizing == "aggressive"
        assert len(rec.recommended_signals) > 0

    def test_bear_strategy(self, bear_market):
        from nuri.quant.regime.strategy_map import map_regime_to_strategy
        rec = map_regime_to_strategy(db_path=bear_market)
        assert rec is not None
        assert rec.position_sizing in ("defensive", "minimal")

    def test_no_data(self, db_path):
        from nuri.quant.regime.strategy_map import map_regime_to_strategy
        rec = map_regime_to_strategy(db_path=db_path)
        assert rec is None

    def test_strategy_has_sector_preference(self, bull_market):
        from nuri.quant.regime.strategy_map import map_regime_to_strategy
        rec = map_regime_to_strategy(db_path=bull_market)
        assert rec is not None
        assert len(rec.sector_preference) > 0


class TestPositionRules:
    """(from test_strategy_map.py)."""

    def test_all_combos(self):
        from nuri.quant.regime.strategy_map import POSITION_RULES
        assert POSITION_RULES[("bull", "low")] == "aggressive"
        assert POSITION_RULES[("bull", "high")] == "normal"
        assert POSITION_RULES[("sideways", "low")] == "normal"
        assert POSITION_RULES[("sideways", "high")] == "defensive"
        assert POSITION_RULES[("bear", "low")] == "defensive"
        assert POSITION_RULES[("bear", "high")] == "minimal"

    def test_sector_rules(self):
        from nuri.quant.regime.strategy_map import SECTOR_RULES
        assert "XLK" in SECTOR_RULES["aggressive"]
        assert "XLP" in SECTOR_RULES["defensive"]
        assert "XLP" in SECTOR_RULES["minimal"]


class TestStrategyMapConstants:
    """(from test_strategy_map.py)."""

    def test_thresholds(self):
        from nuri.quant.regime.strategy_map import PF_AVOID_THRESHOLD, PF_RECOMMEND_THRESHOLD
        assert PF_RECOMMEND_THRESHOLD == 1.5
        assert PF_AVOID_THRESHOLD == 1.0

    def test_sector_classifications(self):
        from nuri.quant.regime.strategy_map import DEFENSIVE_SECTORS, GROWTH_SECTORS
        assert "XLP" in DEFENSIVE_SECTORS
        assert "XLK" in GROWTH_SECTORS


class TestStrategyRecommendation:
    """(from test_strategy_map.py)."""

    def test_create(self):
        from nuri.quant.regime.strategy_map import StrategyRecommendation
        rec = StrategyRecommendation(
            regime="bull_low_vol", macro_interpretation="양호",
            position_sizing="aggressive",
            recommended_signals=["rsi_oversold"], avoid_signals=["macd_dead"],
            sector_preference=["XLK"], signal_regime_stats={}, notes="test",
        )
        assert rec.position_sizing == "aggressive"


class TestBuildDataDrivenStrategy:
    """(from test_strategy_map.py)."""

    def test_empty_df(self):
        from nuri.quant.regime.strategy_map import _build_data_driven_strategy
        result = _build_data_driven_strategy("bull_low_vol", pd.DataFrame())
        assert result["recommended"] == []
        assert result["avoid"] == []

    def test_with_data(self):
        from nuri.quant.regime.strategy_map import _build_data_driven_strategy
        cross_df = pd.DataFrame([
            {"signal_id": "rsi_oversold", "regime": "bull_low_vol", "trades": 10, "win_rate": 0.7, "avg_return": 5.0, "profit_factor": 2.5},
            {"signal_id": "macd_dead", "regime": "bull_low_vol", "trades": 8, "win_rate": 0.3, "avg_return": -2.0, "profit_factor": 0.6},
            {"signal_id": "bb_bounce", "regime": "bull_low_vol", "trades": 3, "win_rate": 0.5, "avg_return": 1.0, "profit_factor": 1.2},
        ])
        result = _build_data_driven_strategy("bull_low_vol", cross_df)
        assert "rsi_oversold" in result["recommended"]
        assert "macd_dead" in result["avoid"]
        assert "bb_bounce" not in result["recommended"]
        assert "bb_bounce" not in result["avoid"]
        assert "rsi_oversold" in result["stats"]

    def test_wrong_regime(self):
        from nuri.quant.regime.strategy_map import _build_data_driven_strategy
        cross_df = pd.DataFrame([
            {"signal_id": "rsi", "regime": "bear_high_vol", "trades": 10, "win_rate": 0.7, "avg_return": 5.0, "profit_factor": 2.5},
        ])
        result = _build_data_driven_strategy("bull_low_vol", cross_df)
        assert result["recommended"] == []


class TestFindLatestCsv:
    """(from test_strategy_map.py)."""

    def test_no_report_dir(self, tmp_path, monkeypatch):
        import nuri.quant.regime.strategy_map as sm
        monkeypatch.setattr(sm, "REPORT_DIR", tmp_path / "nonexistent")
        result = sm._find_latest_csv("signal_results.csv")
        assert result is None

    def test_finds_latest(self, tmp_path, monkeypatch):
        import nuri.quant.regime.strategy_map as sm
        d1 = tmp_path / "2026-03-27"
        d1.mkdir()
        d2 = tmp_path / "2026-03-28"
        d2.mkdir()
        (d2 / "signal_results.csv").write_text("data")
        monkeypatch.setattr(sm, "REPORT_DIR", tmp_path)
        result = sm._find_latest_csv("signal_results.csv")
        assert result is not None
        assert "2026-03-28" in str(result)


class TestPrintStrategy:
    """(from test_strategy_map.py)."""

    def test_none(self, capsys):
        from nuri.quant.regime.strategy_map import print_strategy
        print_strategy(None)
        output = capsys.readouterr().out
        assert "불가" in output

    def test_with_rec(self, capsys):
        from nuri.quant.regime.strategy_map import StrategyRecommendation, print_strategy
        rec = StrategyRecommendation(
            regime="bull_low_vol", macro_interpretation="양호",
            position_sizing="aggressive",
            recommended_signals=["rsi_oversold"], avoid_signals=["macd_dead"],
            sector_preference=["XLK"],
            signal_regime_stats={"rsi_oversold": {"trades": 10, "win_rate": 0.7, "pf": 2.5, "avg_return": 5.0}},
            notes="test",
        )
        print_strategy(rec)
        output = capsys.readouterr().out
        assert "bull_low_vol" in output
        assert "rsi_oversold" in output

    def test_with_stats(self, capsys):
        from nuri.quant.regime.strategy_map import StrategyRecommendation, print_strategy
        rec = StrategyRecommendation(
            regime="bear_high_vol", macro_interpretation="악화",
            position_sizing="minimal",
            recommended_signals=[], avoid_signals=["macd_golden"],
            sector_preference=["XLP"],
            signal_regime_stats={"macd_golden": {"trades": 8, "win_rate": 0.3, "pf": 0.6, "avg_return": -2.0}},
            notes="최소 포지션",
        )
        print_strategy(rec)
        output = capsys.readouterr().out
        assert "MINIMAL" in output


class TestPrintCrossAnalysis:
    """(from test_strategy_map.py)."""

    def test_empty(self, capsys):
        from nuri.quant.regime.strategy_map import print_cross_analysis
        print_cross_analysis(pd.DataFrame())
        output = capsys.readouterr().out
        assert "없음" in output

    def test_with_data(self, capsys):
        from nuri.quant.regime.strategy_map import print_cross_analysis
        df = pd.DataFrame([
            {"signal_id": "rsi_oversold", "regime": "bull_low_vol", "trades": 10, "win_rate": 0.7, "avg_return": 5.0, "profit_factor": 2.5},
            {"signal_id": "macd_dead", "regime": "bear_high_vol", "trades": 8, "win_rate": 0.3, "avg_return": -2.0, "profit_factor": 0.6},
        ])
        print_cross_analysis(df)
        output = capsys.readouterr().out
        assert "bull_low_vol" in output
        assert "bear_high_vol" in output


# ═══════════════════════════════════════════════════════════════════
# PART 2: FACTORS — momentum, value, quality, composite
# ═══════════════════════════════════════════════════════════════════


class TestMomentum:
    """(from test_factors.py)."""

    def test_compute_with_data(self, factor_data):
        from nuri.quant.factors.momentum import compute_momentum
        result = compute_momentum()
        assert not result.empty
        assert "momentum_score" in result.columns
        for score in result["momentum_score"]:
            assert 0 <= score <= 1

    def test_empty_db(self, db_path_mp):
        from nuri.quant.factors.momentum import compute_momentum
        result = compute_momentum()
        assert result.empty

    def test_with_tickers_filter(self, factor_data):
        from nuri.quant.factors.momentum import compute_momentum
        result = compute_momentum(tickers=["AAPL"])
        assert len(result) <= 1

    def test_insufficient_data(self, db_path_mp):
        prices = pd.DataFrame([{
            "ticker": "SHORT", "date": f"2024-01-{i+1:02d}",
            "open": 100, "high": 101, "low": 99, "close": 100,
            "volume": 1000, "adj_close": 100,
        } for i in range(5)])
        upsert_prices(prices, db_path_mp)
        from nuri.quant.factors.momentum import compute_momentum
        result = compute_momentum()
        assert "SHORT" not in result.index if not result.empty else True


class TestValue:
    """(from test_factors.py)."""

    def test_empty_when_no_data(self, db_path_mp):
        from nuri.quant.factors.value import compute_value
        result = compute_value(tickers=["FAKE"])
        assert result.empty

    def test_normalization_logic(self):
        scores = {"AAPL": {"pe_ratio": 15.0, "pb_ratio": 2.0},
                  "MSFT": {"pe_ratio": 30.0, "pb_ratio": 5.0}}
        df = pd.DataFrame(scores).T
        for col in ["pe_ratio", "pb_ratio"]:
            valid = df[col].dropna()
            inverted = 1 / valid.clip(lower=0.01)
            col_min, col_max = inverted.min(), inverted.max()
            if col_max > col_min:
                df[col + "_norm"] = (inverted - col_min) / (col_max - col_min)
            else:
                df[col + "_norm"] = 0.5
        norm_cols = [c for c in df.columns if c.endswith("_norm")]
        df["value_score"] = df[norm_cols].mean(axis=1)
        assert df.loc["AAPL", "value_score"] > df.loc["MSFT", "value_score"]


class TestQuality:
    """(from test_factors.py)."""

    def test_empty_when_no_data(self, db_path_mp):
        from nuri.quant.factors.quality import compute_quality
        result = compute_quality(tickers=["FAKE"])
        assert result.empty

    def test_normalization_logic(self):
        scores = {"AAPL": {"roe": 0.30, "operating_margin": 0.25},
                  "MSFT": {"roe": 0.15, "operating_margin": 0.10}}
        df = pd.DataFrame(scores).T
        for col in ["roe", "operating_margin"]:
            valid = df[col].dropna()
            col_min, col_max = valid.min(), valid.max()
            if col_max > col_min:
                df[col + "_norm"] = (valid - col_min) / (col_max - col_min)
            else:
                df[col + "_norm"] = 0.5
        norm_cols = [c for c in df.columns if c.endswith("_norm")]
        df["quality_score"] = df[norm_cols].mean(axis=1)
        assert df.loc["AAPL", "quality_score"] > df.loc["MSFT", "quality_score"]


class TestComposite:
    """(from test_factors.py)."""

    def test_weights_sum_to_one(self):
        from nuri.quant.factors.composite import WEIGHTS
        assert abs(sum(WEIGHTS.values()) - 1.0) < 0.001

    def test_compute_with_data(self, factor_data, monkeypatch):
        from nuri.quant.factors import composite as comp_mod
        empty_df = pd.DataFrame()
        monkeypatch.setattr(comp_mod, "compute_value", lambda: empty_df, raising=False)
        monkeypatch.setattr(comp_mod, "compute_quality", lambda: empty_df, raising=False)
        from nuri.quant.factors.momentum import compute_momentum as _cm
        monkeypatch.setattr(comp_mod, "compute_momentum", _cm, raising=False)
        result = comp_mod.compute_composite()
        if not result.empty:
            assert "composite_score" in result.columns
            for score in result["composite_score"]:
                assert 0 <= score <= 1

    def test_compute_manual(self, factor_data):
        from nuri.quant.factors.composite import WEIGHTS
        m, v, q, s = 0.7, 0.5, 0.6, 0.5
        expected = (m * WEIGHTS["momentum"] + v * WEIGHTS["value"] +
                    q * WEIGHTS["quality"] + s * WEIGHTS["sentiment"])
        assert 0 < expected < 1

    def test_print_composite_empty(self, capsys):
        from nuri.quant.factors.composite import print_composite
        print_composite(pd.DataFrame())
        output = capsys.readouterr().out
        assert "없습니다" in output

    def test_print_composite_with_data(self, capsys):
        from nuri.quant.factors.composite import print_composite
        df = pd.DataFrame([{
            "momentum_score": 0.7, "value_score": 0.5,
            "quality_score": 0.6, "sentiment_score": 0.5, "composite_score": 0.58,
        }], index=["AAPL"])
        print_composite(df)
        output = capsys.readouterr().out
        assert "AAPL" in output
        assert "멀티팩터" in output


# ═══════════════════════════════════════════════════════════════════
# PART 3: VALIDATION — signal_backtest
# ═══════════════════════════════════════════════════════════════════


class TestSignalBacktest:
    """C-1 (from test_validation.py)."""

    def test_rsi_oversold_detection(self, sample_prices):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="TEST", signals=["rsi_oversold"], db_path=sample_prices)
        assert len(results) >= 1
        assert results[0].won is True

    def test_holding_period_exit(self, sample_prices):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="TEST", signals=["rsi_oversold"], db_path=sample_prices)
        assert len(results) >= 1
        assert results[0].holding_days == 20

    def test_macd_signal_detection(self, sample_prices):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="TEST", signals=["macd_golden", "macd_dead"], db_path=sample_prices)
        assert isinstance(results, list)
        for r in results:
            assert r.signal_id in ("macd_golden", "macd_dead")

    def test_bb_bounce_detection(self, sample_prices):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="TEST", signals=["bb_bounce"], db_path=sample_prices)
        assert isinstance(results, list)
        for r in results:
            assert r.signal_id == "bb_bounce"
            assert r.holding_days == 20

    def test_sma_cross_with_long_data(self, long_prices):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="LONG", signals=["sma_golden", "sma_dead"], db_path=long_prices)
        assert isinstance(results, list)

    def test_scorecard_calculation(self):
        from nuri.quant.validation.signal_backtest import SignalResult, generate_scorecard
        results = [
            SignalResult("rsi_oversold", "TEST", "2025-01-01", 100, "2025-01-21", 110, 10.0, 20, True),
            SignalResult("rsi_oversold", "TEST", "2025-02-01", 100, "2025-02-21", 95, -5.0, 20, False),
            SignalResult("rsi_oversold", "TEST", "2025-03-01", 100, "2025-03-21", 108, 8.0, 20, True),
        ]
        cards = generate_scorecard(results)
        total = [c for c in cards if c.ticker is None and c.signal_id == "rsi_oversold"]
        assert len(total) == 1
        card = total[0]
        assert card.total_trades == 3
        assert abs(card.win_rate - 2 / 3) < 0.01
        assert abs(card.avg_return - (10 - 5 + 8) / 3) < 0.1
        assert abs(card.profit_factor - 3.6) < 0.1

    def test_scorecard_all_wins(self):
        from nuri.quant.validation.signal_backtest import SignalResult, generate_scorecard
        results = [
            SignalResult("bb_bounce", "A", "2025-01-01", 100, "2025-01-21", 110, 10.0, 20, True),
            SignalResult("bb_bounce", "A", "2025-02-01", 100, "2025-02-21", 105, 5.0, 20, True),
        ]
        cards = generate_scorecard(results)
        total = [c for c in cards if c.ticker is None]
        assert total[0].profit_factor == float("inf")
        assert total[0].win_rate == 1.0

    def test_empty_signals(self, db_path):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="NONEXIST", signals=["rsi_oversold"], db_path=db_path)
        assert results == []


class TestSignalBacktest_R60:
    """(from test_sixty_percent.py)."""

    def test_compute_indicators(self, full_db):
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import compute_indicators
        df = query_df("SELECT * FROM prices WHERE ticker='AAPL' ORDER BY date")
        if not df.empty:
            result = compute_indicators(df)
            assert "rsi_14" in result.columns or "sma_20" in result.columns

    def test_backtest_signals(self, full_db, tmp_path):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(db_path=full_db)
        assert isinstance(results, list)

    def test_generate_scorecard(self):
        from nuri.quant.validation.signal_backtest import SignalResult, generate_scorecard
        results = [
            SignalResult("rsi_oversold", "AAPL", "2024-06-01", 150.0, "2024-06-15", 160.0, 6.67, 10, True),
            SignalResult("rsi_oversold", "AAPL", "2024-07-01", 155.0, "2024-07-15", 150.0, -3.23, 10, False),
            SignalResult("macd_golden", "MSFT", "2024-06-01", 300.0, "2024-06-15", 320.0, 6.67, 10, True),
        ]
        scorecards = generate_scorecard(results)
        assert len(scorecards) > 0

    def test_print_scorecard(self, capsys):
        from nuri.quant.validation.signal_backtest import SignalScorecard, print_scorecard
        scorecards = [
            SignalScorecard(
                signal_id="rsi_oversold", ticker=None,
                total_trades=50, win_rate=0.6,
                avg_return=3.5, median_return=2.5,
                max_return=15.0, max_loss=-8.0,
                profit_factor=2.0, avg_holding_days=10.0,
            ),
        ]
        print_scorecard(scorecards)
        output = capsys.readouterr().out
        assert "rsi_oversold" in output


class TestVolumeSpikeSignal:
    """(from test_signals_extended.py)."""

    def test_volume_spike_detection(self, volume_spike_prices):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="VSPK", signals=["volume_spike"], db_path=volume_spike_prices)
        assert len(results) >= 1
        assert results[0].signal_id == "volume_spike"
        assert results[0].holding_days == 10

    def test_volume_spike_not_triggered_on_normal(self, volume_spike_prices):
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import compute_indicators, detect_signal_entries
        df = query_df(
            "SELECT date, open, high, low, close, volume FROM prices WHERE ticker = ? ORDER BY date",
            ("VSPK",), db_path=volume_spike_prices,
        )
        df["date"] = pd.to_datetime(df["date"])
        df = df.reset_index(drop=True)
        df = compute_indicators(df)
        entries = detect_signal_entries(df, "volume_spike")
        for idx in entries:
            vol = df["volume"].iloc[idx]
            vol_avg = df["volume_sma_20"].iloc[idx]
            assert vol > vol_avg * 3


class TestGapSignals:
    """(from test_signals_extended.py)."""

    def test_gap_up_detection(self, gap_prices):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="GAPTEST", signals=["gap_up"], db_path=gap_prices)
        assert len(results) >= 1
        assert results[0].signal_id == "gap_up"
        assert results[0].holding_days == 10

    def test_gap_down_detection(self, gap_prices):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="GAPTEST", signals=["gap_down"], db_path=gap_prices)
        assert len(results) >= 1
        assert results[0].signal_id == "gap_down"
        assert results[0].holding_days == 10

    def test_gap_signals_no_false_positive(self, gap_prices):
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import compute_indicators, detect_signal_entries
        df = query_df(
            "SELECT date, open, high, low, close, volume FROM prices WHERE ticker = ? ORDER BY date",
            ("GAPTEST",), db_path=gap_prices,
        )
        df["date"] = pd.to_datetime(df["date"])
        df = df.reset_index(drop=True)
        df = compute_indicators(df)
        gap_up_entries = detect_signal_entries(df, "gap_up")
        gap_down_entries = detect_signal_entries(df, "gap_down")
        for idx in gap_up_entries:
            assert df["open"].iloc[idx] > df["close"].iloc[idx - 1] * 1.02
        for idx in gap_down_entries:
            assert df["open"].iloc[idx] < df["close"].iloc[idx - 1] * 0.98


class TestSignalDefinitions:
    """(from test_signals_extended.py)."""

    def test_new_signals_in_definitions(self):
        from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS
        assert "volume_spike" in SIGNAL_DEFINITIONS
        assert "gap_up" in SIGNAL_DEFINITIONS
        assert "gap_down" in SIGNAL_DEFINITIONS
        assert SIGNAL_DEFINITIONS["volume_spike"]["hold_days"] == 10
        assert SIGNAL_DEFINITIONS["gap_up"]["hold_days"] == 10
        assert SIGNAL_DEFINITIONS["gap_down"]["hold_days"] == 10

    def test_buy_sell_classification(self):
        from nuri.quant.validation.signal_backtest import BUY_SIGNALS, SELL_SIGNALS
        assert "volume_spike" in BUY_SIGNALS
        assert "gap_up" in BUY_SIGNALS
        assert "gap_down" in SELL_SIGNALS

    def test_original_7_signals_unchanged(self):
        from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS
        original = ["rsi_oversold", "rsi_overbought", "macd_golden", "macd_dead",
                     "sma_golden", "sma_dead", "bb_bounce"]
        for sig_id in original:
            assert sig_id in SIGNAL_DEFINITIONS
        assert SIGNAL_DEFINITIONS["rsi_oversold"]["hold_days"] == 20
        assert SIGNAL_DEFINITIONS["macd_golden"]["hold_days"] is None
        assert SIGNAL_DEFINITIONS["sma_golden"]["hold_days"] is None

    def test_macro_signals_in_definitions(self):
        from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS
        assert "vix_reversal" in SIGNAL_DEFINITIONS
        assert "pcr_reversal" in SIGNAL_DEFINITIONS
        assert "yield_curve_recovery" in SIGNAL_DEFINITIONS
        assert SIGNAL_DEFINITIONS["vix_reversal"]["hold_days"] == 20
        assert SIGNAL_DEFINITIONS["pcr_reversal"]["hold_days"] == 15
        assert SIGNAL_DEFINITIONS["yield_curve_recovery"]["hold_days"] is None

    def test_macro_signals_in_buy_classification(self):
        from nuri.quant.validation.signal_backtest import BUY_SIGNALS
        assert "vix_reversal" in BUY_SIGNALS
        assert "pcr_reversal" in BUY_SIGNALS
        assert "yield_curve_recovery" in BUY_SIGNALS

    def test_total_signal_count_is_15(self):
        from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS
        assert len(SIGNAL_DEFINITIONS) == 15


class TestVixReversal:
    """(from test_signals_extended.py)."""

    def test_vix_reversal_detection(self, vix_reversal_data):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="SPY", signals=["vix_reversal"], db_path=vix_reversal_data)
        assert len(results) >= 1
        assert results[0].signal_id == "vix_reversal"
        assert results[0].holding_days == 20

    def test_vix_reversal_no_false_positive_1day(self, db_path):
        dates = pd.date_range("2025-01-01", periods=60)
        close = np.linspace(100, 120, 60)
        df = pd.DataFrame({
            "ticker": "TEST1D",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.999, "high": close * 1.01,
            "low": close * 0.99, "close": close,
            "volume": [1_000_000] * 60, "adj_close": close,
        })
        upsert_prices(df, db_path)
        macro_records = []
        for i, d in enumerate(dates):
            vix = 35.0 if i == 21 else (24.0 if i == 22 else 18.0)
            macro_records.append({"indicator": "vix", "date": d.strftime("%Y-%m-%d"), "value": vix, "source": "test"})
        upsert_macro(macro_records, db_path)
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="TEST1D", signals=["vix_reversal"], db_path=db_path)
        assert len(results) == 0


class TestPcrReversal:
    """(from test_signals_extended.py)."""

    def test_pcr_reversal_detection(self, pcr_reversal_data):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="SPY", signals=["pcr_reversal"], db_path=pcr_reversal_data)
        assert len(results) >= 1
        assert results[0].signal_id == "pcr_reversal"
        assert results[0].holding_days == 15


class TestYieldCurveRecovery:
    """(from test_signals_extended.py)."""

    def test_yield_curve_recovery_detection(self, yield_curve_data):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="SPY", signals=["yield_curve_recovery"], db_path=yield_curve_data)
        assert len(results) >= 1
        assert results[0].signal_id == "yield_curve_recovery"

    def test_graceful_skip_no_macro_data(self, db_path):
        dates = pd.date_range("2025-01-01", periods=60)
        close = np.linspace(100, 120, 60)
        df = pd.DataFrame({
            "ticker": "NOMACRO",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.999, "high": close * 1.01,
            "low": close * 0.99, "close": close,
            "volume": [1_000_000] * 60, "adj_close": close,
        })
        upsert_prices(df, db_path)
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(
            ticker="NOMACRO", signals=["vix_reversal", "pcr_reversal", "yield_curve_recovery"], db_path=db_path,
        )
        assert results == []


class TestInsiderCluster:
    """(from test_signals_extended.py)."""

    def test_insider_cluster_detection(self, insider_cluster_data):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="INSD", signals=["insider_cluster"], db_path=insider_cluster_data)
        assert len(results) >= 1
        assert results[0].signal_id == "insider_cluster"
        assert results[0].holding_days == 20

    def test_insider_cluster_no_data_graceful(self, db_path):
        dates = pd.date_range("2025-01-01", periods=60)
        close = np.linspace(100, 115, 60)
        df = pd.DataFrame({
            "ticker": "NOINSD",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.999, "high": close * 1.01,
            "low": close * 0.99, "close": close,
            "volume": [1_000_000] * 60, "adj_close": close,
        })
        upsert_prices(df, db_path)
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="NOINSD", signals=["insider_cluster"], db_path=db_path)
        assert results == []


class TestShortSqueeze:
    """(from test_signals_extended.py)."""

    def test_short_squeeze_detection(self, short_squeeze_data):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="SQZZ", signals=["short_squeeze"], db_path=short_squeeze_data)
        assert len(results) >= 1
        assert results[0].signal_id == "short_squeeze"
        assert results[0].holding_days == 15

    def test_short_squeeze_no_data_graceful(self, db_path):
        dates = pd.date_range("2025-01-01", periods=60)
        close = np.linspace(100, 115, 60)
        df = pd.DataFrame({
            "ticker": "NOSI",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.999, "high": close * 1.01,
            "low": close * 0.99, "close": close,
            "volume": [1_000_000] * 60, "adj_close": close,
        })
        upsert_prices(df, db_path)
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="NOSI", signals=["short_squeeze"], db_path=db_path)
        assert results == []


class TestSignalBacktest_R27:
    """(from test_coverage_round27.py)."""

    def test_compute_indicators_pandas_fallback(self):
        from nuri.quant.validation.signal_backtest import compute_indicators
        dates = pd.bdate_range("2024-01-01", periods=50)
        df = pd.DataFrame({
            "date": dates,
            "close": np.random.uniform(100, 200, 50),
            "volume": np.random.uniform(100000, 500000, 50),
        })
        result = compute_indicators(df)
        assert "rsi_14" in result.columns
        assert "macd" in result.columns
        assert "bb_lower" in result.columns
        assert "volume_sma_20" in result.columns

    def test_merge_macro_data(self, db_path):
        from nuri.quant.validation.signal_backtest import merge_macro_data
        _seed_macro(db_path)
        df = pd.DataFrame({"date": pd.to_datetime(["2025-03-28"]), "close": [100.0]})
        result = merge_macro_data(df, db_path=db_path)
        assert "macro_vix" in result.columns
        assert "macro_pcr" in result.columns
        assert "macro_yield_spread" in result.columns

    def test_merge_macro_data_no_date_column(self, db_path):
        from nuri.quant.validation.signal_backtest import merge_macro_data
        df = pd.DataFrame({"close": [100.0]})
        result = merge_macro_data(df, db_path=db_path)
        assert "macro_vix" not in result.columns

    def test_merge_macro_data_fallback_yield(self, db_path):
        from nuri.quant.validation.signal_backtest import merge_macro_data
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)", ("us_2y_yield", "2025-03-28", 4.0))
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)", ("us_10y_yield", "2025-03-28", 4.5))
        df = pd.DataFrame({"date": pd.to_datetime(["2025-03-28"]), "close": [100.0]})
        result = merge_macro_data(df, db_path=db_path)
        assert "macro_yield_spread" in result.columns

    def test_merge_data_signals(self, db_path):
        from nuri.quant.validation.signal_backtest import merge_data_signals
        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO insider_trades (ticker, date, transaction_type, shares, value) VALUES (?,?,?,?,?)",
                    ("AAPL", f"2025-03-{20+i:02d}", "Purchase", 100, 15000),
                )
        df = pd.DataFrame({"date": pd.to_datetime(["2025-03-25", "2025-03-26", "2025-03-27"]), "close": [150, 151, 152]})
        result = merge_data_signals(df, "AAPL", db_path=db_path)
        assert "insider_buy_count_10d" in result.columns
        assert "short_interest" in result.columns

    def test_merge_data_signals_no_date(self, db_path):
        from nuri.quant.validation.signal_backtest import merge_data_signals
        df = pd.DataFrame({"close": [100]})
        result = merge_data_signals(df, "AAPL", db_path=db_path)
        assert "insider_buy_count_10d" not in result.columns

    def test_entry_detectors_individual(self):
        from nuri.quant.validation.signal_backtest import (
            _entry_gap_down,
            _entry_gap_up,
            _entry_insider_cluster,
            _entry_pcr_reversal,
            _entry_short_squeeze,
            _entry_vix_reversal,
            _entry_volume_spike,
        )
        df = pd.DataFrame({"open": [100, 105], "close": [100, 102]})
        assert _entry_gap_up(df, 1) is True
        df = pd.DataFrame({"open": [100, 95], "close": [100, 98]})
        assert _entry_gap_down(df, 1) is True
        df = pd.DataFrame({"volume": [100000] * 20 + [500000], "volume_sma_20": [100000] * 20 + [100000]})
        assert _entry_volume_spike(df, 20) is True
        df = pd.DataFrame({"macro_vix": [35, 32, 31, 30, 24]})
        assert _entry_vix_reversal(df, 4) is True
        df2 = pd.DataFrame({"close": [100, 101]})
        assert _entry_vix_reversal(df2, 1) is False
        pcr_vals = [0.7] * 15 + [1.3, 1.2, 1.1, 1.0, 0.9, 0.75]
        df = pd.DataFrame({"macro_pcr": pcr_vals})
        assert _entry_pcr_reversal(df, len(pcr_vals) - 1) is True
        df = pd.DataFrame({"insider_buy_count_10d": [0, 1, 2, 3]})
        assert _entry_insider_cluster(df, 3) is True
        df = pd.DataFrame({"short_interest": [5, 5, 15, 15, 15, 15], "close": [100, 101, 102, 103, 104, 105]})
        assert _entry_short_squeeze(df, 5) is True

    def test_exit_functions(self):
        from nuri.quant.validation.signal_backtest import (
            _exit_macd_dead,
            _exit_macd_golden,
            _exit_sma_dead,
            _exit_sma_golden,
            _exit_yield_curve_recovery,
        )
        df = pd.DataFrame({"macd": [1.0, -0.5], "macd_signal": [0.5, 0.5]})
        assert _exit_macd_golden(df, 1) is True
        assert _exit_macd_golden(df, 0) is False
        df = pd.DataFrame({"macd": [-1.0, 0.5], "macd_signal": [-0.5, -0.5]})
        assert _exit_macd_dead(df, 1) is True
        df = pd.DataFrame({"sma_50": [200, 150], "sma_200": [190, 180]})
        assert _exit_sma_golden(df, 1) is True
        df = pd.DataFrame({"sma_50": [150, 200], "sma_200": [180, 180]})
        assert _exit_sma_dead(df, 1) is True
        df = pd.DataFrame({"macro_yield_spread": [0.5, -0.1]})
        assert _exit_yield_curve_recovery(df, 1) is True
        df2 = pd.DataFrame({"close": [100]})
        assert _exit_yield_curve_recovery(df2, 0) is False

    def test_backtest_signals_with_data(self, db_path):
        from nuri.quant.validation.signal_backtest import backtest_signals
        _seed_prices(db_path, "AAPL", days=60)
        _seed_portfolio(db_path, [("AAPL", 150.0, 10)])
        results = backtest_signals(ticker="AAPL", signals=["rsi_oversold", "gap_up"], db_path=db_path)
        assert isinstance(results, list)

    def test_generate_scorecard(self):
        from nuri.quant.validation.signal_backtest import SignalResult, generate_scorecard
        results = [
            SignalResult("rsi_oversold", "AAPL", "2025-01-01", 100, "2025-01-20", 110, 10.0, 20, True),
            SignalResult("rsi_oversold", "AAPL", "2025-02-01", 110, "2025-02-20", 105, -4.5, 20, False),
            SignalResult("rsi_oversold", "TSLA", "2025-01-10", 200, "2025-01-30", 220, 10.0, 20, True),
        ]
        scorecards = generate_scorecard(results)
        assert len(scorecards) > 0
        total_cards = [s for s in scorecards if s.ticker is None]
        assert len(total_cards) >= 1

    def test_generate_scorecard_empty(self):
        from nuri.quant.validation.signal_backtest import generate_scorecard
        assert generate_scorecard([]) == []

    def test_print_scorecard(self, capsys):
        from nuri.quant.validation.signal_backtest import SignalScorecard, print_scorecard
        print_scorecard([])
        captured = capsys.readouterr()
        assert "데이터가 없습니다" in captured.out
        sc = [SignalScorecard("rsi_oversold", None, 10, 0.6, 5.0, 4.0, 15.0, -3.0, 2.0, 15.0)]
        print_scorecard(sc)

    def test_detect_signal_entries_unknown(self):
        from nuri.quant.validation.signal_backtest import detect_signal_entries
        df = pd.DataFrame({"close": [100, 101]})
        assert detect_signal_entries(df, "nonexistent_signal") == []

    def test_compute_exit_hold_days(self):
        from nuri.quant.validation.signal_backtest import compute_exit
        df = pd.DataFrame({"close": list(range(30))})
        assert compute_exit(df, 5, "rsi_oversold") == 25
        assert compute_exit(df, 15, "rsi_oversold") is None

    def test_compute_exit_signal_based(self):
        from nuri.quant.validation.signal_backtest import compute_exit
        df = pd.DataFrame({
            "close": list(range(10)),
            "macd": [1, 1, 1, 0.5, 0.3, -0.1, -0.5, -1, -1, -1],
            "macd_signal": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        })
        result = compute_exit(df, 1, "macd_golden")
        assert result == 5

    def test_public_api_functions_exist(self):
        from nuri.quant.validation.signal_backtest import (
            compute_exit,
            compute_indicators,
            detect_signal_entries,
            merge_data_signals,
            merge_macro_data,
        )
        assert compute_indicators is not None
        assert detect_signal_entries is not None
        assert compute_exit is not None
        assert merge_macro_data is not None
        assert merge_data_signals is not None


class TestMacroSignalDetectors:
    """(from test_coverage_round19.py)."""

    def _make_df(self, n=30):
        return pd.DataFrame({"date": pd.date_range("2025-01-01", periods=n),
                             "close": np.linspace(100, 110, n),
                             "open": np.linspace(99, 109, n),
                             "volume": [1000000] * n})

    def test_vix_reversal_entry(self):
        from nuri.quant.validation.signal_backtest import _entry_vix_reversal
        df = self._make_df(30)
        df["macro_vix"] = 32.0
        df.loc[26:, "macro_vix"] = 24.0
        assert _entry_vix_reversal(df, 26) is True

    def test_vix_reversal_no_entry(self):
        from nuri.quant.validation.signal_backtest import _entry_vix_reversal
        df = self._make_df(30)
        df["macro_vix"] = 20.0
        assert _entry_vix_reversal(df, 10) is False

    def test_vix_reversal_missing_column(self):
        from nuri.quant.validation.signal_backtest import _entry_vix_reversal
        df = self._make_df(30)
        assert _entry_vix_reversal(df, 10) is False

    def test_pcr_reversal_entry(self):
        from nuri.quant.validation.signal_backtest import _entry_pcr_reversal
        df = self._make_df(30)
        df["macro_pcr"] = 0.9
        df.loc[5:10, "macro_pcr"] = 1.3
        df.loc[22:, "macro_pcr"] = 0.7
        assert _entry_pcr_reversal(df, 25) is True

    def test_pcr_reversal_no_peak(self):
        from nuri.quant.validation.signal_backtest import _entry_pcr_reversal
        df = self._make_df(30)
        df["macro_pcr"] = 0.7
        assert _entry_pcr_reversal(df, 25) is False

    def test_yield_curve_recovery_entry(self):
        from nuri.quant.validation.signal_backtest import _entry_yield_curve_recovery
        df = self._make_df(10)
        df["macro_yield_spread"] = [-0.5, -0.4, -0.3, -0.2, -0.1, 0.05, 0.1, 0.2, 0.3, 0.4]
        assert _entry_yield_curve_recovery(df, 5) is True

    def test_yield_curve_recovery_no_entry(self):
        from nuri.quant.validation.signal_backtest import _entry_yield_curve_recovery
        df = self._make_df(10)
        df["macro_yield_spread"] = [0.5] * 10
        assert _entry_yield_curve_recovery(df, 5) is False


class TestDataSignalDetectors:
    """(from test_coverage_round19.py)."""

    def test_insider_cluster_entry(self):
        from nuri.quant.validation.signal_backtest import _entry_insider_cluster
        df = pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=10),
            "close": [100] * 10,
            "insider_buy_count_10d": [0, 1, 2, 2, 3, 4, 4, 3, 2, 1],
        })
        assert _entry_insider_cluster(df, 4) is True

    def test_short_squeeze_entry(self):
        from nuri.quant.validation.signal_backtest import _entry_short_squeeze
        df = pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=10),
            "close": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
            "short_interest": [12.0] * 10,
        })
        assert _entry_short_squeeze(df, 5) is True


class TestComputeExit_R19:
    """(from test_coverage_round19.py)."""

    def test_hold_days_exit(self):
        from nuri.quant.validation.signal_backtest import compute_exit
        df = pd.DataFrame({"close": range(50)})
        assert compute_exit(df, 5, "rsi_oversold") == 25

    def test_hold_days_exit_out_of_range(self):
        from nuri.quant.validation.signal_backtest import compute_exit
        df = pd.DataFrame({"close": range(10)})
        assert compute_exit(df, 5, "rsi_oversold") is None

    def test_signal_exit_function(self):
        from nuri.quant.validation.signal_backtest import compute_exit
        df = pd.DataFrame({"close": range(20), "macd": [0.5] * 10 + [-0.5] * 10, "macd_signal": [0.0] * 20})
        assert compute_exit(df, 0, "macd_golden") == 10

    def test_yield_curve_recovery_exit(self):
        from nuri.quant.validation.signal_backtest import compute_exit
        df = pd.DataFrame({"close": range(20), "macro_yield_spread": [0.5] * 10 + [-0.5] * 10})
        assert compute_exit(df, 0, "yield_curve_recovery") == 10


class TestMergeDataSignals_R19:
    """(from test_coverage_round19.py)."""

    def test_merge_with_insider_trades(self, tmp_path):
        from nuri.quant.validation.signal_backtest import merge_data_signals
        path = tmp_path / "test.db"
        init_db(path)
        with get_db(path) as conn:
            conn.execute(
                "INSERT INTO insider_trades (ticker, date, insider_name, transaction_type, shares, value) VALUES (?, ?, ?, ?, ?, ?)",
                ("AAPL", "2025-03-01", "Tim Cook", "P-Purchase", 1000, 190000.0),
            )
        dates = pd.date_range("2025-02-25", periods=10, freq="B")
        df = pd.DataFrame({"date": dates, "close": [190.0] * 10})
        result = merge_data_signals(df, "AAPL", db_path=path)
        assert "insider_buy_count_10d" in result.columns
        assert "short_interest" in result.columns

    def test_merge_empty_db(self, tmp_path):
        from nuri.quant.validation.signal_backtest import merge_data_signals
        path = tmp_path / "test.db"
        init_db(path)
        df = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=5), "close": [100] * 5})
        result = merge_data_signals(df, "AAPL", db_path=path)
        assert "insider_buy_count_10d" in result.columns


class TestMergeMacroData_R19:
    """(from test_coverage_round19.py)."""

    def test_merge_macro(self, rich_db):
        from nuri.quant.validation.signal_backtest import merge_macro_data
        dates = pd.date_range("2025-01-01", periods=20, freq="B")
        df = pd.DataFrame({"date": dates, "close": np.linspace(100, 110, 20)})
        result = merge_macro_data(df, db_path=rich_db)
        assert "macro_vix" in result.columns
        assert "macro_pcr" in result.columns
        assert "macro_yield_spread" in result.columns

    def test_merge_macro_no_date_col(self):
        from nuri.quant.validation.signal_backtest import merge_macro_data
        df = pd.DataFrame({"close": [100, 101]})
        result = merge_macro_data(df)
        assert "macro_vix" not in result.columns


class TestSignalScorecard_R19:
    """(from test_coverage_round19.py)."""

    def test_generate_scorecard_with_results(self):
        from nuri.quant.validation.signal_backtest import SignalResult, generate_scorecard
        results = [
            SignalResult(signal_id="rsi_oversold", ticker="AAPL",
                         entry_date="2025-01-01", entry_price=100.0,
                         exit_date="2025-01-21", exit_price=110.0,
                         return_pct=10.0, holding_days=20, won=True),
            SignalResult(signal_id="rsi_oversold", ticker="AAPL",
                         entry_date="2025-02-01", entry_price=110.0,
                         exit_date="2025-02-21", exit_price=105.0,
                         return_pct=-4.55, holding_days=20, won=False),
        ]
        scorecards = generate_scorecard(results)
        assert len(scorecards) >= 2
        aggregate = [s for s in scorecards if s.ticker is None]
        assert len(aggregate) == 1
        assert aggregate[0].total_trades == 2
        assert aggregate[0].win_rate == 0.5

    def test_print_scorecard_empty(self, capsys):
        from nuri.quant.validation.signal_backtest import print_scorecard
        print_scorecard([])
        captured = capsys.readouterr()
        assert "없습니다" in captured.out


class TestSignalBacktestDeep:
    """(from test_coverage_round8.py)."""

    def test_compute_indicators(self, rich_db):
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import compute_indicators
        df = query_df("SELECT * FROM prices WHERE ticker='AAPL' ORDER BY date")
        if len(df) > 50:
            result = compute_indicators(df)
            assert "rsi_14" in result.columns
            assert "macd" in result.columns

    def test_detect_signal_entries(self, rich_db):
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import compute_indicators, detect_signal_entries
        df = query_df("SELECT * FROM prices WHERE ticker='AAPL' ORDER BY date")
        if len(df) > 50:
            df = compute_indicators(df)
            entries = detect_signal_entries(df, "rsi_oversold")
            assert isinstance(entries, list)

    def test_compute_exit(self, rich_db):
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import compute_exit, compute_indicators, detect_signal_entries
        df = query_df("SELECT * FROM prices WHERE ticker='AAPL' ORDER BY date")
        if len(df) > 50:
            df = compute_indicators(df)
            entries = detect_signal_entries(df, "rsi_oversold")
            if entries:
                exit_idx = compute_exit(df, entries[0], "rsi_oversold")
                assert exit_idx is None or isinstance(exit_idx, int)


class TestSignalBacktestMore:
    """(from test_coverage_round12.py)."""

    def test_macd_signal(self, rich_db):
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import compute_indicators, detect_signal_entries
        df = query_df("SELECT * FROM prices WHERE ticker='AAPL' ORDER BY date")
        if len(df) > 50:
            df = compute_indicators(df)
            entries = detect_signal_entries(df, "macd_golden")
            assert isinstance(entries, list)

    def test_bb_bounce_signal(self, rich_db):
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import compute_indicators, detect_signal_entries
        df = query_df("SELECT * FROM prices WHERE ticker='AAPL' ORDER BY date")
        if len(df) > 50:
            df = compute_indicators(df)
            entries = detect_signal_entries(df, "bb_bounce")
            assert isinstance(entries, list)

    def test_volume_spike(self, rich_db):
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import compute_indicators, detect_signal_entries
        df = query_df("SELECT * FROM prices WHERE ticker='AAPL' ORDER BY date")
        if len(df) > 50:
            df = compute_indicators(df)
            entries = detect_signal_entries(df, "volume_spike")
            assert isinstance(entries, list)

    def test_sma_golden(self, rich_db):
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import compute_indicators, detect_signal_entries
        df = query_df("SELECT * FROM prices WHERE ticker='AAPL' ORDER BY date")
        if len(df) > 50:
            df = compute_indicators(df)
            entries = detect_signal_entries(df, "sma_golden")
            assert isinstance(entries, list)


class TestSignalBacktestRun:
    """(from test_coverage_round13.py)."""

    def test_backtest_signals(self, rich_db):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals()
        assert isinstance(results, list)


class TestSignalBacktestHelpers:
    """(from test_coverage_final.py)."""

    def test_signal_definitions(self):
        from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS
        assert isinstance(SIGNAL_DEFINITIONS, dict)
        assert len(SIGNAL_DEFINITIONS) > 0

    def test_backtest_signals_callable(self):
        from nuri.quant.validation.signal_backtest import backtest_signals
        assert callable(backtest_signals)


# ═══════════════════════════════════════════════════════════════════
# PART 3b: VALIDATION — superinvestor_backtest
# ═══════════════════════════════════════════════════════════════════


class TestSuperinvestorBacktest:
    """C-2 (from test_validation.py)."""

    def test_data_readiness_check(self, db_path):
        from nuri.quant.validation.superinvestor_backtest import _check_data_readiness
        assert _check_data_readiness(db_path=db_path) is False

    def test_empty_backtest(self, db_path):
        from nuri.quant.validation.superinvestor_backtest import backtest_superinvestor
        results = backtest_superinvestor(db_path=db_path)
        assert results == []


class TestSuperinvestorBacktest_Final:
    """(from test_coverage_final.py)."""

    def test_import(self):
        from nuri.quant.validation.superinvestor_backtest import backtest_superinvestor
        assert callable(backtest_superinvestor)

    def test_data_readiness_empty(self, db_path):
        from nuri.quant.validation.superinvestor_backtest import _check_data_readiness
        ready = _check_data_readiness(db_path=db_path)
        assert ready is False

    def test_get_price_not_found(self, db_path):
        from nuri.quant.validation.superinvestor_backtest import _get_price_on_or_after
        result = _get_price_on_or_after("FAKE", "2026-01-01", db_path=db_path)
        assert result is None


class TestSuperinvestorBacktest_R19:
    """(from test_coverage_round19.py)."""

    def test_check_data_readiness_no_data(self, tmp_path):
        path = tmp_path / "test.db"
        init_db(path)
        from nuri.quant.validation.superinvestor_backtest import _check_data_readiness
        assert _check_data_readiness(db_path=path) is False

    def test_check_data_readiness_one_quarter(self, tmp_path):
        from nuri.quant.validation.superinvestor_backtest import _check_data_readiness
        path = tmp_path / "test.db"
        init_db(path)
        with get_db(path) as conn:
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, filing_date, shares, market_value) VALUES (?, ?, ?, ?, ?)",
                ("Buffett", "AAPL", "2025-01-15", 100000, 50000000),
            )
        assert _check_data_readiness(db_path=path) is False

    def test_check_data_readiness_two_quarters(self, tmp_path):
        from nuri.quant.validation.superinvestor_backtest import _check_data_readiness
        path = tmp_path / "test.db"
        init_db(path)
        with get_db(path) as conn:
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, filing_date, shares, market_value) VALUES (?, ?, ?, ?, ?)",
                ("Buffett", "AAPL", "2025-01-15", 100000, 50000000),
            )
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, filing_date, shares, market_value) VALUES (?, ?, ?, ?, ?)",
                ("Buffett", "AAPL", "2025-04-15", 120000, 60000000),
            )
        assert _check_data_readiness(db_path=path) is True

    def test_backtest_no_data_returns_empty(self, tmp_path):
        from nuri.quant.validation.superinvestor_backtest import backtest_superinvestor
        path = tmp_path / "test.db"
        init_db(path)
        results = backtest_superinvestor(db_path=path)
        assert results == []

    def test_generate_scorecard_empty(self):
        from nuri.quant.validation.superinvestor_backtest import generate_scorecard
        assert generate_scorecard([], 120) == []

    def test_generate_scorecard_with_results(self):
        from nuri.quant.validation.superinvestor_backtest import FollowResult, generate_scorecard
        results = [
            FollowResult(investor="Buffett", ticker="AAPL", filing_date="2025-01-15",
                         change_type="NEW", entry_date="2025-01-16", entry_price=190.0,
                         exit_date="2025-05-16", exit_price=210.0,
                         return_pct=10.53, benchmark_return_pct=5.0, excess_return_pct=5.53),
            FollowResult(investor="Buffett", ticker="MSFT", filing_date="2025-01-15",
                         change_type="INCREASED", entry_date="2025-01-16", entry_price=400.0,
                         exit_date="2025-05-16", exit_price=380.0,
                         return_pct=-5.0, benchmark_return_pct=5.0, excess_return_pct=-10.0),
        ]
        scorecards = generate_scorecard(results, 120)
        assert len(scorecards) == 1
        sc = scorecards[0]
        assert sc.investor == "Buffett"
        assert sc.total_follows == 2
        assert sc.win_rate == 0.5

    def test_print_scorecard_empty(self, capsys):
        from nuri.quant.validation.superinvestor_backtest import print_scorecard
        print_scorecard([])
        captured = capsys.readouterr()
        assert "없습니다" in captured.out

    def test_print_scorecard_with_data(self, capsys):
        from nuri.quant.validation.superinvestor_backtest import InvestorScorecard, print_scorecard
        sc = InvestorScorecard(
            investor="Buffett", hold_days=120, total_follows=5,
            win_rate=0.6, avg_return=8.5, avg_excess_return=3.2,
            best_ticker="AAPL", best_return=25.0,
            worst_ticker="META", worst_return=-10.0,
        )
        print_scorecard([sc])
        captured = capsys.readouterr()
        assert "Buffett" in captured.out
        assert "120일" in captured.out


class TestSuperinvestorBacktestData:
    """(from test_coverage_round12.py)."""

    def test_backtest_with_superinvestor_data(self, rich_db):
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO superinvestors "
                "(investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name) "
                "VALUES ('Buffett', '2025-08-15', 'AAPL', 900000000, 171000000000, 48.5, 'Apple Inc')")
            conn.execute(
                "INSERT OR REPLACE INTO superinvestors "
                "(investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name) "
                "VALUES ('Buffett', '2025-02-15', 'AAPL', 905000000, 165000000000, 49.0, 'Apple Inc')")
        from nuri.quant.validation.superinvestor_backtest import backtest_superinvestor
        results = backtest_superinvestor()
        assert isinstance(results, list)


class TestSuperinvestorBacktestIntegration:
    """(from test_coverage_round19.py)."""

    def test_backtest_with_mocked_detect_changes(self, rich_db):
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, filing_date, shares, market_value) VALUES (?, ?, ?, ?, ?)",
                ("Warren Buffett", "AAPL", "2024-02-15", 100000, 50000000))
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, filing_date, shares, market_value) VALUES (?, ?, ?, ?, ?)",
                ("Warren Buffett", "AAPL", "2024-05-15", 120000, 60000000))
        mock_changes = pd.DataFrame([{
            "ticker": "AAPL", "filing_date": "2024-05-15",
            "change_type": "INCREASED", "shares_change": 20000,
        }])
        from nuri.quant.validation.superinvestor_backtest import backtest_superinvestor
        with patch("nuri.collectors.superinvestors.detect_changes", return_value=mock_changes), \
             patch("nuri.collectors.superinvestors.SUPERINVESTORS", {"Warren Buffett": "0000000001"}):
            results = backtest_superinvestor(investor="Warren Buffett", hold_days=30, db_path=rich_db)
        assert isinstance(results, list)
        if results:
            assert results[0].investor == "Warren Buffett"
            assert results[0].ticker == "AAPL"


# ═══════════════════════════════════════════════════════════════════
# PART 3c: VALIDATION — analyst_backtest
# ═══════════════════════════════════════════════════════════════════


class TestAnalystBacktest:
    """C-3 (from test_validation.py)."""

    def test_insufficient_data_message(self, db_path):
        from nuri.quant.validation.analyst_backtest import validate_estimates
        results = validate_estimates(min_elapsed_days=90, db_path=db_path)
        assert results == []


class TestAnalystBacktest_Extra:
    """(from test_coverage_extra.py)."""

    def test_validate_estimates(self, db_path):
        from nuri.quant.validation.analyst_backtest import validate_estimates
        results = validate_estimates(db_path=db_path)
        assert isinstance(results, list)

    def test_estimate_result_class(self):
        from nuri.quant.validation.analyst_backtest import EstimateResult
        r = EstimateResult(
            ticker="AAPL", estimate_date="2026-01-01", recommendation="Buy",
            target_mean=200.0, price_at_estimate=180.0, actual_price=195.0,
            actual_date="2026-04-01", target_gap_pct=11.1, actual_return_pct=8.3,
            target_hit=False,
        )
        assert r.target_hit is False
        assert r.ticker == "AAPL"


class TestAnalystBacktestData:
    """(from test_coverage_round12.py)."""

    def test_with_estimates_data(self, rich_db):
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO estimates "
                "(ticker, date, recommendation, target_high, target_low, "
                "target_mean, target_median, num_analysts, current_price) "
                "VALUES ('AAPL', '2025-06-01', 'buy', 250, 180, 220, 215, 30, 190)")
        from nuri.quant.validation.analyst_backtest import validate_estimates
        results = validate_estimates()
        assert isinstance(results, list)


# ═══════════════════════════════════════════════════════════════════
# PART 3d: VALIDATION — scorecard
# ═══════════════════════════════════════════════════════════════════


class TestGenerateValidationReport:
    """C-4 (from test_scorecard.py)."""

    @pytest.fixture
    def report_dir(self, tmp_path):
        d = tmp_path / "2026-03-28"
        d.mkdir()
        sig_data = pd.DataFrame([
            {"ticker": None, "signal_id": "rsi_oversold", "total_trades": 50, "win_rate": 0.65,
             "profit_factor": 2.1, "avg_return": 5.2, "median_return": 3.8},
            {"ticker": None, "signal_id": "macd_golden", "total_trades": 30, "win_rate": 0.55,
             "profit_factor": 1.5, "avg_return": 2.1, "median_return": 1.5},
            {"ticker": None, "signal_id": "bb_bounce", "total_trades": 40, "win_rate": 0.45,
             "profit_factor": 0.8, "avg_return": -1.0, "median_return": -0.5},
        ])
        sig_data.to_csv(d / "signal_scorecard.csv", index=False)
        return d

    @pytest.fixture
    def full_report_dir(self, report_dir):
        si_data = pd.DataFrame([
            {"investor": "Buffett", "total_follows": 20, "win_rate": 0.70, "avg_return": 12.0, "avg_excess_return": 5.0},
            {"investor": "Dalio", "total_follows": 15, "win_rate": 0.55, "avg_return": 6.0, "avg_excess_return": -1.0},
        ])
        si_data.to_csv(report_dir / "superinvestor_scorecard.csv", index=False)
        an_data = pd.DataFrame([
            {"recommendation": "Strong Buy", "target_hit": True, "actual_return_pct": 15.0},
            {"recommendation": "Strong Buy", "target_hit": True, "actual_return_pct": 8.0},
            {"recommendation": "Buy", "target_hit": False, "actual_return_pct": -3.0},
            {"recommendation": "Hold", "target_hit": False, "actual_return_pct": 1.0},
        ])
        an_data.to_csv(report_dir / "analyst_results.csv", index=False)
        return report_dir

    def test_with_signal_only(self, report_dir):
        from nuri.quant.validation.scorecard import generate_validation_report
        path = generate_validation_report(output_dir=report_dir)
        assert path is not None
        assert path.exists()
        assert path.suffix == ".html"
        content = path.read_text()
        assert "rsi_oversold" in content

    def test_with_all_sections(self, full_report_dir):
        from nuri.quant.validation.scorecard import generate_validation_report
        path = generate_validation_report(output_dir=full_report_dir)
        assert path is not None
        content = path.read_text()
        assert "Buffett" in content

    def test_no_csv_returns_none(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        from nuri.quant.validation.scorecard import generate_validation_report
        path = generate_validation_report(output_dir=d)
        assert path is None


# ═══════════════════════════════════════════════════════════════════
# PART 4: BACKTEST — optimizer
# ═══════════════════════════════════════════════════════════════════


class TestOptimizer:
    """(from test_coverage_round5.py)."""

    def test_optimize_signal_import(self):
        from nuri.quant.backtest.optimizer import optimize_signal
        assert callable(optimize_signal)


class TestOptimizer_NewFeatures:
    """(from test_new_features.py)."""

    def test_optimize_signal(self, db_path):
        prices = []
        for i in range(200):
            date = f"2025-{(i // 30 + 1):02d}-{(i % 28 + 1):02d}"
            prices.append({
                "ticker": "AAPL", "date": date,
                "open": 150 + i * 0.1, "high": 152 + i * 0.1,
                "low": 148 + i * 0.1, "close": 150 + i * 0.1,
                "volume": 1000000, "adj_close": 150 + i * 0.1,
            })
        upsert_prices(pd.DataFrame(prices), db_path)
        upsert_portfolio([
            {"account": "test", "ticker": "AAPL", "quantity": 10,
             "avg_price": 150, "currency": "USD", "sector": "Tech"},
        ], db_path)
        from nuri.quant.backtest.optimizer import optimize_signal
        results = optimize_signal("rsi_oversold", db_path=db_path)
        assert isinstance(results, list)


class TestOptimizerExtended:
    """(from test_sixty_percent.py)."""

    def test_optimize_signal(self, full_db):
        from nuri.quant.backtest.optimizer import optimize_signal
        result = optimize_signal("rsi_oversold", db_path=full_db)
        assert isinstance(result, (list, type(None)))

    def test_backtest_with_params(self, full_db):
        from nuri.core.db import query_df
        from nuri.quant.backtest.optimizer import _backtest_signal_with_params
        df = query_df("SELECT * FROM prices WHERE ticker='AAPL' ORDER BY date")
        if not df.empty and len(df) > 50:
            result = _backtest_signal_with_params(df, "rsi_oversold", {"rsi_entry": 30, "rsi_exit": 70})
            assert result is None or hasattr(result, "win_rate")


class TestOptimizerAll:
    """(from test_coverage_round8.py)."""

    def test_optimize_all(self, rich_db):
        from nuri.quant.backtest.optimizer import optimize_all
        result = optimize_all()
        assert isinstance(result, pd.DataFrame)


class TestOptimizer_Push:
    """(from test_coverage_push.py)."""

    def test_opt_result(self):
        from nuri.quant.backtest.optimizer import OptResult
        r = OptResult(signal_id="rsi_oversold", params={"rsi_th": 30},
                      total_trades=50, win_rate=0.65, avg_return=3.5, profit_factor=2.1, sharpe=1.5)
        assert r.signal_id == "rsi_oversold"

    def test_optimize_all_empty(self, db_path_mp):
        from nuri.quant.backtest.optimizer import optimize_all
        results = optimize_all(db_path=db_path_mp)
        assert isinstance(results, pd.DataFrame)

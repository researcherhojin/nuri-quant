"""Shared fixtures for tests/collectors/.

Auto-loaded by pytest.
"""
import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_macro, upsert_portfolio, upsert_prices


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """Isolated DB with DB_PATH patched."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture
def db_with_us_tickers(db_path):
    """DB with US portfolio tickers."""
    upsert_portfolio(
        [
            {"account": "test", "ticker": "TSLA", "quantity": 10,
             "avg_price": 300, "currency": "USD", "sector": "EV"},
            {"account": "test", "ticker": "NVDA", "quantity": 5,
             "avg_price": 800, "currency": "USD", "sector": "Semi"},
            {"account": "test", "ticker": "AAPL", "quantity": 20,
             "avg_price": 180, "currency": "USD", "sector": "Tech"},
        ],
        db_path,
    )
    return db_path


@pytest.fixture
def db_with_portfolio(db_path, monkeypatch):
    """DB with portfolio + prices seeded."""
    upsert_portfolio(
        [
            {"account": "test", "ticker": "AAPL", "quantity": 10, "avg_price": 190,
             "currency": "USD", "sector": "Tech"},
            {"account": "test", "ticker": "NVDA", "quantity": 5, "avg_price": 130,
             "currency": "USD", "sector": "Semiconductor"},
            {"account": "test", "ticker": "005930.KS", "quantity": 4, "avg_price": 60000,
             "currency": "KRW", "sector": "Semiconductor"},
        ],
        db_path,
    )

    dates = pd.date_range("2025-01-01", periods=30, freq="B")
    rows = []
    for t in ["AAPL", "NVDA", "SPY", "005930.KS"]:
        base = {"AAPL": 190, "NVDA": 130, "SPY": 550, "005930.KS": 60000}.get(t, 100)
        for i, d in enumerate(dates):
            p = base + i * 0.5
            rows.append({
                "ticker": t, "date": d.strftime("%Y-%m-%d"),
                "open": p, "high": p + 2, "low": p - 1,
                "close": p + 1, "volume": 1_000_000, "adj_close": p + 1,
            })
    upsert_prices(pd.DataFrame(rows), db_path)

    upsert_macro([
        {"indicator": "fear_greed", "date": "2025-01-30", "value": 55.0, "source": "CNN"},
        {"indicator": "vix", "date": "2025-01-30", "value": 18.5, "source": "test"},
    ], db_path)

    return db_path


@pytest.fixture
def rich_db(tmp_path, monkeypatch):
    """Rich DB with portfolio, prices, macro."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    upsert_portfolio(
        [
            {"account": "test", "ticker": "AAPL", "quantity": 10, "avg_price": 190,
             "currency": "USD", "sector": "Tech"},
            {"account": "test", "ticker": "NVDA", "quantity": 5, "avg_price": 130,
             "currency": "USD", "sector": "Semi"},
            {"account": "test", "ticker": "005930.KS", "quantity": 100, "avg_price": 70000,
             "currency": "KRW", "sector": "Tech"},
        ],
        path,
    )

    dates = pd.date_range("2024-06-01", periods=50, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA"]:
        base = {"SPY": 450, "AAPL": 170, "NVDA": 120}[t]
        for i, d in enumerate(dates):
            p = base + i * 0.3
            rows.append({
                "ticker": t, "date": d.strftime("%Y-%m-%d"),
                "open": p, "high": p + 3, "low": p - 2,
                "close": p + 1, "volume": 50000000, "adj_close": p + 1,
            })
    upsert_prices(pd.DataFrame(rows), path)

    macro = []
    for i, d in enumerate(dates):
        ds = d.strftime("%Y-%m-%d")
        macro.append({"indicator": "vix", "date": ds, "value": 15.0, "source": "test"})
        macro.append({"indicator": "fear_greed", "date": ds, "value": 55.0, "source": "test"})
    upsert_macro(macro, path)

    return path


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    """retry backoff sleep 건너뛰기."""
    import time

    monkeypatch.setattr(time, "sleep", lambda _: None)

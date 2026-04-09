"""Shared fixtures for tests/trading/execution/.

Extracted from tests/test_trading_engine_all.py (refactor #157).
"""
import numpy as np
import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_macro, upsert_portfolio, upsert_prices


@pytest.fixture()
def rich_db(tmp_path, monkeypatch):
    """Full DB with portfolio, 300+ days prices (SPY + tickers), macro."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10, "avg_price": 170, "currency": "USD", "sector": "Technology"},
        {"account": "test", "ticker": "NVDA", "quantity": 5, "avg_price": 120, "currency": "USD", "sector": "Semiconductor"},
        {"account": "test", "ticker": "TSLA", "quantity": 8, "avg_price": 250, "currency": "USD", "sector": "SectorA"},
    ], path)

    dates = pd.bdate_range("2024-06-01", periods=300, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA", "TSLA", "VOO"]:
        base = {"SPY": 450, "AAPL": 170, "NVDA": 120, "TSLA": 200, "VOO": 440}[t]
        for i, d in enumerate(dates):
            p = base + i * 0.2 + np.sin(i / 20) * 5
            rows.append({
                "ticker": t, "date": d.strftime("%Y-%m-%d"),
                "open": p, "high": p + 3, "low": p - 2,
                "close": p + 1, "volume": 50_000_000, "adj_close": p + 1,
            })
    upsert_prices(pd.DataFrame(rows), path)

    macro = []
    for i, d in enumerate(dates):
        ds = d.strftime("%Y-%m-%d")
        macro.append({"indicator": "vix", "date": ds, "value": 15 + np.sin(i / 30) * 8, "source": "test"})
        macro.append({"indicator": "fear_greed", "date": ds, "value": 50 + np.sin(i / 25) * 30, "source": "test"})
    upsert_macro(macro, path)
    return path

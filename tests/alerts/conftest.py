"""Shared fixtures for tests/alerts/.

Auto-loaded by pytest.
"""

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_macro, upsert_portfolio, upsert_prices


@pytest.fixture(autouse=True)
def _no_local_account_filter(monkeypatch):
    """손절 스캐너가 로컬 `config/portfolio.yaml` 의 실계좌 집합을 읽지 않게 한다 (#1874).

    집합이 비면 필터가 꺼진다 — CI(파일 없음)와 같은 조건이다. 필터 동작 자체는
    `tests/api/test_stop_loss_consistency.py` 가 명시적으로 검증한다.
    """
    monkeypatch.setattr("nuri.alerts.risk_signals.get_real_accounts", lambda: set())


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """Basic DB fixture with DB_PATH monkeypatched."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture
def rich_db(tmp_path, monkeypatch):
    """DB with portfolio, 500-day prices for SPY/AAPL/NVDA, macro data."""
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
    dates = pd.date_range("2024-06-01", periods=500, freq="B")
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
                    "volume": 50000000,
                    "adj_close": p + 1,
                }
            )
    upsert_prices(pd.DataFrame(rows), path)
    vix = [
        {"indicator": "vix", "date": d.strftime("%Y-%m-%d"), "value": 15 + np.sin(i / 30) * 8, "source": "test"}
        for i, d in enumerate(dates)
    ]
    fg = [
        {"indicator": "fear_greed", "date": d.strftime("%Y-%m-%d"), "value": 50 + np.sin(i / 25) * 30, "source": "test"}
        for i, d in enumerate(dates)
    ]
    upsert_macro(vix + fg, path)
    return path


@pytest.fixture
def db_with_portfolio(tmp_path, monkeypatch):
    """DB with portfolio + prices seeded (from test_coverage_round24)."""
    import nuri.core.db as db_mod

    path = tmp_path / "r24.db"
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
            {
                "account": "test",
                "ticker": "005930.KS",
                "quantity": 4,
                "avg_price": 60000,
                "currency": "KRW",
                "sector": "Semiconductor",
            },
        ],
        path,
    )

    dates = pd.date_range("2025-01-01", periods=30, freq="B")
    rows = []
    for t in ["AAPL", "NVDA", "SPY", "005930.KS"]:
        base = {"AAPL": 190, "NVDA": 130, "SPY": 550, "005930.KS": 60000}.get(t, 100)
        for i, d in enumerate(dates):
            p = base + i * 0.5
            rows.append(
                {
                    "ticker": t,
                    "date": d.strftime("%Y-%m-%d"),
                    "open": p,
                    "high": p + 2,
                    "low": p - 1,
                    "close": p + 1,
                    "volume": 1_000_000,
                    "adj_close": p + 1,
                }
            )
    upsert_prices(pd.DataFrame(rows), path)

    upsert_macro(
        [
            {"indicator": "fear_greed", "date": "2025-01-30", "value": 55.0, "source": "CNN"},
            {"indicator": "vix", "date": "2025-01-30", "value": 18.5, "source": "test"},
        ],
        path,
    )

    return path

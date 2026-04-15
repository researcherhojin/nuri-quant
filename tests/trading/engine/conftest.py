"""Shared fixtures for tests/trading/engine/.

Extracted from tests/test_trading_engine_all.py (refactor #157).
"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture()
def db_path_monkeypatched(tmp_path, monkeypatch):
    """DB with monkeypatched DB_PATH for modules that use the global."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture()
def populated_db(db_path, monkeypatch):
    """Gate/certification test data: portfolio + 300-day SPY + VIX."""
    import nuri.core.db as db_mod

    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?, ?, ?, ?, ?, ?)",
            ("test", "TEST", 100, 50.0, "USD", "Technology"),
        )

    dates = pd.bdate_range("2024-01-01", periods=300)
    close = np.linspace(100, 150, 300) + np.random.normal(0, 1, 300)
    df = pd.DataFrame(
        {
            "ticker": "SPY",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.99,
            "high": close * 1.01,
            "low": close * 0.98,
            "close": close,
            "volume": [50000000] * 300,
            "adj_close": close,
        }
    )
    upsert_prices(df, db_path)

    df2 = df.copy()
    df2["ticker"] = "TEST"
    upsert_prices(df2, db_path)

    upsert_macro(
        [{"indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"), "value": 18.0, "source": "test"}], db_path
    )
    upsert_macro(
        [{"indicator": "fear_greed", "date": dates[-1].strftime("%Y-%m-%d"), "value": 50.0, "source": "test"}], db_path
    )

    return db_path


@pytest.fixture()
def populated_db_cert(tmp_path, monkeypatch):
    """Certification-specific populated DB (from test_certification.py)."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    with get_db(path) as conn:
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?, ?, ?, ?, ?, ?)",
            ("test", "AAPL", 10, 150.0, "USD", "Technology"),
        )
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?, ?, ?, ?, ?, ?)",
            ("test", "MSFT", 5, 300.0, "USD", "Technology"),
        )

    today = datetime.now().strftime("%Y-%m-%d")
    prices = pd.DataFrame(
        [
            {
                "ticker": "SPY",
                "date": today,
                "open": 500,
                "high": 510,
                "low": 495,
                "close": 505,
                "volume": 50000000,
                "adj_close": 505,
            },
            {
                "ticker": "AAPL",
                "date": today,
                "open": 155,
                "high": 158,
                "low": 153,
                "close": 156,
                "volume": 10000000,
                "adj_close": 156,
            },
            {
                "ticker": "MSFT",
                "date": today,
                "open": 310,
                "high": 315,
                "low": 308,
                "close": 312,
                "volume": 5000000,
                "adj_close": 312,
            },
        ]
    )
    upsert_prices(prices, path)

    upsert_macro(
        [
            {"indicator": "vix", "date": today, "value": 18.0, "source": "test"},
            {"indicator": "usd_krw", "date": today, "value": 1380.0, "source": "test"},
        ],
        path,
    )

    return path


@pytest.fixture()
def rich_db(tmp_path, monkeypatch):
    """Full DB with portfolio, 300+ days prices (SPY + tickers), macro (from round16/round10)."""
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
                "avg_price": 170,
                "currency": "USD",
                "sector": "Technology",
            },
            {
                "account": "test",
                "ticker": "NVDA",
                "quantity": 5,
                "avg_price": 120,
                "currency": "USD",
                "sector": "Semiconductor",
            },
            {
                "account": "test",
                "ticker": "TSLA",
                "quantity": 8,
                "avg_price": 250,
                "currency": "USD",
                "sector": "SectorA",
            },
        ],
        path,
    )

    dates = pd.bdate_range("2024-06-01", periods=300, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA", "TSLA", "VOO"]:
        base = {"SPY": 450, "AAPL": 170, "NVDA": 120, "TSLA": 200, "VOO": 440}[t]
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


def _seed_prices_r23(db_path, ticker="AAPL", close=170.0, high=180.0, days=5):
    """Insert sample price rows (round23 helper)."""
    with get_db(db_path) as conn:
        for i in range(days):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ticker, date_str, close - 2, high, close - 5, close, 1000000),
            )


def _seed_macro_r23(db_path, indicator="vix", value=20.0, days=1):
    """Insert sample macro rows (round23 helper)."""
    with get_db(db_path) as conn:
        for i in range(days):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT OR REPLACE INTO macro (indicator, date, value, source) VALUES (?, ?, ?, ?)",
                (indicator, date_str, value, "test"),
            )


def _seed_kr_portfolio(db_path, holdings=None):
    """KR 종목이 포함된 portfolio fixture (#248 asset-class gate 테스트용).

    holdings 기본값: 삼성전자(005930.KS) + KR ETF 5종 (US/Tech/Commodity/Bond/KRIndex).
    이 조합이 실제 사용자 포트폴리오와 동일 — asset_class_rules 전체 경로 검증.
    """
    defaults = [
        ("005930.KS", "Semiconductor", 50.0),
        ("000660.KS", "Semiconductor", 50.0),
        ("448300.KS", "ETF/USIndex", 50.0),
        ("132030.KS", "ETF/Commodity", 50.0),
        ("447660.KS", "ETF/Bond", 50.0),
        ("292160.KS", "ETF/KRIndex", 50.0),
        ("AAPL", "Technology", 150.0),
    ]
    with get_db(db_path) as conn:
        for ticker, sector, price in holdings or defaults:
            conn.execute(
                "INSERT OR REPLACE INTO portfolio (ticker, sector, avg_price, quantity, account) "
                "VALUES (?, ?, ?, ?, ?)",
                (ticker, sector, price, 10, "test_account"),
            )


def _seed_usd_krw_series(db_path, values=None):
    """usd_krw 4일치 시계열 삽입 — _compute_3d_change 작동 검증용."""
    values = values or [1300.0, 1305.0, 1310.0, 1330.0]  # 4개 필요 (LIMIT 4)
    with get_db(db_path) as conn:
        for i, v in enumerate(values):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT OR REPLACE INTO macro (indicator, date, value, source) VALUES (?, ?, ?, ?)",
                ("usd_krw", date_str, v, "test"),
            )

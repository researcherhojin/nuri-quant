"""Shared fixtures for tests/api/.

Auto-loaded by pytest. Helpers live in _helpers.py to be importable.
"""

import asyncio
import json
import time as _time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from tests.api._helpers import _csv_file  # noqa: F401


@pytest.fixture(autouse=True)
def _mock_pykrx_names(monkeypatch):
    """#712: pykrx get_market_ticker_name 은 live KRX 네트워크 의존 → CI flaky.

    yfinance 가 전역 모킹되듯 KR 종목명 해석도 결정적 stub 으로 network-free 화.
    get_ticker_name 은 @lru_cache 라 테스트 간 stale(None) 캐시 오염을 막기 위해
    앞뒤로 cache_clear (네트워크 미가용 시 None 이 캐시되면 후속 테스트도 빈 결과).
    """
    import sys
    import types

    from nuri.core import ticker_names as _tn

    _KR_NAMES = {"005930": "삼성전자", "000660": "SK하이닉스", "005380": "현대차"}
    _fake_stock = types.SimpleNamespace(get_market_ticker_name=lambda code: _KR_NAMES.get(str(code), ""))
    monkeypatch.setitem(sys.modules, "pykrx", types.SimpleNamespace(stock=_fake_stock))
    _tn.get_ticker_name.cache_clear()
    _tn.get_ticker_name_local.cache_clear()  # #1255: 요청 경로가 쓰는 쪽도 같이 비운다
    yield
    _tn.get_ticker_name.cache_clear()
    _tn.get_ticker_name_local.cache_clear()


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    """Isolated test DB with DB_PATH monkeypatched."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with isolated DB + YAML."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    import nuri.core.db as db_mod

    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    import nuri.core.portfolio_sync as sync_mod

    monkeypatch.setattr(sync_mod, "CONFIG_PATH", tmp_path / "portfolio.yaml")

    from nuri.api.main import app

    return TestClient(app)


@pytest.fixture()
def seeded_client(client):
    """Client with one holding pre-added."""
    client.post(
        "/api/portfolio",
        json={
            "account": "sample",
            "ticker": "AAPL",
            "quantity": 10,
            "avg_price": 180.0,
            "currency": "USD",
            "sector": "Tech",
        },
    )
    return client


@pytest.fixture()
def populated_db(db_path):
    """Portfolio + price data."""
    today = datetime.now().strftime("%Y-%m-%d")
    with get_db(db_path) as conn:
        for ticker, qty, price, sector in [
            ("AAPL", 10, 150.0, "Technology"),
            ("MSFT", 5, 300.0, "Software"),
            ("TSLA", 8, 340.0, "SectorA"),
        ]:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test", ticker, qty, price, "USD", sector),
            )

    dates = pd.bdate_range("2024-01-01", periods=250)
    for ticker, base in [("SPY", 450), ("AAPL", 150), ("MSFT", 300), ("TSLA", 340)]:
        close = np.linspace(base, base * 1.1, 250)
        df = pd.DataFrame(
            {
                "ticker": ticker,
                "date": [d.strftime("%Y-%m-%d") for d in dates],
                "open": close * 0.99,
                "high": close * 1.01,
                "low": close * 0.98,
                "close": close,
                "volume": [1000000] * 250,
                "adj_close": close,
            }
        )
        upsert_prices(df, db_path)

    upsert_macro(
        [
            {"indicator": "vix", "date": today, "value": 18.0, "source": "test"},
            {"indicator": "fear_greed", "date": today, "value": 55.0, "source": "test"},
        ],
        db_path,
    )
    return db_path


@pytest.fixture()
def _seed_recommendations(db_path):
    """Insert recommendations for dashboard action tests."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals) VALUES (?,?,?,?,?,?)",
            ("2025-03-31", "AAPL", "BUY", 0.75, "bull_low_vol", "rsi_oversold,macd_golden"),
        )
        conn.execute(
            "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals) VALUES (?,?,?,?,?,?)",
            ("2025-03-31", "MSFT", "SELL", 0.85, "bear_high_vol", "macd_dead,sma_dead"),
        )


@pytest.fixture()
def _seed_positions(db_path):
    """Insert open positions."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, quantity, status) VALUES (?,?,?,?,?,?,?)",
            ("core", "AAPL", "long", "2025-01-05", 145.0, 10, "open"),
        )


@pytest.fixture()
def _seed_prices(db_path):
    """Insert price data for AAPL and MSFT (80 rows each)."""
    dates = pd.bdate_range("2025-01-01", periods=80).strftime("%Y-%m-%d").tolist()
    rows = []
    np.random.seed(42)
    base_aapl = 150.0
    base_msft = 300.0
    for i, d in enumerate(dates):
        aapl_close = base_aapl + np.random.randn() * 2 + i * 0.1
        msft_close = base_msft + np.random.randn() * 3 + i * 0.15
        rows.append(("AAPL", d, aapl_close - 1, aapl_close + 1, aapl_close - 2, aapl_close, 1000000, aapl_close))
        rows.append(("MSFT", d, msft_close - 1, msft_close + 1, msft_close - 2, msft_close, 800000, msft_close))
        rows.append(
            ("VOO", d, msft_close / 2, msft_close / 2 + 1, msft_close / 2 - 1, msft_close / 2, 500000, msft_close / 2)
        )
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume, adj_close) VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )


@pytest.fixture()
def _seed_portfolio(db_path):
    """Insert portfolio holdings for AAPL and MSFT."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?,?,?,?,?,?)",
            ("test", "AAPL", 10, 145.0, "USD", "Technology"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?,?,?,?,?,?)",
            ("test", "MSFT", 5, 290.0, "USD", "Technology"),
        )

"""Shared fixtures for tests/analysis/.

Auto-loaded by pytest. Extracted from tests/test_analysis_all.py during the
per-feature split (see #157).
"""
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """Base isolated DB with DB_PATH patched."""
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture
def populated_db(db_path, monkeypatch):
    """분석에 필요한 데이터 (from test_analysis.py)."""
    upsert_portfolio([
        {"account": "test", "ticker": "TSLA", "quantity": 10,
         "avg_price": 300, "currency": "USD", "sector": "SectorA"},
        {"account": "test", "ticker": "NVDA", "quantity": 5,
         "avg_price": 130, "currency": "USD", "sector": "Semiconductor"},
        {"account": "test", "ticker": "VOO", "quantity": 2,
         "avg_price": 500, "currency": "USD", "sector": "ETF"},
    ], db_path)

    dates = pd.bdate_range("2026-01-02", periods=60).strftime("%Y-%m-%d").tolist()
    for ticker, base_price in [("TSLA", 300), ("NVDA", 150), ("VOO", 520)]:
        df = pd.DataFrame([
            {"ticker": ticker, "date": dates[i],
             "open": base_price + i, "high": base_price + i + 5,
             "low": base_price + i - 5, "close": base_price + i,
             "volume": 1000000, "adj_close": base_price + i}
            for i in range(len(dates))
        ])
        upsert_prices(df, db_path)

    upsert_macro([
        {"indicator": "usd_krw", "date": "2026-03-24", "value": 1450.0, "source": "FRED"},
        {"indicator": "fear_greed", "date": "2026-03-24", "value": 45.0, "source": "CNN"},
        {"indicator": "fed_funds_rate", "date": "2026-03-24", "value": 5.0, "source": "FRED"},
    ], db_path)

    return db_path


@pytest.fixture
def price_data(db_path):
    """가격 + 포트폴리오 테스트 데이터 (from test_uncovered.py)."""
    prices = []
    for i in range(100):
        date = f"2025-{(i // 28 + 1):02d}-{(i % 28 + 1):02d}"
        for ticker, base in [("AAPL", 150), ("MSFT", 300), ("TSLA", 250)]:
            prices.append({
                "ticker": ticker, "date": date,
                "open": base + i * 0.1, "high": base + i * 0.1 + 2,
                "low": base + i * 0.1 - 2, "close": base + i * 0.1,
                "volume": 1000000, "adj_close": base + i * 0.1,
            })
    upsert_prices(pd.DataFrame(prices), db_path)
    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10,
         "avg_price": 150, "currency": "USD", "sector": "Tech"},
        {"account": "test", "ticker": "MSFT", "quantity": 5,
         "avg_price": 300, "currency": "USD", "sector": "Tech"},
        {"account": "test", "ticker": "TSLA", "quantity": 8,
         "avg_price": 250, "currency": "USD", "sector": "SectorA"},
    ], db_path)
    return db_path


@pytest.fixture
def price_db(db_path):
    """포트폴리오 + 250일 가격 데이터 (from test_coverage_push.py)."""
    with get_db(db_path) as conn:
        for t, q, p, s in [("AAPL", 10, 150, "Technology"), ("MSFT", 5, 300, "Software"),
                            ("GOOGL", 3, 2700, "BigTech")]:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)", ("test", t, q, p, "USD", s))

    dates = pd.bdate_range("2023-06-01", periods=250)
    for ticker, base in [("AAPL", 140), ("MSFT", 280), ("GOOGL", 120), ("SPY", 430)]:
        close = np.linspace(base, base * 1.15, 250) + np.random.normal(0, 0.5, 250)
        df = pd.DataFrame({
            "ticker": ticker, "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.99, "high": close * 1.01,
            "low": close * 0.98, "close": close,
            "volume": [1000000] * 250, "adj_close": close,
        })
        upsert_prices(df, db_path)

    today = datetime.now().strftime("%Y-%m-%d")
    upsert_macro([
        {"indicator": "vix", "date": today, "value": 16.0, "source": "test"},
        {"indicator": "fear_greed", "date": today, "value": 55.0, "source": "test"},
        {"indicator": "usd_krw", "date": today, "value": 1380.0, "source": "test"},
    ], db_path)
    return db_path


@pytest.fixture
def rich_db(db_path):
    """Rich DB with portfolio, 500-day prices, macro, fundamentals, estimates (from test_coverage_round20.py)."""
    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10,
         "avg_price": 150.0, "currency": "USD", "sector": "Technology"},
        {"account": "test", "ticker": "NVDA", "quantity": 5,
         "avg_price": 120.0, "currency": "USD", "sector": "Semiconductor"},
        {"account": "test", "ticker": "005930.KS", "quantity": 100,
         "avg_price": 70000.0, "currency": "KRW", "sector": "반도체"},
    ], db_path)

    dates = pd.date_range("2024-01-01", periods=500, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA", "005930.KS", "VOO"]:
        base = {"SPY": 450, "AAPL": 150, "NVDA": 120, "005930.KS": 70000, "VOO": 440}[t]
        for i, d in enumerate(dates):
            p = base + i * 0.3 + np.sin(i / 20) * 5
            rows.append({
                "ticker": t, "date": d.strftime("%Y-%m-%d"),
                "open": p, "high": p + 4, "low": p - 3,
                "close": p + 1, "volume": 50_000_000, "adj_close": p + 1,
            })
    upsert_prices(pd.DataFrame(rows), db_path)

    macro_records = []
    for i, d in enumerate(dates):
        ds = d.strftime("%Y-%m-%d")
        macro_records.append({"indicator": "vix", "date": ds,
                              "value": 15 + np.sin(i / 30) * 8, "source": "test"})
        macro_records.append({"indicator": "fear_greed", "date": ds,
                              "value": 50 + np.sin(i / 25) * 30, "source": "test"})
        macro_records.append({"indicator": "usd_krw", "date": ds,
                              "value": 1350.0, "source": "test"})
    upsert_macro(macro_records, db_path)

    with get_db(db_path) as conn:
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
        conn.execute(
            "INSERT OR REPLACE INTO superinvestors (investor, filing_date, ticker, shares, market_value, portfolio_pct)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            ("Warren Buffett", "2025-01-01", "AAPL", 1000000, 200000000, 25.0),
        )
        conn.execute(
            "INSERT INTO news (ticker, date, title, url, source, sentiment)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            ("AAPL", "2025-01-01", "Apple grows", "https://x.com/1", "test", 0.7),
        )
        conn.execute(
            "INSERT INTO news (ticker, date, title, url, source, sentiment)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            ("AAPL", "2025-01-02", "Apple OK", "https://x.com/2", "test", 0.3),
        )

    return db_path


@pytest.fixture
def market_db(db_path):
    """시장 데이터 (포트폴리오 + 300일 가격) from test_coverage_extra.py / test_coverage_final.py."""
    from nuri.core.timezone import today_kst
    today = today_kst()

    with get_db(db_path) as conn:
        for t, q, p, s in [("AAPL", 10, 150, "Technology"), ("MSFT", 5, 300, "Software")]:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)", ("test", t, q, p, "USD", s))

    dates = pd.date_range(end=today, periods=300)
    for ticker, base in [("SPY", 430), ("AAPL", 140), ("MSFT", 280)]:
        close = np.linspace(base, base * 1.15, 300) + np.random.normal(0, 0.5, 300)
        df = pd.DataFrame({
            "ticker": ticker, "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.99, "high": close * 1.01,
            "low": close * 0.98, "close": close,
            "volume": [1000000] * 300, "adj_close": close,
        })
        upsert_prices(df, db_path)

    upsert_macro([
        {"indicator": "vix", "date": today, "value": 16.0, "source": "test"},
        {"indicator": "fear_greed", "date": today, "value": 60.0, "source": "test"},
        {"indicator": "usd_krw", "date": today, "value": 1380.0, "source": "test"},
    ], db_path)
    return db_path


@pytest.fixture()
def _seed_prices_r22(db_path):
    """Insert price data for AAPL, MSFT, VOO (80+ rows each) from test_coverage_round22.py."""
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
        rows.append(("VOO", d, msft_close / 2, msft_close / 2 + 1, msft_close / 2 - 1, msft_close / 2, 500000, msft_close / 2))
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume, adj_close) VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )


@pytest.fixture()
def _seed_portfolio_r22(db_path):
    """Insert portfolio holdings from test_coverage_round22.py."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?,?,?,?,?,?)",
            ("test", "AAPL", 10, 145.0, "USD", "Technology"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?,?,?,?,?,?)",
            ("test", "MSFT", 5, 290.0, "USD", "Technology"),
        )


@pytest.fixture()
def _seed_news(db_path):
    """Insert news with NULL sentiment (from test_coverage_round22.py)."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO news (ticker, date, title, url, source, sentiment) VALUES (?,?,?,?,?,?)",
            ("AAPL", "2025-01-10", "Apple surges on record earnings beat", "https://example.com/1", "test", None),
        )
        conn.execute(
            "INSERT INTO news (ticker, date, title, url, source, sentiment) VALUES (?,?,?,?,?,?)",
            ("MSFT", "2025-01-10", "Microsoft drops on weak outlook warns investors", "https://example.com/2", "test", None),
        )
        conn.execute(
            "INSERT INTO news (ticker, date, title, url, source, sentiment) VALUES (?,?,?,?,?,?)",
            ("TSLA", "2025-01-11", "Tesla stock flat today no major news", "https://example.com/3", "test", None),
        )


@pytest.fixture()
def _seed_news_with_sentiment(db_path):
    """Insert news WITH sentiment already set (from test_coverage_round22.py)."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO news (ticker, date, title, url, source, sentiment) VALUES (?,?,?,?,?,?)",
            ("AAPL", "2025-01-10", "Apple rally", "https://a.com/1", "test", 0.5),
        )
        conn.execute(
            "INSERT INTO news (ticker, date, title, url, source, sentiment) VALUES (?,?,?,?,?,?)",
            ("MSFT", "2025-01-10", "Microsoft drop", "https://a.com/2", "test", -0.3),
        )
        conn.execute(
            "INSERT INTO news (ticker, date, title, url, source, sentiment) VALUES (?,?,?,?,?,?)",
            ("TSLA", "2025-01-11", "Tesla flat", "https://a.com/3", "test", 0.0),
        )

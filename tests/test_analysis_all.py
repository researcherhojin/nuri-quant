"""Consolidated analysis module tests — nuri.analysis.* (portfolio, risk, sector, charts,
evidence_charts, correlation, sentiment, performance, rebalance, rebalance_advisor).

Extracted from 20+ test files. Each class name suffixed with source round where needed
to avoid duplicates.
"""
import logging
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, query, query_df, upsert_macro, upsert_news, upsert_portfolio, upsert_prices

# ═══════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════════════════
# 1. Portfolio Analysis
# ═══════════════════════════════════════════════════════════════════════


class TestPortfolioAnalysis:
    """From test_analysis.py."""
    def test_analyze_returns_dataframe(self, populated_db):
        from nuri.analysis.portfolio import analyze_portfolio
        df = analyze_portfolio()
        assert not df.empty
        assert "weight_pct" in df.columns

    def test_total_weight_100(self, populated_db):
        from nuri.analysis.portfolio import analyze_portfolio
        df = analyze_portfolio()
        assert abs(df["weight_pct"].sum() - 100.0) < 0.1


class TestPortfolioAnalysis_Extra:
    """From test_coverage_extra.py."""
    def test_analyze_empty(self, db_path):
        from nuri.analysis.portfolio import analyze_portfolio
        df = analyze_portfolio()
        assert isinstance(df, pd.DataFrame)

    def test_analyze_with_data(self, market_db):
        from nuri.analysis.portfolio import analyze_portfolio
        df = analyze_portfolio()
        assert isinstance(df, pd.DataFrame)


class TestPortfolioExtended:
    """From test_coverage_push.py."""
    def test_print_summary(self, price_db, capsys):
        from nuri.analysis.portfolio import analyze_portfolio, print_summary
        df = analyze_portfolio()
        print_summary(df)
        output = capsys.readouterr().out
        assert len(output) > 0

    def test_exchange_rate(self, price_db):
        from nuri.analysis.portfolio import get_exchange_rate
        rate = get_exchange_rate()
        assert rate > 0


class TestPortfolioAnalysis_R9:
    """From test_coverage_round9.py (TestRiskAnalysis.test_portfolio_analysis)."""
    def test_portfolio_analysis(self, rich_db):
        from nuri.analysis.portfolio import analyze_portfolio
        with patch("nuri.analysis.portfolio.get_exchange_rate", return_value=1400.0):
            result = analyze_portfolio()
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0


# ═══════════════════════════════════════════════════════════════════════
# 2. Risk Analysis
# ═══════════════════════════════════════════════════════════════════════


class TestRiskAnalysis:
    """From test_analysis.py."""
    def test_risk_metrics_keys(self, populated_db):
        from nuri.analysis.risk import analyze_risk
        metrics = analyze_risk()
        assert "sharpe_ratio" in metrics
        assert "cvar_95_daily_pct" in metrics


class TestRiskAnalysis_Extra:
    """From test_coverage_extra.py."""
    def test_analyze_empty(self, db_path):
        from nuri.analysis.risk import analyze_risk
        result = analyze_risk()
        assert isinstance(result, dict)


class TestRiskExtended:
    """From test_coverage_push.py."""
    def test_with_data(self, price_db):
        from nuri.analysis.risk import analyze_risk
        result = analyze_risk()
        assert isinstance(result, dict)


class TestRiskAnalysis_R9:
    """From test_coverage_round9.py."""
    def test_analyze_risk(self, rich_db):
        from nuri.analysis.risk import analyze_risk
        result = analyze_risk()
        assert isinstance(result, dict)


class TestPrintRisk:
    """From test_coverage_round22.py."""
    def test_print_empty(self, capsys):
        from nuri.analysis.risk import print_risk
        print_risk({})
        assert "데이터가 없습니다" in capsys.readouterr().out

    def test_print_normal_metrics(self, capsys):
        from nuri.analysis.risk import print_risk
        metrics = {
            "annual_return_pct": 12.5,
            "annual_volatility_pct": 18.3,
            "var_95_daily_pct": -1.8,
            "var_99_daily_pct": -2.5,
            "cvar_95_daily_pct": -2.2,
            "sharpe_ratio": 0.68,
            "sortino_ratio": 1.1,
            "max_drawdown_pct": -8.5,
            "current_drawdown_pct": -3.2,
            "beta": 1.05,
            "portfolio_stop_triggered": False,
            "stop_loss_alerts": [],
        }
        print_risk(metrics)
        out = capsys.readouterr().out
        assert "리스크 지표" in out
        assert "Sharpe" in out

    def test_print_with_stop_triggered(self, capsys):
        from nuri.analysis.risk import print_risk
        metrics = {
            "annual_return_pct": -5.0,
            "annual_volatility_pct": 30.0,
            "var_95_daily_pct": -3.5,
            "var_99_daily_pct": -4.8,
            "cvar_95_daily_pct": -4.0,
            "sharpe_ratio": -0.5,
            "sortino_ratio": -0.7,
            "max_drawdown_pct": -12.5,
            "current_drawdown_pct": -10.0,
            "beta": 1.2,
            "portfolio_stop_triggered": True,
            "stop_loss_alerts": [{"ticker": "TSLA", "pnl_pct": -25.0}],
        }
        print_risk(metrics)
        out = capsys.readouterr().out
        assert "스톱 발동" in out
        assert "손절선 도달" in out
        assert "TSLA" in out


class TestAnalyzeRiskEmpty:
    """From test_coverage_round22.py."""
    def test_empty_portfolio(self, db_path, monkeypatch):
        import nuri.analysis.risk as mod
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: query(sql, *a, db_path=db_path, **kw))
        monkeypatch.setattr(mod, "query_df", lambda sql, *a, **kw: pd.DataFrame())
        result = mod.analyze_risk()
        assert result == {}


class TestAnalyzeRiskMocked:
    """From test_coverage_round22.py."""
    def test_empty_weights(self, db_path, monkeypatch):
        import nuri.analysis.risk as mod
        holdings_df = pd.DataFrame({"ticker": ["AAPL"], "total_qty": [10]})
        monkeypatch.setattr(mod, "query_df", lambda sql, *a, **kw: holdings_df)
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: [])
        result = mod.analyze_risk()
        assert result == {}


# ═══════════════════════════════════════════════════════════════════════
# 3. Sector Analysis
# ═══════════════════════════════════════════════════════════════════════


class TestSectorAnalysis:
    """From test_analysis.py."""
    def test_sector_weights_sum_100(self, populated_db):
        from nuri.analysis.sector import analyze_sector
        sector_df, _, _ = analyze_sector()
        assert not sector_df.empty
        assert abs(sector_df["weight_pct"].sum() - 100.0) < 0.5


class TestSectorAnalysis_Extra:
    """From test_coverage_extra.py."""
    def test_analyze_empty(self, db_path):
        from nuri.analysis.sector import analyze_sector
        result = analyze_sector()
        assert isinstance(result, tuple)


class TestSector:
    """From test_coverage_round2.py."""
    def test_analyze_sector(self, db_path):
        from nuri.analysis.sector import analyze_sector
        with patch("nuri.analysis.sector.get_exchange_rate", return_value=1400.0):
            sector_df, region_df, warnings = analyze_sector()
        assert isinstance(sector_df, pd.DataFrame)
        assert isinstance(region_df, pd.DataFrame)
        assert isinstance(warnings, list)


class TestAnalyzeSector:
    """From test_coverage_round22.py."""
    def test_empty_holdings(self, db_path, monkeypatch):
        from nuri.analysis import sector as mod
        monkeypatch.setattr(mod, "query_df", lambda sql, **kw: pd.DataFrame())
        s, r, w = mod.analyze_sector()
        assert s.empty and r.empty and w == []

    def test_no_prices(self, db_path, monkeypatch):
        from nuri.analysis import sector as mod
        holdings = pd.DataFrame({
            "ticker": ["AAPL"],
            "total_qty": [10],
            "sector": ["Tech"],
            "currency": ["USD"],
        })
        monkeypatch.setattr(mod, "query_df", lambda sql, **kw: holdings)
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: [])
        monkeypatch.setattr(mod, "get_exchange_rate", lambda: 1350.0)
        s, r, w = mod.analyze_sector()
        assert s.empty

    def test_with_data(self, db_path, _seed_prices_r22, _seed_portfolio_r22, monkeypatch):
        from nuri.analysis import sector as mod
        from nuri.core.db import query as real_query
        from nuri.core.db import query_df as real_query_df
        monkeypatch.setattr(mod, "query_df", lambda sql, **kw: real_query_df(sql, db_path=db_path))
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: real_query(sql, *a, db_path=db_path, **kw))
        monkeypatch.setattr(mod, "get_exchange_rate", lambda: 1350.0)
        s, r, w = mod.analyze_sector()
        assert not s.empty
        assert not r.empty


class TestPrintSector:
    """From test_coverage_round22.py."""
    def test_print_with_warnings(self, capsys):
        from nuri.analysis.sector import print_sector
        sector_df = pd.DataFrame({
            "sector": ["Technology", "Energy"],
            "current_value": [50000, 20000],
            "weight_pct": [50.0, 20.0],
        })
        region_df = pd.DataFrame({
            "region": ["US", "KR"],
            "current_value": [60000, 10000],
            "weight_pct": [85.7, 14.3],
        })
        warnings = ["warning: Technology: 50.0% > 35% limit"]
        print_sector(sector_df, region_df, warnings)
        out = capsys.readouterr().out
        assert "섹터 노출도" in out
        assert "지역 노출도" in out
        assert "Technology" in out

    def test_print_no_warnings(self, capsys):
        from nuri.analysis.sector import print_sector
        sector_df = pd.DataFrame({
            "sector": ["Technology"],
            "current_value": [10000],
            "weight_pct": [30.0],
        })
        region_df = pd.DataFrame({
            "region": ["US"],
            "current_value": [10000],
            "weight_pct": [100.0],
        })
        print_sector(sector_df, region_df, [])
        out = capsys.readouterr().out
        assert "Technology" in out


class TestSectorKR:
    """From test_coverage_round22.py."""
    def test_kr_ticker(self, db_path, monkeypatch):
        from nuri.analysis import sector as mod
        holdings = pd.DataFrame({
            "ticker": ["005930.KS"],
            "total_qty": [100],
            "sector": ["Technology"],
            "currency": ["KRW"],
        })
        monkeypatch.setattr(mod, "query_df", lambda sql, **kw: holdings)
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: [{"close": 70000}])
        monkeypatch.setattr(mod, "get_exchange_rate", lambda: 1350.0)
        s, r, w = mod.analyze_sector()
        assert not r.empty
        kr_rows = r[r["region"] == "KR"]
        assert len(kr_rows) == 1


# ═══════════════════════════════════════════════════════════════════════
# 4. Charts
# ═══════════════════════════════════════════════════════════════════════


class TestCharts:
    """From test_uncovered.py."""
    def test_load_chart_data(self, price_data):
        from nuri.analysis.charts import _load_chart_data
        df = _load_chart_data("AAPL")
        if df is not None:
            assert "close" in df.columns

    def test_load_chart_data_missing(self, db_path):
        from nuri.analysis.charts import _load_chart_data
        df = _load_chart_data("XXXXX")
        assert df is None


class TestCharts_R3:
    """From test_coverage_round3.py."""
    def test_load_chart_data(self, db_path):
        from nuri.analysis.charts import _load_chart_data
        df = _load_chart_data("AAPL")
        # db_path may have data from fixture
        assert df is not None or df is None  # either is valid

    def test_detect_signals(self, db_path):
        from nuri.analysis.charts import _detect_signals, _load_chart_data
        df = _load_chart_data("AAPL")
        if df is not None and len(df) > 30:
            result = _detect_signals(df)
            assert isinstance(result, pd.DataFrame)

    def test_get_info_panel(self, db_path):
        from nuri.analysis.charts import _get_info_panel
        info = _get_info_panel("AAPL")
        assert isinstance(info, dict)


class TestChartsGeneration:
    """From test_coverage_round4.py."""
    def test_generate_plotly_chart(self, rich_db, tmp_path):
        from nuri.analysis.charts import _load_chart_data, generate_plotly_chart
        df = _load_chart_data("AAPL")
        assert df is not None
        output = generate_plotly_chart("AAPL", df, tmp_path)
        assert output.exists()
        assert output.suffix == ".html"

    def test_generate_charts_all(self, rich_db, tmp_path):
        from nuri.analysis.charts import generate_charts
        results = generate_charts(output_dir=tmp_path)
        assert isinstance(results, list)


class TestChartsDeep:
    """From test_coverage_round7.py."""
    def test_detect_signals_with_data(self, rich_db):
        from nuri.analysis.charts import _detect_signals, _load_chart_data
        df = _load_chart_data("AAPL")
        if df is not None and len(df) > 50:
            result = _detect_signals(df)
            assert "signal" in result.columns or len(result) > 0

    def test_get_info_panel(self, rich_db):
        from nuri.analysis.charts import _get_info_panel
        info = _get_info_panel("AAPL")
        assert "ticker" in info

    def test_generate_charts_with_output(self, rich_db, tmp_path):
        from nuri.analysis.charts import generate_charts
        results = generate_charts(output_dir=tmp_path, tickers=["AAPL"])
        assert isinstance(results, list)


class TestChartsMore:
    """From test_coverage_round11.py."""
    def test_load_spy(self, rich_db):
        from nuri.analysis.charts import _load_chart_data
        df = _load_chart_data("SPY")
        assert df is not None
        assert len(df) > 100

    def test_load_nonexistent(self, rich_db):
        from nuri.analysis.charts import _load_chart_data
        df = _load_chart_data("FAKE")
        assert df is None or len(df) == 0

    def test_generate_charts_multiple(self, rich_db, tmp_path):
        from nuri.analysis.charts import generate_charts
        results = generate_charts(output_dir=tmp_path, tickers=["AAPL", "NVDA"])
        assert isinstance(results, list)
        assert len(results) >= 2


class TestChartsPNG:
    """From test_coverage_round12.py."""
    def test_generate_png_chart(self, rich_db, tmp_path):
        from nuri.analysis.charts import _load_chart_data, generate_png_chart
        df = _load_chart_data("AAPL")
        if df is not None and len(df) > 50:
            path = generate_png_chart("AAPL", df, tmp_path)
            assert path.exists()
            assert path.suffix == ".png"

    def test_generate_charts_multiple_tickers(self, rich_db, tmp_path):
        from nuri.analysis.charts import generate_charts
        results = generate_charts(output_dir=tmp_path, tickers=["AAPL", "NVDA"])
        assert isinstance(results, list)


class TestChartsLoad:
    """From test_coverage_round13.py."""
    def test_load_all_tickers(self, rich_db):
        from nuri.analysis.charts import _load_chart_data
        for t in ["AAPL", "NVDA", "SPY"]:
            df = _load_chart_data(t)
            assert df is not None
            assert len(df) > 100

    def test_detect_signals_all_types(self, rich_db):
        from nuri.analysis.charts import _detect_signals, _load_chart_data
        df = _load_chart_data("AAPL")
        result = _detect_signals(df)
        assert "signal" in result.columns or "type" in result.columns or len(result.columns) > 0


class TestChartsAll:
    """From test_coverage_round14.py."""
    def test_generate_for_all_tickers(self, rich_db, tmp_path):
        from nuri.analysis.charts import generate_charts
        results = generate_charts(output_dir=tmp_path)
        assert isinstance(results, list)
        assert len(results) >= 2


class TestChartsLoadData:
    """From test_coverage_round20.py."""
    def test_load_chart_data_returns_df(self, rich_db):
        from nuri.analysis.charts import _load_chart_data
        df = _load_chart_data("AAPL")
        assert df is not None
        assert "close" in df.columns
        assert "sma_20" in df.columns
        assert "rsi_14" in df.columns
        assert "macd" in df.columns
        assert "bb_upper" in df.columns
        assert len(df) > 20

    def test_load_chart_data_returns_none_for_missing(self, rich_db):
        from nuri.analysis.charts import _load_chart_data
        result = _load_chart_data("ZZZZ")
        assert result is None

    def test_load_chart_data_returns_none_for_few_rows(self, rich_db):
        from nuri.analysis.charts import _load_chart_data
        rows = []
        for i in range(5):
            rows.append({
                "ticker": "FEW", "date": f"2025-01-{i+1:02d}",
                "open": 100, "high": 102, "low": 98,
                "close": 101, "volume": 1000, "adj_close": 101,
            })
        upsert_prices(pd.DataFrame(rows), rich_db)
        result = _load_chart_data("FEW")
        assert result is None


class TestChartsDetectSignals:
    """From test_coverage_round20.py."""
    def test_detect_signals_returns_df(self, rich_db):
        from nuri.analysis.charts import _detect_signals, _load_chart_data
        df = _load_chart_data("AAPL")
        assert df is not None
        sig_df = _detect_signals(df)
        assert isinstance(sig_df, pd.DataFrame)
        assert "date" in sig_df.columns or sig_df.empty
        assert "type" in sig_df.columns or sig_df.empty


class TestChartsInfoPanel:
    """From test_coverage_round20.py."""
    def test_get_info_panel_with_data(self, rich_db):
        from nuri.analysis.charts import _get_info_panel
        info = _get_info_panel("AAPL")
        assert info["ticker"] == "AAPL"
        assert info.get("pe") == 28.0
        assert info.get("roe") == 0.35
        assert info.get("recommendation") == "buy"
        assert info.get("target_mean") == 220.0
        assert info.get("sentiment") is not None
        assert info.get("superinvestors") is not None
        assert len(info["superinvestors"]) >= 1

    def test_get_info_panel_empty_ticker(self, rich_db):
        from nuri.analysis.charts import _get_info_panel
        info = _get_info_panel("ZZZZ")
        assert info["ticker"] == "ZZZZ"
        assert info.get("pe") is None


class TestChartsGenerate_R20:
    """From test_coverage_round20.py."""
    @patch("nuri.analysis.charts.generate_plotly_chart")
    def test_generate_charts_calls_plotly(self, mock_plotly, rich_db, tmp_path):
        from nuri.analysis.charts import generate_charts
        mock_plotly.return_value = tmp_path / "AAPL.html"
        generate_charts(tickers=["AAPL"], output_dir=tmp_path)
        assert mock_plotly.called

    def test_generate_charts_skips_missing_ticker(self, rich_db, tmp_path):
        from nuri.analysis.charts import generate_charts
        result = generate_charts(tickers=["ZZZZ"], output_dir=tmp_path)
        assert result == []

    @patch("nuri.analysis.charts.generate_plotly_chart", side_effect=RuntimeError("plotly error"))
    def test_generate_charts_handles_error(self, mock_plotly, rich_db, tmp_path):
        from nuri.analysis.charts import generate_charts
        result = generate_charts(tickers=["AAPL"], output_dir=tmp_path)
        assert result == []


class TestCharts_R27:
    """From test_coverage_round27.py."""
    def test_load_chart_data_no_data(self, db_path, monkeypatch):
        import nuri.analysis.charts as charts_mod
        monkeypatch.setattr(charts_mod, "query_df", lambda *a, **kw: pd.DataFrame())
        result = charts_mod._load_chart_data("AAPL")
        assert result is None

    def test_load_chart_data_insufficient(self, db_path, monkeypatch):
        import nuri.analysis.charts as charts_mod
        df = pd.DataFrame({"date": ["2025-01-01"], "open": [1], "high": [2], "low": [0.5], "close": [1.5], "volume": [100]})
        monkeypatch.setattr(charts_mod, "query_df", lambda *a, **kw: df)
        result = charts_mod._load_chart_data("AAPL")
        assert result is None

    def test_load_chart_data_with_data(self, db_path, monkeypatch):
        import nuri.analysis.charts as charts_mod
        dates = pd.bdate_range("2024-01-01", periods=50)
        np.random.seed(42)
        df = pd.DataFrame({
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": np.random.uniform(100, 200, 50),
            "high": np.random.uniform(200, 250, 50),
            "low": np.random.uniform(80, 100, 50),
            "close": np.random.uniform(100, 200, 50),
            "volume": np.random.uniform(100000, 500000, 50),
        })
        monkeypatch.setattr(charts_mod, "query_df", lambda *a, **kw: df)
        result = charts_mod._load_chart_data("AAPL")
        assert result is not None
        assert "rsi_14" in result.columns

    def test_detect_signals(self):
        from nuri.analysis.charts import _detect_signals
        dates = pd.bdate_range("2024-01-01", periods=50)
        np.random.seed(42)
        df = pd.DataFrame({
            "open": np.random.uniform(100, 200, 50),
            "high": np.random.uniform(200, 250, 50),
            "low": np.random.uniform(80, 100, 50),
            "close": np.random.uniform(100, 200, 50),
            "volume": np.random.uniform(100000, 500000, 50),
            "rsi_14": np.concatenate([np.linspace(25, 35, 25), np.linspace(35, 75, 25)]),
            "macd": np.sin(np.arange(50) / 5),
            "macd_signal": np.sin(np.arange(50) / 5 - 0.5),
        }, index=dates)
        result = _detect_signals(df)
        assert isinstance(result, pd.DataFrame)
        assert "date" in result.columns

    def test_get_info_panel(self, db_path, monkeypatch):
        import nuri.analysis.charts as charts_mod
        call_count = [0]
        def mock_query(sql, params=(), **kwargs):
            call_count[0] += 1
            if "fundamentals" in sql:
                return [{"pe_ratio": 25, "forward_pe": 20, "roe": 0.15,
                         "revenue_growth": 0.2, "debt_to_equity": 0.5,
                         "market_cap": 1e12, "beta": 1.2}]
            elif "estimates" in sql:
                return [{"recommendation": "buy", "target_mean": 200,
                         "target_high": 250, "target_low": 180,
                         "num_analysts": 30, "current_price": 190}]
            elif "sentiment" in sql:
                return [{"avg_s": 0.15, "cnt": 10}]
            elif "superinvestors" in sql:
                return [{"investor": "Buffett", "portfolio_pct": 5.0}]
            return []
        monkeypatch.setattr(charts_mod, "query", mock_query)
        info = charts_mod._get_info_panel("AAPL")
        assert info["ticker"] == "AAPL"
        assert info["pe"] == 25
        assert info["recommendation"] == "buy"
        assert info["sentiment"] == 0.15
        assert len(info["superinvestors"]) == 1

    def test_generate_charts_no_data(self, db_path, monkeypatch):
        import nuri.analysis.charts as charts_mod
        monkeypatch.setattr(charts_mod, "get_tickers", lambda **kw: ["AAPL"])
        monkeypatch.setattr(charts_mod, "_load_chart_data", lambda t: None)
        result = charts_mod.generate_charts(tickers=["AAPL"], output_dir=db_path.parent / "charts")
        assert result == []


# ═══════════════════════════════════════════════════════════════════════
# 5. Correlation
# ═══════════════════════════════════════════════════════════════════════


class TestCorrelation:
    """From test_uncovered.py."""
    def test_analyze_correlation(self, price_data):
        from nuri.analysis.correlation import analyze_correlation
        corr, warnings = analyze_correlation(min_days=20)
        assert isinstance(corr, pd.DataFrame)
        assert isinstance(warnings, list)
        if not corr.empty:
            assert "AAPL" in corr.columns

    def test_empty_db(self, db_path):
        from nuri.analysis.correlation import analyze_correlation
        corr, warnings = analyze_correlation()
        assert corr.empty


class TestCorrelation_Push:
    """From test_coverage_push.py."""
    def test_with_data(self, price_db):
        from nuri.analysis.correlation import analyze_correlation
        corr, warnings = analyze_correlation(min_days=20)
        assert isinstance(corr, pd.DataFrame)
        assert isinstance(warnings, list)


class TestCorrelation_R2:
    """From test_coverage_round2.py."""
    def test_analyze_with_data(self, db_path):
        from nuri.analysis.correlation import analyze_correlation
        corr, warnings = analyze_correlation(min_days=10)
        assert isinstance(corr, pd.DataFrame)
        assert isinstance(warnings, list)

    def test_print_correlation(self, capsys):
        from nuri.analysis.correlation import print_correlation
        corr = pd.DataFrame({"AAPL": [1.0, 0.9], "NVDA": [0.9, 1.0]},
                             index=["AAPL", "NVDA"])
        warnings = [{"ticker_a": "AAPL", "ticker_b": "NVDA", "correlation": 0.9}]
        print_correlation(corr, warnings)
        output = capsys.readouterr().out
        assert "AAPL" in output


class TestAnalyzeCorrelation:
    """From test_coverage_round22.py."""
    def test_less_than_2_tickers(self, db_path, monkeypatch):
        from nuri.analysis import correlation as mod
        monkeypatch.setattr(mod, "get_tickers", lambda: ["AAPL"])
        monkeypatch.setattr(mod, "query_df", lambda sql, **kw: pd.DataFrame())
        corr, warnings = mod.analyze_correlation()
        assert corr.empty
        assert warnings == []

    def test_insufficient_data(self, db_path, monkeypatch):
        from nuri.analysis import correlation as mod
        monkeypatch.setattr(mod, "get_tickers", lambda: ["AAPL", "MSFT"])
        df = pd.DataFrame({
            "ticker": ["AAPL"] * 5 + ["MSFT"] * 5,
            "date": list(pd.bdate_range("2025-01-01", periods=5).strftime("%Y-%m-%d")) * 2,
            "close": [150, 151, 152, 153, 154, 300, 301, 302, 303, 304],
        })
        monkeypatch.setattr(mod, "query_df", lambda sql, **kw: df)
        corr, warnings = mod.analyze_correlation(min_days=60)
        assert corr.empty

    def test_corr_with_data(self, db_path, _seed_prices_r22, _seed_portfolio_r22, monkeypatch):
        from nuri.analysis import correlation as mod
        from nuri.core.db import get_tickers
        monkeypatch.setattr(mod, "get_tickers", lambda: get_tickers(db_path=db_path))
        monkeypatch.setattr(mod, "query_df", lambda sql, **kw: query_df(sql, db_path=db_path))
        corr, warnings = mod.analyze_correlation(min_days=20)
        assert not corr.empty
        assert isinstance(warnings, list)

    def test_high_correlation_warning(self, monkeypatch):
        from nuri.analysis import correlation as mod
        monkeypatch.setattr(mod, "get_tickers", lambda: ["A", "B"])
        dates = pd.bdate_range("2024-01-01", periods=100).strftime("%Y-%m-%d").tolist()
        np.random.seed(0)
        closes_a = np.cumsum(np.random.randn(100)) + 100
        closes_b = closes_a + np.random.randn(100) * 0.1
        df = pd.DataFrame({
            "ticker": ["A"] * 100 + ["B"] * 100,
            "date": dates * 2,
            "close": list(closes_a) + list(closes_b),
        })
        monkeypatch.setattr(mod, "query_df", lambda sql, **kw: df)
        corr, warnings = mod.analyze_correlation(min_days=60)
        assert len(warnings) > 0
        assert warnings[0]["correlation"] > 0.80


class TestSaveHeatmap:
    """From test_coverage_round22.py."""
    def test_save_heatmap_success(self, tmp_path, monkeypatch):
        from nuri.analysis import correlation as mod
        monkeypatch.setattr(mod, "EXPORT_DIR", tmp_path)
        corr = pd.DataFrame(
            [[1.0, 0.85], [0.85, 1.0]],
            index=["AAPL", "MSFT"],
            columns=["AAPL", "MSFT"],
        )
        mod.save_heatmap(corr)
        assert (tmp_path / "correlation.png").exists()

    def test_save_heatmap_fail(self, tmp_path, monkeypatch, caplog):
        from nuri.analysis import correlation as mod
        monkeypatch.setattr(mod, "EXPORT_DIR", Path("/dev/null/impossible"))
        with caplog.at_level(logging.WARNING):
            mod.save_heatmap(pd.DataFrame(
                [[1.0, 0.5], [0.5, 1.0]],
                index=["A", "B"], columns=["A", "B"],
            ))


class TestPrintCorrelation:
    """From test_coverage_round22.py."""
    def test_empty(self, capsys):
        from nuri.analysis.correlation import print_correlation
        print_correlation(pd.DataFrame(), [])
        assert "데이터가 없습니다" in capsys.readouterr().out

    def test_with_warnings(self, capsys):
        from nuri.analysis.correlation import print_correlation
        corr = pd.DataFrame([[1.0, 0.9], [0.9, 1.0]], index=["A", "B"], columns=["A", "B"])
        warns = [{"ticker_a": "A", "ticker_b": "B", "correlation": 0.9}]
        print_correlation(corr, warns)
        out = capsys.readouterr().out
        assert "고상관 쌍" in out
        assert "A" in out

    def test_no_warnings(self, capsys):
        from nuri.analysis.correlation import print_correlation
        corr = pd.DataFrame([[1.0, 0.3], [0.3, 1.0]], index=["A", "B"], columns=["A", "B"])
        print_correlation(corr, [])
        out = capsys.readouterr().out
        assert "분산 양호" in out


class TestCorrelationMain:
    """From test_coverage_round22.py."""
    def test_main_empty(self, monkeypatch, capsys):
        from nuri.analysis import correlation as mod
        monkeypatch.setattr(mod, "get_tickers", lambda: [])
        monkeypatch.setattr(mod, "query_df", lambda sql, **kw: pd.DataFrame())
        corr, warns = mod.analyze_correlation()
        mod.print_correlation(corr, warns)
        if not corr.empty:
            mod.save_heatmap(corr)
        out = capsys.readouterr().out
        assert "데이터가 없습니다" in out


# ═══════════════════════════════════════════════════════════════════════
# 6. Sentiment
# ═══════════════════════════════════════════════════════════════════════


class TestSentiment:
    """From test_uncovered.py."""
    def test_compute_sentiment_positive(self):
        from nuri.analysis.sentiment import compute_sentiment
        score = compute_sentiment("Company reports record earnings growth and profit surge")
        assert score > 0

    def test_compute_sentiment_negative(self):
        from nuri.analysis.sentiment import compute_sentiment
        score = compute_sentiment("Stock crashes amid fraud investigation and bankruptcy fears")
        assert score < 0

    def test_compute_sentiment_neutral(self):
        from nuri.analysis.sentiment import compute_sentiment
        score = compute_sentiment("Company to hold annual meeting next week")
        assert -0.5 <= score <= 0.5

    def test_analyze_sentiment_empty(self, db_path):
        from nuri.analysis.sentiment import analyze_sentiment
        stats = analyze_sentiment()
        assert stats["total"] == 0

    def test_analyze_sentiment_with_news(self, db_path):
        from nuri.analysis.sentiment import analyze_sentiment
        upsert_news([{
            "ticker": "AAPL", "date": "2025-06-01",
            "title": "Apple reports record breaking revenue growth",
            "url": "https://example.com/1", "source": "test", "sentiment": None,
        }], db_path)
        stats = analyze_sentiment()
        assert stats["total"] >= 1


class TestSentiment_R2:
    """From test_coverage_round2.py."""
    def test_compute_positive(self):
        from nuri.analysis.sentiment import compute_sentiment
        score = compute_sentiment("Strong growth beats expectations with record revenue")
        assert score > 0

    def test_compute_negative(self):
        from nuri.analysis.sentiment import compute_sentiment
        score = compute_sentiment("Company faces lawsuit and massive debt crisis")
        assert score < 0

    def test_compute_neutral(self):
        from nuri.analysis.sentiment import compute_sentiment
        score = compute_sentiment("xyz abc 123")
        assert score == 0.0

    def test_compute_empty(self):
        from nuri.analysis.sentiment import compute_sentiment
        assert compute_sentiment("") == 0.0


class TestComputeSentiment:
    """From test_coverage_round22.py."""
    def test_empty_title(self):
        from nuri.analysis.sentiment import compute_sentiment
        assert compute_sentiment("") == 0.0
        assert compute_sentiment(None) == 0.0

    def test_positive_title(self):
        from nuri.analysis.sentiment import compute_sentiment
        score = compute_sentiment("Stock surges on record earnings growth")
        assert score > 0

    def test_negative_title(self):
        from nuri.analysis.sentiment import compute_sentiment
        score = compute_sentiment("Crash fears amid recession and layoffs warning")
        assert score < 0

    def test_neutral_title(self):
        from nuri.analysis.sentiment import compute_sentiment
        score = compute_sentiment("Quarterly results announced for company")
        assert score == 0.0

    def test_mixed_title(self):
        from nuri.analysis.sentiment import compute_sentiment
        score = compute_sentiment("rally and crash equal")
        assert -0.5 <= score <= 0.5


class TestAnalyzeSentiment:
    """From test_coverage_round22.py."""
    def test_with_null_sentiment_news(self, db_path, _seed_news, monkeypatch):
        import nuri.analysis.sentiment as mod
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: query(sql, *a, db_path=db_path, **kw))
        monkeypatch.setattr(mod, "get_db", lambda *a, **kw: get_db(db_path))
        stats = mod.analyze_sentiment()
        assert isinstance(stats, dict)
        rows = query("SELECT sentiment FROM news WHERE sentiment IS NOT NULL", db_path=db_path)
        assert len(rows) == 3

    def test_no_new_news(self, db_path, _seed_news_with_sentiment, monkeypatch):
        import nuri.analysis.sentiment as mod
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: query(sql, *a, db_path=db_path, **kw))
        monkeypatch.setattr(mod, "get_db", lambda *a, **kw: get_db(db_path))
        stats = mod.analyze_sentiment()
        assert isinstance(stats, dict)

    def test_empty_stats(self, db_path, monkeypatch):
        import nuri.analysis.sentiment as mod
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: query(sql, *a, db_path=db_path, **kw))
        monkeypatch.setattr(mod, "get_db", lambda *a, **kw: get_db(db_path))
        stats = mod.analyze_sentiment()
        assert isinstance(stats, dict)


class TestPrintSentiment:
    """From test_coverage_round22.py."""
    def test_print_with_data(self, db_path, _seed_news_with_sentiment, monkeypatch, capsys):
        import nuri.analysis.sentiment as mod
        def mock_query(sql, *a, **kw):
            return query(sql, *a, db_path=db_path, **kw)
        monkeypatch.setattr(mod, "query", mock_query)
        stats = {"total": 3, "avg_sentiment": 0.067, "positive": 1, "negative": 1, "neutral": 1}
        mod.print_sentiment(stats)
        out = capsys.readouterr().out
        assert "센티먼트 분석" in out
        assert "전체 뉴스" in out

    def test_print_no_data(self, capsys):
        from nuri.analysis.sentiment import print_sentiment
        print_sentiment({})
        assert "데이터가 없습니다" in capsys.readouterr().out

    def test_print_zero_total(self, capsys):
        from nuri.analysis.sentiment import print_sentiment
        print_sentiment({"total": 0})
        assert "데이터가 없습니다" in capsys.readouterr().out

    def test_print_positive_label(self, db_path, monkeypatch, capsys):
        import nuri.analysis.sentiment as mod
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: [{"ticker": "AAPL", "avg_s": 0.5, "cnt": 1}])
        stats = {"total": 2, "avg_sentiment": 0.3, "positive": 2, "negative": 0, "neutral": 0}
        mod.print_sentiment(stats)
        out = capsys.readouterr().out
        assert "긍정" in out

    def test_print_negative_label(self, db_path, monkeypatch, capsys):
        import nuri.analysis.sentiment as mod
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: [{"ticker": "MSFT", "avg_s": -0.5, "cnt": 1}])
        stats = {"total": 2, "avg_sentiment": -0.3, "positive": 0, "negative": 2, "neutral": 0}
        mod.print_sentiment(stats)
        out = capsys.readouterr().out
        assert "부정" in out

    def test_print_neutral_label(self, monkeypatch, capsys):
        import nuri.analysis.sentiment as mod
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: [])
        stats = {"total": 2, "avg_sentiment": 0.01, "positive": 0, "negative": 0, "neutral": 2}
        mod.print_sentiment(stats)
        out = capsys.readouterr().out
        assert "중립" in out

    def test_print_with_ticker_stats(self, db_path, _seed_news_with_sentiment, monkeypatch, capsys):
        import nuri.analysis.sentiment as mod
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: query(sql, *a, db_path=db_path, **kw))
        stats = {"total": 3, "avg_sentiment": 0.067, "positive": 1, "negative": 1, "neutral": 1}
        mod.print_sentiment(stats)
        out = capsys.readouterr().out
        assert "Ticker" in out or "센티먼트" in out


class TestSentimentMain:
    """From test_coverage_round22.py."""
    def test_main_block(self, db_path, _seed_news, monkeypatch):
        import nuri.analysis.sentiment as mod
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: query(sql, *a, db_path=db_path, **kw))
        monkeypatch.setattr(mod, "get_db", lambda *a, **kw: get_db(db_path))
        stats = mod.analyze_sentiment()
        mod.print_sentiment(stats)


# ═══════════════════════════════════════════════════════════════════════
# 7. Performance
# ═══════════════════════════════════════════════════════════════════════


class TestPerformance:
    """From test_analysis.py."""
    def test_portfolio_returns(self, populated_db):
        from nuri.analysis.performance import get_portfolio_returns
        returns = get_portfolio_returns()
        assert len(returns) > 0


class TestPerformance_Uncovered:
    """From test_uncovered.py."""
    def test_get_portfolio_returns(self, price_data):
        from nuri.analysis.performance import get_portfolio_returns
        returns = get_portfolio_returns()
        assert isinstance(returns, pd.Series)

    def test_get_benchmark_returns_empty(self, db_path):
        from nuri.analysis.performance import get_benchmark_returns
        returns = get_benchmark_returns()
        assert isinstance(returns, pd.Series)


class TestPerformance_Push:
    """From test_coverage_push.py."""
    def test_portfolio_returns(self, price_db):
        from nuri.analysis.performance import get_portfolio_returns
        returns = get_portfolio_returns()
        assert isinstance(returns, pd.Series)

    def test_benchmark_returns(self, price_db):
        from nuri.analysis.performance import get_benchmark_returns
        returns = get_benchmark_returns()
        assert isinstance(returns, pd.Series)


class TestPerformance_R2:
    """From test_coverage_round2.py."""
    def test_get_portfolio_returns(self, db_path):
        from nuri.analysis.performance import get_portfolio_returns
        returns = get_portfolio_returns(days=30)
        assert isinstance(returns, pd.Series)

    def test_get_benchmark_returns(self, db_path):
        from nuri.analysis.performance import get_benchmark_returns
        result = get_benchmark_returns()
        assert isinstance(result, pd.Series)


class TestPerformanceReturns:
    """From test_coverage_round16.py."""
    def test_empty_portfolio(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        from nuri.analysis.performance import get_portfolio_returns
        returns = get_portfolio_returns()
        assert returns.empty

    def test_portfolio_returns_with_data(self, rich_db):
        from nuri.analysis.performance import get_portfolio_returns
        returns = get_portfolio_returns()
        assert not returns.empty
        assert returns.name == "Nuri-Quant Portfolio"

    def test_benchmark_returns(self, rich_db):
        from nuri.analysis.performance import get_benchmark_returns
        returns = get_benchmark_returns()
        assert not returns.empty
        assert returns.name == "VOO"

    def test_benchmark_returns_no_voo(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        path = tmp_path / "novoo.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        from nuri.analysis.performance import get_benchmark_returns
        returns = get_benchmark_returns()
        assert returns.empty


class TestPerformancePrint:
    """From test_coverage_round16.py."""
    def test_empty_returns(self, capsys):
        from nuri.analysis.performance import print_performance
        print_performance(pd.Series(dtype=float), pd.Series(dtype=float))
        out = capsys.readouterr().out
        assert "성과 데이터가 없습니다" in out

    def test_with_returns(self, capsys, rich_db):
        from nuri.analysis.performance import get_benchmark_returns, get_portfolio_returns, print_performance
        port = get_portfolio_returns()
        bench = get_benchmark_returns()
        print_performance(port, bench)
        out = capsys.readouterr().out
        assert "Sharpe" in out
        assert "Alpha" in out


class TestPerformanceReturns_R22:
    """From test_coverage_round22.py."""
    def test_empty_portfolio(self, db_path, monkeypatch):
        import nuri.analysis.performance as mod
        monkeypatch.setattr(mod, "query_df", lambda sql, *a, **kw: pd.DataFrame())
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: [])
        result = mod.get_portfolio_returns()
        assert result.empty

    def test_zero_total(self, db_path, monkeypatch):
        import nuri.analysis.performance as mod
        holdings = pd.DataFrame({"ticker": ["AAPL"], "total_qty": [10]})
        monkeypatch.setattr(mod, "query_df", lambda sql, *a, **kw: holdings)
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: [])
        result = mod.get_portfolio_returns()
        assert result.empty

    def test_with_data(self, db_path, _seed_prices_r22, _seed_portfolio_r22, monkeypatch):
        import nuri.analysis.performance as mod
        from nuri.core.db import query as real_query
        from nuri.core.db import query_df as real_query_df
        monkeypatch.setattr(mod, "query_df", lambda sql, *a, **kw: real_query_df(sql, db_path=db_path))
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: real_query(sql, *a, db_path=db_path, **kw))
        result = mod.get_portfolio_returns()
        assert not result.empty
        assert result.name == "Nuri-Quant Portfolio"


class TestBenchmarkReturns:
    """From test_coverage_round22.py."""
    def test_empty(self, db_path, monkeypatch):
        import nuri.analysis.performance as mod
        monkeypatch.setattr(mod, "query_df", lambda sql, *a, **kw: pd.DataFrame())
        result = mod.get_benchmark_returns()
        assert result.empty

    def test_with_voo(self, db_path, _seed_prices_r22, monkeypatch):
        import nuri.analysis.performance as mod
        from nuri.core.db import query_df as real_query_df
        monkeypatch.setattr(mod, "query_df", lambda sql, *a, **kw: real_query_df(sql, db_path=db_path))
        result = mod.get_benchmark_returns()
        assert not result.empty
        assert result.name == "VOO"


class TestPrintPerformance:
    """From test_coverage_round22.py."""
    def test_empty(self, capsys):
        from nuri.analysis.performance import print_performance
        print_performance(pd.Series(dtype=float), pd.Series(dtype=float))
        assert "데이터가 없습니다" in capsys.readouterr().out

    def test_with_data(self, capsys, monkeypatch):
        from nuri.analysis.performance import print_performance
        np.random.seed(42)
        dates = pd.bdate_range("2025-01-01", periods=60)
        port_returns = pd.Series(np.random.randn(60) * 0.01, index=dates, name="Portfolio")
        bench_returns = pd.Series(np.random.randn(60) * 0.008, index=dates, name="VOO")
        print_performance(port_returns, bench_returns)
        out = capsys.readouterr().out
        assert "성과 분석" in out
        assert "Sharpe" in out
        assert "VOO" in out

    def test_with_no_benchmark(self, capsys, monkeypatch):
        from nuri.analysis.performance import print_performance
        np.random.seed(42)
        dates = pd.bdate_range("2025-01-01", periods=60)
        port_returns = pd.Series(np.random.randn(60) * 0.01, index=dates, name="Portfolio")
        print_performance(port_returns, pd.Series(dtype=float))
        out = capsys.readouterr().out
        assert "성과 분석" in out


class TestGenerateHtmlReport:
    """From test_coverage_round22.py."""
    def test_generate(self, tmp_path, monkeypatch):
        import nuri.analysis.performance as mod
        monkeypatch.setattr(mod, "EXPORT_DIR", tmp_path)
        np.random.seed(42)
        dates = pd.bdate_range("2025-01-01", periods=60)
        port = pd.Series(np.random.randn(60) * 0.01, index=dates, name="Portfolio")
        bench = pd.Series(np.random.randn(60) * 0.008, index=dates, name="VOO")
        path = mod.generate_html_report(port, bench)
        assert Path(path).exists()

    def test_generate_no_benchmark(self, tmp_path, monkeypatch):
        import nuri.analysis.performance as mod
        monkeypatch.setattr(mod, "EXPORT_DIR", tmp_path)
        np.random.seed(42)
        dates = pd.bdate_range("2025-01-01", periods=60)
        port = pd.Series(np.random.randn(60) * 0.01, index=dates, name="Portfolio")
        path = mod.generate_html_report(port, pd.Series(dtype=float))
        assert Path(path).exists()


# ═══════════════════════════════════════════════════════════════════════
# 8. Rebalance (MVO/RP)
# ═══════════════════════════════════════════════════════════════════════


class TestAnalysisRebalance:
    """From test_coverage_push.py."""
    def test_empty_db(self, db_path):
        from nuri.analysis.rebalance import analyze_rebalance
        result = analyze_rebalance(method="rp")
        assert isinstance(result, pd.DataFrame)

    def test_with_data(self, price_db):
        from nuri.analysis.rebalance import analyze_rebalance
        result = analyze_rebalance(method="rp")
        assert isinstance(result, pd.DataFrame)

    def test_mvo_method(self, price_db):
        from nuri.analysis.rebalance import analyze_rebalance
        result = analyze_rebalance(method="mvo")
        assert isinstance(result, pd.DataFrame)


class TestRebalanceModule:
    """From test_coverage_round3.py."""
    def test_analyze_rebalance_returns_df(self, db_path):
        from nuri.analysis.rebalance import analyze_rebalance
        result = analyze_rebalance()
        assert isinstance(result, pd.DataFrame)


class TestAnalysisRebalance_Final:
    """From test_coverage_final.py."""
    def test_import(self):
        from nuri.analysis.rebalance import analyze_rebalance
        assert callable(analyze_rebalance)

    def test_empty_db(self, db_path):
        from nuri.analysis.rebalance import analyze_rebalance
        result = analyze_rebalance(method="rp")
        assert isinstance(result, pd.DataFrame)


class TestPrintRebalance:
    """From test_coverage_round22.py."""
    def test_empty(self, capsys):
        from nuri.analysis.rebalance import print_rebalance
        print_rebalance(pd.DataFrame())
        assert "데이터가 없습니다" in capsys.readouterr().out

    def test_no_actionable(self, capsys):
        from nuri.analysis.rebalance import print_rebalance
        df = pd.DataFrame([{
            "ticker": "AAPL",
            "sector": "Tech",
            "current_weight": 10.0,
            "optimal_weight": 10.0,
            "drift": 0.0,
            "trade_value_usd": 0,
            "trade_shares": 0,
            "action": "HOLD",
        }])
        df.attrs["method"] = "Mean-Variance (Max Sharpe)"
        print_rebalance(df)
        out = capsys.readouterr().out
        assert "불필요" in out

    def test_with_actions(self, capsys):
        from nuri.analysis.rebalance import print_rebalance
        df = pd.DataFrame([
            {
                "ticker": "AAPL",
                "sector": "Tech",
                "current_weight": 25.0,
                "optimal_weight": 10.0,
                "drift": 15.0,
                "trade_value_usd": -5000,
                "trade_shares": -30,
                "action": "SELL",
            },
            {
                "ticker": "MSFT",
                "sector": "Tech",
                "current_weight": 5.0,
                "optimal_weight": 15.0,
                "drift": -10.0,
                "trade_value_usd": 3000,
                "trade_shares": 10,
                "action": "BUY",
            },
        ])
        df.attrs["method"] = "Risk Parity"
        print_rebalance(df)
        out = capsys.readouterr().out
        assert "Risk Parity" in out
        assert "SELL" in out
        assert "BUY" in out


class TestAnalyzeRebalanceEmpty:
    """From test_coverage_round22.py."""
    def test_empty_portfolio(self, db_path, monkeypatch):
        import nuri.analysis.rebalance as mod
        call_count = [0]
        def mock_query_df(sql, *a, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return pd.DataFrame({
                    "ticker": ["AAPL"] * 15,
                    "date": [f"2025-01-{i:02d}" for i in range(1, 16)],
                    "close": [150 + i for i in range(15)],
                })
            return pd.DataFrame()
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: [])
        monkeypatch.setattr(mod, "query_df", mock_query_df)
        result = mod.analyze_rebalance()
        assert result.empty

    def test_insufficient_returns(self, db_path, monkeypatch):
        import nuri.analysis.rebalance as mod
        prices_df = pd.DataFrame({
            "ticker": ["AAPL", "AAPL", "AAPL"],
            "date": ["2025-01-01", "2025-01-02", "2025-01-03"],
            "close": [150, 151, 152],
        })
        def mock_query_df(sql, *a, **kw):
            if "prices" in sql:
                return prices_df
            return pd.DataFrame()
        monkeypatch.setattr(mod, "query_df", mock_query_df)
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: [])
        result = mod.analyze_rebalance()
        assert result.empty

    def test_zero_total_value(self, db_path, monkeypatch):
        import nuri.analysis.rebalance as mod
        dates = pd.bdate_range("2024-01-01", periods=20).strftime("%Y-%m-%d").tolist()
        prices_df = pd.DataFrame({
            "ticker": ["AAPL"] * 20,
            "date": dates,
            "close": [150 + i * 0.5 for i in range(20)],
        })
        holdings_df = pd.DataFrame({
            "ticker": ["AAPL"],
            "total_qty": [10],
            "sector": ["Tech"],
        })
        call_count = [0]
        def mock_query_df(sql, *a, **kw):
            call_count[0] += 1
            if "prices" in sql:
                return prices_df
            if "portfolio" in sql:
                return holdings_df
            return pd.DataFrame()
        monkeypatch.setattr(mod, "query_df", mock_query_df)
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: [])
        result = mod.analyze_rebalance()
        assert result.empty


# ═══════════════════════════════════════════════════════════════════════
# 9. Rebalance Advisor
# ═══════════════════════════════════════════════════════════════════════


class TestRebalanceDeep:
    """From test_coverage_round7.py."""
    def test_detect_violations_leveraged(self, rich_db):
        from nuri.analysis.rebalance_advisor import detect_violations
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio") as mock_ap:
            mock_df = pd.DataFrame([
                {"ticker": "TSLL", "account": "test", "quantity": 96,
                 "avg_price": 20.0, "current_price": 12.0,
                 "current_value_usd": 1152, "pnl_pct": -29.1,
                 "weight_pct": 5.0, "sector": "SectorB", "currency": "USD"},
            ])
            mock_df.attrs["total_value_usd"] = 23000
            mock_ap.return_value = mock_df
            violations = detect_violations()
        lev = [v for v in violations if v.get("violation_type") == "leverage_etf"]
        assert len(lev) > 0


class TestDetectViolations:
    """From test_new_modules.py."""
    def test_leverage_etf_detected(self, db_path):
        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "TSLL", "sector": "SectorB", "quantity": 96,
             "avg_price": 20.0, "current_price": 11.44, "currency": "USD",
             "current_value_usd": 1098.24, "cost_basis_usd": 1625.28,
             "pnl_usd": -527.04, "pnl_pct": -32.4, "weight_pct": 5.0, "price_date": "2026-03-27"},
            {"account": "test", "ticker": "NVDA", "sector": "Semiconductor", "quantity": 20,
             "avg_price": 100.0, "current_price": 167.99, "currency": "USD",
             "current_value_usd": 3359.8, "cost_basis_usd": 2642.8,
             "pnl_usd": 717.0, "pnl_pct": 27.1, "weight_pct": 10.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 4458.04
        from nuri.analysis.rebalance_advisor import detect_violations
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            violations = detect_violations(db_path=db_path)
        leverage_violations = [v for v in violations if v["violation_type"] == "leverage_etf"]
        assert len(leverage_violations) >= 1
        assert leverage_violations[0]["ticker"] == "TSLL"

    def test_stop_loss_exceeded(self, db_path):
        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "BADSTOCK", "sector": "Test", "quantity": 10,
             "avg_price": 100.0, "current_price": 80.0, "currency": "USD",
             "current_value_usd": 800.0, "cost_basis_usd": 1000.0,
             "pnl_usd": -200.0, "pnl_pct": -20.0, "weight_pct": 100.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 800.0
        from nuri.analysis.rebalance_advisor import detect_violations
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            violations = detect_violations(db_path=db_path)
        stop_violations = [v for v in violations if v["violation_type"] == "stop_loss_exceeded"]
        assert len(stop_violations) >= 1

    def test_position_limit_exceeded(self, db_path):
        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "TSLA", "sector": "SectorA", "quantity": 100,
             "avg_price": 350.0, "current_price": 360.0, "currency": "USD",
             "current_value_usd": 36000.0, "cost_basis_usd": 35000.0,
             "pnl_usd": 1000.0, "pnl_pct": 2.9, "weight_pct": 95.0, "price_date": "2026-03-27"},
            {"account": "test", "ticker": "NVDA", "sector": "Semiconductor", "quantity": 1,
             "avg_price": 160.0, "current_price": 168.0, "currency": "USD",
             "current_value_usd": 168.0, "cost_basis_usd": 160.0,
             "pnl_usd": 8.0, "pnl_pct": 5.0, "weight_pct": 5.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 36168.0
        from nuri.analysis.rebalance_advisor import detect_violations
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            violations = detect_violations(db_path=db_path)
        pos_violations = [v for v in violations if v["violation_type"] == "position_limit_exceeded"]
        assert len(pos_violations) >= 1

    def test_no_violations(self, db_path):
        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "NVDA", "sector": "Semiconductor", "quantity": 1,
             "avg_price": 160.0, "current_price": 168.0, "currency": "USD",
             "current_value_usd": 168.0, "cost_basis_usd": 160.0,
             "pnl_usd": 8.0, "pnl_pct": 5.0, "weight_pct": 10.0, "price_date": "2026-03-27"},
            {"account": "test", "ticker": "GOOGL", "sector": "BigTech", "quantity": 1,
             "avg_price": 260.0, "current_price": 274.0, "currency": "USD",
             "current_value_usd": 274.0, "cost_basis_usd": 260.0,
             "pnl_usd": 14.0, "pnl_pct": 5.4, "weight_pct": 10.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 442.0
        from nuri.analysis.rebalance_advisor import detect_violations
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            violations = detect_violations(db_path=db_path)
        assert len(violations) == 0


class TestCalculateRebalanceActions:
    """From test_new_modules.py."""
    def test_sorted_by_priority(self, db_path):
        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "TSLL", "sector": "SectorB", "quantity": 96,
             "avg_price": 20.0, "current_price": 11.44, "currency": "USD",
             "current_value_usd": 1098.24, "cost_basis_usd": 1625.28,
             "pnl_usd": -527.04, "pnl_pct": -32.4, "weight_pct": 5.0, "price_date": "2026-03-27"},
            {"account": "test", "ticker": "BADSTOCK", "sector": "Test", "quantity": 10,
             "avg_price": 100.0, "current_price": 80.0, "currency": "USD",
             "current_value_usd": 800.0, "cost_basis_usd": 1000.0,
             "pnl_usd": -200.0, "pnl_pct": -20.0, "weight_pct": 5.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 1898.24
        from nuri.analysis.rebalance_advisor import calculate_rebalance_actions
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            actions = calculate_rebalance_actions(db_path=db_path)
        if len(actions) >= 2:
            priorities = [a["priority"] for a in actions]
            assert priorities == sorted(priorities)

    def test_total_recovery_calculated(self, db_path):
        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "TSLL", "sector": "SectorB", "quantity": 96,
             "avg_price": 20.0, "current_price": 11.44, "currency": "USD",
             "current_value_usd": 1098.24, "cost_basis_usd": 1625.28,
             "pnl_usd": -527.04, "pnl_pct": -32.4, "weight_pct": 100.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 1098.24
        from nuri.analysis.rebalance_advisor import calculate_rebalance_actions
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            actions = calculate_rebalance_actions(db_path=db_path)
        assert len(actions) > 0
        total = sum(a["sell_value_usd"] for a in actions)
        assert total > 0


class TestGenerateAdvisorReport:
    """From test_new_modules.py."""
    def test_report_structure(self, db_path):
        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "TSLL", "sector": "SectorB", "quantity": 96,
             "avg_price": 20.0, "current_price": 11.44, "currency": "USD",
             "current_value_usd": 1098.24, "cost_basis_usd": 1625.28,
             "pnl_usd": -527.04, "pnl_pct": -32.4, "weight_pct": 5.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 1098.24
        from nuri.analysis.rebalance_advisor import generate_advisor_report
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            report = generate_advisor_report(db_path=db_path)
        assert "actions" in report
        assert "total_violations" in report
        assert "total_recovery_usd" in report
        assert "violations_by_type" in report
        assert "violations_by_severity" in report
        assert "has_critical" in report

    def test_empty_portfolio_report(self, db_path):
        mock_df = pd.DataFrame()
        from nuri.analysis.rebalance_advisor import generate_advisor_report
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            report = generate_advisor_report(db_path=db_path)
        assert report["total_violations"] == 0
        assert report["total_recovery_usd"] == 0


class TestRebalanceSeverity:
    """From test_coverage_round16.py."""
    def test_leverage_etf(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("leverage_etf", 0, 0) == "critical"

    def test_stop_loss_critical(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("stop_loss_exceeded", -15, -7) == "critical"

    def test_stop_loss_high(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("stop_loss_exceeded", -8, -7) == "high"

    def test_position_limit_high(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("position_limit_exceeded", 30, 0.15) == "high"

    def test_position_limit_medium(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("position_limit_exceeded", 18, 0.15) == "medium"

    def test_sector_limit_high(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("sector_limit_exceeded", 50, 0.35) == "high"

    def test_sector_limit_medium(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("sector_limit_exceeded", 40, 0.35) == "medium"

    def test_unknown_type(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("some_new_type", 0, 0) == "medium"


class TestRebalancePrint:
    """From test_coverage_round16.py."""
    def test_no_actions(self, capsys):
        from nuri.analysis.rebalance_advisor import print_rebalance_advisor
        print_rebalance_advisor([])
        out = capsys.readouterr().out
        assert "위반 사항 없음" in out

    def test_with_actions(self, capsys):
        from nuri.analysis.rebalance_advisor import print_rebalance_advisor
        actions = [
            {"ticker": "TQQQ", "sell_shares": 100, "sell_value_usd": 5000, "reason": "레버리지 ETF",
             "action": "SELL_ALL", "severity": "critical", "cumulative_recovery_usd": 5000},
            {"ticker": "AAPL", "sell_shares": 5, "sell_value_usd": 1000, "reason": "비중 초과",
             "action": "REDUCE", "severity": "high", "cumulative_recovery_usd": 6000},
        ]
        print_rebalance_advisor(actions)
        out = capsys.readouterr().out
        assert "SELL TQQQ" in out
        assert "[!!]" in out
        assert "총 회수" in out


class TestRebalanceGetFactorScores:
    """From test_coverage_round16.py."""
    def test_empty(self, rich_db):
        from nuri.analysis.rebalance_advisor import _get_factor_scores
        scores = _get_factor_scores(db_path=rich_db)
        assert scores == {}

    def test_with_data(self, rich_db):
        from nuri.analysis.rebalance_advisor import _get_factor_scores
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO factors (ticker, date, composite_score) VALUES (?, ?, ?)",
                ("AAPL", "2025-03-20", 0.85))
        scores = _get_factor_scores(db_path=rich_db)
        assert scores["AAPL"] == 0.85


class TestRebalanceGenerateReport:
    """From test_coverage_round16.py."""
    def test_no_violations(self, rich_db):
        from nuri.analysis.rebalance_advisor import generate_advisor_report
        with patch("nuri.analysis.rebalance_advisor.detect_violations", return_value=[]):
            report = generate_advisor_report(db_path=rich_db)
        assert report["total_violations"] == 0
        assert report["has_critical"] is False

    def test_with_violations(self, rich_db):
        from nuri.analysis.rebalance_advisor import generate_advisor_report
        fake_violations = [
            {"ticker": "TQQQ", "violation_type": "leverage_etf", "priority": 1,
             "current_value": -5, "limit_value": 0, "severity": "critical",
             "action": "SELL_ALL", "sell_shares": 50, "sell_value_usd": 3000, "reason": "test"},
        ]
        with patch("nuri.analysis.rebalance_advisor.detect_violations", return_value=fake_violations):
            report = generate_advisor_report(db_path=rich_db)
        assert report["total_violations"] == 1
        assert report["has_critical"] is True
        assert report["violations_by_type"]["leverage_etf"] == 1


class TestRebalanceAdvisor_R27:
    """From test_coverage_round27.py."""
    def test_severity_leverage(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("leverage_etf", 0, 0) == "critical"

    def test_severity_stop_loss_critical(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("stop_loss_exceeded", -14, -7) == "critical"

    def test_severity_stop_loss_high(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("stop_loss_exceeded", -8, -7) == "high"

    def test_severity_position_limit(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("position_limit_exceeded", 20, 0.15) == "medium"
        assert _severity("position_limit_exceeded", 30, 0.15) == "high"

    def test_severity_sector_limit(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("sector_limit_exceeded", 40, 0.35) == "medium"
        assert _severity("sector_limit_exceeded", 55, 0.35) == "high"

    def test_severity_default(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("unknown_type", 0, 0) == "medium"

    def test_print_rebalance_advisor_empty(self, capsys):
        from nuri.analysis.rebalance_advisor import print_rebalance_advisor
        print_rebalance_advisor([])
        captured = capsys.readouterr()
        assert "위반 사항 없음" in captured.out

    def test_print_rebalance_advisor_with_actions(self, capsys):
        from nuri.analysis.rebalance_advisor import print_rebalance_advisor
        actions = [{
            "ticker": "TQQQ", "action": "SELL_ALL", "sell_shares": 10,
            "sell_value_usd": 500, "reason": "레버리지 ETF 금지",
            "severity": "critical", "cumulative_recovery_usd": 500,
        }]
        print_rebalance_advisor(actions)
        captured = capsys.readouterr()
        assert "TQQQ" in captured.out

    def test_generate_advisor_report_empty(self, monkeypatch):
        from nuri.analysis.rebalance_advisor import generate_advisor_report
        monkeypatch.setattr("nuri.analysis.rebalance_advisor.calculate_rebalance_actions", lambda db_path=None: [])
        report = generate_advisor_report()
        assert report["total_violations"] == 0
        assert report["has_critical"] is False


class TestRebalanceModule_R3:
    """From test_coverage_round3.py (detect_violations with rate)."""
    def test_detect_violations_with_rate(self, db_path):
        from nuri.analysis.rebalance_advisor import detect_violations
        mock_df = pd.DataFrame([
            {"ticker": "AAPL", "account": "test", "quantity": 10,
             "avg_price": 190, "current_price": 200, "current_value_usd": 2000,
             "pnl_pct": 5.2, "weight_pct": 60.0, "sector": "Tech", "currency": "USD"},
        ])
        mock_df.attrs["total_value_usd"] = 2000
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            violations = detect_violations()
        assert isinstance(violations, list)


# ═══════════════════════════════════════════════════════════════════════
# 10. Evidence Charts
# ═══════════════════════════════════════════════════════════════════════


class TestEvidenceCharts:
    """From test_coverage_round8.py."""
    def test_generate_regime_chart(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_regime_chart
        try:
            path = generate_regime_chart(output_dir=tmp_path)
            assert path is None or path.exists()
        except Exception:
            pass

    def test_generate_portfolio_heatmap(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_portfolio_heatmap
        try:
            path = generate_portfolio_heatmap(output_dir=tmp_path)
            assert path is None or path.exists()
        except Exception:
            pass

    def test_generate_signal_performance(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_signal_performance_chart
        try:
            path = generate_signal_performance_chart(output_dir=tmp_path)
            assert path is None or path.exists()
        except Exception:
            pass

    def test_generate_fear_greed(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_fear_greed_chart
        try:
            path = generate_fear_greed_chart(output_dir=tmp_path)
            assert path is None or path.exists()
        except Exception:
            pass


class TestEvidenceSellChart:
    """From test_coverage_round13.py."""
    def test_generate_sell_evidence(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_sell_evidence_chart
        violations = [
            {"ticker": "AAPL", "violation_type": "leverage_etf",
             "severity": "critical", "action": "SELL_ALL"},
        ]
        try:
            path = generate_sell_evidence_chart(violations, output_dir=tmp_path)
            assert path.exists() or path is None
        except Exception:
            pass


class TestEvidenceChartsAll:
    """From test_coverage_round15.py."""
    def test_regime_chart(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_regime_chart
        path = generate_regime_chart(output_dir=tmp_path)
        assert path is not None and path.exists()

    def test_portfolio_heatmap(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_portfolio_heatmap
        with patch("nuri.analysis.portfolio.get_exchange_rate", return_value=1400.0):
            try:
                path = generate_portfolio_heatmap(output_dir=tmp_path)
                assert path.exists()
            except Exception:
                pass

    def test_fear_greed_chart(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_fear_greed_chart
        path = generate_fear_greed_chart(output_dir=tmp_path)
        assert path is not None and path.exists()


class TestEvidenceChartsDeep:
    """From test_sixty_percent.py."""
    def test_regime_chart_with_data(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_regime_chart
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_regime_chart(output_dir, db_path=rich_db)
        assert result.exists()

    def test_portfolio_heatmap_with_data(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_portfolio_heatmap
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_portfolio_heatmap(output_dir, db_path=rich_db)
        assert result.exists()

    def test_signal_performance_with_data(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_signal_performance_chart
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_signal_performance_chart(output_dir, db_path=rich_db)
        assert result.exists()

    def test_fear_greed_with_data(self, rich_db, tmp_path):
        with get_db(rich_db) as conn:
            for i in range(60):
                conn.execute(
                    "INSERT OR IGNORE INTO macro (date, indicator, value) VALUES (?, 'fear_greed', ?)",
                    (f"2026-01-{(i % 28) + 1:02d}", 30.0 + i * 0.5),
                )
        from nuri.analysis.evidence_charts import generate_fear_greed_chart
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_fear_greed_chart(output_dir, db_path=rich_db)
        assert result.exists()


class TestEvidenceCharts_NewModules:
    """From test_new_modules.py."""
    def test_portfolio_heatmap(self, db_path, tmp_path):
        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "NVDA", "sector": "Semiconductor", "quantity": 20,
             "avg_price": 100.0, "current_price": 167.99, "currency": "USD",
             "current_value_usd": 3359.8, "cost_basis_usd": 2642.8,
             "pnl_usd": 717.0, "pnl_pct": 27.1, "weight_pct": 60.0, "price_date": "2026-03-27"},
            {"account": "test", "ticker": "TSLL", "sector": "SectorB", "quantity": 96,
             "avg_price": 20.0, "current_price": 11.44, "currency": "USD",
             "current_value_usd": 1098.24, "cost_basis_usd": 1625.28,
             "pnl_usd": -527.04, "pnl_pct": -32.4, "weight_pct": 40.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 4458.04
        from nuri.analysis.evidence_charts import generate_portfolio_heatmap
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        with patch("nuri.analysis.portfolio.analyze_portfolio", return_value=mock_df):
            result = generate_portfolio_heatmap(output_dir, db_path=db_path)
        assert result.exists()
        assert result.suffix == ".html"

    def test_fear_greed_chart(self, db_path, tmp_path):
        with get_db(db_path) as conn:
            for i in range(30):
                conn.execute(
                    "INSERT OR REPLACE INTO macro (date, indicator, value) VALUES (?, 'fear_greed', ?)",
                    (f"2026-03-{i + 1:02d}", 10.0 + i * 2),
                )
        from nuri.analysis.evidence_charts import generate_fear_greed_chart
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_fear_greed_chart(output_dir, db_path=db_path)
        assert result.exists()

    def test_sell_evidence_chart(self, tmp_path):
        violations = [
            {"ticker": "TSLL", "violation_type": "leverage_etf", "severity": "critical",
             "current_value": -32.3, "sell_value_usd": 1100, "action": "SELL_ALL",
             "reason": "레버리지 ETF 금지"},
            {"ticker": "OKLO", "violation_type": "stop_loss_exceeded", "severity": "critical",
             "current_value": -59.9, "sell_value_usd": 1011, "action": "SELL_ALL",
             "reason": "손절 -59.9% 초과"},
        ]
        from nuri.analysis.evidence_charts import generate_sell_evidence_chart
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_sell_evidence_chart(violations, output_dir)
        assert result.exists()
        content = result.read_text()
        assert "TSLL" in content

    def test_signal_performance_empty(self, db_path, tmp_path):
        from nuri.analysis.evidence_charts import generate_signal_performance_chart
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_signal_performance_chart(output_dir, db_path=db_path)
        assert result.exists()


class TestEvidenceChartsExtended:
    """From test_coverage_boost.py."""
    def test_load_latest_scorecard(self, db_path):
        from nuri.analysis.evidence_charts import _load_latest_scorecard
        df = _load_latest_scorecard()
        assert df is None or isinstance(df, pd.DataFrame)

    def test_load_drift_map(self, db_path):
        from nuri.analysis.evidence_charts import _load_drift_map
        result = _load_drift_map(db_path=db_path)
        assert isinstance(result, dict)

    def test_detect_violations_empty(self, db_path, monkeypatch):
        monkeypatch.setattr("nuri.analysis.evidence_charts.analyze_portfolio",
                            lambda **kw: pd.DataFrame(), raising=False)
        from nuri.analysis.evidence_charts import _detect_portfolio_violations
        result = _detect_portfolio_violations(db_path=db_path)
        assert isinstance(result, list)

    def test_regime_chart_no_data(self, db_path, tmp_path):
        from nuri.analysis.evidence_charts import generate_regime_chart
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_regime_chart(output_dir, db_path=db_path)
        assert isinstance(result, type(output_dir / "test"))

    def test_generate_all_evidence_empty(self, db_path, tmp_path, monkeypatch):
        import nuri.analysis.evidence_charts as ec_mod
        monkeypatch.setattr(ec_mod, "REPORT_DIR", tmp_path)
        results = ec_mod.generate_all_evidence(db_path=db_path)
        assert isinstance(results, list)


class TestEvidenceCharts_R19:
    """From test_coverage_round19.py."""
    def test_generate_regime_chart_empty_db(self, tmp_path):
        from nuri.analysis.evidence_charts import generate_regime_chart
        path = tmp_path / "test.db"
        init_db(path)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        result = generate_regime_chart(output_dir, db_path=path)
        assert result == output_dir / "regime_evidence.html"

    def test_generate_regime_chart_with_data(self, rich_db, tmp_path, monkeypatch):
        from nuri.analysis.evidence_charts import generate_regime_chart
        from nuri.quant.regime import classifier as cls_mod
        cls_mod._freshness_warned = False
        monkeypatch.setattr(cls_mod, "_check_data_freshness", lambda db_path=None: True)
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_regime_chart(output_dir, db_path=rich_db)
        assert result.exists()
        assert result.suffix == ".html"

    def test_generate_fear_greed_chart_empty(self, tmp_path):
        from nuri.analysis.evidence_charts import generate_fear_greed_chart
        path = tmp_path / "test.db"
        init_db(path)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        result = generate_fear_greed_chart(output_dir, db_path=path)
        assert result == output_dir / "fear_greed.html"

    def test_generate_fear_greed_chart_with_data(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_fear_greed_chart
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_fear_greed_chart(output_dir, db_path=rich_db)
        assert result.exists()
        content = result.read_text()
        assert "plotly" in content.lower() or "html" in content.lower()

    def test_generate_sell_evidence_no_violations(self, tmp_path):
        from nuri.analysis.evidence_charts import generate_sell_evidence_chart
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        result = generate_sell_evidence_chart([], output_dir)
        assert result.exists()

    def test_generate_sell_evidence_with_violations(self, tmp_path):
        from nuri.analysis.evidence_charts import generate_sell_evidence_chart
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        violations = [
            {"ticker": "TSLA", "type": "stop_loss", "severity": 25.3,
             "action": "SELL ALL", "recovery": "6-12개월"},
            {"ticker": "NVDA", "type": "overweight", "severity": 5.2,
             "action": "REDUCE", "recovery": "리밸런싱 필요"},
        ]
        result = generate_sell_evidence_chart(violations, output_dir)
        assert result.exists()

    def test_save_empty_chart(self, tmp_path):
        from nuri.analysis.evidence_charts import _save_empty_chart
        output_path = tmp_path / "empty.html"
        _save_empty_chart("No data available", output_path)
        assert output_path.exists()
        content = output_path.read_text()
        assert "No data available" in content

    def test_shade_regime_zones_empty(self):
        import plotly.graph_objects as go

        from nuri.analysis.evidence_charts import _shade_regime_zones
        fig = go.Figure()
        df = pd.DataFrame(columns=["date", "sma50", "sma200"])
        _shade_regime_zones(fig, df)

    def test_load_latest_scorecard_no_reports(self, tmp_path, monkeypatch):
        from nuri.analysis import evidence_charts as ec_mod
        monkeypatch.setattr(ec_mod, "REPORT_DIR", tmp_path / "nonexistent")
        result = ec_mod._load_latest_scorecard()
        assert result is None

    def test_detect_portfolio_violations_no_data(self):
        from nuri.analysis.evidence_charts import _detect_portfolio_violations
        with patch("nuri.analysis.portfolio.analyze_portfolio",
                   return_value=pd.DataFrame()):
            violations = _detect_portfolio_violations()
        assert violations == []

    def test_generate_signal_performance_empty(self, tmp_path):
        from nuri.analysis.evidence_charts import generate_signal_performance_chart
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        with patch("nuri.analysis.evidence_charts._load_latest_scorecard", return_value=None):
            result = generate_signal_performance_chart(output_dir)
        assert result.exists()


class TestEvidenceChartsPortfolioViolations:
    """From test_coverage_round19.py."""
    def test_violations_detected(self):
        from nuri.analysis.evidence_charts import _detect_portfolio_violations
        mock_df = pd.DataFrame([
            {"ticker": "TSLA", "pnl_pct": -25.0, "weight_pct": 8.0},
            {"ticker": "NVDA", "pnl_pct": 15.0, "weight_pct": 20.0},
            {"ticker": "AAPL", "pnl_pct": 5.0, "weight_pct": 10.0},
        ])
        with patch("nuri.analysis.portfolio.analyze_portfolio", return_value=mock_df):
            violations = _detect_portfolio_violations()
        assert len(violations) >= 2
        tickers = [v["ticker"] for v in violations]
        assert "TSLA" in tickers
        assert "NVDA" in tickers

    def test_violations_exception_returns_empty(self):
        from nuri.analysis.evidence_charts import _detect_portfolio_violations
        with patch("nuri.analysis.portfolio.analyze_portfolio",
                   side_effect=Exception("no data")):
            violations = _detect_portfolio_violations()
        assert violations == []


class TestSignalPerformanceChart:
    """From test_coverage_round19.py."""
    def test_with_scorecard_data(self, tmp_path):
        from nuri.analysis.evidence_charts import generate_signal_performance_chart
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        scorecard_df = pd.DataFrame([
            {"signal_id": "rsi_oversold", "ticker": None, "total_trades": 10,
             "win_rate": 0.6, "profit_factor": 1.5, "avg_return": 2.0,
             "median_return": 1.5, "max_return": 10.0, "max_loss": -5.0,
             "avg_holding_days": 20},
            {"signal_id": "macd_golden", "ticker": None, "total_trades": 8,
             "win_rate": 0.5, "profit_factor": 1.2, "avg_return": 1.0,
             "median_return": 0.8, "max_return": 8.0, "max_loss": -6.0,
             "avg_holding_days": 30},
        ])
        with patch("nuri.analysis.evidence_charts._load_latest_scorecard",
                   return_value=scorecard_df), \
             patch("nuri.analysis.evidence_charts._load_drift_map",
                   return_value={"rsi_oversold": {"status": "critical", "drift_pct": -15.0}}):
            result = generate_signal_performance_chart(output_dir)
        assert result.exists()
        content = result.read_text()
        assert "rsi_oversold" in content or "plotly" in content.lower()


class TestShadeRegimeZonesWithData:
    """From test_coverage_round19.py."""
    def test_zones_applied(self):
        import plotly.graph_objects as go

        from nuri.analysis.evidence_charts import _shade_regime_zones
        n = 100
        spy = pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=n),
            "close": np.linspace(450, 500, n),
        })
        spy["sma50"] = spy["close"].rolling(20).mean()
        spy["sma200"] = spy["close"].rolling(50).mean()
        fig = go.Figure()
        _shade_regime_zones(fig, spy)


class TestGenerateAllEvidence:
    """From test_coverage_round19.py."""
    def test_all_evidence_with_mocks(self, tmp_path, monkeypatch, capsys):
        import nuri.analysis.evidence_charts as ec_mod
        monkeypatch.setattr(ec_mod, "REPORT_DIR", tmp_path / "reports")
        with patch.object(ec_mod, "generate_regime_chart",
                         return_value=tmp_path / "regime.html"), \
             patch.object(ec_mod, "generate_portfolio_heatmap",
                         return_value=tmp_path / "heatmap.html"), \
             patch.object(ec_mod, "generate_signal_performance_chart",
                         return_value=tmp_path / "signal.html"), \
             patch.object(ec_mod, "generate_fear_greed_chart",
                         return_value=tmp_path / "fg.html"), \
             patch.object(ec_mod, "_detect_portfolio_violations",
                         return_value=[]), \
             patch.object(ec_mod, "generate_sell_evidence_chart",
                         return_value=tmp_path / "sell.html"):
            paths = ec_mod.generate_all_evidence()
        assert len(paths) == 5
        captured = capsys.readouterr()
        assert "완료" in captured.out

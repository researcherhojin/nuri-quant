"""Analysis 모듈 테스트 — v2 Riskfolio-Lib + QuantStats."""
import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_prices, upsert_portfolio, upsert_macro


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def populated_db(db_path, monkeypatch):
    """분석에 필요한 데이터."""
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

    import nuri.core.db
    monkeypatch.setattr(nuri.core.db, "DB_PATH", db_path)
    return db_path


class TestPortfolioAnalysis:
    def test_analyze_returns_dataframe(self, populated_db):
        from nuri.analysis.portfolio import analyze_portfolio
        df = analyze_portfolio()
        assert not df.empty
        assert "weight_pct" in df.columns

    def test_total_weight_100(self, populated_db):
        from nuri.analysis.portfolio import analyze_portfolio
        df = analyze_portfolio()
        assert abs(df["weight_pct"].sum() - 100.0) < 0.1


class TestRiskAnalysis:
    def test_risk_metrics_keys(self, populated_db):
        from nuri.analysis.risk import analyze_risk
        metrics = analyze_risk()
        assert "sharpe_ratio" in metrics
        assert "cvar_95_daily_pct" in metrics  # v2에서 CVaR 추가됨


class TestPerformance:
    def test_portfolio_returns(self, populated_db):
        from nuri.analysis.performance import get_portfolio_returns
        returns = get_portfolio_returns()
        assert len(returns) > 0


class TestSectorAnalysis:
    def test_sector_weights_sum_100(self, populated_db):
        from nuri.analysis.sector import analyze_sector
        sector_df, _, _ = analyze_sector()
        assert not sector_df.empty
        assert abs(sector_df["weight_pct"].sum() - 100.0) < 0.5

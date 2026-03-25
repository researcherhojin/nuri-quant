"""Analysis 모듈 테스트 — 합성 데이터로 결정론적 테스트."""
import pytest
import pandas as pd

from iris.db import init_db, upsert_prices, upsert_portfolio, upsert_macro


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def populated_db(db_path, monkeypatch):
    """분석에 필요한 데이터가 있는 DB."""
    # 포트폴리오
    upsert_portfolio([
        {"account": "test", "ticker": "TSLA", "quantity": 10,
         "avg_price": 300, "currency": "USD", "sector": "SectorA"},
        {"account": "test", "ticker": "NVDA", "quantity": 5,
         "avg_price": 130, "currency": "USD", "sector": "Semiconductor"},
        {"account": "test", "ticker": "VOO", "quantity": 2,
         "avg_price": 500, "currency": "USD", "sector": "ETF"},
    ], db_path)

    # 가격 데이터 (60일)
    for ticker, base_price in [("TSLA", 300), ("NVDA", 150), ("VOO", 520)]:
        df = pd.DataFrame([
            {"ticker": ticker, "date": f"2026-01-{d:02d}" if d <= 31 else f"2026-02-{d-31:02d}",
             "open": base_price + d, "high": base_price + d + 5,
             "low": base_price + d - 5, "close": base_price + d,
             "volume": 1000000, "adj_close": base_price + d}
            for d in range(1, 61)
        ])
        upsert_prices(df, db_path)

    # 매크로
    upsert_macro([
        {"indicator": "usd_krw", "date": "2026-03-24", "value": 1450.0, "source": "FRED"},
        {"indicator": "fear_greed", "date": "2026-03-24", "value": 45.0, "source": "CNN"},
        {"indicator": "fed_funds_rate", "date": "2026-03-24", "value": 5.0, "source": "FRED"},
    ], db_path)

    # DB_PATH를 임시 경로로 오버라이드
    import iris.db
    monkeypatch.setattr(iris.db, "DB_PATH", db_path)

    return db_path


class TestPortfolioAnalysis:
    def test_analyze_returns_dataframe(self, populated_db):
        from iris.analysis.portfolio import analyze_portfolio
        df = analyze_portfolio()
        assert not df.empty
        assert "weight_pct" in df.columns
        assert "pnl_pct" in df.columns

    def test_total_weight_100(self, populated_db):
        from iris.analysis.portfolio import analyze_portfolio
        df = analyze_portfolio()
        total_weight = df["weight_pct"].sum()
        assert abs(total_weight - 100.0) < 0.1


class TestRiskAnalysis:
    def test_risk_metrics_keys(self, populated_db):
        from iris.analysis.risk import analyze_risk
        metrics = analyze_risk()
        assert "sharpe_ratio" in metrics
        assert "max_drawdown_pct" in metrics
        assert "var_95_daily_pct" in metrics


class TestSectorAnalysis:
    def test_sector_weights_sum_100(self, populated_db):
        from iris.analysis.sector import analyze_sector
        sector_df, region_df, warnings = analyze_sector()
        assert not sector_df.empty
        total = sector_df["weight_pct"].sum()
        assert abs(total - 100.0) < 0.5

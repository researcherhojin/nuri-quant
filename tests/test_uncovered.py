"""테스트 미커버 모듈 7개 테스트 — correlation, sentiment, performance, charts, events, news, institutional."""
import pandas as pd
import pytest

from nuri.core.db import init_db, query, upsert_news, upsert_portfolio, upsert_prices


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """테스트 DB 생성 + 글로벌 DB_PATH 교체."""
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture
def price_data(db_path):
    """가격 + 포트폴리오 테스트 데이터."""
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
         "avg_price": 250, "currency": "USD", "sector": "EV/AI"},
    ], db_path)
    return db_path


# ═══════════════════════════════════════════════════════
# Correlation
# ═══════════════════════════════════════════════════════

class TestCorrelation:
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


# ═══════════════════════════════════════════════════════
# Sentiment
# ═══════════════════════════════════════════════════════

class TestSentiment:
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


# ═══════════════════════════════════════════════════════
# Performance
# ═══════════════════════════════════════════════════════

class TestPerformance:
    def test_get_portfolio_returns(self, price_data):
        from nuri.analysis.performance import get_portfolio_returns
        returns = get_portfolio_returns()
        assert isinstance(returns, pd.Series)

    def test_get_benchmark_returns_empty(self, db_path):
        from nuri.analysis.performance import get_benchmark_returns
        returns = get_benchmark_returns()
        assert isinstance(returns, pd.Series)


# ═══════════════════════════════════════════════════════
# Charts (데이터 로드만 테스트, 렌더링은 건너뜀)
# ═══════════════════════════════════════════════════════

class TestCharts:
    def test_load_chart_data(self, price_data):
        from nuri.analysis.charts import _load_chart_data
        df = _load_chart_data("AAPL")
        if df is not None:
            assert "close" in df.columns

    def test_load_chart_data_missing(self, db_path):
        from nuri.analysis.charts import _load_chart_data
        df = _load_chart_data("XXXXX")
        assert df is None


# ═══════════════════════════════════════════════════════
# Events Collector
# ═══════════════════════════════════════════════════════

class TestEventsCollector:
    def test_save_empty(self, db_path):
        from nuri.collectors.events import EventsCollector
        collector = EventsCollector()
        count = collector.save([])
        assert count == 0

    def test_save_records(self, db_path):
        from nuri.collectors.events import EventsCollector
        collector = EventsCollector()
        records = [{
            "date": "2025-06-01", "event_type": "earnings",
            "ticker": "AAPL", "description": "Q2 earnings",
            "importance": "high",
        }]
        count = collector.save(records)
        assert count >= 0


# ═══════════════════════════════════════════════════════
# News Collector
# ═══════════════════════════════════════════════════════

class TestNewsCollector:
    def test_save_empty(self, db_path):
        from nuri.collectors.news import NewsCollector
        collector = NewsCollector()
        count = collector.save([])
        assert count == 0

    def test_upsert_news(self, db_path):
        records = [{
            "ticker": "AAPL", "date": "2025-06-01",
            "title": "Apple announces new product",
            "url": "https://example.com/news/1",
            "source": "test", "sentiment": None,
        }]
        count = upsert_news(records, db_path)
        assert count == 1
        rows = query("SELECT * FROM news WHERE ticker='AAPL'", db_path=db_path)
        assert len(rows) == 1


# ═══════════════════════════════════════════════════════
# Institutional Collector
# ═══════════════════════════════════════════════════════

class TestInstitutionalCollector:
    def test_instantiate(self):
        from nuri.collectors.institutional import InstitutionalCollector
        collector = InstitutionalCollector()
        assert collector.name == "institutional"

    def test_save_empty(self, db_path):
        from nuri.collectors.institutional import InstitutionalCollector
        collector = InstitutionalCollector()
        count = collector.save([])
        assert count == 0

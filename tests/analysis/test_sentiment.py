"""Tests for nuri.analysis.sentiment — split from tests/test_analysis_all.py (#157)."""

from nuri.core.db import get_db, query, upsert_news


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

        upsert_news(
            [
                {
                    "ticker": "AAPL",
                    "date": "2025-06-01",
                    "title": "Apple reports record breaking revenue growth",
                    "url": "https://example.com/1",
                    "source": "test",
                    "sentiment": None,
                }
            ],
            db_path,
        )
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
        assert compute_sentiment(None) == 0.0  # type: ignore[arg-type]

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

    def test_get_stats_empty_rows_returns_empty(self, monkeypatch):
        """Defensive — query returning [] → return {} (line 107)."""
        import nuri.analysis.sentiment as mod

        monkeypatch.setattr(mod, "query", lambda *a, **kw: [])
        result = mod._get_stats()
        assert result == {}

"""nuri.core.catalyst — non-emergency SELL catalyst detection (Phase 2 A-4)."""
import pytest

from nuri.core.db import get_db, init_db


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


class TestHasRecentCatalyst:
    """§2.1 Evidence-first — non-emergency SELL 은 catalyst 없이 'actionable' 로
    승격되지 않도록 gate. 뉴스 (ticker 특화) 또는 유의미 macro_event 둘 중 하나
    만 있어도 통과. 둘 다 없으면 advisory 로 downgrade."""

    def test_no_news_no_macro_returns_false(self, db_path):
        """빈 DB — catalyst 없음 → False + 이유."""
        from nuri.core.catalyst import has_recent_catalyst

        ok, reason = has_recent_catalyst("TSLA", ref_date="2026-04-18", db_path=db_path)
        assert ok is False
        assert "no ticker news" in reason

    def test_recent_ticker_news_passes(self, db_path):
        """14일 이내 뉴스 → True."""
        from nuri.core.catalyst import has_recent_catalyst

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO news (ticker, date, title, url, source, sentiment) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("TSLA", "2026-04-15", "Tesla earnings beat", "https://x/1", "test", 0.4),
            )

        ok, reason = has_recent_catalyst("TSLA", ref_date="2026-04-18", db_path=db_path)
        assert ok is True
        assert "news" in reason
        assert "1 item" in reason

    def test_old_news_outside_window_does_not_pass(self, db_path):
        """14일보다 오래된 뉴스 → 카운트 안 됨 (stale)."""
        from nuri.core.catalyst import has_recent_catalyst

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO news (ticker, date, title, url, source, sentiment) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("TSLA", "2026-03-01", "Old news", "https://x/2", "test", 0.2),
            )

        ok, reason = has_recent_catalyst("TSLA", ref_date="2026-04-18", db_path=db_path)
        assert ok is False

    def test_significant_macro_event_passes(self, db_path):
        """유의미 macro_event (confidence≥0.5, |sentiment|≥0.3) 이 7일 이내 → True."""
        from nuri.core.catalyst import has_recent_catalyst

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro_events (published_at, source, headline, url, "
                "category, sentiment, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("2026-04-15", "test", "Fed rate decision", "https://m/1",
                 "monetary_policy", -0.5, 0.8),
            )

        ok, reason = has_recent_catalyst("TSLA", ref_date="2026-04-18", db_path=db_path)
        assert ok is True
        assert "macro" in reason

    def test_low_confidence_macro_does_not_pass(self, db_path):
        """confidence < 0.5 macro → 노이즈, 카운트 안 됨."""
        from nuri.core.catalyst import has_recent_catalyst

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro_events (published_at, source, headline, url, "
                "category, sentiment, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("2026-04-15", "test", "Weak classify", "https://m/2",
                 "monetary_policy", -0.5, 0.3),
            )

        ok, _ = has_recent_catalyst("TSLA", ref_date="2026-04-18", db_path=db_path)
        assert ok is False

    def test_neutral_sentiment_macro_does_not_pass(self, db_path):
        """|sentiment| < 0.3 macro → 방향성 없음, 카운트 안 됨."""
        from nuri.core.catalyst import has_recent_catalyst

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro_events (published_at, source, headline, url, "
                "category, sentiment, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("2026-04-15", "test", "Neutral news", "https://m/3",
                 "monetary_policy", 0.1, 0.9),
            )

        ok, _ = has_recent_catalyst("TSLA", ref_date="2026-04-18", db_path=db_path)
        assert ok is False

    def test_old_macro_outside_window_does_not_pass(self, db_path):
        """7일보다 오래된 macro → 카운트 안 됨."""
        from nuri.core.catalyst import has_recent_catalyst

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro_events (published_at, source, headline, url, "
                "category, sentiment, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("2026-04-05", "test", "Stale macro", "https://m/4",
                 "monetary_policy", -0.6, 0.7),
            )

        ok, _ = has_recent_catalyst("TSLA", ref_date="2026-04-18", db_path=db_path)
        assert ok is False

    def test_news_for_other_ticker_does_not_pass(self, db_path):
        """다른 ticker 의 뉴스는 이 ticker 의 catalyst 가 아님."""
        from nuri.core.catalyst import has_recent_catalyst

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO news (ticker, date, title, url, source, sentiment) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("AAPL", "2026-04-15", "Apple news", "https://x/3", "test", 0.4),
            )

        ok, _ = has_recent_catalyst("TSLA", ref_date="2026-04-18", db_path=db_path)
        assert ok is False

    def test_news_takes_priority_over_macro(self, db_path):
        """둘 다 있어도 news 를 먼저 리포트 (ticker-specific 이 더 구체)."""
        from nuri.core.catalyst import has_recent_catalyst

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO news (ticker, date, title, url, source, sentiment) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("TSLA", "2026-04-15", "Tesla news", "https://x/4", "test", 0.3),
            )
            conn.execute(
                "INSERT INTO macro_events (published_at, source, headline, url, "
                "category, sentiment, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("2026-04-15", "test", "Fed news", "https://m/5",
                 "monetary_policy", -0.5, 0.8),
            )

        ok, reason = has_recent_catalyst("TSLA", ref_date="2026-04-18", db_path=db_path)
        assert ok is True
        assert "news" in reason  # news 가 먼저 매칭됨
        assert "macro" not in reason

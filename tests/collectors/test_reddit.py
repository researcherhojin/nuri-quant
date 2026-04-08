"""Per-collector tests for reddit.

Split from tests/test_collectors_all.py for module-level isolation.
"""
from unittest.mock import MagicMock, patch

from nuri.core.db import (
    upsert_macro,
)


class TestRedditCollector:
    def test_count_mentions_dollar_sign(self):
        from nuri.collectors.reddit import RedditCollector

        collector = RedditCollector()
        posts = [
            {"title": "$TSLA to the moon!", "selftext": "Buy $NVDA too"},
            {"title": "What about $TSLA?", "selftext": ""},
        ]
        counts = collector._count_mentions(posts, {"TSLA", "NVDA", "AAPL"})
        assert counts["TSLA"] == 2
        assert counts["NVDA"] == 1

    def test_count_mentions_uppercase(self):
        from nuri.collectors.reddit import RedditCollector

        collector = RedditCollector()
        posts = [{"title": "TSLA earnings tomorrow", "selftext": "NVDA looking good"}]
        counts = collector._count_mentions(posts, {"TSLA", "NVDA"})
        assert counts["TSLA"] == 1
        assert counts["NVDA"] == 1

    def test_noise_words_filtered(self):
        from nuri.collectors.reddit import RedditCollector

        collector = RedditCollector()
        posts = [{"title": "CEO of THE company IS great", "selftext": "BUY NOW OR NOT"}]
        counts = collector._count_mentions(posts, set())
        assert counts.get("THE", 0) == 0
        assert counts.get("CEO", 0) == 0
        assert counts.get("BUY", 0) == 0

    @patch("nuri.collectors.reddit.requests.get")
    @patch("nuri.collectors.reddit.RedditCollector._get_tickers")
    def test_collect_with_mock_api(self, mock_tickers, mock_get):
        from nuri.collectors.reddit import RedditCollector

        mock_tickers.return_value = ["TSLA", "NVDA"]
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"title": "$TSLA yolo", "selftext": "diamond hands TSLA"},
                {"title": "NVDA earnings beat", "selftext": "$TSLA also up"},
                {"title": "Market crash incoming", "selftext": "sell everything"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = RedditCollector()
        records = collector.collect()
        indicators = {r["indicator"]: r["value"] for r in records}
        assert indicators["wsb_post_count"] == 3.0
        assert indicators["wsb_held_mentions"] == 2.0

    @patch("nuri.collectors.reddit.requests.get")
    @patch("nuri.collectors.reddit.RedditCollector._get_tickers")
    def test_save_to_macro(self, mock_tickers, mock_get, db_path):
        from nuri.collectors.reddit import RedditCollector

        mock_tickers.return_value = ["TSLA"]
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [{"title": "$TSLA", "selftext": ""}]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = RedditCollector()
        records = collector.collect()
        count = upsert_macro(records, db_path)
        assert count >= 1

    @patch("nuri.collectors.reddit.requests.get")
    @patch("nuri.collectors.reddit.RedditCollector._get_tickers")
    def test_api_failure_returns_empty(self, mock_tickers, mock_get):
        from nuri.collectors.reddit import RedditCollector

        mock_tickers.return_value = ["TSLA"]
        mock_get.side_effect = Exception("connection error")
        collector = RedditCollector()
        records = collector.collect()
        assert records == []



class TestRedditCollectorPagination:
    def test_collect_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.reddit import RedditCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [
            {"title": "$AAPL moon!", "selftext": "Buy AAPL", "created_utc": 1706400000},
            {"title": "NVDA earnings", "selftext": "NVDA beat", "created_utc": 1706400001},
        ]}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.reddit.requests.get", lambda url, **kw: mock_resp)
        results = RedditCollector().collect(days=1)
        assert "wsb_post_count" in [r["indicator"] for r in results]

    def test_collect_api_failure(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.reddit import RedditCollector

        monkeypatch.setattr("nuri.collectors.reddit.requests.get", MagicMock(side_effect=Exception("fail")))
        assert RedditCollector().collect() == []

    def test_collect_no_posts(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.reddit import RedditCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.reddit.requests.get", MagicMock(return_value=mock_resp))
        assert RedditCollector().collect() == []

    def test_count_mentions_noise_filter(self, db_with_portfolio):
        from nuri.collectors.reddit import RedditCollector

        counts = RedditCollector()._count_mentions(
            [{"title": "I AM going to BUY the DIP", "selftext": "AAPL NVDA"}], {"AAPL", "NVDA"})
        assert counts["AAPL"] >= 1
        assert counts.get("AM", 0) == 0

    def test_fetch_posts_pagination(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.reddit import RedditCollector

        call_count = [0]

        def mock_get(url, **kwargs):
            call_count[0] += 1
            mock_resp = MagicMock()
            if call_count[0] <= 2:
                mock_resp.json.return_value = {"data": [{"title": f"Post {call_count[0]}", "selftext": "", "created_utc": 1706400000 + call_count[0]}]}
            else:
                mock_resp.json.return_value = {"data": []}
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        monkeypatch.setattr("nuri.collectors.reddit.requests.get", mock_get)
        assert len(RedditCollector()._fetch_posts(days=1)) == 2

    def test_save(self, db_with_portfolio):
        from nuri.collectors.reddit import RedditCollector

        assert RedditCollector().save([{"indicator": "wsb_post_count", "date": "2025-01-30", "value": 100.0, "source": "Reddit_WSB"}]) == 1



class TestFetchPostsNoLastUTC:
    def test_fetch_posts_no_last_utc(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.reddit import RedditCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [{"title": "Test", "selftext": "", "created_utc": None}]}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.reddit.requests.get", MagicMock(return_value=mock_resp))
        assert len(RedditCollector()._fetch_posts(days=1)) == 1

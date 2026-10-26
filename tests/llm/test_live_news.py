"""실시간 종목 뉴스 (#1958) + TradingAgents 에서 가져온 Yahoo 파싱 — 네트워크 없이 Search 를 스텁한다."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

import nuri.core.db as db_mod
from nuri.llm import live_news
from nuri.llm.tradingagents import yahoo_news as yn

EPOCH = 1772870400  # 2026-03-07 08:00:00 UTC


def flat(ticker="AAA", link="https://x/1", **over):
    a = {
        "title": "t",
        "link": link,
        "publisher": "wire",
        "providerPublishTime": EPOCH,
        "relatedTickers": [ticker],
    }
    a.update(over)
    return a


def stub_search(monkeypatch, result):
    """`yf.Search(t, news_count=)` → result (SimpleNamespace 또는 예외)."""
    seen = []

    def search(ticker, news_count):
        seen.append((ticker, news_count))
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Search=search))
    return seen


@pytest.fixture(autouse=True)
def _no_db(monkeypatch, tmp_path):
    """실시간 조회는 DB 에 닿지 않는다 — 연결 진입점은 부르면 실패하고, 열리면 이 경로에 파일이 생긴다."""

    def boom(*a, **k):
        raise AssertionError("live news opened a DB connection")

    path = tmp_path / "must-not-exist.db"
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    monkeypatch.setattr(db_mod, "get_db", boom)
    monkeypatch.setattr(db_mod, "get_connection", boom)
    yield
    assert not path.exists(), "live news opened a DB connection"


def test_neither_module_imports_the_db_layer():
    """구조 잠금 — 읽기 전용 연결(`mode=ro`)은 파일을 만들지 않아 위 픽스처만으로는 못 잡을 수 있다."""
    import ast
    import inspect

    from nuri.llm import tradingagents

    for mod in (live_news, yn, tradingagents):
        tree = ast.parse(inspect.getsource(mod))
        names = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        names += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert not [m for m in names if m and (m.startswith("nuri.core.db") or m == "sqlite3")], mod.__name__


class TestFetchTime:
    @pytest.mark.parametrize(
        ("micro", "want"), [(0, "2026-03-09 23:59:59"), (1, "2026-03-10 00:00:00"), (999999, "2026-03-10 00:00:00")]
    )
    def test_the_fetch_time_is_rounded_up_so_a_sub_second_late_fetch_cannot_pass(self, monkeypatch, micro, want):
        from datetime import datetime, timedelta, timezone

        kst = timezone(timedelta(hours=9))
        monkeypatch.setattr(live_news, "kst_now", lambda: datetime(2026, 3, 10, 8, 59, 59, micro, tzinfo=kst))
        assert live_news._now_utc() == want


class TestExtractArticleData:
    def test_flat_epoch_and_nested_iso_become_utc(self):
        assert yn.extract_article_data(flat())["pub_date"] == "2026-03-07 08:00:00"
        nested = {"content": {"title": "h", "pubDate": "2026-03-07T17:00:00+09:00"}}
        assert yn.extract_article_data(nested)["pub_date"] == "2026-03-07 08:00:00"

    @pytest.mark.parametrize(
        "item",
        [
            {"title": "t"},
            {"providerPublishTime": 0},
            {"providerPublishTime": "x"},
            {"providerPublishTime": 10**20},
            {"content": {}},
            {"content": {"pubDate": "not a date"}},
            {"content": {"pubDate": "2026-03-07T08:00:00"}},  # 시간대 없음 — 기기 시간대로 읽지 않는다
        ],
    )
    def test_a_missing_or_ambiguous_time_is_none_never_today(self, item):
        assert yn.extract_article_data(item)["pub_date"] is None

    def test_nested_fields_and_null_defaults(self):
        item = {
            "content": {
                "title": None,
                "summary": "sum",
                "clickThroughUrl": {"url": "https://x/2"},
                "provider": None,
                "pubDate": "2026-03-07T08:00:00Z",
            }
        }
        assert yn.extract_article_data(item) == {
            "title": "No title",
            "summary": "sum",
            "publisher": "Unknown",
            "link": "https://x/2",
            "pub_date": "2026-03-07 08:00:00",
        }


class TestTaggedAndAnswered:
    def test_only_articles_tagged_with_the_symbol_case_insensitively(self):
        arts = [flat(), flat(relatedTickers=["aaa"]), flat(relatedTickers=["ZZZ"]), "junk", flat(relatedTickers=None)]
        assert len(yn.tagged(arts, "AAA")) == 2

    def test_answered_needs_news_or_the_same_symbol_in_quotes(self):
        assert yn.answered([flat()], [], "AAA")
        assert yn.answered([], [{"symbol": "aaa"}], "AAA")
        assert not yn.answered([], [{"symbol": "ZZZ"}, "junk"], "AAA")
        assert not yn.answered(None, None, "AAA")


class TestFetch:
    def test_ok_keeps_tagged_articles_with_a_link(self, monkeypatch):
        seen = stub_search(
            monkeypatch,
            SimpleNamespace(news=[flat(), flat(link=""), flat(relatedTickers=["ZZZ"])], quotes=[]),
        )
        got = live_news.fetch("AAA")
        assert got["status"] == "ok" and [a["link"] for a in got["articles"]] == ["https://x/1"]
        assert seen == [("AAA", live_news.NEWS_COUNT)]
        assert len(got["fetched_at"]) == 19

    def test_zero_tagged_is_ok_but_no_answer_is_failed(self, monkeypatch):
        stub_search(monkeypatch, SimpleNamespace(news=[], quotes=[{"symbol": "AAA"}]))
        assert live_news.fetch("AAA")["status"] == "ok"
        stub_search(monkeypatch, SimpleNamespace(news=None, quotes=None))
        got = live_news.fetch("AAA")
        assert got["status"] == "failed" and got["reason"] == "no answer" and got["articles"] == []

    def test_an_exception_is_failed_and_still_records_the_fetch_time(self, monkeypatch):
        stub_search(monkeypatch, TimeoutError("slow"))
        got = live_news.fetch("AAA")
        assert got["status"] == "failed" and got["reason"] == "TimeoutError" and "fetched_at" in got

    def test_kr_is_excluded_without_a_request(self, monkeypatch):
        seen = stub_search(monkeypatch, SimpleNamespace(news=[flat()], quotes=[]))
        assert live_news.fetch("005930.KS")["status"] == "excluded"
        assert seen == []

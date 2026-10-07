"""Per-collector tests for finviz.

Split from tests/test_collectors_all.py for module-level isolation.
"""

from unittest.mock import MagicMock, patch


class TestFINVIZCollector:
    def test_instantiate(self):
        from nuri.collectors.finviz import FINVIZCollector

        c = FINVIZCollector()
        assert c.name == "finviz"

    def test_signals_constant(self):
        from nuri.collectors.finviz import FINVIZ_SIGNALS

        assert "new_high" in FINVIZ_SIGNALS
        assert "oversold_rsi" in FINVIZ_SIGNALS

    def test_save_records(self, db_path):
        from nuri.collectors.finviz import FINVIZCollector

        c = FINVIZCollector()
        records = [{"date": "2026-03-30", "ticker": "AAPL", "signal": "new_high", "source": "FINVIZ"}]
        count = c.save(records, db_path=db_path)
        assert count == 1


class TestFINVIZCollector_Phase2:
    @patch("nuri.collectors.finviz.FINVIZCollector._fetch_signal_tickers")
    def test_fetch_signal_tickers(self, mock_fetch):
        from nuri.collectors.finviz import FINVIZCollector

        mock_fetch.return_value = {"TSLA", "NVDA", "AAPL", "MSFT"}
        collector = FINVIZCollector()
        tickers = collector._fetch_signal_tickers("Oversold")
        assert "TSLA" in tickers
        assert len(tickers) == 4

    @patch("nuri.collectors.finviz.FINVIZCollector._fetch_signal_tickers")
    @patch("nuri.collectors.finviz.FINVIZCollector._get_tickers")
    def test_collect_filters_held(self, mock_tickers, mock_fetch):
        from nuri.collectors.finviz import FINVIZCollector

        mock_tickers.return_value = ["TSLA", "NVDA", "AAPL"]
        mock_fetch.side_effect = [
            {"TSLA", "MSFT", "GME"},
            set(),
            {"NVDA"},
            set(),
            set(),
            {"TSLA", "AAPL"},
        ]
        collector = FINVIZCollector()
        records = collector.collect()
        tickers_found = {r["ticker"] for r in records}
        assert "TSLA" in tickers_found
        assert "GME" not in tickers_found

    def test_save_to_external_analysis(self, db_with_us_tickers):
        from nuri.collectors.finviz import FINVIZCollector

        collector = FINVIZCollector()
        data = [
            {"date": "2026-03-28", "ticker": "TSLA", "signal": "oversold_rsi", "source": "FINVIZ"},
            {"date": "2026-03-28", "ticker": "NVDA", "signal": "new_high", "source": "FINVIZ"},
        ]
        count = collector.save(data, db_path=db_with_us_tickers)
        assert count == 2

    @patch("nuri.collectors.finviz.FINVIZCollector._get_tickers")
    def test_collect_no_holdings(self, mock_tickers):
        from nuri.collectors.finviz import FINVIZCollector

        mock_tickers.return_value = []
        collector = FINVIZCollector()
        assert collector.collect() == []


class TestFINVIZCollectorMockedScreener:
    def test_collect_with_mocked_screener(self, rich_db, monkeypatch):
        from nuri.collectors.finviz import FINVIZCollector

        collector = FINVIZCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["AAPL", "NVDA"])
        monkeypatch.setattr(collector, "_fetch_signal_tickers", lambda signal: {"AAPL", "MSFT"})
        records = collector.collect()
        aapl_records = [r for r in records if r["ticker"] == "AAPL"]
        assert len(aapl_records) > 0

    def test_collect_no_us_tickers(self, rich_db, monkeypatch):
        from nuri.collectors.finviz import FINVIZCollector

        collector = FINVIZCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: [])
        assert collector.collect() == []

    def test_collect_fetch_exception(self, rich_db, monkeypatch):
        from nuri.collectors.finviz import FINVIZCollector

        collector = FINVIZCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["AAPL"])
        monkeypatch.setattr(collector, "_fetch_signal_tickers", MagicMock(side_effect=RuntimeError("fail")))
        # 전부 실패하면 빈 목록이 아니라 실패다 (#1724) — 이 테스트가 예전엔 그 조용한 성공을 잠갔다
        import pytest

        from nuri.collectors.base import CollectionFailureError

        with pytest.raises(CollectionFailureError):
            collector.collect()

    def test_fetch_signal_tickers_finvizfinance(self, monkeypatch):
        from nuri.collectors.finviz import FINVIZCollector

        collector = FINVIZCollector()
        mock_screener = MagicMock()
        mock_screener.screener_view.return_value = ["AAPL", "MSFT", "GOOG"]
        mock_ticker_cls = MagicMock(return_value=mock_screener)
        with patch("nuri.collectors.finviz.Ticker", mock_ticker_cls, create=True):
            mock_mod = MagicMock()
            mock_mod.screener.ticker.Ticker = mock_ticker_cls
            with patch.dict(
                "sys.modules",
                {
                    "finvizfinance": mock_mod,
                    "finvizfinance.screener": mock_mod.screener,
                    "finvizfinance.screener.ticker": mock_mod.screener.ticker,
                },
            ):
                result = collector._fetch_signal_tickers("Oversold")
                assert isinstance(result, set)

    def test_save_empty(self, rich_db):
        from nuri.collectors.finviz import FINVIZCollector

        assert FINVIZCollector().save([]) == 0

    def test_save_records(self, rich_db):
        from nuri.collectors.finviz import FINVIZCollector

        count = FINVIZCollector().save(
            [
                {"date": "2025-01-01", "ticker": "AAPL", "signal": "oversold_rsi", "source": "FINVIZ"},
            ],
            db_path=rich_db,
        )
        assert count == 1

    def test_scrape_signal_fallback_mocked(self, monkeypatch):
        from nuri.collectors.finviz import FINVIZCollector

        collector = FINVIZCollector()
        html_content = """
        <html><body>
        <a href="quote.ashx?t=AAPL">AAPL</a>
        <a href="quote.ashx?t=MSFT">MSFT</a>
        </body></html>
        """
        mock_resp = MagicMock()
        mock_resp.text = html_content
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock_resp):
            result = collector._scrape_signal_fallback("Oversold")
            assert "AAPL" in result


# ##############################################################################
# Source: test_coverage_round24.py -- comprehensive collector tests
# ##############################################################################


# ─── Phase 3-D #616: branch coverage ──────────────────────────────────


class TestFinvizFallbackBranches:
    def test_finvizfinance_empty_list_falls_to_scrape(self, monkeypatch):
        """94→100: finvizfinance result 빈 list → if False → 직접 스크래핑 호출."""
        from nuri.collectors.finviz import FINVIZCollector

        # finvizfinance Ticker 가 빈 list 반환 (signal 없음 케이스)
        class _FakeTicker:
            def set_filter(self, signal):
                pass

            def screener_view(self, **kw):
                return []  # 빈 list → if 블록 skip

        import sys

        fake_mod = type(sys)("finvizfinance.screener.ticker")
        fake_mod.Ticker = _FakeTicker
        # finvizfinance 모듈 트리 stub
        monkeypatch.setitem(sys.modules, "finvizfinance.screener.ticker", fake_mod)

        c = FINVIZCollector()
        scrape_called = []
        monkeypatch.setattr(c, "_scrape_signal_fallback", lambda s: scrape_called.append(s) or set())
        result = c._fetch_signal_tickers("Oversold")
        assert scrape_called == ["Oversold"]
        assert result == set()

    def test_scrape_skips_non_quote_links(self, monkeypatch):
        """133→131: href 에 quote.ashx 미포함 → 다음 link iter."""
        import requests

        from nuri.collectors.finviz import FINVIZCollector

        # quote.ashx 없는 링크만 있는 HTML
        fake_html = '<a href="/news.ashx">News</a><a href="/about">About</a>'
        fake_resp = type("R", (), {"text": fake_html, "raise_for_status": lambda self: None, "status_code": 200})()
        monkeypatch.setattr(requests, "get", lambda *a, **kw: fake_resp)

        c = FINVIZCollector()
        result = c._scrape_signal_fallback("Oversold")
        assert result == set()

    def test_scrape_skips_invalid_ticker_text(self, monkeypatch):
        """135→131: ticker 가 non-alpha or len>5 → 다음 iter."""
        import requests

        from nuri.collectors.finviz import FINVIZCollector

        # quote.ashx 링크는 있지만 텍스트가 invalid (숫자 / 너무 김)
        fake_html = (
            '<a href="/quote.ashx?t=AAA">123</a>'  # non-alpha
            '<a href="/quote.ashx?t=BBB">VERYLONGTICKER</a>'  # len > 5
            '<a href="/quote.ashx?t=CCC"></a>'  # 빈 텍스트
        )
        fake_resp = type("R", (), {"text": fake_html, "raise_for_status": lambda self: None, "status_code": 200})()
        monkeypatch.setattr(requests, "get", lambda *a, **kw: fake_resp)

        c = FINVIZCollector()
        result = c._scrape_signal_fallback("Oversold")
        assert result == set()  # 모두 invalid → empty


class TestAllSignalsFailedIsAFailure:
    """시그널이 전부 실패하면 빈 목록이 아니라 수집 실패다 (#1724).

    빈 목록은 collector_runs 에 finished·0행으로 남아 실패율 점검이 못 본다 — 2026-08-17 부터
    50일간 운영이 그 상태였다(#1723: finvizfinance 파싱 실패 + 대체 경로 403).
    """

    def _collector(self, monkeypatch, fetch):
        from nuri.collectors.finviz import FINVIZCollector

        collector = FINVIZCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["AAPL"])
        monkeypatch.setattr(collector, "_fetch_signal_tickers", fetch)
        return collector

    def test_every_signal_failing_raises(self, monkeypatch):
        import pytest

        from nuri.collectors.base import CollectionFailureError

        def boom(signal):
            raise RuntimeError("403")

        with pytest.raises(CollectionFailureError, match="전부 실패"):
            self._collector(monkeypatch, boom).collect()

    def test_partial_failure_still_returns_what_arrived(self, monkeypatch):
        from nuri.collectors.finviz import FINVIZ_SIGNALS

        first = next(iter(FINVIZ_SIGNALS.values()))

        def some(signal):
            if signal != first:
                raise RuntimeError("403")
            return {"AAPL"}

        records = self._collector(monkeypatch, some).collect()
        assert [r["ticker"] for r in records] == ["AAPL"]

    def test_no_match_with_working_signals_is_still_an_empty_success(self, monkeypatch):
        """보유 종목이 어느 시그널에도 없으면 0건은 정상이다 — 실패와 구분해야 한다."""
        assert self._collector(monkeypatch, lambda signal: {"ZZZZ"}).collect() == []

    def test_run_records_the_failure_without_retrying(self, monkeypatch):
        """`run()` 은 CollectionFailureError 를 재시도 없이 올린다 — 막힌 사이트를 세 번 더 두드리지 않는다."""
        import pytest

        from nuri.collectors.base import CollectionFailureError

        calls = []

        def boom(signal):
            calls.append(signal)
            raise RuntimeError("403")

        collector = self._collector(monkeypatch, boom)
        with pytest.raises(CollectionFailureError):
            collector.run()
        from nuri.collectors.finviz import FINVIZ_SIGNALS

        assert len(calls) == len(FINVIZ_SIGNALS)

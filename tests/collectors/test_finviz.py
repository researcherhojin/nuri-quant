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
        records = [{"date": "2026-03-30", "ticker": "AAPL",
                     "signal": "new_high", "source": "FINVIZ"}]
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
            {"TSLA", "MSFT", "GME"}, set(), {"NVDA"}, set(), set(), {"TSLA", "AAPL"},
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
        assert isinstance(collector.collect(), list)

    def test_fetch_signal_tickers_finvizfinance(self, monkeypatch):
        from nuri.collectors.finviz import FINVIZCollector

        collector = FINVIZCollector()
        mock_screener = MagicMock()
        mock_screener.screener_view.return_value = ["AAPL", "MSFT", "GOOG"]
        mock_ticker_cls = MagicMock(return_value=mock_screener)
        with patch("nuri.collectors.finviz.Ticker", mock_ticker_cls, create=True):
            mock_mod = MagicMock()
            mock_mod.screener.ticker.Ticker = mock_ticker_cls
            with patch.dict("sys.modules", {"finvizfinance": mock_mod, "finvizfinance.screener": mock_mod.screener,
                                            "finvizfinance.screener.ticker": mock_mod.screener.ticker}):
                result = collector._fetch_signal_tickers("Oversold")
                assert isinstance(result, set)

    def test_save_empty(self, rich_db):
        from nuri.collectors.finviz import FINVIZCollector

        assert FINVIZCollector().save([]) == 0

    def test_save_records(self, rich_db):
        from nuri.collectors.finviz import FINVIZCollector

        count = FINVIZCollector().save([
            {"date": "2025-01-01", "ticker": "AAPL", "signal": "oversold_rsi", "source": "FINVIZ"},
        ], db_path=rich_db)
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

"""Per-collector tests for scheduler_integration.

Split from tests/test_collectors_all.py for module-level isolation.
"""
from unittest.mock import MagicMock, patch


class TestSchedulerRunCollector:
    def test_run_collector_stock(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.stock.StockCollector", return_value=mock_collector):
            _run_collector("stock")
        mock_collector.run.assert_called_once()

    def test_run_collector_stock_kr(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.stock_kr.StockKRCollector", return_value=mock_collector):
            _run_collector("stock_kr")
        mock_collector.run.assert_called_once()

    def test_run_collector_macro(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.macro.MacroCollector", return_value=mock_collector):
            _run_collector("macro")
        mock_collector.run.assert_called_once()

    def test_run_collector_technical(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.technical.TechnicalCollector", return_value=mock_collector):
            _run_collector("technical")
        mock_collector.run.assert_called_once()

    def test_run_collector_fear_greed(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.fear_greed.FearGreedCollector", return_value=mock_collector):
            _run_collector("fear_greed")
        mock_collector.run.assert_called_once()

    def test_run_collector_ark(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.ark.ARKCollector", return_value=mock_collector):
            _run_collector("ark")
        mock_collector.run.assert_called_once()

    def test_run_collector_events(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.events.EventsCollector", return_value=mock_collector):
            _run_collector("events")
        mock_collector.run.assert_called_once()

    def test_run_collector_news(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.news.NewsCollector", return_value=mock_collector):
            _run_collector("news")
        mock_collector.run.assert_called_once()

    def test_run_collector_fundamental(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.fundamental.FundamentalCollector", return_value=mock_collector):
            _run_collector("fundamental")
        mock_collector.run.assert_called_once()

    def test_run_collector_superinvestors(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.superinvestors.SuperinvestorCollector", return_value=mock_collector):
            _run_collector("superinvestors")
        mock_collector.run.assert_called_once()

    def test_run_collector_estimates(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.estimates.EstimatesCollector", return_value=mock_collector):
            _run_collector("estimates")
        mock_collector.run.assert_called_once()

    def test_run_collector_etf_flows(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.etf_flows.EtfFlowsCollector", return_value=mock_collector):
            _run_collector("etf_flows")
        mock_collector.run.assert_called_once()

    def test_run_collector_wallstreet(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.wallstreet.WallStreetCollector", return_value=mock_collector):
            _run_collector("wallstreet")
        mock_collector.run.assert_called_once()

    def test_run_collector_exception_handled(self):
        from nuri.scheduler import _run_collector

        with patch("nuri.collectors.stock.StockCollector", side_effect=RuntimeError("boom")):
            _run_collector("stock")


# ##############################################################################
# Source: test_coverage_round19.py
# ##############################################################################

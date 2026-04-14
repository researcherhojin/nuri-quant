"""Per-collector tests for stock.

Split from tests/test_collectors_all.py for module-level isolation.
"""

from unittest.mock import MagicMock

import pandas as pd

from nuri.core.db import (
    init_db,
)


class TestStockCollector:
    def test_period_to_start_date(self):
        from nuri.collectors.stock import StockCollector

        c = StockCollector()
        result = c._period_to_start_date("5d")
        assert len(result) == 10
        assert "-" in result


class TestStockCollectorTickerCollection:
    def test_collect_ticker_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-15"]),
                "open": [190.0],
                "high": [195.0],
                "low": [189.0],
                "close": [194.0],
                "volume": [50000000],
                "adj_close": [194.0],
            }
        )
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        df = StockCollector()._collect_ticker("AAPL", "2025-01-01", "2025-01-30")
        assert df is not None and not df.empty

    def test_collect_ticker_empty(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame()
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert StockCollector()._collect_ticker("AAPL", "2025-01-01", "2025-01-30") is None

    def test_collect_ticker_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_obb = MagicMock()
        mock_obb.equity.price.historical.side_effect = Exception("provider error")
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert StockCollector()._collect_ticker("AAPL", "2025-01-01", "2025-01-30") is None

    def test_collect_ticker_no_adj_close(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-15"]),
                "open": [190.0],
                "high": [195.0],
                "low": [189.0],
                "close": [194.0],
                "volume": [50000000],
            }
        )
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        df = StockCollector()._collect_ticker("AAPL", "2025-01-01", "2025-01-30")
        assert df is not None and "adj_close" in df.columns

    def test_collect_no_tickers(self, monkeypatch, tmp_path):
        import nuri.core.db as db_mod
        from nuri.collectors.stock import StockCollector

        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        assert StockCollector().collect(period="5d").empty

    def test_period_to_start_date(self):
        from nuri.collectors.stock import StockCollector

        result = StockCollector._period_to_start_date("1mo")
        assert len(result) == 10

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        assert StockCollector().save(pd.DataFrame()) == 0


class TestStockCollectorEdgeCases:
    def test_collect_full_flow(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-15"]),
                "open": [190.0],
                "high": [195.0],
                "low": [189.0],
                "close": [194.0],
                "volume": [50000000],
                "adj_close": [194.0],
            }
        )
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert not StockCollector().collect(period="5d").empty


class TestStockUniverseModeCoverage:
    """#272 Phase 2b: tqdm + summary 패치 커버리지."""

    def test_collect_universe_summary_logged(self, monkeypatch, db_with_portfolio, caplog):
        """20+ tickers + universe 모드: summary 로그 fire."""
        import logging

        from nuri.collectors.stock import StockCollector

        c = StockCollector()
        # 25개 ticker, 모두 데이터 부족
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: [f"T{i}" for i in range(25)])
        monkeypatch.setattr(c, "_collect_ticker", lambda *a, **kw: None)

        with caplog.at_level(logging.INFO):
            c.collect(source="universe", period="5d")

        summary = [r for r in caplog.records if "수집 결과:" in r.message]
        assert len(summary) >= 1, "Expected summary log for 25-ticker universe"

    def test_collect_universe_source_in_log(self, monkeypatch, db_with_portfolio, caplog):
        """수집 대상 메시지에 source 표시."""
        import logging

        from nuri.collectors.stock import StockCollector

        c = StockCollector()
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: ["A"])
        monkeypatch.setattr(c, "_collect_ticker", lambda *a, **kw: None)

        with caplog.at_level(logging.INFO):
            c.collect(source="universe", period="5d")

        info = [r for r in caplog.records if "source=universe" in r.message]
        assert len(info) >= 1


class TestStockOneYearBackfill:
    """#272 후속: `make collect-universe-1y` — P1 A (tech analysis) 선행 조건.

    1y = 252 trading days (chart_analysis.LOOKBACK_52W 와 정확히 일치).
    chart_analysis.analyze_chart lookback_days=365 default 과 맞춤.
    """

    def test_period_1y_maps_to_365_days_ago(self):
        """_period_to_start_date('1y') → 365일 전 (±1일 허용, 월말 경계)."""
        from datetime import datetime, timedelta

        from nuri.collectors.stock import StockCollector
        from nuri.core.timezone import kst_now

        c = StockCollector()
        start = c._period_to_start_date("1y")
        parsed = datetime.strptime(start, "%Y-%m-%d")
        now = kst_now().replace(tzinfo=None)
        delta = (now - parsed).days
        # mapping["1y"] = 365. ±2일 tolerance (timezone 경계 + 반올림).
        assert 363 <= delta <= 367, f"1y should map to ~365 days, got {delta}"

    def test_collect_1y_universe_logs_period(self, monkeypatch, db_with_portfolio, caplog):
        """collect(period='1y', source='universe') — 1y 로그 + universe source 모두 기록."""
        import logging

        from nuri.collectors.stock import StockCollector

        c = StockCollector()
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: ["SPY"])
        monkeypatch.setattr(c, "_collect_ticker", lambda *a, **kw: None)

        with caplog.at_level(logging.INFO):
            c.collect(source="universe", period="1y")

        # "수집 대상: ... (1y, source=universe)" 단일 메시지
        hits = [r for r in caplog.records if "1y" in r.message and "source=universe" in r.message]
        assert len(hits) >= 1, (
            f"Expected log with both '1y' and 'source=universe'. "
            f"Got: {[r.message for r in caplog.records if '수집' in r.message]}"
        )

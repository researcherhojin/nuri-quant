"""Per-collector tests for macro.

Split from tests/test_collectors_all.py for module-level isolation.
"""
from unittest.mock import MagicMock

import pandas as pd


class TestMacroCollector:
    def test_instantiate(self):
        from nuri.collectors.macro import MacroCollector

        c = MacroCollector()
        assert c.name == "macro"

    def test_save_empty(self, db_path):
        from nuri.collectors.macro import MacroCollector

        c = MacroCollector()
        assert c.save([]) == 0

    def test_save_records(self, db_path):
        from nuri.collectors.macro import MacroCollector

        c = MacroCollector()
        records = [
            {"indicator": "vix", "date": "2026-03-30", "value": 25.5, "source": "test"},
            {"indicator": "fear_greed", "date": "2026-03-30", "value": 45.0, "source": "test"},
        ]
        count = c.save(records)
        assert count == 2



class TestMacroCollectorFREDAndYFinance:
    def test_collect_fred(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_series = pd.Series([4.5, 4.3], index=pd.to_datetime(["2025-01-15", "2025-01-16"]))
        mock_fred = MagicMock()
        mock_fred.get_series.return_value = mock_series
        import sys

        monkeypatch.setitem(sys.modules, "fredapi", MagicMock(Fred=MagicMock(return_value=mock_fred)))
        collector = MacroCollector()
        collector.api_key = "test_fred_key"
        results = collector._collect_fred(days=30)
        assert len(results) > 0

    def test_collect_fred_series_failure(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_fred = MagicMock()
        mock_fred.get_series.side_effect = Exception("FRED API error")
        import sys

        monkeypatch.setitem(sys.modules, "fredapi", MagicMock(Fred=MagicMock(return_value=mock_fred)))
        collector = MacroCollector()
        collector.api_key = "test_key"
        assert collector._collect_fred(days=30) == []

    def test_collect_yfinance_fallback(self, monkeypatch, db_with_portfolio):
        import yfinance as yf

        from nuri.collectors.macro import MacroCollector

        mock_df = pd.DataFrame({
            "Date": pd.to_datetime(["2025-01-15"]),
            "Close": [4.5], "Open": [4.4], "High": [4.6], "Low": [4.3], "Volume": [0],
        })
        monkeypatch.setattr(yf, "download", lambda *a, **kw: mock_df)
        collector = MacroCollector()
        collector.api_key = ""
        assert len(collector._collect_yfinance(days=30)) > 0

    def test_collect_yfinance_empty_df(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_result = MagicMock()
        mock_result.to_df.return_value = pd.DataFrame()
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert MacroCollector()._collect_yfinance(days=30) == []

    def test_collect_yfinance_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_obb = MagicMock()
        mock_obb.equity.price.historical.side_effect = Exception("connection error")
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert MacroCollector()._collect_yfinance(days=30) == []

    def test_collect_prefers_fred(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_series = pd.Series([4.5], index=pd.to_datetime(["2025-01-15"]))
        mock_fred = MagicMock()
        mock_fred.get_series.return_value = mock_series
        import sys

        monkeypatch.setitem(sys.modules, "fredapi", MagicMock(Fred=MagicMock(return_value=mock_fred)))
        collector = MacroCollector()
        collector.api_key = "real_key"
        results = collector.collect(days=30)
        assert all(r["source"] == "FRED" for r in results)

    def test_collect_nan_value_skipped(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_df = pd.DataFrame({"date": pd.to_datetime(["2025-01-15", "2025-01-16"]), "close": [float("nan"), 4.3]})
        mock_result = MagicMock()
        mock_result.to_df.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        results = MacroCollector()._collect_yfinance(days=30)
        for r in results:
            assert not pd.isna(r["value"])

    def test_save(self, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        assert MacroCollector().save([{"indicator": "vix", "date": "2025-01-30", "value": 18.5, "source": "test"}]) == 1



class TestMacroCollectorEdgeCases:
    def test_collect_uses_yfinance_when_no_fred_key(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_df = pd.DataFrame({"date": pd.to_datetime(["2025-01-15"]), "close": [4.5]})
        mock_result = MagicMock()
        mock_result.to_df.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        collector = MacroCollector()
        collector.api_key = ""
        assert isinstance(collector.collect(days=30), list)

    def test_collect_fred_returns_empty_falls_to_yfinance(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_fred = MagicMock()
        mock_fred.get_series.return_value = pd.Series(dtype=float)
        import sys

        monkeypatch.setitem(sys.modules, "fredapi", MagicMock(Fred=MagicMock(return_value=mock_fred)))
        mock_df = pd.DataFrame({"date": pd.to_datetime(["2025-01-15"]), "close": [4.5]})
        mock_result = MagicMock()
        mock_result.to_df.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        collector = MacroCollector()
        collector.api_key = "real_key"
        assert isinstance(collector.collect(days=30), list)

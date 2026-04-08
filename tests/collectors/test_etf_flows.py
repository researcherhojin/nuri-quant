"""Per-collector tests for etf_flows.

Split from tests/test_collectors_all.py for module-level isolation.
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from nuri.collectors.base import MAX_FAILURE_RATE, BaseCollector, CollectionFailureError
from nuri.core.db import (
    get_db,
    init_db,
    query,
    upsert_macro,
    upsert_portfolio,
    upsert_prices,
)


class TestEtfFlowsCollector:
    def test_instantiate(self):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        c = EtfFlowsCollector()
        assert c.name == "etf_flows"

    def test_save_records(self, db_path):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        c = EtfFlowsCollector()
        records = [{"ticker": "SPY", "date": "2026-03-30", "name": "SPDR S&P 500",
                     "total_assets": 500e9, "volume_avg": 80000000,
                     "nav_price": 520.0}]
        count = c.save(records)
        assert count == 1



class TestEtfFlowsDeep:
    def test_collect_with_obb_mock(self, rich_db):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        c = EtfFlowsCollector()
        with patch.object(c, "collect", return_value=[
            {"ticker": "SPY", "date": "2026-03-30", "name": "SPDR S&P 500",
             "total_assets": 500e9, "volume_avg": 80000000, "nav_price": 520.0},
        ]):
            data = c.collect()
            count = c.save(data)
        assert count == 1

    def test_analyze_sector_rotation(self, rich_db):
        from nuri.collectors.etf_flows import analyze_sector_rotation

        result = analyze_sector_rotation(days=30)
        assert result is None or isinstance(result, pd.DataFrame)



class TestEtfFlowsFull:
    def test_collect_mock(self, rich_db):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        c = EtfFlowsCollector()
        with patch.object(c, "collect", return_value=[
            {"ticker": "SPY", "date": "2026-03-30", "name": "SPDR S&P 500",
             "total_assets": 500e9, "volume_avg": 80000000, "nav_price": 520},
        ]):
            result = c.collect()
            count = c.save(result)
        assert count == 1


# ##############################################################################
# Source: test_coverage_round11.py
# ##############################################################################



class TestEtfFlowsCollectorSectorRotation:
    def test_collect_success(self, rich_db):
        from nuri.collectors.etf_flows import _upsert_etf_flows

        records = [{"ticker": "XLK", "date": "2025-03-15", "name": "Technology Select SPDR",
                     "total_assets": 50e9, "volume_avg": 10000000.0, "nav_price": 200.0}]
        count = _upsert_etf_flows(records, db_path=rich_db)
        assert count == 1

    def test_upsert_etf_flows_empty(self, rich_db):
        from nuri.collectors.etf_flows import _upsert_etf_flows

        assert _upsert_etf_flows([], db_path=rich_db) == 0

    def test_save_empty(self, rich_db):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        c = EtfFlowsCollector()
        assert c.save([]) == 0
        assert c.save(None) == 0

    def test_analyze_sector_rotation_with_data(self, rich_db):
        from nuri.collectors.etf_flows import _upsert_etf_flows, analyze_sector_rotation

        records = []
        for d in ["2025-03-01", "2025-03-08", "2025-03-15", "2025-03-22"]:
            for ticker, aum in [("XLK", 50e9 + int(d[-2:]) * 1e8), ("XLF", 30e9 + int(d[-2:]) * 5e7)]:
                records.append({"ticker": ticker, "date": d, "name": f"Test {ticker}",
                                "total_assets": aum, "volume_avg": 10000000.0, "nav_price": 200.0})
        _upsert_etf_flows(records, db_path=rich_db)
        df = analyze_sector_rotation(db_path=rich_db)
        assert df is not None
        assert not df.empty

    def test_analyze_sector_rotation_insufficient_data(self, rich_db):
        from nuri.collectors.etf_flows import analyze_sector_rotation

        result = analyze_sector_rotation(db_path=rich_db)
        assert result is None

    def test_analyze_sector_rotation_single_day(self, rich_db):
        from nuri.collectors.etf_flows import _upsert_etf_flows, analyze_sector_rotation

        _upsert_etf_flows([{"ticker": "XLK", "date": "2025-03-15", "name": "Technology",
                            "total_assets": 50e9, "volume_avg": 10000000.0, "nav_price": 200.0}],
                          db_path=rich_db)
        result = analyze_sector_rotation(db_path=rich_db)
        assert result is None

    def test_print_sector_rotation_none(self, capsys):
        from nuri.collectors.etf_flows import print_sector_rotation

        print_sector_rotation(None)
        out = capsys.readouterr().out
        assert "없음" in out

    def test_print_sector_rotation_with_data(self, capsys):
        from nuri.collectors.etf_flows import print_sector_rotation

        df = pd.DataFrame([{"ticker": "XLK", "sector": "Technology", "aum_current": 50e9,
                            "aum_prev": 48e9, "aum_change_pct": 4.17, "volume_trend_pct": 2.5}])
        print_sector_rotation(df)
        out = capsys.readouterr().out
        assert "XLK" in out



class TestEtfFlowsCollectorErrorHandling:
    def test_collect_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        mock_df = pd.DataFrame([{"name": "Tech", "total_assets": 50e9, "volume_avg": 20000000, "nav_price": 200.0}])
        mock_obb = MagicMock()
        mock_obb.etf.info.return_value = MagicMock(to_df=MagicMock(return_value=mock_df))
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        results = EtfFlowsCollector().collect()
        assert len(results) > 0

    def test_collect_empty(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        mock_obb = MagicMock()
        mock_obb.etf.info.return_value = MagicMock(to_df=MagicMock(return_value=pd.DataFrame()))
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert EtfFlowsCollector().collect() == []

    def test_collect_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        mock_obb = MagicMock()
        mock_obb.etf.info.side_effect = Exception("ETF API error")
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert EtfFlowsCollector().collect() == []

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        c = EtfFlowsCollector()
        assert c.save([]) == 0
        assert c.save(None) == 0

    def test_analyze_sector_rotation_no_data(self, db_with_portfolio):
        from nuri.collectors.etf_flows import analyze_sector_rotation

        assert analyze_sector_rotation(db_path=db_with_portfolio) is None

    def test_analyze_sector_rotation_with_data(self, db_with_portfolio):
        from nuri.collectors.etf_flows import _upsert_etf_flows, analyze_sector_rotation

        records = []
        for ticker in ["XLK", "XLF"]:
            for d in ["2025-01-15", "2025-01-30"]:
                records.append({"ticker": ticker, "date": d, "name": f"{ticker} ETF",
                                "total_assets": 50e9, "volume_avg": 20000000, "nav_price": 200.0})
        _upsert_etf_flows(records, db_path=db_with_portfolio)
        assert analyze_sector_rotation(db_path=db_with_portfolio) is not None

    def test_analyze_sector_rotation_with_volume_trend(self, db_with_portfolio):
        from nuri.collectors.etf_flows import _upsert_etf_flows, analyze_sector_rotation

        records = [{"ticker": "XLK", "date": f"2025-01-{d:02d}", "name": "Tech",
                     "total_assets": 50e9 + d * 1e9, "volume_avg": 20000000 + d * 1000000, "nav_price": 200 + d}
                   for d in range(1, 9)]
        _upsert_etf_flows(records, db_path=db_with_portfolio)
        assert analyze_sector_rotation(db_path=db_with_portfolio) is not None

    def test_print_sector_rotation_none(self, capsys):
        from nuri.collectors.etf_flows import print_sector_rotation

        print_sector_rotation(None)
        assert "데이터 없음" in capsys.readouterr().out

    def test_print_sector_rotation_with_data(self, capsys):
        from nuri.collectors.etf_flows import print_sector_rotation

        df = pd.DataFrame([{"ticker": "XLK", "sector": "Technology", "aum_current": 50e9,
                            "aum_prev": 48e9, "aum_change_pct": 4.17, "volume_trend_pct": 10.0}])
        print_sector_rotation(df)
        assert "XLK" in capsys.readouterr().out



class TestEtfFlowsNanValues:
    def test_collect_nan_assets(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        mock_df = pd.DataFrame([{"name": "Test ETF", "total_assets": float("nan"), "volume_avg": float("nan"), "nav_price": float("nan")}])
        mock_obb = MagicMock()
        mock_obb.etf.info.return_value = MagicMock(to_df=MagicMock(return_value=mock_df))
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        results = EtfFlowsCollector().collect()
        assert len(results) > 0
        assert results[0]["total_assets"] is None


# ##############################################################################
# Source: test_uncovered.py
# ##############################################################################

"""Per-collector tests for etf_flows.

Split from tests/test_collectors_all.py for module-level isolation.
"""
from unittest.mock import MagicMock, patch

import pandas as pd


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


class TestEtfFlowsYfinanceFallback:
    """yfinance Ticker.info 폴백 경로 (#274) regression lock-in.

    - total_assets 누락 시 failed 처리 (analyze_sector_rotation TypeError 방지)
    - NaN primary + usable secondary → pd.notna 기반 secondary 선택
    """

    def _patch_openbb_fail(self, monkeypatch):
        """OpenBB primary 를 무조건 실패시켜 yfinance fallback 유도."""
        import sys

        mock_obb = MagicMock()
        mock_obb.etf.info.side_effect = ImportError("OBBject_EtfCountries not found")
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

    def test_yfinance_fallback_full_fields(self, monkeypatch):
        """yfinance .info 에 모든 필드 정상 — 변환 후 dict 반환."""
        import sys

        from nuri.collectors.etf_flows import EtfFlowsCollector

        self._patch_openbb_fail(monkeypatch)

        info = {
            "longName": "SPDR S&P 500 ETF Trust",
            "totalAssets": 650_000_000_000,
            "averageVolume": 80_000_000,
            "navPrice": 700.12,
        }
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value.info = info
        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

        rec = EtfFlowsCollector()._fetch_etf("SPY", "S&P 500", "2026-04-17")
        assert rec is not None
        assert rec["ticker"] == "SPY"
        assert rec["name"] == "SPDR S&P 500 ETF Trust"
        assert rec["total_assets"] == 650_000_000_000
        assert rec["volume_avg"] == 80_000_000
        assert rec["nav_price"] == 700.12

    def test_yfinance_fallback_rejects_missing_total_assets(self, monkeypatch):
        """totalAssets 없으면 None 반환 (failed 처리).

        downstream analyze_sector_rotation() 이 `aum_current - aum_prev` 를 수행 →
        partial None 이 섞이면 TypeError → 분석 전체 crash.
        """
        import sys

        from nuri.collectors.etf_flows import EtfFlowsCollector

        self._patch_openbb_fail(monkeypatch)

        # 1) totalAssets 자체 누락
        info_missing = {"longName": "X", "averageVolume": 100, "navPrice": 50}
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value.info = info_missing
        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)
        assert EtfFlowsCollector()._fetch_etf("XX", "X", "2026-04-17") is None

        # 2) totalAssets 가 NaN
        info_nan = {"longName": "Y", "totalAssets": float("nan"), "averageVolume": 100, "navPrice": 50}
        mock_yf.Ticker.return_value.info = info_nan
        assert EtfFlowsCollector()._fetch_etf("YY", "Y", "2026-04-17") is None

    def test_yfinance_fallback_secondary_when_primary_is_nan(self, monkeypatch):
        """averageVolume 이 NaN 이면 averageVolume10days 로 fallback.

        `a or b` 는 NaN 을 truthy 로 취급 → pd.notna 기반 명시적 선택 필요.
        """
        import sys

        from nuri.collectors.etf_flows import EtfFlowsCollector

        self._patch_openbb_fail(monkeypatch)

        info = {
            "longName": "Partial ETF",
            "totalAssets": 100_000_000,
            "averageVolume": float("nan"),        # primary NaN
            "averageVolume10days": 5_000_000,     # secondary usable
            "navPrice": float("nan"),             # primary NaN
            "regularMarketPrice": 55.0,           # secondary usable
        }
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value.info = info
        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

        rec = EtfFlowsCollector()._fetch_etf("PP", "Partial", "2026-04-17")
        assert rec is not None
        assert rec["volume_avg"] == 5_000_000, "secondary averageVolume10days must be picked when primary is NaN"
        assert rec["nav_price"] == 55.0, "secondary regularMarketPrice must be picked when navPrice is NaN"

    def test_yfinance_fallback_all_secondary_missing(self, monkeypatch):
        """primary NaN + secondary 도 missing → volume_avg/nav_price 는 None (total_assets 있으면 row 유지)."""
        import sys

        from nuri.collectors.etf_flows import EtfFlowsCollector

        self._patch_openbb_fail(monkeypatch)

        info = {
            "totalAssets": 1_000_000,
            "averageVolume": float("nan"),
            "navPrice": float("nan"),
            # no secondary
        }
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value.info = info
        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

        rec = EtfFlowsCollector()._fetch_etf("QQ", "Q", "2026-04-17")
        assert rec is not None
        assert rec["total_assets"] == 1_000_000
        assert rec["volume_avg"] is None
        assert rec["nav_price"] is None


# ##############################################################################
# Source: test_uncovered.py
# ##############################################################################

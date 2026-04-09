"""Tests for nuri.analysis.sector — split from tests/test_analysis_all.py (#157)."""
from unittest.mock import patch

import pandas as pd


class TestSectorAnalysis:
    """From test_analysis.py."""
    def test_sector_weights_sum_100(self, populated_db):
        from nuri.analysis.sector import analyze_sector
        sector_df, _, _ = analyze_sector()
        assert not sector_df.empty
        assert abs(sector_df["weight_pct"].sum() - 100.0) < 0.5


class TestSectorAnalysis_Extra:
    """From test_coverage_extra.py."""
    def test_analyze_empty(self, db_path):
        from nuri.analysis.sector import analyze_sector
        result = analyze_sector()
        assert isinstance(result, tuple)


class TestSector:
    """From test_coverage_round2.py."""
    def test_analyze_sector(self, db_path):
        from nuri.analysis.sector import analyze_sector
        with patch("nuri.analysis.sector.get_exchange_rate", return_value=1400.0):
            sector_df, region_df, warnings = analyze_sector()
        assert isinstance(sector_df, pd.DataFrame)
        assert isinstance(region_df, pd.DataFrame)
        assert isinstance(warnings, list)


class TestAnalyzeSector:
    """From test_coverage_round22.py."""
    def test_empty_holdings(self, db_path, monkeypatch):
        from nuri.analysis import sector as mod
        monkeypatch.setattr(mod, "query_df", lambda sql, **kw: pd.DataFrame())
        s, r, w = mod.analyze_sector()
        assert s.empty and r.empty and w == []

    def test_no_prices(self, db_path, monkeypatch):
        from nuri.analysis import sector as mod
        holdings = pd.DataFrame({
            "ticker": ["AAPL"],
            "total_qty": [10],
            "sector": ["Tech"],
            "currency": ["USD"],
        })
        monkeypatch.setattr(mod, "query_df", lambda sql, **kw: holdings)
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: [])
        monkeypatch.setattr(mod, "get_exchange_rate", lambda: 1350.0)
        s, r, w = mod.analyze_sector()
        assert s.empty

    def test_with_data(self, db_path, _seed_prices_r22, _seed_portfolio_r22, monkeypatch):
        from nuri.analysis import sector as mod
        from nuri.core.db import query as real_query
        from nuri.core.db import query_df as real_query_df
        monkeypatch.setattr(mod, "query_df", lambda sql, **kw: real_query_df(sql, db_path=db_path))
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: real_query(sql, *a, db_path=db_path, **kw))
        monkeypatch.setattr(mod, "get_exchange_rate", lambda: 1350.0)
        s, r, w = mod.analyze_sector()
        assert not s.empty
        assert not r.empty


class TestPrintSector:
    """From test_coverage_round22.py."""
    def test_print_with_warnings(self, capsys):
        from nuri.analysis.sector import print_sector
        sector_df = pd.DataFrame({
            "sector": ["Technology", "Energy"],
            "current_value": [50000, 20000],
            "weight_pct": [50.0, 20.0],
        })
        region_df = pd.DataFrame({
            "region": ["US", "KR"],
            "current_value": [60000, 10000],
            "weight_pct": [85.7, 14.3],
        })
        warnings = ["warning: Technology: 50.0% > 35% limit"]
        print_sector(sector_df, region_df, warnings)
        out = capsys.readouterr().out
        assert "섹터 노출도" in out
        assert "지역 노출도" in out
        assert "Technology" in out

    def test_print_no_warnings(self, capsys):
        from nuri.analysis.sector import print_sector
        sector_df = pd.DataFrame({
            "sector": ["Technology"],
            "current_value": [10000],
            "weight_pct": [30.0],
        })
        region_df = pd.DataFrame({
            "region": ["US"],
            "current_value": [10000],
            "weight_pct": [100.0],
        })
        print_sector(sector_df, region_df, [])
        out = capsys.readouterr().out
        assert "Technology" in out


class TestSectorKR:
    """From test_coverage_round22.py."""
    def test_kr_ticker(self, db_path, monkeypatch):
        from nuri.analysis import sector as mod
        holdings = pd.DataFrame({
            "ticker": ["005930.KS"],
            "total_qty": [100],
            "sector": ["Technology"],
            "currency": ["KRW"],
        })
        monkeypatch.setattr(mod, "query_df", lambda sql, **kw: holdings)
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: [{"close": 70000}])
        monkeypatch.setattr(mod, "get_exchange_rate", lambda: 1350.0)
        s, r, w = mod.analyze_sector()
        assert not r.empty
        kr_rows = r[r["region"] == "KR"]
        assert len(kr_rows) == 1

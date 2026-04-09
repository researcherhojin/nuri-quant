"""Tests for nuri.analysis.correlation — split from tests/test_analysis_all.py (#157)."""
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from nuri.core.db import query_df


class TestCorrelation:
    """From test_uncovered.py."""
    def test_analyze_correlation(self, price_data):
        from nuri.analysis.correlation import analyze_correlation
        corr, warnings = analyze_correlation(min_days=20)
        assert isinstance(corr, pd.DataFrame)
        assert isinstance(warnings, list)
        if not corr.empty:
            assert "AAPL" in corr.columns

    def test_empty_db(self, db_path):
        from nuri.analysis.correlation import analyze_correlation
        corr, warnings = analyze_correlation()
        assert corr.empty


class TestCorrelation_Push:
    """From test_coverage_push.py."""
    def test_with_data(self, price_db):
        from nuri.analysis.correlation import analyze_correlation
        corr, warnings = analyze_correlation(min_days=20)
        assert isinstance(corr, pd.DataFrame)
        assert isinstance(warnings, list)


class TestCorrelation_R2:
    """From test_coverage_round2.py."""
    def test_analyze_with_data(self, db_path):
        from nuri.analysis.correlation import analyze_correlation
        corr, warnings = analyze_correlation(min_days=10)
        assert isinstance(corr, pd.DataFrame)
        assert isinstance(warnings, list)

    def test_print_correlation(self, capsys):
        from nuri.analysis.correlation import print_correlation
        corr = pd.DataFrame({"AAPL": [1.0, 0.9], "NVDA": [0.9, 1.0]},
                             index=["AAPL", "NVDA"])
        warnings = [{"ticker_a": "AAPL", "ticker_b": "NVDA", "correlation": 0.9}]
        print_correlation(corr, warnings)
        output = capsys.readouterr().out
        assert "AAPL" in output


class TestAnalyzeCorrelation:
    """From test_coverage_round22.py."""
    def test_less_than_2_tickers(self, db_path, monkeypatch):
        from nuri.analysis import correlation as mod
        monkeypatch.setattr(mod, "get_tickers", lambda: ["AAPL"])
        monkeypatch.setattr(mod, "query_df", lambda sql, **kw: pd.DataFrame())
        corr, warnings = mod.analyze_correlation()
        assert corr.empty
        assert warnings == []

    def test_insufficient_data(self, db_path, monkeypatch):
        from nuri.analysis import correlation as mod
        monkeypatch.setattr(mod, "get_tickers", lambda: ["AAPL", "MSFT"])
        df = pd.DataFrame({
            "ticker": ["AAPL"] * 5 + ["MSFT"] * 5,
            "date": list(pd.bdate_range("2025-01-01", periods=5).strftime("%Y-%m-%d")) * 2,
            "close": [150, 151, 152, 153, 154, 300, 301, 302, 303, 304],
        })
        monkeypatch.setattr(mod, "query_df", lambda sql, **kw: df)
        corr, warnings = mod.analyze_correlation(min_days=60)
        assert corr.empty

    def test_corr_with_data(self, db_path, _seed_prices_r22, _seed_portfolio_r22, monkeypatch):
        from nuri.analysis import correlation as mod
        from nuri.core.db import get_tickers
        monkeypatch.setattr(mod, "get_tickers", lambda: get_tickers(db_path=db_path))
        monkeypatch.setattr(mod, "query_df", lambda sql, **kw: query_df(sql, db_path=db_path))
        corr, warnings = mod.analyze_correlation(min_days=20)
        assert not corr.empty
        assert isinstance(warnings, list)

    def test_high_correlation_warning(self, monkeypatch):
        from nuri.analysis import correlation as mod
        monkeypatch.setattr(mod, "get_tickers", lambda: ["A", "B"])
        dates = pd.bdate_range("2024-01-01", periods=100).strftime("%Y-%m-%d").tolist()
        np.random.seed(0)
        closes_a = np.cumsum(np.random.randn(100)) + 100
        closes_b = closes_a + np.random.randn(100) * 0.1
        df = pd.DataFrame({
            "ticker": ["A"] * 100 + ["B"] * 100,
            "date": dates * 2,
            "close": list(closes_a) + list(closes_b),
        })
        monkeypatch.setattr(mod, "query_df", lambda sql, **kw: df)
        corr, warnings = mod.analyze_correlation(min_days=60)
        assert len(warnings) > 0
        assert warnings[0]["correlation"] > 0.80


class TestSaveHeatmap:
    """From test_coverage_round22.py."""
    def test_save_heatmap_success(self, tmp_path, monkeypatch):
        from nuri.analysis import correlation as mod
        monkeypatch.setattr(mod, "EXPORT_DIR", tmp_path)
        corr = pd.DataFrame(
            [[1.0, 0.85], [0.85, 1.0]],
            index=["AAPL", "MSFT"],
            columns=["AAPL", "MSFT"],
        )
        mod.save_heatmap(corr)
        assert (tmp_path / "correlation.png").exists()

    def test_save_heatmap_fail(self, tmp_path, monkeypatch, caplog):
        from nuri.analysis import correlation as mod
        monkeypatch.setattr(mod, "EXPORT_DIR", Path("/dev/null/impossible"))
        with caplog.at_level(logging.WARNING):
            mod.save_heatmap(pd.DataFrame(
                [[1.0, 0.5], [0.5, 1.0]],
                index=["A", "B"], columns=["A", "B"],
            ))


class TestPrintCorrelation:
    """From test_coverage_round22.py."""
    def test_empty(self, capsys):
        from nuri.analysis.correlation import print_correlation
        print_correlation(pd.DataFrame(), [])
        assert "데이터가 없습니다" in capsys.readouterr().out

    def test_with_warnings(self, capsys):
        from nuri.analysis.correlation import print_correlation
        corr = pd.DataFrame([[1.0, 0.9], [0.9, 1.0]], index=["A", "B"], columns=["A", "B"])
        warns = [{"ticker_a": "A", "ticker_b": "B", "correlation": 0.9}]
        print_correlation(corr, warns)
        out = capsys.readouterr().out
        assert "고상관 쌍" in out
        assert "A" in out

    def test_no_warnings(self, capsys):
        from nuri.analysis.correlation import print_correlation
        corr = pd.DataFrame([[1.0, 0.3], [0.3, 1.0]], index=["A", "B"], columns=["A", "B"])
        print_correlation(corr, [])
        out = capsys.readouterr().out
        assert "분산 양호" in out


class TestCorrelationMain:
    """From test_coverage_round22.py."""
    def test_main_empty(self, monkeypatch, capsys):
        from nuri.analysis import correlation as mod
        monkeypatch.setattr(mod, "get_tickers", lambda: [])
        monkeypatch.setattr(mod, "query_df", lambda sql, **kw: pd.DataFrame())
        corr, warns = mod.analyze_correlation()
        mod.print_correlation(corr, warns)
        if not corr.empty:
            mod.save_heatmap(corr)
        out = capsys.readouterr().out
        assert "데이터가 없습니다" in out

"""Tests for nuri.analysis.portfolio — split from tests/test_analysis_all.py (#157)."""
from unittest.mock import patch

import pandas as pd


class TestPortfolioAnalysis:
    """From test_analysis.py."""
    def test_analyze_returns_dataframe(self, populated_db):
        from nuri.analysis.portfolio import analyze_portfolio
        df = analyze_portfolio()
        assert not df.empty
        assert "weight_pct" in df.columns

    def test_total_weight_100(self, populated_db):
        from nuri.analysis.portfolio import analyze_portfolio
        df = analyze_portfolio()
        assert abs(df["weight_pct"].sum() - 100.0) < 0.1


class TestPortfolioAnalysis_Extra:
    """From test_coverage_extra.py."""
    def test_analyze_empty(self, db_path):
        from nuri.analysis.portfolio import analyze_portfolio
        df = analyze_portfolio()
        assert isinstance(df, pd.DataFrame)

    def test_analyze_with_data(self, market_db):
        from nuri.analysis.portfolio import analyze_portfolio
        df = analyze_portfolio()
        assert isinstance(df, pd.DataFrame)


class TestPortfolioExtended:
    """From test_coverage_push.py."""
    def test_print_summary(self, price_db, capsys):
        from nuri.analysis.portfolio import analyze_portfolio, print_summary
        df = analyze_portfolio()
        print_summary(df)
        output = capsys.readouterr().out
        assert len(output) > 0

    def test_exchange_rate(self, price_db):
        from nuri.analysis.portfolio import get_exchange_rate
        rate = get_exchange_rate()
        assert rate > 0


class TestPortfolioAnalysis_R9:
    """From test_coverage_round9.py (TestRiskAnalysis.test_portfolio_analysis)."""
    def test_portfolio_analysis(self, rich_db):
        from nuri.analysis.portfolio import analyze_portfolio
        with patch("nuri.analysis.portfolio.get_exchange_rate", return_value=1400.0):
            result = analyze_portfolio()
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0

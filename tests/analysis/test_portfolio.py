"""Tests for nuri.analysis.portfolio — split from tests/test_analysis_all.py (#157)."""

# cspell:ignore ZZZNOPRICE
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


class TestPortfolioCoverageGaps:
    """Lock-tests for portfolio.py missing lines."""

    def test_get_exchange_rate_via_openbb(self, db_path, monkeypatch):
        """No DB rate → OpenBB returns price (lines 52-58)."""
        import sys
        from unittest.mock import MagicMock

        import nuri.analysis.portfolio as port_mod

        monkeypatch.setattr(port_mod, "query", lambda *a, **kw: [])

        fake_obb = MagicMock()
        fake_result = MagicMock()
        fake_df = pd.DataFrame({"close": [1430.0, 1440.0]})
        fake_result.to_dataframe.return_value = fake_df
        fake_obb.currency.price.historical.return_value = fake_result
        fake_module = MagicMock()
        fake_module.obb = fake_obb
        monkeypatch.setitem(sys.modules, "openbb", fake_module)

        rate = port_mod.get_exchange_rate()
        assert rate == 1440.0

    def test_analyze_portfolio_no_prices(self, db_path, monkeypatch):
        """holdings 있지만 모두 가격 없음 → empty df (line 133)."""
        import nuri.analysis.portfolio as port_mod
        import nuri.core.db as db_mod
        from nuri.core.db import get_db

        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?,?,?,?,?,?)",
                ("test", "ZZZNOPRICE", 10, 100.0, "USD", "Tech"),
            )

        monkeypatch.setattr(port_mod, "get_exchange_rate", lambda: 1400.0)
        result = port_mod.analyze_portfolio()
        assert result.empty

    def test_analyze_portfolio_tsll_warning(self, db_path, monkeypatch):
        """TSLL 보유 → 레버리지 ETF 경고 (line 150)."""
        import nuri.analysis.portfolio as port_mod
        import nuri.core.db as db_mod
        from nuri.core.db import get_db

        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?,?,?,?,?,?)",
                ("test", "TSLL", 5, 10.0, "USD", "Leveraged"),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close) VALUES (?,?,?,?,?,?,?,?)",
                ("TSLL", "2026-05-01", 9.0, 11.0, 8.5, 10.5, 1000, 10.5),
            )

        monkeypatch.setattr(port_mod, "get_exchange_rate", lambda: 1400.0)
        df = port_mod.analyze_portfolio()
        assert any("TSLL" in w and "레버리지" in w for w in df.attrs.get("warnings", []))

    def test_print_summary_empty_df(self, capsys):
        """빈 df → 'no data' 메시지 (lines 162-163)."""
        import nuri.analysis.portfolio as port_mod

        port_mod.print_summary(pd.DataFrame())
        out = capsys.readouterr().out
        assert "데이터가 없습니다" in out

    def test_get_exchange_rate_openbb_failure_raises(self, db_path, monkeypatch):
        """OpenBB raise → StaleExchangeRateError (lines 59-62)."""
        import sys
        from unittest.mock import MagicMock

        import nuri.analysis.portfolio as port_mod

        monkeypatch.setattr(port_mod, "query", lambda *a, **kw: [])

        fake_obb = MagicMock()
        fake_obb.currency.price.historical.side_effect = RuntimeError("openbb down")
        fake_module = MagicMock()
        fake_module.obb = fake_obb
        monkeypatch.setitem(sys.modules, "openbb", fake_module)

        import pytest

        with pytest.raises(port_mod.StaleExchangeRateError):
            port_mod.get_exchange_rate()

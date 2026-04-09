"""Tests for nuri.analysis.performance — split from tests/test_analysis_all.py (#157)."""
from pathlib import Path

import numpy as np
import pandas as pd

from nuri.core.db import init_db


class TestPerformance:
    """From test_analysis.py."""
    def test_portfolio_returns(self, populated_db):
        from nuri.analysis.performance import get_portfolio_returns
        returns = get_portfolio_returns()
        assert len(returns) > 0


class TestPerformance_Uncovered:
    """From test_uncovered.py."""
    def test_get_portfolio_returns(self, price_data):
        from nuri.analysis.performance import get_portfolio_returns
        returns = get_portfolio_returns()
        assert isinstance(returns, pd.Series)

    def test_get_benchmark_returns_empty(self, db_path):
        from nuri.analysis.performance import get_benchmark_returns
        returns = get_benchmark_returns()
        assert isinstance(returns, pd.Series)


class TestPerformance_Push:
    """From test_coverage_push.py."""
    def test_portfolio_returns(self, price_db):
        from nuri.analysis.performance import get_portfolio_returns
        returns = get_portfolio_returns()
        assert isinstance(returns, pd.Series)

    def test_benchmark_returns(self, price_db):
        from nuri.analysis.performance import get_benchmark_returns
        returns = get_benchmark_returns()
        assert isinstance(returns, pd.Series)


class TestPerformance_R2:
    """From test_coverage_round2.py."""
    def test_get_portfolio_returns(self, db_path):
        from nuri.analysis.performance import get_portfolio_returns
        returns = get_portfolio_returns(days=30)
        assert isinstance(returns, pd.Series)

    def test_get_benchmark_returns(self, db_path):
        from nuri.analysis.performance import get_benchmark_returns
        result = get_benchmark_returns()
        assert isinstance(result, pd.Series)


class TestPerformanceReturns:
    """From test_coverage_round16.py."""
    def test_empty_portfolio(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        from nuri.analysis.performance import get_portfolio_returns
        returns = get_portfolio_returns()
        assert returns.empty

    def test_portfolio_returns_with_data(self, rich_db):
        from nuri.analysis.performance import get_portfolio_returns
        returns = get_portfolio_returns()
        assert not returns.empty
        assert returns.name == "Nuri-Quant Portfolio"

    def test_benchmark_returns(self, rich_db):
        from nuri.analysis.performance import get_benchmark_returns
        returns = get_benchmark_returns()
        assert not returns.empty
        assert returns.name == "VOO"

    def test_benchmark_returns_no_voo(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        path = tmp_path / "novoo.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        from nuri.analysis.performance import get_benchmark_returns
        returns = get_benchmark_returns()
        assert returns.empty


class TestPerformancePrint:
    """From test_coverage_round16.py."""
    def test_empty_returns(self, capsys):
        from nuri.analysis.performance import print_performance
        print_performance(pd.Series(dtype=float), pd.Series(dtype=float))
        out = capsys.readouterr().out
        assert "성과 데이터가 없습니다" in out

    def test_with_returns(self, capsys, rich_db):
        from nuri.analysis.performance import get_benchmark_returns, get_portfolio_returns, print_performance
        port = get_portfolio_returns()
        bench = get_benchmark_returns()
        print_performance(port, bench)
        out = capsys.readouterr().out
        assert "Sharpe" in out
        assert "Alpha" in out


class TestPerformanceReturns_R22:
    """From test_coverage_round22.py."""
    def test_empty_portfolio(self, db_path, monkeypatch):
        import nuri.analysis.performance as mod
        monkeypatch.setattr(mod, "query_df", lambda sql, *a, **kw: pd.DataFrame())
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: [])
        result = mod.get_portfolio_returns()
        assert result.empty

    def test_zero_total(self, db_path, monkeypatch):
        import nuri.analysis.performance as mod
        holdings = pd.DataFrame({"ticker": ["AAPL"], "total_qty": [10]})
        monkeypatch.setattr(mod, "query_df", lambda sql, *a, **kw: holdings)
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: [])
        result = mod.get_portfolio_returns()
        assert result.empty

    def test_with_data(self, db_path, _seed_prices_r22, _seed_portfolio_r22, monkeypatch):
        import nuri.analysis.performance as mod
        from nuri.core.db import query as real_query
        from nuri.core.db import query_df as real_query_df
        monkeypatch.setattr(mod, "query_df", lambda sql, *a, **kw: real_query_df(sql, db_path=db_path))
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: real_query(sql, *a, db_path=db_path, **kw))
        result = mod.get_portfolio_returns()
        assert not result.empty
        assert result.name == "Nuri-Quant Portfolio"


class TestBenchmarkReturns:
    """From test_coverage_round22.py."""
    def test_empty(self, db_path, monkeypatch):
        import nuri.analysis.performance as mod
        monkeypatch.setattr(mod, "query_df", lambda sql, *a, **kw: pd.DataFrame())
        result = mod.get_benchmark_returns()
        assert result.empty

    def test_with_voo(self, db_path, _seed_prices_r22, monkeypatch):
        import nuri.analysis.performance as mod
        from nuri.core.db import query_df as real_query_df
        monkeypatch.setattr(mod, "query_df", lambda sql, *a, **kw: real_query_df(sql, db_path=db_path))
        result = mod.get_benchmark_returns()
        assert not result.empty
        assert result.name == "VOO"


class TestPrintPerformance:
    """From test_coverage_round22.py."""
    def test_empty(self, capsys):
        from nuri.analysis.performance import print_performance
        print_performance(pd.Series(dtype=float), pd.Series(dtype=float))
        assert "데이터가 없습니다" in capsys.readouterr().out

    def test_with_data(self, capsys, monkeypatch):
        from nuri.analysis.performance import print_performance
        np.random.seed(42)
        dates = pd.bdate_range("2025-01-01", periods=60)
        port_returns = pd.Series(np.random.randn(60) * 0.01, index=dates, name="Portfolio")
        bench_returns = pd.Series(np.random.randn(60) * 0.008, index=dates, name="VOO")
        print_performance(port_returns, bench_returns)
        out = capsys.readouterr().out
        assert "성과 분석" in out
        assert "Sharpe" in out
        assert "VOO" in out

    def test_with_no_benchmark(self, capsys, monkeypatch):
        from nuri.analysis.performance import print_performance
        np.random.seed(42)
        dates = pd.bdate_range("2025-01-01", periods=60)
        port_returns = pd.Series(np.random.randn(60) * 0.01, index=dates, name="Portfolio")
        print_performance(port_returns, pd.Series(dtype=float))
        out = capsys.readouterr().out
        assert "성과 분석" in out


class TestGenerateHtmlReport:
    """From test_coverage_round22.py."""
    def test_generate(self, tmp_path, monkeypatch):
        import nuri.analysis.performance as mod
        monkeypatch.setattr(mod, "EXPORT_DIR", tmp_path)
        np.random.seed(42)
        dates = pd.bdate_range("2025-01-01", periods=60)
        port = pd.Series(np.random.randn(60) * 0.01, index=dates, name="Portfolio")
        bench = pd.Series(np.random.randn(60) * 0.008, index=dates, name="VOO")
        path = mod.generate_html_report(port, bench)
        assert Path(path).exists()

    def test_generate_no_benchmark(self, tmp_path, monkeypatch):
        import nuri.analysis.performance as mod
        monkeypatch.setattr(mod, "EXPORT_DIR", tmp_path)
        np.random.seed(42)
        dates = pd.bdate_range("2025-01-01", periods=60)
        port = pd.Series(np.random.randn(60) * 0.01, index=dates, name="Portfolio")
        path = mod.generate_html_report(port, pd.Series(dtype=float))
        assert Path(path).exists()

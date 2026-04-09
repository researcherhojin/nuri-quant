"""Tests for nuri.analysis.rebalance — split from tests/test_analysis_all.py (#157)."""
import pandas as pd


class TestAnalysisRebalance:
    """From test_coverage_push.py."""
    def test_empty_db(self, db_path):
        from nuri.analysis.rebalance import analyze_rebalance
        result = analyze_rebalance(method="rp")
        assert isinstance(result, pd.DataFrame)

    def test_with_data(self, price_db):
        from nuri.analysis.rebalance import analyze_rebalance
        result = analyze_rebalance(method="rp")
        assert isinstance(result, pd.DataFrame)

    def test_mvo_method(self, price_db):
        from nuri.analysis.rebalance import analyze_rebalance
        result = analyze_rebalance(method="mvo")
        assert isinstance(result, pd.DataFrame)


class TestRebalanceModule:
    """From test_coverage_round3.py."""
    def test_analyze_rebalance_returns_df(self, db_path):
        from nuri.analysis.rebalance import analyze_rebalance
        result = analyze_rebalance()
        assert isinstance(result, pd.DataFrame)


class TestAnalysisRebalance_Final:
    """From test_coverage_final.py."""
    def test_import(self):
        from nuri.analysis.rebalance import analyze_rebalance
        assert callable(analyze_rebalance)

    def test_empty_db(self, db_path):
        from nuri.analysis.rebalance import analyze_rebalance
        result = analyze_rebalance(method="rp")
        assert isinstance(result, pd.DataFrame)


class TestPrintRebalance:
    """From test_coverage_round22.py."""
    def test_empty(self, capsys):
        from nuri.analysis.rebalance import print_rebalance
        print_rebalance(pd.DataFrame())
        assert "데이터가 없습니다" in capsys.readouterr().out

    def test_no_actionable(self, capsys):
        from nuri.analysis.rebalance import print_rebalance
        df = pd.DataFrame([{
            "ticker": "AAPL",
            "sector": "Tech",
            "current_weight": 10.0,
            "optimal_weight": 10.0,
            "drift": 0.0,
            "trade_value_usd": 0,
            "trade_shares": 0,
            "action": "HOLD",
        }])
        df.attrs["method"] = "Mean-Variance (Max Sharpe)"
        print_rebalance(df)
        out = capsys.readouterr().out
        assert "불필요" in out

    def test_with_actions(self, capsys):
        from nuri.analysis.rebalance import print_rebalance
        df = pd.DataFrame([
            {
                "ticker": "AAPL",
                "sector": "Tech",
                "current_weight": 25.0,
                "optimal_weight": 10.0,
                "drift": 15.0,
                "trade_value_usd": -5000,
                "trade_shares": -30,
                "action": "SELL",
            },
            {
                "ticker": "MSFT",
                "sector": "Tech",
                "current_weight": 5.0,
                "optimal_weight": 15.0,
                "drift": -10.0,
                "trade_value_usd": 3000,
                "trade_shares": 10,
                "action": "BUY",
            },
        ])
        df.attrs["method"] = "Risk Parity"
        print_rebalance(df)
        out = capsys.readouterr().out
        assert "Risk Parity" in out
        assert "SELL" in out
        assert "BUY" in out


class TestAnalyzeRebalanceEmpty:
    """From test_coverage_round22.py."""
    def test_empty_portfolio(self, db_path, monkeypatch):
        import nuri.analysis.rebalance as mod
        call_count = [0]
        def mock_query_df(sql, *a, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return pd.DataFrame({
                    "ticker": ["AAPL"] * 15,
                    "date": [f"2025-01-{i:02d}" for i in range(1, 16)],
                    "close": [150 + i for i in range(15)],
                })
            return pd.DataFrame()
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: [])
        monkeypatch.setattr(mod, "query_df", mock_query_df)
        result = mod.analyze_rebalance()
        assert result.empty

    def test_insufficient_returns(self, db_path, monkeypatch):
        import nuri.analysis.rebalance as mod
        prices_df = pd.DataFrame({
            "ticker": ["AAPL", "AAPL", "AAPL"],
            "date": ["2025-01-01", "2025-01-02", "2025-01-03"],
            "close": [150, 151, 152],
        })
        def mock_query_df(sql, *a, **kw):
            if "prices" in sql:
                return prices_df
            return pd.DataFrame()
        monkeypatch.setattr(mod, "query_df", mock_query_df)
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: [])
        result = mod.analyze_rebalance()
        assert result.empty

    def test_zero_total_value(self, db_path, monkeypatch):
        import nuri.analysis.rebalance as mod
        dates = pd.bdate_range("2024-01-01", periods=20).strftime("%Y-%m-%d").tolist()
        prices_df = pd.DataFrame({
            "ticker": ["AAPL"] * 20,
            "date": dates,
            "close": [150 + i * 0.5 for i in range(20)],
        })
        holdings_df = pd.DataFrame({
            "ticker": ["AAPL"],
            "total_qty": [10],
            "sector": ["Tech"],
        })
        call_count = [0]
        def mock_query_df(sql, *a, **kw):
            call_count[0] += 1
            if "prices" in sql:
                return prices_df
            if "portfolio" in sql:
                return holdings_df
            return pd.DataFrame()
        monkeypatch.setattr(mod, "query_df", mock_query_df)
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: [])
        result = mod.analyze_rebalance()
        assert result.empty

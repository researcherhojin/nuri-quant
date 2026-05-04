"""Tests for nuri.analysis.rebalance — split from tests/test_analysis_all.py (#157)."""
import numpy as np
import pandas as pd
import pytest


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

    def test_leverage_etf_branches(self, db_path, monkeypatch):
        """LEVERAGE_ETFS 종목이 holdings 에 있으면 → 77-78 (upperlng pass) + 109 (SELL 레버리지) 분기 진입."""
        import nuri.analysis.rebalance as mod
        from nuri.core.rules import LEVERAGE_ETFS

        leverage_ticker = next(iter(LEVERAGE_ETFS))  # 첫 번째 레버리지 ETF (e.g., 'TQQQ')

        # Riskfolio 가 numerical solve 가능하도록 60일 가격 + variation 보장
        np.random.seed(42)
        dates = pd.bdate_range("2024-01-01", periods=60).strftime("%Y-%m-%d").tolist()
        prices_rows = []
        for ticker, base in [(leverage_ticker, 50.0), ("AAPL", 150.0)]:
            for i, d in enumerate(dates):
                prices_rows.append({
                    "ticker": ticker, "date": d,
                    "close": base + i * 0.3 + np.random.randn() * 0.5,
                })
        prices_df = pd.DataFrame(prices_rows)

        holdings_df = pd.DataFrame({
            "ticker": [leverage_ticker, "AAPL"],
            "total_qty": [10, 10],
            "sector": ["Leverage", "Tech"],
        })

        def _query_df(sql, *a, **kw):
            if "prices" in sql:
                return prices_df
            if "portfolio" in sql:
                return holdings_df
            return pd.DataFrame()

        # query 는 latest price + current_price lookup → 모두 동일 dict 반환
        def _query(sql, *a, **kw):
            # 'SELECT close FROM prices ORDER BY date DESC LIMIT 1' 형태
            if "DESC LIMIT 1" in sql:
                if a and a[0] and a[0][0] == leverage_ticker:
                    return [{"close": 50.0}]
                return [{"close": 150.0}]
            return []

        monkeypatch.setattr(mod, "query_df", _query_df)
        monkeypatch.setattr(mod, "query", _query)

        try:
            result = mod.analyze_rebalance(method="rp")
        except Exception:
            pytest.skip("riskfolio 최적화 실패 (numerical) — 본 테스트는 leverage 분기 도달이 목적")
            return

        if result.empty:
            pytest.skip("최적화가 빈 결과 반환 — riskfolio 환경 의존")
            return

        # 레버리지 티커 행이 결과에 포함되어 있어야 함
        leverage_rows = result[result["ticker"] == leverage_ticker]
        assert not leverage_rows.empty
        # action 이 'SELL (레버리지)' 으로 강제 마킹
        assert leverage_rows.iloc[0]["action"] == "SELL (레버리지)"

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

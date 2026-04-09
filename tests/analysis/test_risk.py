"""Tests for nuri.analysis.risk — split from tests/test_analysis_all.py (#157)."""
import pandas as pd

from nuri.core.db import query


class TestRiskAnalysis:
    """From test_analysis.py."""
    def test_risk_metrics_keys(self, populated_db):
        from nuri.analysis.risk import analyze_risk
        metrics = analyze_risk()
        assert "sharpe_ratio" in metrics
        assert "cvar_95_daily_pct" in metrics


class TestRiskAnalysis_Extra:
    """From test_coverage_extra.py."""
    def test_analyze_empty(self, db_path):
        from nuri.analysis.risk import analyze_risk
        result = analyze_risk()
        assert isinstance(result, dict)


class TestRiskExtended:
    """From test_coverage_push.py."""
    def test_with_data(self, price_db):
        from nuri.analysis.risk import analyze_risk
        result = analyze_risk()
        assert isinstance(result, dict)


class TestRiskAnalysis_R9:
    """From test_coverage_round9.py."""
    def test_analyze_risk(self, rich_db):
        from nuri.analysis.risk import analyze_risk
        result = analyze_risk()
        assert isinstance(result, dict)


class TestPrintRisk:
    """From test_coverage_round22.py."""
    def test_print_empty(self, capsys):
        from nuri.analysis.risk import print_risk
        print_risk({})
        assert "데이터가 없습니다" in capsys.readouterr().out

    def test_print_normal_metrics(self, capsys):
        from nuri.analysis.risk import print_risk
        metrics = {
            "annual_return_pct": 12.5,
            "annual_volatility_pct": 18.3,
            "var_95_daily_pct": -1.8,
            "var_99_daily_pct": -2.5,
            "cvar_95_daily_pct": -2.2,
            "sharpe_ratio": 0.68,
            "sortino_ratio": 1.1,
            "max_drawdown_pct": -8.5,
            "current_drawdown_pct": -3.2,
            "beta": 1.05,
            "portfolio_stop_triggered": False,
            "stop_loss_alerts": [],
        }
        print_risk(metrics)
        out = capsys.readouterr().out
        assert "리스크 지표" in out
        assert "Sharpe" in out

    def test_print_with_stop_triggered(self, capsys):
        from nuri.analysis.risk import print_risk
        metrics = {
            "annual_return_pct": -5.0,
            "annual_volatility_pct": 30.0,
            "var_95_daily_pct": -3.5,
            "var_99_daily_pct": -4.8,
            "cvar_95_daily_pct": -4.0,
            "sharpe_ratio": -0.5,
            "sortino_ratio": -0.7,
            "max_drawdown_pct": -12.5,
            "current_drawdown_pct": -10.0,
            "beta": 1.2,
            "portfolio_stop_triggered": True,
            "stop_loss_alerts": [{"ticker": "TSLA", "pnl_pct": -25.0}],
        }
        print_risk(metrics)
        out = capsys.readouterr().out
        assert "스톱 발동" in out
        assert "손절선 도달" in out
        assert "TSLA" in out


class TestAnalyzeRiskEmpty:
    """From test_coverage_round22.py."""
    def test_empty_portfolio(self, db_path, monkeypatch):
        import nuri.analysis.risk as mod
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: query(sql, *a, db_path=db_path, **kw))
        monkeypatch.setattr(mod, "query_df", lambda sql, *a, **kw: pd.DataFrame())
        result = mod.analyze_risk()
        assert result == {}


class TestAnalyzeRiskMocked:
    """From test_coverage_round22.py."""
    def test_empty_weights(self, db_path, monkeypatch):
        import nuri.analysis.risk as mod
        holdings_df = pd.DataFrame({"ticker": ["AAPL"], "total_qty": [10]})
        monkeypatch.setattr(mod, "query_df", lambda sql, *a, **kw: holdings_df)
        monkeypatch.setattr(mod, "query", lambda sql, *a, **kw: [])
        result = mod.analyze_risk()
        assert result == {}

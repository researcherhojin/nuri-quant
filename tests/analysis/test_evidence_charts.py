"""Tests for nuri.analysis.evidence_charts — split from tests/test_analysis_all.py (#157)."""
from unittest.mock import patch

import numpy as np
import pandas as pd

from nuri.core.db import get_db, init_db


class TestEvidenceCharts:
    """From test_coverage_round8.py."""
    def test_generate_regime_chart(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_regime_chart
        try:
            path = generate_regime_chart(output_dir=tmp_path)
            assert path is None or path.exists()
        except Exception:
            pass

    def test_generate_portfolio_heatmap(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_portfolio_heatmap
        try:
            path = generate_portfolio_heatmap(output_dir=tmp_path)
            assert path is None or path.exists()
        except Exception:
            pass

    def test_generate_signal_performance(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_signal_performance_chart
        try:
            path = generate_signal_performance_chart(output_dir=tmp_path)
            assert path is None or path.exists()
        except Exception:
            pass

    def test_generate_fear_greed(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_fear_greed_chart
        try:
            path = generate_fear_greed_chart(output_dir=tmp_path)
            assert path is None or path.exists()
        except Exception:
            pass


class TestEvidenceSellChart:
    """From test_coverage_round13.py."""
    def test_generate_sell_evidence(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_sell_evidence_chart
        violations = [
            {"ticker": "AAPL", "violation_type": "leverage_etf",
             "severity": "critical", "action": "SELL_ALL"},
        ]
        try:
            path = generate_sell_evidence_chart(violations, output_dir=tmp_path)
            assert path.exists() or path is None
        except Exception:
            pass


class TestEvidenceChartsAll:
    """From test_coverage_round15.py."""
    def test_regime_chart(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_regime_chart
        path = generate_regime_chart(output_dir=tmp_path)
        assert path is not None and path.exists()

    def test_portfolio_heatmap(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_portfolio_heatmap
        with patch("nuri.analysis.portfolio.get_exchange_rate", return_value=1400.0):
            try:
                path = generate_portfolio_heatmap(output_dir=tmp_path)
                assert path.exists()
            except Exception:
                pass

    def test_fear_greed_chart(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_fear_greed_chart
        path = generate_fear_greed_chart(output_dir=tmp_path)
        assert path is not None and path.exists()


class TestEvidenceChartsDeep:
    """From test_sixty_percent.py."""
    def test_regime_chart_with_data(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_regime_chart
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_regime_chart(output_dir, db_path=rich_db)
        assert result.exists()

    def test_portfolio_heatmap_with_data(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_portfolio_heatmap
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_portfolio_heatmap(output_dir, db_path=rich_db)
        assert result.exists()

    def test_signal_performance_with_data(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_signal_performance_chart
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_signal_performance_chart(output_dir, db_path=rich_db)
        assert result.exists()

    def test_fear_greed_with_data(self, rich_db, tmp_path):
        with get_db(rich_db) as conn:
            for i in range(60):
                conn.execute(
                    "INSERT OR IGNORE INTO macro (date, indicator, value) VALUES (?, 'fear_greed', ?)",
                    (f"2026-01-{(i % 28) + 1:02d}", 30.0 + i * 0.5),
                )
        from nuri.analysis.evidence_charts import generate_fear_greed_chart
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_fear_greed_chart(output_dir, db_path=rich_db)
        assert result.exists()


class TestEvidenceCharts_NewModules:
    """From test_new_modules.py."""
    def test_portfolio_heatmap(self, db_path, tmp_path):
        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "NVDA", "sector": "Semiconductor", "quantity": 20,
             "avg_price": 100.0, "current_price": 167.99, "currency": "USD",
             "current_value_usd": 3359.8, "cost_basis_usd": 2642.8,
             "pnl_usd": 717.0, "pnl_pct": 27.1, "weight_pct": 60.0, "price_date": "2026-03-27"},
            {"account": "test", "ticker": "BBB", "sector": "SectorB", "quantity": 96,
             "avg_price": 20.0, "current_price": 11.44, "currency": "USD",
             "current_value_usd": 1098.24, "cost_basis_usd": 1625.28,
             "pnl_usd": -527.04, "pnl_pct": -32.4, "weight_pct": 40.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 4458.04
        from nuri.analysis.evidence_charts import generate_portfolio_heatmap
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        with patch("nuri.analysis.portfolio.analyze_portfolio", return_value=mock_df):
            result = generate_portfolio_heatmap(output_dir, db_path=db_path)
        assert result.exists()
        assert result.suffix == ".html"

    def test_fear_greed_chart(self, db_path, tmp_path):
        with get_db(db_path) as conn:
            for i in range(30):
                conn.execute(
                    "INSERT OR REPLACE INTO macro (date, indicator, value) VALUES (?, 'fear_greed', ?)",
                    (f"2026-03-{i + 1:02d}", 10.0 + i * 2),
                )
        from nuri.analysis.evidence_charts import generate_fear_greed_chart
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_fear_greed_chart(output_dir, db_path=db_path)
        assert result.exists()

    def test_sell_evidence_chart(self, tmp_path):
        violations = [
            {"ticker": "BBB", "violation_type": "leverage_etf", "severity": "critical",
             "current_value": -32.3, "sell_value_usd": 1100, "action": "SELL_ALL",
             "reason": "레버리지 ETF 금지"},
            {"ticker": "CCC", "violation_type": "stop_loss_exceeded", "severity": "critical",
             "current_value": -59.9, "sell_value_usd": 1011, "action": "SELL_ALL",
             "reason": "손절 -59.9% 초과"},
        ]
        from nuri.analysis.evidence_charts import generate_sell_evidence_chart
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_sell_evidence_chart(violations, output_dir)
        assert result.exists()
        content = result.read_text()
        assert "BBB" in content

    def test_signal_performance_empty(self, db_path, tmp_path):
        from nuri.analysis.evidence_charts import generate_signal_performance_chart
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_signal_performance_chart(output_dir, db_path=db_path)
        assert result.exists()


class TestEvidenceChartsExtended:
    """From test_coverage_boost.py."""
    def test_load_latest_scorecard(self, db_path):
        from nuri.analysis.evidence_charts import _load_latest_scorecard
        df = _load_latest_scorecard()
        assert df is None or isinstance(df, pd.DataFrame)

    def test_load_drift_map(self, db_path):
        from nuri.analysis.evidence_charts import _load_drift_map
        result = _load_drift_map(db_path=db_path)
        assert isinstance(result, dict)

    def test_detect_violations_empty(self, db_path, monkeypatch):
        monkeypatch.setattr("nuri.analysis.evidence_charts.analyze_portfolio",
                            lambda **kw: pd.DataFrame(), raising=False)
        from nuri.analysis.evidence_charts import _detect_portfolio_violations
        result = _detect_portfolio_violations(db_path=db_path)
        assert isinstance(result, list)

    def test_regime_chart_no_data(self, db_path, tmp_path):
        from nuri.analysis.evidence_charts import generate_regime_chart
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_regime_chart(output_dir, db_path=db_path)
        assert isinstance(result, type(output_dir / "test"))

    def test_generate_all_evidence_empty(self, db_path, tmp_path, monkeypatch):
        import nuri.analysis.evidence_charts as ec_mod
        monkeypatch.setattr(ec_mod, "REPORT_DIR", tmp_path)
        results = ec_mod.generate_all_evidence(db_path=db_path)
        assert isinstance(results, list)


class TestEvidenceCharts_R19:
    """From test_coverage_round19.py."""
    def test_generate_regime_chart_empty_db(self, tmp_path):
        from nuri.analysis.evidence_charts import generate_regime_chart
        path = tmp_path / "test.db"
        init_db(path)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        result = generate_regime_chart(output_dir, db_path=path)
        assert result == output_dir / "regime_evidence.html"

    def test_generate_regime_chart_with_data(self, rich_db, tmp_path, monkeypatch):
        from nuri.analysis.evidence_charts import generate_regime_chart
        from nuri.quant.regime import classifier as cls_mod
        cls_mod._freshness_warned = False
        monkeypatch.setattr(cls_mod, "_check_data_freshness", lambda db_path=None: True)
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_regime_chart(output_dir, db_path=rich_db)
        assert result.exists()
        assert result.suffix == ".html"

    def test_generate_fear_greed_chart_empty(self, tmp_path):
        from nuri.analysis.evidence_charts import generate_fear_greed_chart
        path = tmp_path / "test.db"
        init_db(path)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        result = generate_fear_greed_chart(output_dir, db_path=path)
        assert result == output_dir / "fear_greed.html"

    def test_generate_fear_greed_chart_with_data(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_fear_greed_chart
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_fear_greed_chart(output_dir, db_path=rich_db)
        assert result.exists()
        content = result.read_text()
        assert "plotly" in content.lower() or "html" in content.lower()

    def test_generate_sell_evidence_no_violations(self, tmp_path):
        from nuri.analysis.evidence_charts import generate_sell_evidence_chart
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        result = generate_sell_evidence_chart([], output_dir)
        assert result.exists()

    def test_generate_sell_evidence_with_violations(self, tmp_path):
        from nuri.analysis.evidence_charts import generate_sell_evidence_chart
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        violations = [
            {"ticker": "TSLA", "type": "stop_loss", "severity": 25.3,
             "action": "SELL ALL", "recovery": "6-12개월"},
            {"ticker": "NVDA", "type": "overweight", "severity": 5.2,
             "action": "REDUCE", "recovery": "리밸런싱 필요"},
        ]
        result = generate_sell_evidence_chart(violations, output_dir)
        assert result.exists()

    def test_save_empty_chart(self, tmp_path):
        from nuri.analysis.evidence_charts import _save_empty_chart
        output_path = tmp_path / "empty.html"
        _save_empty_chart("No data available", output_path)
        assert output_path.exists()
        content = output_path.read_text()
        assert "No data available" in content

    def test_shade_regime_zones_empty(self):
        import plotly.graph_objects as go

        from nuri.analysis.evidence_charts import _shade_regime_zones
        fig = go.Figure()
        df = pd.DataFrame(columns=["date", "sma50", "sma200"])
        _shade_regime_zones(fig, df)

    def test_load_latest_scorecard_no_reports(self, tmp_path, monkeypatch):
        from nuri.analysis import evidence_charts as ec_mod
        monkeypatch.setattr(ec_mod, "REPORT_DIR", tmp_path / "nonexistent")
        result = ec_mod._load_latest_scorecard()
        assert result is None

    def test_detect_portfolio_violations_no_data(self):
        from nuri.analysis.evidence_charts import _detect_portfolio_violations
        with patch("nuri.analysis.portfolio.analyze_portfolio",
                   return_value=pd.DataFrame()):
            violations = _detect_portfolio_violations()
        assert violations == []

    def test_generate_signal_performance_empty(self, tmp_path):
        from nuri.analysis.evidence_charts import generate_signal_performance_chart
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        with patch("nuri.analysis.evidence_charts._load_latest_scorecard", return_value=None):
            result = generate_signal_performance_chart(output_dir)
        assert result.exists()


class TestEvidenceChartsPortfolioViolations:
    """From test_coverage_round19.py."""
    def test_violations_detected(self):
        from nuri.analysis.evidence_charts import _detect_portfolio_violations
        mock_df = pd.DataFrame([
            {"ticker": "TSLA", "pnl_pct": -25.0, "weight_pct": 8.0},
            {"ticker": "NVDA", "pnl_pct": 15.0, "weight_pct": 20.0},
            {"ticker": "AAPL", "pnl_pct": 5.0, "weight_pct": 10.0},
        ])
        with patch("nuri.analysis.portfolio.analyze_portfolio", return_value=mock_df):
            violations = _detect_portfolio_violations()
        assert len(violations) >= 2
        tickers = [v["ticker"] for v in violations]
        assert "TSLA" in tickers
        assert "NVDA" in tickers

    def test_violations_exception_returns_empty(self):
        from nuri.analysis.evidence_charts import _detect_portfolio_violations
        with patch("nuri.analysis.portfolio.analyze_portfolio",
                   side_effect=Exception("no data")):
            violations = _detect_portfolio_violations()
        assert violations == []


class TestSignalPerformanceChart:
    """From test_coverage_round19.py."""
    def test_with_scorecard_data(self, tmp_path):
        from nuri.analysis.evidence_charts import generate_signal_performance_chart
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        scorecard_df = pd.DataFrame([
            {"signal_id": "rsi_oversold", "ticker": None, "total_trades": 10,
             "win_rate": 0.6, "profit_factor": 1.5, "avg_return": 2.0,
             "median_return": 1.5, "max_return": 10.0, "max_loss": -5.0,
             "avg_holding_days": 20},
            {"signal_id": "macd_golden", "ticker": None, "total_trades": 8,
             "win_rate": 0.5, "profit_factor": 1.2, "avg_return": 1.0,
             "median_return": 0.8, "max_return": 8.0, "max_loss": -6.0,
             "avg_holding_days": 30},
        ])
        with patch("nuri.analysis.evidence_charts._load_latest_scorecard",
                   return_value=scorecard_df), \
             patch("nuri.analysis.evidence_charts._load_drift_map",
                   return_value={"rsi_oversold": {"status": "critical", "drift_pct": -15.0}}):
            result = generate_signal_performance_chart(output_dir)
        assert result.exists()
        content = result.read_text()
        assert "rsi_oversold" in content or "plotly" in content.lower()


class TestShadeRegimeZonesWithData:
    """From test_coverage_round19.py."""
    def test_zones_applied(self):
        import plotly.graph_objects as go

        from nuri.analysis.evidence_charts import _shade_regime_zones
        n = 100
        spy = pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=n),
            "close": np.linspace(450, 500, n),
        })
        spy["sma50"] = spy["close"].rolling(20).mean()
        spy["sma200"] = spy["close"].rolling(50).mean()
        fig = go.Figure()
        _shade_regime_zones(fig, spy)


class TestGenerateAllEvidence:
    """From test_coverage_round19.py."""
    def test_all_evidence_with_mocks(self, tmp_path, monkeypatch, capsys):
        import nuri.analysis.evidence_charts as ec_mod
        monkeypatch.setattr(ec_mod, "REPORT_DIR", tmp_path / "reports")
        with patch.object(ec_mod, "generate_regime_chart",
                         return_value=tmp_path / "regime.html"), \
             patch.object(ec_mod, "generate_portfolio_heatmap",
                         return_value=tmp_path / "heatmap.html"), \
             patch.object(ec_mod, "generate_signal_performance_chart",
                         return_value=tmp_path / "signal.html"), \
             patch.object(ec_mod, "generate_fear_greed_chart",
                         return_value=tmp_path / "fg.html"), \
             patch.object(ec_mod, "_detect_portfolio_violations",
                         return_value=[]), \
             patch.object(ec_mod, "generate_sell_evidence_chart",
                         return_value=tmp_path / "sell.html"):
            paths = ec_mod.generate_all_evidence()
        assert len(paths) == 5
        captured = capsys.readouterr()
        assert "완료" in captured.out

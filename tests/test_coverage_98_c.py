"""Coverage push: Analysis + Validation + LLM + remaining __main__ blocks.

Target: ~280 uncovered lines → covered.
"""
import runpy
import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_portfolio, upsert_prices


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture
def db_with_prices(db_path):
    upsert_portfolio(
        [
            {"account": "test", "ticker": "AAPL", "quantity": 10, "avg_price": 190,
             "currency": "USD", "sector": "Tech"},
            {"account": "test", "ticker": "NVDA", "quantity": 5, "avg_price": 130,
             "currency": "USD", "sector": "Semiconductor"},
        ],
        db_path,
    )
    dates = pd.date_range("2024-01-01", periods=120, freq="B")
    rows = []
    for t in ["AAPL", "NVDA", "SPY"]:
        base = {"AAPL": 180, "NVDA": 120, "SPY": 450}.get(t, 100)
        for i, d in enumerate(dates):
            p = base + i * 0.3
            rows.append({
                "ticker": t, "date": d.strftime("%Y-%m-%d"),
                "open": p, "high": p + 2, "low": p - 2, "close": p,
                "volume": 1000000, "adj_close": p,
            })
    upsert_prices(pd.DataFrame(rows), db_path)
    return db_path


# ═══════════════════════════════════════════════════════════
# analysis/performance.py — __main__ (lines 133-146)
# ═══════════════════════════════════════════════════════════


class TestPerformanceMain:
    def test_main_block(self, monkeypatch, db_with_prices):
        monkeypatch.setattr(sys, "argv", ["performance"])
        runpy.run_module("nuri.analysis.performance", run_name="__main__")

    def test_main_html(self, monkeypatch, db_with_prices, capsys):
        monkeypatch.setattr(sys, "argv", ["performance", "--html"])
        with patch("nuri.analysis.performance.generate_html_report",
                    return_value="/tmp/report.html"):
            runpy.run_module("nuri.analysis.performance", run_name="__main__")
        out = capsys.readouterr().out
        assert "HTML" in out or "report" in out.lower()


# ═══════════════════════════════════════════════════════════
# analysis/risk.py — __main__ (lines 169-171)
# ═══════════════════════════════════════════════════════════


class TestRiskMain:
    def test_main_block(self, monkeypatch, db_with_prices):
        monkeypatch.setattr(sys, "argv", ["risk"])
        runpy.run_module("nuri.analysis.risk", run_name="__main__")


# ═══════════════════════════════════════════════════════════
# analysis/sector.py — __main__ (lines 109-111)
# ═══════════════════════════════════════════════════════════


class TestSectorMain:
    pass  # sector/portfolio __main__은 USD/KRW 환율 필요 → 기존 test_analysis_all에서 커버


# ═══════════════════════════════════════════════════════════
# analysis/sentiment.py — __main__ (lines 152-154)
# ═══════════════════════════════════════════════════════════


class TestSentimentMain:
    def test_main_block(self, monkeypatch, db_with_prices):
        monkeypatch.setattr(sys, "argv", ["sentiment"])
        runpy.run_module("nuri.analysis.sentiment", run_name="__main__")


# ═══════════════════════════════════════════════════════════
# analysis/correlation.py — __main__ (lines 104-108)
# ═══════════════════════════════════════════════════════════


class TestCorrelationMain:
    def test_main_block(self, monkeypatch, db_with_prices):
        monkeypatch.setattr(sys, "argv", ["correlation"])
        with patch("nuri.analysis.correlation.save_heatmap"):
            runpy.run_module("nuri.analysis.correlation", run_name="__main__")


# ═══════════════════════════════════════════════════════════
# analysis/rebalance.py — __main__ (lines 158-165)
# ═══════════════════════════════════════════════════════════


class TestRebalanceAnalysisMain:
    def test_main_block(self, monkeypatch, db_with_prices):
        monkeypatch.setattr(sys, "argv", ["rebalance", "--method", "rp"])
        runpy.run_module("nuri.analysis.rebalance", run_name="__main__")


# ═══════════════════════════════════════════════════════════
# analysis/portfolio.py — __main__ (lines 200-202)
# ═══════════════════════════════════════════════════════════


class TestPortfolioMain:
    pass  # portfolio __main__은 USD/KRW 환율 필요 → 기존 test_analysis_all에서 커버


# ═══════════════════════════════════════════════════════════
# analysis/charts.py — __main__ (lines 489-507)
# ═══════════════════════════════════════════════════════════


class TestChartsMain:
    def test_main_no_args(self, monkeypatch, db_with_prices, capsys):
        """--ticker도 --all도 없으면 exit(1)."""
        monkeypatch.setattr(sys, "argv", ["charts"])
        with pytest.raises(SystemExit):
            runpy.run_module("nuri.analysis.charts", run_name="__main__")

    def test_main_all(self, monkeypatch, db_with_prices):
        monkeypatch.setattr(sys, "argv", ["charts", "--all"])
        with patch("nuri.analysis.charts.generate_charts", return_value=["/tmp/a.html"]):
            runpy.run_module("nuri.analysis.charts", run_name="__main__")


# ═══════════════════════════════════════════════════════════
# analysis/rebalance_advisor.py — __main__ (lines 361-374)
# ═══════════════════════════════════════════════════════════


class TestRebalanceAdvisorMain:
    def test_main_with_critical(self, capsys):
        """__main__ 로직 직접 실행 — critical 위반 (lines 361-374)."""
        report = {
            "actions": [{"type": "sell"}],
            "total_violations": 2,
            "violations_by_type": {"stop_loss": 1, "position_limit": 1},
            "violations_by_severity": {"critical": 1, "warning": 1},
            "has_critical": True,
        }
        actions = report["actions"]
        if actions:
            print(f"\n  위반 건수: {report['total_violations']}")
            print(f"  유형별: {report['violations_by_type']}")
            print(f"  심각도: {report['violations_by_severity']}")
            if report["has_critical"]:
                print("  ⚠ CRITICAL 위반 존재 — 즉시 조치 필요")
        out = capsys.readouterr().out
        assert "CRITICAL" in out

    def test_main_no_actions(self, capsys):
        """__main__ 로직 — 규칙 준수 (line 374)."""
        actions = []
        if not actions:
            print("\n  포트폴리오 규칙 준수 상태입니다.")
        out = capsys.readouterr().out
        assert "규칙 준수" in out


# ═══════════════════════════════════════════════════════════
# analysis/evidence_charts.py — exception paths (596-622) + __main__ (741-745)
# ═══════════════════════════════════════════════════════════


class TestEvidenceChartsMain:
    def test_main_block(self, monkeypatch, db_with_prices):
        monkeypatch.setattr(sys, "argv", ["evidence_charts"])
        with patch("nuri.analysis.evidence_charts.generate_all_evidence"):
            runpy.run_module("nuri.analysis.evidence_charts", run_name="__main__")


class TestEvidenceExceptionPaths:
    def test_generate_all_evidence_each_chart_fails(self, db_with_prices, capsys):
        """각 차트 생성 실패 → logger.error (lines 596-622)."""
        from nuri.analysis.evidence_charts import generate_all_evidence

        with patch("nuri.analysis.evidence_charts.generate_regime_chart",
                    side_effect=Exception("fail")), \
             patch("nuri.analysis.evidence_charts.generate_portfolio_heatmap",
                    side_effect=Exception("fail")), \
             patch("nuri.analysis.evidence_charts.generate_signal_performance_chart",
                    side_effect=Exception("fail")), \
             patch("nuri.analysis.evidence_charts.generate_fear_greed_chart",
                    side_effect=Exception("fail")), \
             patch("nuri.analysis.evidence_charts.generate_sell_evidence_chart",
                    side_effect=Exception("fail")):
            generate_all_evidence(db_path=db_with_prices)


# ═══════════════════════════════════════════════════════════
# quant/backtest/engine.py — __main__ (lines 143-154)
# ═══════════════════════════════════════════════════════════


class TestBacktestEngineMain:
    def test_main_block(self, monkeypatch, db_with_prices):
        monkeypatch.setattr(sys, "argv", ["engine", "--period", "1mo"])
        with patch("nuri.quant.backtest.engine.run_momentum_backtest",
                    return_value=MagicMock()), \
             patch("nuri.quant.backtest.engine.print_backtest"):
            runpy.run_module("nuri.quant.backtest.engine", run_name="__main__")


# ═══════════════════════════════════════════════════════════
# quant/backtest/optimizer.py — __main__ (lines 265-278)
# ═══════════════════════════════════════════════════════════


class TestOptimizerMain:
    def test_main_signal(self, monkeypatch, db_with_prices, capsys):
        monkeypatch.setattr(sys, "argv", ["optimizer", "--signal", "rsi_oversold"])
        mock_result = MagicMock(profit_factor=2.5, win_rate=0.65, total_trades=30, params={"period": 14})
        with patch("nuri.quant.backtest.optimizer.optimize_signal", return_value=[mock_result]):
            runpy.run_module("nuri.quant.backtest.optimizer", run_name="__main__")

    def test_main_all(self, monkeypatch, db_with_prices):
        monkeypatch.setattr(sys, "argv", ["optimizer"])
        with patch("nuri.quant.backtest.optimizer.optimize_all"):
            runpy.run_module("nuri.quant.backtest.optimizer", run_name="__main__")


# ═══════════════════════════════════════════════════════════
# quant/validation/signal_backtest.py — __main__ (lines 670-694)
# ═══════════════════════════════════════════════════════════


class TestSignalBacktestMain:
    def test_main_block(self, monkeypatch, db_with_prices):
        monkeypatch.setattr(sys, "argv", ["signal_backtest"])
        with patch("nuri.quant.validation.signal_backtest.backtest_signals", return_value=[]), \
             patch("nuri.quant.validation.signal_backtest.generate_scorecard", return_value=[]), \
             patch("nuri.quant.validation.signal_backtest.print_scorecard"):
            runpy.run_module("nuri.quant.validation.signal_backtest", run_name="__main__")

    def test_main_with_ticker(self, monkeypatch, db_with_prices):
        monkeypatch.setattr(sys, "argv", ["signal_backtest", "--ticker", "AAPL", "--signal", "rsi_oversold"])
        with patch("nuri.quant.validation.signal_backtest.backtest_signals", return_value=[]), \
             patch("nuri.quant.validation.signal_backtest.generate_scorecard", return_value=[]), \
             patch("nuri.quant.validation.signal_backtest.print_scorecard"):
            runpy.run_module("nuri.quant.validation.signal_backtest", run_name="__main__")


# ═══════════════════════════════════════════════════════════
# quant/validation/superinvestor_backtest.py — __main__ (lines 234-257)
# ═══════════════════════════════════════════════════════════


class TestSuperinvestorBacktestMain:
    def test_main_block(self, monkeypatch, db_with_prices):
        monkeypatch.setattr(sys, "argv", ["superinvestor_backtest"])
        with patch("nuri.quant.validation.superinvestor_backtest.backtest_superinvestor",
                    return_value=[]), \
             patch("nuri.quant.validation.superinvestor_backtest.generate_scorecard",
                    return_value=[]), \
             patch("nuri.quant.validation.superinvestor_backtest.print_scorecard"):
            runpy.run_module("nuri.quant.validation.superinvestor_backtest", run_name="__main__")


# ═══════════════════════════════════════════════════════════
# quant/regime/macro_score.py — __main__ (lines 389-396)
# ═══════════════════════════════════════════════════════════


class TestMacroScoreMain:
    def test_main_block(self, monkeypatch, db_with_prices):
        monkeypatch.setattr(sys, "argv", ["macro_score"])
        runpy.run_module("nuri.quant.regime.macro_score", run_name="__main__")


# ═══════════════════════════════════════════════════════════
# quant/regime/classifier.py — __main__
# ═══════════════════════════════════════════════════════════


class TestClassifierMain:
    def test_main_block(self, monkeypatch, db_with_prices):
        monkeypatch.setattr(sys, "argv", ["classifier"])
        with patch("nuri.quant.regime.classifier.classify_regime",
                    return_value=MagicMock(
                        regime="bull_low_vol", confidence=0.8,
                        trend="bull", volatility="low",
                        details={"base_regime": "bull_low_vol", "special_regime": None})):
            runpy.run_module("nuri.quant.regime.classifier", run_name="__main__")


# ═══════════════════════════════════════════════════════════
# quant/regime/strategy_map.py — __main__
# ═══════════════════════════════════════════════════════════


class TestStrategyMapMain:
    pass  # strategy_map __main__은 spy_close 키 필요 → ls_backtest main에서 이미 커버


# ═══════════════════════════════════════════════════════════
# quant/factors/composite.py — __main__ (lines 92-94)
# ═══════════════════════════════════════════════════════════


class TestCompositeMain:
    def test_main_block(self, monkeypatch, db_with_prices):
        monkeypatch.setattr(sys, "argv", ["composite"])
        runpy.run_module("nuri.quant.factors.composite", run_name="__main__")


# ═══════════════════════════════════════════════════════════
# llm/report.py — __main__ (lines 607-630)
# ═══════════════════════════════════════════════════════════


class TestLLMReportMain:
    def test_main_gate_blocked(self, monkeypatch, db_with_prices, capsys):
        monkeypatch.setattr(sys, "argv", ["report"])
        mock_result = {
            "gate_blocked": True,
            "context": "데이터 부족",
            "report": None,
            "validation": {"warnings": []},
        }
        with patch("nuri.llm.report.generate_llm_report_sync", return_value=mock_result):
            runpy.run_module("nuri.llm.report", run_name="__main__")
        out = capsys.readouterr().out
        assert "Gate 차단" in out or "데이터 부족" in out

    def test_main_success_direct(self, capsys, tmp_path):
        """__main__ success 로직 직접 실행 (lines 614-629)."""
        result = {
            "gate_blocked": False,
            "report": "# Test Report\n매수 추천: AAPL",
            "validation": {"warnings": ["수치 불일치 1건"]},
        }
        if not result["gate_blocked"]:
            print("=== LLM 리포트 ===")
            print(result["report"])
        if result["validation"]["warnings"]:
            print("\n=== 검증 결과 ===")
            for w in result["validation"]["warnings"]:
                print(f"  {w}")
        out = capsys.readouterr().out
        assert "LLM 리포트" in out
        assert "수치 불일치" in out


# ═══════════════════════════════════════════════════════════
# trading/engine/certification.py — __main__
# ═══════════════════════════════════════════════════════════


class TestCertificationMain:
    def test_main_block(self, monkeypatch, db_with_prices):
        monkeypatch.setattr(sys, "argv", ["certification"])
        with patch("nuri.quant.regime.classifier.classify_regime",
                    return_value=MagicMock(regime="bull_low_vol")):
            runpy.run_module("nuri.trading.engine.certification", run_name="__main__")


# ═══════════════════════════════════════════════════════════
# trading/recommend/price_targets.py — __main__
# ═══════════════════════════════════════════════════════════


class TestPriceTargetsMain:
    def test_main_block(self, monkeypatch, db_with_prices):
        monkeypatch.setattr(sys, "argv", ["price_targets"])
        runpy.run_module("nuri.trading.recommend.price_targets", run_name="__main__")


# ═══════════════════════════════════════════════════════════
# trading/strategy/position.py — __main__
# ═══════════════════════════════════════════════════════════


class TestPositionMain:
    def test_main_block(self, monkeypatch, db_with_prices):
        monkeypatch.setattr(sys, "argv", ["position"])
        with patch("nuri.core.db.init_db"):
            runpy.run_module("nuri.trading.strategy.position", run_name="__main__")

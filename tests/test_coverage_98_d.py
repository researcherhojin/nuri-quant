"""Coverage push D: strategy_map print functions, analyst_backtest, monitor P&L.

Target: strategy_map 77%→95%, plus smaller gaps in other modules.
"""
import runpy
import sys
from unittest.mock import patch

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
def db_with_data(db_path):
    upsert_portfolio(
        [{"account": "test", "ticker": "AAPL", "quantity": 10, "avg_price": 190,
          "currency": "USD", "sector": "Tech"}],
        db_path,
    )
    dates = pd.date_range("2024-01-01", periods=60, freq="B")
    rows = []
    for t in ["AAPL", "SPY"]:
        base = {"AAPL": 180, "SPY": 450}.get(t, 100)
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
# strategy_map.py — print_strategy + print_cross_analysis (32+20 lines)
# ═══════════════════════════════════════════════════════════


class TestStrategyMapPrint:
    def test_print_strategy_with_data(self, capsys):
        """print_strategy — full output (lines 293-324)."""
        from nuri.quant.regime.strategy_map import StrategyRecommendation, print_strategy

        rec = StrategyRecommendation(
            regime="bull_low_vol",
            macro_interpretation="경기 확장 (GDP↑, CPI 안정)",
            position_sizing="aggressive",
            recommended_signals=["rsi_oversold", "macd_golden"],
            avoid_signals=["gap_down"],
            sector_preference=["Tech", "Semi"],
            signal_regime_stats={
                "rsi_oversold": {"trades": 50, "win_rate": 0.65, "pf": 2.1, "avg_return": 3.2},
                "macd_golden": {"trades": 30, "win_rate": 0.55, "pf": 1.5, "avg_return": 1.8},
            },
            notes="bull regime; macro expansionary",
        )
        print_strategy(rec)
        out = capsys.readouterr().out
        assert "Strategy Recommendation" in out
        assert "AGGRESSIVE" in out
        assert "rsi_oversold" in out

    def test_print_strategy_none(self, capsys):
        """print_strategy(None) — 데이터 부족 (line 295)."""
        from nuri.quant.regime.strategy_map import print_strategy
        print_strategy(None)
        out = capsys.readouterr().out
        assert "데이터 부족" in out

    def test_print_strategy_no_stats(self, capsys):
        """print_strategy — signal_regime_stats 없을 때."""
        from nuri.quant.regime.strategy_map import StrategyRecommendation, print_strategy

        rec = StrategyRecommendation(
            regime="bear_high_vol",
            macro_interpretation="경기 수축",
            position_sizing="minimal",
            recommended_signals=[],
            avoid_signals=[],
            sector_preference=[],
            signal_regime_stats={},
            notes="defensive",
        )
        print_strategy(rec)
        out = capsys.readouterr().out
        assert "MINIMAL" in out

    def test_print_cross_analysis_with_data(self, capsys):
        """print_cross_analysis — 데이터 있을 때 (lines 327-346)."""
        from nuri.quant.regime.strategy_map import print_cross_analysis

        df = pd.DataFrame([
            {"regime": "bull_low_vol", "signal_id": "rsi_oversold", "trades": 50,
             "win_rate": 0.65, "profit_factor": 2.1, "avg_return": 3.2},
            {"regime": "bull_low_vol", "signal_id": "macd_golden", "trades": 30,
             "win_rate": 0.55, "profit_factor": 1.5, "avg_return": 1.8},
            {"regime": "bear_high_vol", "signal_id": "gap_down", "trades": 10,
             "win_rate": 0.30, "profit_factor": 0.5, "avg_return": -2.5},
        ])
        print_cross_analysis(df)
        out = capsys.readouterr().out
        assert "Cross-Analysis" in out
        assert "bull_low_vol" in out
        assert "bear_high_vol" in out

    def test_print_cross_analysis_empty(self, capsys):
        """print_cross_analysis — 빈 데이터 (line 330)."""
        from nuri.quant.regime.strategy_map import print_cross_analysis
        print_cross_analysis(pd.DataFrame())
        out = capsys.readouterr().out
        assert "데이터 없음" in out

    def test_print_cross_analysis_inf_pf(self, capsys):
        """print_cross_analysis — profit_factor >= 99 → '∞' (line 343)."""
        from nuri.quant.regime.strategy_map import print_cross_analysis

        df = pd.DataFrame([
            {"regime": "bull_low_vol", "signal_id": "rsi_oversold", "trades": 5,
             "win_rate": 1.0, "profit_factor": 999.0, "avg_return": 10.0},
        ])
        print_cross_analysis(df)
        out = capsys.readouterr().out
        assert "∞" in out


# ═══════════════════════════════════════════════════════════
# analyst_backtest.py — print_results + __main__ (lines 131-169)
# ═══════════════════════════════════════════════════════════


class TestAnalystBacktestMain:
    def test_main_block(self, monkeypatch, db_with_data):
        monkeypatch.setattr(sys, "argv", ["analyst_backtest"])
        with patch("nuri.quant.validation.analyst_backtest.validate_estimates", return_value=[]), \
             patch("nuri.quant.validation.analyst_backtest.print_results"):
            runpy.run_module("nuri.quant.validation.analyst_backtest", run_name="__main__")


class TestAnalystPrintResults:
    def test_print_results_with_data(self, capsys):
        """print_results — 결과 출력 (lines 131-149)."""
        from nuri.quant.validation.analyst_backtest import EstimateResult, print_results

        results = [
            EstimateResult(ticker="AAPL", estimate_date="2024-01-01", recommendation="Buy",
                           target_mean=250.0, price_at_estimate=200.0, actual_price=230.0,
                           actual_date="2024-04-01",
                           target_gap_pct=25.0, actual_return_pct=15.0, target_hit=True),
            EstimateResult(ticker="NVDA", estimate_date="2024-01-01", recommendation="Hold",
                           target_mean=180.0, price_at_estimate=200.0, actual_price=170.0,
                           actual_date="2024-04-01",
                           target_gap_pct=-10.0, actual_return_pct=-15.0, target_hit=False),
        ]
        print_results(results)
        out = capsys.readouterr().out
        assert "애널리스트 목표가 검증" in out
        assert "AAPL" in out
        assert "적중률" in out

    def test_print_results_empty(self, capsys):
        """print_results — 빈 결과 (line 134)."""
        from nuri.quant.validation.analyst_backtest import print_results
        print_results([])
        out = capsys.readouterr().out
        assert out == ""


# ═══════════════════════════════════════════════════════════
# monitor.py — print_monitor P&L (lines 147-156)
# ═══════════════════════════════════════════════════════════


class TestMonitorPnLDirect:
    def test_pnl_with_best_worst(self, monkeypatch, db_with_data, capsys):
        """print_monitor — P&L summary with best/worst (lines 147-156)."""
        from nuri.trading.strategy.monitor import print_monitor

        pnl = {
            "total_positions": 3, "total_pnl": 12.5, "winners": 2, "losers": 1,
            "long_pnl": 15.0, "short_pnl": -2.5, "core_pnl": 14.0, "tactical_pnl": -1.5,
            "best": {"ticker": "AAPL", "pnl": 20.0},
            "worst": {"ticker": "SH", "pnl": -5.0},
        }
        with patch("nuri.quant.regime.classifier.classify_regime") as mock_cls, \
             patch("nuri.quant.regime.classifier.print_regime"), \
             patch("nuri.trading.strategy.monitor.daily_pnl_summary", return_value=pnl):
            mock_cls.return_value = None  # print_regime mocked → skip
            print_monitor(db_path=db_with_data)
        out = capsys.readouterr().out
        assert "P&L Summary" in out
        assert "Best" in out
        assert "Worst" in out

    def test_pnl_no_positions(self, monkeypatch, db_with_data, capsys):
        """print_monitor — P&L: total_positions=0."""
        from nuri.trading.strategy.monitor import print_monitor

        pnl = {
            "total_positions": 0, "total_pnl": 0, "winners": 0, "losers": 0,
            "long_pnl": 0, "short_pnl": 0, "core_pnl": 0, "tactical_pnl": 0,
            "best": None, "worst": None,
        }
        with patch("nuri.quant.regime.classifier.classify_regime") as mock_cls, \
             patch("nuri.quant.regime.classifier.print_regime"), \
             patch("nuri.trading.strategy.monitor.daily_pnl_summary", return_value=pnl):
            mock_cls.return_value = None  # print_regime mocked → skip
            print_monitor(db_path=db_with_data)
        out = capsys.readouterr().out
        # P&L section should not appear when no positions
        assert "P&L Summary" not in out


# ═══════════════════════════════════════════════════════════
# consensus.py — print_consensus price targets + external data (lines 279-319)
# ═══════════════════════════════════════════════════════════


class TestConsensusPrintExtras:
    def test_print_consensus_with_targets(self, db_with_data, capsys):
        """print_consensus — price targets section (lines 279-292)."""
        from nuri.trading.agents.consensus import ConsensusResult, print_consensus

        results = [
            ConsensusResult(
                ticker="AAPL", final_action="BUY", final_confidence=85,
                agreement_rate=0.9, verdicts=[], dissent=[], reasoning="ok",
            ),
        ]
        with patch("nuri.trading.recommend.price_targets.calculate_targets",
                    return_value={"ticker": "AAPL", "entry_price": 200, "stop_loss": 186}), \
             patch("nuri.trading.recommend.price_targets.format_target_tree",
                    return_value="종목: AAPL\n├── 매수가: $200"):
            print_consensus(results)
        out = capsys.readouterr().out
        assert "Price Targets" in out

    def test_print_consensus_with_external(self, db_with_data, capsys):
        """print_consensus — external data section (lines 295-319)."""
        from nuri.trading.agents.consensus import ConsensusResult, print_consensus

        results = [
            ConsensusResult(
                ticker="AAPL", final_action="HOLD", final_confidence=50,
                agreement_rate=0.6, verdicts=[], dissent=[], reasoning="ok",
            ),
        ]
        ext_data = [
            {"data_type": "consensus", "value": "Strong Buy", "source": "tipranks", "numeric_value": None},
            {"data_type": "superinvestor_count", "value": "14", "source": "dataroma", "numeric_value": 14},
            {"data_type": "target_price", "value": "$273", "source": "tipranks", "numeric_value": 273.0},
        ]
        with patch("nuri.trading.recommend.price_targets.calculate_targets",
                    return_value={"error": "no data"}), \
             patch("nuri.collectors.external.get_external", return_value=ext_data):
            print_consensus(results)
        out = capsys.readouterr().out
        assert "External Data" in out
        assert "TipRanks" in out

    def test_print_consensus_targets_exception(self, db_with_data, capsys):
        """print_consensus — price targets 실패 시 건너뜀 (line 291-292)."""
        from nuri.trading.agents.consensus import ConsensusResult, print_consensus

        results = [
            ConsensusResult(
                ticker="AAPL", final_action="BUY", final_confidence=85,
                agreement_rate=0.9, verdicts=[], dissent=[], reasoning="ok",
            ),
        ]
        with patch("nuri.trading.recommend.price_targets.calculate_targets",
                    side_effect=Exception("no data")):
            print_consensus(results)
        # Should not crash


# ═══════════════════════════════════════════════════════════
# tracker.py — print_tracking_report recent section (lines 270-284)
# ═══════════════════════════════════════════════════════════


class TestTrackerPrintRecent:
    def test_print_with_recent_recommendations(self, db_with_data, capsys):
        """print_tracking_report — recent 섹션 (lines 270-284)."""
        from nuri.core.db import get_db
        from nuri.trading.recommend.tracker import print_tracking_report

        # 추천 데이터 삽입
        with get_db(db_with_data) as conn:
            conn.execute(
                """INSERT INTO recommendations
                   (date, ticker, action, confidence, signals, entry_price, outcome_30d, hit)
                   VALUES ('2024-03-01', 'AAPL', 'BUY', 80, '{}', 200.0, 15.5, 1)""",
            )
            conn.execute(
                """INSERT INTO recommendations
                   (date, ticker, action, confidence, signals, entry_price, outcome_30d, hit)
                   VALUES ('2024-03-02', 'NVDA', 'SELL', 70, '{}', 130.0, NULL, NULL)""",
            )

        print_tracking_report(db_path=db_with_data)
        out = capsys.readouterr().out
        assert "AAPL" in out
        assert "Recent" in out

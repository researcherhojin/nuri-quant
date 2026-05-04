"""strategy_map.py 브랜치 커버 — codecov 갭 (#611).

print_strategy 의 signal_regime_stats 빈 분기 (325->332).
"""

from __future__ import annotations

from nuri.quant.regime.strategy_map import StrategyRecommendation, print_strategy


class TestPrintStrategyEmptyStats:
    def test_no_signal_stats_skips_performance_block(self, capsys):
        """signal_regime_stats 가 비어있으면 'Signal Performance' 블록 출력 생략 (325 False → 332)."""
        rec = StrategyRecommendation(
            regime="sideways_high_vol",
            macro_interpretation="Neutral",
            position_sizing="defensive",
            recommended_signals=["rsi_oversold"],
            avoid_signals=["sma_dead"],
            sector_preference=["XLP", "XLU"],
            signal_regime_stats={},  # 핵심: 비어있어 325 분기 False 트리거
            notes="테스트",
        )
        print_strategy(rec)
        out = capsys.readouterr().out
        assert "Strategy Recommendation" in out
        # signal_regime_stats 비어있으면 헤더가 출력되지 않아야 함
        assert "Signal Performance" not in out

    def test_with_signal_stats_prints_performance_block(self, capsys):
        """signal_regime_stats 가 있으면 'Signal Performance' 블록 출력 (325 True 분기, 회귀 lock)."""
        rec = StrategyRecommendation(
            regime="bull_low_vol",
            macro_interpretation="Risk-on",
            position_sizing="aggressive",
            recommended_signals=["rsi_oversold"],
            avoid_signals=[],
            sector_preference=["XLK"],
            signal_regime_stats={
                "rsi_oversold": {"trades": 12, "win_rate": 0.66, "pf": 2.4, "avg_return": 3.5},
            },
            notes="ok",
        )
        print_strategy(rec)
        out = capsys.readouterr().out
        assert "Signal Performance" in out
        assert "rsi_oversold" in out

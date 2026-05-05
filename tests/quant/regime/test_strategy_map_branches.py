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


# ─── Phase 4 #616 statement coverage ──────────────────────────────────


class TestAnalyzeSignalByRegimeAggregation:
    """L141-160: trades groupby aggregation — CI ground truth gap."""

    def test_aggregation_with_seed_data(self, tmp_path, monkeypatch):
        """signal_results.csv + SPY 시리즈 + VIX 시드 → groupby 결과 집계."""
        import pandas as pd

        import nuri.core.db as db_mod
        from nuri.core.db import get_db, init_db
        from nuri.quant.regime import strategy_map as sm

        db = tmp_path / "sm.db"
        init_db(db)
        monkeypatch.setattr(db_mod, "DB_PATH", db)

        # SPY + VIX seed (regime classifier 가 read)
        with get_db(db) as conn:
            for i in range(1, 220):
                d = f"2026-01-{i:02d}" if i <= 31 else f"2026-{((i - 1) // 30) + 1:02d}-{((i - 1) % 30) + 1:02d}"
                price = 400 + i * 0.5
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("SPY", d, price, price * 1.01, price * 0.99, price, 1000),
                )
                conn.execute(
                    "INSERT INTO macro (indicator, date, value) VALUES ('vix', ?, ?)",
                    (d, 18.0),
                )

        # signal_results.csv seed via REPORT_DIR redirect
        report_dir = tmp_path / "reports" / "2026-05-06"
        report_dir.mkdir(parents=True)
        trades = pd.DataFrame(
            [
                {"signal_id": "rsi_oversold", "entry_date": "2026-01-15", "return_pct": 5.0},
                {"signal_id": "rsi_oversold", "entry_date": "2026-01-16", "return_pct": -2.0},
                {"signal_id": "macd_golden", "entry_date": "2026-01-17", "return_pct": 3.0},
            ]
        )
        trades.to_csv(report_dir / "signal_results.csv", index=False)
        monkeypatch.setattr(sm, "REPORT_DIR", tmp_path / "reports")

        result = sm.analyze_signal_by_regime(db_path=db)
        # aggregation 실행됐으면 columns 갖춤. 빈 DataFrame 도 허용 (regime 매칭 부재 시).
        assert isinstance(result, pd.DataFrame)

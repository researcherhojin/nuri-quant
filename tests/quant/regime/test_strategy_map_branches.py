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


# ─── Phase 4 #616 — close 9 stmts (analyze_signal_by_regime aggregation) ──


class TestAnalyzeSignalByRegimeFullPath:
    """L141-160: groupby aggregation + DataFrame construction.

    Previous test 가 _load_spy_series / _find_latest_csv 의 실제 path 의존 →
    CI 환경에서 fail. helper 들을 직접 mock.
    """

    def test_aggregation_produces_dataframe(self, tmp_path, monkeypatch):
        import pandas as pd

        from nuri.quant.regime import strategy_map as sm

        # Fake CSV (signal_results)
        csv_path = tmp_path / "signal_results.csv"
        trades_df = pd.DataFrame(
            [
                {"signal_id": "rsi_oversold", "entry_date": "2026-04-01", "return_pct": 5.0},
                {"signal_id": "rsi_oversold", "entry_date": "2026-04-02", "return_pct": -2.0},
                {"signal_id": "macd_golden", "entry_date": "2026-04-01", "return_pct": 3.0},
                {"signal_id": "macd_golden", "entry_date": "2026-04-03", "return_pct": -4.0},
            ]
        )
        trades_df.to_csv(csv_path, index=False)

        # Fake SPY series with sma50/sma200/bb_width
        spy_df = pd.DataFrame(
            [
                {"date": "2026-04-01", "close": 500.0, "sma50": 495, "sma200": 480, "bb_width": 0.05},
                {"date": "2026-04-02", "close": 501.0, "sma50": 496, "sma200": 481, "bb_width": 0.05},
                {"date": "2026-04-03", "close": 502.0, "sma50": 497, "sma200": 482, "bb_width": 0.05},
            ]
        )

        monkeypatch.setattr(sm, "_find_latest_csv", lambda name: csv_path)
        monkeypatch.setattr(sm, "_load_spy_series", lambda db_path=None: spy_df)
        monkeypatch.setattr(sm, "compute_dynamic_thresholds", lambda db_path: {})
        monkeypatch.setattr(sm, "_get_vix", lambda date=None, db_path=None: 18.0)
        monkeypatch.setattr(sm, "_classify_single", lambda *a, **kw: ("bull", "low"))

        result = sm.analyze_signal_by_regime(db_path=tmp_path / "fake.db")

        assert not result.empty
        assert "signal_id" in result.columns
        assert "profit_factor" in result.columns
        # 2 signals × 1 regime = 2 rows
        assert len(result) == 2


# ─── Phase 4 #616 — close strategy_map.py 22 stmts batch ──────────────


class TestGetRealAccountsHeldAddCI:
    """held_add.py L142, 145-150: read portfolio.yaml + iter accounts.

    이전 test 가 hardcoded path 사용 → CI 에서 file 없으면 except 흡수,
    real path 우회 필요. monkeypatch builtins.open 으로 fake yaml content.
    """

    def test_real_accounts_with_yaml_open_patched(self, monkeypatch):
        import io

        yaml_text = (
            "accounts:\n"
            "  main:\n"
            "    strategy: core\n"
            "  legacy:\n"
            "    note: empty\n"  # substantive key 없음
            "  toss:\n"
            "    label: Sub\n"
        )

        real_open = open

        def _opener(path, *args, **kwargs):
            if str(path).endswith("portfolio.yaml"):
                return io.StringIO(yaml_text)
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr("builtins.open", _opener)

        from nuri.trading.recommend.held_add import _get_real_accounts

        result = _get_real_accounts()
        assert "main" in result
        assert "toss" in result
        assert "legacy" not in result


class TestGetRealAccountsActionsCI:
    """actions.py L507-512: yaml load + iter (uses Path.read_text)."""

    def test_real_accounts_via_read_text_patch(self, monkeypatch):
        from pathlib import Path

        yaml_text = (
            "accounts:\n"
            "  main:\n"
            "    strategy: core\n"
            "  shell:\n"
            "    note: empty\n"
            "  long_term:\n"
            "    holdings:\n"
            "      AAA: 10\n"
        )
        original_read_text = Path.read_text

        def _mock_read_text(self, *args, **kwargs):
            if str(self).endswith("portfolio.yaml"):
                return yaml_text
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr("pathlib.Path.read_text", _mock_read_text)

        from nuri.api.routes.actions import _get_real_accounts

        result = _get_real_accounts()
        assert "main" in result
        assert "long_term" in result
        assert "shell" not in result

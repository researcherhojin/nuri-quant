"""D-3 레짐별 전략 매핑 테스트."""
import pandas as pd
import pytest

from nuri.core.db import init_db


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


# ═══════════════════════════════════════════════════════
# 상수 / 규칙 테이블
# ═══════════════════════════════════════════════════════

class TestPositionRules:
    def test_all_combos(self):
        from nuri.quant.regime.strategy_map import POSITION_RULES
        assert POSITION_RULES[("bull", "low")] == "aggressive"
        assert POSITION_RULES[("bull", "high")] == "normal"
        assert POSITION_RULES[("sideways", "low")] == "normal"
        assert POSITION_RULES[("sideways", "high")] == "defensive"
        assert POSITION_RULES[("bear", "low")] == "defensive"
        assert POSITION_RULES[("bear", "high")] == "minimal"

    def test_sector_rules(self):
        from nuri.quant.regime.strategy_map import SECTOR_RULES
        assert "XLK" in SECTOR_RULES["aggressive"]
        assert "XLP" in SECTOR_RULES["defensive"]
        assert "XLP" in SECTOR_RULES["minimal"]


class TestConstants:
    def test_thresholds(self):
        from nuri.quant.regime.strategy_map import PF_AVOID_THRESHOLD, PF_RECOMMEND_THRESHOLD
        assert PF_RECOMMEND_THRESHOLD == 1.5
        assert PF_AVOID_THRESHOLD == 1.0

    def test_sector_classifications(self):
        from nuri.quant.regime.strategy_map import DEFENSIVE_SECTORS, GROWTH_SECTORS
        assert "XLP" in DEFENSIVE_SECTORS
        assert "XLK" in GROWTH_SECTORS


# ═══════════════════════════════════════════════════════
# StrategyRecommendation
# ═══════════════════════════════════════════════════════

class TestStrategyRecommendation:
    def test_create(self):
        from nuri.quant.regime.strategy_map import StrategyRecommendation
        rec = StrategyRecommendation(
            regime="bull_low_vol", macro_interpretation="양호",
            position_sizing="aggressive",
            recommended_signals=["rsi_oversold"], avoid_signals=["macd_dead"],
            sector_preference=["XLK"], signal_regime_stats={}, notes="test",
        )
        assert rec.position_sizing == "aggressive"


# ═══════════════════════════════════════════════════════
# _build_data_driven_strategy
# ═══════════════════════════════════════════════════════

class TestBuildDataDrivenStrategy:
    def test_empty_df(self):
        from nuri.quant.regime.strategy_map import _build_data_driven_strategy
        result = _build_data_driven_strategy("bull_low_vol", pd.DataFrame())
        assert result["recommended"] == []
        assert result["avoid"] == []

    def test_with_data(self):
        from nuri.quant.regime.strategy_map import _build_data_driven_strategy
        cross_df = pd.DataFrame([
            {"signal_id": "rsi_oversold", "regime": "bull_low_vol", "trades": 10, "win_rate": 0.7, "avg_return": 5.0, "profit_factor": 2.5},
            {"signal_id": "macd_dead", "regime": "bull_low_vol", "trades": 8, "win_rate": 0.3, "avg_return": -2.0, "profit_factor": 0.6},
            {"signal_id": "bb_bounce", "regime": "bull_low_vol", "trades": 3, "win_rate": 0.5, "avg_return": 1.0, "profit_factor": 1.2},  # < 5 trades
        ])
        result = _build_data_driven_strategy("bull_low_vol", cross_df)
        assert "rsi_oversold" in result["recommended"]
        assert "macd_dead" in result["avoid"]
        # bb_bounce has < 5 trades, so not in either list
        assert "bb_bounce" not in result["recommended"]
        assert "bb_bounce" not in result["avoid"]
        assert "rsi_oversold" in result["stats"]

    def test_wrong_regime(self):
        from nuri.quant.regime.strategy_map import _build_data_driven_strategy
        cross_df = pd.DataFrame([
            {"signal_id": "rsi", "regime": "bear_high_vol", "trades": 10, "win_rate": 0.7, "avg_return": 5.0, "profit_factor": 2.5},
        ])
        result = _build_data_driven_strategy("bull_low_vol", cross_df)
        assert result["recommended"] == []


# ═══════════════════════════════════════════════════════
# _find_latest_csv
# ═══════════════════════════════════════════════════════

class TestFindLatestCsv:
    def test_no_report_dir(self, tmp_path, monkeypatch):
        import nuri.quant.regime.strategy_map as sm
        monkeypatch.setattr(sm, "REPORT_DIR", tmp_path / "nonexistent")
        result = sm._find_latest_csv("signal_results.csv")
        assert result is None

    def test_finds_latest(self, tmp_path, monkeypatch):
        import nuri.quant.regime.strategy_map as sm

        # 2개 날짜 디렉토리
        d1 = tmp_path / "2026-03-27"
        d1.mkdir()
        d2 = tmp_path / "2026-03-28"
        d2.mkdir()
        (d2 / "signal_results.csv").write_text("data")

        monkeypatch.setattr(sm, "REPORT_DIR", tmp_path)
        result = sm._find_latest_csv("signal_results.csv")
        assert result is not None
        assert "2026-03-28" in str(result)


# ═══════════════════════════════════════════════════════
# print 함수
# ═══════════════════════════════════════════════════════

class TestPrintStrategy:
    def test_none(self, capsys):
        from nuri.quant.regime.strategy_map import print_strategy
        print_strategy(None)
        output = capsys.readouterr().out
        assert "불가" in output

    def test_with_rec(self, capsys):
        from nuri.quant.regime.strategy_map import StrategyRecommendation, print_strategy
        rec = StrategyRecommendation(
            regime="bull_low_vol", macro_interpretation="양호",
            position_sizing="aggressive",
            recommended_signals=["rsi_oversold"], avoid_signals=["macd_dead"],
            sector_preference=["XLK"],
            signal_regime_stats={"rsi_oversold": {"trades": 10, "win_rate": 0.7, "pf": 2.5, "avg_return": 5.0}},
            notes="test",
        )
        print_strategy(rec)
        output = capsys.readouterr().out
        assert "bull_low_vol" in output
        assert "rsi_oversold" in output

    def test_with_stats(self, capsys):
        from nuri.quant.regime.strategy_map import StrategyRecommendation, print_strategy
        rec = StrategyRecommendation(
            regime="bear_high_vol", macro_interpretation="악화",
            position_sizing="minimal",
            recommended_signals=[], avoid_signals=["macd_golden"],
            sector_preference=["XLP"],
            signal_regime_stats={"macd_golden": {"trades": 8, "win_rate": 0.3, "pf": 0.6, "avg_return": -2.0}},
            notes="최소 포지션",
        )
        print_strategy(rec)
        output = capsys.readouterr().out
        assert "MINIMAL" in output


class TestPrintCrossAnalysis:
    def test_empty(self, capsys):
        from nuri.quant.regime.strategy_map import print_cross_analysis
        print_cross_analysis(pd.DataFrame())
        output = capsys.readouterr().out
        assert "없음" in output

    def test_with_data(self, capsys):
        from nuri.quant.regime.strategy_map import print_cross_analysis
        df = pd.DataFrame([
            {"signal_id": "rsi_oversold", "regime": "bull_low_vol", "trades": 10, "win_rate": 0.7, "avg_return": 5.0, "profit_factor": 2.5},
            {"signal_id": "macd_dead", "regime": "bear_high_vol", "trades": 8, "win_rate": 0.3, "avg_return": -2.0, "profit_factor": 0.6},
        ])
        print_cross_analysis(df)
        output = capsys.readouterr().out
        assert "bull_low_vol" in output
        assert "bear_high_vol" in output

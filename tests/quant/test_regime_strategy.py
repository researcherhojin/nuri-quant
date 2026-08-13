"""Tests for regime_strategy — split from test_quant_all.py."""

from datetime import timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from nuri.core.timezone import kst_now, today_kst
from tests.quant._helpers import (  # noqa: F401
    _insert_spy_data,
    _insert_spy_data_trend,
    _seed_macro,
    _seed_portfolio,
    _seed_prices,
    _seed_spy_data,
)


class TestStrategyMap:
    """D-3 (from test_regime.py).

    classify_regime을 직접 호출하면 xdist shard에서 다른 테스트의
    mock leak로 Exception("skip") 발생 가능 (#85).
    regime_state를 명시적으로 전달하여 우회.
    """

    def test_bull_strategy(self, bull_market):
        from nuri.quant.regime.classifier import classify_regime
        from nuri.quant.regime.strategy_map import map_regime_to_strategy

        regime = classify_regime(db_path=bull_market)
        rec = map_regime_to_strategy(regime_state=regime, db_path=bull_market)
        assert rec is not None
        assert rec.position_sizing == "aggressive"
        assert len(rec.recommended_signals) > 0

    def test_bear_strategy(self, bear_market):
        from nuri.quant.regime.classifier import classify_regime
        from nuri.quant.regime.strategy_map import map_regime_to_strategy

        regime = classify_regime(db_path=bear_market)
        rec = map_regime_to_strategy(regime_state=regime, db_path=bear_market)
        assert rec is not None
        assert rec.position_sizing in ("defensive", "minimal")

    def test_no_data(self, db_path):
        from unittest.mock import patch

        from nuri.quant.regime.strategy_map import map_regime_to_strategy

        # classify_regime을 source 레벨에서 mock → xdist shard mock leak 차단 (#85)
        with patch("nuri.quant.regime.strategy_map.classify_regime", return_value=None):
            rec = map_regime_to_strategy(db_path=db_path)
        assert rec is None

    def test_strategy_has_sector_preference(self, bull_market):
        from nuri.quant.regime.classifier import classify_regime
        from nuri.quant.regime.strategy_map import map_regime_to_strategy

        regime = classify_regime(db_path=bull_market)
        rec = map_regime_to_strategy(regime_state=regime, db_path=bull_market)
        assert rec is not None
        assert len(rec.sector_preference) > 0


class TestPositionRules:
    """(from test_strategy_map.py)."""

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


class TestStrategyMapConstants:
    """(from test_strategy_map.py)."""

    def test_thresholds(self):
        from nuri.quant.regime.strategy_map import PF_AVOID_THRESHOLD, PF_RECOMMEND_THRESHOLD

        assert PF_RECOMMEND_THRESHOLD == 1.5
        assert PF_AVOID_THRESHOLD == 1.0

    def test_sector_classifications(self):
        from nuri.quant.regime.strategy_map import DEFENSIVE_SECTORS, GROWTH_SECTORS

        assert "XLP" in DEFENSIVE_SECTORS
        assert "XLK" in GROWTH_SECTORS


class TestStrategyRecommendation:
    """(from test_strategy_map.py)."""

    def test_create(self):
        from nuri.quant.regime.strategy_map import StrategyRecommendation

        rec = StrategyRecommendation(
            regime="bull_low_vol",
            macro_interpretation="양호",
            position_sizing="aggressive",
            recommended_signals=["rsi_oversold"],
            avoid_signals=["macd_dead"],
            sector_preference=["XLK"],
            signal_regime_stats={},
            notes="test",
        )
        assert rec.position_sizing == "aggressive"


class TestBuildDataDrivenStrategy:
    """(from test_strategy_map.py)."""

    def test_empty_df(self):
        from nuri.quant.regime.strategy_map import _build_data_driven_strategy

        result = _build_data_driven_strategy("bull_low_vol", pd.DataFrame())
        assert result["recommended"] == []
        assert result["avoid"] == []

    def test_with_data(self):
        from nuri.quant.regime.strategy_map import _build_data_driven_strategy

        cross_df = pd.DataFrame(
            [
                {
                    "signal_id": "rsi_oversold",
                    "regime": "bull_low_vol",
                    "trades": 10,
                    "win_rate": 0.7,
                    "avg_return": 5.0,
                    "profit_factor": 2.5,
                },
                {
                    "signal_id": "macd_dead",
                    "regime": "bull_low_vol",
                    "trades": 8,
                    "win_rate": 0.3,
                    "avg_return": -2.0,
                    "profit_factor": 0.6,
                },
                {
                    "signal_id": "bb_bounce",
                    "regime": "bull_low_vol",
                    "trades": 3,
                    "win_rate": 0.5,
                    "avg_return": 1.0,
                    "profit_factor": 1.2,
                },
            ]
        )
        result = _build_data_driven_strategy("bull_low_vol", cross_df)
        assert "rsi_oversold" in result["recommended"]
        assert "macd_dead" in result["avoid"]
        assert "bb_bounce" not in result["recommended"]
        assert "bb_bounce" not in result["avoid"]
        assert "rsi_oversold" in result["stats"]

    def test_wrong_regime(self):
        from nuri.quant.regime.strategy_map import _build_data_driven_strategy

        cross_df = pd.DataFrame(
            [
                {
                    "signal_id": "rsi",
                    "regime": "bear_high_vol",
                    "trades": 10,
                    "win_rate": 0.7,
                    "avg_return": 5.0,
                    "profit_factor": 2.5,
                },
            ]
        )
        result = _build_data_driven_strategy("bull_low_vol", cross_df)
        assert result["recommended"] == []


class TestFindLatestCsv:
    """(from test_strategy_map.py)."""

    def test_no_report_dir(self, tmp_path, monkeypatch):
        import nuri.quant.regime.strategy_map as sm

        monkeypatch.setattr(sm, "REPORT_DIR", tmp_path / "nonexistent")
        result = sm._find_latest_csv("signal_results.csv")
        assert result is None

    def test_dir_exists_no_csv(self, tmp_path, monkeypatch):
        """REPORT_DIR 존재하지만 csv 없는 디렉토리만 → None (line 163)."""
        import nuri.quant.regime.strategy_map as sm

        d = tmp_path / "2026-03-27"
        d.mkdir()
        # signal_results.csv 없음
        monkeypatch.setattr(sm, "REPORT_DIR", tmp_path)
        result = sm._find_latest_csv("signal_results.csv")
        assert result is None

    def test_finds_latest(self, tmp_path, monkeypatch):
        import nuri.quant.regime.strategy_map as sm

        d1 = tmp_path / "2026-03-27"
        d1.mkdir()
        d2 = tmp_path / "2026-03-28"
        d2.mkdir()
        (d2 / "signal_results.csv").write_text("data")
        monkeypatch.setattr(sm, "REPORT_DIR", tmp_path)
        result = sm._find_latest_csv("signal_results.csv")
        assert result is not None
        assert "2026-03-28" in str(result)


class TestPrintStrategy:
    """(from test_strategy_map.py)."""

    def test_none(self, capsys):
        from nuri.quant.regime.strategy_map import print_strategy

        print_strategy(None)
        output = capsys.readouterr().out
        assert "불가" in output

    def test_with_rec(self, capsys):
        from nuri.quant.regime.strategy_map import StrategyRecommendation, print_strategy

        rec = StrategyRecommendation(
            regime="bull_low_vol",
            macro_interpretation="양호",
            position_sizing="aggressive",
            recommended_signals=["rsi_oversold"],
            avoid_signals=["macd_dead"],
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
            regime="bear_high_vol",
            macro_interpretation="악화",
            position_sizing="minimal",
            recommended_signals=[],
            avoid_signals=["macd_golden"],
            sector_preference=["XLP"],
            signal_regime_stats={"macd_golden": {"trades": 8, "win_rate": 0.3, "pf": 0.6, "avg_return": -2.0}},
            notes="최소 포지션",
        )
        print_strategy(rec)
        output = capsys.readouterr().out
        assert "MINIMAL" in output


class TestPrintCrossAnalysis:
    """(from test_strategy_map.py)."""

    def test_empty(self, capsys):
        from nuri.quant.regime.strategy_map import print_cross_analysis

        print_cross_analysis(pd.DataFrame())
        output = capsys.readouterr().out
        assert "없음" in output

    def test_with_data(self, capsys):
        from nuri.quant.regime.strategy_map import print_cross_analysis

        df = pd.DataFrame(
            [
                {
                    "signal_id": "rsi_oversold",
                    "regime": "bull_low_vol",
                    "trades": 10,
                    "win_rate": 0.7,
                    "avg_return": 5.0,
                    "profit_factor": 2.5,
                },
                {
                    "signal_id": "macd_dead",
                    "regime": "bear_high_vol",
                    "trades": 8,
                    "win_rate": 0.3,
                    "avg_return": -2.0,
                    "profit_factor": 0.6,
                },
            ]
        )
        print_cross_analysis(df)
        output = capsys.readouterr().out
        assert "bull_low_vol" in output
        assert "bear_high_vol" in output


class TestAnalyzeSignalByRegimeBranches:
    """analyze_signal_by_regime 의 early return 분기 (lines 102, 106, 111, 132)."""

    def test_no_csv_returns_empty(self, tmp_path, monkeypatch):
        from nuri.quant.regime import strategy_map as sm

        monkeypatch.setattr(sm, "_find_latest_csv", lambda fn: None)
        result = sm.analyze_signal_by_regime()
        assert result.empty

    def test_empty_csv_returns_empty(self, tmp_path, monkeypatch):
        from nuri.quant.regime import strategy_map as sm

        empty_csv = tmp_path / "signal_results.csv"
        empty_csv.write_text("entry_date,signal_id,return_pct\n")
        monkeypatch.setattr(sm, "_find_latest_csv", lambda fn: empty_csv)
        result = sm.analyze_signal_by_regime()
        assert result.empty

    def test_empty_spy_returns_empty(self, tmp_path, monkeypatch):
        from nuri.quant.regime import strategy_map as sm

        csv = tmp_path / "signal_results.csv"
        csv.write_text("entry_date,signal_id,return_pct\n2024-01-01,rsi_oversold,5.0\n")
        monkeypatch.setattr(sm, "_find_latest_csv", lambda fn: csv)
        monkeypatch.setattr(sm, "_load_spy_series", lambda db_path=None: pd.DataFrame())
        result = sm.analyze_signal_by_regime()
        assert result.empty

    def test_dates_dont_match_returns_empty(self, tmp_path, monkeypatch, db_path):
        """trades 의 entry_date 가 spy_df 와 매칭 안 되면 빈 result (line 132)."""
        from nuri.quant.regime import strategy_map as sm

        csv = tmp_path / "signal_results.csv"
        csv.write_text("entry_date,signal_id,return_pct\n1990-01-01,rsi_oversold,5.0\n")
        monkeypatch.setattr(sm, "_find_latest_csv", lambda fn: csv)

        # SPY 시계열은 다른 날짜 → 매칭 실패
        spy_df = pd.DataFrame(
            {
                "date": ["2024-01-01"],
                "close": [400],
                "sma50": [395],
                "sma200": [390],
                "bb_width": [0.1],
            }
        )
        monkeypatch.setattr(sm, "_load_spy_series", lambda db_path=None: spy_df)
        result = sm.analyze_signal_by_regime(db_path=db_path)
        assert result.empty


class TestBuildDataDrivenStrategyReliable:
    """reliable.empty (line 185)."""

    def test_no_signal_above_min_trades(self):
        from nuri.quant.regime.strategy_map import _build_data_driven_strategy

        # trades < 5 인 시그널만
        cross_df = pd.DataFrame(
            [
                {
                    "signal_id": "rsi_oversold",
                    "regime": "bull_low_vol",
                    "trades": 3,
                    "win_rate": 0.7,
                    "avg_return": 5.0,
                    "profit_factor": 2.5,
                },
            ]
        )
        result = _build_data_driven_strategy("bull_low_vol", cross_df)
        assert result["recommended"] == []
        assert result["avoid"] == []


class TestMapStrategySpecialAndFallback:
    """special_regime sizing (line 225) + rule-based fallback (lines 242-251) +
    high vol (lines 256-261) + macro adjust (273-279).

    ⚠️ 이 클래스의 테스트는 `map_regime_to_strategy()` 를 `db_path` 없이 부른다.
    그러면 내부의 `analyze_signal_by_regime(None)` 이 **실제 `data/portfolio.db`**
    로 들어가고, `_get_vix()` 가 SPY 행마다 호출되면서 커넥션을 **1,118회** 연다
    (2026-08-14 실측, 테스트당 2.25초). 그 자체로 느린 것도 문제지만, 진짜 문제는
    다른 테스트가 같은 파일에 **쓴다**는 것이다 (`tests/CLAUDE.md` 참조) —
    `-n auto` 로 워커가 붙으면 읽는 쪽이 간헐적으로 깨진다. 실제로
    `test_high_vol_no_stats_truncates` 가 전체 실행 5회 중 1회 실패했고,
    단독 실행은 항상 통과했다.

    `db_path_mp` 가 `nuri.core.db.DB_PATH` 를 tmp DB 로 돌린다 → 커넥션 1회,
    실 DB 무접근. 단언은 그대로 성립한다(실측) — 이 테스트들이 보는 것은
    포지션 사이징·폴백·절삭 **분기**이지 교차분석 데이터가 아니기 때문이다.
    """

    @pytest.fixture(autouse=True)
    def _isolate_db(self, db_path_mp):
        """클래스 전체에 DB 격리 강제. 새 테스트가 이 함정을 다시 밟지 않게."""

    def test_special_regime_sizing(self):
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore
        from nuri.quant.regime.strategy_map import map_regime_to_strategy

        regime = RegimeState(
            date="2025-06-15",
            trend="bull",
            volatility="low",
            regime="recovery",
            confidence=0.8,
            details={"special_regime": "recovery"},
        )
        macro = MacroScore(
            date="2025-06-15",
            total_score=50,
            yield_curve_score=50,
            vix_score=50,
            sentiment_score=50,
            employment_score=50,
            inflation_score=50,
            monetary_score=50,
            yield_spread_3m10y_score=50,
            put_call_ratio_score=50,
            event_score=0,
            interpretation="Neutral",
            warnings=[],
            details={},
        )
        rec = map_regime_to_strategy(regime_state=regime, macro_score=macro)
        assert rec is not None
        # SPECIAL_REGIME_SIZING['recovery'] 적용

    def test_rule_fallback_bear(self):
        """trend == 'bear' rule fallback (line 245-247)."""
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore
        from nuri.quant.regime.strategy_map import map_regime_to_strategy

        regime = RegimeState(
            date="2025-06-15",
            trend="bear",
            volatility="low",
            regime="bear_low_vol",
            confidence=0.8,
            details={},
        )
        macro = MacroScore(
            date="2025-06-15",
            total_score=50,
            yield_curve_score=50,
            vix_score=50,
            sentiment_score=50,
            employment_score=50,
            inflation_score=50,
            monetary_score=50,
            yield_spread_3m10y_score=50,
            put_call_ratio_score=50,
            event_score=0,
            interpretation="Neutral",
            warnings=[],
            details={},
        )
        rec = map_regime_to_strategy(regime_state=regime, macro_score=macro)
        assert rec is not None
        assert "rsi_overbought" in rec.recommended_signals or "macd_dead" in rec.recommended_signals

    def test_rule_fallback_sideways(self, monkeypatch):
        """trend == 'sideways' rule fallback (line 248-250)."""
        from nuri.quant.regime import strategy_map as sm
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore

        # 데이터 부족 강제 (recommended empty)
        monkeypatch.setattr(
            sm,
            "_build_data_driven_strategy",
            lambda r, df: {
                "recommended": [],
                "avoid": [],
                "stats": {},
            },
        )

        regime = RegimeState(
            date="2025-06-15",
            trend="sideways",
            volatility="low",
            regime="sideways_low_vol",
            confidence=0.8,
            details={},
        )
        macro = MacroScore(
            date="2025-06-15",
            total_score=50,
            yield_curve_score=50,
            vix_score=50,
            sentiment_score=50,
            employment_score=50,
            inflation_score=50,
            monetary_score=50,
            yield_spread_3m10y_score=50,
            put_call_ratio_score=50,
            event_score=0,
            interpretation="Neutral",
            warnings=[],
            details={},
        )
        rec = sm.map_regime_to_strategy(regime_state=regime, macro_score=macro)
        assert rec is not None
        assert "rsi_oversold" in rec.recommended_signals
        assert "bb_bounce" in rec.recommended_signals

    def test_high_vol_with_stats_truncates(self, monkeypatch):
        """high vol + recommended > 2 + stats 있음 → PF 상위 2개 유지 (lines 256-258)."""
        from nuri.quant.regime import strategy_map as sm
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore

        # data_strategy 가 4개 추천 + stats 가 채워진 상태로 mocking
        monkeypatch.setattr(
            sm,
            "_build_data_driven_strategy",
            lambda r, df: {
                "recommended": ["a", "b", "c", "d"],
                "avoid": [],
                "stats": {"a": {"pf": 1.0}, "b": {"pf": 3.0}, "c": {"pf": 2.0}, "d": {"pf": 0.5}},
            },
        )

        regime = RegimeState(
            date="2025-06-15",
            trend="bull",
            volatility="high",
            regime="bull_high_vol",
            confidence=0.8,
            details={},
        )
        macro = MacroScore(
            date="2025-06-15",
            total_score=50,
            yield_curve_score=50,
            vix_score=50,
            sentiment_score=50,
            employment_score=50,
            inflation_score=50,
            monetary_score=50,
            yield_spread_3m10y_score=50,
            put_call_ratio_score=50,
            event_score=0,
            interpretation="Neutral",
            warnings=[],
            details={},
        )
        rec = sm.map_regime_to_strategy(regime_state=regime, macro_score=macro)
        assert rec is not None
        # 상위 2개만 → b, c
        assert rec.recommended_signals == ["b", "c"]

    def test_high_vol_no_stats_truncates(self, monkeypatch):
        """high vol + stats 없음 → 단순 [:2] (line 260)."""
        from nuri.quant.regime import strategy_map as sm
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore

        monkeypatch.setattr(
            sm,
            "_build_data_driven_strategy",
            lambda r, df: {
                "recommended": ["a", "b", "c"],
                "avoid": [],
                "stats": {},
            },
        )

        regime = RegimeState(
            date="2025-06-15",
            trend="bull",
            volatility="high",
            regime="bull_high_vol",
            confidence=0.8,
            details={},
        )
        macro = MacroScore(
            date="2025-06-15",
            total_score=50,
            yield_curve_score=50,
            vix_score=50,
            sentiment_score=50,
            employment_score=50,
            inflation_score=50,
            monetary_score=50,
            yield_spread_3m10y_score=50,
            put_call_ratio_score=50,
            event_score=0,
            interpretation="Neutral",
            warnings=[],
            details={},
        )
        rec = sm.map_regime_to_strategy(regime_state=regime, macro_score=macro)
        assert rec is not None
        assert len(rec.recommended_signals) == 2

    def test_macro_adverse_forces_defensive(self, monkeypatch):
        """macro < 30 + position aggressive/normal → defensive (lines 273-275)."""
        from nuri.quant.regime import strategy_map as sm
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore

        monkeypatch.setattr(
            sm,
            "_build_data_driven_strategy",
            lambda r, df: {
                "recommended": ["x"],
                "avoid": [],
                "stats": {},
            },
        )

        regime = RegimeState(
            date="2025-06-15",
            trend="bull",
            volatility="low",
            regime="bull_low_vol",
            confidence=0.8,
            details={},
        )
        macro = MacroScore(
            date="2025-06-15",
            total_score=20,  # < 30
            yield_curve_score=50,
            vix_score=50,
            sentiment_score=50,
            employment_score=50,
            inflation_score=50,
            monetary_score=50,
            yield_spread_3m10y_score=50,
            put_call_ratio_score=50,
            event_score=0,
            interpretation="Adverse",
            warnings=[],
            details={},
        )
        rec = sm.map_regime_to_strategy(regime_state=regime, macro_score=macro)
        assert rec is not None
        assert rec.position_sizing == "defensive"

    def test_macro_favorable_relaxes_defensive(self, monkeypatch):
        """macro > 70 + position defensive → normal (lines 276-279)."""
        from nuri.quant.regime import strategy_map as sm
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore

        monkeypatch.setattr(
            sm,
            "_build_data_driven_strategy",
            lambda r, df: {
                "recommended": ["x"],
                "avoid": [],
                "stats": {},
            },
        )

        regime = RegimeState(
            date="2025-06-15",
            trend="bear",
            volatility="low",
            regime="bear_low_vol",
            confidence=0.8,
            details={},
        )
        macro = MacroScore(
            date="2025-06-15",
            total_score=80,  # > 70
            yield_curve_score=50,
            vix_score=50,
            sentiment_score=50,
            employment_score=50,
            inflation_score=50,
            monetary_score=50,
            yield_spread_3m10y_score=50,
            put_call_ratio_score=50,
            event_score=0,
            interpretation="Favorable",
            warnings=[],
            details={},
        )
        rec = sm.map_regime_to_strategy(regime_state=regime, macro_score=macro)
        assert rec is not None
        assert rec.position_sizing == "normal"

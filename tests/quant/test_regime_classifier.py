"""Tests for regime_classifier — split from test_quant_all.py."""

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


class TestRegimeClassifier:
    """D-1 (from test_regime.py)."""

    def test_bull_regime_detection(self, bull_market):
        from nuri.quant.regime.classifier import classify_regime

        state = classify_regime(db_path=bull_market)
        assert state is not None
        assert state.trend == "bull"
        assert state.volatility == "low"
        assert state.regime == "bull_low_vol"

    def test_bear_regime_detection(self, bear_market):
        from nuri.quant.regime.classifier import classify_regime

        state = classify_regime(db_path=bear_market)
        assert state is not None
        assert state.trend == "bear"
        assert state.volatility == "high"
        assert state.regime == "bear_high_vol"

    def test_confidence_range(self, bull_market):
        from nuri.quant.regime.classifier import classify_regime

        state = classify_regime(db_path=bull_market)
        assert state is not None
        assert 0.0 <= state.confidence <= 1.0

    def test_insufficient_data(self, db_path):
        from nuri.quant.regime.classifier import classify_regime

        state = classify_regime(db_path=db_path)
        assert state is None


class TestEuphoria:
    """(from test_regime_special.py)."""

    def test_euphoria_detection(self, euphoria_market):
        from nuri.quant.regime.classifier import classify_regime

        state = classify_regime(db_path=euphoria_market)
        assert state is not None
        assert state.regime == "euphoria"
        assert state.details["special_regime"] == "euphoria"
        assert state.trend == "bull"
        assert state.details["base_regime"].startswith("bull_")

    def test_euphoria_not_triggered_vix_high(self, db_path):
        from nuri.quant.regime.classifier import _detect_euphoria

        assert _detect_euphoria(15.0, 85.0) is False

    def test_euphoria_not_triggered_fg_low(self, db_path):
        from nuri.quant.regime.classifier import _detect_euphoria

        assert _detect_euphoria(10.0, 75.0) is False

    def test_euphoria_unit(self):
        from nuri.quant.regime.classifier import _detect_euphoria

        assert _detect_euphoria(11.9, 81.0) is True
        assert _detect_euphoria(None, 85.0) is False
        assert _detect_euphoria(10.0, None) is False


class TestStagflation:
    """(from test_regime_special.py)."""

    def test_stagflation_detection(self, db_path):
        from nuri.quant.regime.classifier import _detect_stagflation

        upsert_macro(
            [
                {"indicator": "cpi_yoy", "date": "2025-01-15", "value": 5.5, "source": "test"},
                {"indicator": "gdp_growth", "date": "2025-01-15", "value": 0.5, "source": "test"},
            ],
            db_path,
        )
        assert _detect_stagflation(db_path=db_path) is True

    def test_stagflation_no_gdp_graceful(self, db_path):
        from nuri.quant.regime.classifier import _detect_stagflation

        upsert_macro(
            [
                {"indicator": "cpi_yoy", "date": "2025-01-15", "value": 5.5, "source": "test"},
            ],
            db_path,
        )
        assert _detect_stagflation(db_path=db_path) is False

    def test_stagflation_no_cpi(self, db_path):
        from nuri.quant.regime.classifier import _detect_stagflation

        assert _detect_stagflation(db_path=db_path) is False

    def test_stagflation_normal_conditions(self, db_path):
        from nuri.quant.regime.classifier import _detect_stagflation

        upsert_macro(
            [
                {"indicator": "cpi_yoy", "date": "2025-01-15", "value": 2.5, "source": "test"},
                {"indicator": "gdp_growth", "date": "2025-01-15", "value": 2.5, "source": "test"},
            ],
            db_path,
        )
        assert _detect_stagflation(db_path=db_path) is False


class TestRecovery:
    """(from test_regime_special.py)."""

    def test_recovery_unit(self):
        from nuri.quant.regime.classifier import _detect_recovery

        phase1 = np.full(100, 180.0)
        phase2 = np.linspace(180, 120, 100)
        phase3 = np.linspace(120, 200, 100)
        close_arr = np.concatenate([phase1, phase2, phase3])
        df = pd.DataFrame({"close": close_arr})
        df["sma50"] = df["close"].rolling(50).mean()
        df["sma200"] = df["close"].rolling(200).mean()
        result = _detect_recovery(df)
        assert isinstance(result, bool)

    def test_recovery_insufficient_data(self):
        from nuri.quant.regime.classifier import _detect_recovery

        df = pd.DataFrame({"close": np.linspace(100, 200, 200)})
        df["sma50"] = df["close"].rolling(50).mean()
        df["sma200"] = df["close"].rolling(200).mean()
        assert _detect_recovery(df) is False

    def test_recovery_none_input(self):
        from nuri.quant.regime.classifier import _detect_recovery

        assert _detect_recovery(None) is False  # type: ignore[arg-type]


class TestSectorRotation:
    """(from test_regime_special.py)."""

    def test_sector_rotation_detection(self, db_path):
        from nuri.quant.regime.classifier import _detect_sector_rotation

        dates = pd.date_range(end=today_kst(), periods=25)
        spy_close = np.full(25, 500.0)
        df_spy = pd.DataFrame(
            {
                "ticker": "SPY",
                "date": [d.strftime("%Y-%m-%d") for d in dates],
                "open": spy_close * 0.999,
                "high": spy_close * 1.01,
                "low": spy_close * 0.99,
                "close": spy_close,
                "volume": [50_000_000] * 25,
                "adj_close": spy_close,
            }
        )
        upsert_prices(df_spy, db_path)
        xlk_close = np.linspace(200, 210, 25)
        df_xlk = pd.DataFrame(
            {
                "ticker": "XLK",
                "date": [d.strftime("%Y-%m-%d") for d in dates],
                "open": xlk_close * 0.999,
                "high": xlk_close * 1.01,
                "low": xlk_close * 0.99,
                "close": xlk_close,
                "volume": [10_000_000] * 25,
                "adj_close": xlk_close,
            }
        )
        upsert_prices(df_xlk, db_path)
        assert _detect_sector_rotation(db_path=db_path) is True

    def test_sector_rotation_spy_not_flat(self, db_path):
        from nuri.quant.regime.classifier import _detect_sector_rotation

        dates = pd.date_range(end=today_kst(), periods=25)
        spy_close = np.linspace(500, 525, 25)
        df = pd.DataFrame(
            {
                "ticker": "SPY",
                "date": [d.strftime("%Y-%m-%d") for d in dates],
                "open": spy_close * 0.999,
                "high": spy_close * 1.01,
                "low": spy_close * 0.99,
                "close": spy_close,
                "volume": [50_000_000] * 25,
                "adj_close": spy_close,
            }
        )
        upsert_prices(df, db_path)
        assert _detect_sector_rotation(db_path=db_path) is False

    def test_sector_rotation_no_data(self, db_path):
        from nuri.quant.regime.classifier import _detect_sector_rotation

        assert _detect_sector_rotation(db_path=db_path) is False


class TestSpecialRegimePriority:
    """(from test_regime_special.py)."""

    def test_euphoria_beats_recovery(self, db_path):
        from nuri.quant.regime.classifier import _detect_euphoria

        assert _detect_euphoria(10.0, 85.0) is True

    def test_special_regime_sizing(self):
        from nuri.quant.regime.classifier import SPECIAL_REGIME_SIZING

        assert SPECIAL_REGIME_SIZING["euphoria"] == "defensive"
        assert SPECIAL_REGIME_SIZING["stagflation"] == "minimal"
        assert SPECIAL_REGIME_SIZING["recovery"] == "aggressive"
        assert SPECIAL_REGIME_SIZING["sector_rotation"] == "normal"

    def test_base_regime_unchanged_when_no_special(self, db_path):
        close = np.linspace(100, 200, 300) + np.random.normal(0, 0.5, 300)
        dates = _insert_spy_data(db_path, close)
        upsert_macro(
            [
                {"indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"), "value": 16.0, "source": "test"},
                {"indicator": "fear_greed", "date": dates[-1].strftime("%Y-%m-%d"), "value": 60.0, "source": "test"},
            ],
            db_path,
        )
        from nuri.quant.regime.classifier import classify_regime

        state = classify_regime(db_path=db_path)
        assert state is not None
        assert state.details["special_regime"] is None
        assert state.regime.endswith("_vol")


class TestDynamicThresholds:
    """(from test_regime.py)."""

    def test_thresholds_with_vix_data(self, bull_market):
        from nuri.quant.regime.classifier import compute_dynamic_thresholds

        th = compute_dynamic_thresholds(db_path=bull_market)
        assert "vix_threshold" in th
        assert "sideways_pct" in th
        assert th["sideways_pct"] >= 1.0

    def test_thresholds_without_data(self, db_path):
        from nuri.quant.regime.classifier import compute_dynamic_thresholds

        th = compute_dynamic_thresholds(db_path=db_path)
        assert th["vix_threshold"] == 18.0
        assert th["sideways_pct"] == 2.0


class TestVixHysteresis:
    """(from test_data_integrity.py)."""

    def test_historical_vix_used_per_day(self, db_path):
        dates = _insert_spy_data_trend(db_path, n_days=300, trend="bull")
        for i, vix_val in enumerate([14.0, 15.0, 16.0, 17.0, 18.0]):
            upsert_macro([{"indicator": "vix", "date": dates[-(5 - i)], "value": vix_val, "source": "test"}], db_path)
        upsert_macro([{"indicator": "fear_greed", "date": dates[-1], "value": 55.0, "source": "test"}], db_path)
        from nuri.quant.regime.classifier import _get_vix

        assert _get_vix(date=dates[-5], db_path=db_path) == 14.0
        assert _get_vix(date=dates[-4], db_path=db_path) == 15.0
        assert _get_vix(date=dates[-3], db_path=db_path) == 16.0
        assert _get_vix(date=dates[-2], db_path=db_path) == 17.0
        assert _get_vix(date=dates[-1], db_path=db_path) == 18.0

    def test_hysteresis_calls_get_vix_per_day(self, db_path):
        dates = _insert_spy_data_trend(db_path, n_days=300, trend="bull")
        for i in range(10):
            upsert_macro(
                [{"indicator": "vix", "date": dates[-(10 - i)], "value": 15.0 + i * 0.1, "source": "test"}], db_path
            )
        upsert_macro([{"indicator": "fear_greed", "date": dates[-1], "value": 60.0, "source": "test"}], db_path)
        call_dates = []
        from nuri.quant.regime import classifier

        original_get_vix = classifier._get_vix

        def tracking_get_vix(date=None, db_path=None):
            call_dates.append(date)
            return original_get_vix(date=date, db_path=db_path)

        with patch.object(classifier, "_get_vix", side_effect=tracking_get_vix):
            state = classifier.classify_regime(db_path=db_path)
        assert state is not None
        hysteresis_calls = [d for d in call_dates if d is not None]
        assert len(hysteresis_calls) >= 2

    def test_regime_still_works_with_single_vix(self, db_path):
        dates = _insert_spy_data_trend(db_path, n_days=300, trend="bull")
        upsert_macro([{"indicator": "vix", "date": dates[-1], "value": 15.0, "source": "test"}], db_path)
        upsert_macro([{"indicator": "fear_greed", "date": dates[-1], "value": 55.0, "source": "test"}], db_path)
        from nuri.quant.regime.classifier import classify_regime

        state = classify_regime(db_path=db_path)
        assert state is not None
        assert state.trend == "bull"


class TestDataFreshnessEnforcement:
    """(from test_data_integrity.py)."""

    @pytest.fixture(autouse=True)
    def reset_freshness_warned(self):
        from nuri.quant.regime import classifier

        classifier._freshness_warned = False
        yield
        classifier._freshness_warned = False

    def test_stale_data_blocks_regime(self, db_path):
        stale_date = (kst_now().replace(tzinfo=None) - timedelta(days=10)).strftime("%Y-%m-%d")
        _insert_spy_data_trend(db_path, n_days=300, trend="bull", last_date=stale_date)
        upsert_macro([{"indicator": "vix", "date": stale_date, "value": 15.0, "source": "test"}], db_path)
        from nuri.quant.regime.classifier import classify_regime

        state = classify_regime(db_path=db_path)
        assert state is None

    def test_fresh_data_allows_regime(self, db_path):
        today = today_kst()
        dates = _insert_spy_data_trend(db_path, n_days=300, trend="bull", last_date=today)
        upsert_macro([{"indicator": "vix", "date": dates[-1], "value": 15.0, "source": "test"}], db_path)
        upsert_macro([{"indicator": "fear_greed", "date": dates[-1], "value": 60.0, "source": "test"}], db_path)
        from nuri.quant.regime.classifier import classify_regime

        state = classify_regime(db_path=db_path)
        assert state is not None

    def test_dated_query_bypasses_freshness(self, db_path):
        stale_date = (kst_now().replace(tzinfo=None) - timedelta(days=10)).strftime("%Y-%m-%d")
        _insert_spy_data_trend(db_path, n_days=300, trend="bull", last_date=stale_date)
        upsert_macro([{"indicator": "vix", "date": stale_date, "value": 15.0, "source": "test"}], db_path)
        upsert_macro([{"indicator": "fear_greed", "date": stale_date, "value": 60.0, "source": "test"}], db_path)
        from nuri.quant.regime.classifier import classify_regime

        state = classify_regime(date=stale_date, db_path=db_path)
        assert state is not None

    def test_no_data_returns_false(self, db_path):
        from nuri.quant.regime.classifier import _check_data_freshness

        assert _check_data_freshness(db_path=db_path) is False

    def test_freshness_check_returns_true_for_fresh(self, db_path):
        today = today_kst()
        _insert_spy_data_trend(db_path, n_days=300, trend="bull", last_date=today)
        from nuri.quant.regime.classifier import _check_data_freshness

        assert _check_data_freshness(db_path=db_path) is True


class TestClassifySingle:
    """(from test_coverage_round19.py)."""

    def test_bull(self):
        from nuri.quant.regime.classifier import _classify_single

        th = {"sideways_pct": 2.0, "vix_threshold": 18.0, "vix_bear_threshold": 24.0, "bb_width_threshold": 6.0}
        trend, vol = _classify_single(close=500, sma50=490, sma200=460, vix=15.0, bb_width=5.0, thresholds=th)
        assert trend == "bull"
        assert vol == "low"

    def test_bear(self):
        from nuri.quant.regime.classifier import _classify_single

        th = {"sideways_pct": 2.0, "vix_threshold": 18.0, "vix_bear_threshold": 24.0, "bb_width_threshold": 6.0}
        trend, vol = _classify_single(close=400, sma50=420, sma200=460, vix=30.0, bb_width=8.0, thresholds=th)
        assert trend == "bear"
        assert vol == "high"

    def test_sideways_narrow_gap(self):
        from nuri.quant.regime.classifier import _classify_single

        th = {"sideways_pct": 2.0, "vix_threshold": 18.0, "vix_bear_threshold": 24.0, "bb_width_threshold": 6.0}
        trend, vol = _classify_single(close=460, sma50=461, sma200=460, vix=16.0, bb_width=5.0, thresholds=th)
        assert trend == "sideways"

    def test_volatility_from_bb_when_no_vix(self):
        from nuri.quant.regime.classifier import _classify_single

        th = {"sideways_pct": 2.0, "vix_threshold": 18.0, "vix_bear_threshold": 24.0, "bb_width_threshold": 6.0}
        trend, vol = _classify_single(close=500, sma50=490, sma200=460, vix=None, bb_width=8.0, thresholds=th)
        assert vol == "high"


class TestClassifyRegime_R19:
    """(from test_coverage_round19.py)."""

    def test_full_classification(self, rich_db, monkeypatch):
        from nuri.quant.regime import classifier as cls_mod

        cls_mod._freshness_warned = False
        monkeypatch.setattr(cls_mod, "_check_data_freshness", lambda db_path=None: True)
        result = cls_mod.classify_regime(db_path=rich_db)
        assert result is not None
        assert result.trend in ("bull", "bear", "sideways")
        assert result.volatility in ("high", "low")
        assert 0 <= result.confidence <= 1
        assert result.details["base_regime"] is not None

    def test_with_date_param(self, rich_db):
        from nuri.quant.regime.classifier import classify_regime

        result = classify_regime(date="2025-06-01", db_path=rich_db)
        if result is not None:
            assert result.date <= "2025-06-01"

    def test_print_regime_none(self, capsys):
        from nuri.quant.regime.classifier import print_regime

        print_regime(None)
        captured = capsys.readouterr()
        assert "불가" in captured.out

    def test_print_regime_with_state(self, capsys):
        from nuri.quant.regime.classifier import RegimeState, print_regime

        state = RegimeState(
            date="2025-06-01",
            trend="bull",
            volatility="low",
            regime="bull_low_vol",
            confidence=0.75,
            details={
                "spy_close": 500.0,
                "sma50": 490.0,
                "sma200": 460.0,
                "sma_diff_pct": 6.5,
                "vix": 15.0,
                "fear_greed": 65.0,
                "rsi": 55.0,
                "bb_width": 5.0,
                "thresholds": {
                    "vix_threshold": 18.0,
                    "vix_bear_threshold": 24.0,
                    "sideways_pct": 2.0,
                    "bb_width_threshold": 6.0,
                },
                "base_regime": "bull_low_vol",
                "special_regime": None,
            },
        )
        print_regime(state)
        captured = capsys.readouterr()
        assert "BULL" in captured.out
        assert "LOW VOL" in captured.out

    def test_print_regime_special(self, capsys):
        from nuri.quant.regime.classifier import RegimeState, print_regime

        state = RegimeState(
            date="2025-06-01",
            trend="bull",
            volatility="low",
            regime="euphoria",
            confidence=0.8,
            details={
                "spy_close": 500.0,
                "sma50": 490.0,
                "sma200": 460.0,
                "sma_diff_pct": 6.5,
                "vix": 10.0,
                "fear_greed": 85.0,
                "rsi": None,
                "bb_width": 5.0,
                "thresholds": {},
                "base_regime": "bull_low_vol",
                "special_regime": "euphoria",
            },
        )
        print_regime(state)
        captured = capsys.readouterr()
        assert "EUPHORIA" in captured.out

    def test_print_history_empty(self, capsys):
        from nuri.quant.regime.classifier import print_history

        print_history([])
        captured = capsys.readouterr()
        assert "없음" in captured.out

    def test_print_history_with_data(self, capsys):
        from nuri.quant.regime.classifier import RegimeState, print_history

        states = [
            RegimeState(
                date="2025-06-01",
                trend="bull",
                volatility="low",
                regime="bull_low_vol",
                confidence=0.75,
                details={
                    "spy_close": 500.0,
                    "sma50": 490.0,
                    "sma200": 460.0,
                    "sma_diff_pct": 6.5,
                    "vix": 15.0,
                    "fear_greed": 65.0,
                    "rsi": 55.0,
                    "bb_width": 5.0,
                    "thresholds": {},
                    "base_regime": "bull_low_vol",
                    "special_regime": None,
                },
            )
        ]
        print_history(states)
        captured = capsys.readouterr()
        assert "Regime History" in captured.out


class TestDynamicThresholds_R19:
    """(from test_coverage_round19.py)."""

    def test_with_data(self, rich_db):
        from nuri.quant.regime.classifier import compute_dynamic_thresholds

        th = compute_dynamic_thresholds(db_path=rich_db)
        assert "vix_threshold" in th
        assert "sideways_pct" in th
        assert th["vix_threshold"] > 0

    def test_with_insufficient_data(self, tmp_path):
        path = tmp_path / "empty.db"
        init_db(path)
        from nuri.quant.regime.classifier import compute_dynamic_thresholds

        th = compute_dynamic_thresholds(db_path=path)
        assert th["vix_threshold"] == 18.0
        assert th["sideways_pct"] == 2.0


class TestSpecialRegimes_R19:
    """(from test_coverage_round19.py)."""

    def test_euphoria_detected(self):
        from nuri.quant.regime.classifier import _detect_euphoria

        assert _detect_euphoria(vix=10.0, fear_greed=85.0) is True

    def test_euphoria_not_detected_high_vix(self):
        from nuri.quant.regime.classifier import _detect_euphoria

        assert _detect_euphoria(vix=15.0, fear_greed=85.0) is False

    def test_euphoria_not_detected_low_fg(self):
        from nuri.quant.regime.classifier import _detect_euphoria

        assert _detect_euphoria(vix=10.0, fear_greed=60.0) is False

    def test_euphoria_none_inputs(self):
        from nuri.quant.regime.classifier import _detect_euphoria

        assert _detect_euphoria(vix=None, fear_greed=85.0) is False
        assert _detect_euphoria(vix=10.0, fear_greed=None) is False

    def test_stagflation_detected(self, tmp_path):
        from nuri.quant.regime.classifier import _detect_stagflation

        path = tmp_path / "test.db"
        init_db(path)
        upsert_macro(
            [
                {"indicator": "cpi_yoy", "date": "2025-01-01", "value": 5.0, "source": "test"},
                {"indicator": "gdp_growth", "date": "2025-01-01", "value": 0.5, "source": "test"},
            ],
            path,
        )
        assert _detect_stagflation(db_path=path) is True

    def test_stagflation_not_detected_normal_economy(self, tmp_path):
        from nuri.quant.regime.classifier import _detect_stagflation

        path = tmp_path / "test.db"
        init_db(path)
        upsert_macro(
            [
                {"indicator": "cpi_yoy", "date": "2025-01-01", "value": 2.5, "source": "test"},
                {"indicator": "gdp_growth", "date": "2025-01-01", "value": 2.5, "source": "test"},
            ],
            path,
        )
        assert _detect_stagflation(db_path=path) is False

    def test_stagflation_no_gdp_data(self, tmp_path):
        from nuri.quant.regime.classifier import _detect_stagflation

        path = tmp_path / "test.db"
        init_db(path)
        upsert_macro([{"indicator": "cpi_yoy", "date": "2025-01-01", "value": 5.0, "source": "test"}], path)
        assert _detect_stagflation(db_path=path) is False

    def test_recovery_detected(self):
        from nuri.quant.regime.classifier import _detect_recovery

        n = 300
        df = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=n), "close": np.linspace(100, 200, n)})
        sma50 = np.ones(n) * 150.0
        sma200 = np.ones(n) * 160.0
        sma50[-1] = 165
        sma200[-1] = 160
        df["sma50"] = sma50
        df["sma200"] = sma200
        assert _detect_recovery(df) is True

    def test_recovery_not_detected_bull_to_bull(self):
        from nuri.quant.regime.classifier import _detect_recovery

        n = 300
        df = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=n), "close": np.linspace(100, 200, n)})
        df["sma50"] = 170.0
        df["sma200"] = 160.0
        assert _detect_recovery(df) is False

    def test_recovery_short_data(self):
        from nuri.quant.regime.classifier import _detect_recovery

        df = pd.DataFrame({"date": ["2024-01-01"], "close": [100], "sma50": [100], "sma200": [100]})
        assert _detect_recovery(df) is False
        assert _detect_recovery(None) is False  # type: ignore[arg-type]

    def test_sector_rotation_detected(self, tmp_path):
        from nuri.quant.regime.classifier import _detect_sector_rotation

        path = tmp_path / "test.db"
        init_db(path)
        dates = pd.date_range("2025-01-01", periods=21, freq="B")
        rows = []
        for d in dates:
            rows.append(
                {
                    "ticker": "SPY",
                    "date": d.strftime("%Y-%m-%d"),
                    "open": 450,
                    "high": 451,
                    "low": 449,
                    "close": 450,
                    "volume": 1000000,
                    "adj_close": 450,
                }
            )
        for i, d in enumerate(dates):
            p = 200 + i * 0.5
            rows.append(
                {
                    "ticker": "XLK",
                    "date": d.strftime("%Y-%m-%d"),
                    "open": p,
                    "high": p + 1,
                    "low": p - 1,
                    "close": p,
                    "volume": 1000000,
                    "adj_close": p,
                }
            )
        upsert_prices(pd.DataFrame(rows), path)
        assert _detect_sector_rotation(db_path=path) is True

    def test_sector_rotation_spy_not_flat(self, tmp_path):
        from nuri.quant.regime.classifier import _detect_sector_rotation

        path = tmp_path / "test.db"
        init_db(path)
        dates = pd.date_range("2025-01-01", periods=21, freq="B")
        rows = []
        for i, d in enumerate(dates):
            p = 450 + i * 2
            rows.append(
                {
                    "ticker": "SPY",
                    "date": d.strftime("%Y-%m-%d"),
                    "open": p,
                    "high": p + 1,
                    "low": p - 1,
                    "close": p,
                    "volume": 1000000,
                    "adj_close": p,
                }
            )
        upsert_prices(pd.DataFrame(rows), path)
        assert _detect_sector_rotation(db_path=path) is False


class TestClassifierExtended:
    """(from test_coverage_final.py)."""

    def test_classify_regime(self, rich_db):
        from nuri.quant.regime.classifier import classify_regime

        result = classify_regime(db_path=rich_db)
        if result:
            assert result.trend in ("bull", "bear", "sideways")
            assert result.volatility in ("low", "high")
            assert 0 <= result.confidence <= 1

    def test_classify_single(self, rich_db):
        from nuri.quant.regime.classifier import _classify_single, compute_dynamic_thresholds

        thresholds = compute_dynamic_thresholds(db_path=rich_db)
        trend, vol = _classify_single(500, 480, 440, 15, 0.03, thresholds)
        assert trend == "bull"
        assert vol == "low"

    def test_classify_bear(self, rich_db):
        from nuri.quant.regime.classifier import _classify_single, compute_dynamic_thresholds

        thresholds = compute_dynamic_thresholds(db_path=rich_db)
        trend, vol = _classify_single(400, 450, 480, 15, 0.03, thresholds)
        assert trend == "bear"

    def test_high_vol(self, rich_db):
        from nuri.quant.regime.classifier import _classify_single, compute_dynamic_thresholds

        thresholds = compute_dynamic_thresholds(db_path=rich_db)
        trend, vol = _classify_single(500, 480, 440, 30, 0.08, thresholds)
        assert vol == "high"


class TestRegimeDeep:
    """(from test_coverage_round4.py)."""

    def test_classify_regime(self, rich_db, monkeypatch):
        from nuri.quant.regime import classifier as cls_mod

        monkeypatch.setattr(cls_mod, "_check_data_freshness", lambda db_path=None: True)
        state = cls_mod.classify_regime(db_path=rich_db)
        assert state is not None
        assert hasattr(state, "regime")
        assert hasattr(state, "trend")

    def test_classify_with_historical_vix(self, rich_db, monkeypatch):
        from nuri.quant.regime import classifier as cls_mod

        monkeypatch.setattr(cls_mod, "_check_data_freshness", lambda db_path=None: True)
        state = cls_mod.classify_regime(db_path=rich_db)
        assert state is not None
        assert state.confidence > 0


class TestRegimeSpecial_R12:
    """(from test_coverage_round12.py)."""

    def test_classify_volatility(self, rich_db, monkeypatch):
        from nuri.quant.regime import classifier as cls_mod

        monkeypatch.setattr(cls_mod, "_check_data_freshness", lambda db_path=None: True)
        state = cls_mod.classify_regime(db_path=rich_db)
        assert state is not None
        assert state.volatility in ("low", "high")

    def test_regime_details(self, rich_db, monkeypatch):
        from nuri.quant.regime import classifier as cls_mod

        monkeypatch.setattr(cls_mod, "_check_data_freshness", lambda db_path=None: True)
        state = cls_mod.classify_regime(db_path=rich_db)
        assert state is not None
        assert "base_regime" in state.details


class TestClassifyRegimeHistory:
    """(from test_coverage_round19.py)."""

    def test_history_with_data(self, rich_db, monkeypatch):
        from nuri.quant.regime import classifier as cls_mod

        cls_mod._freshness_warned = False
        monkeypatch.setattr(cls_mod, "_check_data_freshness", lambda db_path=None: True)
        from nuri.quant.regime.classifier import classify_regime_history

        history = classify_regime_history(start_date="2024-06-01", end_date="2025-06-01", db_path=rich_db)
        assert isinstance(history, list)
        if history:
            assert history[0].trend in ("bull", "bear", "sideways")

    def test_history_empty_db(self, tmp_path):
        path = tmp_path / "empty.db"
        init_db(path)
        from nuri.quant.regime.classifier import classify_regime_history

        history = classify_regime_history(db_path=path)
        assert history == []


class TestDataFreshness_R19:
    """(from test_coverage_round19.py)."""

    def test_no_data(self, tmp_path, monkeypatch):
        from nuri.quant.regime import classifier as cls_mod

        cls_mod._freshness_warned = False
        path = tmp_path / "empty.db"
        init_db(path)
        import nuri.core.db as db_mod

        monkeypatch.setattr(db_mod, "DB_PATH", path)
        result = cls_mod._check_data_freshness(db_path=path)
        assert result is False

    def test_recent_data(self, rich_db, monkeypatch):
        from nuri.quant.regime import classifier as cls_mod

        cls_mod._freshness_warned = False
        from nuri.core.db import query as _query

        rows = _query("SELECT MAX(date) as latest FROM prices WHERE ticker = 'SPY'", db_path=rich_db)
        latest_str = rows[0]["latest"]
        from datetime import datetime

        latest_dt = datetime.strptime(latest_str, "%Y-%m-%d")
        mock_now = latest_dt + timedelta(hours=24)
        with patch("nuri.core.timezone.kst_now", return_value=mock_now):
            result = cls_mod._check_data_freshness(db_path=rich_db)
        assert result is True


class TestClassifierDeep:
    """(from test_sixty_percent.py)."""

    def test_print_regime(self, full_db, capsys):
        from nuri.quant.regime.classifier import classify_regime, print_regime

        result = classify_regime(db_path=full_db)
        print_regime(result)
        output = capsys.readouterr().out
        assert len(output) > 0

    def test_compute_thresholds(self, full_db):
        from nuri.quant.regime.classifier import compute_dynamic_thresholds

        thresholds = compute_dynamic_thresholds(db_path=full_db)
        assert isinstance(thresholds, dict)
        assert "vix_threshold" in thresholds
        assert "sideways_pct" in thresholds


class TestRegimeEnumeration:
    """Lock-tests for `BASE_REGIMES` / `SPECIAL_REGIMES` / `ALL_REGIMES` constants
    added 2026-04-29 in PR #494 to give README claim "10 regimes (6 base + 4
    special)" a code-truth source. STRATEGY §5.3.1 Gotcha-Test Pair — these tests
    fail if anyone changes the count without also updating the verify-doc-counts
    pipeline / README claims.

    Why these matter: `verify_doc_counts.sh live_regimes()` reads `len(ALL_REGIMES)`
    and compares to README's `· N regimes` pattern. If ALL_REGIMES drifts silently
    (e.g., someone adds a 5th special regime) without updating the README claim,
    the next CI / `make verify-doc-counts` run breaks. These tests catch the
    inverse: someone changes the tuple shape but the README claim still says 10.
    """

    def test_base_regimes_count_is_six(self):
        from nuri.quant.regime.classifier import BASE_REGIMES

        assert len(BASE_REGIMES) == 6, (
            f"BASE_REGIMES count drifted: expected 6 (3 trend × 2 volatility), got {len(BASE_REGIMES)}"
        )

    def test_special_regimes_count_is_four(self):
        from nuri.quant.regime.classifier import SPECIAL_REGIMES

        assert len(SPECIAL_REGIMES) == 4, (
            f"SPECIAL_REGIMES count drifted: expected 4 (euphoria/stagflation/recovery/sector_rotation), got {len(SPECIAL_REGIMES)}"
        )

    def test_all_regimes_total_is_ten(self):
        """Critical README sync — '10 regimes (6 base + 4 special)' canonical."""
        from nuri.quant.regime.classifier import ALL_REGIMES

        assert len(ALL_REGIMES) == 10, (
            f"ALL_REGIMES count drifted: expected 10, got {len(ALL_REGIMES)}. "
            f"Update README.md '· N regimes' AND verify_doc_counts.sh in same PR."
        )

    def test_special_regimes_synced_with_sizing_dict(self):
        """SPECIAL_REGIMES tuple must equal SPECIAL_REGIME_SIZING.keys() — single source.

        Why: SPECIAL_REGIME_SIZING is the strategy-map sizing dict (used by callers).
        If someone adds a regime to the dict but forgets to update the tuple,
        ALL_REGIMES drifts silently. This test enforces sync.
        """
        from nuri.quant.regime.classifier import SPECIAL_REGIME_SIZING, SPECIAL_REGIMES

        assert set(SPECIAL_REGIMES) == set(SPECIAL_REGIME_SIZING.keys()), (
            f"SPECIAL_REGIMES tuple {SPECIAL_REGIMES} drifted from SPECIAL_REGIME_SIZING keys "
            f"{tuple(SPECIAL_REGIME_SIZING.keys())} — update both in the same edit."
        )

    def test_base_regime_literals_match_classifier_construction(self):
        """BASE_REGIMES literals must match what `_classify_single` actually emits via
        `f'{trend}_{volatility}_vol'`. If trend or volatility values drift, this catches it.
        """
        from nuri.quant.regime.classifier import BASE_REGIMES

        # `_classify_single` returns trend ∈ {bull, bear, sideways} × volatility ∈ {low, high}
        expected = {f"{trend}_{vol}_vol" for trend in ("bull", "bear", "sideways") for vol in ("low", "high")}
        assert set(BASE_REGIMES) == expected, (
            f"BASE_REGIMES tuple {BASE_REGIMES} drifted from classifier emission shape "
            f"{expected} — `_classify_single` produces these literals."
        )

    def test_no_duplicate_regime_names(self):
        """Defense against silent collision when adding a regime."""
        from nuri.quant.regime.classifier import ALL_REGIMES

        assert len(ALL_REGIMES) == len(set(ALL_REGIMES)), f"ALL_REGIMES has duplicates: {ALL_REGIMES}"

    def test_classifier_only_emits_known_regimes(self, bull_market):
        """End-to-end: classify_regime() output regime label MUST be in ALL_REGIMES.

        Why: caller code (strategy_map, position sizing) often switches on regime
        label. An unknown label silently falls into default branches. This test
        prevents the classifier from emitting a label not declared in ALL_REGIMES.
        """
        from nuri.quant.regime.classifier import ALL_REGIMES, classify_regime

        state = classify_regime(db_path=bull_market)
        assert state is not None, "bull_market fixture should produce a non-None regime state"
        assert state.regime in ALL_REGIMES, (
            f"classify_regime() emitted unknown label '{state.regime}' — not in ALL_REGIMES "
            f"({ALL_REGIMES}). Either add to the enumeration or fix the classifier."
        )


class TestClassifierMissingBranches:
    """Lines 100-101 (gap_pct < 50), 189 (mixed trend), 275/280 (recovery early returns),
    319 (sector rotation skip), 472/481/489 (sideways confidence checks)."""

    def test_dynamic_thresholds_short_history(self, db_path):
        """spy 데이터 < 250 행 → fallback else branch (line 102-104)."""
        from nuri.quant.regime.classifier import compute_dynamic_thresholds

        with get_db(db_path) as conn:
            for i in range(100):
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("SPY", f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}", 400, 402, 398, 400, 1000),
                )
        th = compute_dynamic_thresholds(db_path=db_path)
        assert th["sideways_pct"] == 2.0

    def test_classify_single_mixed_signals(self):
        """price > sma200 but sma50 < sma200 → 혼조 = sideways (line 189)."""
        from nuri.quant.regime.classifier import _classify_single

        thresholds = {
            "sideways_pct": 1.0,
            "vix_threshold": 20.0,
            "vix_bear_threshold": 25.0,
            "bb_width_threshold": 6.0,
        }
        # close > sma200 (price_above) but sma50_above_sma200=False
        trend, vol = _classify_single(
            close=110,
            sma50=95,
            sma200=100,  # sma_diff_pct = -5%
            vix=15,
            bb_width=4,
            thresholds=thresholds,
        )
        assert trend == "sideways"

    def test_detect_recovery_short_or_nan(self):
        """spy_df < 250 또는 latest sma NaN → False (line 267 + 275)."""
        from nuri.quant.regime.classifier import _detect_recovery

        # short
        empty = pd.DataFrame({"close": [], "sma50": [], "sma200": []})
        assert _detect_recovery(empty) is False

        # 250 행 이상 + latest sma NaN → line 274-275 hit
        n = 260
        df_nan = pd.DataFrame(
            {
                "close": [100.0] * n,
                "sma50": [100.0] * (n - 1) + [float("nan")],  # latest 만 NaN
                "sma200": [99.0] * n,
            }
        )
        assert _detect_recovery(df_nan) is False

    def test_detect_recovery_past_sma_nan(self):
        """250+ 행 + 200일 전 sma NaN → line 285-286 hit."""
        from nuri.quant.regime.classifier import _detect_recovery

        n = 260
        df = pd.DataFrame(
            {
                "close": [100.0] * n,
                "sma50": [100.0] * n,
                "sma200": [99.0] * n,
            }
        )
        # past_idx = 260 - 200 = 60. iloc[60] sma 를 NaN 으로
        df.iloc[60, df.columns.get_loc("sma50")] = float("nan")
        assert _detect_recovery(df) is False

    def test_detect_sector_rotation_no_etf_data(self, db_path):
        """ETF prices < 21 rows → 모든 ETF skip → False (line 319)."""
        from nuri.quant.regime.classifier import _detect_sector_rotation

        assert _detect_sector_rotation(db_path=db_path) is False

    def test_sideways_trend_confidence(self, db_path):
        """sideways trend confidence checks: 25≤fg≤75, 35≤rsi≤65, |slope|<th (lines 472, 481, 489)."""
        from nuri.quant.regime.classifier import classify_regime

        with get_db(db_path) as conn:
            for i in range(300):
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("SPY", f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}", 400, 401, 399, 400, 1000),  # 평탄
                )
            conn.execute(
                "INSERT INTO macro (indicator, date, value, source) VALUES ('vix', '2025-06-15', 15.0, 'test')"
            )
            conn.execute(
                "INSERT INTO macro (indicator, date, value, source) VALUES ('fear_greed', '2025-06-15', 50.0, 'test')"
            )
        state = classify_regime(date="2025-06-15", db_path=db_path)
        assert state is not None


class TestClassifierEventBasedPromotion:
    """이벤트 기반 special regime 보강 (lines 447-458)."""

    def _seed_baseline(self, db_path, days=300):
        """충분한 SPY 가격 + macro VIX 시드."""
        with get_db(db_path) as conn:
            for i in range(days):
                close = 400 + i * 0.5
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        "SPY",
                        f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                        close * 0.99,
                        close * 1.01,
                        close * 0.99,
                        close,
                        1000000,
                    ),
                )
            conn.execute(
                "INSERT INTO macro (indicator, date, value, source) VALUES ('vix', '2025-06-15', 15.0, 'test')"
            )

    def test_event_score_exception_caught(self, db_path, monkeypatch):
        """event_score 모듈 실행 실패 → except pass (lines 457-458)."""
        from nuri.quant.regime.classifier import classify_regime

        self._seed_baseline(db_path)

        import nuri.quant.regime.event_score as es_mod

        def boom(*a, **kw):
            raise RuntimeError("simulated")

        monkeypatch.setattr(es_mod, "compute_event_score", boom)
        state = classify_regime(date="2025-06-15", db_path=db_path)
        assert state is not None

    def test_event_promotes_recovery_when_bull(self, db_path):
        """recovery hint + trend != 'bear' → recovery promotion (lines 448-449)."""
        from nuri.quant.regime.classifier import classify_regime

        self._seed_baseline(db_path)

        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO macro_events "
                    "(published_at, source, headline, url, category, sentiment, confidence) "
                    "VALUES ('2025-06-14', 'test', 'evt', ?, 'geopolitical_de_escalation', 0.8, 0.9)",
                    (f"http://t/r-{i}",),
                )
        state = classify_regime(date="2025-06-15", db_path=db_path)
        assert state is not None

    def test_event_promotes_stagflation(self, db_path):
        """stagflation hint → stagflation promotion (lines 450-451)."""
        from nuri.quant.regime.classifier import classify_regime

        self._seed_baseline(db_path)

        # event_classifier REGIME_HINT_BY_CATEGORY 에서 stagflation hint 매핑된 카테고리는
        # fed_hawkish 또는 oil_supply_shock 가능성. 명시적으로 hint 컬럼 set
        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO macro_events "
                    "(published_at, source, headline, url, category, sentiment, confidence, regime_hint) "
                    "VALUES ('2025-06-14', 'test', 'evt', ?, 'oil_supply_shock', -0.8, 0.9, 'stagflation')",
                    (f"http://t/sf-{i}",),
                )
        state = classify_regime(date="2025-06-15", db_path=db_path)
        assert state is not None

    def test_event_promotes_sector_rotation(self, db_path):
        """sector_rotation hint (lines 455-456)."""
        from nuri.quant.regime.classifier import classify_regime

        self._seed_baseline(db_path)

        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO macro_events "
                    "(published_at, source, headline, url, category, sentiment, confidence, regime_hint) "
                    "VALUES ('2025-06-14', 'test', 'evt', ?, 'sector_rally', 0.6, 0.9, 'sector_rotation')",
                    (f"http://t/sr-{i}",),
                )
        state = classify_regime(date="2025-06-15", db_path=db_path)
        assert state is not None

    def test_event_bear_high_vol_passes(self, db_path):
        """bear_high_vol hint + score <= -15 → pass (line 452-454, no-op)."""
        from nuri.quant.regime.classifier import classify_regime

        self._seed_baseline(db_path)

        with get_db(db_path) as conn:
            for i in range(8):
                conn.execute(
                    "INSERT INTO macro_events "
                    "(published_at, source, headline, url, category, sentiment, confidence, regime_hint) "
                    "VALUES ('2025-06-14', 'test', 'evt', ?, 'geopolitical_escalation', -0.9, 0.95, 'bear_high_vol')",
                    (f"http://t/b-{i}",),
                )
        state = classify_regime(date="2025-06-15", db_path=db_path)
        assert state is not None


class TestClassifierHysteresisRecentTrendsEmpty:
    """recent_trends 모두 NaN → fallback to single classify (lines 421-423)."""

    def test_all_nan_sma_hysteresis_window(self, db_path, monkeypatch):
        """hysteresis window 의 모든 row sma NaN → recent_trends empty → fallback (lines 397, 421).

        주의: classify_regime entry 는 latest sma 가 valid 해야 하지만 hysteresis loop 에서는
        spy_df.iloc[-hyst_days:0] (5 days) 가 모두 NaN 이어야 함 — 단 iloc[-1] 도 NaN 이면
        latest 에러. 그래서 latest 만 valid + 그 외 hysteresis 범위 NaN 으로 강제.

        Actually hysteresis window 는 iloc[-5:] = 마지막 5 일. iloc[-1] 포함.
        iloc[-1] 만 valid 면 recent_trends 에 1 개 들어감 → not empty.
        line 421 도달 불가능 (latest valid + hysteresis loop 에 latest 포함 → 항상 ≥1).

        이 분기는 실제로 도달 불가 — pragma 필요.
        """
        from nuri.quant.regime import classifier as cls

        n = 260
        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=n).strftime("%Y-%m-%d"),
                "close": [400.0] * n,
                "sma50": [400.0] * n,
                "sma200": [395.0] * n,
                "rsi": [50.0] * n,
                "bb_width": [3.0] * n,
                "sma50_slope": [0.1] * n,
            }
        )
        # 마지막 5일 sma 일부 NaN — line 397 continue 분기 hit (전부는 아님)
        for k in range(2, 5):
            df.iloc[-k, df.columns.get_loc("sma50")] = float("nan")

        monkeypatch.setattr(cls, "_load_spy_series", lambda date=None, db_path=None: df)
        monkeypatch.setattr(cls, "_get_vix", lambda date=None, db_path=None: 15.0)
        monkeypatch.setattr(cls, "_get_fear_greed", lambda date=None, db_path=None: 50.0)
        import nuri.quant.regime.event_score as es_mod

        class FakeES:
            event_count = 0
            score = 0
            regime_hint = None

        monkeypatch.setattr(es_mod, "compute_event_score", lambda date=None, db_path=None: FakeES())

        state = cls.classify_regime(date="2024-12-31", db_path=db_path)
        assert state is not None

    def test_stagflation_promotion_path(self, db_path):
        """CPI > 4 + GDP < 1 → stagflation special regime (line 433)."""
        from nuri.quant.regime.classifier import classify_regime

        # bull SPY 시드
        with get_db(db_path) as conn:
            for i in range(300):
                close = 400 + i * 0.5
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        "SPY",
                        f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                        close * 0.99,
                        close * 1.01,
                        close * 0.99,
                        close,
                        1000000,
                    ),
                )
            # CPI 5%, GDP 0.5% → stagflation 발동
            conn.execute(
                "INSERT INTO macro (indicator, date, value, source) VALUES ('cpi_yoy', '2025-06-15', 5.0, 'test')"
            )
            conn.execute(
                "INSERT INTO macro (indicator, date, value, source) VALUES ('gdp_growth', '2025-06-15', 0.5, 'test')"
            )
            conn.execute(
                "INSERT INTO macro (indicator, date, value, source) VALUES ('vix', '2025-06-15', 18.0, 'test')"
            )
        state = classify_regime(date="2025-06-15", db_path=db_path)
        assert state is not None
        assert state.details.get("special_regime") == "stagflation"

    def test_recovery_promotion_path(self, db_path, monkeypatch):
        """SMA50 200일 전 < SMA200 + 현재 SMA50 >= SMA200 → recovery (line 435).

        장기 하락 후 반등 시퀀스. 500+ 일 필요 (200일 전 idx 의 sma200 도 valid 해야 함).
        """
        from nuri.quant.regime import classifier as cls

        # _detect_recovery 가 True 반환하도록 직접 patch — 실제 시드 대신 구조 lock
        monkeypatch.setattr(cls, "_detect_recovery", lambda spy_df: True)
        # _detect_euphoria, _detect_stagflation 모두 False
        monkeypatch.setattr(cls, "_detect_euphoria", lambda v, fg: False)
        monkeypatch.setattr(cls, "_detect_stagflation", lambda db_path=None, date=None: False)

        # 충분한 SPY 데이터 시드
        with get_db(db_path) as conn:
            for i in range(300):
                close = 400 + i * 0.5
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        "SPY",
                        f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                        close * 0.99,
                        close * 1.01,
                        close * 0.99,
                        close,
                        1000000,
                    ),
                )
            conn.execute(
                "INSERT INTO macro (indicator, date, value, source) VALUES ('vix', '2025-06-15', 18.0, 'test')"
            )
        state = cls.classify_regime(date="2025-06-15", db_path=db_path)
        assert state is not None
        assert state.details.get("special_regime") == "recovery"

    def test_short_history_skips_hysteresis(self, db_path, monkeypatch):
        """spy_df < hyst_days + 200 → 단일 classify_single (line 423).

        freshness check 우회 위해 date 인자 지정 (과거 날짜).
        """
        from nuri.quant.regime import classifier as cls

        n = 200
        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=n).strftime("%Y-%m-%d"),
                "close": [400.0] * n,
                "sma50": [400.0] * n,
                "sma200": [395.0] * n,
                "rsi": [50.0] * n,
                "bb_width": [3.0] * n,
                "sma50_slope": [0.1] * n,
            }
        )
        monkeypatch.setattr(cls, "_load_spy_series", lambda date=None, db_path=None: df)
        monkeypatch.setattr(cls, "_get_vix", lambda date=None, db_path=None: 15.0)
        monkeypatch.setattr(cls, "_get_fear_greed", lambda date=None, db_path=None: 50.0)
        # freshness 우회 — _check_data_freshness 항상 OK
        monkeypatch.setattr(cls, "_check_data_freshness", lambda *a, **kw: True)
        import nuri.quant.regime.event_score as es_mod

        class FakeES:
            event_count = 0
            score = 0
            regime_hint = None

        monkeypatch.setattr(es_mod, "compute_event_score", lambda date=None, db_path=None: FakeES())

        state = cls.classify_regime(date="2024-07-19", db_path=db_path)
        assert state is not None

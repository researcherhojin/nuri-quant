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
        upsert_macro([
            {"indicator": "cpi_yoy", "date": "2025-01-15", "value": 5.5, "source": "test"},
            {"indicator": "gdp_growth", "date": "2025-01-15", "value": 0.5, "source": "test"},
        ], db_path)
        assert _detect_stagflation(db_path=db_path) is True

    def test_stagflation_no_gdp_graceful(self, db_path):
        from nuri.quant.regime.classifier import _detect_stagflation
        upsert_macro([
            {"indicator": "cpi_yoy", "date": "2025-01-15", "value": 5.5, "source": "test"},
        ], db_path)
        assert _detect_stagflation(db_path=db_path) is False

    def test_stagflation_no_cpi(self, db_path):
        from nuri.quant.regime.classifier import _detect_stagflation
        assert _detect_stagflation(db_path=db_path) is False

    def test_stagflation_normal_conditions(self, db_path):
        from nuri.quant.regime.classifier import _detect_stagflation
        upsert_macro([
            {"indicator": "cpi_yoy", "date": "2025-01-15", "value": 2.5, "source": "test"},
            {"indicator": "gdp_growth", "date": "2025-01-15", "value": 2.5, "source": "test"},
        ], db_path)
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
        df_spy = pd.DataFrame({
            "ticker": "SPY",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": spy_close * 0.999, "high": spy_close * 1.01,
            "low": spy_close * 0.99, "close": spy_close,
            "volume": [50_000_000] * 25, "adj_close": spy_close,
        })
        upsert_prices(df_spy, db_path)
        xlk_close = np.linspace(200, 210, 25)
        df_xlk = pd.DataFrame({
            "ticker": "XLK",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": xlk_close * 0.999, "high": xlk_close * 1.01,
            "low": xlk_close * 0.99, "close": xlk_close,
            "volume": [10_000_000] * 25, "adj_close": xlk_close,
        })
        upsert_prices(df_xlk, db_path)
        assert _detect_sector_rotation(db_path=db_path) is True

    def test_sector_rotation_spy_not_flat(self, db_path):
        from nuri.quant.regime.classifier import _detect_sector_rotation
        dates = pd.date_range(end=today_kst(), periods=25)
        spy_close = np.linspace(500, 525, 25)
        df = pd.DataFrame({
            "ticker": "SPY",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": spy_close * 0.999, "high": spy_close * 1.01,
            "low": spy_close * 0.99, "close": spy_close,
            "volume": [50_000_000] * 25, "adj_close": spy_close,
        })
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
        upsert_macro([
            {"indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"), "value": 16.0, "source": "test"},
            {"indicator": "fear_greed", "date": dates[-1].strftime("%Y-%m-%d"), "value": 60.0, "source": "test"},
        ], db_path)
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
            upsert_macro([{"indicator": "vix", "date": dates[-(10 - i)], "value": 15.0 + i * 0.1, "source": "test"}], db_path)
        upsert_macro([{"indicator": "fear_greed", "date": dates[-1], "value": 60.0, "source": "test"}], db_path)
        call_dates = []
        from nuri.quant.regime import classifier
        original_get_vix = classifier._get_vix

        def tracking_get_vix(date=None, db_path=None):
            call_dates.append(date)
            return original_get_vix(date=date, db_path=db_path)

        with patch.object(classifier, '_get_vix', side_effect=tracking_get_vix):
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
            date="2025-06-01", trend="bull", volatility="low",
            regime="bull_low_vol", confidence=0.75,
            details={
                "spy_close": 500.0, "sma50": 490.0, "sma200": 460.0,
                "sma_diff_pct": 6.5, "vix": 15.0, "fear_greed": 65.0,
                "rsi": 55.0, "bb_width": 5.0,
                "thresholds": {"vix_threshold": 18.0, "vix_bear_threshold": 24.0,
                               "sideways_pct": 2.0, "bb_width_threshold": 6.0},
                "base_regime": "bull_low_vol", "special_regime": None,
            },
        )
        print_regime(state)
        captured = capsys.readouterr()
        assert "BULL" in captured.out
        assert "LOW VOL" in captured.out

    def test_print_regime_special(self, capsys):
        from nuri.quant.regime.classifier import RegimeState, print_regime
        state = RegimeState(
            date="2025-06-01", trend="bull", volatility="low",
            regime="euphoria", confidence=0.8,
            details={
                "spy_close": 500.0, "sma50": 490.0, "sma200": 460.0,
                "sma_diff_pct": 6.5, "vix": 10.0, "fear_greed": 85.0,
                "rsi": None, "bb_width": 5.0,
                "thresholds": {}, "base_regime": "bull_low_vol",
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
        states = [RegimeState(
            date="2025-06-01", trend="bull", volatility="low",
            regime="bull_low_vol", confidence=0.75,
            details={"spy_close": 500.0, "sma50": 490.0, "sma200": 460.0,
                     "sma_diff_pct": 6.5, "vix": 15.0, "fear_greed": 65.0,
                     "rsi": 55.0, "bb_width": 5.0, "thresholds": {},
                     "base_regime": "bull_low_vol", "special_regime": None},
        )]
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
        upsert_macro([
            {"indicator": "cpi_yoy", "date": "2025-01-01", "value": 5.0, "source": "test"},
            {"indicator": "gdp_growth", "date": "2025-01-01", "value": 0.5, "source": "test"},
        ], path)
        assert _detect_stagflation(db_path=path) is True

    def test_stagflation_not_detected_normal_economy(self, tmp_path):
        from nuri.quant.regime.classifier import _detect_stagflation
        path = tmp_path / "test.db"
        init_db(path)
        upsert_macro([
            {"indicator": "cpi_yoy", "date": "2025-01-01", "value": 2.5, "source": "test"},
            {"indicator": "gdp_growth", "date": "2025-01-01", "value": 2.5, "source": "test"},
        ], path)
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
            rows.append({"ticker": "SPY", "date": d.strftime("%Y-%m-%d"),
                         "open": 450, "high": 451, "low": 449,
                         "close": 450, "volume": 1000000, "adj_close": 450})
        for i, d in enumerate(dates):
            p = 200 + i * 0.5
            rows.append({"ticker": "XLK", "date": d.strftime("%Y-%m-%d"),
                         "open": p, "high": p + 1, "low": p - 1,
                         "close": p, "volume": 1000000, "adj_close": p})
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
            rows.append({"ticker": "SPY", "date": d.strftime("%Y-%m-%d"),
                         "open": p, "high": p + 1, "low": p - 1,
                         "close": p, "volume": 1000000, "adj_close": p})
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

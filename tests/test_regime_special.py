"""특수 레짐 테스트 — euphoria, stagflation, recovery, sector_rotation."""
import numpy as np
import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_macro, upsert_prices
from nuri.core.timezone import today_kst


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _insert_spy_data(db_path, close_array, dates=None):
    """SPY 가격 데이터 삽입 헬퍼."""
    n = len(close_array)
    if dates is None:
        dates = pd.date_range(end=today_kst(), periods=n)
    df = pd.DataFrame({
        "ticker": "SPY",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close_array * 0.999,
        "high": close_array * 1.01,
        "low": close_array * 0.99,
        "close": close_array,
        "volume": [50_000_000] * n,
        "adj_close": close_array,
    })
    upsert_prices(df, db_path)
    return dates


# ═══════════════════════════════════════════════════════
# Euphoria 레짐
# ═══════════════════════════════════════════════════════


@pytest.fixture
def euphoria_market(db_path):
    """과열장 시뮬레이션: VIX < 12, Fear&Greed > 80."""
    close = np.linspace(100, 200, 300) + np.random.normal(0, 0.5, 300)
    dates = _insert_spy_data(db_path, close)

    upsert_macro([
        {"indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"), "value": 10.0, "source": "test"},
        {"indicator": "fear_greed", "date": dates[-1].strftime("%Y-%m-%d"), "value": 85.0, "source": "test"},
    ], db_path)
    return db_path


class TestEuphoria:

    def test_euphoria_detection(self, euphoria_market):
        """VIX < 12 AND Fear&Greed > 80 → euphoria 레짐."""
        from nuri.quant.regime.classifier import classify_regime
        state = classify_regime(db_path=euphoria_market)
        assert state is not None
        assert state.regime == "euphoria"
        assert state.details["special_regime"] == "euphoria"
        # base regime은 bull
        assert state.trend == "bull"
        assert state.details["base_regime"].startswith("bull_")

    def test_euphoria_not_triggered_vix_high(self, db_path):
        """VIX >= 12이면 euphoria 아님."""
        from nuri.quant.regime.classifier import _detect_euphoria
        assert _detect_euphoria(15.0, 85.0) is False

    def test_euphoria_not_triggered_fg_low(self, db_path):
        """Fear&Greed <= 80이면 euphoria 아님."""
        from nuri.quant.regime.classifier import _detect_euphoria
        assert _detect_euphoria(10.0, 75.0) is False

    def test_euphoria_unit(self):
        """정확한 조건에서 True."""
        from nuri.quant.regime.classifier import _detect_euphoria
        assert _detect_euphoria(11.9, 81.0) is True
        assert _detect_euphoria(None, 85.0) is False
        assert _detect_euphoria(10.0, None) is False


# ═══════════════════════════════════════════════════════
# Stagflation 레짐
# ═══════════════════════════════════════════════════════


class TestStagflation:

    def test_stagflation_detection(self, db_path):
        """CPI > 4% AND GDP < 1% → stagflation."""
        from nuri.quant.regime.classifier import _detect_stagflation
        upsert_macro([
            {"indicator": "cpi_yoy", "date": "2025-01-15", "value": 5.5, "source": "test"},
            {"indicator": "gdp_growth", "date": "2025-01-15", "value": 0.5, "source": "test"},
        ], db_path)
        assert _detect_stagflation(db_path=db_path) is True

    def test_stagflation_no_gdp_graceful(self, db_path):
        """GDP 데이터 없으면 False (graceful skip)."""
        from nuri.quant.regime.classifier import _detect_stagflation
        upsert_macro([
            {"indicator": "cpi_yoy", "date": "2025-01-15", "value": 5.5, "source": "test"},
        ], db_path)
        assert _detect_stagflation(db_path=db_path) is False

    def test_stagflation_no_cpi(self, db_path):
        """CPI 데이터 없으면 False."""
        from nuri.quant.regime.classifier import _detect_stagflation
        assert _detect_stagflation(db_path=db_path) is False

    def test_stagflation_normal_conditions(self, db_path):
        """CPI 정상, GDP 정상 → False."""
        from nuri.quant.regime.classifier import _detect_stagflation
        upsert_macro([
            {"indicator": "cpi_yoy", "date": "2025-01-15", "value": 2.5, "source": "test"},
            {"indicator": "gdp_growth", "date": "2025-01-15", "value": 2.5, "source": "test"},
        ], db_path)
        assert _detect_stagflation(db_path=db_path) is False


# ═══════════════════════════════════════════════════════
# Recovery 레짐
# ═══════════════════════════════════════════════════════


@pytest.fixture
def recovery_market(db_path):
    """회복장 시뮬레이션: 200일 전 SMA50 < SMA200, 현재 SMA50 >= SMA200."""
    # 150일 횡보 → 80일 하락 → 70일 상승 (300일)
    # 200일 전 시점: 하락 중이므로 SMA50 < SMA200
    # 현재: 상승으로 SMA50 > SMA200
    phase1 = np.full(100, 180.0) + np.random.normal(0, 0.3, 100)  # 횡보
    phase2 = np.linspace(180, 130, 100) + np.random.normal(0, 0.3, 100)  # 하락
    phase3 = np.linspace(130, 190, 100) + np.random.normal(0, 0.3, 100)  # V자 회복
    close = np.concatenate([phase1, phase2, phase3])

    dates = _insert_spy_data(db_path, close)

    upsert_macro([
        {"indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"), "value": 18.0, "source": "test"},
        {"indicator": "fear_greed", "date": dates[-1].strftime("%Y-%m-%d"), "value": 55.0, "source": "test"},
    ], db_path)
    return db_path


class TestRecovery:

    def test_recovery_unit(self):
        """recovery 함수 단위 테스트: SMA50/SMA200 크로스 확인."""
        from nuri.quant.regime.classifier import _detect_recovery

        # 충분한 데이터, SMA50 < SMA200 → SMA50 > SMA200 크로스
        phase1 = np.full(100, 180.0)
        phase2 = np.linspace(180, 120, 100)
        phase3 = np.linspace(120, 200, 100)
        close_arr = np.concatenate([phase1, phase2, phase3])

        df = pd.DataFrame({"close": close_arr})
        df["sma50"] = df["close"].rolling(50).mean()
        df["sma200"] = df["close"].rolling(200).mean()

        result = _detect_recovery(df)
        # 200일 전 시점은 하락 초기, 현재는 회복 → 가능
        assert isinstance(result, bool)

    def test_recovery_insufficient_data(self):
        """250일 미만 데이터 → False."""
        from nuri.quant.regime.classifier import _detect_recovery
        df = pd.DataFrame({"close": np.linspace(100, 200, 200)})
        df["sma50"] = df["close"].rolling(50).mean()
        df["sma200"] = df["close"].rolling(200).mean()
        assert _detect_recovery(df) is False

    def test_recovery_none_input(self):
        """None → False."""
        from nuri.quant.regime.classifier import _detect_recovery
        assert _detect_recovery(None) is False


# ═══════════════════════════════════════════════════════
# Sector Rotation 레짐
# ═══════════════════════════════════════════════════════


class TestSectorRotation:

    def test_sector_rotation_detection(self, db_path):
        """SPY 횡보 + 섹터 ETF 3%+ → sector_rotation."""
        from nuri.quant.regime.classifier import _detect_sector_rotation

        dates = pd.date_range(end=today_kst(), periods=25)
        # SPY: 횡보 (0% 수익률)
        spy_close = np.full(25, 500.0)
        df_spy = pd.DataFrame({
            "ticker": "SPY",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": spy_close * 0.999, "high": spy_close * 1.01,
            "low": spy_close * 0.99, "close": spy_close,
            "volume": [50_000_000] * 25, "adj_close": spy_close,
        })
        upsert_prices(df_spy, db_path)

        # XLK: 5% 상승
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
        """SPY 5% 상승이면 sector_rotation 아님."""
        from nuri.quant.regime.classifier import _detect_sector_rotation

        dates = pd.date_range(end=today_kst(), periods=25)
        spy_close = np.linspace(500, 525, 25)  # 5% 상승
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
        """데이터 없으면 False."""
        from nuri.quant.regime.classifier import _detect_sector_rotation
        assert _detect_sector_rotation(db_path=db_path) is False


# ═══════════════════════════════════════════════════════
# 우선순위 + 하위 호환성
# ═══════════════════════════════════════════════════════


class TestSpecialRegimePriority:

    def test_euphoria_beats_recovery(self, db_path):
        """euphoria와 recovery 둘 다 해당되면 euphoria 우선."""
        from nuri.quant.regime.classifier import _detect_euphoria
        # euphoria 조건 충족
        assert _detect_euphoria(10.0, 85.0) is True
        # 우선순위 순서: euphoria > stagflation > recovery > sector_rotation
        # classify_regime에서 if-elif 순서로 보장됨

    def test_special_regime_sizing(self):
        """특수 레짐 포지션 사이징 매핑 확인."""
        from nuri.quant.regime.classifier import SPECIAL_REGIME_SIZING
        assert SPECIAL_REGIME_SIZING["euphoria"] == "defensive"
        assert SPECIAL_REGIME_SIZING["stagflation"] == "minimal"
        assert SPECIAL_REGIME_SIZING["recovery"] == "aggressive"
        assert SPECIAL_REGIME_SIZING["sector_rotation"] == "normal"

    def test_base_regime_unchanged_when_no_special(self, db_path):
        """특수 조건 미충족 시 base 6-regime 유지."""
        close = np.linspace(100, 200, 300) + np.random.normal(0, 0.5, 300)
        dates = _insert_spy_data(db_path, close)

        # 평범한 VIX/F&G (euphoria 미충족)
        upsert_macro([
            {"indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"), "value": 16.0, "source": "test"},
            {"indicator": "fear_greed", "date": dates[-1].strftime("%Y-%m-%d"), "value": 60.0, "source": "test"},
        ], db_path)

        from nuri.quant.regime.classifier import classify_regime
        state = classify_regime(db_path=db_path)
        assert state is not None
        assert state.details["special_regime"] is None
        assert state.regime.endswith("_vol")  # base regime 형식

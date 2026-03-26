"""Phase D 레짐 분류기 테스트 — in-memory SQLite로 격리."""
import numpy as np
import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_prices, upsert_macro


@pytest.fixture
def db_path(tmp_path):
    """임시 DB 경로 픽스처."""
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def bull_market(db_path):
    """상승장 시뮬레이션: SPY가 SMA200 위, VIX 낮음."""
    # 300일 상승 추세 (100 → 200)
    dates = pd.bdate_range("2024-01-01", periods=300)
    close = np.linspace(100, 200, 300) + np.random.normal(0, 1, 300)

    df = pd.DataFrame({
        "ticker": "SPY",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.99,
        "high": close * 1.01,
        "low": close * 0.98,
        "close": close,
        "volume": [50000000] * 300,
        "adj_close": close,
    })
    upsert_prices(df, db_path)

    # VIX = 15 (낮음)
    upsert_macro([{
        "indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"),
        "value": 15.0, "source": "test",
    }], db_path)

    # Fear & Greed = 65 (탐욕 쪽)
    upsert_macro([{
        "indicator": "fear_greed", "date": dates[-1].strftime("%Y-%m-%d"),
        "value": 65.0, "source": "test",
    }], db_path)

    return db_path


@pytest.fixture
def bear_market(db_path):
    """하락장 시뮬레이션: SPY가 SMA200 아래, VIX 높음."""
    # 300일: 200일 상승 후 100일 급락
    dates = pd.bdate_range("2024-01-01", periods=300)
    up = np.linspace(150, 200, 200)
    down = np.linspace(200, 130, 100)
    close = np.concatenate([up, down]) + np.random.normal(0, 0.5, 300)

    df = pd.DataFrame({
        "ticker": "SPY",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.99,
        "high": close * 1.01,
        "low": close * 0.98,
        "close": close,
        "volume": [50000000] * 300,
        "adj_close": close,
    })
    upsert_prices(df, db_path)

    # VIX = 32 (높음)
    upsert_macro([{
        "indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"),
        "value": 32.0, "source": "test",
    }], db_path)

    # Fear & Greed = 20 (공포)
    upsert_macro([{
        "indicator": "fear_greed", "date": dates[-1].strftime("%Y-%m-%d"),
        "value": 20.0, "source": "test",
    }], db_path)

    return db_path


# ═══════════════════════════════════════════════════════
# D-1: 레짐 분류기 테스트
# ═══════════════════════════════════════════════════════


class TestRegimeClassifier:
    """D-1 레짐 분류기 테스트."""

    def test_bull_regime_detection(self, bull_market):
        """상승 추세 + 낮은 VIX → bull_low_vol."""
        from nuri.analysis.regime.classifier import classify_regime
        state = classify_regime(db_path=bull_market)
        assert state is not None
        assert state.trend == "bull"
        assert state.volatility == "low"
        assert state.regime == "bull_low_vol"

    def test_bear_regime_detection(self, bear_market):
        """하락 추세 + 높은 VIX → bear_high_vol."""
        from nuri.analysis.regime.classifier import classify_regime
        state = classify_regime(db_path=bear_market)
        assert state is not None
        assert state.trend == "bear"
        assert state.volatility == "high"
        assert state.regime == "bear_high_vol"

    def test_confidence_range(self, bull_market):
        """신뢰도는 0~1 사이."""
        from nuri.analysis.regime.classifier import classify_regime
        state = classify_regime(db_path=bull_market)
        assert 0.0 <= state.confidence <= 1.0

    def test_insufficient_data(self, db_path):
        """데이터 부족 시 None 반환."""
        from nuri.analysis.regime.classifier import classify_regime
        state = classify_regime(db_path=db_path)
        assert state is None


# ═══════════════════════════════════════════════════════
# D-2: 매크로 스코어 테스트
# ═══════════════════════════════════════════════════════


class TestMacroScore:
    """D-2 매크로 스코어 테스트."""

    def test_score_range(self, db_path):
        """스코어는 0~100 사이."""
        from nuri.analysis.regime.macro_score import compute_macro_score
        score = compute_macro_score(db_path=db_path)
        assert 0 <= score.total_score <= 100

    def test_favorable_conditions(self, db_path):
        """양호한 매크로 조건 → 높은 점수."""
        from nuri.analysis.regime.macro_score import compute_macro_score
        date = "2025-01-15"
        # 양호한 매크로 환경 주입
        upsert_macro([
            {"indicator": "us_10y_yield", "date": date, "value": 4.0, "source": "test"},
            {"indicator": "us_2y_yield", "date": date, "value": 3.0, "source": "test"},
            {"indicator": "vix", "date": date, "value": 14.0, "source": "test"},
            {"indicator": "fear_greed", "date": date, "value": 55.0, "source": "test"},
            {"indicator": "unemployment", "date": date, "value": 3.8, "source": "test"},
            {"indicator": "cpi_yoy", "date": date, "value": 2.1, "source": "test"},
            {"indicator": "fed_funds_rate", "date": date, "value": 2.0, "source": "test"},
        ], db_path)
        score = compute_macro_score(date=date, db_path=db_path)
        assert score.total_score > 65
        assert score.interpretation == "Favorable"

    def test_adverse_conditions(self, db_path):
        """악화된 매크로 조건 → 낮은 점수."""
        from nuri.analysis.regime.macro_score import compute_macro_score
        date = "2025-06-15"
        upsert_macro([
            {"indicator": "us_10y_yield", "date": date, "value": 3.0, "source": "test"},
            {"indicator": "us_2y_yield", "date": date, "value": 4.5, "source": "test"},  # 역전
            {"indicator": "vix", "date": date, "value": 35.0, "source": "test"},
            {"indicator": "fear_greed", "date": date, "value": 10.0, "source": "test"},  # 극도 공포
            {"indicator": "unemployment", "date": date, "value": 7.0, "source": "test"},
            {"indicator": "cpi_yoy", "date": date, "value": 6.5, "source": "test"},
            {"indicator": "fed_funds_rate", "date": date, "value": 5.5, "source": "test"},
        ], db_path)
        score = compute_macro_score(date=date, db_path=db_path)
        assert score.total_score < 35
        assert score.interpretation in ("Cautious", "Adverse")


# ═══════════════════════════════════════════════════════
# D-3: 전략 매핑 테스트
# ═══════════════════════════════════════════════════════


class TestStrategyMap:
    """D-3 레짐별 전략 매핑 테스트."""

    def test_bull_strategy(self, bull_market):
        """상승장 → aggressive, 매수 시그널 추천."""
        from nuri.analysis.regime.strategy_map import map_regime_to_strategy
        rec = map_regime_to_strategy(db_path=bull_market)
        assert rec is not None
        assert rec.position_sizing == "aggressive"
        assert len(rec.recommended_signals) > 0

    def test_bear_strategy(self, bear_market):
        """하락장 → minimal/defensive."""
        from nuri.analysis.regime.strategy_map import map_regime_to_strategy
        rec = map_regime_to_strategy(db_path=bear_market)
        assert rec is not None
        assert rec.position_sizing in ("defensive", "minimal")

    def test_no_data(self, db_path):
        """데이터 없으면 None."""
        from nuri.analysis.regime.strategy_map import map_regime_to_strategy
        rec = map_regime_to_strategy(db_path=db_path)
        assert rec is None

    def test_strategy_has_sector_preference(self, bull_market):
        """전략에 섹터 선호 목록이 있어야 함."""
        from nuri.analysis.regime.strategy_map import map_regime_to_strategy
        rec = map_regime_to_strategy(db_path=bull_market)
        assert rec is not None
        assert len(rec.sector_preference) > 0


# ═══════════════════════════════════════════════════════
# 동적 임계값 테스트
# ═══════════════════════════════════════════════════════


class TestDynamicThresholds:

    def test_thresholds_with_vix_data(self, bull_market):
        """VIX 데이터가 있으면 중앙값 기반 임계값."""
        from nuri.analysis.regime.classifier import compute_dynamic_thresholds
        th = compute_dynamic_thresholds(db_path=bull_market)
        assert "vix_threshold" in th
        assert "sideways_pct" in th
        assert th["sideways_pct"] >= 1.0  # 최소 1%

    def test_thresholds_without_data(self, db_path):
        """데이터 없으면 기본값 폴백."""
        from nuri.analysis.regime.classifier import compute_dynamic_thresholds
        th = compute_dynamic_thresholds(db_path=db_path)
        assert th["vix_threshold"] == 18.0  # 기본값
        assert th["sideways_pct"] == 2.0


# ═══════════════════════════════════════════════════════
# 섹터 분류 테스트
# ═══════════════════════════════════════════════════════


class TestSectorClassification:

    def test_classify_sector(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("Technology") == "growth"
        assert _classify_sector("EV/AI") == "growth"
        assert _classify_sector("AI/Cloud") == "growth"
        assert _classify_sector("Consumer Staples") == "defensive"
        assert _classify_sector("Health Care") == "defensive"
        assert _classify_sector("Utilities") == "defensive"
        assert _classify_sector("Finance") == "neutral"
        assert _classify_sector("") == "neutral"
        assert _classify_sector("Semiconductor") == "growth"

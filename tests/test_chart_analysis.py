"""차트 패턴 분석 (chart_analysis.py) 단위 테스트."""
import numpy as np
import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_prices
from nuri.quant.chart_analysis import (
    ChartAnalysis,
    analyze_chart,
    bb_position,
    bb_width_pct,
    distance_from_52w_high,
    distance_from_52w_low,
    macd_histogram_turn,
    trend_strength_9d,
    volume_profile_poc,
)

# ── helpers ──


def _make_df(closes, *, volumes=None, hists=None, bb=None) -> pd.DataFrame:
    df = pd.DataFrame({"close": closes})
    if volumes is not None:
        df["volume"] = volumes
    if hists is not None:
        df["macd_hist"] = hists
    if bb is not None:
        df["bb_upper"], df["bb_middle"], df["bb_lower"] = bb
    return df


# ═══════════════════════════════════════════════════════
# MACD histogram turn
# ═══════════════════════════════════════════════════════


class TestMacdHistogramTurn:
    def test_bullish_turn(self):
        df = _make_df([100, 101], hists=[-0.5, 0.2])
        assert macd_histogram_turn(df) == "bullish"

    def test_bearish_turn(self):
        df = _make_df([100, 101], hists=[0.5, -0.2])
        assert macd_histogram_turn(df) == "bearish"

    def test_no_turn_both_positive(self):
        df = _make_df([100, 101], hists=[0.3, 0.5])
        assert macd_histogram_turn(df) is None

    def test_no_turn_both_negative(self):
        df = _make_df([100, 101], hists=[-0.5, -0.3])
        assert macd_histogram_turn(df) is None

    def test_missing_column(self):
        df = pd.DataFrame({"close": [100, 101]})
        assert macd_histogram_turn(df) is None

    def test_nan_values(self):
        df = _make_df([100, 101], hists=[np.nan, 0.5])
        assert macd_histogram_turn(df) is None


# ═══════════════════════════════════════════════════════
# BB position
# ═══════════════════════════════════════════════════════


class TestBBPosition:
    def test_at_lower_band(self):
        df = _make_df([90.0], bb=([110], [100], [90]))
        assert bb_position(df) == 0.0

    def test_at_upper_band(self):
        df = _make_df([110.0], bb=([110], [100], [90]))
        assert bb_position(df) == 100.0

    def test_at_middle(self):
        df = _make_df([100.0], bb=([110], [100], [90]))
        assert bb_position(df) == 50.0

    def test_above_upper(self):
        df = _make_df([120.0], bb=([110], [100], [90]))
        assert bb_position(df) > 100.0

    def test_missing_columns(self):
        df = pd.DataFrame({"close": [100]})
        assert bb_position(df) == 50.0


class TestBBWidth:
    def test_normal_width(self):
        df = _make_df([100], bb=([110], [100], [90]))
        # width = (110-90) / 100 * 100 = 20
        assert bb_width_pct(df) == 20.0

    def test_zero_middle(self):
        df = _make_df([0], bb=([0], [0], [0]))
        assert bb_width_pct(df) == 0.0


# ═══════════════════════════════════════════════════════
# 52w distance
# ═══════════════════════════════════════════════════════


class TestDistance52w:
    def test_at_high(self):
        closes = [50, 60, 70, 80, 100]
        df = _make_df(closes)
        dist, high = distance_from_52w_high(df)
        assert dist == 0.0
        assert high == 100.0

    def test_below_high(self):
        closes = [50, 60, 100, 80, 90]
        df = _make_df(closes)
        dist, high = distance_from_52w_high(df)
        assert dist == -10.0
        assert high == 100.0

    def test_at_low(self):
        closes = [100, 80, 60, 40, 30]
        df = _make_df(closes)
        dist, low = distance_from_52w_low(df)
        assert dist == 0.0
        assert low == 30.0

    def test_above_low(self):
        closes = [100, 80, 60, 30, 33]
        df = _make_df(closes)
        dist, low = distance_from_52w_low(df)
        assert dist == 10.0
        assert low == 30.0


# ═══════════════════════════════════════════════════════
# Volume Profile POC
# ═══════════════════════════════════════════════════════


class TestVolumeProfilePOC:
    def test_poc_at_high_volume_price(self):
        # 가격 100에 거래량 집중, 90/110은 미미
        closes = [90, 100, 100, 100, 110]
        volumes = [10, 1000, 1000, 1000, 10]
        df = _make_df(closes, volumes=volumes)
        poc = volume_profile_poc(df, lookback=5, bins=5)
        # POC가 100 근처여야 함
        assert 95 <= poc <= 105

    def test_zero_volume_returns_current_price(self):
        closes = [100, 101, 102]
        volumes = [0, 0, 0]
        df = _make_df(closes, volumes=volumes)
        assert volume_profile_poc(df) == 102.0

    def test_missing_volume_column(self):
        df = pd.DataFrame({"close": [100, 101, 102]})
        assert volume_profile_poc(df) == 0.0


# ═══════════════════════════════════════════════════════
# Trend strength
# ═══════════════════════════════════════════════════════


class TestTrendStrength:
    def test_strong_uptrend(self):
        closes = [100, 102, 104, 106, 108, 110, 112, 114, 116]
        df = _make_df(closes)
        assert trend_strength_9d(df) > 50

    def test_strong_downtrend(self):
        closes = [116, 114, 112, 110, 108, 106, 104, 102, 100]
        df = _make_df(closes)
        assert trend_strength_9d(df) < -50

    def test_flat(self):
        closes = [100] * 9
        df = _make_df(closes)
        assert abs(trend_strength_9d(df)) < 1

    def test_insufficient_data(self):
        df = _make_df([100, 101, 102])
        assert trend_strength_9d(df) == 0.0


# ═══════════════════════════════════════════════════════
# analyze_chart 통합 (DB 사용)
# ═══════════════════════════════════════════════════════


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "chart.db"
    init_db(path)
    return path


@pytest.fixture
def seed_strong_uptrend(db_path):
    """강세 추세 데이터 생성."""
    base_price = 100.0
    rows = []
    for i in range(300):  # 300일 = 약 14개월 (52주 + 여유)
        price = base_price * (1 + 0.005 * i)  # 매일 +0.5%
        rows.append({
            "ticker": "TEST_UP",
            "date": f"2025-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}",
            "open": price * 0.99,
            "high": price * 1.01,
            "low": price * 0.98,
            "close": price,
            "volume": 1_000_000,
            "adj_close": price,
        })
    df = pd.DataFrame(rows)
    upsert_prices(df, db_path=db_path)
    return db_path


def test_analyze_chart_returns_dataclass(seed_strong_uptrend):
    result = analyze_chart("TEST_UP", db_path=seed_strong_uptrend)
    assert isinstance(result, ChartAnalysis)
    assert result.ticker == "TEST_UP"
    assert result.price > 0


def test_analyze_chart_strong_uptrend_visual_bias(seed_strong_uptrend):
    result = analyze_chart("TEST_UP", db_path=seed_strong_uptrend)
    # 강세 추세에서 visual_bias가 bullish이어야 함
    assert result.visual_bias in ("bullish", "neutral")  # neutral 허용 (BB 위치에 따라)
    assert result.trend_strength > 0
    # 52주 고점 근접 (지속 상승이므로 거의 고점)
    assert result.dist_from_52w_high >= -5


def test_analyze_chart_missing_ticker(db_path):
    result = analyze_chart("DOES_NOT_EXIST", db_path=db_path)
    assert result.price == 0.0
    assert "데이터 부족" in result.reasons


def test_analyze_chart_reasons_populated(seed_strong_uptrend):
    result = analyze_chart("TEST_UP", db_path=seed_strong_uptrend)
    assert len(result.reasons) > 0  # 최소 1개 이상의 패턴 설명

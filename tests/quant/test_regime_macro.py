"""Tests for regime_macro — split from test_quant_all.py."""

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


class TestMacroScore:
    """D-2 (from test_regime.py)."""

    def test_score_range(self, db_path):
        from nuri.quant.regime.macro_score import compute_macro_score

        score = compute_macro_score(db_path=db_path)
        assert 0 <= score.total_score <= 100

    def test_favorable_conditions(self, db_path):
        from nuri.quant.regime.macro_score import compute_macro_score

        date = "2025-01-15"
        upsert_macro(
            [
                {"indicator": "us_10y_yield", "date": date, "value": 4.0, "source": "test"},
                {"indicator": "us_2y_yield", "date": date, "value": 3.0, "source": "test"},
                {"indicator": "vix", "date": date, "value": 14.0, "source": "test"},
                {"indicator": "fear_greed", "date": date, "value": 55.0, "source": "test"},
                {"indicator": "unemployment", "date": date, "value": 3.8, "source": "test"},
                {"indicator": "cpi_yoy", "date": date, "value": 2.1, "source": "test"},
                {"indicator": "fed_funds_rate", "date": date, "value": 2.0, "source": "test"},
            ],
            db_path,
        )
        score = compute_macro_score(date=date, db_path=db_path)
        assert score.total_score > 65
        assert score.interpretation == "Favorable"

    def test_adverse_conditions(self, db_path):
        from nuri.quant.regime.macro_score import compute_macro_score

        date = "2025-06-15"
        upsert_macro(
            [
                {"indicator": "us_10y_yield", "date": date, "value": 3.0, "source": "test"},
                {"indicator": "us_2y_yield", "date": date, "value": 4.5, "source": "test"},
                {"indicator": "vix", "date": date, "value": 35.0, "source": "test"},
                {"indicator": "fear_greed", "date": date, "value": 10.0, "source": "test"},
                {"indicator": "unemployment", "date": date, "value": 7.0, "source": "test"},
                {"indicator": "cpi_yoy", "date": date, "value": 6.5, "source": "test"},
                {"indicator": "fed_funds_rate", "date": date, "value": 5.5, "source": "test"},
            ],
            db_path,
        )
        score = compute_macro_score(date=date, db_path=db_path)
        assert score.total_score < 35
        assert score.interpretation in ("Cautious", "Adverse")


class TestMacroScoreWarnings:
    """(from test_data_integrity.py)."""

    def test_empty_db_has_all_warnings(self, db_path):
        from nuri.quant.regime.macro_score import compute_macro_score

        score = compute_macro_score(db_path=db_path)
        assert score.warnings is not None
        assert len(score.warnings) == 8

    def test_partial_data_partial_warnings(self, db_path):
        date = "2025-01-15"
        upsert_macro(
            [
                {"indicator": "vix", "date": date, "value": 15.0, "source": "test"},
                {"indicator": "fear_greed", "date": date, "value": 50.0, "source": "test"},
            ],
            db_path,
        )
        from nuri.quant.regime.macro_score import compute_macro_score

        score = compute_macro_score(date=date, db_path=db_path)
        assert score.warnings is not None
        warning_names = [w.split(":")[0] for w in score.warnings]
        assert "vix" not in warning_names
        assert "sentiment" not in warning_names
        assert len(score.warnings) == 6

    def test_full_data_no_warnings(self, db_path):
        date = "2025-01-15"
        upsert_macro(
            [
                {"indicator": "us_10y_yield", "date": date, "value": 4.0, "source": "test"},
                {"indicator": "us_2y_yield", "date": date, "value": 3.0, "source": "test"},
                {"indicator": "us_3m_yield", "date": date, "value": 2.5, "source": "test"},
                {"indicator": "vix", "date": date, "value": 15.0, "source": "test"},
                {"indicator": "put_call_ratio", "date": date, "value": 0.85, "source": "test"},
                {"indicator": "fear_greed", "date": date, "value": 55.0, "source": "test"},
                {"indicator": "unemployment", "date": date, "value": 3.8, "source": "test"},
                {"indicator": "cpi_yoy", "date": date, "value": 2.1, "source": "test"},
                {"indicator": "fed_funds_rate", "date": date, "value": 2.0, "source": "test"},
            ],
            db_path,
        )
        from nuri.quant.regime.macro_score import compute_macro_score

        score = compute_macro_score(date=date, db_path=db_path)
        assert score.warnings is None

    def test_score_still_50_when_missing(self, db_path):
        from nuri.quant.regime.macro_score import compute_macro_score

        score = compute_macro_score(db_path=db_path)
        assert score.total_score == 50.0


class TestMacroScoreExtended:
    """(from test_coverage_final.py)."""

    def test_compute(self, rich_db):
        from nuri.quant.regime.macro_score import compute_macro_score

        score = compute_macro_score(db_path=rich_db)
        assert hasattr(score, "total_score")
        assert 0 <= score.total_score <= 100

    def test_print(self, rich_db, capsys):
        from nuri.quant.regime.macro_score import compute_macro_score, print_macro_score

        score = compute_macro_score(db_path=rich_db)
        print_macro_score(score)
        output = capsys.readouterr().out
        assert "Macro" in output or "매크로" in output


class TestMacroScoreEventIntegration:
    """B2/B4: event_score 통합 및 회귀 테스트 (#142)."""

    def test_no_events_score_near_original(self, db_path):
        """B4 회귀: 이벤트 0건 → event_score 50 (중립) → 기존 대비 ±5점."""
        from nuri.quant.regime.macro_score import compute_macro_score

        score = compute_macro_score(db_path=db_path)
        # event_score should be 50 (neutral, no events)
        assert score.event_score == 50.0
        # Empty DB → all indicators default to 50 → total ~50
        # event weight (10%) × 50 = 5, same as other defaults
        assert 40 <= score.total_score <= 60

    def test_event_score_field_exists(self, db_path):
        """MacroScore dataclass has event_score field."""
        from nuri.quant.regime.macro_score import compute_macro_score

        score = compute_macro_score(db_path=db_path)
        assert hasattr(score, "event_score")
        assert isinstance(score.event_score, float)

    def test_negative_events_lower_score(self, db_path):
        """Strong negative events → lower macro_score."""
        from nuri.quant.regime.macro_score import compute_macro_score

        # Baseline without events
        baseline = compute_macro_score(db_path=db_path)

        # Add strong negative events
        with get_db(db_path) as conn:
            for i in range(10):
                conn.execute(
                    "INSERT INTO macro_events (published_at, source, headline, url, category, sentiment, confidence) "
                    "VALUES (?, 'test', 'war headline', ?, 'geopolitical_escalation', -0.8, 0.9)",
                    (today_kst(), f"http://test/neg-{i}"),
                )

        with_events = compute_macro_score(db_path=db_path)
        assert with_events.event_score < 50  # Below neutral
        assert with_events.total_score < baseline.total_score

    def test_positive_events_raise_score(self, db_path):
        """Strong positive events → higher macro_score."""
        from nuri.quant.regime.macro_score import compute_macro_score

        baseline = compute_macro_score(db_path=db_path)

        with get_db(db_path) as conn:
            for i in range(10):
                conn.execute(
                    "INSERT INTO macro_events (published_at, source, headline, url, category, sentiment, confidence) "
                    "VALUES (?, 'test', 'rate cut', ?, 'fed_dovish', 0.7, 0.85)",
                    (today_kst(), f"http://test/pos-{i}"),
                )

        with_events = compute_macro_score(db_path=db_path)
        assert with_events.event_score > 50
        assert with_events.total_score > baseline.total_score

    def test_event_details_in_output(self, db_path):
        """details dict includes event metadata."""
        from nuri.quant.regime.macro_score import compute_macro_score

        score = compute_macro_score(db_path=db_path)
        assert "event_raw" in score.details
        assert "event_count" in score.details

    def test_weights_sum_to_one(self):
        """B2: all 9 weights sum to 1.0."""
        from nuri.quant.regime.macro_score import WEIGHTS

        assert len(WEIGHTS) == 9
        assert abs(sum(WEIGHTS.values()) - 1.0) < 0.01


class TestMacroScoreBoundaryBranches:
    """모든 piece-wise 점수 함수의 boundary 분기 (lines 90, 94, 96, 117, 134, 136,
    155, 159, 166, 187, 193, 213, 217, 219, 226, 248, 252, 254, 257, 285, 288, 291)."""

    def _seed(self, db_path, indicator, value, date="2025-06-15"):
        upsert_macro([{"indicator": indicator, "date": date, "value": value, "source": "test"}], db_path)

    def test_yield_curve_normal_high_spread(self, db_path):
        """spread > 1.0 → 100 (line 90)."""
        from nuri.quant.regime.macro_score import _score_yield_curve

        self._seed(db_path, "us_10y_yield", 5.0)
        self._seed(db_path, "us_2y_yield", 3.0)  # spread = 2.0
        score, _ = _score_yield_curve(db_path=db_path, date="2025-06-15")
        assert score == 100.0

    def test_yield_curve_mid_spread(self, db_path):
        """0 < spread <= 0.5 → 50~75 (line 94)."""
        from nuri.quant.regime.macro_score import _score_yield_curve

        self._seed(db_path, "us_10y_yield", 4.3)
        self._seed(db_path, "us_2y_yield", 4.0)  # spread = 0.3
        score, _ = _score_yield_curve(db_path=db_path, date="2025-06-15")
        assert 50 < score < 75

    def test_yield_curve_mild_inversion(self, db_path):
        """-0.5 < spread <= 0 → 25~50 (line 96)."""
        from nuri.quant.regime.macro_score import _score_yield_curve

        self._seed(db_path, "us_10y_yield", 4.0)
        self._seed(db_path, "us_2y_yield", 4.3)  # spread = -0.3
        score, _ = _score_yield_curve(db_path=db_path, date="2025-06-15")
        assert 25 < score < 50

    def test_vix_extreme_high(self, db_path):
        """VIX > 30 → 0~20 (line 117 not, 119)."""
        from nuri.quant.regime.macro_score import _score_vix

        self._seed(db_path, "vix", 32.0)
        score, _ = _score_vix(db_path=db_path, date="2025-06-15")
        assert 0 <= score < 20

    def test_vix_mid_high(self, db_path):
        """VIX 20~30 (line 117 — 20 ≤ vix < 30 → score 20~60)."""
        from nuri.quant.regime.macro_score import _score_vix

        self._seed(db_path, "vix", 25.0)
        score, _ = _score_vix(db_path=db_path, date="2025-06-15")
        assert 20 < score < 60

    def test_sentiment_low_fear(self, db_path):
        """25 ≤ fg < 40 (line 134)."""
        from nuri.quant.regime.macro_score import _score_sentiment

        self._seed(db_path, "fear_greed", 30.0)
        score, _ = _score_sentiment(db_path=db_path, date="2025-06-15")
        assert 50 < score < 80

    def test_sentiment_mild_greed(self, db_path):
        """60 < fg <= 75 (line 136)."""
        from nuri.quant.regime.macro_score import _score_sentiment

        self._seed(db_path, "fear_greed", 70.0)
        score, _ = _score_sentiment(db_path=db_path, date="2025-06-15")
        assert 50 < score < 80

    def test_employment_with_trend(self, db_path):
        """trend != None → trend_adj 적용 (lines 165-166)."""
        from nuri.quant.regime.macro_score import _score_employment

        self._seed(db_path, "unemployment", 4.0, date="2025-06-15")
        # 3 개월 전 더 낮은 값 → trend 양수 (악화)
        self._seed(db_path, "unemployment", 3.0, date="2025-03-15")
        score, _ = _score_employment(db_path=db_path, date="2025-06-15")
        assert 0 <= score <= 100

    def test_employment_low_unemployment_below_3_5(self, db_path):
        """unemp < 3.5 → 100 (line 155)."""
        from nuri.quant.regime.macro_score import _score_employment

        self._seed(db_path, "unemployment", 3.0)
        score, _ = _score_employment(db_path=db_path, date="2025-06-15")
        assert score >= 90

    def test_employment_mid_high(self, db_path):
        """4.5 <= unemp < 6 (line 159)."""
        from nuri.quant.regime.macro_score import _score_employment

        self._seed(db_path, "unemployment", 5.0)
        score, _ = _score_employment(db_path=db_path, date="2025-06-15")
        assert 30 < score < 70

    def test_inflation_mid_deviation(self, db_path):
        """1.5 < deviation <= 3.0 (line 187)."""
        from nuri.quant.regime.macro_score import _score_inflation

        self._seed(db_path, "cpi_yoy", 4.0)  # deviation 2.0
        score, _ = _score_inflation(db_path=db_path, date="2025-06-15")
        assert 20 < score < 60

    def test_inflation_deflation_capped(self, db_path):
        """cpi < 0 → 추가 감점 score = min(score, 20) (line 193)."""
        from nuri.quant.regime.macro_score import _score_inflation

        self._seed(db_path, "cpi_yoy", -1.0)
        score, _ = _score_inflation(db_path=db_path, date="2025-06-15")
        assert score <= 20

    def test_monetary_low_rate(self, db_path):
        """fed_funds < 1 → 90 (line 213)."""
        from nuri.quant.regime.macro_score import _score_monetary

        self._seed(db_path, "fed_funds_rate", 0.5)
        score, _ = _score_monetary(db_path=db_path, date="2025-06-15")
        assert score >= 80  # 90 ± trend

    def test_monetary_with_rising_trend(self, db_path):
        """trend != None → trend_adj 적용 (line 226)."""
        from nuri.quant.regime.macro_score import _score_monetary

        self._seed(db_path, "fed_funds_rate", 3.0, date="2025-06-15")
        self._seed(db_path, "fed_funds_rate", 1.0, date="2024-12-15")  # 6개월 전 — 인상 중
        score, _ = _score_monetary(db_path=db_path, date="2025-06-15")
        assert 0 <= score <= 100

    def test_monetary_mid_high_rate(self, db_path):
        """4 <= fed < 5.5 (line 219)."""
        from nuri.quant.regime.macro_score import _score_monetary

        self._seed(db_path, "fed_funds_rate", 4.5)
        score, _ = _score_monetary(db_path=db_path, date="2025-06-15")
        assert 0 <= score <= 100

    def test_monetary_2_5_4_range(self, db_path):
        """2.5 <= fed < 4 (line 217)."""
        from nuri.quant.regime.macro_score import _score_monetary

        self._seed(db_path, "fed_funds_rate", 3.0)
        score, _ = _score_monetary(db_path=db_path, date="2025-06-15")
        assert 30 <= score <= 100

    def test_yield_curve_3m10y_normal_high(self, db_path):
        """3m10y spread > 1.5 → 100 (line 248)."""
        from nuri.quant.regime.macro_score import _score_yield_spread_3m10y

        self._seed(db_path, "us_10y_yield", 5.5)
        self._seed(db_path, "us_3m_yield", 3.5)  # spread 2.0
        score, _ = _score_yield_spread_3m10y(db_path=db_path, date="2025-06-15")
        assert score == 100.0

    def test_yield_curve_3m10y_mid_high(self, db_path):
        """1.0 < spread <= 1.5 (line 250)."""
        from nuri.quant.regime.macro_score import _score_yield_spread_3m10y

        self._seed(db_path, "us_10y_yield", 4.7)
        self._seed(db_path, "us_3m_yield", 3.5)  # spread 1.2
        score, _ = _score_yield_spread_3m10y(db_path=db_path, date="2025-06-15")
        assert 65 <= score < 100

    def test_yield_curve_3m10y_low_mid(self, db_path):
        """0.5 < spread <= 1.0 (line 252)."""
        from nuri.quant.regime.macro_score import _score_yield_spread_3m10y

        self._seed(db_path, "us_10y_yield", 4.3)
        self._seed(db_path, "us_3m_yield", 3.5)  # spread 0.8
        score, _ = _score_yield_spread_3m10y(db_path=db_path, date="2025-06-15")
        assert 60 <= score < 90

    def test_yield_curve_3m10y_low_positive(self, db_path):
        """0 < spread <= 0.5 (line 254)."""
        from nuri.quant.regime.macro_score import _score_yield_spread_3m10y

        self._seed(db_path, "us_10y_yield", 4.3)
        self._seed(db_path, "us_3m_yield", 4.0)  # spread 0.3
        score, _ = _score_yield_spread_3m10y(db_path=db_path, date="2025-06-15")
        assert 50 < score < 65

    def test_yield_curve_3m10y_mild_inversion(self, db_path):
        """-0.5 < spread <= 0 (line 257)."""
        from nuri.quant.regime.macro_score import _score_yield_spread_3m10y

        self._seed(db_path, "us_10y_yield", 4.0)
        self._seed(db_path, "us_3m_yield", 4.3)  # spread -0.3
        score, _ = _score_yield_spread_3m10y(db_path=db_path, date="2025-06-15")
        assert 20 < score < 50

    def test_pcr_mid_high_range(self, db_path):
        """0.95 < pcr <= 1.10 (line 286-288)."""
        from nuri.quant.regime.macro_score import _score_put_call_ratio

        self._seed(db_path, "put_call_ratio", 1.0)
        score, _ = _score_put_call_ratio(db_path=db_path, date="2025-06-15")
        assert 65 <= score < 100

    def test_pcr_below_neutral(self, db_path):
        """0.70 <= pcr < 0.80 (line 285)."""
        from nuri.quant.regime.macro_score import _score_put_call_ratio

        self._seed(db_path, "put_call_ratio", 0.75)
        score, _ = _score_put_call_ratio(db_path=db_path, date="2025-06-15")
        assert 65 <= score < 90

    def test_pcr_low_extreme(self, db_path):
        """pcr < 0.70 → 과도한 탐욕 (line 288)."""
        from nuri.quant.regime.macro_score import _score_put_call_ratio

        self._seed(db_path, "put_call_ratio", 0.5)
        score, _ = _score_put_call_ratio(db_path=db_path, date="2025-06-15")
        assert score <= 65

    def test_pcr_high_extreme(self, db_path):
        """pcr > 1.10 → 과도한 공포 (line 291)."""
        from nuri.quant.regime.macro_score import _score_put_call_ratio

        self._seed(db_path, "put_call_ratio", 1.4)
        score, _ = _score_put_call_ratio(db_path=db_path, date="2025-06-15")
        assert score <= 65

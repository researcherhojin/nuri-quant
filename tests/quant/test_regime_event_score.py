"""Tests for nuri.quant.regime.event_score."""
from unittest.mock import patch

import pytest

from nuri.core.db import get_db, init_db
from nuri.quant.regime.event_score import (
    CATEGORY_WEIGHT,
    EventScore,
    compute_event_score,
    print_event_score,
)


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _insert_events(db_path, events):
    """Insert macro_events rows."""
    with get_db(db_path) as conn:
        for e in events:
            conn.execute(
                "INSERT INTO macro_events (published_at, source, headline, url, category, sentiment, confidence, regime_hint) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (e.get("published_at", "2026-04-09"),
                 e.get("source", "test"),
                 e.get("headline", "test headline"),
                 e.get("url", f"http://test/{id(e)}"),
                 e.get("category", "neutral"),
                 e.get("sentiment", 0.0),
                 e.get("confidence", 0.5),
                 e.get("regime_hint")),
            )


class TestEventScoreDataclass:
    def test_create(self):
        es = EventScore(
            date="2026-04-09", score=5.0, event_count=10,
            category_breakdown={"fed_dovish": 2.0}, dominant_category="fed_dovish",
            regime_hint="bull_low_vol",
        )
        assert es.score == 5.0
        assert es.event_count == 10

    def test_zero_events(self):
        es = EventScore(
            date="2026-04-09", score=0.0, event_count=0,
            category_breakdown={}, dominant_category=None, regime_hint=None,
        )
        assert es.score == 0.0
        assert es.dominant_category is None


class TestCategoryWeights:
    def test_all_categories_present(self):
        """All event_classifier categories have weights."""
        from nuri.llm.event_classifier import CATEGORIES
        for cat in CATEGORIES:
            assert cat in CATEGORY_WEIGHT, f"Missing weight for category: {cat}"

    def test_neutral_is_zero(self):
        assert CATEGORY_WEIGHT["neutral"] == 0.0

    def test_escalation_is_negative(self):
        assert CATEGORY_WEIGHT["geopolitical_escalation"] < 0

    def test_dovish_is_positive(self):
        assert CATEGORY_WEIGHT["fed_dovish"] > 0


class TestComputeEventScore:
    def test_empty_db_returns_zero(self, db_path):
        """No events → score 0."""
        es = compute_event_score(db_path=db_path, date="2026-04-09")
        assert es.score == 0.0
        assert es.event_count == 0
        assert es.dominant_category is None

    def test_single_positive_event(self, db_path):
        """Fed dovish → positive score."""
        _insert_events(db_path, [
            {"category": "fed_dovish", "sentiment": 0.5, "confidence": 0.8},
        ])
        es = compute_event_score(db_path=db_path, date="2026-04-09")
        assert es.score > 0
        assert es.event_count == 1
        assert es.dominant_category == "fed_dovish"

    def test_single_negative_event(self, db_path):
        """Geopolitical escalation → negative score."""
        _insert_events(db_path, [
            {"category": "geopolitical_escalation", "sentiment": -0.6, "confidence": 0.9},
        ])
        es = compute_event_score(db_path=db_path, date="2026-04-09")
        assert es.score < 0
        assert es.dominant_category == "geopolitical_escalation"

    def test_neutral_events_only(self, db_path):
        """All neutral → score ~0."""
        _insert_events(db_path, [
            {"category": "neutral", "sentiment": 0.0, "confidence": 0.5},
            {"category": "neutral", "sentiment": 0.1, "confidence": 0.3},
        ])
        es = compute_event_score(db_path=db_path, date="2026-04-09")
        assert abs(es.score) < 1.0

    def test_mixed_events_cancel_out(self, db_path):
        """Opposing events partially cancel."""
        _insert_events(db_path, [
            {"category": "fed_dovish", "sentiment": 0.5, "confidence": 0.8},
            {"category": "fed_hawkish", "sentiment": -0.5, "confidence": 0.8},
        ])
        es = compute_event_score(db_path=db_path, date="2026-04-09")
        # Not exactly zero due to different weights, but closer to zero than single event
        assert abs(es.score) < 15

    def test_score_clamped_to_range(self, db_path):
        """Score never exceeds [-20, +20]."""
        # Insert many strong negative events
        events = [
            {"category": "geopolitical_escalation", "sentiment": -0.9, "confidence": 0.95,
             "url": f"http://test/clamp-{i}"}
            for i in range(50)
        ]
        _insert_events(db_path, events)
        es = compute_event_score(db_path=db_path, date="2026-04-09")
        assert es.score >= -20.0
        assert es.score <= 20.0

    def test_lookback_filters_old_events(self, db_path):
        """Events outside lookback window are excluded."""
        _insert_events(db_path, [
            {"category": "fed_dovish", "sentiment": 0.8, "confidence": 0.9,
             "published_at": "2026-03-01"},  # old
        ])
        es = compute_event_score(db_path=db_path, date="2026-04-09", lookback_days=3)
        assert es.event_count == 0
        assert es.score == 0.0

    def test_zero_sentiment_uses_half_weight(self, db_path):
        """When sentiment is 0, contribution = weight × confidence × 0.5."""
        _insert_events(db_path, [
            {"category": "fed_dovish", "sentiment": 0.0, "confidence": 0.8},
        ])
        es = compute_event_score(db_path=db_path, date="2026-04-09")
        assert es.score > 0  # Still positive because category weight is positive

    def test_regime_hint_from_dominant(self, db_path):
        """Dominant category maps to regime hint."""
        _insert_events(db_path, [
            {"category": "geopolitical_de_escalation", "sentiment": 0.5, "confidence": 0.8},
        ])
        es = compute_event_score(db_path=db_path, date="2026-04-09")
        assert es.regime_hint == "recovery"

    def test_category_breakdown_populated(self, db_path):
        """Breakdown shows per-category contributions."""
        _insert_events(db_path, [
            {"category": "earnings_beat", "sentiment": 0.6, "confidence": 0.7, "url": "http://t/1"},
            {"category": "trade_war", "sentiment": -0.4, "confidence": 0.8, "url": "http://t/2"},
        ])
        es = compute_event_score(db_path=db_path, date="2026-04-09")
        assert "earnings_beat" in es.category_breakdown
        assert "trade_war" in es.category_breakdown
        assert es.category_breakdown["earnings_beat"] > 0
        assert es.category_breakdown["trade_war"] < 0


class TestNewCategories:
    """#137 신규 카테고리 가중치 검증."""

    def test_export_surge_positive(self, db_path):
        _insert_events(db_path, [
            {"category": "export_surge", "sentiment": 0.7, "confidence": 0.8, "url": "http://t/export1"},
        ])
        es = compute_event_score(db_path=db_path, date="2026-04-09")
        assert es.score > 0
        assert es.dominant_category == "export_surge"
        assert es.regime_hint == "recovery"

    def test_demand_growth_positive(self, db_path):
        _insert_events(db_path, [
            {"category": "demand_growth", "sentiment": 0.6, "confidence": 0.85, "url": "http://t/demand1"},
        ])
        es = compute_event_score(db_path=db_path, date="2026-04-09")
        assert es.score > 0
        assert es.regime_hint == "bull_low_vol"

    def test_currency_shift_negative_by_default(self, db_path):
        _insert_events(db_path, [
            {"category": "currency_shift", "sentiment": -0.5, "confidence": 0.7, "url": "http://t/fx1"},
        ])
        es = compute_event_score(db_path=db_path, date="2026-04-09")
        assert es.score < 0  # currency_shift weight is -0.35


class TestConfidenceFloor:
    """신뢰도 < 0.3 이벤트는 스코어 계산에서 제외 (#137)."""

    def test_low_confidence_events_excluded(self, db_path):
        """confidence < 0.3 이벤트는 무시된다."""
        _insert_events(db_path, [
            # 저신뢰 이벤트 — 제외되어야 함
            {"category": "geopolitical_escalation", "sentiment": -0.8, "confidence": 0.2, "url": "http://t/low1"},
            {"category": "sector_selloff", "sentiment": -0.9, "confidence": 0.1, "url": "http://t/low2"},
        ])
        es = compute_event_score(db_path=db_path, date="2026-04-09")
        assert es.event_count == 0  # 둘 다 제외
        assert es.score == 0.0

    def test_mixed_confidence_only_high_counted(self, db_path):
        """고신뢰만 스코어에 반영, 저신뢰는 제외."""
        _insert_events(db_path, [
            {"category": "earnings_beat", "sentiment": 0.7, "confidence": 0.8, "url": "http://t/high1"},
            {"category": "sector_selloff", "sentiment": -0.9, "confidence": 0.15, "url": "http://t/low1"},
        ])
        es = compute_event_score(db_path=db_path, date="2026-04-09")
        assert es.event_count == 1  # 고신뢰만
        assert es.score > 0  # earnings_beat만 반영 → 양수

    def test_threshold_boundary(self, db_path):
        """confidence == 0.3 이벤트는 포함 (>=)."""
        _insert_events(db_path, [
            {"category": "fed_dovish", "sentiment": 0.5, "confidence": 0.3, "url": "http://t/boundary"},
        ])
        es = compute_event_score(db_path=db_path, date="2026-04-09")
        assert es.event_count == 1
        assert es.score > 0


class TestSimulation:
    """B5: 시뮬레이션 검증 — 복합 이벤트 시나리오."""

    def test_ceasefire_oil_drop_semi_rotation(self, db_path):
        """Iran ceasefire + oil -8% + semi rotation → strong positive score."""
        _insert_events(db_path, [
            # 휴전 뉴스 (강한 긍정)
            {"category": "geopolitical_de_escalation", "sentiment": 0.8, "confidence": 0.9,
             "url": "http://t/ceasefire-1"},
            {"category": "geopolitical_de_escalation", "sentiment": 0.7, "confidence": 0.85,
             "url": "http://t/ceasefire-2"},
            {"category": "geopolitical_de_escalation", "sentiment": 0.6, "confidence": 0.8,
             "url": "http://t/ceasefire-3"},
            # 유가 하락 (공급 정상화 → 긍정적 결과)
            {"category": "oil_demand_drop", "sentiment": 0.3, "confidence": 0.7,
             "url": "http://t/oil-1"},
            # 반도체 섹터 랠리
            {"category": "sector_rally", "sentiment": 0.6, "confidence": 0.8,
             "url": "http://t/semi-1"},
            {"category": "sector_rally", "sentiment": 0.5, "confidence": 0.75,
             "url": "http://t/semi-2"},
        ])
        es = compute_event_score(db_path=db_path, date="2026-04-09")
        assert es.score > 5, f"Expected positive score, got {es.score}"
        assert es.event_count == 6
        assert es.dominant_category == "geopolitical_de_escalation"
        assert es.regime_hint == "recovery"

    def test_war_escalation_scenario(self, db_path):
        """War escalation + trade war → strong negative score."""
        _insert_events(db_path, [
            {"category": "geopolitical_escalation", "sentiment": -0.8, "confidence": 0.9,
             "url": "http://t/war-1"},
            {"category": "geopolitical_escalation", "sentiment": -0.7, "confidence": 0.85,
             "url": "http://t/war-2"},
            {"category": "trade_war", "sentiment": -0.6, "confidence": 0.8,
             "url": "http://t/trade-1"},
            {"category": "trade_war", "sentiment": -0.5, "confidence": 0.75,
             "url": "http://t/trade-2"},
        ])
        es = compute_event_score(db_path=db_path, date="2026-04-09")
        assert es.score < -5, f"Expected negative score, got {es.score}"
        assert es.dominant_category == "geopolitical_escalation"
        assert es.regime_hint == "bear_high_vol"


class TestPrintEventScore:
    def test_print_with_events(self, capsys):
        es = EventScore(
            date="2026-04-09", score=8.5, event_count=15,
            category_breakdown={"fed_dovish": 3.5, "earnings_beat": 2.0},
            dominant_category="fed_dovish", regime_hint="bull_low_vol",
        )
        print_event_score(es)
        output = capsys.readouterr().out
        assert "+8.5" in output
        assert "15 events" in output
        assert "fed_dovish" in output
        assert "bull_low_vol" in output

    def test_print_no_events(self, capsys):
        es = EventScore(
            date="2026-04-09", score=0.0, event_count=0,
            category_breakdown={}, dominant_category=None, regime_hint=None,
        )
        print_event_score(es)
        output = capsys.readouterr().out
        assert "+0.0" in output
        assert "0 events" in output

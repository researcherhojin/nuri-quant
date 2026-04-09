"""Tests for nuri.llm.event_classifier — regex fallback + Ollama mock.

Network-free: 모든 Ollama 호출은 monkeypatch로 mock.
"""
from unittest.mock import MagicMock

import pytest

from nuri.llm.event_classifier import (
    CATEGORIES,
    REGIME_HINT_BY_CATEGORY,
    _classify_with_regex,
    _normalize,
    classify_event,
)


class TestModuleInvariants:
    """REGIME_HINT 매핑이 모든 카테고리 커버하는지."""

    def test_every_category_has_regime_hint(self):
        missing = [c for c in CATEGORIES if c not in REGIME_HINT_BY_CATEGORY]
        assert not missing, f"missing regime hints: {missing}"

    def test_neutral_has_no_regime_hint(self):
        assert REGIME_HINT_BY_CATEGORY["neutral"] is None


class TestRegexFallback:
    """결정론적 키워드 매칭. 네트워크 0."""

    @pytest.mark.parametrize(
        ("headline", "expected_category"),
        [
            ("Iran and Israel agree to ceasefire after 2 weeks", "geopolitical_de_escalation"),
            ("Russia missile strike hits Kyiv power grid", "geopolitical_escalation"),
            ("Fed signals rate cut next month", "fed_dovish"),
            ("Powell hints at hawkish tightening", "fed_hawkish"),
            ("OPEC+ cut sends oil supply tumbling", "oil_supply_shock"),
            ("NVDA crushed estimates with record revenue", "earnings_beat"),
            ("AAPL missed estimates, cut guidance", "earnings_miss"),
            ("S&P 500 jumps 2% after CPI miss", "sector_rally"),
            ("Semiconductor sector plunges 5%", "sector_selloff"),
            ("Trump announces new tariff on China", "trade_war"),
        ],
    )
    def test_keyword_categorization(self, headline, expected_category):
        result = _classify_with_regex(headline)
        assert result["category"] == expected_category
        assert result["regime_hint"] == REGIME_HINT_BY_CATEGORY[expected_category]
        assert result["confidence"] == 0.5  # regex는 항상 mid

    def test_empty_returns_neutral(self):
        result = classify_event("", use_llm=False)
        assert result["category"] == "neutral"
        assert result["sentiment"] == 0.0
        assert result["regime_hint"] is None

    def test_whitespace_returns_neutral(self):
        assert classify_event("   ", use_llm=False)["category"] == "neutral"

    def test_unmatched_returns_neutral(self):
        result = classify_event("The weather is nice today", use_llm=False)
        assert result["category"] == "neutral"


class TestNormalize:
    """LLM 출력 검증/클램프."""

    def test_clamps_sentiment_above_one(self):
        result = _normalize({"category": "fed_dovish", "sentiment": 5.0, "confidence": 0.8})
        assert result["sentiment"] == 1.0

    def test_clamps_sentiment_below_negative_one(self):
        result = _normalize({"category": "fed_hawkish", "sentiment": -3.5, "confidence": 0.7})
        assert result["sentiment"] == -1.0

    def test_clamps_confidence(self):
        result = _normalize({"category": "earnings_beat", "sentiment": 0.5, "confidence": 1.7})
        assert result["confidence"] == 1.0
        result2 = _normalize({"category": "earnings_beat", "sentiment": 0.5, "confidence": -0.3})
        assert result2["confidence"] == 0.0

    def test_unknown_category_falls_to_neutral_with_low_confidence(self):
        result = _normalize({"category": "alien_invasion", "sentiment": 0.9, "confidence": 0.95})
        assert result["category"] == "neutral"
        assert result["confidence"] == 0.2

    def test_attaches_regime_hint(self):
        result = _normalize({"category": "geopolitical_de_escalation", "sentiment": 0.6, "confidence": 0.8})
        assert result["regime_hint"] == "recovery"


class TestOllamaPath:
    """Ollama JSON 경로 — requests.post mock."""

    def test_ollama_success(self, monkeypatch):
        from nuri.llm import event_classifier as mod

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "response": '{"category": "fed_dovish", "sentiment": 0.4, "confidence": 0.85}'
        }
        mock_requests = MagicMock()
        mock_requests.post.return_value = mock_resp
        monkeypatch.setitem(__import__("sys").modules, "requests", mock_requests)

        result = mod.classify_event("Fed cuts rates by 50bps", use_llm=True)
        assert result["category"] == "fed_dovish"
        assert result["sentiment"] == 0.4
        assert result["confidence"] == 0.85
        assert result["regime_hint"] == "bull_low_vol"

    def test_ollama_connection_error_falls_back_to_regex(self, monkeypatch):
        from nuri.llm import event_classifier as mod

        mock_requests = MagicMock()
        mock_requests.post.side_effect = ConnectionError("Ollama down")
        monkeypatch.setitem(__import__("sys").modules, "requests", mock_requests)

        result = mod.classify_event("Iran ceasefire announced", use_llm=True)
        assert result["category"] == "geopolitical_de_escalation"
        assert result["confidence"] == 0.5  # regex fallback marker

    def test_ollama_invalid_json_falls_back(self, monkeypatch):
        from nuri.llm import event_classifier as mod

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"response": "not valid json {"}
        mock_requests = MagicMock()
        mock_requests.post.return_value = mock_resp
        monkeypatch.setitem(__import__("sys").modules, "requests", mock_requests)

        result = mod.classify_event("Russia escalates strikes on Ukraine", use_llm=True)
        # 깨진 JSON → ValueError → regex fallback
        assert result["category"] == "geopolitical_escalation"

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


class TestOpenAIPath_R152:
    """OpenAI gpt-5.4-nano 경로 (#152 Step 2) — wrapper.chat_json mock.

    LLM 경로의 wrapper 호출이 wrapper의 typed exceptions(Disabled,
    Unavailable, ResponseError) 어느 것을 raise하더라도 단일 헤드라인은
    조용히 regex로 폴백한다. wrapper의 audit/cost logging은 wrapper
    자체 테스트(test_openai_client.py)에서 검증된다.
    """

    def _patch_wrapper(self, monkeypatch, *, returns=None, raises=None):
        """get_client().chat_json을 패치한다."""
        from nuri.llm import event_classifier as ec_mod
        from nuri.llm import openai_client as cli_mod

        fake_client = MagicMock()
        if raises is not None:
            fake_client.chat_json.side_effect = raises
        else:
            fake_client.chat_json.return_value = returns or {}

        # Patch get_client to return our fake (event_classifier imports it lazily)
        monkeypatch.setattr(cli_mod, "_singleton", fake_client)
        # The lazy import inside _classify_with_openai uses get_client(), which
        # returns _singleton if non-None — so setting _singleton is sufficient.
        return fake_client, ec_mod

    def test_openai_success(self, monkeypatch):
        fake, mod = self._patch_wrapper(monkeypatch, returns={
            "category": "fed_dovish",
            "sentiment": 0.4,
            "confidence": 0.85,
        })
        result = mod.classify_event("Fed cuts rates by 50bps", use_llm=True)
        assert result["category"] == "fed_dovish"
        assert result["sentiment"] == 0.4
        assert result["confidence"] == 0.85
        assert result["regime_hint"] == "bull_low_vol"
        # wrapper called once with public headline only (Tier 0)
        assert fake.chat_json.call_count == 1
        call = fake.chat_json.call_args
        assert "Headline: Fed cuts rates by 50bps" in call.kwargs["user"]

    def test_unavailable_falls_back_to_regex(self, monkeypatch):
        from nuri.llm.openai_client import ExternalLLMUnavailable
        _, mod = self._patch_wrapper(
            monkeypatch,
            raises=ExternalLLMUnavailable("network down"),
        )
        result = mod.classify_event("Iran ceasefire announced", use_llm=True)
        # regex가 ceasefire를 잡음
        assert result["category"] == "geopolitical_de_escalation"
        assert result["confidence"] == 0.5  # regex fallback marker

    def test_disabled_falls_back_to_regex(self, monkeypatch):
        """NURI_DISABLE_EXTERNAL_LLM 시 wrapper raises Disabled → regex로 폴백."""
        from nuri.llm.openai_client import ExternalLLMDisabled
        _, mod = self._patch_wrapper(
            monkeypatch,
            raises=ExternalLLMDisabled("opt-out"),
        )
        result = mod.classify_event("Russia escalates strikes", use_llm=True)
        assert result["category"] == "geopolitical_escalation"

    def test_response_error_falls_back_to_regex(self, monkeypatch):
        from nuri.llm.openai_client import ExternalLLMResponseError
        _, mod = self._patch_wrapper(
            monkeypatch,
            raises=ExternalLLMResponseError("non-JSON garbage"),
        )
        result = mod.classify_event("OPEC+ cut sends oil supply tumbling", use_llm=True)
        assert result["category"] == "oil_supply_shock"

    def test_unknown_category_from_llm_normalizes_to_neutral(self, monkeypatch):
        """LLM이 미지의 category 반환 시 normalize로 neutral 변환."""
        _, mod = self._patch_wrapper(monkeypatch, returns={
            "category": "alien_invasion",
            "sentiment": 0.9,
            "confidence": 0.95,
        })
        result = mod.classify_event("Aliens land in Times Square", use_llm=True)
        assert result["category"] == "neutral"
        assert result["confidence"] == 0.2  # normalize의 unknown-category marker

    def test_use_llm_false_skips_wrapper_entirely(self, monkeypatch):
        """use_llm=False일 때 wrapper가 호출되지 않아야 한다 (offline test path)."""
        from nuri.llm import openai_client as cli_mod
        fake_client = MagicMock()
        monkeypatch.setattr(cli_mod, "_singleton", fake_client)

        from nuri.llm import event_classifier as mod
        mod.classify_event("Fed cuts rates", use_llm=False)
        assert fake_client.chat_json.call_count == 0

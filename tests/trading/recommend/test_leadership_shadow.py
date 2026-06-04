"""Lock-tests for P2 leadership shadow channels in _score_ticker.

핵심 불변식: weight=0 인 shadow 채널은 라이브 점수를 바꾸지 않는다 (sources 노출만).
+ crowding 가드(과열 추격 페널티) + RS percentile clamp.
"""

import pytest

from nuri.trading.recommend.buy_candidate_emitter import _build_why_now, _score_ticker

FACTOR = {"composite": 0.7}
PRICE = {"ret_5d": 2.0, "breakout_pct": 1.0, "close": 100.0}
LEGACY_W = {"factor_composite": 0.40, "momentum_5d": 0.25, "technical_rsi": 0.15, "breakout_30d": 0.20}
SHADOW_W = {**LEGACY_W, "rs_rank": 0.0, "dollar_volume": 0.0}


class TestLeadershipShadow:
    def test_adding_shadow_weights_keeps_legacy_score(self):
        # config 에 rs_rank/dollar_volume(=0) 추가 + 값 전달해도 점수는 legacy 와 IEEE-exact 동일
        legacy, _ = _score_ticker("X", FACTOR, PRICE, 50.0, LEGACY_W)
        shadow, _ = _score_ticker("X", FACTOR, PRICE, 50.0, SHADOW_W, rs_rank=95.0, dollar_volume=2.0)
        assert legacy == shadow  # x + 0.0*finite == x (strict)

    def test_weight_zero_invariant_to_leadership_values(self):
        none_lead, _ = _score_ticker("X", FACTOR, PRICE, 50.0, SHADOW_W)
        strong_lead, _ = _score_ticker("X", FACTOR, PRICE, 50.0, SHADOW_W, rs_rank=99.0, dollar_volume=2.4)
        assert none_lead == strong_lead  # weight=0 → 값 무관 (strict)

    def test_why_now_ignores_shadow_channels(self):
        # rs_rank/dollar_volume 이 sources 최댓값이어도 why_now 는 라이브 채널만 본다 (진짜 shadow)
        sources = {
            "factor": 60.0,
            "momentum": 55.0,
            "rsi": 50.0,
            "breakout": 50.0,
            "rs_rank": 99.0,  # shadow 최댓값
            "dollar_volume": 90.0,
        }
        why = _build_why_now(sources, {"ret_5d": 1.0, "breakout_pct": 0.0}, 50.0)
        assert "Multi-factor" in why  # factor(60) 가 라이브 최댓값 → factor 텍스트
        assert "Multi-source" not in why  # shadow argmax fallthrough 아님

    def test_sources_expose_shadow_channels(self):
        _, sources = _score_ticker("X", FACTOR, PRICE, 50.0, SHADOW_W, rs_rank=95.0, dollar_volume=2.0)
        assert "rs_rank" in sources and "dollar_volume" in sources
        assert sources["rs_rank"] == 95.0

    def test_missing_leadership_is_neutral(self):
        _, sources = _score_ticker("X", FACTOR, PRICE, 50.0, SHADOW_W)
        assert sources["rs_rank"] == 50.0
        assert sources["dollar_volume"] == 50.0

    def test_crowding_guard_penalizes_overheated_surge(self):
        _, moderate = _score_ticker("X", FACTOR, PRICE, 50.0, SHADOW_W, dollar_volume=2.0)
        _, overheated = _score_ticker("X", FACTOR, PRICE, 50.0, SHADOW_W, dollar_volume=6.0)
        # 과열 추격(surge 6.0)은 완만한 확장(2.0)보다 낮은 dollar_volume 점수 (급등주 추격 금지)
        assert overheated["dollar_volume"] < moderate["dollar_volume"]
        assert moderate["dollar_volume"] == pytest.approx(76.7, abs=0.1)

    def test_rs_percentile_clamped(self):
        _, hi = _score_ticker("X", FACTOR, PRICE, 50.0, SHADOW_W, rs_rank=150.0)
        _, lo = _score_ticker("X", FACTOR, PRICE, 50.0, SHADOW_W, rs_rank=-10.0)
        assert hi["rs_rank"] == 100.0
        assert lo["rs_rank"] == 0.0

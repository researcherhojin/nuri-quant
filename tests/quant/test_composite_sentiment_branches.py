"""합성 점수에 시장 센티먼트가 **있을 때** 실제로 더해지는지 — 없을 때의 재배분은 기존 테스트 몫."""

from __future__ import annotations

import pandas as pd
import pytest

from nuri.quant.factors import composite


def test_a_present_sentiment_is_added_with_its_configured_weight(monkeypatch):
    """momentum·value·quality 는 고정하고 센티먼트 0.9 를 준다 — 점수는 네 성분의 가중합이다.

    value/quality 가 없는 종목(TST_B)은 0.5(백분위 중앙)로 채운다.
    """
    monkeypatch.setattr(
        "nuri.quant.factors.momentum.compute_momentum",
        lambda: pd.DataFrame({"momentum_score": [0.8, 0.4]}, index=["TST_A", "TST_B"]),
    )
    monkeypatch.setattr(
        "nuri.quant.factors.value.compute_value",
        lambda tickers=None: pd.DataFrame({"value_score": [0.6]}, index=["TST_A"]),
    )
    monkeypatch.setattr(
        "nuri.quant.factors.quality.compute_quality",
        lambda tickers=None: pd.DataFrame({"quality_score": [0.7]}, index=["TST_A"]),
    )
    monkeypatch.setattr(composite, "_market_sentiment", lambda: 0.9)

    out = composite.compute_composite()

    assert out.loc["TST_A", "composite_score"] == pytest.approx(0.8 * 0.30 + 0.6 * 0.25 + 0.7 * 0.25 + 0.9 * 0.20)
    assert out.loc["TST_B", "composite_score"] == pytest.approx(0.4 * 0.30 + 0.5 * 0.25 + 0.5 * 0.25 + 0.9 * 0.20)
    assert set(out["sentiment_score"]) == {0.9}

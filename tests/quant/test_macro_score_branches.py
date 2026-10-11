"""매크로 종합 점수의 해석 밴드 — 전 성분이 측정된 약세 배경은 `Cautious` 다."""

from __future__ import annotations

import pytest

from nuri.core.db import init_db, upsert_macro
from nuri.core.timezone import today_kst
from nuri.quant.regime.macro_score import compute_macro_score


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "macro.db"
    init_db(path)
    return path


def test_a_weak_but_fully_measured_backdrop_reads_cautious(db_path):
    """역전된 곡선 · VIX 26 · 공포 35 · 높은 물가와 기준금리 — 30 ≤ 총점 < 50 이고 커버리지가
    충분하니 `Insufficient` 가 아니라 `Cautious` 다."""
    today = today_kst()
    values = {
        "us_10y_yield": 4.0,
        "us_2y_yield": 4.3,
        "us_3m_yield": 4.8,
        "vix": 26.0,
        "put_call_ratio": 1.0,
        "fear_greed": 35.0,
        "unemployment": 4.8,
        "cpi_yoy": 4.0,
        "fed_funds_rate": 5.0,
    }
    upsert_macro([{"indicator": k, "date": today, "value": v, "source": "test"} for k, v in values.items()], db_path)

    score = compute_macro_score(db_path=db_path)

    assert score.coverage == pytest.approx(1.0, abs=1e-6)
    assert 30 <= score.total_score < 50
    assert score.interpretation == "Cautious"

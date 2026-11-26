"""Learning Memory 의 나머지 분기 — 모르는 agent 의 판정 · 전부 0 인 가중치.

시드 날짜는 오늘 기준이다 — 집계 쿼리가 `date('now', -lookback)` 창이라 리터럴 날짜는
시간이 지나면 창 밖으로 밀려 테스트가 0행을 읽으며 초록이 된다 (tests/CLAUDE.md time-bomb).
"""

from __future__ import annotations

import logging

import pytest

from nuri.core.db import init_db
from nuri.core.db.connection import get_db
from nuri.core.timezone import today_kst
from nuri.trading.agents.consensus.learning_memory import _compute_horizon_eligibility, select_weight_source
from nuri.trading.agents.consensus.models import AgentEligibility
from nuri.trading.agents.consensus.registry import DEFAULT_WEIGHTS


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "lm.db"
    init_db(path)
    return path


def _seed(db_path, prefix: str, verdicts_json: str, n: int) -> None:
    with get_db(db_path) as conn:
        for i in range(n):
            conn.execute(
                "INSERT INTO recommendations (ticker, action, confidence, agent_verdicts, outcome_30d, date) "
                "VALUES (?, 'BUY', 70, ?, 0.05, ?)",
                (f"{prefix}{i:02d}", verdicts_json, today_kst()),
            )


def test_verdicts_from_agents_outside_the_roster_are_ignored(db_path, caplog):
    """로스터 밖 agent 의 판정은 아무 agent 의 적중률에도 들어가지 않는다 — 그것만 있는 행은
    `rows_skipped_no_usable` 로 센다. 로스터 agent 와 같이 있으면 로스터 쪽만 집계된다."""
    _seed(db_path, "OUT", '[{"agent_name": "retired_agent", "action": "BUY"}]', 3)
    _seed(
        db_path,
        "MIX",
        '[{"agent_name": "retired_agent", "action": "SELL"}, {"agent_name": "technical", "action": "BUY"}]',
        12,
    )

    with caplog.at_level(logging.INFO, logger="nuri.trading.agents.consensus.learning_memory"):
        elig = _compute_horizon_eligibility(
            outcome_col="outcome_30d", adjustment_range=0.30, label="canonical_30d", db_path=db_path
        )

    assert "retired_agent" not in elig
    assert (elig["technical"].sample_count, elig["technical"].eligible) == (12, True)
    assert "rows_seen=15 rows_parsed=12" in caplog.text and "rows_skipped_no_usable=3" in caplog.text


def test_all_zero_weights_are_returned_as_zeros_not_divided(db_path):
    """선택된 가중치 합이 0 이면 정규화하지 않는다 — 0 으로 나누지 않고 0 을 그대로 낸다."""
    zero = {name: AgentEligibility(name=name, sample_count=10, weight=0.0, eligible=True) for name in DEFAULT_WEIGHTS}

    weights, sources = select_weight_source(zero, {})

    assert weights == dict.fromkeys(DEFAULT_WEIGHTS, 0.0)
    assert set(sources.values()) == {"canonical_30d"}

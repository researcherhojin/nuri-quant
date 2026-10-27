"""#1979: 호환용 retail 슬롯은 과거 Reddit 데이터와 무관하게 기권한다."""

import pytest

from nuri.core.db import get_db, query
from nuri.trading.agents.consensus.registry import build_all_agents
from nuri.trading.agents.retail_agent import RetailAgent


@pytest.mark.parametrize("mentions", [None, 1.0, 15.0, 50.0])
def test_historical_reddit_data_cannot_vote(db_path, monkeypatch, mentions):
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT INTO macro (date, indicator, value) VALUES ('2026-10-27', ?, ?)",
            [("wsb_mention_TEST", mentions), ("wsb_post_count", 1500.0)],
        )
    before = query("SELECT * FROM macro", db_path=db_path)
    agent = RetailAgent()
    monkeypatch.setattr(agent, "_safe_query", lambda *a, **kw: pytest.fail("read retired input"))
    verdict = agent.analyze("TEST", db_path=db_path)
    assert verdict.action == "HOLD" and verdict.confidence == 0
    assert verdict.abstained and not verdict.degraded
    assert verdict.data_points == {} and "1979" in verdict.reasoning
    assert query("SELECT * FROM macro", db_path=db_path) == before


def test_compatibility_slot_never_needs_a_database():
    agent = next(agent for agent in build_all_agents() if agent.name == "retail")
    verdict = agent.analyze("TEST", db_path="/nonexistent-retired-input/no.db")
    assert verdict.abstained and verdict.confidence == 0 and not verdict.degraded

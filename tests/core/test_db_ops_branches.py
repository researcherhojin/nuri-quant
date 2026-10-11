"""core/db 쓰기 함수의 입력 거부 분기 — 없는 기준 id · 범위 밖 alpha 지출.

거부는 **쓰기 전에** 일어나야 한다 — 원장에 반쪽 행이 남지 않는다.
"""

from __future__ import annotations

import pytest

from nuri.core.db import ThesisValidationError, init_db, log_challenger_attempt, query, record_human_check


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "ops.db"
    init_db(path)
    return path


def test_a_human_check_for_an_unknown_criterion_is_refused(db_path):
    with pytest.raises(ThesisValidationError, match="기준 999 이 없다"):
        record_human_check(999, "holding", db_path=db_path)

    assert query("SELECT COUNT(*) AS n FROM thesis_criteria_checks", db_path=db_path)[0]["n"] == 0


@pytest.mark.parametrize("alpha", [0.0, -0.01, 1.01])
def test_an_alpha_spend_outside_zero_to_one_is_refused(db_path, alpha):
    """alpha-spending 원장은 (0, 1] 만 받는다 — 0 은 '공짜 시도', 1 초과는 예산 위반이다."""
    with pytest.raises(ValueError, match="alpha_spent"):
        log_challenger_attempt("variant", 1, "v2", "rejected", alpha, db_path=db_path)

    assert query("SELECT COUNT(*) AS n FROM challenger_attempts", db_path=db_path)[0]["n"] == 0


def test_a_pending_decision_does_not_supersede_the_days_emitted_one(db_path):
    """같은 날 같은 종목의 emitted 결정은 새 emitted/blocked 만 대체한다 — pending 은 대기일 뿐이다."""
    from nuri.core.db import log_decision

    audit = {"regime_run_id": "r", "hypothesis_id": "h", "causal_audit_id": "c"}
    log_decision("d-emit", "TST_A", "2026-10-07", "BUY", 0.8, audit, {}, "emitted", db_path=db_path)
    log_decision("d-pend", "TST_A", "2026-10-07", "BUY", 0.6, audit, {}, "pending", db_path=db_path)

    rows = query("SELECT decision_id, status FROM agent_decisions ORDER BY decision_id", db_path=db_path)
    assert [(r["decision_id"], r["status"]) for r in rows] == [("d-emit", "emitted"), ("d-pend", "pending")]

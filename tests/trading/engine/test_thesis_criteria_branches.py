"""thesis_criteria 의 나머지 분기 — writer 거부 2종 · 파생 metric 판정 · 깨진 날짜.

파생 metric(`prices+signals`)과 깨진 날짜는 **나이를 못 재는** 경로다. 그때 낡음을 어떻게
판정해야 하는지는 열린 문제라(파생 metric 은 `STALE_AFTER_DAYS` 에 키가 없다), 여기서는
낡음 의미를 박지 않는다 — 신선한 데이터로 판정이 된다는 것과, 깨진 날짜가 점검을 죽이지
않는다는 것만 잠근다.
"""

from __future__ import annotations

import pytest

from nuri.core.db import get_db, init_db
from nuri.trading.engine import thesis_criteria as tc

AS_OF = "2026-10-07"


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


class TestWriterRejects:
    def test_an_unknown_kind_is_rejected(self):
        with pytest.raises(tc.CriterionValidationError, match="machine\\|human"):
            tc.validate_criterion("auto", "close", "<", 1.0)

    def test_a_machine_criterion_without_a_threshold_is_rejected(self):
        with pytest.raises(tc.CriterionValidationError, match="threshold"):
            tc.validate_criterion("machine", "close", "<", None)


class TestEvaluationWhenTheAgeIsNotRead:
    def test_the_derived_200d_metric_is_judged_on_fresh_legs(self, db_path):
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES ('ZZZZ', ?, 95, 95, 95, 95, 1)",
                (AS_OF,),
            )
            conn.execute("INSERT INTO signals (ticker, date, sma_200) VALUES ('ZZZZ', ?, 100)", (AS_OF,))
        criterion = {"kind": "machine", "metric": "close_over_sma200_pct", "op": "<", "threshold": 0}

        result = tc.evaluate_criterion(criterion, "ZZZZ", as_of=AS_OF, db_path=db_path)

        assert result["result"] == "breached"
        assert result["observed"] == pytest.approx(-5.0)

    def test_an_unparseable_source_date_does_not_kill_the_check(self, db_path):
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO fundamentals (ticker, date, pe_ratio) VALUES ('ZZZZ', 'FY2026-Q3', 18.0)")
        criterion = {"kind": "machine", "metric": "pe_ratio", "op": ">", "threshold": 40}

        result = tc.evaluate_criterion(criterion, "ZZZZ", as_of=AS_OF, db_path=db_path)

        assert result["observed"] == 18.0
        assert result["result"] in {"holding", "breached", "unevaluable"}

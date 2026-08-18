"""논지 verdict 롤업 — 기준 판정 이력에서 굴려 올린 사후 채점 (#1096).

이 파일이 잠그는 축은 하나다:

> **`held` 는 얻기 어려워야 한다.** 측정하지 못한 것, 중간에 갈아탄 것, 부분만 측정된 것이
> "지켜졌다" 로 흘러가면 채점이 자기 편이 되고 원장은 다시 서사가 된다.

`unevaluable` 을 `holding` 으로 적지 않는 규율(#1092)의 논지 층 대응물이다. 아래
`TestHeldIsHardToGet` 이 그 축이고, 나머지는 우선순위(반증 > 철회 > 마감)와 append-only.
"""

from __future__ import annotations

import pandas as pd
import pytest

from nuri.core.db import (
    ThesisValidationError,
    add_criteria,
    get_db,
    init_db,
    query,
    record_human_check,
    upsert_prices,
    upsert_thesis,
)
from nuri.trading.engine import thesis_criteria as tc

#: 전부 과거로 앵커된 날짜다 — 마감 경과 여부가 이 파일의 판정 축이라 `today_kst()`
#: 앵커링이 오히려 의미를 흐린다. 대신 `as_of` 를 명시로 넘겨 wall-clock 을 배제한다.
DEADLINE = "2026-06-01"
BEFORE = "2026-05-30"
AFTER = "2026-06-02"

MACHINE = {
    "kind": "machine",
    "statement": "종가가 100 아래로 무너지면 논지는 틀렸다",
    "metric": "close",
    "op": "<",
    "threshold": 100.0,
    "deadline_date": DEADLINE,
}
HUMAN = {"kind": "human", "statement": "경영진이 교체되면 논지는 틀렸다", "deadline_date": DEADLINE}


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _thesis(db_path, ticker, criteria, status="active"):
    tid = upsert_thesis(
        ticker=ticker,
        author="user",
        stance="bullish",
        bull_case="수요가 공급을 앞선다",
        bear_case="고객사 자체 칩 전환이 점유율을 깎는다",
        evidence=[{"side": "bull", "claim": "매출 증가", "source_type": "filing"}],
        effective_date="2026-05-01",
        status=status,
        db_path=db_path,
    )
    add_criteria(tid, criteria, db_path=db_path)
    return tid


def _seed_close(db_path, ticker, close):
    upsert_prices(
        pd.DataFrame(
            [
                {
                    "ticker": ticker,
                    "date": BEFORE,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1000,
                    "adj_close": close,
                }
            ]
        ),
        db_path=db_path,
    )


def _verdict(db_path, ticker):
    return query("SELECT verdict FROM theses WHERE ticker = ?", (ticker,), db_path=db_path)[0]["verdict"]


class TestHeldIsHardToGet:
    """`held` 로 새는 경로를 전부 막는다 — 이 클래스가 이 파일의 이유다."""

    def test_all_criteria_measured_and_clean_is_held(self, db_path):
        _thesis(db_path, "AAAA", [dict(MACHINE)])
        _seed_close(db_path, "AAAA", 120.0)
        tc.run_daily_checks(as_of=BEFORE, db_path=db_path)

        tc.roll_up_verdicts(as_of=AFTER, db_path=db_path)

        assert _verdict(db_path, "AAAA") == "held"

    def test_partially_measured_is_unevaluable_not_held(self, db_path):
        """machine 은 유지, human 은 아무도 판정 안 함 → `held` 가 아니라 `unevaluable`.

        이걸 `held` 로 적으면 "사람 기준은 늘 지켜지고 있다" 는 거짓말이 채점에 들어간다.
        """
        _thesis(db_path, "BBBB", [dict(MACHINE), dict(HUMAN)])
        _seed_close(db_path, "BBBB", 120.0)
        tc.run_daily_checks(as_of=BEFORE, db_path=db_path)

        tc.roll_up_verdicts(as_of=AFTER, db_path=db_path)

        assert _verdict(db_path, "BBBB") == "unevaluable"

    def test_nothing_measurable_is_unevaluable(self, db_path):
        """가격이 없어 machine 기준도 `unevaluable` → 논지도 `unevaluable`."""
        _thesis(db_path, "CCCC", [dict(MACHINE)])
        tc.run_daily_checks(as_of=BEFORE, db_path=db_path)

        tc.roll_up_verdicts(as_of=AFTER, db_path=db_path)

        assert _verdict(db_path, "CCCC") == "unevaluable"

    def test_human_judgement_unblocks_held(self, db_path):
        """사람이 판정을 남기면 그때 비로소 `held` — 없으면 도달 불가능한 판정이 된다."""
        _thesis(db_path, "DDDD", [dict(MACHINE), dict(HUMAN)])
        _seed_close(db_path, "DDDD", 120.0)
        tc.run_daily_checks(as_of=BEFORE, db_path=db_path)
        human_id = query(
            "SELECT c.id FROM thesis_criteria c JOIN theses t ON t.id = c.thesis_id "
            "WHERE t.ticker = 'DDDD' AND c.kind = 'human'",
            db_path=db_path,
        )[0]["id"]

        record_human_check(human_id, "holding", check_date=BEFORE, db_path=db_path)
        tc.roll_up_verdicts(as_of=AFTER, db_path=db_path)

        assert _verdict(db_path, "DDDD") == "held"


class TestVerdictPriority:
    def test_breach_wins_and_does_not_wait_for_deadline(self, db_path):
        """반증은 마감을 기다리지 않는다 — 틀린 건 그날 틀린 것이다."""
        _thesis(db_path, "EEEE", [dict(MACHINE)])
        _seed_close(db_path, "EEEE", 50.0)
        tc.run_daily_checks(as_of=BEFORE, db_path=db_path)

        tc.roll_up_verdicts(as_of=BEFORE, db_path=db_path)

        assert _verdict(db_path, "EEEE") == "broken"

    def test_superseded_thesis_is_abandoned_not_held(self, db_path):
        """v2 를 쓰면 v1 은 `abandoned` — 갈아탄 논지를 "지켜졌다" 로 결산하면 갈아타기가 공짜다."""
        _thesis(db_path, "FFFF", [dict(MACHINE)])
        _seed_close(db_path, "FFFF", 120.0)
        tc.run_daily_checks(as_of=BEFORE, db_path=db_path)
        _thesis(db_path, "FFFF", [dict(MACHINE)])  # v2 → v1 이 superseded

        tc.roll_up_verdicts(as_of=AFTER, db_path=db_path)

        v1 = query("SELECT verdict FROM theses WHERE ticker = 'FFFF' ORDER BY version", db_path=db_path)[0]
        assert v1["verdict"] == "abandoned"

    def test_breach_outranks_abandonment(self, db_path):
        """반증된 뒤 갈아탄 논지는 `broken` 으로 남는다 — 반증 사실이 지워지면 안 된다."""
        _thesis(db_path, "GGGG", [dict(MACHINE)])
        _seed_close(db_path, "GGGG", 50.0)
        tc.run_daily_checks(as_of=BEFORE, db_path=db_path)
        _thesis(db_path, "GGGG", [dict(MACHINE)])

        tc.roll_up_verdicts(as_of=AFTER, db_path=db_path)

        v1 = query("SELECT verdict FROM theses WHERE ticker = 'GGGG' ORDER BY version", db_path=db_path)[0]
        assert v1["verdict"] == "broken"


class TestInProgressStaysBlank:
    def test_before_deadline_writes_no_verdict(self, db_path):
        _thesis(db_path, "HHHH", [dict(MACHINE, deadline_date="2027-01-01")])
        _seed_close(db_path, "HHHH", 120.0)
        tc.run_daily_checks(as_of=BEFORE, db_path=db_path)

        counts = tc.roll_up_verdicts(as_of=AFTER, db_path=db_path)

        assert _verdict(db_path, "HHHH") is None
        assert sum(counts.values()) == 0

    def test_criterion_without_deadline_never_terminates(self, db_path):
        """마감 없는 기준은 영원히 진행 중 — 끝나지 않는 관찰을 결산할 수는 없다."""
        _thesis(db_path, "IIII", [dict(MACHINE, deadline_date=None)])
        _seed_close(db_path, "IIII", 120.0)
        tc.run_daily_checks(as_of=BEFORE, db_path=db_path)

        tc.roll_up_verdicts(as_of="2030-01-01", db_path=db_path)

        assert _verdict(db_path, "IIII") is None

    def test_zero_criteria_is_not_a_vacuous_pass(self):
        """`all([])` 은 True 다 — 기준 0건이 만점으로 읽히는 공허참을 직접 잠근다.

        쿼리가 INNER JOIN 이라 지금은 도달하지 않는 경로지만, 방어가 **우연**이면
        다음 리팩터가 걷어간다. 그래서 판정 함수 자체를 직접 부른다.
        """
        assert tc._verdict_for("active", [], {}, AFTER) is None

    def test_thesis_without_criteria_is_never_scored(self, db_path):
        """#1092 이전 유물 — 반증 기준 없는 논지를 `held` 로 적으면 서사가 채점을 통과한다."""
        upsert_thesis(
            ticker="JJJJ",
            author="user",
            stance="bullish",
            bull_case="좋다",
            bear_case="나쁠 수도 있다",
            evidence=[{"side": "bull", "claim": "c", "source_type": "filing"}],
            effective_date="2026-05-01",
            status="active",
            db_path=db_path,
        )

        counts = tc.roll_up_verdicts(as_of=AFTER, db_path=db_path)

        assert _verdict(db_path, "JJJJ") is None
        assert sum(counts.values()) == 0


class TestHumanCheckIsNotAnEditButton:
    def test_machine_criterion_cannot_be_hand_judged(self, db_path):
        """기계 판정을 손으로 덮을 수 있으면 원장이 취향대로 다듬어진다."""
        _thesis(db_path, "KKKK", [dict(MACHINE)])
        machine_id = query(
            "SELECT c.id FROM thesis_criteria c JOIN theses t ON t.id = c.thesis_id WHERE t.ticker = 'KKKK'",
            db_path=db_path,
        )[0]["id"]

        with pytest.raises(ThesisValidationError, match="machine"):
            record_human_check(machine_id, "holding", db_path=db_path)

    def test_same_day_rejudgement_does_not_overwrite(self, db_path):
        """판정 이력은 append-only — 하루에 두 번 부르면 두 번째는 무시된다."""
        _thesis(db_path, "LLLL", [dict(MACHINE), dict(HUMAN)])
        human_id = query(
            "SELECT c.id FROM thesis_criteria c JOIN theses t ON t.id = c.thesis_id "
            "WHERE t.ticker = 'LLLL' AND c.kind = 'human'",
            db_path=db_path,
        )[0]["id"]

        assert record_human_check(human_id, "breached", check_date=BEFORE, db_path=db_path) is True
        assert record_human_check(human_id, "holding", check_date=BEFORE, db_path=db_path) is False

        rows = query("SELECT result FROM thesis_criteria_checks WHERE criterion_id = ?", (human_id,), db_path=db_path)
        assert [r["result"] for r in rows] == ["breached"]

    def test_daily_placeholder_is_upgraded_not_appended(self, db_path):
        """일별 점검이 적은 `unevaluable(manual)` 은 자리표시자다 — 사람 판정이 그걸 대체한다.

        이걸 append-only 로 지키면 사람은 그날도, 다음날도 판정을 못 남긴다. 일별 점검이
        매일 먼저 적기 때문이다 — 규율이 아니라 잠금이 된다.
        """
        _thesis(db_path, "PPPP", [dict(MACHINE), dict(HUMAN)])
        tc.run_daily_checks(as_of=BEFORE, db_path=db_path)
        human_id = query(
            "SELECT c.id FROM thesis_criteria c JOIN theses t ON t.id = c.thesis_id "
            "WHERE t.ticker = 'PPPP' AND c.kind = 'human'",
            db_path=db_path,
        )[0]["id"]

        assert record_human_check(human_id, "breached", "감사보고서", check_date=BEFORE, db_path=db_path) is True
        # 사람 판정이 앉은 뒤에는 같은 날 재판정이 거부된다 — 자리표시자와 판정의 차이.
        assert record_human_check(human_id, "holding", check_date=BEFORE, db_path=db_path) is False

        rows = query(
            "SELECT result, detail FROM thesis_criteria_checks WHERE criterion_id = ?",
            (human_id,),
            db_path=db_path,
        )
        assert len(rows) == 1, "자리표시자 위에 행이 하나 더 쌓였다"
        assert rows[0]["result"] == "breached"
        assert rows[0]["detail"] == "감사보고서"

    def test_unevaluable_is_not_a_recordable_human_verdict(self, db_path):
        """`unevaluable` 은 기본 상태다 — 손으로 적을 수 있게 하면 판정 회피가 기록이 된다."""
        _thesis(db_path, "MMMM", [dict(MACHINE), dict(HUMAN)])
        human_id = query(
            "SELECT c.id FROM thesis_criteria c JOIN theses t ON t.id = c.thesis_id "
            "WHERE t.ticker = 'MMMM' AND c.kind = 'human'",
            db_path=db_path,
        )[0]["id"]

        with pytest.raises(ThesisValidationError, match="holding"):
            record_human_check(human_id, "unevaluable", db_path=db_path)


class TestRollupIsTheOnlyVerdictWriter:
    def test_counts_reflect_every_scored_thesis_not_only_changes(self, db_path):
        """두 번 돌려도 건수가 줄지 않는다 — 이 값은 '오늘 바뀐 수' 가 아니라 현재 상태다."""
        _thesis(db_path, "NNNN", [dict(MACHINE)])
        _seed_close(db_path, "NNNN", 120.0)
        tc.run_daily_checks(as_of=BEFORE, db_path=db_path)

        first = tc.roll_up_verdicts(as_of=AFTER, db_path=db_path)
        second = tc.roll_up_verdicts(as_of=AFTER, db_path=db_path)

        assert first == second == {"broken": 0, "held": 1, "abandoned": 0, "unevaluable": 0}

    def test_late_breach_flips_held_back_to_broken(self, db_path):
        """마감 뒤 반증이 들어와도 반증이 이긴다 — `held` 가 최종 방패가 되면 안 된다."""
        _thesis(db_path, "OOOO", [dict(MACHINE)])
        _seed_close(db_path, "OOOO", 120.0)
        tc.run_daily_checks(as_of=BEFORE, db_path=db_path)
        tc.roll_up_verdicts(as_of=AFTER, db_path=db_path)
        assert _verdict(db_path, "OOOO") == "held"

        criterion_id = query(
            "SELECT c.id FROM thesis_criteria c JOIN theses t ON t.id = c.thesis_id WHERE t.ticker = 'OOOO'",
            db_path=db_path,
        )[0]["id"]
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO thesis_criteria_checks (criterion_id, check_date, result) VALUES (?, ?, 'breached')",
                (criterion_id, AFTER),
            )

        tc.roll_up_verdicts(as_of=AFTER, db_path=db_path)

        assert _verdict(db_path, "OOOO") == "broken"

    def test_verdict_values_match_the_schema_check(self, db_path):
        """`VERDICTS` 가 문서용 상수로 굳지 않게 — 스키마 CHECK 와 실제로 대조한다."""
        ddl = query("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'theses'", db_path=db_path)[0]["sql"]

        for verdict in tc.VERDICTS:
            assert f"'{verdict}'" in ddl


class TestSchedulerRunsTheRollup:
    """등록 확인이 아니라 **분기를 실행**해서 verdict 가 실제로 앉는지 본다.

    `run_daily_checks` 만 부르고 롤업을 빠뜨려도 잡은 성공하고 카운트도 그럴듯하다 —
    `theses.verdict` 만 영원히 NULL 이다. 그게 이 레포가 반복해 온 "도는 줄 아는데 안 도는"
    모양이라, 구조가 아니라 산출물로 잠근다. 전역 DB 격리(`tests/conftest.py`)를 쓰므로
    dispatch 가 `db_path` 없이 불려도 프로덕션에 닿지 않는다.
    """

    def test_dispatch_writes_a_verdict(self):
        import nuri.scheduler as sch
        from nuri.core.timezone import today_kst

        today = today_kst()
        tid = upsert_thesis(
            ticker="QQQQ",
            author="user",
            stance="bullish",
            bull_case="수요가 공급을 앞선다",
            bear_case="점유율이 깎인다",
            evidence=[{"side": "bull", "claim": "매출 증가", "source_type": "filing"}],
            effective_date=today,
            status="active",
        )
        add_criteria(tid, [dict(MACHINE, deadline_date="2026-01-01")])
        upsert_prices(
            pd.DataFrame(
                [
                    {
                        "ticker": "QQQQ",
                        "date": today,
                        "open": 120.0,
                        "high": 120.0,
                        "low": 120.0,
                        "close": 120.0,
                        "volume": 1000,
                        "adj_close": 120.0,
                    }
                ]
            )
        )

        sch._dispatch_collector("thesis_criteria")

        assert query("SELECT verdict FROM theses WHERE id = ?", (tid,))[0]["verdict"] == "held"

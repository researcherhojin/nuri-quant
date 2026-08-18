"""사전등록 반증 기준의 일별 점검 (#1092).

이 파일이 잠그는 것은 계산이 아니라 **한 줄의 규율**이다:

> 해소되지 않는 metric 은 `unevaluable` 이다. 절대 `holding` 이 아니다.

`_check_volatility_for_class` 가 넉 달간 초록이던 이유가 정확히 이것 — 측정하지 못한 것을
"이상 없음" 으로 적으면 게이트가 **있는데 안 잡는** 상태가 되고, 그건 게이트가 없는 것보다
나쁘다(있다고 믿게 되므로). 아래 `TestUnevaluableNeverLeaksAsHolding` 이 그 축이다.

나머지 둘:
- **양방향 계약** — 미등록 metric 은 writer 가 거부하고, 등록된 metric 은 전부 실제로 해소된다.
  한쪽만 있으면 목록과 구현이 조용히 갈린다.
- **Surface 천장** — breach 는 알림·뱃지까지고 주문/축을 만들지 않는다 (§7.1).
"""

from __future__ import annotations

import pandas as pd
import pytest

from nuri.core.db import (
    ThesisValidationError,
    add_criteria,
    get_active_thesis,
    init_db,
    query,
    upsert_prices,
    upsert_thesis,
)
from nuri.core.timezone import today_kst
from nuri.trading.engine import thesis_criteria as tc


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def thesis(db_path):
    return upsert_thesis(
        ticker="ZZZZ",
        author="user",
        stance="bullish",
        bull_case="가속기 수요가 공급을 앞선다",
        bear_case="고객사 자체 칩 전환이 점유율을 깎는다",
        evidence=[{"side": "bull", "claim": "매출 증가", "source_type": "filing"}],
        effective_date="2026-05-01",
        status="active",
        db_path=db_path,
    )


def _seed_close(db_path, close: float, date: str | None = None):
    d = date or today_kst()
    upsert_prices(
        pd.DataFrame(
            [
                {
                    "ticker": "ZZZZ",
                    "date": d,
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


def _machine(metric="close", op="<", threshold=90.0, statement="50일선 이탈 시 전제 붕괴"):
    return {"kind": "machine", "statement": statement, "metric": metric, "op": op, "threshold": threshold}


class TestUnevaluableNeverLeaksAsHolding:
    """이 클래스가 이 기능의 존재 이유다."""

    def test_missing_data_is_unevaluable_not_holding(self, db_path, thesis):
        """가격이 없으면 '이상 없음' 이 아니라 '측정 불가' 다.

        Mutation lock: `no_data` 분기를 `holding` 으로 바꾸면 FAIL. 그 한 글자가
        "기준이 매일 지켜지고 있다" 는 거짓말을 원장에 매일 쌓는다.
        """
        add_criteria(thesis, [_machine()], db_path=db_path)
        counts = tc.run_daily_checks(today_kst(), db_path=db_path)
        assert counts == {"holding": 0, "breached": 0, "unevaluable": 1}
        row = query("SELECT result, detail FROM thesis_criteria_checks", db_path=db_path)[0]
        assert row["result"] == "unevaluable"
        assert row["detail"].startswith("no_data:")

    def test_stale_data_is_unevaluable_not_holding(self, db_path, thesis):
        """값이 있어도 너무 낡으면 측정 불가다 — 낡은 값으로 '지켜졌다' 고 적으면 안 된다."""
        from datetime import date, timedelta

        old = (date.fromisoformat(today_kst()) - timedelta(days=30)).isoformat()
        _seed_close(db_path, 80.0, date=old)
        add_criteria(thesis, [_machine()], db_path=db_path)

        tc.run_daily_checks(today_kst(), db_path=db_path)
        row = query("SELECT result, detail FROM thesis_criteria_checks", db_path=db_path)[0]
        assert row["result"] == "unevaluable", "낡은 값으로 판정했다"
        assert row["detail"].startswith("stale:")

    def test_human_criteria_are_unevaluable_not_holding(self, db_path, thesis):
        """사람 기준을 기계가 '지켜졌다' 고 적으면 매일 거짓말이 쌓인다."""
        add_criteria(
            db_path=db_path,
            thesis_id=thesis,
            criteria=[_machine(), {"kind": "human", "statement": "경영진이 capex 가이던스를 하향하면"}],
        )
        _seed_close(db_path, 200.0)
        counts = tc.run_daily_checks(today_kst(), db_path=db_path)
        assert counts["unevaluable"] == 1 and counts["holding"] == 1
        detail = query("SELECT detail FROM thesis_criteria_checks WHERE result = 'unevaluable'", db_path=db_path)[0][
            "detail"
        ]
        assert "manual" in detail

    def test_unregistered_metric_on_an_existing_row_is_unevaluable(self, db_path, thesis):
        """writer 를 우회해 들어온 행(마이그레이션 이전 데이터 등)도 통과로 새지 않는다."""
        from nuri.core.db import get_db

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO thesis_criteria (thesis_id, kind, statement, metric, op, threshold)"
                " VALUES (?, 'machine', 's', 'not_a_metric', '<', 1.0)",
                (thesis,),
            )
        tc.run_daily_checks(today_kst(), db_path=db_path)
        row = query("SELECT result, detail FROM thesis_criteria_checks", db_path=db_path)[0]
        assert row["result"] == "unevaluable"
        assert row["detail"] == "no_metric:not_a_metric"


class TestVerdict:
    def test_breach_and_holding_both_resolve(self, db_path, thesis):
        _seed_close(db_path, 80.0)
        add_criteria(
            thesis,
            [_machine(op="<", threshold=90.0), _machine(op=">", threshold=200.0, statement="관심 소멸")],
            db_path=db_path,
        )
        counts = tc.run_daily_checks(today_kst(), db_path=db_path)
        assert counts == {"holding": 1, "breached": 1, "unevaluable": 0}

        rows = {r["result"]: r for r in query("SELECT result, observed FROM thesis_criteria_checks", db_path=db_path)}
        assert rows["breached"]["observed"] == 80.0
        assert rows["holding"]["observed"] == 80.0

    def test_rerunning_the_same_day_does_not_overwrite_the_verdict(self, db_path, thesis):
        """하루 1건이되, **먼저 기록된 판정이 이긴다**.

        행 수만 세면 `INSERT OR REPLACE` 로 바꿔도 통과한다(UNIQUE 가 여전히 1행을 지키므로)
        — 실측으로 그 뮤테이션이 살아남았다. 진짜 계약은 **그날의 판정이 나중 실행에
        덮이지 않는 것**이다: 덮이면 그날 무엇으로 판정했는지 사후에 알 수 없고, 채점의
        근거가 사라진다.
        """
        _seed_close(db_path, 80.0)  # close < 90 → breached
        add_criteria(thesis, [_machine()], db_path=db_path)
        d = today_kst()
        tc.run_daily_checks(d, db_path=db_path)

        _seed_close(db_path, 200.0)  # 같은 날 값이 뒤집혀도
        tc.run_daily_checks(d, db_path=db_path)

        rows = query("SELECT result, observed FROM thesis_criteria_checks", db_path=db_path)
        assert len(rows) == 1, "하루 1건이 아니다"
        assert rows[0]["result"] == "breached", "나중 실행이 그날 판정을 덮었다"
        assert rows[0]["observed"] == 80.0

    def test_only_active_theses_are_checked(self, db_path):
        """draft/superseded 논지의 기준까지 매일 판정하면 원장이 죽은 기준으로 부푼다."""
        draft = upsert_thesis(
            ticker="WWWW",
            author="llm",
            stance="bullish",
            bull_case="B",
            bear_case="R",
            evidence=[{"side": "bull", "claim": "c", "source_type": "filing"}],
            db_path=db_path,
        )
        add_criteria(draft, [_machine()], db_path=db_path)
        assert tc.run_daily_checks(today_kst(), db_path=db_path) == {
            "holding": 0,
            "breached": 0,
            "unevaluable": 0,
        }


class TestWriterContract:
    """양방향 — 미등록은 거부되고, 등록된 것은 전부 해소된다."""

    def test_every_registered_metric_actually_resolves(self, db_path):
        """목록에 있는데 해소가 안 되면 그 기준은 영원히 unevaluable 이다.

        `no_data` 는 티커에 값이 없다는 뜻이라 정상 — 여기서 잡는 것은 **예외로 죽거나
        no_metric 을 내는 것**, 즉 목록과 구현이 갈린 경우다.
        """
        for metric in tc.METRIC_RESOLVERS:
            value, date, table = tc.METRIC_RESOLVERS[metric]("ZZZZ", db_path)
            assert value is None and date is None, f"{metric}: 빈 DB 인데 값이 나왔다"
            assert isinstance(table, str) and table

    def test_unregistered_metric_is_rejected_at_write_time(self, db_path, thesis):
        with pytest.raises(ThesisValidationError, match="해소기 없는 metric"):
            add_criteria(thesis, [_machine(metric="made_up_metric")], db_path=db_path)

    def test_all_human_criteria_are_rejected(self, db_path, thesis):
        """machine 이 하나도 없으면 자동 점검이 장식이다."""
        with pytest.raises(ThesisValidationError, match="machine 기준이 최소 1개"):
            add_criteria(thesis, [{"kind": "human", "statement": "감으로"}], db_path=db_path)

    def test_zero_criteria_is_rejected(self, db_path, thesis):
        with pytest.raises(ThesisValidationError, match="0건"):
            add_criteria(thesis, [], db_path=db_path)

    def test_blank_statement_is_rejected(self, db_path, thesis):
        """metric 만 있고 문장이 없으면 나중에 무엇을 반증하려 했는지 알 수 없다."""
        with pytest.raises(ThesisValidationError, match="statement"):
            add_criteria(thesis, [_machine(statement="   ")], db_path=db_path)

    def test_bad_operator_is_rejected(self, db_path, thesis):
        with pytest.raises(ThesisValidationError, match="op"):
            add_criteria(thesis, [_machine(op="!=")], db_path=db_path)

    def test_a_rejected_batch_writes_nothing(self, db_path, thesis):
        """검증이 INSERT 앞이어야 한다 — 뒤면 반쪽 기준 집합이 남는다."""
        with pytest.raises(ThesisValidationError):
            add_criteria(thesis, [_machine(), _machine(metric="nope")], db_path=db_path)
        assert query("SELECT COUNT(*) c FROM thesis_criteria", db_path=db_path)[0]["c"] == 0


class TestSurfaceCeiling:
    def test_checks_never_write_an_action_axis(self, db_path, thesis):
        """반증 발화는 Surface 전용 — 주문도 축도 만들지 않는다 (§7.1 · Escalation Ladder).

        Mutation lock: breach 를 recommendations/agent_decisions 로 흘리면 FAIL.
        """
        _seed_close(db_path, 80.0)
        add_criteria(thesis, [_machine()], db_path=db_path)
        tc.run_daily_checks(today_kst(), db_path=db_path)

        for table in ("recommendations", "agent_decisions", "decisions"):
            assert query(f"SELECT COUNT(*) c FROM {table}", db_path=db_path)[0]["c"] == 0, (
                f"{table} 에 행이 생겼다 — 반증 점검이 매매 축을 건드렸다"
            )


class TestReadPath:
    def test_criteria_reach_the_decision_read_path(self, db_path, thesis):
        """배선만 하고 화면에 안 닿으면 `data/thesis_query/` markdown 39개와 같은 운명이다."""
        _seed_close(db_path, 80.0)
        add_criteria(thesis, [_machine()], db_path=db_path)
        tc.run_daily_checks(today_kst(), db_path=db_path)

        got = get_active_thesis("ZZZZ", as_of=today_kst(), db_path=db_path)
        assert got is not None
        assert len(got["criteria"]) == 1
        assert got["criteria"][0]["last_result"] == "breached"
        assert got["criteria"][0]["last_checked"] == today_kst()

    def test_scheduler_dispatch_reaches_the_checker(self):
        """`_STAGE_OF_JOB` 에 track 으로 올려 두고 dispatcher 분기가 없으면 조용히 안 돈다."""
        import nuri.scheduler as sch

        assert sch._STAGE_OF_JOB["thesis_criteria"] == "track"
        scheduled = {j["args"][0] for j in sch.SCHEDULES if j.get("func") is sch._run_collector and j.get("args")}
        assert "thesis_criteria" in scheduled

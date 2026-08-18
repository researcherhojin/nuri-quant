"""미실행 거래 원장 — candidate_runs / candidate_ledger (#1094).

이 파일이 잠그는 것은 **기록되지 않는 날이 없다**는 것이다.

`save_buy_candidates`(#1078)는 발행된 후보만 남긴다. 그래서 차단된 날 — 2026-08-18 이
정확히 그랬다, `regime=recovery` 로 후보 0건 — 은 원장에서 "아무 일도 없던 날" 로 보인다.
실제로는 시스템이 돌았고 18종목을 건너뛴다는 판단을 내렸는데도.

없으면 사후 채점이 **실행한 것만** 보게 되고 그 성적표는 실제 실력보다 좋다(생존 편향).
"""

from __future__ import annotations

import pytest

from nuri.core.db import (
    get_candidate_run,
    init_db,
    mark_acted,
    query,
    record_candidate_run,
)
from nuri.core.timezone import today_kst
from nuri.trading.recommend.buy_candidate_emitter import BuyCandidate, EmitResult


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _candidate(ticker="ZZZZ", score=88.0):
    return BuyCandidate(
        ticker=ticker,
        score=score,
        deploy_pct=6.0,
        entry=100.0,
        stop=93.0,
        tp1=121.0,
        tp2=142.0,
        why_now="breakout",
        sources={"factor": 0.9},
    )


def _emitted(**over):
    r = EmitResult(candidates=[_candidate()], regime="bull_low_vol", vix=16.2, **over)
    r.n_scored, r.n_qualified, r.threshold = 200, 3, 70.0
    return r


class TestBlockedDaysAreRecorded:
    """이 클래스가 이 기능의 존재 이유다."""

    def test_a_regime_blocked_run_still_leaves_a_row(self, db_path):
        """후보 0건이어도 run 이 남는다 — 차단된 날이 가장 정보량 많은 미실행 기록이다.

        Mutation lock: 0건일 때 조기 return 하면 FAIL. 2026-08-18 프로덕션이 이 케이스였다.
        """
        blocked = EmitResult(
            regime="recovery",
            vix=None,
            skipped={f"T{i:02d}": "held (보유 중)" for i in range(18)},
            blocked_reason="regime=recovery (방어 모드, 신규 매수 차단)",
        )
        record_candidate_run(blocked, "2026-08-18", db_path=db_path)

        run = get_candidate_run("2026-08-18", db_path=db_path)
        assert run is not None, "차단된 날이 원장에서 사라졌다"
        assert run["n_emitted"] == 0 and run["n_skipped"] == 18
        assert run["blocked_reason"].startswith("regime=recovery")
        assert len(run["ledger"]) == 18
        assert {r["disposition"] for r in run["ledger"]} == {"skipped"}

    def test_the_reason_is_kept_per_ticker(self, db_path):
        """티커별 사유를 뭉뚱그리면 '왜 안 샀나' 의 결이 사라진다."""
        blocked = EmitResult(
            regime="bull_low_vol",
            skipped={"AAA": "held (보유 중)", "BBB": "cooldown 5d", "CCC": "leverage ETF"},
        )
        record_candidate_run(blocked, "2026-08-18", db_path=db_path)
        reasons = {r["ticker"]: r["reason"] for r in get_candidate_run("2026-08-18", db_path=db_path)["ledger"]}
        assert reasons == {"AAA": "held (보유 중)", "BBB": "cooldown 5d", "CCC": "leverage ETF"}

    def test_an_empty_run_with_no_skips_still_records(self, db_path):
        """VIX 차단은 채점 전에 끊기므로 skipped 도 비어 있다 — 그래도 run 은 남아야 한다."""
        record_candidate_run(
            EmitResult(regime="bull_high_vol", vix=33.0, blocked_reason="VIX 33.0 > 30 (신규 매수 차단)"),
            "2026-08-18",
            db_path=db_path,
        )
        run = get_candidate_run("2026-08-18", db_path=db_path)
        assert run is not None and run["ledger"] == []
        assert run["vix"] == 33.0


class TestDenominator:
    def test_scored_and_qualified_distinguish_two_kinds_of_zero(self, db_path):
        """'채점 대상이 0' 과 '200개 채점했는데 아무도 임계를 못 넘음' 은 다른 상태다."""
        r = EmitResult(regime="bull_low_vol", blocked_reason="top scorer 61/100 < threshold 70")
        r.n_scored, r.n_qualified, r.threshold = 200, 0, 70.0
        record_candidate_run(r, "2026-08-18", db_path=db_path)

        run = get_candidate_run("2026-08-18", db_path=db_path)
        assert (run["n_scored"], run["n_qualified"], run["n_emitted"]) == (200, 0, 0)
        assert run["threshold"] == 70.0

    def test_emitter_fills_the_denominator(self):
        """`EmitResult` 가 분모를 안 실으면 원장은 늘 0 을 적는다 — 배선 축."""
        r = EmitResult()
        assert hasattr(r, "n_scored") and hasattr(r, "n_qualified") and hasattr(r, "threshold")


class TestActedIsManual:
    def test_acted_defaults_to_zero(self, db_path):
        """체결을 알 방법이 없다 — `trades` 0행, `first_buy_date` 전부 동일 상수."""
        record_candidate_run(_emitted(), "2026-08-19", db_path=db_path)
        row = get_candidate_run("2026-08-19", db_path=db_path)["ledger"][0]
        assert row["acted"] == 0 and row["acted_at"] is None

    def test_a_person_can_mark_it(self, db_path):
        record_candidate_run(_emitted(), "2026-08-19", db_path=db_path)
        assert mark_acted("2026-08-19", "ZZZZ", db_path=db_path) is True
        row = get_candidate_run("2026-08-19", db_path=db_path)["ledger"][0]
        assert row["acted"] == 1 and row["acted_at"]

    def test_rerunning_the_day_does_not_erase_it(self, db_path):
        """재실행이 사람이 켠 값을 지우면 '실행 vs 미실행' 비교가 조용히 거짓이 된다.

        Mutation lock: UPSERT 에 `acted = excluded.acted` 를 넣으면 FAIL.
        """
        record_candidate_run(_emitted(), "2026-08-19", db_path=db_path)
        mark_acted("2026-08-19", "ZZZZ", db_path=db_path)
        record_candidate_run(_emitted(), "2026-08-19", db_path=db_path)

        row = get_candidate_run("2026-08-19", db_path=db_path)["ledger"][0]
        assert row["acted"] == 1, "재실행이 사람이 켠 체결 표시를 지웠다"

    def test_marking_an_unknown_ticker_reports_failure(self, db_path):
        record_candidate_run(_emitted(), "2026-08-19", db_path=db_path)
        assert mark_acted("2026-08-19", "NOPE", db_path=db_path) is False


class TestOneRowPerDay:
    def test_rerun_updates_rather_than_duplicates(self, db_path):
        """run 은 그날의 **최종 상태**다 — 두 번 돌면 두 번째가 그날의 결론이다."""
        record_candidate_run(EmitResult(regime="recovery", blocked_reason="차단"), "2026-08-19", db_path=db_path)
        record_candidate_run(_emitted(), "2026-08-19", db_path=db_path)

        assert query("SELECT COUNT(*) c FROM candidate_runs", db_path=db_path)[0]["c"] == 1
        run = get_candidate_run("2026-08-19", db_path=db_path)
        assert run["blocked_reason"] is None and run["n_emitted"] == 1

    def test_defaults_to_today(self, db_path):
        record_candidate_run(_emitted(), db_path=db_path)
        assert get_candidate_run(today_kst(), db_path=db_path) is not None


class TestSurfaceCeiling:
    def test_the_ledger_writes_no_trading_row(self, db_path):
        """기록이지 신호가 아니다 — 축도 주문도 만들지 않고 §3.11 표본도 안 건드린다.

        Mutation lock: `recommendations` 로 흘리면 FAIL.
        """
        record_candidate_run(_emitted(), "2026-08-19", db_path=db_path)
        for table in ("recommendations", "agent_decisions", "decisions"):
            assert query(f"SELECT COUNT(*) c FROM {table}", db_path=db_path)[0]["c"] == 0, table

    def test_missing_run_reads_as_none(self, db_path):
        assert get_candidate_run("2020-01-01", db_path=db_path) is None

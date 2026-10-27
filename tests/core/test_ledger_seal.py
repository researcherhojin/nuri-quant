"""판정 원장 봉인 (#1718) — Gotcha-Test Pair.

봉인은 "고쳐지지 않았다" 를 증명하는 장치라, 잠금은 전부 **변조를 실제로 가해** 잡히는지 본다.
제외 컬럼(사후 측정·라벨 백필)의 변경이 무결로 남는지도 같이 본다 — 그게 깨지면 정상 운영이
매일 변조로 보고된다.
"""

from __future__ import annotations

import pytest

from nuri.core.db import get_db, init_db, query
from nuri.core.db import ledger_seal as seal


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "seal.db"
    init_db(p)
    with get_db(p) as conn:
        for date, ticker, action in [
            ("2026-10-01", "AAA", "BUY"),
            ("2026-10-01", "BBB", "HOLD"),
            ("2026-10-02", "AAA", "SELL"),
            ("2026-10-05", "CCC", "BUY"),
            ("2026-10-07", "DDD", "BUY"),  # 오늘 — 봉인 대상 아님
        ]:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence) VALUES (?, ?, ?, 70.0)",
                (date, ticker, action),
            )
    return p


TODAY = "2026-10-07"


def _sealed(db_path):
    return seal.seal_closed_days(TODAY, db_path=db_path)


class TestSealing:
    def test_closed_days_are_sealed_and_today_is_not(self, db_path):
        assert _sealed(db_path) == ["2026-10-01", "2026-10-02", "2026-10-05"]
        assert seal.verify(db_path=db_path) == []

    def test_later_runs_extend_the_same_chain(self, db_path):
        _sealed(db_path)
        latest = seal.latest_seal(db_path=db_path)
        assert latest is not None
        first_head = latest["seal_hash"]
        assert seal.seal_closed_days("2026-10-08", db_path=db_path) == ["2026-10-07"]
        row = query("SELECT prev_hash FROM recommendation_seals WHERE date = '2026-10-07'", db_path=db_path)[0]
        assert row["prev_hash"] == first_head
        assert seal.verify(db_path=db_path) == []

    def test_rerun_on_the_same_day_seals_nothing_new(self, db_path):
        _sealed(db_path)
        assert _sealed(db_path) == []


class TestTamperIsDetected:
    def _problems(self, db_path, sql, params=()):
        _sealed(db_path)
        with get_db(db_path) as conn:
            conn.execute(sql, params)
        return seal.verify(db_path=db_path)

    def test_editing_a_sealed_field(self, db_path):
        problems = self._problems(db_path, "UPDATE recommendations SET action = 'BUY' WHERE ticker = 'BBB'")
        assert any(p.startswith("2026-10-01") for p in problems)

    def test_deleting_a_row(self, db_path):
        problems = self._problems(db_path, "DELETE FROM recommendations WHERE date = '2026-10-02'")
        assert any(p.startswith("2026-10-02") for p in problems)

    def test_inserting_into_a_sealed_day(self, db_path):
        problems = self._problems(
            db_path, "INSERT INTO recommendations (date, ticker, action) VALUES ('2026-10-05', 'ZZZ', 'BUY')"
        )
        assert any(p.startswith("2026-10-05") for p in problems)

    def test_backdating_into_an_unsealed_day_inside_the_sealed_range(self, db_path):
        """10-03 에는 행이 없어 봉인도 없다 — 거기에 소급해 넣으면 날짜별 digest 로는 안 보인다."""
        problems = self._problems(
            db_path, "INSERT INTO recommendations (date, ticker, action) VALUES ('2026-10-03', 'ZZZ', 'BUY')"
        )
        assert any(p.startswith("2026-10-03") and "소급" in p for p in problems)

    def test_rewriting_a_seal_row_breaks_its_hash(self, db_path):
        problems = self._problems(
            db_path, "UPDATE recommendation_seals SET digest = ? WHERE date = '2026-10-02'", ("0" * 64,)
        )
        assert any(p.startswith("2026-10-02") and "seal_hash" in p for p in problems)

    def test_recomputing_one_seal_breaks_the_next_link(self, db_path):
        """한 봉인을 자기 해시까지 맞춰 고쳐도 다음 날짜의 prev_hash 가 어긋난다."""
        _sealed(db_path)
        with get_db(db_path) as conn:
            conn.execute("UPDATE recommendations SET action = 'BUY' WHERE ticker = 'BBB'")
            n, digest = seal._day_digest(conn, "2026-10-01")
            new = seal._seal_hash(seal.GENESIS, "2026-10-01", n, digest)
            conn.execute(
                "UPDATE recommendation_seals SET n_rows = ?, digest = ?, seal_hash = ? WHERE date = '2026-10-01'",
                (n, digest, new),
            )
        problems = seal.verify(db_path=db_path)
        assert any(p.startswith("2026-10-02") and "prev_hash" in p for p in problems)


class TestForeignFieldSet:
    def test_a_seal_from_another_field_set_is_reported_not_verified(self, db_path):
        """v2 체인 행은 이 코드가 검증할 수 없다 — 조용히 통과시키지도, v1 규칙으로 오판하지도 않는다.

        최신 행을 고친다: 중간 행이면 다음 날짜의 체인 끊김 보고가 따라붙어 그 연쇄까지 잠그게 된다.
        seal_hash 도 바꿔 두므로 field_set 검사를 지우면 v1 해시 검사가 대신 걸려 목록이 달라진다.
        """
        _sealed(db_path)
        with get_db(db_path) as conn:
            conn.execute(
                "UPDATE recommendation_seals SET field_set = 'v2', seal_hash = ? WHERE date = '2026-10-05'",
                ("f" * 64,),
            )
        assert seal.verify(db_path=db_path) == ["2026-10-05: field_set 'v2' — 이 코드는 'v1' 만 검증한다"]


class TestLegitimateChangesStayClean:
    """사후 측정·라벨 백필은 정상 운영이다 — 이게 변조로 잡히면 봉인이 매일 거짓 경보를 낸다."""

    @pytest.mark.parametrize(
        "sql",
        [
            "UPDATE recommendations SET outcome_30d = 4.2, hit = 1, hit_quality = 0.2, tracked_at = '2026-11-01 07:00'",
            "UPDATE recommendations SET outcome_7d = 1.0, outcome_14d = 2.0, outcome_21d = 3.0, outcome_60d = 5.0, outcome_90d = 6.0",
            "UPDATE recommendations SET regime = 'bull_low_vol'",
        ],
    )
    def test_excluded_columns_do_not_trip_the_seal(self, db_path, sql):
        _sealed(db_path)
        with get_db(db_path) as conn:
            conn.execute(sql)
        assert seal.verify(db_path=db_path) == []


class TestFieldSetIsFrozen:
    def test_v1_field_list(self):
        assert seal.FIELDS_V1 == (
            "id",
            "date",
            "ticker",
            "action",
            "confidence",
            "signals",
            "entry_price",
            "agent_verdicts",
            "scoring_detail",
            "alpha_action",
            "portfolio_action",
            "source",
            "code_rev",
            "execution_config_sha_v1",
        ), "봉인 필드를 바꿨다 — 과거 봉인과 비교가 깨진다. FIELD_SET 을 v2 로 올리고 새 체인을 시작할 것"

    def test_every_sealed_field_is_a_real_column(self, db_path):
        cols = {r["name"] for r in query("SELECT name FROM pragma_table_info('recommendations')", db_path=db_path)}
        assert set(seal.FIELDS_V1) <= cols


class TestAnchor:
    def test_monthly_line_carries_the_chain_head(self):
        from nuri.alerts.alpha_report import format_progress_reason

        line = format_progress_reason(
            {"n": 0, "ledger_seal": {"date": "2026-10-06", "seal_hash": "abcdef0123456789" * 4}}
        )
        assert f"봉인 2026-10-06 · {'abcdef0123456789' * 4}" in line, (
            "앞 12자(48비트)만 실으면 앵커를 맞춰 만들 수 있다"
        )

    def test_deleting_the_newest_seal_and_resealing_passes_verify_but_not_the_anchor(self, db_path):
        """남은 체인은 정합하다 — verify() 는 못 본다. DB 밖의 머리와 대조해야 잡힌다."""
        _sealed(db_path)
        anchored = seal.latest_seal(db_path=db_path)
        assert anchored is not None
        with get_db(db_path) as conn:
            conn.execute("DELETE FROM recommendation_seals WHERE date = ?", (anchored["date"],))
            conn.execute("UPDATE recommendations SET action = 'SELL' WHERE date = ?", (anchored["date"],))
        _sealed(db_path)
        assert seal.verify(db_path=db_path) == []
        assert seal.verify_anchor(anchored["date"], anchored["seal_hash"], db_path=db_path)

    def test_deleting_every_seal_is_caught_by_the_anchor(self, db_path):
        _sealed(db_path)
        anchored = seal.latest_seal(db_path=db_path)
        with get_db(db_path) as conn:
            conn.execute("DELETE FROM recommendation_seals")
        assert seal.verify(db_path=db_path) == []
        assert anchored is not None
        assert seal.verify_anchor(anchored["date"], anchored["seal_hash"], db_path=db_path)

    def test_untouched_chain_matches_its_anchor(self, db_path):
        _sealed(db_path)
        anchored = seal.latest_seal(db_path=db_path)
        assert anchored is not None
        assert seal.verify_anchor(anchored["date"], anchored["seal_hash"], db_path=db_path) == []

    def test_no_seal_no_anchor(self):
        from nuri.alerts.alpha_report import format_progress_reason

        assert "봉인" not in format_progress_reason({"n": 0})


class TestHashCompatibility:
    """Chain 일반화(#1962) 전 코드로 계산한 봉인값 — 해시 형식이 바뀌면 운영 원장의 과거 봉인이 전부 불일치가 된다.

    origin/main(60c04521)의 `ledger_seal.py` 를 이 픽스처에 그대로 돌려 얻은 값이다.
    """

    def test_seals_match_the_pre_refactor_values(self, db_path):
        _sealed(db_path)
        rows = query("SELECT date, n_rows, digest, seal_hash FROM recommendation_seals ORDER BY date", db_path=db_path)
        assert [tuple(r.values()) for r in rows] == [
            (
                "2026-10-01",
                2,
                "8b7a918b3985939e7a920ec2a3bbeaa5ac3f67f19ab58293ee2be63be180772f",
                "93ecc90261ad3fb72dc4bbba6aba968fff9c0d0072b3568636cad5aef9db7800",
            ),
            (
                "2026-10-02",
                1,
                "b6060cb72f57d4ea7f161f4ab78f2e2b7711572cb4e81cbddc0f2588c6b8b65a",
                "94cb0b4a6a710ca2ce242e68ef8851bc5d746b3df96c921a0a9007e11ae7771d",
            ),
            (
                "2026-10-05",
                1,
                "9a9d2e04f0212c0fce07ed55de39c5da0c11f7e4b12c995f977d30a9f42681d6",
                "1a23b402836e8dd2fa68b14d1d10bf5eb20eae93385c112ecac4b29616a7f300",
            ),
        ]


class TestDailyJob:
    """봉인은 월간 리포트 job 안에서 **매일**, production 에서만 돈다 (#1718)."""

    def test_production_job_seals_and_records_it(self):
        from unittest.mock import patch

        from nuri import scheduler

        with (
            patch("nuri.alerts.alpha_report.is_production", return_value=True),
            patch("nuri.alerts.alpha_report.already_emitted", return_value=True),
            patch("nuri.alerts.alpha_report.stage_alpha_progress_brief", return_value=None),
            patch("nuri.core.db.ledger_seal.seal_closed_days", return_value=["2026-10-06"]) as sealed,
            patch("nuri.core.db.ledger_seal.verify", return_value=[]),
            patch("nuri.core.events.emit_event") as emitted,
        ):
            scheduler._run_alpha_report()
        # 판정 원장 한 번, thesis 실험 원장(#1962) 한 번 — 각자 자기 체인으로
        assert sealed.call_count == 2
        assert "chain" not in sealed.call_args_list[0].kwargs
        assert sealed.call_args_list[1].kwargs["chain"] is seal.THESIS_RUNS
        payload = emitted.call_args.kwargs["payload"]
        assert payload["sealed_days"] == 1 and payload["seal_problems"] == 0

    def test_off_production_does_not_seal(self):
        from unittest.mock import patch

        from nuri import scheduler

        with (
            patch("nuri.alerts.alpha_report.is_production", return_value=False),
            patch("nuri.alerts.alpha_report.stage_alpha_progress_brief", return_value=None),
            patch("nuri.core.db.ledger_seal.seal_closed_days") as sealed,
            patch("nuri.core.events.emit_event"),
        ):
            scheduler._run_alpha_report()
        sealed.assert_not_called()

    def test_seal_failure_does_not_block_the_report(self):
        """봉인은 Surface — 실패가 진행 리포트 stage 를 막으면 관측이 관측 대상을 죽인다 (#894)."""
        from unittest.mock import patch

        from nuri import scheduler

        with (
            patch("nuri.alerts.alpha_report.is_production", return_value=True),
            patch("nuri.alerts.alpha_report.already_emitted", return_value=False),
            patch("nuri.alerts.alpha_report.stage_alpha_progress_brief", return_value=9) as staged,
            patch("nuri.core.db.ledger_seal.seal_closed_days", side_effect=RuntimeError("locked")),
            patch("nuri.core.events.emit_event") as emitted,
        ):
            scheduler._run_alpha_report()
        staged.assert_called_once_with()
        assert emitted.call_args.kwargs["payload"]["error"] is None

    def test_a_seal_mismatch_is_counted_and_warned(self, caplog):
        """불일치는 매일 job 이 표면화한다 — 개수는 heartbeat payload 에, 경고는 운영 로그에."""
        import logging
        from unittest.mock import patch

        from nuri import scheduler

        with (
            patch("nuri.alerts.alpha_report.is_production", return_value=True),
            patch("nuri.alerts.alpha_report.already_emitted", return_value=True),
            patch("nuri.alerts.alpha_report.stage_alpha_progress_brief", return_value=None),
            patch("nuri.core.db.ledger_seal.seal_closed_days", return_value=[]),
            patch("nuri.core.db.ledger_seal.verify", return_value=["2026-10-01: a", "2026-10-02: b"]),
            patch("nuri.core.events.emit_event") as emitted,
            caplog.at_level(logging.WARNING, logger="nuri.scheduler"),
        ):
            scheduler._run_alpha_report()
        assert emitted.call_args.kwargs["payload"]["seal_problems"] == 2
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("봉인 불일치 2건" in m for m in warnings)


class TestCli:
    """`python -m nuri.core.db.ledger_seal` — 운영자가 손으로 돌리는 검증. 종료 코드가 곧 판정이다."""

    @pytest.fixture(autouse=True)
    def _pin_today(self, monkeypatch):
        from nuri.core import timezone

        monkeypatch.setattr(timezone, "today_kst", lambda: TODAY)

    def test_seal_prints_the_sealed_range_and_the_head(self, db_path, capsys):
        assert seal.main(["--db", str(db_path), "--seal"]) == 0
        head = seal.latest_seal(db_path=db_path)
        assert head is not None
        assert capsys.readouterr().out.splitlines() == [
            "봉인 3일 (2026-10-01 ~ 2026-10-05)",
            f"봉인 머리: 2026-10-05 · {head['seal_hash'][:16]}",
            "✓ 무결",
        ]

    def test_resealing_on_the_same_day_prints_no_range(self, db_path, capsys):
        _sealed(db_path)
        assert seal.main(["--db", str(db_path), "--seal"]) == 0
        assert capsys.readouterr().out.splitlines()[0] == "봉인 0일"

    def test_tampering_exits_nonzero_and_lists_each_problem(self, db_path, capsys):
        _sealed(db_path)
        with get_db(db_path) as conn:
            conn.execute("DELETE FROM recommendations WHERE date = '2026-10-02'")
        assert seal.main(["--db", str(db_path)]) == 1
        out = capsys.readouterr().out.splitlines()
        assert "✗ 2026-10-02: 봉인 후 행이 바뀌었다 (행 수 1 → 0)" in out
        assert out[-1] == "✗ 1건 불일치"

    def test_an_anchor_that_no_longer_matches_exits_nonzero(self, db_path, capsys):
        _sealed(db_path)
        head = seal.latest_seal(db_path=db_path)
        assert head is not None
        assert seal.main(["--db", str(db_path), "--anchor", head["date"], head["seal_hash"]]) == 0
        assert seal.main(["--db", str(db_path), "--anchor", head["date"], "0" * 64]) == 1
        assert "✗ 2026-10-05: 외부에 남은 머리와 다르다 (봉인 재계산)" in capsys.readouterr().out.splitlines()

    def test_an_unsealed_ledger_has_no_head_and_is_clean(self, tmp_path, capsys):
        empty = tmp_path / "empty.db"
        init_db(empty)
        assert seal.main(["--db", str(empty)]) == 0
        assert capsys.readouterr().out.splitlines() == ["✓ 무결"]


def test_module_entry_point_exits_with_the_verdict(db_path, monkeypatch):
    """`python -m` 의 종료 코드가 판정이다 — 변조된 원장이 0 으로 끝나면 호출한 쪽은 무결로 읽는다."""
    import runpy
    import sys

    _sealed(db_path)
    with get_db(db_path) as conn:
        conn.execute("UPDATE recommendations SET action = 'BUY' WHERE ticker = 'BBB'")
    monkeypatch.setattr(sys, "argv", ["ledger_seal", "--db", str(db_path)])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("nuri.core.db.ledger_seal", run_name="__main__")
    assert exc.value.code == 1

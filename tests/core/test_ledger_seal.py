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
        first_head = seal.latest_seal(db_path=db_path)["seal_hash"]
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
        assert "봉인 2026-10-06 · abcdef012345" in line

    def test_no_seal_no_anchor(self):
        from nuri.alerts.alpha_report import format_progress_reason

        assert "봉인" not in format_progress_reason({"n": 0})


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
        sealed.assert_called_once()
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

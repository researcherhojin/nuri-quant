"""thesis 실험 원장 (#1962) — 운영 기기에서만 쓰고, 봉인 뒤 변조를 잡는다.

봉인 잠금은 `test_ledger_seal.py` 와 같은 방식이다: 변조를 실제로 가해 `verify()` 가 잡는지 본다.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from nuri.core.db import get_db, init_db, query
from nuri.core.db import ledger_seal as seal
from nuri.core.db import thesis_ledger as tl

TODAY = "2026-10-07"
CHAIN = seal.THESIS_RUNS


def _run(ticker="AAA", rating="Hold", outcome="verdict"):
    return {
        "arm": "A",
        "arm_hash": "ah",
        "ticker": ticker,
        "scored": True,
        "run_hash": f"rh-{ticker}",
        "packet_hashes": ["tp", "mp"],
        "view_hash": "vh",
        "calls": [{"prompt_sha256": "p1", "content_hash": "c1"}],
        "budget_tokens": 14000,
        "rating": rating,
        "outcome": outcome,
    }


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    p = tmp_path / "t.db"
    init_db(p)
    monkeypatch.setenv("NURI_ROLE", "production")
    for day, ticker in [("2026-10-01", "AAA"), ("2026-10-01", "BBB"), ("2026-10-02", "AAA"), (TODAY, "CCC")]:
        tl.record_run(_run(ticker), cohort_date=day, runtime={"version": "v"}, canary_sha256="cn", db_path=p)
    return p


class TestWriter:
    def test_a_row_carries_the_run_and_its_provenance(self, db_path):
        row = query("SELECT * FROM thesis_runs WHERE cohort_date = '2026-10-02'", db_path=db_path)[0]
        assert (row["arm"], row["ticker"], row["scored"], row["rating"], row["outcome"]) == (
            "A",
            "AAA",
            1,
            "Hold",
            "verdict",
        )
        assert row["arm_hash"] == "ah"
        assert json.loads(row["prompt_hashes"]) == ["p1"] and json.loads(row["call_hashes"]) == ["c1"]
        assert json.loads(row["runtime"]) == {"version": "v"} and row["canary_sha256"] == "cn"

    @pytest.mark.parametrize("role", ["", "dev", "productions"])
    def test_only_the_production_role_may_write(self, db_path, monkeypatch, role):
        """dev 복제본 · MBP 대화형 실행은 원장에 쓰지 않는다 — mini scheduler plist 에만 이 값이 있다."""
        monkeypatch.setenv("NURI_ROLE", role)
        with pytest.raises(tl.NotProductionError):
            tl.record_run(_run(), cohort_date="2026-10-03", runtime={}, canary_sha256=None, db_path=db_path)
        assert query("SELECT COUNT(*) AS n FROM thesis_runs", db_path=db_path)[0]["n"] == 4


def _sealed(db_path):
    return seal.seal_closed_days(TODAY, db_path=db_path, chain=CHAIN)


class TestSealAndTamper:
    def test_closed_days_are_sealed_and_verify_clean(self, db_path):
        assert _sealed(db_path) == ["2026-10-01", "2026-10-02"]
        assert seal.verify(db_path=db_path, chain=CHAIN) == []
        # 판정 원장 체인과 섞이지 않는다
        assert seal.latest_seal(db_path=db_path) is None

    def test_an_edited_sealed_field_is_caught(self, db_path):
        _sealed(db_path)
        with get_db(db_path) as conn:
            conn.execute("UPDATE thesis_runs SET rating = 'Buy' WHERE cohort_date = '2026-10-01' AND ticker = 'AAA'")
        assert any("2026-10-01" in p and "봉인 필드 변경" in p for p in seal.verify(db_path=db_path, chain=CHAIN))

    def test_a_deleted_row_is_caught(self, db_path):
        _sealed(db_path)
        with get_db(db_path) as conn:
            conn.execute("DELETE FROM thesis_runs WHERE cohort_date = '2026-10-01' AND ticker = 'BBB'")
        assert any("행 수 2 → 1" in p for p in seal.verify(db_path=db_path, chain=CHAIN))

    def test_a_row_inserted_into_a_sealed_date_is_caught(self, db_path):
        _sealed(db_path)
        tl.record_run(_run("ZZZ"), cohort_date="2026-10-02", runtime={}, canary_sha256=None, db_path=db_path)
        assert any("행 수 1 → 2" in p for p in seal.verify(db_path=db_path, chain=CHAIN))

    def test_a_backdated_row_is_caught(self, db_path):
        _sealed(db_path)
        tl.record_run(_run("ZZZ"), cohort_date="2026-09-30", runtime={}, canary_sha256=None, db_path=db_path)
        assert any("2026-09-30" in p and "소급 삽입" in p for p in seal.verify(db_path=db_path, chain=CHAIN))

    def test_an_edited_arm_hash_is_caught(self, db_path):
        """팔 정의 지문도 봉인 필드다 (#1963) — 어떤 팔로 돌렸는지 사후에 바꾸지 못한다."""
        _sealed(db_path)
        with get_db(db_path) as conn:
            conn.execute("UPDATE thesis_runs SET arm_hash = 'other' WHERE cohort_date = '2026-10-02'")
        assert any("2026-10-02" in p and "봉인 필드 변경" in p for p in seal.verify(db_path=db_path, chain=CHAIN))

    def test_a_rewritten_recorded_time_is_caught(self, db_path):
        """기록 시각은 "개장 전에 기록됐다" 의 증거라 봉인 대상이다 — 고치면 잡힌다."""
        _sealed(db_path)
        with get_db(db_path) as conn:
            conn.execute("UPDATE thesis_runs SET recorded_at = '2000-01-01 00:00:00' WHERE cohort_date = '2026-10-01'")
        assert any("2026-10-01" in p and "봉인 필드 변경" in p for p in seal.verify(db_path=db_path, chain=CHAIN))

    def test_a_resealed_chain_is_caught_only_by_the_anchor(self, db_path):
        _sealed(db_path)
        anchored = seal.latest_seal(db_path=db_path, chain=CHAIN)
        assert anchored is not None
        with get_db(db_path) as conn:
            conn.execute("UPDATE thesis_runs SET rating = 'Buy' WHERE cohort_date = '2026-10-02'")
            conn.execute("DELETE FROM thesis_run_seals")
        _sealed(db_path)
        assert seal.verify(db_path=db_path, chain=CHAIN) == []  # 다시 만든 체인은 그 자체로 정합하다
        assert seal.verify_anchor(anchored["date"], anchored["seal_hash"], db_path=db_path, chain=CHAIN) == [
            f"{anchored['date']}: 외부에 남은 머리와 다르다 (봉인 재계산)"
        ]

    def test_cli_chain_option(self, db_path, capsys, monkeypatch):
        from nuri.core import timezone

        monkeypatch.setattr(timezone, "today_kst", lambda: TODAY)
        assert seal.main(["--db", str(db_path), "--chain", "thesis_runs", "--seal"]) == 0
        assert "봉인 2일 (2026-10-01 ~ 2026-10-02)" in capsys.readouterr().out
        head = seal.latest_seal(db_path=db_path, chain=CHAIN)
        assert head is not None
        assert seal.main(["--db", str(db_path), "--chain", "thesis_runs", "--anchor", head["date"], "0" * 64]) == 1


class TestReportAndJob:
    def test_the_monthly_brief_carries_the_thesis_head_in_full(self):
        from nuri.alerts.alpha_report import format_progress_reason

        line = format_progress_reason({"n": 0, "thesis_ledger_seal": {"date": "2026-10-02", "seal_hash": "f" * 64}})
        assert f"thesis 봉인 2026-10-02 · {'f' * 64}" in line

    def test_the_brief_looks_up_both_heads(self, db_path):
        from nuri.alerts import alpha_report

        _sealed(db_path)
        with (
            patch.object(alpha_report, "build_progress_report", return_value={"n": 0}),
            patch("nuri.agents.discord.outbox.stage_brief", return_value=3) as staged,
        ):
            alpha_report.stage_alpha_progress_brief(db_path=db_path)
        head = seal.latest_seal(db_path=db_path, chain=CHAIN)
        assert head is not None
        assert head["seal_hash"] in staged.call_args.kwargs["payload"]["reason"]

    def test_a_thesis_seal_failure_does_not_stop_the_job(self, caplog):
        import logging

        from nuri import scheduler

        def fake_seal(today, db_path=None, chain=seal.RECOMMENDATIONS):
            if chain is CHAIN:
                raise RuntimeError("locked")
            return []

        with (
            patch("nuri.alerts.alpha_report.is_production", return_value=True),
            patch("nuri.alerts.alpha_report.already_emitted", return_value=True),
            patch("nuri.alerts.alpha_report.stage_alpha_progress_brief", return_value=None) as staged,
            patch("nuri.core.db.ledger_seal.seal_closed_days", side_effect=fake_seal),
            patch("nuri.core.db.ledger_seal.verify", return_value=[]),
            patch("nuri.core.events.emit_event"),
            caplog.at_level(logging.ERROR, logger="nuri.scheduler"),
        ):
            scheduler._run_alpha_report()
        staged.assert_called_once_with()
        assert "thesis 원장 봉인 실패" in caplog.text

    def test_a_thesis_mismatch_is_warned(self, caplog):
        import logging

        from nuri import scheduler

        def fake_verify(db_path=None, chain=seal.RECOMMENDATIONS):
            return ["2026-10-01: x"] if chain is CHAIN else []

        with (
            patch("nuri.alerts.alpha_report.is_production", return_value=True),
            patch("nuri.alerts.alpha_report.already_emitted", return_value=True),
            patch("nuri.alerts.alpha_report.stage_alpha_progress_brief", return_value=None),
            patch("nuri.core.db.ledger_seal.seal_closed_days", return_value=[]),
            patch("nuri.core.db.ledger_seal.verify", side_effect=fake_verify),
            patch("nuri.core.events.emit_event"),
            caplog.at_level(logging.WARNING, logger="nuri.scheduler"),
        ):
            scheduler._run_alpha_report()
        assert "thesis 원장 봉인 불일치" in caplog.text

"""thesis 파일럿 경보 · 보고 (#1998)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest
import yaml

from nuri.core.db import get_db, init_db, query
from nuri.core.timezone import KST
from nuri.llm import thesis_freeze as tf
from nuri.llm import thesis_pilot as tp
from nuri.llm import thesis_pilot_ops as ops

PILOT = tp.Pilot("pilot-x", 5, ("A", "B"), 75)
NOW = datetime(2026, 11, 4, 18, 0, tzinfo=KST)  # 수요일 저녁 — 그날 아침 밤이 돌았어야 한다
COHORT = "2026-11-04"


def utc(kst_hour, minute=0, day=4):
    return datetime(2026, 11, day, kst_hour, minute, tzinfo=KST).astimezone(timezone.utc)


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "t.db"
    init_db(p)
    return p


@pytest.fixture
def freeze_path(tmp_path):
    p = tmp_path / "freeze.yaml"
    doc = {
        "freezes": [
            {"experiment": "pilot-x", "start": date(2026, 11, 4), "end": date(2026, 11, 27), "arms": {"A": "a" * 64}}
        ]
    }
    p.write_text(yaml.safe_dump(doc))
    return p


def add_night(db, outcome="ran", exit_code=0, ended=True, cohort=COHORT, tickers=5, start=None, end=None):
    with get_db(db) as conn:
        conn.execute(
            "INSERT INTO thesis_pilot_nights (experiment, cohort_date, started_at, ended_at, outcome, exit_code, "
            "seed, universe_hash, tickers) VALUES ('pilot-x', ?, ?, ?, ?, ?, 's', 'u', ?)",
            (
                cohort,
                (start or utc(8)).isoformat(),
                (end or utc(9)).isoformat() if ended else None,
                outcome if ended else None,
                exit_code if ended else None,
                tickers,
            ),
        )


def add_batch(db, status, started, batch_id="b1"):
    with get_db(db) as conn:
        conn.execute(
            "INSERT INTO thesis_batches (batch_id, experiment, started_at, canary_start, status) "
            "VALUES (?, 'pilot-x', ?, 'c', ?)",
            (batch_id, started.isoformat(), status),
        )


def find(db, freeze_path, now=NOW, hours=6):
    return ops.findings(PILOT, now, defer_hours=hours, freeze_path=freeze_path, db_path=db)


NEXT = datetime(2026, 11, 5, 18, 0, tzinfo=KST)  # 다음 날 — 04 의 밤이 있었어야 한다


class TestFindings:
    def test_a_healthy_night_raises_nothing(self, db, freeze_path):
        add_night(db)
        add_batch(db, "ok", utc(8))
        assert find(db, freeze_path, now=NEXT) == []

    def test_today_is_not_missing_yet(self, db, freeze_path):
        """오늘 밤은 러너가 아직 안 돌았을 수 있다 — 다음 날 판정한다(지연 최대 하루)."""
        assert find(db, freeze_path) == []

    def test_every_missed_session_night_in_the_window_is_reported(self, db, freeze_path):
        """창 시작(11-04) 전 · 세션 없는 밤(일 · 월 아침) · 오늘은 빼고, 지난 밤을 모두 본다."""
        found = find(db, freeze_path, now=datetime(2026, 11, 10, 18, 0, tzinfo=KST))
        assert [(f["kind"], f["cohort"]) for f in found] == [
            ("missing", d) for d in ("2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07")
        ]

    def test_another_experiments_window_expects_nothing_of_this_one(self, db, tmp_path):
        p = tmp_path / "other.yaml"
        doc = {"experiment": "other", "start": date(2026, 11, 4), "end": date(2026, 11, 27), "arms": {"A": "a" * 64}}
        p.write_text(yaml.safe_dump({"freezes": [doc]}))
        assert find(db, p, now=NEXT) == []

    def test_nothing_is_expected_after_the_window(self, db, freeze_path):
        for d in range(4, 28):
            add_night(db, cohort=f"2026-11-{d:02d}")
        assert find(db, freeze_path, now=datetime(2026, 12, 5, 18, 0, tzinfo=KST)) == []

    @pytest.mark.parametrize(
        ("outcome", "exit_code"),
        [("refused:ollama_busy", 5), ("ran", 3), ("error:OSError", 1), ("refused:other", 0)],
    )
    def test_a_refused_failed_or_crashed_night_is_reported(self, db, freeze_path, outcome, exit_code):
        add_night(db, outcome=outcome, exit_code=exit_code)
        found = find(db, freeze_path, now=NEXT)
        assert [f["kind"] for f in found] == ["failed"] and outcome in found[0]["detail"]

    def test_an_unfinished_night_is_stuck_after_the_cap_even_without_a_batch(self, db, freeze_path):
        """예약 뒤 러너가 죽었다 — 배치 행이 없어도 기한으로 잡는다 (Codex 리뷰)."""
        add_night(db, ended=False)
        assert find(db, freeze_path, hours=12) == []  # 08 → 18 시: 10h
        assert [f["kind"] for f in find(db, freeze_path, hours=6)] == ["stuck"]

    def test_a_batch_open_past_the_cap_is_stuck(self, db, freeze_path):
        add_night(db)
        add_batch(db, "open", utc(8))
        assert [f["kind"] for f in find(db, freeze_path, hours=6)] == ["stuck"]
        assert find(db, freeze_path, hours=12) == []

    def test_a_canary_change_is_reported_on_any_later_day(self, db, freeze_path):
        """그날 확인을 놓쳐도 사라지지 않는다 — 반복은 outbox 키가 막는다."""
        add_night(db)
        add_batch(db, "canary_changed", utc(8))
        assert [f["kind"] for f in find(db, freeze_path, now=datetime(2026, 11, 4, 9, 0, tzinfo=KST))] == [
            "canary_changed"
        ]
        assert [f["kind"] for f in find(db, freeze_path, now=NEXT)] == ["canary_changed"]


class TestStage:
    def test_one_ops_message_per_cohort_and_kind_even_after_it_was_sent(self, db, freeze_path):
        assert ops.stage(find(db, freeze_path, now=NEXT), "pilot-x", db_path=db) == 1
        with get_db(db) as conn:
            conn.execute("UPDATE discord_outbox SET status = 'sent'")
        assert ops.stage(find(db, freeze_path, now=NEXT), "pilot-x", db_path=db) == 0
        rows = query("SELECT channel, dedupe_key, payload_json FROM discord_outbox", db_path=db)
        assert [(r["channel"], r["dedupe_key"]) for r in rows] == [("ops", "thesis-pilot:pilot-x:2026-11-04:missing")]
        assert "missing" in json.loads(rows[0]["payload_json"])["summary"]

    @pytest.mark.parametrize(
        ("setup", "kind"),
        [
            (lambda db: add_night(db, outcome="ran", exit_code=3), "failed"),
            (lambda db: (add_night(db), add_batch(db, "open", utc(8))), "stuck"),
            (lambda db: (add_night(db), add_batch(db, "canary_changed", utc(8))), "canary_changed"),
            (lambda db: None, "missing"),
        ],
    )
    def test_each_kind_is_staged_once(self, db, freeze_path, setup, kind):
        setup(db)
        assert ops.stage(find(db, freeze_path, now=NEXT), "pilot-x", db_path=db) == 1
        assert ops.stage(find(db, freeze_path, now=NEXT), "pilot-x", db_path=db) == 0
        (row,) = query("SELECT dedupe_key FROM discord_outbox", db_path=db)
        assert row["dedupe_key"].endswith(f":{kind}")

    def test_a_healthy_experiment_stages_nothing(self, db, freeze_path):
        add_night(db)
        add_batch(db, "ok", utc(8))
        assert ops.stage(find(db, freeze_path, now=NEXT), "pilot-x", db_path=db) == 0


class TestDeferHours:
    @pytest.mark.parametrize(("raw", "hours"), [("3", 3), ("99", 99), (None, 6), ("0", 6), ("100", 6), ("6h", 6)])
    def test_the_same_rule_as_autopull(self, raw, hours):
        assert ops.defer_hours(raw) == hours


def seed_report(db):
    """손으로 셀 수 있는 원장 — 두 밤, 팔 둘, 종목 셋."""
    add_night(db, cohort="2026-11-03", tickers=3, start=utc(8, day=3), end=utc(9, day=3))
    add_night(db, cohort="2026-11-04", outcome="refused:ollama_busy", exit_code=5)
    add_batch(db, "ok", utc(8, day=3), batch_id="b3")
    runs = [  # (arm, ticker, 기록 시각 분, outcome, rating)
        ("A", "T1", 3, "verdict", "Buy"),
        ("B", "T1", 3, "verdict", "Hold"),
        ("A", "T2", 7, "review_model", "REVIEW"),
        ("B", "T2", 7, "verdict", "Sell"),
        ("A", "T3", 12, "verdict", "Hold"),
        ("B", "T3", 12, "verdict", "Buy"),
    ]
    with get_db(db) as conn:
        for arm, t, minute, outcome, rating in runs:
            at = utc(8, minute, day=3).strftime("%Y-%m-%d %H:%M:%S")  # SQLite datetime('now') 형식
            conn.execute(
                "INSERT INTO thesis_runs (experiment, batch_id, cohort_date, arm, arm_hash, ticker, cutoff, late, "
                "scored, run_hash, packet_hashes, view_hash, prompt_hashes, call_hashes, runtime, budget_tokens, "
                "rating, outcome, recorded_at) VALUES ('pilot-x', 'b3', '2026-11-03', ?, 'h', ?, 'c', 0, 1, 'r', "
                "'[]', 'v', '[]', '[]', '{}', 14000, ?, ?, ?)",
                (arm, t, rating, outcome, at),
            )
        for pct, swap in ((90.0, 10.0), (70.0, 40.0)):
            conn.execute("INSERT INTO thesis_pilot_samples VALUES ('pilot-x', '2026-11-03', 'x', ?, ?)", (pct, swap))
        fmt = "%Y-%m-%d %H:%M:%S"
        for name, s, e in (
            ("news", utc(8, 30, 3), utc(8, 31, 3)),
            ("factors", utc(9, 30, 3), utc(9, 40, 3)),
            ("technical", utc(7, 0, 3), utc(7, 10, 3)),
        ):
            conn.execute(
                "INSERT INTO collector_runs (collector_name, started_at, finished_at, status) VALUES (?, ?, ?, "
                "'finished')",
                (name, s.strftime(fmt), e.strftime(fmt)),
            )
        for run_id, actor, at in (("r1", "sre", utc(8, 45, 3)), ("r2", "watchdog", utc(7, 30, 3))):
            # 둘 다 아직 끝나지 않았다 — watchdog 은 밤 전에 시작해 밤 내내 돌고 있다
            conn.execute(
                "INSERT INTO agent_run_ledger (run_id, actor_name, status, started_at) VALUES (?, ?, 'started', ?)",
                (run_id, actor, at.strftime(fmt)),
            )


class TestReport:
    def test_numbers_match_a_hand_count(self, db):
        seed_report(db)
        r = ops.report("pilot-x", db_path=db)
        assert r["nights"] == {"ran": 1, "refused:ollama_busy": 1}
        assert r["drawn_tickers"] == 3
        assert r["arms"]["A"] == {
            "runs": 3,
            "outcomes": {"review_model": 1, "verdict": 2},
            "review_rate": 0.333,
            "completion": 0.667,
        }
        assert r["arms"]["B"] == {"runs": 3, "outcomes": {"verdict": 3}, "review_rate": 0.0, "completion": 1.0}
        # 08:00 시작 → 08:03, 08:07, 08:12 에 종목이 끝났다: 180 · 240 · 300 초
        assert r["ticker_wall_s"] == {"n": 3, "median": 240.0, "max": 300.0}
        assert r["memory"] == {
            "min_available_pct": 70.0,
            "min_swap_mb": 10.0,
            "max_swap_mb": 40.0,
            "swap_growth_mb": 30.0,
            "samples": 2,
        }
        # 08:00–09:00 창 — news(08:30) · 끝나지 않은 sre(08:45) · watchdog(07:30~) 은 겹치고,
        # factors(09:30) · technical(07:00–07:10) 은 아니다
        assert r["overlapping_jobs"] == {"news": 1, "sre": 1, "watchdog": 1}

    def test_verdicts_from_a_night_that_did_not_finish_do_not_inflate_completion(self, db):
        """분자 · 분모는 같은 밤들에서 — 거절된 11-04 의 판정은 완료율에 들어가지 않는다 (Codex 리뷰: 1.6)."""
        seed_report(db)
        with get_db(db) as conn:
            conn.execute(
                "INSERT INTO thesis_runs (experiment, batch_id, cohort_date, arm, arm_hash, ticker, cutoff, late, "
                "scored, run_hash, packet_hashes, view_hash, prompt_hashes, call_hashes, runtime, budget_tokens, "
                "rating, outcome) VALUES ('pilot-x', 'b4', '2026-11-04', 'B', 'h', 'T9', 'c', 0, 1, 'r', '[]', 'v', "
                "'[]', '[]', '{}', 14000, 'Hold', 'verdict')"
            )
        b = ops.report("pilot-x", db_path=db)["arms"]["B"]
        assert b["runs"] == 4 and b["completion"] == 1.0

    def test_the_report_carries_no_ticker_or_rating(self, db):
        seed_report(db)
        text = json.dumps(ops.report("pilot-x", db_path=db))
        assert not any(t in text for t in ("T1", "T2", "T3", "Buy", "Sell", "Overweight"))

    def test_an_empty_experiment_reports_zeros(self, db):
        r = ops.report("pilot-x", db_path=db)
        assert r["arms"] == {} and r["ticker_wall_s"] == {"n": 0, "median": None, "max": None}

    def test_runs_without_their_batch_row_are_skipped_for_wall_time(self, db):
        seed_report(db)
        with get_db(db) as conn:
            conn.execute("DELETE FROM thesis_batches")
        assert ops.report("pilot-x", db_path=db)["ticker_wall_s"]["n"] == 0


class TestCli:
    def _repo(self, tmp_path, monkeypatch, experiment):
        (tmp_path / "config").mkdir()
        doc = {"experiment": experiment, "tickers_per_night": 5, "arms": ["A", "B"], "brief_quiet_minutes": 75}
        (tmp_path / tp.PILOT_PATH).write_text(yaml.safe_dump(doc))
        monkeypatch.chdir(tmp_path)

    def test_disabled(self, tmp_path, monkeypatch, capsys):
        self._repo(tmp_path, monkeypatch, None)
        assert ops.main(["check"]) == 0 and capsys.readouterr().out.strip() == "disabled"

    def test_report_and_check(self, tmp_path, monkeypatch, capsys, db, freeze_path):
        self._repo(tmp_path, monkeypatch, "pilot-x")
        (tmp_path / tf.FREEZE_PATH).write_text(freeze_path.read_text())
        seed_report(db)
        assert ops.main(["report", "--db", str(db)]) == 0
        assert json.loads(capsys.readouterr().out)["drawn_tickers"] == 3
        monkeypatch.setattr(ops, "kst_now", lambda: NOW)
        assert ops.main(["check", "--db", str(db)]) == 0
        assert json.loads(capsys.readouterr().out) == {"findings": 1, "staged": 1}

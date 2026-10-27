"""다단계 팔 B 의 메모리 (#1966) — 진입 세션 · 정산 · reflection · 보이는 조건 · 상한. 가격 · 모델은 가짜다."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest
import requests

from nuri.core.db import get_db, init_db, query
from nuri.core.db import thesis_ledger as ledger
from nuri.llm import local_client as lc
from nuri.llm import thesis_memory as tm

KST = timezone(timedelta(hours=9))
CFG_MEMORY = {
    "holding_sessions": 5,
    "same_ticker": 5,
    "cross_ticker": 3,
    "benchmark": "SPY",
    "settle_after_close_hours": 3,
    "give_up_days": 7,
    "reflection_num_predict": 300,
    "decision_chars": 1500,
}


class TestEntrySession:
    @pytest.mark.parametrize(
        ("cutoff", "entry"),
        [
            # 금 09:00 KST = 목 20:00 ET → 금요일 개장
            (datetime(2026, 10, 23, 9, 0, tzinfo=KST), date(2026, 10, 23)),
            # 토 09:00 KST = 금 20:00 ET → 월요일
            (datetime(2026, 10, 24, 9, 0, tzinfo=KST), date(2026, 10, 26)),
            # 개장 그 순간은 "뒤에 열리는" 이 아니다 → 다음 세션
            (datetime(2026, 10, 23, 9, 30, tzinfo=timezone(timedelta(hours=-4))), date(2026, 10, 26)),
            # 개장 1분 전 → 그날
            (datetime(2026, 10, 23, 9, 29, tzinfo=timezone(timedelta(hours=-4))), date(2026, 10, 23)),
            # 추수감사절(목) 전날 저녁 → 금요일
            (datetime(2026, 11, 26, 9, 0, tzinfo=KST), date(2026, 11, 27)),
        ],
    )
    def test_the_first_session_opening_after_the_cutoff(self, cutoff, entry):
        assert tm.entry_session(cutoff) == entry

    def test_the_window_skips_weekends_and_holidays(self):
        days = tm.window(datetime(2026, 11, 24, 9, 0, tzinfo=KST), 5)  # 화 09:00 KST → 화 개장부터
        assert days == [
            date(2026, 11, 24),
            date(2026, 11, 25),
            date(2026, 11, 27),
            date(2026, 11, 30),
            date(2026, 12, 1),
        ]


CUTOFF = datetime(2026, 10, 23, 9, 0, tzinfo=KST)  # 진입 10-23(금), 청산 10-29(목)
SESSIONS = ["2026-10-23", "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29"]
AFTER = datetime(2026, 10, 30, 12, 0, tzinfo=KST)  # 10-29 16:00 ET + 3h 이후


def series(t_open=100.0, t_close=110.0, s_open=500.0, s_close=505.0):
    return {
        "T0": {SESSIONS[0]: [t_open, 99.0], SESSIONS[-1]: [108.0, t_close]},
        "SPY": {SESSIONS[0]: [s_open, 501.0], SESSIONS[-1]: [503.0, s_close]},
    }


def cfg(tmp_path):
    return {"memory": dict(CFG_MEMORY), "archive_dir": str(tmp_path / "arch")}


class TestSettle:
    def test_not_before_the_last_close_plus_the_buffer(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tm, "_fetch", lambda *a: pytest.fail("fetched too early"))
        early = datetime(2026, 10, 30, 7, 59, tzinfo=KST)  # 10-29 16:00 ET = 10-30 05:00 KST, +3h = 08:00
        assert tm.settle("T0", CUTOFF, cfg=cfg(tmp_path), now=early) is None

    def test_alpha_matches_a_hand_computation(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tm, "_fetch", lambda tickers, s, e: series())
        row = tm.settle("T0", CUTOFF, cfg=cfg(tmp_path), now=AFTER)
        assert row is not None and row["status"] == "ok"
        assert row["raw_return"] == pytest.approx(110 / 100 - 1) and row["benchmark_return"] == pytest.approx(
            505 / 500 - 1
        )
        assert row["alpha"] == pytest.approx(0.10 - 0.01)
        assert (row["entry_session"], row["exit_session"]) == (SESSIONS[0], SESSIONS[-1])
        assert row["series"] == series()  # 받은 계열을 그대로 남긴다

    def test_a_zero_open_or_missing_bar_waits_then_gives_up(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tm, "_fetch", lambda tickers, s, e: series(t_open=0.0))
        assert tm.settle("T0", CUTOFF, cfg=cfg(tmp_path), now=AFTER) is None
        late = AFTER + timedelta(days=8)
        row = tm.settle("T0", CUTOFF, cfg=cfg(tmp_path), now=late)
        assert row is not None and row["status"] == "missing" and row["alpha"] is None

    @pytest.mark.parametrize("bad", [float("nan"), float("inf")])
    @pytest.mark.parametrize("who", ["T0", "SPY"])
    @pytest.mark.parametrize(("session", "col"), [(0, 0), (-1, 1)])  # 진입 시가 · 청산 종가
    def test_nonfinite_prices_never_settle_as_ok(self, monkeypatch, tmp_path, bad, who, session, col):
        """무한대 진입가는 수익률을 -100% 라는 유한값으로 만든다 — 가격 자체를 검사해야 한다."""
        s = series()
        s[who][SESSIONS[session]][col] = bad
        monkeypatch.setattr(tm, "_fetch", lambda tickers, a, e: s)
        assert tm.settle("T0", CUTOFF, cfg=cfg(tmp_path), now=AFTER) is None
        row = tm.settle("T0", CUTOFF, cfg=cfg(tmp_path), now=AFTER + timedelta(days=8))
        assert row is not None and row["status"] == "missing"

    def test_an_absent_bar_waits_like_a_zero_one(self, monkeypatch, tmp_path):
        s = series()
        del s["T0"][SESSIONS[0]]
        monkeypatch.setattr(tm, "_fetch", lambda tickers, a, e: s)
        assert tm.settle("T0", CUTOFF, cfg=cfg(tmp_path), now=AFTER) is None

    def test_an_early_close_is_recorded_at_its_real_time(self, monkeypatch, tmp_path):
        """2026-11-27 은 13:00 ET 마감(nyse.com) — 그 시각 + 버퍼에 정산이 열리고, 기록도 그 시각이다."""
        c = cfg(tmp_path)
        c["memory"]["early_closes"] = ["2026-11-27"]
        cut = datetime(2026, 11, 20, 9, 0, tzinfo=KST)  # 금 개장 진입 → 11-20, 23, 24, 25, 27
        assert tm.window(cut, 5)[-1] == date(2026, 11, 27)
        days = [d.isoformat() for d in tm.window(cut, 5)]
        s = {"T0": {days[0]: [1.0, 1.0], days[-1]: [1.0, 1.1]}, "SPY": {days[0]: [1.0, 1.0], days[-1]: [1.0, 1.0]}}
        monkeypatch.setattr(tm, "_fetch", lambda tickers, a, e: s)
        ny = timezone(timedelta(hours=-5))
        assert tm.settle("T0", cut, cfg=c, now=datetime(2026, 11, 27, 15, 59, tzinfo=ny)) is None
        row = tm.settle("T0", cut, cfg=c, now=datetime(2026, 11, 27, 16, 0, tzinfo=ny))
        assert row is not None and row["exit_close_at"] == "2026-11-27T18:00:00+00:00"

    @pytest.mark.parametrize(
        ("day", "utc"),
        [(date(2026, 10, 30), "2026-10-30T20:00:00+00:00"), (date(2026, 11, 2), "2026-11-02T21:00:00+00:00")],
    )
    def test_closes_follow_new_york_daylight_saving(self, day, utc):
        assert tm._close_at(day).astimezone(timezone.utc).isoformat() == utc

    def test_fetch_reads_open_and_close_from_one_download(self, monkeypatch):
        import sys
        from types import SimpleNamespace

        import pandas as pd

        calls = []

        def download(t, start, end, progress):
            calls.append((t, start, end))
            return pd.DataFrame(
                {"Open": [1.0, 2.0], "Close": [1.5, 2.5]}, index=pd.to_datetime(["2026-10-23", "2026-10-29"])
            )

        monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=download))
        got = tm._fetch(["T0"], date(2026, 10, 23), date(2026, 10, 29))
        assert got == {"T0": {"2026-10-23": [1.0, 1.5], "2026-10-29": [2.0, 2.5]}}
        assert calls == [("T0", "2026-10-23", "2026-10-30")]  # end 는 배타 — 마지막 날을 포함하려고 +1일
        monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=lambda *a, **k: pd.DataFrame()))
        assert tm._fetch(["T0"], date(2026, 10, 23), date(2026, 10, 29)) == {"T0": {}}


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "m.db"
    init_db(p)
    monkeypatch.setenv("NURI_ROLE", "production")
    return p


def _run(
    db,
    tmp_path,
    ticker,
    *,
    arm="B",
    rating="Overweight",
    cutoff=CUTOFF,
    run_hash=None,
    archive=True,
    late=False,
    experiment="exp",
    arm_hash="ah",
    batch_status="ok",
):
    run_hash = run_hash or f"{ticker}{arm}{cutoff.isoformat()}".ljust(16, "x")
    batch = ledger.start_batch(experiment, "c", db_path=db)
    if batch_status != "open":
        ledger.end_batch(batch, "c" if batch_status == "ok" else "other", db_path=db)
    run = {
        "arm": arm,
        "arm_hash": arm_hash,
        "ticker": ticker,
        "scored": True,
        "run_hash": run_hash,
        "packet_hashes": ["tp", "mp"],
        "view_hash": "vh",
        "calls": [],
        "budget_tokens": 14000,
        "rating": rating,
        "outcome": "verdict",
    }
    rid = ledger.record_run(
        run,
        experiment=experiment,
        batch_id=batch,
        cohort_date=cutoff.date().isoformat(),
        cutoff=cutoff.isoformat(),
        late=late,
        runtime={},
        canary_sha256="c",
        db_path=db,
    )
    if archive:
        d = tmp_path / "arch" / "runs"
        d.mkdir(parents=True, exist_ok=True)
        rendered = f"**Rating**: {rating}\n- [bull] target 42 reached"
        (d / f"{ticker}-{run_hash[:16]}.json").write_text(json.dumps({"run": {"rendered": rendered}}))
    return rid


class FakeGenerate:
    def __init__(self, text: object = "The call worked because 77 momentum held.\nLesson: weigh it."):
        self.text, self.prompts = text, []

    def __call__(self, prompt, *, cfg, num_predict, session=None):
        self.prompts.append(prompt)
        if isinstance(self.text, Exception):
            raise self.text
        return {"content_hash": "rc", "response": {"response": self.text}}


class TestSettleAndReflect:
    def test_one_return_per_ticker_and_cutoff_shared_by_both_arms(self, db, tmp_path, monkeypatch):
        _run(db, tmp_path, "T0", arm="A")
        _run(db, tmp_path, "T0", arm="B")
        monkeypatch.setattr(tm, "_fetch", lambda tickers, s, e: series())
        assert tm.settle_pending(cfg=cfg(tmp_path), now=AFTER, db_path=db) == 1
        assert tm.settle_pending(cfg=cfg(tmp_path), now=AFTER, db_path=db) == 0
        assert query("SELECT COUNT(*) AS n FROM thesis_returns", db_path=db)[0]["n"] == 1

    def test_a_window_not_yet_closed_is_left_for_later(self, db, tmp_path, monkeypatch):
        _run(db, tmp_path, "T0")
        monkeypatch.setattr(tm, "_fetch", lambda *a: pytest.fail("fetched too early"))
        assert tm.settle_pending(cfg=cfg(tmp_path), now=AFTER - timedelta(days=2), db_path=db) == 0

    def test_reflections_go_to_scored_b_calls_only_and_see_the_numbers(self, db, tmp_path, monkeypatch):
        _run(db, tmp_path, "T0", arm="A")
        rid_b = _run(db, tmp_path, "T0", arm="B")
        _run(db, tmp_path, "T1", arm="B", rating="REVIEW")
        monkeypatch.setattr(tm, "_fetch", lambda tickers, s, e: series() | {"T1": series()["T0"]})
        tm.settle_pending(cfg=cfg(tmp_path), now=AFTER, db_path=db)
        fake = FakeGenerate()
        monkeypatch.setattr(lc, "generate", fake)
        assert tm.reflect_pending(cfg=cfg(tmp_path), db_path=db) == {"written": 1, "no_archive": 0, "failed": 0}
        assert "Raw return over 5 trading days: +10.0%" in fake.prompts[0] and "Alpha vs SPY: +9.0%" in fake.prompts[0]
        assert "do not write numbers" in fake.prompts[0]
        row = query("SELECT * FROM thesis_reflections", db_path=db)[0]
        assert row["run_id"] == rid_b and "\n" not in row["reflection"]

    def test_a_missing_archive_and_a_failed_call_are_counted_not_invented(self, db, tmp_path, monkeypatch):
        _run(db, tmp_path, "T0", arm="B", archive=False)
        _run(db, tmp_path, "T1", arm="B")
        monkeypatch.setattr(tm, "_fetch", lambda tickers, s, e: series() | {"T1": series()["T0"]})
        tm.settle_pending(cfg=cfg(tmp_path), now=AFTER, db_path=db)
        monkeypatch.setattr(lc, "generate", FakeGenerate(requests.Timeout("x")))
        assert tm.reflect_pending(cfg=cfg(tmp_path), db_path=db) == {"written": 0, "no_archive": 1, "failed": 1}

    def test_off_production_nothing_is_written(self, db, tmp_path, monkeypatch):
        _run(db, tmp_path, "T0")
        monkeypatch.setattr(tm, "_fetch", lambda tickers, s, e: series())
        monkeypatch.setenv("NURI_ROLE", "dev")
        with pytest.raises(ledger.NotProductionError):
            tm.settle_pending(cfg=cfg(tmp_path), now=AFTER, db_path=db)
        assert query("SELECT COUNT(*) AS n FROM thesis_returns", db_path=db)[0]["n"] == 0


def _settled_with_reflection(
    db, tmp_path, monkeypatch, ticker, cutoff, *, fetched_at, created_at, late=False, batch_status="ok"
):
    """시계를 고정해 정산 수신 시각 · reflection 생성 시각을 정한다."""
    _run(db, tmp_path, ticker, cutoff=cutoff, late=late, batch_status=batch_status)
    monkeypatch.setattr(tm, "_fetch", lambda tickers, s, e: {ticker: series()["T0"], "SPY": series()["SPY"]})
    monkeypatch.setattr(tm, "window", lambda c, n: [date.fromisoformat(SESSIONS[0]), date.fromisoformat(SESSIONS[-1])])
    monkeypatch.setattr(tm, "kst_now", lambda: fetched_at)
    tm.settle_pending(cfg=cfg(tmp_path), now=fetched_at, db_path=db)
    monkeypatch.setattr(lc, "generate", FakeGenerate())
    monkeypatch.setattr(tm, "kst_now", lambda: created_at)
    tm.reflect_pending(cfg=cfg(tmp_path), db_path=db)


class TestPastContext:
    LATER = datetime(2026, 11, 10, 9, 0, tzinfo=KST)

    def _ok(self, db, tmp_path, monkeypatch, ticker="T0", late=False):
        _settled_with_reflection(
            db, tmp_path, monkeypatch, ticker, CUTOFF, fetched_at=AFTER, created_at=AFTER, late=late
        )

    def test_numbers_come_from_code_and_model_text_is_masked_and_quoted(self, db, tmp_path, monkeypatch):
        self._ok(db, tmp_path, monkeypatch)
        text = tm.past_context("T0", self.LATER, cfg=cfg(tmp_path), experiment="exp", arm_hash="ah", db_path=db)
        assert text.startswith("Past analyses of T0 (most recent first):")
        assert "| Overweight | raw +10.0% | alpha +9.0% | 5 sessions]" in text
        assert (
            "77" not in text
            and "42" not in text
            and '"The call worked because # momentum held. Lesson: weigh it."' in text
        )

    @pytest.mark.parametrize(
        ("table", "column"),
        [
            ("thesis_returns", "exit_close_at"),  # 청산 종가가 cutoff 뒤
            ("thesis_returns", "fetched_at"),  # 정산 수신이 cutoff 뒤
            ("thesis_reflections", "created_at"),  # reflection 이 cutoff 뒤
        ],
    )
    def test_each_visibility_time_alone_hides_the_entry(self, db, tmp_path, monkeypatch, table, column):
        """보이는 기억 하나를 만든 뒤 세 시각 중 하나만 cutoff 뒤로 옮긴다 — 조건 하나를 지우면 그 경우가 빨개진다."""
        self._ok(db, tmp_path, monkeypatch)
        assert (
            tm.past_context("T0", self.LATER, cfg=cfg(tmp_path), experiment="exp", arm_hash="ah", db_path=db) != ""
        )  # 양성 대조
        after = (self.LATER + timedelta(minutes=1)).astimezone(timezone.utc).isoformat()
        with get_db(db) as conn:
            conn.execute(f"UPDATE {table} SET {column} = ?", (after,))
        assert tm.past_context("T0", self.LATER, cfg=cfg(tmp_path), experiment="exp", arm_hash="ah", db_path=db) == ""

    @pytest.mark.parametrize(("experiment", "arm_hash"), [("pilot", "ah"), ("exp", "other")])
    def test_another_experiment_or_arm_definition_is_invisible(self, db, tmp_path, monkeypatch, experiment, arm_hash):
        """파일럿 교훈은 확증 실행에, 프롬프트가 바뀐 팔의 교훈은 새 팔에 섞이지 않는다 (#1981)."""
        self._ok(db, tmp_path, monkeypatch)
        assert tm.past_context("T0", self.LATER, cfg=cfg(tmp_path), experiment="exp", arm_hash="ah", db_path=db) != ""
        assert (
            tm.past_context("T0", self.LATER, cfg=cfg(tmp_path), experiment=experiment, arm_hash=arm_hash, db_path=db)
            == ""
        )

    @pytest.mark.parametrize("batch_status", ["canary_changed", "open"])
    def test_a_run_from_an_unverified_batch_never_becomes_memory(self, db, tmp_path, monkeypatch, batch_status):
        """끝 canary 가 바뀌었거나 끝나지 못한 배치 — reflection 도 기억도 없다 (#1981)."""
        _settled_with_reflection(
            db, tmp_path, monkeypatch, "T0", CUTOFF, fetched_at=AFTER, created_at=AFTER, batch_status=batch_status
        )
        assert query("SELECT COUNT(*) AS n FROM thesis_reflections", db_path=db)[0]["n"] == 0
        with get_db(db) as conn:
            conn.execute(
                "INSERT INTO thesis_reflections SELECT id, 'd', 'h', 'lesson', 'rc', '2000-01-01T00:00:00+00:00' "
                "FROM thesis_runs"
            )
        assert tm.past_context("T0", self.LATER, cfg=cfg(tmp_path), experiment="exp", arm_hash="ah", db_path=db) == ""

    def test_a_late_run_never_becomes_memory(self, db, tmp_path, monkeypatch):
        """진입 개장 뒤에 기록된 판정은 그날 가격을 봤을 수 있다 — reflection 도 기억도 없다."""
        self._ok(db, tmp_path, monkeypatch, late=True)
        assert query("SELECT COUNT(*) AS n FROM thesis_reflections", db_path=db)[0]["n"] == 0
        # reflection 이 어떤 경로로든 생겨도 기억에는 들어가지 않는다 — 조회 쪽 조건을 따로 잠근다
        with get_db(db) as conn:
            conn.execute(
                "INSERT INTO thesis_reflections SELECT id, 'd', 'h', 'lesson', 'rc', '2000-01-01T00:00:00+00:00' "
                "FROM thesis_runs"
            )
        assert tm.past_context("T0", self.LATER, cfg=cfg(tmp_path), experiment="exp", arm_hash="ah", db_path=db) == ""

    def test_another_tickers_lesson_appears_without_its_decision(self, db, tmp_path, monkeypatch):
        self._ok(db, tmp_path, monkeypatch, ticker="X1")
        text = tm.past_context("T0", self.LATER, cfg=cfg(tmp_path), experiment="exp", arm_hash="ah", db_path=db)
        assert text.startswith("Recent cross-ticker lessons:") and "| X1 | Overweight | raw +10.0%]" in text
        assert "decision" not in text and "Past analyses" not in text

    def test_same_ticker_and_cross_ticker_caps(self, db, tmp_path, monkeypatch):
        with get_db(db) as conn:
            conn.execute("INSERT INTO thesis_batches VALUES ('bk', 'exp', 's', 'c', 'e', 'c', 'ok')")
            for i in range(7):
                for t in ("T0", "X1"):
                    c = (CUTOFF - timedelta(days=30 * (i + 1))).isoformat()
                    conn.execute(
                        "INSERT INTO thesis_runs (cohort_date, arm, arm_hash, ticker, cutoff, late, scored, run_hash, "
                        "packet_hashes, view_hash, prompt_hashes, call_hashes, runtime, budget_tokens, rating, outcome, "
                        "experiment, batch_id) "
                        "VALUES (?, 'B', 'ah', ?, ?, 0, 1, ?, '[]', 'v', '[]', '[]', '{}', 14000, 'Hold', 'verdict', 'exp', 'bk')",
                        (c[:10], t, c, f"{t}{i}"),
                    )
                    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    conn.execute(
                        "INSERT INTO thesis_returns VALUES (?, ?, 'ok', 'a', 'b', '2000-01-01T00:00:00+00:00', 0.01, "
                        "'SPY', 0.0, 0.01, '{}', '2000-01-01T00:00:00+00:00')",
                        (t, c),
                    )
                    conn.execute(
                        "INSERT INTO thesis_reflections VALUES (?, 'd', 'h', 'lesson', 'rc', '2000-01-01T00:00:00+00:00')",
                        (rid,),
                    )
        text = tm.past_context("T0", self.LATER, cfg=cfg(tmp_path), experiment="exp", arm_hash="ah", db_path=db)
        assert text.count("| T0 |") == 5 and text.count("| X1 |") == 3

    def test_nothing_settled_gives_an_empty_block(self, db, tmp_path):
        assert tm.past_context("T0", self.LATER, cfg=cfg(tmp_path), experiment="exp", arm_hash="ah", db_path=db) == ""


def test_cli_settles_then_reflects(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(lc, "load_config", lambda: cfg(tmp_path))
    monkeypatch.setattr(tm, "settle_pending", lambda **kw: 2)
    monkeypatch.setattr(tm, "reflect_pending", lambda **kw: {"written": 1, "no_archive": 0, "failed": 0})
    assert tm.main([]) == 0
    assert json.loads(capsys.readouterr().out) == {"settled": 2, "written": 1, "no_archive": 0, "failed": 0}

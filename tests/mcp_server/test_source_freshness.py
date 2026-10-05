"""nuri-read 의 출처 선택과 신선도 판정 (#1617).

개발 머신에서 MCP 가 5주 전에 멈춘 로컬 DB 를 현재처럼 내던 결함의 잠금이다.
- 출처 우선순위: NURI_DB_PATH > 최신 replica > 기본 DB
- stale 판정은 출처 종류가 아니라 데이터(VIX · 인증 · 후보 run 날짜)와 replica 파일 나이로 한다
- 응답에 경로가 없다 — replica 파일명에 mini 호스트명이 들어간다

시각은 전부 `now` 로 주입한다 — `date.today()` 를 쓰면 KST 달력 판정이 UTC CI 에서 하루씩 어긋난다.
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from nuri.core.db import get_db, init_db
from nuri.core.timezone import KST
from nuri.mcp import source

#: 2026-10-06 12:00 KST
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=KST).timestamp()
TODAY = date(2026, 10, 6)


def _ago(days: int) -> str:
    return (TODAY - timedelta(days=days)).isoformat()


def _seed(path: Path, vix: str, cert: str | None = None, run: str | None = None, mtime: float = NOW) -> Path:
    """세 산출물을 심는다. cert/run 을 안 주면 vix 와 같은 날짜."""
    init_db(path)
    with get_db(path) as conn:
        conn.execute("INSERT INTO macro (indicator, date, value, source) VALUES ('vix', ?, 15.0, 'cboe')", (vix,))
        conn.execute(
            "INSERT INTO certifications (timestamp, certified, score, total_conditions, passed, failed, warnings,"
            " conditions_json) VALUES (?, 0, 0.5, 1, 0, 1, 0, '[]')",
            (f"{cert or vix}T22:00:00+09:00",),
        )
        conn.execute("INSERT INTO candidate_runs (run_date) VALUES (?)", (run or vix,))
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture()
def no_env(monkeypatch):
    monkeypatch.delenv("NURI_DB_PATH", raising=False)


class TestResolveSource:
    def test_env_override_wins(self, tmp_path, monkeypatch):
        replicas = tmp_path / "replicas"
        replicas.mkdir()
        (replicas / "a.db").write_bytes(b"")
        monkeypatch.setenv("NURI_DB_PATH", str(tmp_path / "explicit.db"))
        src = source.resolve_source(replicas)
        assert (src.kind, src.path) == ("env_override", tmp_path / "explicit.db")

    @pytest.mark.usefixtures("no_env")
    def test_newest_replica_is_chosen(self, tmp_path):
        replicas = tmp_path / "replicas"
        replicas.mkdir()
        old, new = replicas / "old.db", replicas / "new.db"
        old.write_bytes(b"")
        new.write_bytes(b"")
        os.utime(old, (time.time() - 7200, time.time() - 7200))
        src = source.resolve_source(replicas)
        assert (src.kind, src.path) == ("replica", new)

    @pytest.mark.usefixtures("no_env")
    def test_replica_vanishing_during_lookup_is_skipped(self, tmp_path):
        """glob 과 stat 사이에 사라진 파일 — 깨진 symlink 로 재현한다. 기동을 막지 않는다 (Codex P3)."""
        replicas = tmp_path / "replicas"
        replicas.mkdir()
        (replicas / "gone.db").symlink_to(tmp_path / "nowhere.db")
        (replicas / "ok.db").write_bytes(b"")
        assert source.resolve_source(replicas) == source.Source(replicas / "ok.db", "replica")

    @pytest.mark.usefixtures("no_env")
    def test_falls_back_to_default_db_and_says_so(self, tmp_path):
        src = source.resolve_source(tmp_path / "absent")
        assert src.kind == "local"
        assert src.path == source.DB_PATH


class TestFreshness:
    def test_fresh_replica_is_not_stale(self, tmp_path):
        db = _seed(tmp_path / "r.db", TODAY.isoformat())
        out = source.freshness(source.Source(db, "replica"), now=NOW)
        assert out["stale"] is False, out["stale_reasons"]
        assert out["latest"] == {
            "vix_date": TODAY.isoformat(),
            "certification_at": f"{TODAY.isoformat()}T22:00:00+09:00",
            "candidate_run_date": TODAY.isoformat(),
        }

    def test_replica_age_boundary(self, tmp_path):
        hours = source.REPLICA_STALE_HOURS
        at = _seed(tmp_path / "at.db", TODAY.isoformat(), mtime=NOW - hours * 3600)
        over = _seed(tmp_path / "over.db", TODAY.isoformat(), mtime=NOW - (hours + 0.1) * 3600)
        assert source.freshness(source.Source(at, "replica"), now=NOW)["stale"] is False
        out = source.freshness(source.Source(over, "replica"), now=NOW)
        assert out["stale"] is True
        assert any("replica not updated" in r for r in out["stale_reasons"])

    def test_old_local_file_is_not_judged_by_file_age(self, tmp_path):
        """mini 에서는 local 이 원장 자체 — 파일 나이 상한은 replica 에만 건다."""
        db = _seed(tmp_path / "ledger.db", TODAY.isoformat(), mtime=NOW - 100 * 3600)
        out = source.freshness(source.Source(db, "local"), now=NOW)
        assert out["stale"] is False, out["stale_reasons"]
        assert out["note"]

    def test_frozen_data_is_stale_even_in_a_fresh_file(self, tmp_path):
        """개발 DB 사고의 형태 — 파일은 방금 만졌지만 데이터는 5주 전."""
        db = _seed(tmp_path / "local.db", _ago(38))
        out = source.freshness(source.Source(db, "local"), now=NOW)
        assert out["stale"] is True
        assert any("VIX is 38 days old" in r for r in out["stale_reasons"])

    @pytest.mark.parametrize(
        ("field", "label", "limit"),
        [
            ("vix", "VIX", source.DATA_STALE_DAYS),
            ("cert", "certification", source.DATA_STALE_DAYS),
            ("run", "candidate run", source.CANDIDATE_RUN_STALE_DAYS),
        ],
    )
    def test_each_output_has_its_own_age_limit(self, tmp_path, field, label, limit):
        """Codex P1 — macro 는 매시간 돌아 VIX 는 늘 새롭다. premarket_brief 가 멈추면 인증·후보만
        낡으므로 셋을 각각 판정해야 한다. 경계: 상한 일수는 정상, 하루 더는 stale."""
        fresh = TODAY.isoformat()
        for days, expect in ((limit, False), (limit + 1, True)):
            dates = {"vix": fresh, "cert": fresh, "run": fresh, field: _ago(days)}
            db = _seed(tmp_path / f"{field}_{days}.db", dates["vix"], dates["cert"], dates["run"])
            out = source.freshness(source.Source(db, "replica"), now=NOW)
            assert out["stale"] is expect, (days, out["stale_reasons"])
            if expect:
                assert out["stale_reasons"] == [f"latest {label} is {days} days old (> {limit})"]

    def test_day_count_uses_the_kst_calendar(self, tmp_path, monkeypatch):
        """2026-10-06 01:00 KST = 10-05 16:00 UTC. 09-30 데이터는 KST 로 6일(stale), 머신 로컬
        시간대가 UTC 면 5일(정상)로 갈린다 — 시간대를 UTC 로 강제해 로컬 달력 회귀를 잡는다."""
        db = _seed(tmp_path / "r.db", _ago(6), cert=_ago(1), run=_ago(1))  # VIX 만 판정을 가르게
        now = datetime(2026, 10, 6, 1, 0, tzinfo=KST).timestamp()
        with monkeypatch.context() as m:
            m.setenv("TZ", "UTC")
            time.tzset()
            try:
                out = source.freshness(source.Source(db, "replica"), now=now)
            finally:
                m.undo()
                time.tzset()
        assert out["stale"] is True, out["stale_reasons"]

    @pytest.mark.parametrize(
        ("vix", "run", "at", "expect"),
        [
            # 미국 월요일 휴장(2026-10-12 콜럼버스의 날) — 수요일 KST 에 금요일 VIX 는 정상
            ("2026-10-09", "2026-10-13", datetime(2026, 10, 14, 12, 0), False),
            # 월요일 브리프(22시 KST) 전에는 금요일 run 이 최신 — 정상
            ("2026-10-02", "2026-10-02", datetime(2026, 10, 5, 21, 0), False),
            # 월요일 브리프를 놓쳤다 — 화요일 새벽에 금요일 run 은 stale
            ("2026-10-02", "2026-10-02", datetime(2026, 10, 6, 1, 0), True),
            # Codex 재현: 수요일 밤, VIX·인증은 새롭고 후보 run 만 금요일 — stale
            ("2026-10-06", "2026-10-02", datetime(2026, 10, 7, 23, 30), True),
        ],
    )
    def test_calendar_cases_pin_the_limits(self, tmp_path, vix, run, at, expect):
        """경계 테스트는 상수에서 값을 끌어와 상수를 바꿔도 통과한다 — 실제 달력 사례로 값을 잠근다."""
        now = at.replace(tzinfo=KST).timestamp()
        db = _seed(tmp_path / "r.db", vix, cert=vix, run=run, mtime=now)
        out = source.freshness(source.Source(db, "replica"), now=now)
        assert out["stale"] is expect, out["stale_reasons"]

    def test_empty_db_is_stale_not_fresh(self, tmp_path):
        init_db(tmp_path / "empty.db")
        out = source.freshness(source.Source(tmp_path / "empty.db", "replica"), now=time.time())
        assert out["stale"] is True
        assert {"no VIX in the source", "no certification in the source"} <= set(out["stale_reasons"])

    def test_truncated_replica_is_reported_not_raised(self, tmp_path):
        """`rsync --partial` 이 끊기면 실제 파일명에 반쪽 파일이 남는다 — 예외로 서버 기동을 막지
        말고 stale 로 보고한다 (Codex P2)."""
        from nuri.mcp import server

        db = _seed(tmp_path / "r.db", TODAY.isoformat())
        data = db.read_bytes()
        db.write_bytes(data[: len(data) // 2])
        os.utime(db, (NOW, NOW))
        out = source.freshness(source.Source(db, "replica"), now=NOW)
        assert out["stale"] is True
        assert any("unreadable (DatabaseError)" in r for r in out["stale_reasons"]), out["stale_reasons"]
        assert server._schema_lag(db)[0] == 0

    def test_missing_file_is_stale(self, tmp_path):
        out = source.freshness(source.Source(tmp_path / "gone.db", "replica"), now=NOW)
        assert out["stale"] is True
        assert out["stale_reasons"] == ["source file missing"]

    def test_response_carries_no_path(self, tmp_path):
        db = _seed(tmp_path / "portfolio_host-Macmini.db", TODAY.isoformat())
        out = source.freshness(source.Source(db, "replica"), now=NOW)
        assert str(tmp_path) not in repr(out) and "Macmini" not in repr(out)
        assert set(out) == {"source", "file_age_hours", "latest", "stale", "stale_reasons", "note"}


class TestServerReadsTheResolvedSource:
    """도구가 `resolve_source()` 를 실제로 쓰는지 — 라이브 테스트는 NURI_DB_PATH 를 주므로
    기본 DB 와 경로가 같아 이 배선을 못 잠근다."""

    def test_every_db_tool_reads_the_resolved_source(self, tmp_path, monkeypatch):
        from nuri.mcp import server

        db = _seed(tmp_path / "replica.db", "2026-09-15")  # 실 replica 와 겹치지 않는 날짜
        monkeypatch.setattr(source, "resolve_source", lambda *a, **k: source.Source(db, "replica"))

        assert server.macro_facts()["vix"]["date"] == "2026-09-15"
        assert server.buy_candidates()["run"]["run_date"] == "2026-09-15"
        assert [r["score"] for r in server.siege_status()] == [0.5]
        assert server.data_freshness()["source"] == "replica"

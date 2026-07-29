"""고아 agent run 정리 테스트 (#942).

Gotcha-Test Pair:
정리의 목적은 **알림을 끄는 것이 아니라 원장을 사실대로 만드는 것**이다. 그래서
두 가지를 잠근다.

1. `finished_at` 은 `started_at` 이어야 한다. `datetime('now')` 로 찍으면 40일 전에
   죽은 run 이 40일짜리 duration 을 가진 것처럼 보인다 — 알림은 꺼지고 원장은
   거짓말을 하게 된다. 정확히 이게 "고쳤다" 와 "숨겼다" 의 차이다.
2. 행은 남아야 한다 (DELETE 금지). 그때 완료를 못 한 건 사실이고, 지우면 왜
   비었는지 아무도 모른다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nuri.core.db import get_db, init_db, query
from scripts.ops.reap_orphan_runs import REAP_REASON, find_orphans, main, reap


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "reap.db"
    init_db(path)
    return path


def _seed_run(db_path: Path, run_id: str, actor: str, *, hours_ago: float, finished: bool):
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT INTO agent_run_ledger (run_id, actor_name, status, started_at, finished_at)
               VALUES (?, ?, ?, datetime('now', ?), ?)""",
            (
                run_id,
                actor,
                "finished" if finished else "started",
                f"-{int(hours_ago * 60)} minutes",
                "2026-01-01 00:00:00" if finished else None,
            ),
        )


class TestFindOrphans:
    def test_only_stale_unfinished_rows(self, db_path):
        _seed_run(db_path, "old-orphan", "dispatcher", hours_ago=100, finished=False)
        _seed_run(db_path, "fresh-running", "dispatcher", hours_ago=0.5, finished=False)
        _seed_run(db_path, "completed", "dispatcher", hours_ago=100, finished=True)

        found = {o["run_id"] for o in find_orphans(24, db_path=db_path)}
        assert found == {"old-orphan"}


class TestReapKeepsTheLedgerHonest:
    def test_finished_at_is_started_at_not_now(self, db_path):
        """duration 을 날조하지 않는다 — 이게 '고쳤다' 와 '숨겼다' 의 차이다."""
        _seed_run(db_path, "r1", "dispatcher", hours_ago=960, finished=False)
        reap(find_orphans(24, db_path=db_path), db_path=db_path)

        row = dict(
            query("SELECT started_at, finished_at, status FROM agent_run_ledger WHERE run_id='r1'", db_path=db_path)[0]
        )
        assert row["status"] == "timeout"
        assert row["finished_at"] == row["started_at"], (
            "finished_at 이 now() 로 찍히면 40일짜리 duration 이 생겨 원장이 거짓말을 한다"
        )

    def test_row_is_kept_not_deleted(self, db_path):
        _seed_run(db_path, "r1", "dispatcher", hours_ago=960, finished=False)
        reap(find_orphans(24, db_path=db_path), db_path=db_path)

        rows = query("SELECT error_message FROM agent_run_ledger WHERE run_id='r1'", db_path=db_path)
        assert len(rows) == 1, "행을 지우면 왜 비었는지 아무도 모른다"
        assert REAP_REASON in dict(rows[0])["error_message"]

    def test_status_is_timeout_not_failed(self, db_path):
        """실패했다는 증거는 없다 — 완료를 보고하지 않았을 뿐이다."""
        _seed_run(db_path, "r1", "dispatcher", hours_ago=960, finished=False)
        reap(find_orphans(24, db_path=db_path), db_path=db_path)
        assert (
            dict(query("SELECT status FROM agent_run_ledger WHERE run_id='r1'", db_path=db_path)[0])["status"]
            == "timeout"
        )

    def test_running_job_is_untouched(self, db_path):
        """지금 돌고 있는 run 을 마감해 버리면 진짜 실행을 죽은 것으로 만든다."""
        _seed_run(db_path, "live", "dispatcher", hours_ago=0.5, finished=False)
        reap(find_orphans(24, db_path=db_path), db_path=db_path)

        row = dict(query("SELECT status, finished_at FROM agent_run_ledger WHERE run_id='live'", db_path=db_path)[0])
        assert row["status"] == "started" and row["finished_at"] is None


class TestCli:
    def test_dry_run_does_not_write(self, db_path, capsys):
        _seed_run(db_path, "r1", "dispatcher", hours_ago=960, finished=False)
        assert main(["--db-path", str(db_path)]) == 0
        assert "dry-run" in capsys.readouterr().out
        assert (
            dict(query("SELECT status FROM agent_run_ledger WHERE run_id='r1'", db_path=db_path)[0])["status"]
            == "started"
        )

    def test_apply_writes(self, db_path, capsys):
        _seed_run(db_path, "r1", "dispatcher", hours_ago=960, finished=False)
        assert main(["--db-path", str(db_path), "--apply"]) == 0
        assert "1건 timeout" in capsys.readouterr().out

    def test_no_orphans_is_clean_exit(self, db_path, capsys):
        assert main(["--db-path", str(db_path)]) == 0
        assert "고아 run 없음" in capsys.readouterr().out

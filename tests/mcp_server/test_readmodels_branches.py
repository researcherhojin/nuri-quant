"""read model 의 run 선택 분기 — 날짜를 지정하면 그 날의 run, 없으면 빈 응답."""

from __future__ import annotations

import pytest

from nuri.core.db import get_db, init_db
from nuri.mcp import readmodels


@pytest.fixture()
def two_runs(tmp_path):
    path = tmp_path / "t.db"
    init_db(path)
    with get_db(path) as conn:
        for run_date, n in (("2026-08-28", 1), ("2026-08-29", 2)):
            conn.execute(
                "INSERT INTO candidate_runs (run_date, regime, vix, threshold, blocked_reason,"
                " n_scored, n_qualified, n_emitted, n_skipped) VALUES (?, 'bull_low_vol', 15.2, 0.6, NULL, 10, ?, ?, 0)",
                (run_date, n, n),
            )
    return path


def test_a_requested_run_date_returns_that_run_not_the_latest(two_runs):
    out = readmodels.latest_buy_candidates(run_date="2026-08-28", db_path=two_runs)

    assert (out["run"]["run_date"], out["run"]["n_emitted"]) == ("2026-08-28", 1)


def test_a_run_date_without_a_run_is_an_empty_answer(two_runs):
    assert readmodels.latest_buy_candidates(run_date="2026-08-30", db_path=two_runs) == {"run": None, "candidates": []}

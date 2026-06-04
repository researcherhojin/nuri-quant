"""Lock-tests for `save_backtest` (nuri/core/db/research_ops.py — P1a backtests writer).

backtests 테이블은 그동안 writer 부재(Phase 3 placeholder)였다. save_backtest 가 채운다.
- round-trip known-answer: 기록한 값이 그대로 읽힌다
- params dict ↔ JSON round-trip / None → 빈 객체
- created_at None → KST 자동 스탬프, 명시 → 보존
- lastrowid 반환 (AUTOINCREMENT)
- db_path 격리
"""

from __future__ import annotations

import json

import pytest

from nuri.core.db import init_db, query, save_backtest


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "bt.db"
    init_db(p)
    return p


def _save_minimal(db_path, **overrides):
    kwargs = dict(
        strategy_id="S",
        start_date="2026-01-01",
        end_date="2026-02-01",
        total_return=1.0,
        sharpe=0.5,
        max_drawdown=-2.0,
        win_rate=50.0,
        db_path=db_path,
    )
    kwargs.update(overrides)
    return save_backtest(**kwargs)


class TestSaveBacktest:
    def test_round_trip_known_values(self, db_path):
        bid = save_backtest(
            strategy_id="Momentum Top-5",
            start_date="2026-01-02",
            end_date="2026-03-31",
            total_return=12.34,
            sharpe=1.45,
            max_drawdown=-8.7,
            win_rate=55.5,
            params={"period": "3mo", "top_n": 5, "rebalance_days": 20},
            db_path=db_path,
        )
        assert bid == 1  # 첫 행 AUTOINCREMENT

        rows = query("SELECT * FROM backtests", db_path=db_path)
        assert len(rows) == 1
        r = rows[0]
        assert r["strategy_id"] == "Momentum Top-5"
        assert r["start_date"] == "2026-01-02"
        assert r["end_date"] == "2026-03-31"
        assert r["total_return"] == 12.34
        assert r["sharpe"] == 1.45
        assert r["max_drawdown"] == -8.7
        assert r["win_rate"] == 55.5

    def test_params_json_round_trip(self, db_path):
        _save_minimal(db_path, params={"top_n": 7, "nested": {"a": 1}})
        raw = query("SELECT params FROM backtests", db_path=db_path)[0]["params"]
        assert json.loads(raw) == {"top_n": 7, "nested": {"a": 1}}

    def test_none_params_stored_as_empty_object(self, db_path):
        _save_minimal(db_path)
        assert query("SELECT params FROM backtests", db_path=db_path)[0]["params"] == "{}"

    def test_created_at_auto_kst_stamp(self, db_path):
        _save_minimal(db_path)
        ca = query("SELECT created_at FROM backtests", db_path=db_path)[0]["created_at"]
        # 'YYYY-MM-DD HH:MM:SS' (kst_now, datetime.now 금지 invariant)
        assert ca is not None
        assert ca[:4].isdigit() and ca[4] == "-"

    def test_created_at_explicit_preserved(self, db_path):
        _save_minimal(db_path, created_at="2020-01-01 00:00:00")
        ca = query("SELECT created_at FROM backtests", db_path=db_path)[0]["created_at"]
        assert ca == "2020-01-01 00:00:00"

    def test_autoincrement_ids(self, db_path):
        ids = [_save_minimal(db_path, strategy_id=f"S{i}", total_return=float(i)) for i in range(3)]
        assert ids == [1, 2, 3]

    def test_float_coercion(self, db_path):
        # int 입력도 REAL 컬럼에 float 로 저장
        _save_minimal(db_path, total_return=10, sharpe=1, max_drawdown=-3, win_rate=60)
        r = query("SELECT * FROM backtests", db_path=db_path)[0]
        assert r["total_return"] == 10.0
        assert isinstance(r["total_return"], float)

    def test_non_finite_metrics_coerced_to_null(self, db_path):
        """thin-data 백테스트(0 trades) → inf Sharpe / nan MDD. 창고엔 NULL 로 저장.

        비유한값을 그대로 두면 JSON 직렬화가 Infinity/NaN(invalid) 토큰을 내보내 읽기
        엔드포인트를 깨뜨린다. writer 경계에서 NULL 로 차단 (SQLite NaN→NULL 묵시 변환 비의존).
        """
        _save_minimal(
            db_path,
            total_return=1.5,  # 유한값은 보존
            sharpe=float("inf"),
            max_drawdown=float("nan"),
            win_rate=float("-inf"),
        )
        r = query("SELECT * FROM backtests", db_path=db_path)[0]
        assert r["total_return"] == 1.5
        assert r["sharpe"] is None
        assert r["max_drawdown"] is None
        assert r["win_rate"] is None

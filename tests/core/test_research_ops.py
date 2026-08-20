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


class TestTheRevisionIsRecordedButNeverInvented:
    """`_code_rev` 는 알 수 있으면 기록하고, 모르면 **None** 이다 (#1115).

    지어내면 귀속이 거짓이 된다 — 철회된 산출물을 구분하려고 붙이는 필드인데 그게 부정확하면
    있느니만 못하다. git 이 없는 설치(tarball, 컨테이너)에서 조용히 None 이어야 한다.
    """

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        """`_code_rev` 는 프로세스당 1회 조회 후 캐시한다 — 테스트마다 비운다.

        안 비우면 첫 테스트가 캐시한 값이 나머지 전부의 답이 되어, 실제 분기를 한 번도
        안 타면서 초록이 된다.
        """
        import nuri.core.db.research_ops as ops

        ops._CODE_REV_CACHE = ops._CODE_REV_UNSET
        yield
        ops._CODE_REV_CACHE = ops._CODE_REV_UNSET

    def test_the_revision_is_looked_up_once_per_process(self, monkeypatch):
        """`save_backtest` 를 여러 번 불러도 git 조회는 1회다 (Codex P2).

        `variant_walkforward` · `exit_walkforward` 는 루프 안에서 행마다 저장한다. 캐시가
        없으면 행 수만큼 `git status --porcelain`(워크트리 전체 스캔)이 반복된다.
        """
        import subprocess
        from types import SimpleNamespace

        import nuri.core.db.research_ops as ops

        calls = []

        def _fake(cmd, **_k):
            calls.append(cmd)
            return SimpleNamespace(stdout="abc1234\n" if "rev-parse" in cmd else "")

        monkeypatch.setattr(subprocess, "run", _fake)

        assert [ops._code_rev() for _ in range(5)] == ["abc1234"] * 5
        assert len(calls) == 2, f"git 을 {len(calls)}회 불렀다 — 캐시가 안 먹는다"

    def test_an_empty_rev_is_not_recorded_as_a_revision(self, monkeypatch):
        """`git rev-parse` 가 성공했는데 빈 문자열이면 리비전이 아니다.

        빈 문자열을 그대로 넣으면 `code_rev: ""` 인 행이 생겨, 미귀속(None)과도 다르고
        귀속(SHA)과도 다른 제3의 상태가 원장에 남는다.
        """
        import subprocess
        from types import SimpleNamespace

        import nuri.core.db.research_ops as ops

        monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: SimpleNamespace(stdout="  \n"))

        assert ops._code_rev() is None

    def test_an_unreadable_status_still_yields_the_sha(self, monkeypatch):
        """`git status` 만 실패하면 SHA 는 살린다 — dirty 여부만 모르는 것이지 리비전은 안다.

        여기서 None 으로 떨어뜨리면 알고 있는 정보를 버리게 된다.
        """
        import subprocess
        from types import SimpleNamespace

        import nuri.core.db.research_ops as ops

        def _fake(cmd, **_k):
            if "rev-parse" in cmd:
                return SimpleNamespace(stdout="abc1234\n")
            raise subprocess.SubprocessError("status unavailable")

        monkeypatch.setattr(subprocess, "run", _fake)

        assert ops._code_rev() == "abc1234", "status 실패가 SHA 까지 날렸다"

    def test_a_missing_git_yields_none_not_a_guess(self, monkeypatch):
        import subprocess

        import nuri.core.db.research_ops as ops

        def _no_git(*_a, **_k):
            raise FileNotFoundError("git")

        monkeypatch.setattr(subprocess, "run", _no_git)

        assert ops._code_rev() is None

    def test_a_dirty_tree_is_marked(self, monkeypatch):
        """dirty 트리에서 나온 숫자를 커밋된 코드의 산출물로 읽으면 안 된다."""
        import subprocess
        from types import SimpleNamespace

        import nuri.core.db.research_ops as ops

        calls = []

        def _fake(cmd, **_k):
            calls.append(cmd)
            if "rev-parse" in cmd:
                return SimpleNamespace(stdout="abc1234\n")
            return SimpleNamespace(stdout=" M nuri/foo.py\n")

        monkeypatch.setattr(subprocess, "run", _fake)

        assert ops._code_rev() == "abc1234-dirty"

    def test_a_clean_tree_is_the_bare_sha(self, monkeypatch):
        import subprocess
        from types import SimpleNamespace

        import nuri.core.db.research_ops as ops

        def _fake(cmd, **_k):
            return SimpleNamespace(stdout="abc1234\n" if "rev-parse" in cmd else "")

        monkeypatch.setattr(subprocess, "run", _fake)

        assert ops._code_rev() == "abc1234"

    def test_the_row_carries_it(self, db_path):
        import json

        save_backtest(
            strategy_id="attributed",
            start_date="2026-01-01",
            end_date="2026-02-01",
            total_return=1.0,
            sharpe=1.0,
            max_drawdown=-1.0,
            win_rate=50.0,
            db_path=db_path,
        )
        params = json.loads(query("SELECT params FROM backtests", db_path=db_path)[0]["params"])

        assert params.get("code_rev"), "행이 산출 코드를 특정하지 못한다"


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
        """호출자 params 는 손상 없이 왕복한다 — `code_rev` 만 덧붙는다 (#1115)."""
        _save_minimal(db_path, params={"top_n": 7, "nested": {"a": 1}})
        raw = query("SELECT params FROM backtests", db_path=db_path)[0]["params"]
        stored = json.loads(raw)
        assert {k: v for k, v in stored.items() if k != "code_rev"} == {"top_n": 7, "nested": {"a": 1}}

    def test_none_params_still_records_the_revision(self, db_path):
        """params 를 안 넘겨도 귀속은 붙는다 — 빈 dict 로 남으면 그 행은 영영 미귀속이다."""
        _save_minimal(db_path)
        stored = json.loads(query("SELECT params FROM backtests", db_path=db_path)[0]["params"])
        assert set(stored) == {"code_rev"}

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

    def test_none_metrics_stored_as_null(self, db_path):
        # walk-forward 는 total_return/win_rate 미산출 → None 전달 시 NULL 저장 (inf 와 구분)
        _save_minimal(db_path, total_return=None, sharpe=0.5, max_drawdown=-0.1, win_rate=None)
        r = query("SELECT * FROM backtests", db_path=db_path)[0]
        assert r["total_return"] is None
        assert r["win_rate"] is None
        assert r["sharpe"] == 0.5

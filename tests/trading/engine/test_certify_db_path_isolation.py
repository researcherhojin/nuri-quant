"""`certify(db_path=X)` 는 X **만** 읽어야 한다 (audit 무결성).

왜 이게 중요한가
----------------
`_capture_snapshot()` 의 docstring 은 "Single-source-of-truth" 와 "audit row
metadata 와 gate eval state 가 identically 일치 (R2/R4 rigor)" 를 주장한다.
그런데 2026-08-14 까지 `db_path` 를 `_read_portfolio_raw` 에만 넘기고
`_classify_regime_fresh()` 와 `analyze_portfolio()` 에는 안 넘겼다. 즉 스냅샷이
**절반은 지정 DB, 절반은 기본 DB** 에서 왔고, 그 위에서 계산한 감사 해시는
어느 쪽 상태도 정확히 대표하지 않았다.

프로덕션은 `db_path=None` 이라 지금껏 무해했다. 문제는 **`db_path` 를 넘기는
순간**이고, 다음 세션 최우선 항목인 replay pack(과거 날짜 고정 스냅샷)이
정확히 그 호출 형태다 — 고치지 않으면 replay 스냅샷에 오늘의 프로덕션 상태가
조용히 섞인다.

이 테스트는 값이 아니라 **접근 경로**를 잠근다. 값 비교로는 두 DB 가 우연히
같은 답을 줄 때 통과해 버린다.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

REAL_DB = Path(__file__).resolve().parents[3] / "data" / "portfolio.db"


class TestCertifyReadsOnlyTheGivenDb:
    @staticmethod
    def _seed(db_path) -> None:
        """보유 1종목 + 가격 + 환율. **비면 조기 반환**이라 경로를 안 태운다.

        빈 DB 로 두면 `analyze_portfolio` 이 `holdings.empty` 에서 바로 나가고
        `get_exchange_rate()` 는 호출조차 안 된다 — 그 배선을 되돌려도 테스트가
        통과한다(2026-08-14 실측). 잠금이 되려면 전 경로가 실행돼야 한다.
        """
        from nuri.core.db import get_db

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test", "AAA", 10, 100.0, "USD", "Technology"),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("AAA", "2026-08-14", 100.0, 101.0, 99.0, 100.5, 1000),
            )
            conn.execute(
                "INSERT INTO macro (indicator, date, value, source) VALUES (?, ?, ?, ?)",
                ("usd_krw", "2026-08-14", 1400.0, "test"),
            )

    def test_capture_snapshot_touches_no_other_database(self, db_path, monkeypatch):
        """스냅샷을 뜨는 동안 열린 DB 파일이 `db_path` 하나뿐이어야 한다."""
        import nuri.core.db.connection as conn_mod
        from nuri.trading.engine import certification as cert

        self._seed(db_path)

        opened: list[str] = []
        original = conn_mod.sqlite3.connect

        def spy(path, *args, **kwargs):
            opened.append(str(path))
            return original(path, *args, **kwargs)

        monkeypatch.setattr(conn_mod.sqlite3, "connect", spy)
        cert._capture_snapshot(db_path=db_path)

        others = {p for p in opened if p != str(db_path)}
        assert not others, f"db_path 외의 DB 를 열었다: {sorted(others)}"
        assert opened, "아무 DB 도 안 열었다 — 스파이가 안 걸린 것"

    def test_the_spy_would_notice_a_leak(self, db_path, monkeypatch):
        """스파이가 실제로 감지하는지 — 0건을 훑고 통과하면 의미가 없다."""
        import nuri.core.db.connection as conn_mod

        opened: list[str] = []
        original = conn_mod.sqlite3.connect

        def spy(path, *args, **kwargs):
            opened.append(str(path))
            return original(path, *args, **kwargs)

        monkeypatch.setattr(conn_mod.sqlite3, "connect", spy)
        other = db_path.parent / "other.db"
        sqlite3.connect(str(other)).close()
        assert str(other) in opened

    @pytest.mark.parametrize("fn_name", ["_classify_regime_fresh"])
    def test_snapshot_helpers_accept_db_path(self, fn_name: str) -> None:
        """시그니처가 좁아지면 배선이 조용히 끊긴다."""
        import inspect

        from nuri.trading.engine import certification as cert

        assert "db_path" in inspect.signature(getattr(cert, fn_name)).parameters

    def test_analyze_portfolio_accepts_db_path(self) -> None:
        import inspect

        from nuri.analysis.portfolio import analyze_portfolio, get_exchange_rate

        assert "db_path" in inspect.signature(analyze_portfolio).parameters
        assert "db_path" in inspect.signature(get_exchange_rate).parameters


class TestGatesReadOnlyTheGivenDbOutsideCertify:
    """게이트를 `certify()` **밖에서** 직접 부를 때도 `db_path` 만 읽어야 한다.

    위 클래스는 `_capture_snapshot()` 경로를 덮는다. 그 경로에서는 `CertSnapshot`
    ContextVar 가 세팅돼 있어서 `_snapshot_portfolio()` / `_current_regime()` 이
    DB 를 아예 안 읽고 스냅샷을 반환한다 — 그래서 그 둘의 `db_path` 배선이
    빠져 있어도 위 테스트가 전부 통과했다 (2026-08-14 실측: 배선 6곳을 되돌려도
    `tests/trading/engine/` + `tests/llm/` 611개가 초록이었다).

    스냅샷이 없는 경로 — 테스트·감사 헬퍼가 게이트를 직접 부르는 형태 — 만이
    그 배선을 실제로 실행한다. AST 스윕(`tests/core/test_db_path_forwarding.py`)
    은 구조만 보므로, 동작으로 잠그는 건 여기다.
    """

    @staticmethod
    def _seed_violating_position(db_path) -> None:
        """단일 종목이 포트폴리오의 100% — position_limit 를 확실히 위반시킨다."""
        from nuri.core.db import get_db

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test", "AAA", 100, 100.0, "USD", "Technology"),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("AAA", "2026-08-14", 100.0, 101.0, 99.0, 100.0, 1000),
            )
            conn.execute(
                "INSERT INTO macro (indicator, date, value, source) VALUES (?, ?, ?, ?)",
                ("usd_krw", "2026-08-14", 1400.0, "test"),
            )

    @pytest.mark.parametrize(
        "gate_name",
        ["_check_position_limits", "_check_sector_limits", "_check_stop_loss_compliance"],
    )
    def test_gate_touches_no_other_database(self, gate_name: str, db_path, monkeypatch):
        import nuri.core.db.connection as conn_mod
        from nuri.trading.engine import certification as cert

        self._seed_violating_position(db_path)

        opened: list[str] = []
        original = conn_mod.sqlite3.connect

        def spy(path, *args, **kwargs):
            opened.append(str(path))
            return original(path, *args, **kwargs)

        monkeypatch.setattr(conn_mod.sqlite3, "connect", spy)
        getattr(cert, gate_name)(db_path=db_path)

        others = {p for p in opened if p != str(db_path)}
        assert not others, f"{gate_name} 이 db_path 외의 DB 를 열었다: {sorted(others)}"
        assert opened, f"{gate_name} 이 아무 DB 도 안 열었다 — 경로를 안 탄 것"

    def test_position_limit_sees_the_seeded_violation(self, db_path):
        """경로가 실제로 데이터를 읽는지 — 열기만 하고 안 읽으면 위 테스트가 공허하다."""
        from nuri.trading.engine import certification as cert

        self._seed_violating_position(db_path)
        cond = cert._check_position_limits(db_path=db_path)

        assert cond.passed is False, f"단일 종목 100% 인데 통과했다: {cond.detail}"
        assert "AAA" in cond.detail

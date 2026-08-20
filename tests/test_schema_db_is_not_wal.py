"""격리 DB 원본이 WAL 로 남지 않는다 (#1080).

## 왜 이 파일이 있나

`_schema_db` 는 `init_db()` 로 스키마를 만든다. 그 함수는 **진짜** `get_connection` 을
타는데 — 이 픽스처는 session scope 라 function scope 의 `_force_no_wal` 보다 먼저 돈다 —
거기서 `PRAGMA journal_mode=WAL` 이 걸린다. journal_mode 는 파일에 남는 속성이라
`shutil.copy` 로 만드는 **모든 격리 사본이 WAL 상태로 시작**했다.

그러면 `_test_connect` 가 커넥션마다 WAL→MEMORY 전환을 하게 되는데, 그 전환은
EXCLUSIVE 락을 요구하고 **`busy_timeout` 이 적용되지 않는다**. 같은 파일에 쓰기 락을
쥔 커넥션이 하나라도 있으면 커넥션 생성 자체가 재시도 없이 `database is locked` 로
죽는다. 테스트 하네스의 격리 장치가 부하에서 스스로 무너지는 형태다.

실측 (다른 커넥션이 `BEGIN IMMEDIATE` 보유, 30회 시도):
    WAL 사본    → OperationalError 30/30
    DELETE 사본 → OperationalError  0/30

`busy_timeout` 을 pragma 앞으로 옮기는 것으로는 안 된다 — 그것도 30/30 실패다.
고칠 곳은 커넥션이 아니라 원본의 모드다.

⚠️ 이 파일은 `journal_mode` 문자열을 grep 하지 않는다. 실제로 **락을 잡아두고 커넥션을
열어** 결과를 본다 — 모드 이름이 아니라 견디는지가 잠글 대상이다.
"""

from __future__ import annotations

import shutil
import sqlite3

import pytest


def _test_connect(path):
    """`tests/conftest.py::_force_no_wal` 의 `_test_connect` 와 같은 순서."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=MEMORY")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


class TestTheIsolationSourceIsNotWal:
    def test_the_schema_source_is_not_left_in_wal(self, _schema_db):
        """되돌리면(픽스처의 DELETE 한 줄 삭제) 여기서 'wal' 이 나온다."""
        conn = sqlite3.connect(str(_schema_db))
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            conn.close()

        assert mode != "wal", "격리 원본이 WAL 이다 — 모든 사본이 이걸 상속한다"

    def test_a_copy_opens_while_another_connection_holds_a_write_lock(self, _schema_db, tmp_path):
        """이 파일의 이유. 사본이 WAL 이면 30/30 으로 죽는 자리다.

        `BEGIN IMMEDIATE` 로 쓰기 락을 쥔 커넥션을 두고, 하네스가 하는 그대로
        커넥션을 연다. WAL 사본에서는 `journal_mode=MEMORY` 가 EXCLUSIVE 를 못 얻어
        즉시 `database is locked` 다.
        """
        db = tmp_path / "copy.db"
        shutil.copy(_schema_db, db)

        holder = sqlite3.connect(str(db))
        holder.execute("BEGIN IMMEDIATE")
        try:
            for _ in range(10):
                _test_connect(db).close()
        except sqlite3.OperationalError as e:  # pragma: no cover — 회귀 시에만 도달
            pytest.fail(f"쓰기 락이 있는 동안 커넥션을 못 열었다: {e}")
        finally:
            holder.rollback()
            holder.close()

    def test_a_wal_copy_really_does_fail_here(self, _schema_db, tmp_path):
        """카나리아 — 위 테스트가 '아무 사본이나 통과한다' 로 통과하는 게 아님을 보인다.

        같은 절차를 WAL 사본에 돌리면 실제로 죽는다. 이게 안 죽으면 위 테스트는
        아무것도 증명하지 않으므로, 전제가 깨졌다는 신호로 여기서 실패한다.
        """
        db = tmp_path / "wal_copy.db"
        shutil.copy(_schema_db, db)
        conn = sqlite3.connect(str(db))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.close()

        holder = sqlite3.connect(str(db))
        holder.execute("BEGIN IMMEDIATE")
        try:
            with pytest.raises(sqlite3.OperationalError):
                for _ in range(10):
                    _test_connect(db).close()
        finally:
            holder.rollback()
            holder.close()

"""sqlite3 connection lifecycle — sole sqlite3 importer in the codebase.

PreToolUse hook (.claude/settings.json) blocks `import sqlite3` outside this
file. All other modules must use `query()` / `query_df()` / `upsert_*()` /
`get_db()` from `nuri.core.db` (the package facade re-exports these).

Schema migrations live in `nuri/core/db_migrations.py` (PR #553 P2 Stage 1).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from nuri.core.db_migrations import _MIGRATIONS, _SCHEMA, _SCHEMA_VERSION_TABLE

# Repo root: nuri/core/db/connection.py → parents[3] = repo root
DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "portfolio.db"


def _resolve_db_path(db_path: Optional[Path]) -> Path:
    """Lookup default DB_PATH from facade (nuri.core.db) so test monkeypatch
    on `nuri.core.db.DB_PATH` continues to work post-Stage-2 split.

    Tests do `monkeypatch.setattr(db_mod, "DB_PATH", tmp_path)`. Without this
    indirection, get_connection would use connection.py's local DB_PATH and
    bypass the patch. Cost: 1 attribute lookup per connection (~negligible).
    """
    if db_path is not None:
        return db_path
    from nuri.core import db as _facade

    return _facade.DB_PATH


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """DB 연결 반환. WAL 모드, foreign keys 활성화."""
    path = _resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def get_db(db_path: Optional[Path] = None):
    """DB 컨텍스트 매니저. 성공 시 자동 commit, 실패 시 rollback.

    Resolves `get_connection` via the facade module so test conftest
    `monkeypatch.setattr(db_mod, "get_connection", ...)` (e.g. tmpfs MEMORY
    journal patch in tests/conftest.py) is honored post-Stage-2 split.
    """
    from nuri.core import db as _facade

    conn = _facade.get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[Path] = None) -> None:
    """전체 테이블 스키마 생성 + 증분 마이그레이션 적용."""
    with get_db(db_path) as conn:
        conn.executescript(_SCHEMA)
        conn.executescript(_SCHEMA_VERSION_TABLE)
        _apply_migrations(conn)


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """미적용 마이그레이션을 순서대로 실행."""
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_version").fetchall()}
    for version, desc, sql in _MIGRATIONS:
        if version not in applied:
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                (version, desc),
            )
            conn.commit()

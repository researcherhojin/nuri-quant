"""query_df 는 쿼리 단계 실패를 sqlite 예외로 낸다 — pandas 래퍼를 새지 않는다 (#1754)."""

import pandas as pd
import pytest

import nuri.core.db as dbmod
from nuri.core.db import DatabaseError, OperationalError, query, query_df


@pytest.fixture
def empty_db(tmp_path):
    """스키마가 없는 DB — `get_connection` 은 파일만 만들므로 어떤 테이블 조회도 쿼리 단계에서 실패한다."""
    return tmp_path / "empty.db"


class TestQueryDfRaisesTheSqliteError:
    def test_a_failing_query_raises_the_facade_error_not_the_pandas_wrapper(self, empty_db):
        with pytest.raises(OperationalError, match="no such table: macro") as caught:
            query_df("SELECT value FROM macro", db_path=empty_db)
        assert not isinstance(caught.value, pd.errors.DatabaseError)

    def test_both_readers_share_one_exception_contract(self, empty_db):
        """같은 실패가 `query()` 와 `query_df()` 에서 같은 타입으로 온다 — 좁은 핸들러 하나로 둘 다 잡힌다."""
        caught = []
        for reader in (query, query_df):
            try:
                reader("SELECT value FROM macro", db_path=empty_db)
            except (OperationalError, DatabaseError) as exc:
                caught.append(type(exc))
        assert caught == [OperationalError, OperationalError]

    def test_a_wrapper_without_a_sqlite_cause_is_left_alone(self, empty_db, monkeypatch):
        """원인이 sqlite 예외가 아니면(롤백 실패 등) 되돌릴 대상이 없다 — pandas 예외 그대로 낸다."""
        wrapper = pd.errors.DatabaseError("Execution failed on sql: unable to rollback")

        def fails(*args, **kwargs):
            raise wrapper

        monkeypatch.setattr(dbmod.pd, "read_sql_query", fails)
        with pytest.raises(pd.errors.DatabaseError) as caught:
            query_df("SELECT 1", db_path=empty_db)
        assert caught.value is wrapper

"""nuri.core.db 모듈 테스트 — in-memory SQLite로 격리."""

import pandas as pd
import pytest

from nuri.core.db import (
    get_connection,
    get_db,
    get_latest_price,
    get_schema_version,
    get_tickers,
    init_db,
    query,
    query_df,
    replace_portfolio_account,
    upsert_macro,
    upsert_portfolio,
    upsert_prices,
)


@pytest.fixture
def db_path(tmp_path):
    """임시 DB 경로 픽스처."""
    path = tmp_path / "test.db"
    init_db(path)
    return path


class TestInitDb:
    def test_creates_all_tables(self, db_path):
        """init_db()가 모든 테이블을 생성하는지 확인."""
        conn = get_connection(db_path)
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        conn.close()

        table_names = {t["name"] for t in tables}
        expected = {
            "prices",
            "portfolio",
            "macro",
            "ark",
            "signals",
            "events",
            "news",
            "factors",
            "backtests",
        }
        assert expected.issubset(table_names)

    def test_idempotent(self, db_path):
        """init_db()를 두 번 호출해도 에러 없이 동작."""
        init_db(db_path)
        init_db(db_path)

    def test_busy_timeout_set(self, db_path):
        """busy_timeout=5000 설정 확인."""
        conn = get_connection(db_path)
        result = conn.execute("PRAGMA busy_timeout").fetchone()
        conn.close()
        assert result[0] == 5000


class TestUpsertPrices:
    def test_insert_and_query(self, db_path):
        """주가 데이터 삽입 후 조회."""
        df = pd.DataFrame(
            [
                {
                    "ticker": "TSLA",
                    "date": "2026-03-24",
                    "open": 250.0,
                    "high": 260.0,
                    "low": 245.0,
                    "close": 255.0,
                    "volume": 1000000,
                    "adj_close": 255.0,
                }
            ]
        )
        count = upsert_prices(df, db_path)
        assert count == 1

        result = query("SELECT * FROM prices WHERE ticker='TSLA'", db_path=db_path)
        assert len(result) == 1
        assert result[0]["close"] == 255.0

    def test_upsert_idempotent(self, db_path):
        """같은 데이터 두 번 삽입 시 레코드 수 1 유지."""
        df = pd.DataFrame(
            [
                {
                    "ticker": "TSLA",
                    "date": "2026-03-24",
                    "open": 250.0,
                    "high": 260.0,
                    "low": 245.0,
                    "close": 255.0,
                    "volume": 1000000,
                    "adj_close": 255.0,
                }
            ]
        )
        upsert_prices(df, db_path)
        upsert_prices(df, db_path)

        result = query("SELECT COUNT(*) as cnt FROM prices", db_path=db_path)
        assert result[0]["cnt"] == 1

    def test_empty_dataframe(self, db_path):
        """빈 DataFrame은 0 반환."""
        assert upsert_prices(pd.DataFrame(), db_path) == 0


class TestUpsertPortfolio:
    def test_insert_holdings(self, db_path):
        """보유 종목 삽입."""
        records = [
            {
                "account": "test",
                "ticker": "TSLA",
                "quantity": 33.0,
                "avg_price": 200.0,
                "currency": "USD",
                "sector": "SectorA",
            },
            {
                "account": "sample",
                "ticker": "005930.KS",
                "quantity": 4.0,
                "avg_price": 200500,
                "currency": "KRW",
                "sector": "Semiconductor",
            },
        ]
        count = upsert_portfolio(records, db_path)
        assert count == 2

    def test_upsert_updates_existing(self, db_path):
        """같은 (account, ticker) 삽입 시 업데이트."""
        r1 = [
            {
                "account": "test",
                "ticker": "TSLA",
                "quantity": 10.0,
                "avg_price": 300.0,
                "currency": "USD",
                "sector": "SectorA",
            }
        ]
        r2 = [
            {
                "account": "test",
                "ticker": "TSLA",
                "quantity": 33.0,
                "avg_price": 200.0,
                "currency": "USD",
                "sector": "SectorA",
            }
        ]
        upsert_portfolio(r1, db_path)
        upsert_portfolio(r2, db_path)

        result = query("SELECT quantity FROM portfolio WHERE ticker='TSLA'", db_path=db_path)
        assert len(result) == 1
        assert result[0]["quantity"] == 33.0


class TestReplacePortfolioAccount:
    """yaml → DB sync용 stale 행 자동 삭제."""

    def _seed(self, db_path):
        """test 3종목 + sample 1종목 시드."""
        upsert_portfolio(
            [
                {
                    "account": "test",
                    "ticker": "TSLA",
                    "quantity": 10.0,
                    "avg_price": 300.0,
                    "currency": "USD",
                    "sector": "SectorA",
                },
                {
                    "account": "test",
                    "ticker": "BBB",
                    "quantity": 96.0,
                    "avg_price": 20.0,
                    "currency": "USD",
                    "sector": "SectorB",
                },
                {
                    "account": "test",
                    "ticker": "CCC",
                    "quantity": 20.0,
                    "avg_price": 150.0,
                    "currency": "USD",
                    "sector": "SectorC",
                },
                {
                    "account": "sample",
                    "ticker": "005930.KS",
                    "quantity": 5.0,
                    "avg_price": 50000.0,
                    "currency": "KRW",
                    "sector": "Semiconductor",
                },
            ],
            db_path,
        )

    def test_removes_stale_tickers(self, db_path):
        """yaml에서 사라진 ticker가 DB에서도 삭제됨."""
        self._seed(db_path)

        # test에 TSLA만 남기고 sync (BBB, OKLO는 청산)
        new_records = [
            {
                "account": "test",
                "ticker": "TSLA",
                "quantity": 33.0,
                "avg_price": 200.0,
                "currency": "USD",
                "sector": "SectorA",
            },
        ]
        deleted, inserted = replace_portfolio_account("test", new_records, db_path)

        assert deleted == 3
        assert inserted == 1

        rows = query(
            "SELECT ticker FROM portfolio WHERE account='test' ORDER BY ticker",
            db_path=db_path,
        )
        assert [r["ticker"] for r in rows] == ["TSLA"]

    def test_quantity_updated_on_replace(self, db_path):
        """기존 ticker의 수량/가격이 새 값으로 갱신됨."""
        self._seed(db_path)

        replace_portfolio_account(
            "test",
            [
                {
                    "account": "test",
                    "ticker": "TSLA",
                    "quantity": 33.0,
                    "avg_price": 200.0,
                    "currency": "USD",
                    "sector": "SectorA",
                },
            ],
            db_path,
        )

        rows = query("SELECT quantity, avg_price FROM portfolio WHERE ticker='TSLA'", db_path=db_path)
        assert rows[0]["quantity"] == 33.0
        assert rows[0]["avg_price"] == 200.0

    def test_does_not_touch_other_accounts(self, db_path):
        """sample 계좌는 test sync에 영향 받지 않음."""
        self._seed(db_path)

        replace_portfolio_account("test", [], db_path)

        toss_rows = query("SELECT ticker FROM portfolio WHERE account='sample'", db_path=db_path)
        assert len(toss_rows) == 1
        assert toss_rows[0]["ticker"] == "005930.KS"

    def test_empty_records_clears_account(self, db_path):
        """빈 records → 해당 계좌의 모든 행 삭제 (전량 청산)."""
        self._seed(db_path)

        deleted, inserted = replace_portfolio_account("test", [], db_path)

        assert deleted == 3
        assert inserted == 0

        rows = query("SELECT * FROM portfolio WHERE account='test'", db_path=db_path)
        assert rows == []

    def test_account_mismatch_raises(self, db_path):
        """records의 account가 인자와 다르면 ValueError."""
        with pytest.raises(ValueError, match="account mismatch"):
            replace_portfolio_account(
                "test",
                [
                    {
                        "account": "sample",
                        "ticker": "AAPL",
                        "quantity": 1.0,
                        "avg_price": 200.0,
                        "currency": "USD",
                        "sector": "BigTech",
                    },
                ],
                db_path,
            )

    def test_new_account_no_existing_rows(self, db_path):
        """기존에 없던 계좌도 정상 INSERT (deleted=0)."""
        deleted, inserted = replace_portfolio_account(
            "demo",
            [
                {
                    "account": "demo",
                    "ticker": "AMZN",
                    "quantity": 2.0,
                    "avg_price": 200.0,
                    "currency": "USD",
                    "sector": "BigTech",
                },
            ],
            db_path,
        )

        assert deleted == 0
        assert inserted == 1

    def test_metadata_default_none(self, db_path):
        """metadata 필드 미지정 시 None으로 INSERT."""
        replace_portfolio_account(
            "test",
            [
                {
                    "account": "test",
                    "ticker": "AAPL",
                    "quantity": 1.0,
                    "avg_price": 200.0,
                    "currency": "USD",
                    "sector": "BigTech",
                },
            ],
            db_path,
        )
        rows = query("SELECT metadata FROM portfolio WHERE ticker='AAPL'", db_path=db_path)
        assert rows[0]["metadata"] is None


class TestGetTickers:
    def test_all_tickers(self, db_path):
        """전체 티커 목록 조회."""
        upsert_portfolio(
            [
                {
                    "account": "test",
                    "ticker": "TSLA",
                    "quantity": 33.0,
                    "avg_price": 200.0,
                    "currency": "USD",
                    "sector": "SectorA",
                },
                {
                    "account": "sample",
                    "ticker": "005930.KS",
                    "quantity": 4.0,
                    "avg_price": 200500,
                    "currency": "KRW",
                    "sector": "Semiconductor",
                },
            ],
            db_path,
        )

        tickers = get_tickers(db_path=db_path)
        assert set(tickers) == {"TSLA", "005930.KS"}

    def test_filter_by_account(self, db_path):
        """계좌별 필터링."""
        upsert_portfolio(
            [
                {
                    "account": "test",
                    "ticker": "TSLA",
                    "quantity": 33.0,
                    "avg_price": 200.0,
                    "currency": "USD",
                    "sector": "SectorA",
                },
                {
                    "account": "sample",
                    "ticker": "005930.KS",
                    "quantity": 4.0,
                    "avg_price": 200500,
                    "currency": "KRW",
                    "sector": "Semiconductor",
                },
            ],
            db_path,
        )

        tickers = get_tickers(account="sample", db_path=db_path)
        assert tickers == ["005930.KS"]


class TestQueryDf:
    def test_returns_dataframe(self, db_path):
        """query_df가 DataFrame 반환."""
        upsert_macro(
            [
                {"indicator": "fear_greed", "date": "2026-03-24", "value": 45.0, "source": "CNN"},
            ],
            db_path,
        )

        df = query_df("SELECT * FROM macro", db_path=db_path)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1
        assert df.iloc[0]["indicator"] == "fear_greed"


class TestGetLatestPrice:
    def test_returns_latest(self, db_path):
        """최신 가격 반환."""
        df = pd.DataFrame(
            [
                {
                    "ticker": "TSLA",
                    "date": "2026-03-23",
                    "open": 240.0,
                    "high": 250.0,
                    "low": 235.0,
                    "close": 245.0,
                    "volume": 900000,
                    "adj_close": 245.0,
                },
                {
                    "ticker": "TSLA",
                    "date": "2026-03-24",
                    "open": 250.0,
                    "high": 260.0,
                    "low": 245.0,
                    "close": 255.0,
                    "volume": 1000000,
                    "adj_close": 255.0,
                },
            ]
        )
        upsert_prices(df, db_path)

        latest = get_latest_price("TSLA", db_path)
        assert latest is not None
        assert latest["date"] == "2026-03-24"
        assert latest["close"] == 255.0

    def test_returns_none_for_unknown(self, db_path):
        """없는 종목은 None 반환."""
        assert get_latest_price("XXXXX", db_path) is None


class TestSchemaMigration:
    def test_schema_version_table_exists(self, db_path):
        """init_db() 후 schema_version 테이블 존재."""
        conn = get_connection(db_path)
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'").fetchall()
        conn.close()
        assert len(tables) == 1

    def test_get_schema_version_initial(self, db_path):
        """마이그레이션 적용 후 최신 버전 — MAX(version) 기준."""
        from nuri.core.db import _MIGRATIONS

        expected = max(v for v, _, _ in _MIGRATIONS)
        assert get_schema_version(db_path) == expected

    def test_idempotent_with_migrations(self, db_path):
        """init_db() 여러 번 호출해도 schema_version 중복 없음."""
        from nuri.core.db import _MIGRATIONS

        init_db(db_path)
        init_db(db_path)
        rows = query("SELECT COUNT(*) as c FROM schema_version", db_path=db_path)
        assert rows[0]["c"] == len(_MIGRATIONS)


class TestMigration23ShortHorizonOutcomes:
    """#468 — outcome_7d/14d/21d columns added to recommendations."""

    def test_columns_exist_after_init(self, db_path):
        """Migration 23 적용 후 outcome_{7,14,21}d 모두 존재."""
        cols = {row["name"] for row in query("PRAGMA table_info(recommendations)", db_path=db_path)}
        assert {"outcome_7d", "outcome_14d", "outcome_21d"} <= cols

    def test_columns_are_real_nullable(self, db_path):
        """REAL nullable — forward-only NULL 호환성 (기존 row 보존)."""
        info = {row["name"]: row for row in query("PRAGMA table_info(recommendations)", db_path=db_path)}
        for col in ("outcome_7d", "outcome_14d", "outcome_21d"):
            assert info[col]["type"] == "REAL"
            assert info[col]["notnull"] == 0  # nullable

    def test_idempotent_rerun(self, db_path):
        """init_db() 재호출 시 ALTER TABLE 중복 실행 안 됨 (schema_version gate)."""
        init_db(db_path)
        init_db(db_path)
        # 컬럼 한 번만 존재 (재실행 시 OperationalError 'duplicate column' 안 발생)
        cols = [row["name"] for row in query("PRAGMA table_info(recommendations)", db_path=db_path)]
        assert cols.count("outcome_7d") == 1
        assert cols.count("outcome_14d") == 1
        assert cols.count("outcome_21d") == 1

    def test_existing_rows_have_null_outcomes(self, db_path):
        """Forward-only: 기존 row insert 후 outcome_*d 모두 NULL (lossy retrofit 금지)."""
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("2026-04-08", "AAPL", "BUY", 75.0, "bull_low_vol", "[]"),
            )
        rows = query("SELECT outcome_7d, outcome_14d, outcome_21d FROM recommendations", db_path=db_path)
        assert rows[0]["outcome_7d"] is None
        assert rows[0]["outcome_14d"] is None
        assert rows[0]["outcome_21d"] is None


class TestDbMaintenance:
    def test_dry_run(self, db_path, monkeypatch):
        """dry-run 모드에서 데이터 삭제 없음."""
        import nuri.core.db as db_mod

        monkeypatch.setattr(db_mod, "DB_PATH", db_path)

        from nuri.core.db import get_db

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO pipeline_events (step, event_type, timestamp) VALUES (?, ?, datetime('now', '-120 days'))",
                ("collect", "step_completed"),
            )

        from scripts.db.db_maintenance import run_maintenance

        run_maintenance(dry_run=True)
        rows = query("SELECT COUNT(*) as c FROM pipeline_events", db_path=db_path)
        assert rows[0]["c"] == 1  # dry-run이므로 삭제 안 됨

    def test_scheduler_db_maintenance_runs(self, db_path, monkeypatch):
        """스케줄러 _run_db_maintenance가 정상 실행."""
        import nuri.core.db as db_mod

        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        from nuri.scheduler import _run_db_maintenance

        _run_db_maintenance()  # 빈 DB에서도 에러 없이 실행


class TestUpsertNewsDedupCount:
    """#351 regression lock-in — upsert_news 가 실제 신규 삽입 수 반환.

    이전 구현은 `len(records)` 를 반환하여 URL UNIQUE 로 IGNORE 된 row 도 카운트 포함
    → 로그 "뉴스 N 건 수집" 과 DB 실제 상태 불일치 (§2.4 Observability 위배).
    `cursor.rowcount` 는 INSERT OR IGNORE 에서 실제 inserted rows 만 반환.
    """

    def _make_record(self, url: str, title: str = "t") -> dict:
        return {
            "ticker": "AAPL",
            "date": "2026-04-17",
            "title": title,
            "url": url,
            "source": "test",
            "sentiment": None,
        }

    def test_returns_actual_insert_count_on_url_dedup(self, db_path):
        """중복 URL 포함 input → 반환값이 dedup 후 실제 insert 건수."""
        from nuri.core.db import upsert_news

        records = [
            self._make_record("http://ex.com/1", "t1"),
            self._make_record("http://ex.com/1", "t2"),  # dup URL (IGNORED)
            self._make_record("http://ex.com/2", "t3"),
        ]
        ret = upsert_news(records, db_path=db_path)
        actual = query("SELECT COUNT(*) AS c FROM news", db_path=db_path)[0]["c"]

        assert ret == 2, f"expected actual insert count (2), got {ret}"
        assert ret == actual, "return value must equal DB row count (§2.4)"

    def test_second_call_with_same_urls_returns_zero(self, db_path):
        """동일 URL 재전송 → 전부 IGNORE → 반환 0 (이전엔 len(records) 반환 버그)."""
        from nuri.core.db import upsert_news

        r1 = [self._make_record("http://ex.com/A", "first")]
        assert upsert_news(r1, db_path=db_path) == 1

        # 같은 URL 다시 전송
        r2 = [self._make_record("http://ex.com/A", "second"), self._make_record("http://ex.com/B", "new")]
        ret = upsert_news(r2, db_path=db_path)
        assert ret == 1, f"only /B is new, expected 1, got {ret}"
        # DB 에 총 2 건 (A 는 first 그대로, B 신규)
        actual = query("SELECT COUNT(*) AS c FROM news", db_path=db_path)[0]["c"]
        assert actual == 2

    def test_empty_returns_zero(self, db_path):
        """빈 input → 0 (기존 동작 유지 — len([]) == cursor.rowcount == 0)."""
        from nuri.core.db import upsert_news

        assert upsert_news([], db_path=db_path) == 0


class TestInsertCertification:
    """E4-0a — SIEGE Certificate instrumentation.

    certifications 테이블이 없었던 시절 (SIEGE return-only) 에는 엔진 predictivity
    측정이 불가능. 이 테이블 + insert helper 가 미래 audit 의 기반.
    """

    def _valid_data(self, **overrides):
        base = {
            "timestamp": "2026-04-20T10:00:00+09:00",
            "certified": 0,
            "score": 52.9,
            "total_conditions": 17,
            "passed": 9,
            "failed": 1,
            "warnings": 7,
            "regime": "sideways_high_vol",
            "portfolio_hash": "abc123def456",
            "conditions_json": '[{"id":"position_limit","passed":false,"severity":"error"}]',
            "caller": "test",
        }
        base.update(overrides)
        return base

    def test_insert_returns_row_id(self, db_path):
        """insert_certification 은 lastrowid (> 0) 반환."""
        from nuri.core.db import insert_certification

        rid = insert_certification(self._valid_data(), db_path=db_path)
        assert rid >= 1

    def test_row_stored_with_all_fields(self, db_path):
        """삽입된 row 가 input field 를 모두 보존 (JSON roundtrip, optional 포함)."""
        from nuri.core.db import insert_certification, query

        data = self._valid_data(caller="api:actions", regime="bull_low_vol")
        insert_certification(data, db_path=db_path)

        rows = query("SELECT * FROM certifications", db_path=db_path)
        assert len(rows) == 1
        r = rows[0]
        assert r["timestamp"] == data["timestamp"]
        assert r["certified"] == 0
        assert r["score"] == 52.9
        assert r["total_conditions"] == 17
        assert r["regime"] == "bull_low_vol"
        assert r["caller"] == "api:actions"
        assert r["portfolio_hash"] == "abc123def456"
        assert r["created_at"] is not None  # DB default

    def test_missing_required_key_raises(self, db_path):
        """required key 누락 → ValueError (silent default 금지 — §2.4 loud at boundary)."""
        from nuri.core.db import insert_certification

        data = self._valid_data()
        del data["score"]
        with pytest.raises(ValueError, match="missing required keys"):
            insert_certification(data, db_path=db_path)

    def test_multiple_runs_accumulate_no_dedup(self, db_path):
        """동일 portfolio_hash 라도 시점이 다르면 별개로 기록 (UNIQUE 제약 없음)."""
        from nuri.core.db import insert_certification, query

        insert_certification(self._valid_data(timestamp="2026-04-20T09:00:00+09:00"), db_path=db_path)
        insert_certification(self._valid_data(timestamp="2026-04-20T10:00:00+09:00"), db_path=db_path)
        insert_certification(self._valid_data(timestamp="2026-04-20T11:00:00+09:00"), db_path=db_path)

        rows = query("SELECT COUNT(*) AS c FROM certifications", db_path=db_path)
        assert rows[0]["c"] == 3

    def test_nullable_fields_accepted(self, db_path):
        """regime / portfolio_hash / caller 는 None 허용 (empty portfolio, pre-regime DB)."""
        from nuri.core.db import insert_certification, query

        data = self._valid_data(regime=None, portfolio_hash=None, caller=None)
        insert_certification(data, db_path=db_path)

        rows = query("SELECT regime, portfolio_hash, caller FROM certifications", db_path=db_path)
        assert rows[0]["regime"] is None
        assert rows[0]["portfolio_hash"] is None
        assert rows[0]["caller"] is None

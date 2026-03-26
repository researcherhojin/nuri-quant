"""nuri.db 모듈 테스트 — in-memory SQLite로 격리."""
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from nuri.core.db import (
    get_connection,
    get_tickers,
    get_latest_price,
    init_db,
    query,
    query_df,
    upsert_macro,
    upsert_portfolio,
    upsert_prices,
    upsert_signals,
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
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        conn.close()

        table_names = {t["name"] for t in tables}
        expected = {
            "prices", "portfolio", "macro", "ark", "signals",
            "events", "news", "llm_bench", "factors", "backtests",
        }
        assert expected.issubset(table_names)

    def test_idempotent(self, db_path):
        """init_db()를 두 번 호출해도 에러 없이 동작."""
        init_db(db_path)
        init_db(db_path)


class TestUpsertPrices:
    def test_insert_and_query(self, db_path):
        """주가 데이터 삽입 후 조회."""
        df = pd.DataFrame([{
            "ticker": "TSLA", "date": "2026-03-24",
            "open": 250.0, "high": 260.0, "low": 245.0,
            "close": 255.0, "volume": 1000000, "adj_close": 255.0,
        }])
        count = upsert_prices(df, db_path)
        assert count == 1

        result = query("SELECT * FROM prices WHERE ticker='TSLA'", db_path=db_path)
        assert len(result) == 1
        assert result[0]["close"] == 255.0

    def test_upsert_idempotent(self, db_path):
        """같은 데이터 두 번 삽입 시 레코드 수 1 유지."""
        df = pd.DataFrame([{
            "ticker": "TSLA", "date": "2026-03-24",
            "open": 250.0, "high": 260.0, "low": 245.0,
            "close": 255.0, "volume": 1000000, "adj_close": 255.0,
        }])
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
            {"account": "test", "ticker": "TSLA", "quantity": 33.0,
             "avg_price": 200.0, "currency": "USD", "sector": "SectorA"},
            {"account": "sample", "ticker": "005930.KS", "quantity": 4.0,
             "avg_price": 200500, "currency": "KRW", "sector": "Semiconductor"},
        ]
        count = upsert_portfolio(records, db_path)
        assert count == 2

    def test_upsert_updates_existing(self, db_path):
        """같은 (account, ticker) 삽입 시 업데이트."""
        r1 = [{"account": "test", "ticker": "TSLA", "quantity": 10.0,
               "avg_price": 300.0, "currency": "USD", "sector": "SectorA"}]
        r2 = [{"account": "test", "ticker": "TSLA", "quantity": 33.0,
               "avg_price": 200.0, "currency": "USD", "sector": "SectorA"}]
        upsert_portfolio(r1, db_path)
        upsert_portfolio(r2, db_path)

        result = query("SELECT quantity FROM portfolio WHERE ticker='TSLA'", db_path=db_path)
        assert len(result) == 1
        assert result[0]["quantity"] == 33.0


class TestGetTickers:
    def test_all_tickers(self, db_path):
        """전체 티커 목록 조회."""
        upsert_portfolio([
            {"account": "test", "ticker": "TSLA", "quantity": 33.0,
             "avg_price": 200.0, "currency": "USD", "sector": "SectorA"},
            {"account": "sample", "ticker": "005930.KS", "quantity": 4.0,
             "avg_price": 200500, "currency": "KRW", "sector": "Semiconductor"},
        ], db_path)

        tickers = get_tickers(db_path=db_path)
        assert set(tickers) == {"TSLA", "005930.KS"}

    def test_filter_by_account(self, db_path):
        """계좌별 필터링."""
        upsert_portfolio([
            {"account": "test", "ticker": "TSLA", "quantity": 33.0,
             "avg_price": 200.0, "currency": "USD", "sector": "SectorA"},
            {"account": "sample", "ticker": "005930.KS", "quantity": 4.0,
             "avg_price": 200500, "currency": "KRW", "sector": "Semiconductor"},
        ], db_path)

        tickers = get_tickers(account="sample", db_path=db_path)
        assert tickers == ["005930.KS"]


class TestQueryDf:
    def test_returns_dataframe(self, db_path):
        """query_df가 DataFrame 반환."""
        upsert_macro([
            {"indicator": "fear_greed", "date": "2026-03-24", "value": 45.0, "source": "CNN"},
        ], db_path)

        df = query_df("SELECT * FROM macro", db_path=db_path)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1
        assert df.iloc[0]["indicator"] == "fear_greed"


class TestGetLatestPrice:
    def test_returns_latest(self, db_path):
        """최신 가격 반환."""
        df = pd.DataFrame([
            {"ticker": "TSLA", "date": "2026-03-23", "open": 240.0, "high": 250.0,
             "low": 235.0, "close": 245.0, "volume": 900000, "adj_close": 245.0},
            {"ticker": "TSLA", "date": "2026-03-24", "open": 250.0, "high": 260.0,
             "low": 245.0, "close": 255.0, "volume": 1000000, "adj_close": 255.0},
        ])
        upsert_prices(df, db_path)

        latest = get_latest_price("TSLA", db_path)
        assert latest is not None
        assert latest["date"] == "2026-03-24"
        assert latest["close"] == 255.0

    def test_returns_none_for_unknown(self, db_path):
        """없는 종목은 None 반환."""
        assert get_latest_price("XXXXX", db_path) is None

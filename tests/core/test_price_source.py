"""가격 행의 출처 (#1727) — 어느 공급자가 이 (ticker, date) 를 남겼는가."""

from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd
import pytest

from nuri.core.db import init_db, query, upsert_prices


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "prices.db"
    init_db(p)
    return p


def _bar(ticker="AAA", day="2026-10-06", close=100.0, **extra):
    return {
        "ticker": ticker,
        "date": day,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1,
        "adj_close": close,
        **extra,
    }


def _source(db_path, ticker="AAA"):
    return query("SELECT source FROM prices WHERE ticker = ?", (ticker,), db_path=db_path)[0]["source"]


class TestUpsertPricesRecordsTheSource:
    def test_argument_is_written(self, db_path):
        upsert_prices(pd.DataFrame([_bar()]), db_path=db_path, source="yfinance")
        assert _source(db_path) == "yfinance"

    def test_per_row_column_wins_over_the_argument(self, db_path):
        """KIS 수집기는 KIS 행과 yfinance 폴백 행을 한 프레임에 섞는다 — 행마다 자기 출처."""
        frame = pd.DataFrame([_bar("AAA", source="kis"), _bar("BBB", source="yfinance")])
        upsert_prices(frame, db_path=db_path, source="ignored")
        assert (_source(db_path, "AAA"), _source(db_path, "BBB")) == ("kis", "yfinance")

    def test_rows_without_their_own_source_take_the_argument(self, db_path):
        """concat 으로 섞인 프레임 — 출처 컬럼이 없던 쪽은 NaN 이다. NULL 로 쓰지 않고 인자 값을 쓴다."""
        frame = pd.concat([pd.DataFrame([_bar("AAA")]), pd.DataFrame([_bar("KOSPI", source="yfinance")])])
        upsert_prices(frame, db_path=db_path, source="pykrx")
        assert (_source(db_path, "AAA"), _source(db_path, "KOSPI")) == ("pykrx", "yfinance")

    def test_a_later_writer_replaces_the_source_with_the_row(self, db_path):
        """INSERT OR REPLACE — 같은 (ticker, date) 를 다른 공급자가 덮으면 출처도 그 공급자다."""
        upsert_prices(pd.DataFrame([_bar(close=100.0)]), db_path=db_path, source="kis")
        upsert_prices(pd.DataFrame([_bar(close=101.0)]), db_path=db_path, source="yfinance")
        row = query("SELECT close, source FROM prices", db_path=db_path)
        assert row == [{"close": 101.0, "source": "yfinance"}]


class TestCollectorsName:
    def test_every_production_call_passes_source(self):
        """`upsert_prices` 는 테스트 편의상 source 가 선택 인자다 — 그래서 nuri/ 의 호출은 전수 대조한다.
        새 수집기가 source 없이 쓰면 그 행만 출처 NULL 로 남는다."""
        root = Path(__file__).resolve().parents[2] / "nuri"
        calls, missing = [], []
        for path in root.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (
                    isinstance(node, ast.Call)
                    and getattr(node.func, "id", getattr(node.func, "attr", None)) == "upsert_prices"
                ):
                    where = f"{path.relative_to(root.parent)}:{node.lineno}"
                    calls.append(where)
                    if not any(k.arg == "source" for k in node.keywords):
                        missing.append(where)
        assert len(calls) >= 3, f"수집기 호출을 못 찾았다 — 스윕이 눈이 멀었다: {calls}"
        assert not missing, f"source 없이 prices 에 쓰는 호출: {missing}"

    def test_kis_marks_fallback_rows_as_yfinance(self, monkeypatch):
        from nuri.collectors import kis_realtime as kr

        collector = kr.KISRealtimeCollector.__new__(kr.KISRealtimeCollector)
        collector.logger = __import__("logging").getLogger("t")
        collector.mode = "prod"
        monkeypatch.setattr(collector, "creds", {}, raising=False)
        monkeypatch.setattr(collector, "check_credentials", lambda: True, raising=False)
        monkeypatch.setattr(kr, "get_access_token", lambda creds: "tok")
        monkeypatch.setattr(kr, "get_tickers", lambda: ["AAA", "BBB"])
        monkeypatch.setattr(kr, "inquire_price_us", lambda creds, token, t: _bar(t) if t == "AAA" else None)
        monkeypatch.setattr(kr.time, "sleep", lambda s: None)
        monkeypatch.setattr(collector, "_yfinance_fallback", lambda tickers: [_bar(t) for t in tickers], raising=False)
        frame = collector.collect()
        assert dict(zip(frame["ticker"], frame["source"])) == {"AAA": "kis", "BBB": "yfinance"}

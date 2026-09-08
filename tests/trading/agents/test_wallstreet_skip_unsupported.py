"""#1501 — wallstreet 는 ETF 와 비상장 자리표시자에 yfinance 를 부르지 않는다.

mini 실측: 보유 ETF 3종(DRAM/NASA/QTUM)과 사모 자리표시자 1종이 종목당 3.6~5.5s 씩 느리게 실패해
브리프 34s 중 18.6s 를 차지했다. `SKIP_TICKERS` 하드코딩은 새 ETF 를 못 따라온다 — 데이터로 거른다.
"""

from __future__ import annotations

import pytest

from nuri.core.db import get_db, init_db


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "t.db"
    init_db(path)
    return path


def _holding(db_path, ticker, sector, with_prices=True):
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?, ?, ?, ?, ?, ?)",
            ("test", ticker, 1, 10.0, "USD", sector),
        )
        if with_prices:
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ticker, "2026-09-01", 10, 10, 10, 10.0, 1),
            )


@pytest.fixture
def yfinance_must_not_be_called(monkeypatch):
    import yfinance

    def boom(*a, **k):
        raise AssertionError("yfinance.Ticker 가 호출됐다 — 미지원 종목은 네트워크 전에 걸러야 한다")

    monkeypatch.setattr(yfinance, "Ticker", boom)


class TestSkipByData:
    def test_etf_sector_holding_is_skipped_before_yfinance(self, db_path, yfinance_must_not_be_called):
        from nuri.trading.agents.wallstreet import WallStreetAgent

        _holding(db_path, "DRAM", "ETF/Semiconductor")
        v = WallStreetAgent().analyze("DRAM", db_path=db_path)
        assert v.abstained and "미지원" in v.reasoning

    @pytest.mark.parametrize("sector", ["Leveraged ETF", " etf ", "Sector ETF/Energy", "ETF"])
    def test_etf_token_anywhere_in_sector(self, db_path, yfinance_must_not_be_called, sector):
        from nuri.trading.agents.wallstreet import WallStreetAgent

        _holding(db_path, "XETF", sector)
        assert WallStreetAgent().analyze("XETF", db_path=db_path).abstained

    def test_failed_price_probe_does_not_abstain(self, db_path, monkeypatch):
        """DB 장애를 '미지원 기권' 으로 위장하면 안 된다 (#1436) — 가격 조회가 실패하면 예전처럼 yfinance 로 간다."""
        import yfinance

        from nuri.trading.agents import wallstreet as mod
        from nuri.trading.agents.base import QueryRows

        called = {"n": 0}

        class MockTicker:
            def __init__(self, ticker):
                called["n"] += 1
                self.upgrades_downgrades = None
                self.earnings_history = None
                self.insider_transactions = None
                self.recommendations = None

        monkeypatch.setattr(yfinance, "Ticker", MockTicker)
        _holding(db_path, "NVDA", "Semiconductor", with_prices=False)
        real = mod.WallStreetAgent._safe_query

        def flaky(self, sql, params=(), db_path=None):
            if "FROM prices" in sql:
                return QueryRows(failed=True)
            return real(self, sql, params, db_path)

        monkeypatch.setattr(mod.WallStreetAgent, "_safe_query", flaky)
        v = mod.WallStreetAgent().analyze("NVDA", db_path=db_path)
        assert called["n"] == 1 and "미지원" not in v.reasoning

    def test_unlisted_placeholder_without_prices_is_skipped(self, db_path, yfinance_must_not_be_called):
        from nuri.trading.agents.wallstreet import WallStreetAgent

        _holding(db_path, "SPACEX", "Aerospace/Private", with_prices=False)
        v = WallStreetAgent().analyze("SPACEX", db_path=db_path)
        assert v.abstained and "미지원" in v.reasoning

    def test_listed_equity_still_reaches_yfinance(self, db_path, monkeypatch):
        """회귀 방지 — 데이터 필터가 진짜 주식까지 삼키면 wallstreet 가 조용히 죽는다."""
        import yfinance

        called = {"n": 0}

        class MockTicker:
            def __init__(self, ticker):
                called["n"] += 1
                self.upgrades_downgrades = None
                self.earnings_history = None
                self.insider_transactions = None
                self.recommendations = None

        monkeypatch.setattr(yfinance, "Ticker", MockTicker)
        from nuri.trading.agents.wallstreet import WallStreetAgent

        _holding(db_path, "NVDA", "Semiconductor")
        WallStreetAgent().analyze("NVDA", db_path=db_path)
        assert called["n"] == 1

    def test_ticker_not_in_portfolio_is_not_filtered(self, db_path, monkeypatch):
        """스캐너 종목(포트폴리오 밖)은 sector 도 가격도 없을 수 있다 — 그건 미지원 판정 근거가 아니다."""
        import yfinance

        called = {"n": 0}

        class MockTicker:
            def __init__(self, ticker):
                called["n"] += 1
                self.upgrades_downgrades = None
                self.earnings_history = None
                self.insider_transactions = None
                self.recommendations = None

        monkeypatch.setattr(yfinance, "Ticker", MockTicker)
        from nuri.trading.agents.wallstreet import WallStreetAgent

        WallStreetAgent().analyze("SCAN", db_path=db_path)
        assert called["n"] == 1

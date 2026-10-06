"""`live_quote` 도구 (#1626) — 티커는 호출자가 대고, DB 는 읽지 않으며, 실패는 티커 단위로 보고한다."""

from __future__ import annotations

from unittest.mock import patch

from nuri.mcp import server


def _quote(t: str) -> dict:
    return {
        "ticker": t,
        "price": 1.0,
        "previous_close": 1.0,
        "change_pct": 0.0,
        "currency": "USD",
        "exchange": "X",
        "market_open": False,
        "fetched_at": "2026-10-06T12:00:00+09:00",
        "source": "yfinance",
    }


class TestLiveQuote:
    def test_normalizes_dedupes_and_reports_per_ticker(self):
        calls: list[str] = []

        def fake(t):
            calls.append(t)
            return None if t == "BAD" else _quote(t)

        with patch.object(server, "fetch_quote", side_effect=fake):
            out = server.live_quote([" spy", "SPY", "bad", "005930.ks"])
        assert calls == ["SPY", "BAD", "005930.KS"]
        assert [o["ticker"] for o in out] == ["SPY", "BAD", "005930.KS"]
        assert "error" in out[1] and "price" not in out[1]
        assert "price" in out[0]

    def test_caps_the_ticker_count_without_fetching(self):
        with patch.object(server, "fetch_quote") as fq:
            out = server.live_quote([f"T{i}" for i in range(server.LIVE_QUOTE_MAX_TICKERS + 1)])
        fq.assert_not_called()
        assert len(out) == server.LIVE_QUOTE_MAX_TICKERS + 1 and all("error" in o for o in out)

    def test_empty_input(self):
        with patch.object(server, "fetch_quote") as fq:
            assert server.live_quote(["", "  "]) == []
        fq.assert_not_called()

    def test_reads_no_database(self, tmp_path, monkeypatch):
        """출처가 무엇이든 DB 를 열지 않는다 — 보유 테이블은 설계상 닿을 수 없다."""
        from nuri.mcp import source

        monkeypatch.setattr(
            source, "resolve_source", lambda *a, **k: (_ for _ in ()).throw(AssertionError("DB resolved"))
        )
        with patch.object(server, "fetch_quote", side_effect=_quote):
            assert server.live_quote(["AAPL"])[0]["price"] == 1.0

"""fundamental.py branch coverage — Issue #616 Phase 3-C5.

| line | branch / stmt | trigger |
|---|---|---|
| 274→272 | `if val is not None:` False (col override skip) | KIS record 의 pe_ratio/price_to_book/market_cap 중 일부 None |
| 296→311 | `if results:` False (empty results) | ≥20 tickers, 전부 yfinance skip → results=[] |
| 351→353 | `if record:` False (KIS fetch fail) | `_fetch_kis_kr` 일부 None 반환 |
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock


class TestKisMergeSkipsNoneCols:
    def test_kis_record_with_partial_cols_skips_none_override(self, monkeypatch, db_with_portfolio):
        """274→272: KIS record 의 price_to_book=None → override skip → yfinance 값 보존."""
        from nuri.collectors.fundamental import FundamentalCollector, _kis_record_skeleton

        c = FundamentalCollector()
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: ["005930.KS"])

        def stub_kis(self, kr_tickers, today):
            r = _kis_record_skeleton("005930.KS", today)
            r["pe_ratio"] = 33.94  # KIS 채움
            r["price_to_book"] = None  # KIS 미제공 (우선주 등) → override skip
            r["market_cap"] = 1.3e15
            return [r]

        monkeypatch.setattr(FundamentalCollector, "_collect_kr_via_kis", stub_kis)

        class _FakeTicker:
            def __init__(self, t):
                self.info = {
                    "regularMarketPrice": 222500.0,
                    "trailingPE": 5.27,  # KIS override 됨 → 33.94
                    "priceToBook": 7.77,  # KIS=None → 보존
                    "marketCap": 1.0e15,  # KIS override 됨 → 1.3e15
                }

        mock_yf = MagicMock()
        mock_yf.Ticker = _FakeTicker
        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

        results = c.collect()

        rec = next(r for r in results if r["ticker"] == "005930.KS")
        assert rec["pe_ratio"] == 33.94  # KIS override
        assert rec["price_to_book"] == 7.77  # yfinance 보존 (KIS=None skip path)
        assert rec["market_cap"] == 1.3e15  # KIS override


class TestEmptyResultsBypassCoverageLog:
    def test_twenty_tickers_all_fail_skips_per_field_log(self, monkeypatch, db_with_portfolio):
        """296→311: ≥20 tickers, 전부 yfinance skip → results=[] → coverage log skip → return []."""
        from nuri.collectors.fundamental import FundamentalCollector

        c = FundamentalCollector()
        # 20 US ticker (KR 미포함 → KIS skip)
        tickers = [f"FAKE{i}" for i in range(20)]
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: tickers)

        class _FakeTicker:
            def __init__(self, t):
                self.info = {}  # regularMarketPrice 없음 → skipped

        mock_yf = MagicMock()
        mock_yf.Ticker = _FakeTicker
        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

        results = c.collect()

        assert results == []


class TestCollectKrViaKisSkipsNoneRecord:
    def test_fetch_kis_returns_none_skips_append(self, monkeypatch, db_with_portfolio):
        """351→353: _fetch_kis_kr → None → results.append skip → sleep 만 진행."""
        import nuri.collectors.fundamental as fund_mod

        c = fund_mod.FundamentalCollector()

        # KIS creds + token stub
        from nuri.collectors.kis_realtime import KISCredentials

        fake_creds = KISCredentials("k", "s", "1", "h", "prod")
        monkeypatch.setattr("nuri.collectors.kis_realtime.load_credentials", lambda mode="prod": fake_creds)
        monkeypatch.setattr("nuri.collectors.kis_realtime.get_access_token", lambda c: "fake-token")

        # 1번째 ticker 는 record 정상, 2번째는 None
        call_count = {"n": 0}

        def fake_fetch(ticker, creds, token, today):
            call_count["n"] += 1
            if call_count["n"] == 1:
                from nuri.collectors.fundamental import _kis_record_skeleton

                r = _kis_record_skeleton(ticker, today)
                r["pe_ratio"] = 10.0
                return r
            return None  # 2번째 → 351 False path

        monkeypatch.setattr(fund_mod, "_fetch_kis_kr", fake_fetch)
        # sleep 빠르게
        monkeypatch.setattr("time.sleep", lambda s: None)

        result = c._collect_kr_via_kis(["005930.KS", "000660.KS"], "2026-05-06")

        assert len(result) == 1
        assert result[0]["ticker"] == "005930.KS"
        assert call_count["n"] == 2  # 두 번 모두 호출 (None 도 sleep 진행)

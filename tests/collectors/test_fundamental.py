"""Per-collector tests for fundamental.

Split from tests/test_collectors_all.py for module-level isolation.
"""

from unittest.mock import MagicMock, patch

import pytest

from nuri.core.db import (
    init_db,
)


@pytest.fixture(autouse=True)
def _block_kis_live_calls(monkeypatch):
    """#465 — fundamental.py 가 KR ticker 를 자동으로 KIS 로 보내므로,
    yfinance branch 만 검증하는 기존 18 test 가 실제 KIS API 를 호출하지 않도록 차단.
    KIS-specific test (TestKISFundamentalBranch) 는 자체 monkeypatch 로 override.
    """
    from nuri.collectors.fundamental import FundamentalCollector
    monkeypatch.setattr(FundamentalCollector, "_collect_kr_via_kis", lambda self, kr, today: [])


class TestFundamentalCollector:
    def test_instantiate(self):
        from nuri.collectors.fundamental import FundamentalCollector

        c = FundamentalCollector()
        assert c.name == "fundamental"

    def test_save_records(self, db_path):
        from nuri.collectors.fundamental import _upsert_fundamentals

        records = [
            {
                "ticker": "AAPL",
                "date": "2026-03-30",
                "market_cap": 3e12,
                "pe_ratio": 28.5,
                "forward_pe": 25.0,
                "price_to_book": 45.0,
                "peg_ratio": 2.1,
                "roe": 1.5,
                "roa": 0.3,
                "gross_margin": 0.46,
                "operating_margin": 0.31,
                "profit_margin": 0.26,
                "revenue_growth": 0.08,
                "earnings_growth": 0.1,
                "debt_to_equity": 1.8,
                "current_ratio": 1.1,
                "dividend_yield": 0.005,
                "beta": 1.2,
                "annual_dividend_usd": 0.96,
                "dividend_yield_pct": 0.5,
            }
        ]
        count = _upsert_fundamentals(records)
        assert count == 1

        # 배당 컬럼 검증
        from nuri.core.db import query

        rows = query(
            "SELECT annual_dividend_usd, dividend_yield_pct FROM fundamentals WHERE ticker='AAPL'", db_path=db_path
        )
        assert rows[0]["annual_dividend_usd"] == 0.96
        assert rows[0]["dividend_yield_pct"] == 0.5


class TestFundamentalCollectorMockedYFinance:
    def test_upsert_fundamentals(self, rich_db):
        from nuri.collectors.fundamental import _upsert_fundamentals

        records = [
            {
                "ticker": "AAPL",
                "date": "2025-03-15",
                "market_cap": 3e12,
                "pe_ratio": 28.5,
                "forward_pe": 25.0,
                "price_to_book": 45.0,
                "peg_ratio": 1.5,
                "roe": 1.5,
                "roa": 0.3,
                "gross_margin": 0.45,
                "operating_margin": 0.30,
                "profit_margin": 0.25,
                "revenue_growth": 0.08,
                "earnings_growth": 0.12,
                "debt_to_equity": 1.8,
                "current_ratio": 1.1,
                "dividend_yield": 0.005,
                "beta": 1.2,
                "annual_dividend_usd": 0.96,
                "dividend_yield_pct": 0.5,
            }
        ]
        assert _upsert_fundamentals(records) == 1

    def test_upsert_fundamentals_empty(self, rich_db):
        from nuri.collectors.fundamental import _upsert_fundamentals

        assert _upsert_fundamentals([]) == 0

    def test_save_empty(self, rich_db):
        from nuri.collectors.fundamental import FundamentalCollector

        c = FundamentalCollector()
        assert c.save([]) == 0
        assert c.save(None) == 0

    def test_collect_with_mock_yfinance(self, rich_db, monkeypatch):
        """Migrated from openbb mock — fundamental collector now uses yfinance.Ticker.info."""
        import sys

        from nuri.collectors.fundamental import FundamentalCollector

        mock_ticker = MagicMock()
        mock_ticker.info = {
            "regularMarketPrice": 195.0,
            "marketCap": 3e12,
            "trailingPE": 28.5,
            "forwardPE": 25.0,
            "priceToBook": 45.0,
            "pegRatio": 1.5,
            "returnOnEquity": 1.5,
            "returnOnAssets": 0.3,
            "grossMargins": 0.45,
            "operatingMargins": 0.30,
            "profitMargins": 0.25,
            "revenueGrowth": 0.08,
            "earningsGrowth": 0.12,
            "debtToEquity": 1.8,
            "currentRatio": 1.1,
            "dividendYield": 0.005,
            "beta": 1.2,
        }
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

        c = FundamentalCollector()
        with patch.object(c, "_get_tickers", return_value=["AAPL"]):
            result = c.collect()
        assert len(result) == 1
        assert result[0]["pe_ratio"] == 28.5
        assert result[0]["roe"] == 1.5

    def test_collect_empty_dataframe(self, rich_db, monkeypatch):
        """yfinance가 빈 info를 반환하면 스킵."""
        import sys

        from nuri.collectors.fundamental import FundamentalCollector

        mock_ticker = MagicMock()
        mock_ticker.info = {}  # 빈 info → regularMarketPrice 없음 → 스킵
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

        c = FundamentalCollector()
        with patch.object(c, "_get_tickers", return_value=["FAKE"]):
            result = c.collect()
        assert result == []

    def test_collect_exception(self, rich_db, monkeypatch):
        """yfinance API 예외는 try/except로 잡혀 빈 결과 반환."""
        import sys

        from nuri.collectors.fundamental import FundamentalCollector

        mock_yf = MagicMock()
        mock_yf.Ticker.side_effect = RuntimeError("API error")
        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

        c = FundamentalCollector()
        with patch.object(c, "_get_tickers", return_value=["FAIL"]):
            result = c.collect()
        assert result == []

    def test_collect_nan_fields(self, rich_db, monkeypatch):
        """NaN/None 필드는 None으로 안전 변환되어야 함."""
        import sys

        from nuri.collectors.fundamental import FundamentalCollector

        mock_ticker = MagicMock()
        mock_ticker.info = {
            "regularMarketPrice": 195.0,
            "marketCap": float("nan"),
            "trailingPE": 28.5,
            "forwardPE": None,
            "priceToBook": float("nan"),
            "pegRatio": None,
            "returnOnEquity": None,
            "returnOnAssets": None,
            "grossMargins": None,
            "operatingMargins": None,
            "profitMargins": None,
            "revenueGrowth": None,
            "earningsGrowth": None,
            "debtToEquity": None,
            "currentRatio": None,
            "dividendYield": None,
            "beta": None,
        }
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

        c = FundamentalCollector()
        with patch.object(c, "_get_tickers", return_value=["AAPL"]):
            result = c.collect()
        assert len(result) == 1
        assert result[0]["market_cap"] is None
        assert result[0]["pe_ratio"] == 28.5


class TestFundamentalCollectorErrorHandling:
    def test_collect_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fundamental import FundamentalCollector

        mock_ticker = MagicMock()
        mock_ticker.info = {
            "regularMarketPrice": 195.0,
            "marketCap": 3e12,
            "trailingPE": 28.5,
            "forwardPE": 25.0,
            "priceToBook": 15.0,
            "pegRatio": 1.5,
            "returnOnEquity": 0.35,
            "returnOnAssets": 0.15,
            "grossMargins": 0.45,
            "operatingMargins": 0.30,
            "profitMargins": 0.25,
            "revenueGrowth": 0.08,
            "earningsGrowth": 0.12,
            "debtToEquity": 1.2,
            "currentRatio": 1.5,
            "dividendYield": 0.005,
            "dividendRate": 0.96,
            "beta": 1.1,
        }
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)
        results = FundamentalCollector().collect()
        assert len(results) >= 1
        assert results[0]["pe_ratio"] == 28.5
        # #227: 배당 필드 검증
        assert results[0]["annual_dividend_usd"] == 0.96
        assert results[0]["dividend_yield_pct"] == 0.5  # 0.005 × 100

    def test_collect_empty_df(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fundamental import FundamentalCollector

        mock_ticker = MagicMock()
        mock_ticker.info = {}  # 빈 info → regularMarketPrice 없음 → 스킵
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)
        assert FundamentalCollector().collect() == []

    def test_collect_no_dividend(self, monkeypatch, db_with_portfolio):
        """dividendYield/dividendRate가 None이면 배당 필드도 None."""
        from nuri.collectors.fundamental import FundamentalCollector

        mock_ticker = MagicMock()
        mock_ticker.info = {
            "regularMarketPrice": 195.0,
            "trailingPE": 28.5,
        }
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)
        results = FundamentalCollector().collect()
        assert len(results) >= 1
        assert results[0]["annual_dividend_usd"] is None
        assert results[0]["dividend_yield_pct"] is None

    def test_collect_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fundamental import FundamentalCollector

        mock_yf = MagicMock()
        mock_yf.Ticker.side_effect = Exception("API error")
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)
        assert FundamentalCollector().collect() == []

    def test_collect_nan_values(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fundamental import FundamentalCollector

        mock_ticker = MagicMock()
        mock_ticker.info = {
            "regularMarketPrice": 195.0,
            "marketCap": float("nan"),
            "trailingPE": 28.5,
            "forwardPE": None,
            "priceToBook": None,
            "returnOnEquity": None,
        }
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)
        results = FundamentalCollector().collect()
        assert len(results) >= 1
        assert results[0]["market_cap"] is None
        assert results[0]["pe_ratio"] == 28.5

    def test_collect_no_tickers(self, monkeypatch, tmp_path):
        import nuri.core.db as db_mod
        from nuri.collectors.fundamental import FundamentalCollector

        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        assert FundamentalCollector().collect() == []

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.fundamental import FundamentalCollector

        c = FundamentalCollector()
        assert c.save([]) == 0
        assert c.save(None) == 0


class TestUniverseModeCoverage:
    """#272 Phase 2b: source 파라미터 + tqdm + 필드별 coverage 패치 커버리지."""

    def test_collect_universe_source_passed_to_get_tickers(self, monkeypatch, db_with_portfolio):
        """source='universe' 가 _get_tickers로 전달."""
        from unittest.mock import MagicMock, patch

        from nuri.collectors.fundamental import FundamentalCollector

        c = FundamentalCollector()
        captured = {}

        def fake_get(**kw):
            captured.update(kw)
            return []

        monkeypatch.setattr(c, "_get_tickers", fake_get)
        mock_yf = MagicMock()
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)
        c.collect(source="universe")
        assert captured.get("source") == "universe"

    def test_collect_summary_with_per_field_coverage(self, monkeypatch, db_with_portfolio, caplog):
        """20+ tickers + 데이터 있는 경우: 필드별 coverage table fired."""
        import logging
        from unittest.mock import MagicMock

        from nuri.collectors.fundamental import FundamentalCollector

        c = FundamentalCollector()
        # 25개 tickers, 모두 정상 반환
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: [f"T{i}" for i in range(25)])

        def fake_ticker_info(ticker):
            mock = MagicMock()
            mock.info = {
                "regularMarketPrice": 100.0,
                "trailingPE": 25.0,
                "forwardPE": 22.0,
                "returnOnEquity": 0.15,
                "revenueGrowth": 0.10,
                "debtToEquity": 1.5,
                "dividendYield": 0.02,
            }
            return mock

        mock_yf = MagicMock()
        mock_yf.Ticker.side_effect = fake_ticker_info
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)
        with caplog.at_level(logging.INFO):
            c.collect(source="universe")

        # summary + per-field coverage logs
        summary = [r for r in caplog.records if "펀더멘탈:" in r.message]
        assert len(summary) >= 1
        coverage_log = [r for r in caplog.records if "필드별 coverage" in r.message]
        assert len(coverage_log) >= 1

    def test_collect_skip_empty_info(self, monkeypatch, db_with_portfolio):
        """info 비어있는 ticker는 skipped 카운트."""
        from unittest.mock import MagicMock

        from nuri.collectors.fundamental import FundamentalCollector

        c = FundamentalCollector()
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: ["EMPTY"])

        mock_ticker = MagicMock()
        mock_ticker.info = {}  # empty
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)
        results = c.collect()
        assert results == []  # skipped, no records


class TestKISFundamentalBranch:
    """Issue #465 — KIS Open API 가 KR ticker PER/PBR/market_cap 을 yfinance 보다 정확 제공.

    fundamental.py 가 .KS/.KQ ticker → KIS sequential, US → yfinance thread pool 분기.
    KIS 자격 증명 부재 / 토큰 발급 실패 / per-ticker 실패 모두 yfinance fallback.
    """

    def _kis_response(self, *, per=33.94, pbr=3.48, prpr=222500.0, shares=5846278608) -> dict:
        """KIS inquire-price 응답 shape (raw probe 2026-04-29 005930 기준)."""
        return {
            "rt_cd": "0",
            "output": {
                "stck_prpr": str(int(prpr)),
                "lstn_stcn": str(shares),
                "per": str(per) if per is not None else "0",
                "pbr": str(pbr) if pbr is not None else "0",
                "stck_oprc": "220000", "stck_hgpr": "224000", "stck_lwpr": "219000",
                "acml_vol": "12345678", "stck_sdpr": "221000",
            },
        }

    def test_fetch_kis_kr_extracts_per_pbr_market_cap(self, monkeypatch):
        """raw KIS payload → record 에 pe_ratio / price_to_book / market_cap 채워짐."""
        from nuri.collectors import fundamental as fund_mod

        # Outer self 를 closure 로 capture → R.json 의 self 와 충돌 회피 (Pylance reportSelfClsParameterName)
        response_data = self._kis_response()

        def stub_get(url, headers=None, params=None, timeout=10):
            class R:
                status_code = 200
                def json(self):
                    return response_data
            return R()

        monkeypatch.setattr("requests.get", stub_get)

        from types import SimpleNamespace
        creds = SimpleNamespace(base_url="https://x", app_key="k", app_secret="s")
        record = fund_mod._fetch_kis_kr("005930.KS", creds, "TOKEN", "2026-04-29")

        assert record is not None
        assert record["ticker"] == "005930.KS"
        assert record["date"] == "2026-04-29"
        assert record["pe_ratio"] == 33.94
        assert record["price_to_book"] == 3.48
        # market_cap = 222,500 × 5,846,278,608 = 1,300,796,990,000,000
        assert record["market_cap"] == pytest.approx(222500 * 5846278608, rel=1e-9)

    def test_fetch_kis_kr_zero_per_pbr_treated_as_null(self, monkeypatch):
        """KIS 가 0 으로 반환 (예: 우선주 PER) → None 처리 (false positive 방지)."""
        from types import SimpleNamespace

        from nuri.collectors import fundamental as fund_mod

        response_data = self._kis_response(per=0, pbr=0)

        def stub_get(url, headers=None, params=None, timeout=10):
            class R:
                status_code = 200
                def json(self):
                    return response_data
            return R()

        monkeypatch.setattr("requests.get", stub_get)
        creds = SimpleNamespace(base_url="https://x", app_key="k", app_secret="s")
        record = fund_mod._fetch_kis_kr("005935.KS", creds, "TOKEN", "2026-04-29")

        # per=0/pbr=0 은 None 으로 — but market_cap 은 여전히 계산됨
        assert record is not None
        assert record["pe_ratio"] is None
        assert record["price_to_book"] is None
        assert record["market_cap"] is not None

    def test_fetch_kis_kr_http_error_returns_none(self, monkeypatch):
        """HTTP 500 / 빈 응답 → per-ticker fallback 신호 (None 반환)."""
        from types import SimpleNamespace

        from nuri.collectors import fundamental as fund_mod

        def stub_get(url, headers=None, params=None, timeout=10):
            class R:
                status_code = 500
                def json(self):
                    return {}
            return R()

        monkeypatch.setattr("requests.get", stub_get)
        creds = SimpleNamespace(base_url="https://x", app_key="k", app_secret="s")
        assert fund_mod._fetch_kis_kr("005930.KS", creds, "TOKEN", "2026-04-29") is None

    def test_collect_kr_via_kis_no_credentials_returns_empty(self, monkeypatch, db_with_portfolio):
        """KIS 자격 증명 부재 → 빈 리스트 (caller 가 yfinance fallback)."""
        from nuri.collectors.fundamental import FundamentalCollector

        monkeypatch.setattr("nuri.collectors.kis_realtime.load_credentials", lambda mode: None)
        c = FundamentalCollector()
        result = c._collect_kr_via_kis(["005930.KS", "000660.KS"], "2026-04-29")
        assert result == []

    def test_collect_kr_via_kis_token_failure_returns_empty(self, monkeypatch, db_with_portfolio):
        """KIS 토큰 발급 실패 → 빈 리스트 (yfinance fallback)."""
        from types import SimpleNamespace

        from nuri.collectors.fundamental import FundamentalCollector

        creds = SimpleNamespace(base_url="https://x", app_key="k", app_secret="s")
        monkeypatch.setattr("nuri.collectors.kis_realtime.load_credentials", lambda mode: creds)
        monkeypatch.setattr("nuri.collectors.kis_realtime.get_access_token", lambda c: None)

        c = FundamentalCollector()
        result = c._collect_kr_via_kis(["005930.KS"], "2026-04-29")
        assert result == []

    def test_collect_branches_kr_to_kis_us_to_yfinance(self, monkeypatch, db_with_portfolio):
        """`.KS` → KIS, US → yfinance thread pool. KIS 가 채운 KR ticker 는 yfinance loop skip."""
        from nuri.collectors.fundamental import FundamentalCollector

        c = FundamentalCollector()
        # universe-only (db_with_portfolio fixture 외 추가)
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: ["005930.KS", "AAPL"])

        # KIS path stub — 005930.KS 정상 응답
        def stub_kis(self, kr_tickers, today):
            return [{
                "ticker": "005930.KS",
                "date": today,
                "pe_ratio": 33.94,
                "price_to_book": 3.48,
                "market_cap": 1.3e15,
            }]
        monkeypatch.setattr(FundamentalCollector, "_collect_kr_via_kis", stub_kis)

        # yfinance path stub — AAPL 만 응답해야 함 (005930.KS 는 KIS 가 처리해 skip)
        called_yf_tickers = []

        class _FakeTicker:
            def __init__(self, t):
                called_yf_tickers.append(t)
                self.info = {
                    "regularMarketPrice": 200.0,
                    "trailingPE": 25.0,
                    "marketCap": 3e12,
                }

        mock_yf = MagicMock()
        mock_yf.Ticker = _FakeTicker
        import sys
        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

        results = c.collect(source="universe")

        assert "005930.KS" not in called_yf_tickers, "KIS 가 채운 KR 은 yfinance 가 다시 호출하면 안 됨"
        assert "AAPL" in called_yf_tickers
        tickers_in_results = {r["ticker"] for r in results}
        assert "005930.KS" in tickers_in_results
        assert "AAPL" in tickers_in_results

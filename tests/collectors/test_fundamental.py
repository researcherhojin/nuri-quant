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
                "stck_oprc": "220000",
                "stck_hgpr": "224000",
                "stck_lwpr": "219000",
                "acml_vol": "12345678",
                "stck_sdpr": "221000",
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

    def test_collect_kis_merge_preserves_yfinance_enrichment(self, monkeypatch, db_with_portfolio):
        """codex Round 1 P1 회귀 — KIS 가 채운 KR ticker 도 yfinance loop 가 돌아 ROE/growth 보존.

        KIS 의 pe_ratio/price_to_book/market_cap 은 yfinance 값을 override (정확).
        yfinance 의 roe/revenue_growth/profit_margin/debt_to_equity 는 보존 (KIS 미제공).
        """
        from nuri.collectors.fundamental import FundamentalCollector

        c = FundamentalCollector()
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: ["005930.KS", "AAPL"])

        # KIS stub — 005930.KS 에 정확한 trailing pe/pbr 제공
        def stub_kis(self, kr_tickers, today):
            from nuri.collectors.fundamental import _kis_record_skeleton

            r = _kis_record_skeleton("005930.KS", today)
            r["pe_ratio"] = 33.94
            r["price_to_book"] = 3.48
            r["market_cap"] = 1.3e15
            return [r]

        monkeypatch.setattr(FundamentalCollector, "_collect_kr_via_kis", stub_kis)

        # yfinance stub — KR 도 yfinance loop 거침 (forward_pe/roe/etc 채움)
        called_yf_tickers = []

        class _FakeTicker:
            def __init__(self, t):
                called_yf_tickers.append(t)
                if t == "005930.KS":
                    self.info = {
                        "regularMarketPrice": 222500.0,
                        "trailingPE": 5.27,  # yfinance forward-derived (misleading per #465)
                        "priceToBook": None,  # yfinance KR limit
                        "returnOnEquity": 0.108,  # 10.8% — 보존 대상
                        "revenueGrowth": 0.238,  # 23.8% — 보존 대상
                        "profitMargins": 0.133,  # 13.3% — 보존 대상
                        "debtToEquity": 6.0,  # — 보존 대상
                    }
                else:
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

        # 005930.KS 가 yfinance loop 도 돌았는지 (KIS bypass 회귀 차단)
        assert "005930.KS" in called_yf_tickers, "KR ticker 가 yfinance loop bypass 되면 ROE/growth 손실"

        # 005930.KS record 검증 — KIS pe/pbr 우선 + yfinance ROE 보존
        kr_record = next(r for r in results if r["ticker"] == "005930.KS")
        assert kr_record["pe_ratio"] == 33.94, "KIS trailing PE 가 yfinance 5.27 override"
        assert kr_record["price_to_book"] == 3.48, "KIS PBR (yfinance None) 채움"
        assert kr_record["market_cap"] == 1.3e15, "KIS market_cap 우선"
        # yfinance enrichment 보존 (codex P1)
        assert kr_record["roe"] == pytest.approx(0.108)
        assert kr_record["revenue_growth"] == pytest.approx(0.238)
        assert kr_record["profit_margin"] == pytest.approx(0.133)

    def test_save_empty_returns_zero(self):
        """save([]) → 0 (line 341)."""
        from nuri.collectors.fundamental import FundamentalCollector

        assert FundamentalCollector().save([]) == 0

    def test_collect_kis_only_record_when_yfinance_fails(self, monkeypatch, db_with_portfolio):
        """KIS 가 채운 KR ticker 가 yfinance fetch 실패 시 KIS record 단독으로 results 포함."""
        from nuri.collectors.fundamental import FundamentalCollector

        c = FundamentalCollector()
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: ["005930.KS"])

        def stub_kis(self, kr_tickers, today):
            from nuri.collectors.fundamental import _kis_record_skeleton

            r = _kis_record_skeleton("005930.KS", today)
            r["pe_ratio"] = 33.94
            r["price_to_book"] = 3.48
            return [r]

        monkeypatch.setattr(FundamentalCollector, "_collect_kr_via_kis", stub_kis)

        # yfinance fail (info 빈 dict — skipped)
        mock_ticker = MagicMock()
        mock_ticker.info = {}
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

        results = c.collect(source="universe")
        # yfinance 실패에도 KIS-only record 가 살아남아야 함
        assert len(results) == 1
        assert results[0]["ticker"] == "005930.KS"
        assert results[0]["pe_ratio"] == 33.94


class TestFundamentalExpectedCountGuard:
    """MAX_FAILURE_RATE 가드 활성화 lock-test (PR #588 후속).

    Reason: 직전 audit 에서 _expected_count 가 25/26 collector 에 unset 인 상태로
    base.py 의 'asymmetric data age 방지' 가드가 dead code 였음을 확인.
    fundamental.collect() 가 _expected_count 를 ticker 수로 동적 설정하도록 변경했고,
    이 테스트가 회귀를 차단함.
    """

    def test_collect_sets_expected_count(self, monkeypatch, db_with_portfolio):
        """collect() 진입 시 self._expected_count 가 len(tickers) 로 설정됨."""
        from nuri.collectors.fundamental import FundamentalCollector

        c = FundamentalCollector()
        # initial state — 0 (불활성)
        assert c._expected_count == 0

        mock_ticker = MagicMock()
        mock_ticker.info = {"regularMarketPrice": 100.0, "trailingPE": 20.0}
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: ["AAPL", "MSFT", "GOOGL"])

        c.collect()
        assert c._expected_count == 3, "collect() 가 ticker 수로 _expected_count 설정 안 함"

    def test_run_blocks_save_when_failure_rate_exceeds_threshold(self, monkeypatch, db_with_portfolio):
        """run() 이 70% 실패 시 CollectionFailureError 발생 + save() 미호출."""
        from nuri.collectors.base import CollectionFailureError
        from nuri.collectors.fundamental import FundamentalCollector

        c = FundamentalCollector()
        # 10 ticker 중 2개만 성공 → failure_rate 80% > 10% threshold
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: [f"T{i}" for i in range(10)])

        # yfinance — T0/T1 만 valid info, 나머지 8개는 빈 info (skipped)
        def make_ticker(t):
            mock = MagicMock()
            if t in ("T0", "T1"):
                mock.info = {"regularMarketPrice": 100.0, "trailingPE": 20.0}
            else:
                mock.info = {}
            return mock

        mock_yf = MagicMock()
        mock_yf.Ticker.side_effect = make_ticker
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

        save_called = []
        monkeypatch.setattr(c, "save", lambda data: save_called.append(len(data)) or len(data))

        with pytest.raises(CollectionFailureError, match="실패율 80%"):
            c.run()

        assert save_called == [], "실패율 초과 시 save() 호출되면 안 됨 (asymmetric save 차단)"

    def test_run_allows_save_when_failure_rate_below_threshold(self, monkeypatch, db_with_portfolio):
        """failure_rate 5% < 10% 면 save() 정상 호출."""
        from nuri.collectors.fundamental import FundamentalCollector

        c = FundamentalCollector()
        # 20 ticker 중 19개 성공 → failure_rate 5%
        tickers = [f"T{i}" for i in range(20)]
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: tickers)

        def make_ticker(t):
            mock = MagicMock()
            if t == "T0":
                mock.info = {}
            else:
                mock.info = {"regularMarketPrice": 100.0, "trailingPE": 20.0}
            return mock

        mock_yf = MagicMock()
        mock_yf.Ticker.side_effect = make_ticker
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

        save_called = []
        monkeypatch.setattr(c, "save", lambda data: save_called.append(len(data)) or len(data))

        # 가드 통과 — retry 없이 첫 시도에서 save 호출
        result = c.run()
        assert result == 19, "save() 가 19 records 받아야 함"
        assert save_called == [19], "save() 1회 호출"


# ─── main(argv) CLI: print loop coverage (lines 405-417) ──────────────────


class TestFundamentalMainCli:
    """`main(argv)` 가 fundamentals 행이 있을 때 표 print 분기 진입.

    수집 자체는 외부 API 호출이라 monkeypatch 로 우회. DB 에 fundamentals row 만
    seed 하면 main() 의 query → if rows: print 분기가 covered.
    """

    def test_main_prints_results_when_db_has_fundamentals(self, monkeypatch, tmp_path, capsys):
        import nuri.collectors.fundamental as fund_mod
        from nuri.core.db import init_db

        db = tmp_path / "fund.db"
        init_db(db)
        monkeypatch.setattr("nuri.core.db.DB_PATH", db)

        # Seed fundamentals row directly
        with fund_mod.query.__globals__["get_connection"](db) as conn:
            conn.execute(
                """INSERT INTO fundamentals
                       (ticker, date, market_cap, pe_ratio, forward_pe, roe,
                        revenue_growth, debt_to_equity)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("TEST", "2026-04-01", 1_000_000, 25.5, 22.0, 0.18, 0.12, 1.5),
            )
            conn.commit()

        # FundamentalCollector.run 우회 (외부 API 차단)
        class _StubCollector:
            def run(self, source=None):
                return 1

        monkeypatch.setattr(fund_mod, "FundamentalCollector", _StubCollector)

        rc = fund_mod.main(["--source", "portfolio"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "펀더멘탈 수집 완료" in out
        assert "TEST" in out
        assert "25.5" in out  # pe_ratio
        assert "18.0%" in out  # roe

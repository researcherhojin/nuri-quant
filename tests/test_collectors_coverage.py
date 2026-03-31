"""Collector 커버리지 보강 — 0% 모듈 테스트.

네트워크 의존 collect()는 mock, save()는 DB 격리, 순수 함수는 직접 테스트.
"""
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_portfolio


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    # 테스트용 종목 등록
    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10,
         "avg_price": 190, "currency": "USD", "sector": "Tech"},
        {"account": "test", "ticker": "005930.KS", "quantity": 4,
         "avg_price": 60000, "currency": "KRW", "sector": "Semi"},
    ], path)
    return path


# ─── MacroCollector ───


class TestMacroCollector:
    def test_instantiate(self):
        from nuri.collectors.macro import MacroCollector
        c = MacroCollector()
        assert c.name == "macro"

    def test_save_empty(self, db_path):
        from nuri.collectors.macro import MacroCollector
        c = MacroCollector()
        assert c.save([]) == 0

    def test_save_records(self, db_path):
        from nuri.collectors.macro import MacroCollector
        c = MacroCollector()
        records = [
            {"indicator": "vix", "date": "2026-03-30", "value": 25.5, "source": "test"},
            {"indicator": "fear_greed", "date": "2026-03-30", "value": 45.0, "source": "test"},
        ]
        count = c.save(records)
        assert count == 2


# ─── FundamentalCollector ───


class TestFundamentalCollector:
    def test_instantiate(self):
        from nuri.collectors.fundamental import FundamentalCollector
        c = FundamentalCollector()
        assert c.name == "fundamental"

    def test_save_records(self, db_path):
        from nuri.collectors.fundamental import _upsert_fundamentals
        records = [{"ticker": "AAPL", "date": "2026-03-30", "market_cap": 3e12,
                     "pe_ratio": 28.5, "forward_pe": 25.0, "price_to_book": 45.0,
                     "peg_ratio": 2.1, "roe": 1.5, "roa": 0.3,
                     "gross_margin": 0.46, "operating_margin": 0.31, "profit_margin": 0.26,
                     "revenue_growth": 0.08, "earnings_growth": 0.1,
                     "debt_to_equity": 1.8, "current_ratio": 1.1,
                     "dividend_yield": 0.005, "beta": 1.2}]
        count = _upsert_fundamentals(records)
        assert count == 1


# ─── EstimatesCollector ───


class TestEstimatesCollector:
    def test_instantiate(self):
        from nuri.collectors.estimates import EstimatesCollector
        c = EstimatesCollector()
        assert c.name == "estimates"

    def test_safe_helpers(self):
        from nuri.collectors.estimates import _safe_float, _safe_int
        assert _safe_float(1.5) == 1.5
        assert _safe_float(None) is None
        assert _safe_float(float("nan")) is None
        assert _safe_int(10) == 10
        assert _safe_int(None) is None
        assert _safe_int(float("nan")) is None

    def test_save_records(self, db_path):
        from nuri.collectors.estimates import _upsert_estimates
        records = [{"ticker": "AAPL", "date": "2026-03-30",
                     "recommendation": "buy", "target_high": 250.0,
                     "target_low": 190.0, "target_mean": 220.0,
                     "target_median": 218.0, "num_analysts": 30,
                     "current_price": 195.0}]
        count = _upsert_estimates(records)
        assert count == 1


# ─── ARKCollector ───


class TestARKCollector:
    def test_instantiate(self):
        from nuri.collectors.ark import ARKCollector
        c = ARKCollector()
        assert c.name == "ark"

    def test_save_empty(self, db_path):
        from nuri.collectors.ark import ARKCollector
        c = ARKCollector()
        assert c.save([]) == 0

    def test_save_records(self, db_path):
        from nuri.collectors.ark import ARKCollector
        c = ARKCollector()
        records = [{"date": "2026-03-30", "ticker": "TSLA", "direction": "Buy",
                     "shares": 50000.0, "weight": 8.5, "fund": "ARKK"}]
        count = c.save(records)
        assert count == 1


# ─── FearGreedCollector ───


class TestFearGreedCollector:
    def test_instantiate(self):
        from nuri.collectors.fear_greed import FearGreedCollector
        c = FearGreedCollector()
        assert c.name == "fear_greed"

    def test_save_records(self, db_path):
        from nuri.collectors.fear_greed import FearGreedCollector
        c = FearGreedCollector()
        records = [{"indicator": "fear_greed", "date": "2026-03-30",
                     "value": 55.0, "source": "cnn_api"}]
        count = c.save(records)
        assert count == 1

    @patch("nuri.collectors.fear_greed.requests")
    def test_collect_api(self, mock_requests):
        """CNN API mock — 정상 응답."""
        from nuri.collectors.fear_greed import FearGreedCollector
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "fear_and_greed": {"score": 62.5},
        }
        mock_requests.get.return_value = mock_resp
        c = FearGreedCollector()
        result = c._collect_api()
        assert len(result) == 1
        assert result[0]["value"] == 62.5


# ─── CBOECollector ───


class TestCBOECollector:
    def test_instantiate(self):
        from nuri.collectors.cboe import CBOECollector
        c = CBOECollector()
        assert c.name == "cboe"

    def test_extract_pcr_total(self):
        """TOTAL_PUT_CALL_RATIO 키."""
        from nuri.collectors.cboe import CBOECollector
        c = CBOECollector()
        assert c._extract_pcr({"TOTAL_PUT_CALL_RATIO": 0.85}) == 0.85

    def test_extract_pcr_simple(self):
        """PUT_CALL_RATIO 키."""
        from nuri.collectors.cboe import CBOECollector
        c = CBOECollector()
        assert c._extract_pcr({"PUT_CALL_RATIO": 0.92}) == 0.92

    def test_extract_pcr_calculated(self):
        """put_vol / call_vol 계산."""
        from nuri.collectors.cboe import CBOECollector
        c = CBOECollector()
        result = c._extract_pcr({"TOTAL_PUT_VOLUME": 1000, "TOTAL_CALL_VOLUME": 2000})
        assert abs(result - 0.5) < 0.01

    def test_extract_pcr_missing(self):
        """키 없으면 None."""
        from nuri.collectors.cboe import CBOECollector
        c = CBOECollector()
        assert c._extract_pcr({}) is None

    def test_save_records(self, db_path):
        from nuri.collectors.cboe import CBOECollector
        c = CBOECollector()
        records = [{"indicator": "put_call_ratio", "date": "2026-03-30",
                     "value": 0.85, "source": "cboe"}]
        count = c.save(records)
        assert count == 1


# ─── FINVIZCollector ───


class TestFINVIZCollector:
    def test_instantiate(self):
        from nuri.collectors.finviz import FINVIZCollector
        c = FINVIZCollector()
        assert c.name == "finviz"

    def test_signals_constant(self):
        from nuri.collectors.finviz import FINVIZ_SIGNALS
        assert "new_high" in FINVIZ_SIGNALS
        assert "oversold_rsi" in FINVIZ_SIGNALS

    def test_save_records(self, db_path):
        from nuri.collectors.finviz import FINVIZCollector
        c = FINVIZCollector()
        records = [{"date": "2026-03-30", "ticker": "AAPL",
                     "signal": "new_high", "source": "FINVIZ"}]
        count = c.save(records, db_path=db_path)
        assert count == 1


# ─── WallStreetCollector ───


class TestWallStreetCollector:
    def test_instantiate(self):
        from nuri.collectors.wallstreet import WallStreetCollector
        c = WallStreetCollector()
        assert c.name == "wallstreet"

    def test_save_all_types(self, db_path):
        """ratings/earnings/insiders/short_data 전부 저장."""
        from nuri.collectors.wallstreet import WallStreetCollector
        c = WallStreetCollector()
        data = {
            "ratings": [{"ticker": "AAPL", "date": "2026-03-30", "firm": "GS",
                          "to_grade": "Buy", "from_grade": "Hold", "action": "upgrade",
                          "target_price": 230.0}],
            "earnings": [{"ticker": "AAPL", "quarter": "2026Q1",
                           "eps_actual": 2.1, "eps_estimate": 1.9, "surprise_pct": 10.5}],
            "insiders": [{"ticker": "AAPL", "date": "2026-03-20", "insider_name": "Tim Cook",
                           "position": "CEO", "transaction_type": "Sale",
                           "shares": 50000, "value": 9500000}],
            "short_data": [{"ticker": "AAPL", "short_pct_float": 0.8, "days_to_cover": 1.2}],
        }
        count = c.save(data)
        assert count > 0


# ─── SuperinvestorCollector ───


class TestSuperinvestorCollector:
    def test_instantiate(self):
        from nuri.collectors.superinvestors import SuperinvestorCollector
        c = SuperinvestorCollector()
        assert c.name == "superinvestors"

    def test_superinvestors_dict(self):
        from nuri.collectors.superinvestors import SUPERINVESTORS
        assert "Warren Buffett" in SUPERINVESTORS
        assert "National Pension Service" in SUPERINVESTORS
        assert len(SUPERINVESTORS) >= 8

    def test_save_records(self, db_path):
        from nuri.collectors.superinvestors import SuperinvestorCollector
        c = SuperinvestorCollector()
        records = [{"investor": "Warren Buffett", "ticker": "AAPL",
                     "shares": 900000000, "market_value": 171000000000,
                     "portfolio_pct": 48.5, "filing_date": "2026-02-14",
                     "issuer_name": "Apple Inc."}]
        count = c.save(records)
        assert count == 1


# ─── EtfFlowsCollector ───


class TestEtfFlowsCollector:
    def test_instantiate(self):
        from nuri.collectors.etf_flows import EtfFlowsCollector
        c = EtfFlowsCollector()
        assert c.name == "etf_flows"

    def test_save_records(self, db_path):
        from nuri.collectors.etf_flows import EtfFlowsCollector
        c = EtfFlowsCollector()
        records = [{"ticker": "SPY", "date": "2026-03-30", "name": "SPDR S&P 500",
                     "total_assets": 500e9, "volume_avg": 80000000,
                     "nav_price": 520.0}]
        count = c.save(records)
        assert count == 1


# ─── StockKRCollector ───


class TestStockKRCollector:
    def test_instantiate(self):
        from nuri.collectors.stock_kr import StockKRCollector
        c = StockKRCollector()
        assert c.name == "stock_kr"

    def test_save_records(self, db_path):
        from nuri.core.db import upsert_prices
        df = pd.DataFrame([{"ticker": "005930.KS", "date": "2026-03-30",
                             "open": 60000, "high": 61000, "low": 59500,
                             "close": 60500, "volume": 10000000, "adj_close": 60500}])
        count = upsert_prices(df, db_path=db_path)
        assert count == 1

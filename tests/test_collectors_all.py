"""Consolidated collector tests -- ALL collector-related test classes from the test suite.

Target modules: nuri.collectors.* (all 21 collectors + base)
Total: 335 test methods across 79 classes.
Generated from: test_collector_base.py, test_collectors.py, test_collectors_coverage.py,
  test_collectors_phase2.py, test_coverage_round3/4/5/6/8/9/11/13/15/17/19/20/24.py,
  test_uncovered.py

Zero test loss: every test method that imports from nuri.collectors.* is preserved.
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from nuri.collectors.base import MAX_FAILURE_RATE, BaseCollector, CollectionFailureError
from nuri.core.db import (
    get_db,
    init_db,
    query,
    upsert_macro,
    upsert_portfolio,
    upsert_prices,
)

# ==============================================================================
# Shared fixtures
# ==============================================================================


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """Isolated DB with DB_PATH patched."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture
def db_with_us_tickers(db_path):
    """DB with US portfolio tickers."""
    upsert_portfolio(
        [
            {"account": "test", "ticker": "TSLA", "quantity": 10,
             "avg_price": 300, "currency": "USD", "sector": "EV"},
            {"account": "test", "ticker": "NVDA", "quantity": 5,
             "avg_price": 800, "currency": "USD", "sector": "Semi"},
            {"account": "test", "ticker": "AAPL", "quantity": 20,
             "avg_price": 180, "currency": "USD", "sector": "Tech"},
        ],
        db_path,
    )
    return db_path


@pytest.fixture
def db_with_portfolio(db_path, monkeypatch):
    """DB with portfolio + prices seeded."""
    upsert_portfolio(
        [
            {"account": "test", "ticker": "AAPL", "quantity": 10, "avg_price": 190,
             "currency": "USD", "sector": "Tech"},
            {"account": "test", "ticker": "NVDA", "quantity": 5, "avg_price": 130,
             "currency": "USD", "sector": "Semiconductor"},
            {"account": "test", "ticker": "005930.KS", "quantity": 4, "avg_price": 60000,
             "currency": "KRW", "sector": "Semiconductor"},
        ],
        db_path,
    )

    dates = pd.date_range("2025-01-01", periods=30, freq="B")
    rows = []
    for t in ["AAPL", "NVDA", "SPY", "005930.KS"]:
        base = {"AAPL": 190, "NVDA": 130, "SPY": 550, "005930.KS": 60000}.get(t, 100)
        for i, d in enumerate(dates):
            p = base + i * 0.5
            rows.append({
                "ticker": t, "date": d.strftime("%Y-%m-%d"),
                "open": p, "high": p + 2, "low": p - 1,
                "close": p + 1, "volume": 1_000_000, "adj_close": p + 1,
            })
    upsert_prices(pd.DataFrame(rows), db_path)

    upsert_macro([
        {"indicator": "fear_greed", "date": "2025-01-30", "value": 55.0, "source": "CNN"},
        {"indicator": "vix", "date": "2025-01-30", "value": 18.5, "source": "test"},
    ], db_path)

    return db_path


@pytest.fixture
def rich_db(tmp_path, monkeypatch):
    """Rich DB with portfolio, prices, macro."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    upsert_portfolio(
        [
            {"account": "test", "ticker": "AAPL", "quantity": 10, "avg_price": 190,
             "currency": "USD", "sector": "Tech"},
            {"account": "test", "ticker": "NVDA", "quantity": 5, "avg_price": 130,
             "currency": "USD", "sector": "Semi"},
            {"account": "test", "ticker": "005930.KS", "quantity": 100, "avg_price": 70000,
             "currency": "KRW", "sector": "Tech"},
        ],
        path,
    )

    dates = pd.date_range("2024-06-01", periods=50, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA"]:
        base = {"SPY": 450, "AAPL": 170, "NVDA": 120}[t]
        for i, d in enumerate(dates):
            p = base + i * 0.3
            rows.append({
                "ticker": t, "date": d.strftime("%Y-%m-%d"),
                "open": p, "high": p + 3, "low": p - 2,
                "close": p + 1, "volume": 50000000, "adj_close": p + 1,
            })
    upsert_prices(pd.DataFrame(rows), path)

    macro = []
    for i, d in enumerate(dates):
        ds = d.strftime("%Y-%m-%d")
        macro.append({"indicator": "vix", "date": ds, "value": 15.0, "source": "test"})
        macro.append({"indicator": "fear_greed", "date": ds, "value": 55.0, "source": "test"})
    upsert_macro(macro, path)

    return path


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    """retry backoff sleep 건너뛰기."""
    import time

    monkeypatch.setattr(time, "sleep", lambda _: None)


# ##############################################################################
# Source: test_collector_base.py -- BaseCollector
# ##############################################################################


class GoodCollector(BaseCollector):
    def __init__(self):
        super().__init__("good")

    def collect(self, **kwargs):
        return [{"data": 1}, {"data": 2}]

    def save(self, data):
        return len(data)


class FailCollector(BaseCollector):
    def __init__(self):
        super().__init__("fail")

    def collect(self, **kwargs):
        raise RuntimeError("API 호출 실패")

    def save(self, data):
        return 0


class HighFailureCollector(BaseCollector):
    def __init__(self, expected, actual_count):
        super().__init__("high_fail")
        self._expected_count = expected
        self._actual = actual_count

    def collect(self, **kwargs):
        return list(range(self._actual))

    def save(self, data):
        return len(data)


class TestBaseCollectorRun:
    def test_successful_run(self):
        c = GoodCollector()
        count = c.run()
        assert count == 2
        assert c._last_run is not None

    def test_collect_failure(self):
        c = FailCollector()
        with pytest.raises(RuntimeError, match="API 호출 실패"):
            c.run()

    def test_high_failure_rate_blocked(self):
        c = HighFailureCollector(expected=100, actual_count=80)
        with pytest.raises(CollectionFailureError):
            c.run()

    def test_acceptable_failure_rate(self):
        c = HighFailureCollector(expected=100, actual_count=95)
        count = c.run()
        assert count == 95

    def test_no_expected_count_skips_check(self):
        c = GoodCollector()
        c._expected_count = 0
        count = c.run()
        assert count == 2


class TestGetTickers:
    def test_filter_us(self, db_path):
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("t", "AAPL", 1, 100, "USD"),
            )
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("t", "005930.KS", 1, 50000, "KRW"),
            )

        c = GoodCollector()
        us = c._get_tickers(market="us")
        assert "AAPL" in us
        assert "005930.KS" not in us

    def test_filter_kr(self, db_path):
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("t", "AAPL", 1, 100, "USD"),
            )
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("t", "005930.KS", 1, 50000, "KRW"),
            )

        c = GoodCollector()
        kr = c._get_tickers(market="kr")
        assert "005930.KS" in kr
        assert "AAPL" not in kr

    def test_filter_all(self, db_path):
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("t", "AAPL", 1, 100, "USD"),
            )
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("t", "005930.KS", 1, 50000, "KRW"),
            )

        c = GoodCollector()
        all_tickers = c._get_tickers()
        assert "AAPL" in all_tickers
        assert "005930.KS" in all_tickers


class TestRetryLogic:
    def test_retry_succeeds_on_second_attempt(self):
        call_count = 0

        class RetryCollector(BaseCollector):
            def __init__(self):
                super().__init__("retry")

            def collect(self, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise ConnectionError("temporary")
                return [1, 2]

            def save(self, data):
                return len(data)

        c = RetryCollector()
        count = c.run()
        assert count == 2
        assert call_count == 2

    def test_all_retries_fail(self):
        class AlwaysFailCollector(BaseCollector):
            def __init__(self):
                super().__init__("always_fail")

            def collect(self, **kwargs):
                raise ConnectionError("down")

            def save(self, data):
                return 0

        c = AlwaysFailCollector()
        with pytest.raises(ConnectionError, match="down"):
            c.run()

    def test_failure_alert_called(self, monkeypatch):
        alert_called = False

        class AlertCollector(BaseCollector):
            def __init__(self):
                super().__init__("alert")

            def collect(self, **kwargs):
                raise RuntimeError("boom")

            def save(self, data):
                return 0

            def _send_failure_alert(self, msg):
                nonlocal alert_called
                alert_called = True

        c = AlertCollector()
        with pytest.raises(RuntimeError):
            c.run()
        assert alert_called


class TestMaxFailureRate:
    def test_constant(self):
        assert MAX_FAILURE_RATE == 0.10


# ##############################################################################
# Source: test_collectors.py
# ##############################################################################


class TestStockCollector:
    def test_period_to_start_date(self):
        from nuri.collectors.stock import StockCollector

        c = StockCollector()
        result = c._period_to_start_date("5d")
        assert len(result) == 10
        assert "-" in result


class TestTechnicalCollector:
    def test_compute_talib(self):
        import numpy as np

        from nuri.collectors.technical import TechnicalCollector

        close = np.array([100 + i * 0.5 + np.sin(i) for i in range(50)], dtype=float)
        result = TechnicalCollector._compute_talib(close)
        assert "rsi_14" in result
        assert "macd" in result
        assert len(result["rsi_14"]) == 50


# ##############################################################################
# Source: test_collectors_coverage.py
# ##############################################################################


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
        from nuri.collectors.fear_greed import FearGreedCollector

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"fear_and_greed": {"score": 62.5}}
        mock_requests.get.return_value = mock_resp
        c = FearGreedCollector()
        result = c._collect_api()
        assert len(result) == 1
        assert result[0]["value"] == 62.5


class TestCBOECollector:
    def test_instantiate(self):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        assert c.name == "cboe"

    def test_extract_pcr_total(self):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        assert c._extract_pcr({"TOTAL_PUT_CALL_RATIO": 0.85}) == 0.85

    def test_extract_pcr_simple(self):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        assert c._extract_pcr({"PUT_CALL_RATIO": 0.92}) == 0.92

    def test_extract_pcr_calculated(self):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        result = c._extract_pcr({"TOTAL_PUT_VOLUME": 1000, "TOTAL_CALL_VOLUME": 2000})
        assert abs(result - 0.5) < 0.01

    def test_extract_pcr_missing(self):
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


class TestWallStreetCollector:
    def test_instantiate(self):
        from nuri.collectors.wallstreet import WallStreetCollector

        c = WallStreetCollector()
        assert c.name == "wallstreet"

    def test_save_all_types(self, db_path):
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


class TestStockKRCollector:
    def test_instantiate(self):
        from nuri.collectors.stock_kr import StockKRCollector

        c = StockKRCollector()
        assert c.name == "stock_kr"


# ##############################################################################
# Source: test_collectors_phase2.py
# ##############################################################################


class TestCBOECollector_Phase2:
    def test_extract_pcr_ratio_key(self):
        from nuri.collectors.cboe import CBOECollector

        assert CBOECollector._extract_pcr({"TOTAL_PUT_CALL_RATIO": 0.85}) == 0.85
        assert CBOECollector._extract_pcr({"PUT_CALL_RATIO": 1.2}) == 1.2

    def test_extract_pcr_volume_calc(self):
        from nuri.collectors.cboe import CBOECollector

        result = CBOECollector._extract_pcr({
            "TOTAL_PUT_VOLUME": 1500000,
            "TOTAL_CALL_VOLUME": 2000000,
        })
        assert result == pytest.approx(0.75)

    def test_extract_pcr_missing(self):
        from nuri.collectors.cboe import CBOECollector

        assert CBOECollector._extract_pcr({}) is None
        assert CBOECollector._extract_pcr({"unrelated": 42}) is None

    def test_extract_pcr_zero_call(self):
        from nuri.collectors.cboe import CBOECollector

        assert CBOECollector._extract_pcr({
            "TOTAL_PUT_VOLUME": 100,
            "TOTAL_CALL_VOLUME": 0,
        }) is None

    @patch("nuri.collectors.cboe.requests.get")
    def test_collect_daily_json(self, mock_get):
        from nuri.collectors.cboe import CBOECollector

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"TRADE_DATE": "2026-03-28", "TOTAL_PUT_CALL_RATIO": 0.92}]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = CBOECollector()
        records = collector.collect()
        assert len(records) >= 1
        assert records[0]["indicator"] == "put_call_ratio"
        assert records[0]["value"] == 0.92
        assert records[0]["source"] == "CBOE"

    @patch("nuri.collectors.cboe.requests.get")
    def test_save_to_macro(self, mock_get, db_path):
        from nuri.collectors.cboe import CBOECollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [{"TRADE_DATE": "2026-03-28", "TOTAL_PUT_CALL_RATIO": 0.88}]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = CBOECollector()
        records = collector.collect()
        count = upsert_macro(records, db_path)
        assert count >= 1

        rows = query("SELECT * FROM macro WHERE indicator = 'put_call_ratio'", db_path=db_path)
        assert len(rows) >= 1
        assert rows[0]["value"] == pytest.approx(0.88)

    def test_parse_date_formats(self):
        from nuri.collectors.base import parse_date

        assert parse_date("2026-03-28") == "2026-03-28"
        assert parse_date("03/28/2026") == "2026-03-28"
        assert parse_date("") is None
        assert parse_date("invalid") is None
        assert parse_date("2026-03-28T12:00:00") == "2026-03-28"


class TestCoinGeckoCollector:
    @patch("nuri.collectors.coingecko.requests.get")
    def test_collect_price(self, mock_get):
        from nuri.collectors.coingecko import CoinGeckoCollector

        price_resp = MagicMock()
        price_resp.json.return_value = {
            "bitcoin": {"usd": 67500.0, "usd_market_cap": 1320000000000,
                        "usd_24h_vol": 28500000000, "usd_24h_change": -2.35}
        }
        price_resp.raise_for_status = MagicMock()

        global_resp = MagicMock()
        global_resp.json.return_value = {
            "data": {"market_cap_percentage": {"btc": 54.2},
                     "total_market_cap": {"usd": 2450000000000},
                     "active_cryptocurrencies": 14500}
        }
        global_resp.raise_for_status = MagicMock()
        mock_get.side_effect = [price_resp, global_resp]

        collector = CoinGeckoCollector()
        records = collector.collect()
        indicators = {r["indicator"]: r["value"] for r in records}
        assert indicators["btc_usd_cg"] == 67500.0
        assert indicators["btc_market_cap_t"] == pytest.approx(1.32)
        assert indicators["btc_24h_volume_b"] == pytest.approx(28.5)
        assert indicators["btc_24h_change_pct"] == -2.35
        assert indicators["btc_dominance"] == 54.2
        assert indicators["crypto_total_mcap_t"] == pytest.approx(2.45)
        assert all(r["source"] == "CoinGecko" for r in records)

    @patch("nuri.collectors.coingecko.requests.get")
    def test_save_to_macro(self, mock_get, db_path):
        from nuri.collectors.coingecko import CoinGeckoCollector

        price_resp = MagicMock()
        price_resp.json.return_value = {"bitcoin": {"usd": 70000.0}}
        price_resp.raise_for_status = MagicMock()
        global_resp = MagicMock()
        global_resp.json.return_value = {"data": {"market_cap_percentage": {}, "active_cryptocurrencies": None}}
        global_resp.raise_for_status = MagicMock()
        mock_get.side_effect = [price_resp, global_resp]

        collector = CoinGeckoCollector()
        records = collector.collect()
        count = upsert_macro(records, db_path)
        assert count >= 1
        rows = query("SELECT * FROM macro WHERE indicator = 'btc_usd_cg'", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["value"] == 70000.0

    @patch("nuri.collectors.coingecko.requests.get")
    def test_partial_failure(self, mock_get):
        from nuri.collectors.coingecko import CoinGeckoCollector

        price_resp = MagicMock()
        price_resp.json.return_value = {"bitcoin": {"usd": 65000.0}}
        price_resp.raise_for_status = MagicMock()
        mock_get.side_effect = [price_resp, Exception("global API down")]

        collector = CoinGeckoCollector()
        records = collector.collect()
        assert len(records) >= 1
        assert records[0]["indicator"] == "btc_usd_cg"


class TestFINVIZCollector_Phase2:
    @patch("nuri.collectors.finviz.FINVIZCollector._fetch_signal_tickers")
    def test_fetch_signal_tickers(self, mock_fetch):
        from nuri.collectors.finviz import FINVIZCollector

        mock_fetch.return_value = {"TSLA", "NVDA", "AAPL", "MSFT"}
        collector = FINVIZCollector()
        tickers = collector._fetch_signal_tickers("Oversold")
        assert "TSLA" in tickers
        assert len(tickers) == 4

    @patch("nuri.collectors.finviz.FINVIZCollector._fetch_signal_tickers")
    @patch("nuri.collectors.finviz.FINVIZCollector._get_tickers")
    def test_collect_filters_held(self, mock_tickers, mock_fetch):
        from nuri.collectors.finviz import FINVIZCollector

        mock_tickers.return_value = ["TSLA", "NVDA", "AAPL"]
        mock_fetch.side_effect = [
            {"TSLA", "MSFT", "GME"}, set(), {"NVDA"}, set(), set(), {"TSLA", "AAPL"},
        ]
        collector = FINVIZCollector()
        records = collector.collect()
        tickers_found = {r["ticker"] for r in records}
        assert "TSLA" in tickers_found
        assert "GME" not in tickers_found

    def test_save_to_external_analysis(self, db_with_us_tickers):
        from nuri.collectors.finviz import FINVIZCollector

        collector = FINVIZCollector()
        data = [
            {"date": "2026-03-28", "ticker": "TSLA", "signal": "oversold_rsi", "source": "FINVIZ"},
            {"date": "2026-03-28", "ticker": "NVDA", "signal": "new_high", "source": "FINVIZ"},
        ]
        count = collector.save(data, db_path=db_with_us_tickers)
        assert count == 2

    @patch("nuri.collectors.finviz.FINVIZCollector._get_tickers")
    def test_collect_no_holdings(self, mock_tickers):
        from nuri.collectors.finviz import FINVIZCollector

        mock_tickers.return_value = []
        collector = FINVIZCollector()
        assert collector.collect() == []


class TestRedditCollector:
    def test_count_mentions_dollar_sign(self):
        from nuri.collectors.reddit import RedditCollector

        collector = RedditCollector()
        posts = [
            {"title": "$TSLA to the moon!", "selftext": "Buy $NVDA too"},
            {"title": "What about $TSLA?", "selftext": ""},
        ]
        counts = collector._count_mentions(posts, {"TSLA", "NVDA", "AAPL"})
        assert counts["TSLA"] == 2
        assert counts["NVDA"] == 1

    def test_count_mentions_uppercase(self):
        from nuri.collectors.reddit import RedditCollector

        collector = RedditCollector()
        posts = [{"title": "TSLA earnings tomorrow", "selftext": "NVDA looking good"}]
        counts = collector._count_mentions(posts, {"TSLA", "NVDA"})
        assert counts["TSLA"] == 1
        assert counts["NVDA"] == 1

    def test_noise_words_filtered(self):
        from nuri.collectors.reddit import RedditCollector

        collector = RedditCollector()
        posts = [{"title": "CEO of THE company IS great", "selftext": "BUY NOW OR NOT"}]
        counts = collector._count_mentions(posts, set())
        assert counts.get("THE", 0) == 0
        assert counts.get("CEO", 0) == 0
        assert counts.get("BUY", 0) == 0

    @patch("nuri.collectors.reddit.requests.get")
    @patch("nuri.collectors.reddit.RedditCollector._get_tickers")
    def test_collect_with_mock_api(self, mock_tickers, mock_get):
        from nuri.collectors.reddit import RedditCollector

        mock_tickers.return_value = ["TSLA", "NVDA"]
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"title": "$TSLA yolo", "selftext": "diamond hands TSLA"},
                {"title": "NVDA earnings beat", "selftext": "$TSLA also up"},
                {"title": "Market crash incoming", "selftext": "sell everything"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = RedditCollector()
        records = collector.collect()
        indicators = {r["indicator"]: r["value"] for r in records}
        assert indicators["wsb_post_count"] == 3.0
        assert indicators["wsb_held_mentions"] == 2.0

    @patch("nuri.collectors.reddit.requests.get")
    @patch("nuri.collectors.reddit.RedditCollector._get_tickers")
    def test_save_to_macro(self, mock_tickers, mock_get, db_path):
        from nuri.collectors.reddit import RedditCollector

        mock_tickers.return_value = ["TSLA"]
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [{"title": "$TSLA", "selftext": ""}]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = RedditCollector()
        records = collector.collect()
        count = upsert_macro(records, db_path)
        assert count >= 1

    @patch("nuri.collectors.reddit.requests.get")
    @patch("nuri.collectors.reddit.RedditCollector._get_tickers")
    def test_api_failure_returns_empty(self, mock_tickers, mock_get):
        from nuri.collectors.reddit import RedditCollector

        mock_tickers.return_value = ["TSLA"]
        mock_get.side_effect = Exception("connection error")
        collector = RedditCollector()
        records = collector.collect()
        assert records == []


class TestFREDCalendarCollector:
    def test_fallback_calendar(self):
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        collector = FREDCalendarCollector()
        collector.api_key = ""
        records = collector.collect(days_ahead=365)
        assert isinstance(records, list)
        for r in records:
            assert r["event_type"] == "economic"

    @patch("nuri.collectors.fred_calendar.requests.get")
    def test_collect_fred_api(self, mock_get):
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "release_dates": [
                {"release_id": 10, "date": "2026-04-14"},
                {"release_id": 50, "date": "2026-04-03"},
                {"release_id": 999, "date": "2026-04-10"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = FREDCalendarCollector()
        collector.api_key = "test_key"
        records = collector.collect()
        assert len(records) == 2
        descriptions = {r["description"] for r in records}
        assert "FRED: CPI" in descriptions

    def test_negative_days_ahead_defaults(self):
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        collector = FREDCalendarCollector()
        collector.api_key = ""
        records = collector.collect(days_ahead=-5)
        assert isinstance(records, list)


# ##############################################################################
# Source: test_coverage_round3.py
# ##############################################################################


class TestExternalSave:
    def test_save_external(self, db_path):
        from nuri.collectors.external import save_external

        assert save_external("tipranks", "AAPL", "consensus", "Strong Buy", 4.5) is True

    def test_save_tipranks(self, db_path):
        from nuri.collectors.external import save_tipranks

        save_tipranks("AAPL", "Strong Buy", 230.0, 30)

    def test_save_superinvestor(self, db_path):
        from nuri.collectors.external import save_superinvestor

        save_superinvestor("AAPL", 5, "increasing")

    def test_get_external(self, db_path):
        from nuri.collectors.external import get_external, save_external

        save_external("test_src", "AAPL", "rating", "Buy", 4.0)
        result = get_external("AAPL")
        assert isinstance(result, list)

    def test_get_external_summary(self, db_path):
        from nuri.collectors.external import get_external_summary, save_external

        save_external("test", "AAPL", "score", "high", 9.0)
        summary = get_external_summary()
        assert isinstance(summary, dict)

    def test_print_summary(self, db_path, capsys):
        from nuri.collectors.external import print_summary, save_external

        save_external("test", "AAPL", "score", "high", 9.0)
        print_summary()
        output = capsys.readouterr().out
        assert len(output) > 0


# ##############################################################################
# Source: test_coverage_round4.py
# ##############################################################################


class TestWallStreetDeep:
    def test_collect_and_save(self, rich_db):
        from nuri.collectors.wallstreet import WallStreetCollector

        mock_ticker = MagicMock()
        mock_ticker.upgrades_downgrades = pd.DataFrame([
            {"GradeDate": pd.Timestamp("2026-03-01"), "Firm": "GS",
             "ToGrade": "Buy", "FromGrade": "Hold", "Action": "upgrade"},
        ])
        mock_ticker.earnings_history = pd.DataFrame([
            {"Quarter": pd.Timestamp("2026-01-01"), "epsActual": 2.1,
             "epsEstimate": 1.9, "surprisePercent": 10.5},
        ])
        mock_ticker.insider_transactions = pd.DataFrame([
            {"startDate": pd.Timestamp("2026-03-20"), "insiderName": "Tim Cook",
             "position": "CEO", "transactionType": "Sale",
             "shares": 50000, "value": 9500000},
        ])
        mock_ticker.info = {"shortPercentOfFloat": 0.008, "shortRatio": 1.2}

        c = WallStreetCollector()
        with patch("yfinance.Ticker", return_value=mock_ticker):
            data = c.collect()
        assert "ratings" in data
        count = c.save(data)
        assert count > 0

    def test_collect_empty_data(self, rich_db):
        from nuri.collectors.wallstreet import WallStreetCollector

        mock_ticker = MagicMock()
        mock_ticker.upgrades_downgrades = None
        mock_ticker.earnings_history = None
        mock_ticker.insider_transactions = None
        mock_ticker.info = {}

        c = WallStreetCollector()
        with patch("yfinance.Ticker", return_value=mock_ticker):
            data = c.collect()
        assert isinstance(data, dict)


class TestEtfFlowsDeep:
    def test_collect_with_obb_mock(self, rich_db):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        c = EtfFlowsCollector()
        with patch.object(c, "collect", return_value=[
            {"ticker": "SPY", "date": "2026-03-30", "name": "SPDR S&P 500",
             "total_assets": 500e9, "volume_avg": 80000000, "nav_price": 520.0},
        ]):
            data = c.collect()
            count = c.save(data)
        assert count == 1

    def test_analyze_sector_rotation(self, rich_db):
        from nuri.collectors.etf_flows import analyze_sector_rotation

        result = analyze_sector_rotation(days=30)
        assert result is None or isinstance(result, pd.DataFrame)


class TestInstitutionalDeep:
    def test_save_records(self, rich_db):
        from nuri.collectors.institutional import InstitutionalCollector

        c = InstitutionalCollector()
        data = [
            {"ticker": "005930.KS", "date": "2026-03-30", "market": "KOSPI",
             "institution_net": 1000000, "foreign_net": 500000,
             "individual_net": -1500000, "source": "pykrx"},
        ]
        count = c.save(data)
        assert count >= 0


# ##############################################################################
# Source: test_coverage_round5.py
# ##############################################################################


class TestFilings:
    def test_parse_10k_no_filings(self):
        mock_co = MagicMock()
        mock_co.get_filings.return_value = []
        with patch("edgar.Company", return_value=mock_co), patch("edgar.set_identity"):
            from nuri.collectors.filings import parse_10k

            result = parse_10k("AAPL")
        assert result is None

    def test_collect_filings_empty(self, rich_db):
        from nuri.collectors.filings import collect_filings

        with patch("nuri.collectors.filings.parse_10k", return_value=None):
            result = collect_filings(tickers=["AAPL"])
        assert isinstance(result, list)

    def test_collect_filings_with_data(self, rich_db):
        from nuri.collectors.filings import collect_filings

        mock_data = {
            "ticker": "AAPL", "filing_date": "2026-01-15",
            "revenue": 400e9, "net_income": 100e9,
            "total_assets": 350e9, "total_debt": 120e9,
        }
        with patch("nuri.collectors.filings.parse_10k", return_value=mock_data):
            result = collect_filings(tickers=["AAPL"])
        assert len(result) == 1


class TestSuperinvestorsDeep:
    def test_collect_no_filings(self):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_co = MagicMock()
        mock_co.get_filings.return_value = []
        with patch("edgar.Company", return_value=mock_co), patch("edgar.set_identity"):
            c = SuperinvestorCollector()
            result = c.collect(num_quarters=1)
        assert isinstance(result, list)

    def test_collect_filing_parse_error(self):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_filing = MagicMock()
        mock_filing.filing_date = "2026-02-14"
        mock_filing.obj.side_effect = Exception("parse error")
        mock_co = MagicMock()
        mock_co.get_filings.return_value = [mock_filing]
        with patch("edgar.Company", return_value=mock_co), patch("edgar.set_identity"):
            c = SuperinvestorCollector()
            result = c.collect(num_quarters=1)
        assert isinstance(result, list)


class TestCBOEDeep_R5:
    def test_collect_daily_mock(self):
        from nuri.collectors.cboe import CBOECollector

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"TRADE_DATE": "2026-03-30", "TOTAL_PUT_CALL_RATIO": 0.85}]
        }
        c = CBOECollector()
        with patch("nuri.collectors.cboe.requests") as mock_req:
            mock_req.get.return_value = mock_resp
            result = c._collect_daily()
        assert isinstance(result, list)

    def test_collect_daily_failure(self):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        with patch.object(c, "_collect_daily", return_value=[]):
            result = c._collect_daily()
        assert isinstance(result, list)
        assert len(result) == 0


# ##############################################################################
# Source: test_coverage_round6.py
# ##############################################################################


class TestCBOEDeep_R6:
    def test_collect_daily_success(self):
        from nuri.collectors.cboe import CBOECollector

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"TRADE_DATE": "2026-03-30", "TOTAL_PUT_CALL_RATIO": 0.85}]
        }
        c = CBOECollector()
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c._collect_daily()
        assert isinstance(result, list)
        if result:
            assert result[0]["value"] == 0.85

    def test_collect_totalpc(self):
        from nuri.collectors.cboe import CBOECollector

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"TRADE_DATE": "2026-03-29", "TOTAL_PUT_CALL_RATIO": 0.90},
                {"TRADE_DATE": "2026-03-28", "TOTAL_PUT_CALL_RATIO": 0.88},
            ]
        }
        c = CBOECollector()
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c._collect_totalpc()
        assert isinstance(result, list)

    def test_collect_full(self, rich_db):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"TRADE_DATE": "2026-03-30", "TOTAL_PUT_CALL_RATIO": 0.85}]
        }
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c.collect()
        assert isinstance(result, list)


# ##############################################################################
# Source: test_coverage_round8.py
# ##############################################################################


class TestFilingsDeep:
    def test_parse_10k_with_data(self):
        mock_filing = MagicMock()
        mock_filing.filing_date = "2026-01-15"
        mock_obj = MagicMock()
        mock_obj.financials = MagicMock()
        mock_filing.obj.return_value = mock_obj
        mock_co = MagicMock()
        mock_co.get_filings.return_value = [mock_filing]
        with patch("edgar.Company", return_value=mock_co), patch("edgar.set_identity"):
            from nuri.collectors.filings import parse_10k

            result = parse_10k("AAPL")
        assert result is None or isinstance(result, dict)

    def test_collect_filings_multiple(self):
        from nuri.collectors.filings import collect_filings

        mock_data = {"ticker": "AAPL", "filing_date": "2026-01-15",
                     "revenue": 400e9, "net_income": 100e9}
        with patch("nuri.collectors.filings.parse_10k", return_value=mock_data):
            result = collect_filings(tickers=["AAPL", "NVDA"])
        assert len(result) == 2


# ##############################################################################
# Source: test_coverage_round9.py
# ##############################################################################


class TestSuperinvestorsCollect:
    def test_collect_with_infotable(self):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_info = MagicMock()
        mock_info.infotable = pd.DataFrame([
            {"nameOfIssuer": "Apple Inc", "cusip": "037833100",
             "value": 171000, "sshPrnamt": 900000, "sshPrnamtType": "SH"},
        ])
        mock_filing = MagicMock()
        mock_filing.filing_date = "2026-02-14"
        mock_filing.obj.return_value = mock_info
        mock_co = MagicMock()
        mock_co.get_filings.return_value = [mock_filing]
        with patch("edgar.Company", return_value=mock_co), patch("edgar.set_identity"):
            c = SuperinvestorCollector()
            result = c.collect(num_quarters=1)
        assert isinstance(result, list)

    def test_run_full(self):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_info = MagicMock()
        mock_info.infotable = pd.DataFrame([
            {"nameOfIssuer": "Apple Inc", "cusip": "037833100",
             "value": 171000, "sshPrnamt": 900000, "sshPrnamtType": "SH"},
        ])
        mock_filing = MagicMock()
        mock_filing.filing_date = "2026-02-14"
        mock_filing.obj.return_value = mock_info
        mock_co = MagicMock()
        mock_co.get_filings.return_value = [mock_filing]
        with patch("edgar.Company", return_value=mock_co), patch("edgar.set_identity"):
            c = SuperinvestorCollector()
            c.run(num_quarters=1)


class TestCBOEFull:
    def test_collect_with_fallback(self):
        from nuri.collectors.cboe import CBOECollector

        mock_daily = MagicMock()
        mock_daily.status_code = 200
        mock_daily.json.return_value = {
            "data": [{"TRADE_DATE": "2026-03-30", "TOTAL_PUT_CALL_RATIO": 0.85}]
        }
        mock_fail = MagicMock()
        mock_fail.status_code = 500

        c = CBOECollector()
        with patch("nuri.collectors.cboe.requests.get",
                    side_effect=[mock_daily, mock_fail]):
            daily = c._collect_daily()
            totalpc = c._collect_totalpc()
        assert len(daily) > 0
        assert len(totalpc) == 0


class TestInstitutionalCollect:
    def test_collect_and_save(self, rich_db):
        from nuri.collectors.institutional import InstitutionalCollector

        c = InstitutionalCollector()
        mock_df = pd.DataFrame({
            "기관합계": [1000000, 2000000],
            "외국인합계": [500000, 600000],
            "개인": [-1500000, -2600000],
        }, index=pd.date_range("2026-03-29", periods=2))
        with patch("pykrx.stock.get_market_trading_value_by_date", return_value=mock_df):
            result = c.collect()
        assert isinstance(result, list)
        if result:
            count = c.save(result)
            assert count >= 0


class TestEtfFlowsFull:
    def test_collect_mock(self, rich_db):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        c = EtfFlowsCollector()
        with patch.object(c, "collect", return_value=[
            {"ticker": "SPY", "date": "2026-03-30", "name": "SPDR S&P 500",
             "total_assets": 500e9, "volume_avg": 80000000, "nav_price": 520},
        ]):
            result = c.collect()
            count = c.save(result)
        assert count == 1


# ##############################################################################
# Source: test_coverage_round11.py
# ##############################################################################


class TestFilingsSave:
    def test_save_filings(self, rich_db):
        from nuri.collectors.filings import collect_filings

        mock_data = {"ticker": "AAPL", "filing_date": "2026-01-15",
                     "revenue": 400e9, "net_income": 100e9,
                     "total_assets": 350e9, "total_debt": 120e9}
        with patch("nuri.collectors.filings.parse_10k", return_value=mock_data):
            result = collect_filings(tickers=["AAPL"])
        assert len(result) == 1


# ##############################################################################
# Source: test_coverage_round13.py
# ##############################################################################


class TestSuperinvestorsMultiple:
    def test_collect_multi_investor(self):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_info = MagicMock()
        mock_info.infotable = pd.DataFrame([
            {"nameOfIssuer": "Apple", "cusip": "037", "value": 100,
             "sshPrnamt": 1000, "sshPrnamtType": "SH"},
        ])
        mock_filing = MagicMock()
        mock_filing.filing_date = "2026-02-14"
        mock_filing.obj.return_value = mock_info
        mock_co = MagicMock()
        mock_co.get_filings.return_value = [mock_filing]
        with patch("edgar.Company", return_value=mock_co), patch("edgar.set_identity"):
            c = SuperinvestorCollector()
            result = c.collect(num_quarters=1)
        assert isinstance(result, list)

    def test_print_superinvestors(self, rich_db, capsys):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        c = SuperinvestorCollector()
        c.save([])


# ##############################################################################
# Source: test_coverage_round15.py
# ##############################################################################


class TestFilingsRealLike:
    def test_parse_with_financials(self):
        mock_filing = MagicMock()
        mock_filing.filing_date = "2026-01-15"
        mock_obj = MagicMock()
        mock_obj.financials = {"income": {"revenue": 400e9}, "balance": {"assets": 350e9}}
        mock_filing.obj.return_value = mock_obj
        mock_co = MagicMock()
        mock_co.get_filings.return_value = [mock_filing]
        with patch("edgar.Company", return_value=mock_co), patch("edgar.set_identity"):
            from nuri.collectors.filings import parse_10k

            result = parse_10k("MSFT")
        assert result is None or isinstance(result, dict)

    def test_collect_save_flow(self, rich_db):
        from nuri.collectors.filings import collect_filings

        with patch("nuri.collectors.filings.parse_10k", return_value={
            "ticker": "AAPL", "filing_date": "2026-01-15",
            "revenue": 400e9, "net_income": 100e9,
        }):
            result = collect_filings(tickers=["AAPL", "NVDA", "TSLA"])
        assert len(result) == 3


# ##############################################################################
# Source: test_coverage_round17.py
# ##############################################################################


class TestSuperinvestorCollector_R17:
    def test_collect_success(self, rich_db):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        infotable = pd.DataFrame({
            "Ticker": ["AAPL", "AAPL", "NVDA"],
            "Value": [100e6, 50e6, 200e6],
            "SharesPrnAmount": [500000, 250000, 1000000],
            "Issuer": ["Apple Inc", "Apple Inc", "NVIDIA Corp"],
        })
        mock_filing_obj = MagicMock()
        mock_filing_obj.infotable = infotable
        mock_filing = MagicMock()
        mock_filing.filing_date = date(2025, 3, 1)
        mock_filing.obj.return_value = mock_filing_obj
        mock_filings = MagicMock()
        mock_filings.__len__ = lambda self: 1
        mock_filings.__getitem__ = lambda self, idx: [mock_filing][idx]
        mock_filings.__iter__ = lambda self: iter([mock_filing])
        mock_filings.__bool__ = lambda self: True
        mock_company = MagicMock()
        mock_company.get_filings.return_value = mock_filings

        with patch("nuri.collectors.superinvestors.SUPERINVESTORS", {"TestInvestor": "0001234567"}):
            with patch("edgar.set_identity"):
                with patch("edgar.Company", return_value=mock_company):
                    c = SuperinvestorCollector()
                    result = c.collect(quarters=1)

        assert len(result) == 2
        aapl = [r for r in result if r["ticker"] == "AAPL"][0]
        assert aapl["shares"] == 750000

    def test_collect_empty_filings(self, rich_db):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_company = MagicMock()
        mock_company.get_filings.return_value = []
        with patch("nuri.collectors.superinvestors.SUPERINVESTORS", {"NoFiling": "000000"}):
            with patch("edgar.set_identity"):
                with patch("edgar.Company", return_value=mock_company):
                    c = SuperinvestorCollector()
                    result = c.collect()
        assert result == []

    def test_collect_filing_parse_error(self, rich_db):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_filing = MagicMock()
        mock_filing.filing_date = date(2025, 1, 1)
        mock_filing.obj.side_effect = RuntimeError("parse failure")
        mock_filings = MagicMock()
        mock_filings.__len__ = lambda self: 1
        mock_filings.__getitem__ = lambda self, idx: [mock_filing][idx]
        mock_filings.__iter__ = lambda self: iter([mock_filing])
        mock_filings.__bool__ = lambda self: True
        mock_company = MagicMock()
        mock_company.get_filings.return_value = mock_filings
        with patch("nuri.collectors.superinvestors.SUPERINVESTORS", {"Bad": "000001"}):
            with patch("edgar.set_identity"):
                with patch("edgar.Company", return_value=mock_company):
                    c = SuperinvestorCollector()
                    result = c.collect(quarters=1)
        assert result == []

    def test_collect_empty_infotable(self, rich_db):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_filing_obj = MagicMock()
        mock_filing_obj.infotable = pd.DataFrame()
        mock_filing = MagicMock()
        mock_filing.filing_date = date(2025, 2, 1)
        mock_filing.obj.return_value = mock_filing_obj
        mock_filings = MagicMock()
        mock_filings.__len__ = lambda self: 1
        mock_filings.__getitem__ = lambda self, idx: [mock_filing][idx]
        mock_filings.__iter__ = lambda self: iter([mock_filing])
        mock_filings.__bool__ = lambda self: True
        mock_company = MagicMock()
        mock_company.get_filings.return_value = mock_filings
        with patch("nuri.collectors.superinvestors.SUPERINVESTORS", {"Empty": "000002"}):
            with patch("edgar.set_identity"):
                with patch("edgar.Company", return_value=mock_company):
                    c = SuperinvestorCollector()
                    result = c.collect(quarters=1)
        assert result == []

    def test_collect_nan_ticker_skipped(self, rich_db):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        infotable = pd.DataFrame({
            "Ticker": [None, "MSFT"],
            "Value": [100e6, 200e6],
            "SharesPrnAmount": [500000, 1000000],
            "Issuer": ["Unknown", "Microsoft"],
        })
        mock_filing_obj = MagicMock()
        mock_filing_obj.infotable = infotable
        mock_filing = MagicMock()
        mock_filing.filing_date = date(2025, 3, 1)
        mock_filing.obj.return_value = mock_filing_obj
        mock_filings = MagicMock()
        mock_filings.__len__ = lambda self: 1
        mock_filings.__getitem__ = lambda self, idx: [mock_filing][idx]
        mock_filings.__iter__ = lambda self: iter([mock_filing])
        mock_filings.__bool__ = lambda self: True
        mock_company = MagicMock()
        mock_company.get_filings.return_value = mock_filings
        with patch("nuri.collectors.superinvestors.SUPERINVESTORS", {"NaN": "000003"}):
            with patch("edgar.set_identity"):
                with patch("edgar.Company", return_value=mock_company):
                    c = SuperinvestorCollector()
                    result = c.collect(quarters=1)
        tickers = [r["ticker"] for r in result]
        assert None not in tickers
        assert "MSFT" in tickers

    def test_save_and_upsert(self, rich_db):
        from nuri.collectors.superinvestors import SuperinvestorCollector, _upsert_superinvestors

        records = [{
            "investor": "Buffett", "filing_date": "2025-03-15", "ticker": "AAPL",
            "shares": 900000000, "market_value": 171e9, "portfolio_pct": 48.5,
            "issuer_name": "Apple Inc",
        }]
        c = SuperinvestorCollector()
        count = c.save(records)
        assert count == 1
        assert c.save([]) == 0
        assert c.save(None) == 0
        assert _upsert_superinvestors([]) == 0

    def test_detect_changes(self, rich_db):
        from nuri.collectors.superinvestors import detect_changes

        with get_db(rich_db) as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO superinvestors
                   (investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    ("Test", "2025-01-15", "AAPL", 1000, 150000, 50.0, "Apple"),
                    ("Test", "2025-01-15", "GOOG", 500, 100000, 33.0, "Alphabet"),
                    ("Test", "2025-01-15", "MSFT", 200, 50000, 17.0, "Microsoft"),
                    ("Test", "2025-04-15", "AAPL", 1500, 225000, 45.0, "Apple"),
                    ("Test", "2025-04-15", "MSFT", 200, 52000, 17.0, "Microsoft"),
                    ("Test", "2025-04-15", "NVDA", 300, 100000, 38.0, "NVIDIA"),
                ],
            )
        df = detect_changes("Test", db_path=rich_db)
        assert not df.empty
        types = dict(zip(df["ticker"], df["change_type"]))
        assert types["AAPL"] == "INCREASED"
        assert types["GOOG"] == "CLOSED"
        assert types["MSFT"] == "UNCHANGED"
        assert types["NVDA"] == "NEW"

    def test_detect_changes_fewer_than_2_quarters(self, rich_db):
        from nuri.collectors.superinvestors import detect_changes

        with get_db(rich_db) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO superinvestors
                   (investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("Solo", "2025-01-15", "AAPL", 1000, 150000, 100.0, "Apple"),
            )
        df = detect_changes("Solo", db_path=rich_db)
        assert df.empty

    def test_detect_changes_decreased(self, rich_db):
        from nuri.collectors.superinvestors import detect_changes

        with get_db(rich_db) as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO superinvestors
                   (investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    ("Dec", "2025-01-15", "AAPL", 1000, 150000, 100.0, "Apple"),
                    ("Dec", "2025-04-15", "AAPL", 500, 75000, 100.0, "Apple"),
                ],
            )
        df = detect_changes("Dec", db_path=rich_db)
        assert df.iloc[0]["change_type"] == "DECREASED"


class TestFilingsCollector_R17:
    def _mock_income_df(self):
        return pd.DataFrame({
            "concept": ["Revenue", "NetIncome", "OperatingIncome"],
            "dimension": [False, False, False],
            "is_breakdown": [False, False, False],
            "2024": [100e9, 25e9, 30e9],
        })

    def _mock_balance_df(self):
        return pd.DataFrame({
            "concept": ["Assets", "Liabilities", "CashAndCashEquivalents"],
            "dimension": [False, False, False],
            "is_breakdown": [False, False, False],
            "2024": [400e9, 250e9, 60e9],
        })

    def test_parse_10k_success(self):
        from nuri.collectors.filings import parse_10k

        mock_inc = MagicMock()
        mock_inc.to_dataframe.return_value = self._mock_income_df()
        mock_bs = MagicMock()
        mock_bs.to_dataframe.return_value = self._mock_balance_df()
        mock_obj = MagicMock()
        mock_obj.income_statement = mock_inc
        mock_obj.balance_sheet = mock_bs
        mock_filing = MagicMock()
        mock_filing.filing_date = date(2025, 2, 1)
        mock_filing.obj.return_value = mock_obj
        mock_filings = MagicMock()
        mock_filings.__len__ = lambda self: 1
        mock_filings.__getitem__ = lambda self, idx: mock_filing
        mock_filings.__bool__ = lambda self: True
        mock_company = MagicMock()
        mock_company.get_filings.return_value = mock_filings

        with patch("edgar.set_identity"):
            with patch("edgar.Company", return_value=mock_company):
                result = parse_10k("AAPL")
        assert result is not None
        assert result["ticker"] == "AAPL"
        assert result["revenue"] == 100e9

    def test_parse_10k_no_filings(self):
        from nuri.collectors.filings import parse_10k

        mock_company = MagicMock()
        mock_company.get_filings.return_value = []
        with patch("edgar.set_identity"):
            with patch("edgar.Company", return_value=mock_company):
                result = parse_10k("FAKE")
        assert result is None

    def test_parse_10k_exception(self):
        from nuri.collectors.filings import parse_10k

        with patch("edgar.set_identity"):
            with patch("edgar.Company", side_effect=RuntimeError("network")):
                result = parse_10k("FAIL")
        assert result is None

    def test_parse_10k_income_exception(self):
        from nuri.collectors.filings import parse_10k

        mock_bs = MagicMock()
        mock_bs.to_dataframe.return_value = self._mock_balance_df()
        mock_obj = MagicMock()
        mock_obj.income_statement = None
        mock_obj.balance_sheet = mock_bs
        mock_filing = MagicMock()
        mock_filing.filing_date = date(2025, 2, 1)
        mock_filing.obj.return_value = mock_obj
        mock_filings = MagicMock()
        mock_filings.__len__ = lambda self: 1
        mock_filings.__getitem__ = lambda self, idx: mock_filing
        mock_filings.__bool__ = lambda self: True
        mock_company = MagicMock()
        mock_company.get_filings.return_value = mock_filings
        with patch("edgar.set_identity"):
            with patch("edgar.Company", return_value=mock_company):
                result = parse_10k("AAPL")
        assert result is not None
        assert "total_assets" in result

    def test_collect_filings_with_tickers(self):
        from nuri.collectors.filings import collect_filings

        fake_result = {"ticker": "AAPL", "filing_date": "2025-02-01", "form": "10-K", "revenue": 100e9}
        with patch("nuri.collectors.filings.parse_10k", return_value=fake_result):
            results = collect_filings(tickers=["AAPL"])
        assert len(results) == 1

    def test_collect_filings_skips_none(self):
        from nuri.collectors.filings import collect_filings

        with patch("nuri.collectors.filings.parse_10k", return_value=None):
            results = collect_filings(tickers=["FAKE"])
        assert results == []

    def test_print_filings_empty(self, capsys):
        from nuri.collectors.filings import print_filings

        print_filings([])
        out = capsys.readouterr().out
        assert "없음" in out

    def test_print_filings_with_data(self, capsys):
        from nuri.collectors.filings import print_filings

        data = [{"ticker": "AAPL", "filing_date": "2025-02-01", "revenue": 100e9,
                 "net_income": 25e9, "total_assets": 400e9, "cash": 60e9}]
        print_filings(data)
        out = capsys.readouterr().out
        assert "AAPL" in out


class TestEtfFlowsCollector_R17:
    def test_collect_success(self, rich_db):
        from nuri.collectors.etf_flows import _upsert_etf_flows

        records = [{"ticker": "XLK", "date": "2025-03-15", "name": "Technology Select SPDR",
                     "total_assets": 50e9, "volume_avg": 10000000.0, "nav_price": 200.0}]
        count = _upsert_etf_flows(records, db_path=rich_db)
        assert count == 1

    def test_upsert_etf_flows_empty(self, rich_db):
        from nuri.collectors.etf_flows import _upsert_etf_flows

        assert _upsert_etf_flows([], db_path=rich_db) == 0

    def test_save_empty(self, rich_db):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        c = EtfFlowsCollector()
        assert c.save([]) == 0
        assert c.save(None) == 0

    def test_analyze_sector_rotation_with_data(self, rich_db):
        from nuri.collectors.etf_flows import _upsert_etf_flows, analyze_sector_rotation

        records = []
        for d in ["2025-03-01", "2025-03-08", "2025-03-15", "2025-03-22"]:
            for ticker, aum in [("XLK", 50e9 + int(d[-2:]) * 1e8), ("XLF", 30e9 + int(d[-2:]) * 5e7)]:
                records.append({"ticker": ticker, "date": d, "name": f"Test {ticker}",
                                "total_assets": aum, "volume_avg": 10000000.0, "nav_price": 200.0})
        _upsert_etf_flows(records, db_path=rich_db)
        df = analyze_sector_rotation(db_path=rich_db)
        assert df is not None
        assert not df.empty

    def test_analyze_sector_rotation_insufficient_data(self, rich_db):
        from nuri.collectors.etf_flows import analyze_sector_rotation

        result = analyze_sector_rotation(db_path=rich_db)
        assert result is None

    def test_analyze_sector_rotation_single_day(self, rich_db):
        from nuri.collectors.etf_flows import _upsert_etf_flows, analyze_sector_rotation

        _upsert_etf_flows([{"ticker": "XLK", "date": "2025-03-15", "name": "Technology",
                            "total_assets": 50e9, "volume_avg": 10000000.0, "nav_price": 200.0}],
                          db_path=rich_db)
        result = analyze_sector_rotation(db_path=rich_db)
        assert result is None

    def test_print_sector_rotation_none(self, capsys):
        from nuri.collectors.etf_flows import print_sector_rotation

        print_sector_rotation(None)
        out = capsys.readouterr().out
        assert "없음" in out

    def test_print_sector_rotation_with_data(self, capsys):
        from nuri.collectors.etf_flows import print_sector_rotation

        df = pd.DataFrame([{"ticker": "XLK", "sector": "Technology", "aum_current": 50e9,
                            "aum_prev": 48e9, "aum_change_pct": 4.17, "volume_trend_pct": 2.5}])
        print_sector_rotation(df)
        out = capsys.readouterr().out
        assert "XLK" in out


class TestExternalCollector_R17:
    def test_save_external_success(self, rich_db):
        from nuri.collectors.external import save_external

        assert save_external("tipranks", "AAPL", "consensus", "Strong Buy", db_path=rich_db) is True

    def test_save_external_unknown_source(self, rich_db):
        from nuri.collectors.external import save_external

        assert save_external("unknown_source", "AAPL", "test", "val", db_path=rich_db) is False

    def test_save_tipranks(self, rich_db):
        from nuri.collectors.external import get_external, save_tipranks

        save_tipranks("NVDA", "Strong Buy", 273.61, 38, upside_pct=63.0, db_path=rich_db)
        data = get_external("NVDA", source="tipranks", db_path=rich_db)
        assert len(data) >= 3

    def test_save_superinvestor(self, rich_db):
        from nuri.collectors.external import get_external, save_superinvestor

        save_superinvestor("AAPL", 14, "buying", details="Buffett +5%", db_path=rich_db)
        data = get_external("AAPL", source="dataroma", db_path=rich_db)
        assert len(data) >= 2

    def test_get_external_no_source(self, rich_db):
        from nuri.collectors.external import get_external, save_external

        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=rich_db)
        save_external("dataroma", "AAPL", "count", "10", db_path=rich_db)
        data = get_external("AAPL", db_path=rich_db)
        sources = {d["source"] for d in data}
        assert "tipranks" in sources

    def test_get_external_empty(self, rich_db):
        from nuri.collectors.external import get_external

        assert get_external("ZZZZ", db_path=rich_db) == []

    def test_get_external_summary(self, rich_db):
        from nuri.collectors.external import get_external_summary, save_external

        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=rich_db)
        summary = get_external_summary(db_path=rich_db)
        assert summary["total_records"] >= 1

    def test_get_external_summary_empty(self, rich_db):
        from nuri.collectors.external import get_external_summary

        summary = get_external_summary(db_path=rich_db)
        assert summary["total_records"] == 0

    def test_save_external_with_numeric(self, rich_db):
        from nuri.collectors.external import get_external, save_external

        save_external("tipranks", "TSLA", "target_price", "400.0", numeric_value=400.0, db_path=rich_db)
        data = get_external("TSLA", source="tipranks", db_path=rich_db)
        assert data[0]["numeric_value"] == 400.0

    def test_print_summary(self, rich_db, capsys):
        from nuri.collectors.external import print_summary, save_external

        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=rich_db)
        print_summary(db_path=rich_db)
        out = capsys.readouterr().out
        assert "tipranks" in out.lower() or "TipRanks" in out

    def test_print_ticker_external_empty(self, rich_db, capsys):
        from nuri.collectors.external import print_ticker_external

        print_ticker_external("ZZZZ", db_path=rich_db)
        out = capsys.readouterr().out
        assert "없음" in out

    def test_print_ticker_external_with_data(self, rich_db, capsys):
        from nuri.collectors.external import print_ticker_external, save_external

        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=rich_db)
        print_ticker_external("AAPL", db_path=rich_db)
        out = capsys.readouterr().out
        assert "AAPL" in out


class TestFundamentalCollector_R17:
    def test_upsert_fundamentals(self, rich_db):
        from nuri.collectors.fundamental import _upsert_fundamentals

        records = [{"ticker": "AAPL", "date": "2025-03-15", "market_cap": 3e12, "pe_ratio": 28.5,
                     "forward_pe": 25.0, "price_to_book": 45.0, "peg_ratio": 1.5, "roe": 1.5,
                     "roa": 0.3, "gross_margin": 0.45, "operating_margin": 0.30, "profit_margin": 0.25,
                     "revenue_growth": 0.08, "earnings_growth": 0.12, "debt_to_equity": 1.8,
                     "current_ratio": 1.1, "dividend_yield": 0.005, "beta": 1.2}]
        assert _upsert_fundamentals(records) == 1

    def test_upsert_fundamentals_empty(self, rich_db):
        from nuri.collectors.fundamental import _upsert_fundamentals

        assert _upsert_fundamentals([]) == 0

    def test_save_empty(self, rich_db):
        from nuri.collectors.fundamental import FundamentalCollector

        c = FundamentalCollector()
        assert c.save([]) == 0
        assert c.save(None) == 0

    def test_collect_with_mock_openbb(self, rich_db):
        from nuri.collectors.fundamental import FundamentalCollector

        mock_row = pd.Series({"market_cap": 3e12, "pe_ratio": 28.5, "forward_pe": 25.0,
                              "price_to_book": 45.0, "peg_ratio_ttm": 1.5, "return_on_equity": 1.5,
                              "return_on_assets": 0.3, "gross_margin": 0.45, "operating_margin": 0.30,
                              "profit_margin": 0.25, "revenue_growth": 0.08, "earnings_growth": 0.12,
                              "debt_to_equity": 1.8, "current_ratio": 1.1, "dividend_yield": 0.005, "beta": 1.2})
        mock_df = pd.DataFrame([mock_row])
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.fundamental.metrics.return_value = mock_result

        c = FundamentalCollector()
        with patch.object(c, "_get_tickers", return_value=["AAPL"]):
            with patch("nuri.collectors.fundamental.obb", mock_obb, create=True):
                import types

                original_collect = c.collect

                def patched_collect(**kwargs):
                    with patch.dict("sys.modules", {"openbb": types.ModuleType("openbb")}):
                        import sys

                        sys.modules["openbb"].obb = mock_obb
                        return original_collect(**kwargs)

                result = patched_collect()
        assert len(result) == 1
        assert result[0]["pe_ratio"] == 28.5

    def test_collect_empty_dataframe(self, rich_db):
        from nuri.collectors.fundamental import FundamentalCollector

        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame()
        mock_obb = MagicMock()
        mock_obb.equity.fundamental.metrics.return_value = mock_result

        c = FundamentalCollector()
        with patch.object(c, "_get_tickers", return_value=["FAKE"]):
            import types

            original_collect = c.collect

            def patched_collect(**kwargs):
                import sys

                sys.modules["openbb"] = types.ModuleType("openbb")
                sys.modules["openbb"].obb = mock_obb
                return original_collect(**kwargs)

            result = patched_collect()
        assert result == []

    def test_collect_exception(self, rich_db):
        from nuri.collectors.fundamental import FundamentalCollector

        mock_obb = MagicMock()
        mock_obb.equity.fundamental.metrics.side_effect = RuntimeError("API error")

        c = FundamentalCollector()
        with patch.object(c, "_get_tickers", return_value=["FAIL"]):
            import types

            original_collect = c.collect

            def patched_collect(**kwargs):
                import sys

                sys.modules["openbb"] = types.ModuleType("openbb")
                sys.modules["openbb"].obb = mock_obb
                return original_collect(**kwargs)

            result = patched_collect()
        assert result == []

    def test_collect_nan_fields(self, rich_db):
        from nuri.collectors.fundamental import FundamentalCollector

        mock_row = pd.Series({"market_cap": float("nan"), "pe_ratio": 28.5, "forward_pe": float("nan"),
                              "price_to_book": float("nan"), "peg_ratio_ttm": float("nan"),
                              "return_on_equity": float("nan"), "return_on_assets": float("nan"),
                              "gross_margin": float("nan"), "operating_margin": float("nan"),
                              "profit_margin": float("nan"), "revenue_growth": float("nan"),
                              "earnings_growth": float("nan"), "debt_to_equity": float("nan"),
                              "current_ratio": float("nan"), "dividend_yield": float("nan"), "beta": float("nan")})
        mock_df = pd.DataFrame([mock_row])
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.fundamental.metrics.return_value = mock_result

        c = FundamentalCollector()
        with patch.object(c, "_get_tickers", return_value=["AAPL"]):
            import types

            original_collect = c.collect

            def patched_collect(**kwargs):
                import sys

                sys.modules["openbb"] = types.ModuleType("openbb")
                sys.modules["openbb"].obb = mock_obb
                return original_collect(**kwargs)

            result = patched_collect()
        assert len(result) == 1
        assert result[0]["market_cap"] is None
        assert result[0]["pe_ratio"] == 28.5


class TestCBOECollector_R17:
    def test_extract_pcr_ratio_key(self):
        from nuri.collectors.cboe import CBOECollector

        assert CBOECollector._extract_pcr({"TOTAL_PUT_CALL_RATIO": 0.85}) == 0.85
        assert CBOECollector._extract_pcr({"PUT_CALL_RATIO": 0.92}) == 0.92
        assert CBOECollector._extract_pcr({"put_call_ratio": 1.1}) == 1.1
        assert CBOECollector._extract_pcr({"pcr": 0.75}) == 0.75
        assert CBOECollector._extract_pcr({"ratio": 0.6}) == 0.6

    def test_extract_pcr_from_volumes(self):
        from nuri.collectors.cboe import CBOECollector

        result = CBOECollector._extract_pcr({"TOTAL_PUT_VOLUME": 1000, "TOTAL_CALL_VOLUME": 2000})
        assert abs(result - 0.5) < 0.01

    def test_extract_pcr_none(self):
        from nuri.collectors.cboe import CBOECollector

        assert CBOECollector._extract_pcr({}) is None

    def test_extract_pcr_invalid_values(self):
        from nuri.collectors.cboe import CBOECollector

        assert CBOECollector._extract_pcr({"TOTAL_PUT_CALL_RATIO": "bad"}) is None

    def test_collect_daily_success(self, monkeypatch):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [{"TRADE_DATE": "2025-03-15", "TOTAL_PUT_CALL_RATIO": 0.85}]}
        mock_resp.raise_for_status = MagicMock()
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c._collect_daily()
        assert len(result) == 1
        assert result[0]["value"] == 0.85

    def test_collect_daily_dict_response(self, monkeypatch):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"TOTAL_PUT_CALL_RATIO": 0.92}
        mock_resp.raise_for_status = MagicMock()
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c._collect_daily()
        assert len(result) == 1
        assert result[0]["value"] == 0.92

    def test_collect_totalpc(self):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [{"TRADE_DATE": "2025-03-15", "TOTAL_PUT_CALL_RATIO": 0.88}]}
        mock_resp.raise_for_status = MagicMock()
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c._collect_totalpc()
        assert len(result) == 1

    def test_collect_fred_pcr(self, monkeypatch):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        c.fred_key = "test_key"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "observations": [
                {"date": "2025-03-14", "value": "0.85"},
                {"date": "2025-03-13", "value": "."},
                {"date": "2025-03-12", "value": "0.92"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c._collect_fred_pcr()
        assert len(result) == 2

    def test_collect_fallback_chain(self, monkeypatch):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        c.fred_key = "test_key"
        with patch.object(c, "_collect_daily", side_effect=RuntimeError("fail")):
            with patch.object(c, "_collect_totalpc", side_effect=RuntimeError("fail")):
                with patch.object(c, "_collect_fred_pcr", return_value=[
                    {"indicator": "put_call_ratio", "date": "2025-03-15", "value": 0.9, "source": "FRED"}
                ]):
                    result = c.collect()
        assert len(result) == 1

    def test_collect_all_fail(self, monkeypatch):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        c.fred_key = ""
        with patch.object(c, "_collect_daily", side_effect=RuntimeError("fail")):
            with patch.object(c, "_collect_totalpc", side_effect=RuntimeError("fail")):
                result = c.collect()
        assert result == []

    def test_collect_daily_returns_empty(self, monkeypatch):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        c.fred_key = ""
        with patch.object(c, "_collect_daily", return_value=[]):
            with patch.object(c, "_collect_totalpc", return_value=[
                {"indicator": "put_call_ratio", "date": "2025-03-15", "value": 0.8, "source": "CBOE"}
            ]):
                result = c.collect()
        assert len(result) == 1

    def test_save(self, rich_db):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        records = [{"indicator": "put_call_ratio", "date": "2025-03-15", "value": 0.85, "source": "CBOE"}]
        assert c.save(records) == 1


class TestScheduler_R17:
    def test_run_collector_stock(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.stock.StockCollector", return_value=mock_collector):
            _run_collector("stock")
        mock_collector.run.assert_called_once()

    def test_run_collector_stock_kr(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.stock_kr.StockKRCollector", return_value=mock_collector):
            _run_collector("stock_kr")
        mock_collector.run.assert_called_once()

    def test_run_collector_macro(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.macro.MacroCollector", return_value=mock_collector):
            _run_collector("macro")
        mock_collector.run.assert_called_once()

    def test_run_collector_technical(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.technical.TechnicalCollector", return_value=mock_collector):
            _run_collector("technical")
        mock_collector.run.assert_called_once()

    def test_run_collector_fear_greed(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.fear_greed.FearGreedCollector", return_value=mock_collector):
            _run_collector("fear_greed")
        mock_collector.run.assert_called_once()

    def test_run_collector_ark(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.ark.ARKCollector", return_value=mock_collector):
            _run_collector("ark")
        mock_collector.run.assert_called_once()

    def test_run_collector_events(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.events.EventsCollector", return_value=mock_collector):
            _run_collector("events")
        mock_collector.run.assert_called_once()

    def test_run_collector_news(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.news.NewsCollector", return_value=mock_collector):
            _run_collector("news")
        mock_collector.run.assert_called_once()

    def test_run_collector_fundamental(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.fundamental.FundamentalCollector", return_value=mock_collector):
            _run_collector("fundamental")
        mock_collector.run.assert_called_once()

    def test_run_collector_superinvestors(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.superinvestors.SuperinvestorCollector", return_value=mock_collector):
            _run_collector("superinvestors")
        mock_collector.run.assert_called_once()

    def test_run_collector_estimates(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.estimates.EstimatesCollector", return_value=mock_collector):
            _run_collector("estimates")
        mock_collector.run.assert_called_once()

    def test_run_collector_etf_flows(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.etf_flows.EtfFlowsCollector", return_value=mock_collector):
            _run_collector("etf_flows")
        mock_collector.run.assert_called_once()

    def test_run_collector_wallstreet(self):
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.wallstreet.WallStreetCollector", return_value=mock_collector):
            _run_collector("wallstreet")
        mock_collector.run.assert_called_once()

    def test_run_collector_exception_handled(self):
        from nuri.scheduler import _run_collector

        with patch("nuri.collectors.stock.StockCollector", side_effect=RuntimeError("boom")):
            _run_collector("stock")


# ##############################################################################
# Source: test_coverage_round19.py
# ##############################################################################


class TestSuperinvestorBacktestIntegration:
    def test_backtest_with_mocked_detect_changes(self, rich_db):
        from nuri.quant.validation.superinvestor_backtest import backtest_superinvestor

        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, filing_date, shares, market_value) "
                "VALUES (?, ?, ?, ?, ?)",
                ("Warren Buffett", "AAPL", "2024-02-15", 100000, 50000000),
            )
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, filing_date, shares, market_value) "
                "VALUES (?, ?, ?, ?, ?)",
                ("Warren Buffett", "AAPL", "2024-05-15", 120000, 60000000),
            )

        mock_changes = pd.DataFrame([{
            "ticker": "AAPL", "filing_date": "2024-05-15",
            "change_type": "INCREASED", "shares_change": 20000,
        }])

        with patch("nuri.collectors.superinvestors.detect_changes", return_value=mock_changes), \
             patch("nuri.collectors.superinvestors.SUPERINVESTORS", {"Warren Buffett": "0000000001"}):
            results = backtest_superinvestor(
                investor="Warren Buffett", hold_days=30, db_path=rich_db
            )
        assert isinstance(results, list)


# ##############################################################################
# Source: test_coverage_round20.py
# ##############################################################################


class TestInstitutionalCollector_R20:
    def test_collect_kr_with_mocked_pykrx(self, rich_db, monkeypatch):
        from nuri.collectors.institutional import InstitutionalCollector

        collector = InstitutionalCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["005930.KS"] if market == "kr" else [])
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

        mock_df = pd.DataFrame(
            {"기관합계": [1000000], "외국인합계": [2000000], "개인": [-3000000]},
            index=pd.DatetimeIndex(["2025-01-15"]),
        )
        mock_stock_mod = MagicMock()
        mock_stock_mod.get_market_trading_value_by_date.return_value = mock_df

        with patch.dict("sys.modules", {"pykrx": MagicMock(stock=mock_stock_mod), "pykrx.stock": mock_stock_mod}):
            results = collector._collect_kr(["005930.KS"])
            assert len(results) == 1
            assert results[0]["ticker"] == "005930.KS"

    def test_collect_kr_empty(self, rich_db, monkeypatch):
        from nuri.collectors.institutional import InstitutionalCollector

        collector = InstitutionalCollector()
        mock_stock_mod = MagicMock()
        mock_stock_mod.get_market_trading_value_by_date.return_value = pd.DataFrame()
        with patch.dict("sys.modules", {"pykrx": MagicMock(stock=mock_stock_mod), "pykrx.stock": mock_stock_mod}):
            results = collector._collect_kr(["005930.KS"])
        assert results == []

    def test_collect_kr_exception(self, rich_db, monkeypatch):
        from nuri.collectors.institutional import InstitutionalCollector

        collector = InstitutionalCollector()
        mock_stock_mod = MagicMock()
        mock_stock_mod.get_market_trading_value_by_date.side_effect = RuntimeError("API down")
        with patch.dict("sys.modules", {"pykrx": MagicMock(stock=mock_stock_mod), "pykrx.stock": mock_stock_mod}):
            results = collector._collect_kr(["005930.KS"])
        assert results == []

    def test_save_empty(self, rich_db):
        from nuri.collectors.institutional import InstitutionalCollector

        assert InstitutionalCollector().save([]) == 0

    def test_save_records(self, rich_db):
        from nuri.collectors.institutional import InstitutionalCollector

        count = InstitutionalCollector().save([{
            "ticker": "005930.KS", "date": "2025-01-15", "market": "KR",
            "institution_net": 1000000, "foreign_net": 2000000,
            "individual_net": -3000000, "source": "pykrx",
        }])
        assert count == 1

    def test_safe_float(self):
        from nuri.collectors.institutional import _safe_float

        assert _safe_float(3.14) == 3.14
        assert _safe_float(None) is None
        assert _safe_float(float("nan")) is None


class TestEstimatesCollector_R20:
    def test_collect_with_mocked_openbb(self, rich_db, monkeypatch):
        from nuri.collectors.estimates import EstimatesCollector

        collector = EstimatesCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["AAPL"])
        mock_df = pd.DataFrame([{
            "recommendation": "buy", "target_high": 250.0, "target_low": 180.0,
            "target_consensus": 220.0, "target_median": 215.0,
            "number_of_analysts": 30, "current_price": 200.0,
        }])
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.estimates.consensus.return_value = mock_result
        mock_openbb_module = MagicMock()
        mock_openbb_module.obb = mock_obb
        with patch.dict("sys.modules", {"openbb": mock_openbb_module}):
            results = collector.collect()
            assert len(results) == 1
            assert results[0]["recommendation"] == "buy"

    def test_collect_empty_result(self, rich_db, monkeypatch):
        from nuri.collectors.estimates import EstimatesCollector

        collector = EstimatesCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["AAPL"])
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame()
        mock_obb = MagicMock()
        mock_obb.equity.estimates.consensus.return_value = mock_result
        with patch.dict("sys.modules", {"openbb": MagicMock(obb=mock_obb)}):
            assert collector.collect() == []

    def test_collect_exception(self, rich_db, monkeypatch):
        from nuri.collectors.estimates import EstimatesCollector

        collector = EstimatesCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["AAPL"])
        mock_obb = MagicMock()
        mock_obb.equity.estimates.consensus.side_effect = RuntimeError("API fail")
        with patch.dict("sys.modules", {"openbb": MagicMock(obb=mock_obb)}):
            assert collector.collect() == []

    def test_collect_no_tickers(self, rich_db, monkeypatch):
        from nuri.collectors.estimates import EstimatesCollector

        collector = EstimatesCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: [])
        with patch.dict("sys.modules", {"openbb": MagicMock()}):
            assert collector.collect() == []

    def test_save_empty(self, rich_db):
        from nuri.collectors.estimates import EstimatesCollector

        assert EstimatesCollector().save([]) == 0

    def test_save_records(self, rich_db):
        from nuri.collectors.estimates import EstimatesCollector

        count = EstimatesCollector().save([{
            "ticker": "MSFT", "date": "2025-01-01", "recommendation": "buy",
            "target_high": 500, "target_low": 400, "target_mean": 450,
            "target_median": 445, "num_analysts": 40, "current_price": 420,
        }])
        assert count == 1

    def test_safe_float_and_int(self):
        from nuri.collectors.estimates import _safe_float, _safe_int

        assert _safe_float(3.14) == 3.14
        assert _safe_float(float("nan")) is None
        assert _safe_int(42) == 42
        assert _safe_int(float("nan")) is None


class TestFINVIZCollector_R20:
    def test_collect_with_mocked_screener(self, rich_db, monkeypatch):
        from nuri.collectors.finviz import FINVIZCollector

        collector = FINVIZCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["AAPL", "NVDA"])
        monkeypatch.setattr(collector, "_fetch_signal_tickers", lambda signal: {"AAPL", "MSFT"})
        records = collector.collect()
        aapl_records = [r for r in records if r["ticker"] == "AAPL"]
        assert len(aapl_records) > 0

    def test_collect_no_us_tickers(self, rich_db, monkeypatch):
        from nuri.collectors.finviz import FINVIZCollector

        collector = FINVIZCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: [])
        assert collector.collect() == []

    def test_collect_fetch_exception(self, rich_db, monkeypatch):
        from nuri.collectors.finviz import FINVIZCollector

        collector = FINVIZCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["AAPL"])
        monkeypatch.setattr(collector, "_fetch_signal_tickers", MagicMock(side_effect=RuntimeError("fail")))
        assert isinstance(collector.collect(), list)

    def test_fetch_signal_tickers_finvizfinance(self, monkeypatch):
        from nuri.collectors.finviz import FINVIZCollector

        collector = FINVIZCollector()
        mock_screener = MagicMock()
        mock_screener.screener_view.return_value = ["AAPL", "MSFT", "GOOG"]
        mock_ticker_cls = MagicMock(return_value=mock_screener)
        with patch("nuri.collectors.finviz.Ticker", mock_ticker_cls, create=True):
            mock_mod = MagicMock()
            mock_mod.screener.ticker.Ticker = mock_ticker_cls
            with patch.dict("sys.modules", {"finvizfinance": mock_mod, "finvizfinance.screener": mock_mod.screener,
                                            "finvizfinance.screener.ticker": mock_mod.screener.ticker}):
                result = collector._fetch_signal_tickers("Oversold")
                assert isinstance(result, set)

    def test_save_empty(self, rich_db):
        from nuri.collectors.finviz import FINVIZCollector

        assert FINVIZCollector().save([]) == 0

    def test_save_records(self, rich_db):
        from nuri.collectors.finviz import FINVIZCollector

        count = FINVIZCollector().save([
            {"date": "2025-01-01", "ticker": "AAPL", "signal": "oversold_rsi", "source": "FINVIZ"},
        ], db_path=rich_db)
        assert count == 1

    def test_scrape_signal_fallback_mocked(self, monkeypatch):
        from nuri.collectors.finviz import FINVIZCollector

        collector = FINVIZCollector()
        html_content = """
        <html><body>
        <a href="quote.ashx?t=AAPL">AAPL</a>
        <a href="quote.ashx?t=MSFT">MSFT</a>
        </body></html>
        """
        mock_resp = MagicMock()
        mock_resp.text = html_content
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock_resp):
            result = collector._scrape_signal_fallback("Oversold")
            assert "AAPL" in result


# ##############################################################################
# Source: test_coverage_round24.py -- comprehensive collector tests
# ##############################################################################


class TestSuperinvestorCollector_R24:
    def test_collect_with_mock_edgar(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_infotable = pd.DataFrame({
            "Ticker": ["AAPL", "NVDA", "AAPL"],
            "Value": [1000000, 500000, 200000],
            "SharesPrnAmount": [5000, 3000, 1000],
            "Issuer": ["Apple Inc", "NVIDIA", "Apple Inc"],
        })
        mock_filing_obj = MagicMock()
        mock_filing_obj.infotable = mock_infotable
        mock_filing = MagicMock()
        mock_filing.filing_date = "2025-01-15"
        mock_filing.obj.return_value = mock_filing_obj
        mock_company = MagicMock()
        mock_company.get_filings.return_value = [mock_filing]

        monkeypatch.setattr("nuri.collectors.superinvestors.SUPERINVESTORS", {"Warren Buffett": "0001067983"})
        import sys

        monkeypatch.setitem(sys.modules, "edgar",
                            MagicMock(Company=lambda cik: mock_company, set_identity=MagicMock()))

        collector = SuperinvestorCollector()
        results = collector.collect(quarters=1)
        assert len(results) >= 2

    def test_collect_empty_filings(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_company = MagicMock()
        mock_company.get_filings.return_value = []
        monkeypatch.setattr("nuri.collectors.superinvestors.SUPERINVESTORS", {"Test": "000"})
        import sys

        monkeypatch.setitem(sys.modules, "edgar",
                            MagicMock(Company=lambda cik: mock_company, set_identity=MagicMock()))
        assert SuperinvestorCollector().collect() == []

    def test_collect_filing_parse_failure(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_filing = MagicMock()
        mock_filing.filing_date = "2025-01-15"
        mock_filing.obj.side_effect = Exception("parse error")
        mock_company = MagicMock()
        mock_company.get_filings.return_value = [mock_filing]
        monkeypatch.setattr("nuri.collectors.superinvestors.SUPERINVESTORS", {"Test": "000"})
        import sys

        monkeypatch.setitem(sys.modules, "edgar",
                            MagicMock(Company=lambda cik: mock_company, set_identity=MagicMock()))
        assert SuperinvestorCollector().collect() == []

    def test_collect_empty_infotable(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_filing_obj = MagicMock()
        mock_filing_obj.infotable = pd.DataFrame()
        mock_filing = MagicMock()
        mock_filing.filing_date = "2025-01-15"
        mock_filing.obj.return_value = mock_filing_obj
        mock_company = MagicMock()
        mock_company.get_filings.return_value = [mock_filing]
        monkeypatch.setattr("nuri.collectors.superinvestors.SUPERINVESTORS", {"Test": "000"})
        import sys

        monkeypatch.setitem(sys.modules, "edgar",
                            MagicMock(Company=lambda cik: mock_company, set_identity=MagicMock()))
        assert SuperinvestorCollector().collect() == []

    def test_collect_zero_total_value(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_infotable = pd.DataFrame({"Ticker": ["AAPL"], "Value": [0], "SharesPrnAmount": [100], "Issuer": ["Apple Inc"]})
        mock_filing_obj = MagicMock()
        mock_filing_obj.infotable = mock_infotable
        mock_filing = MagicMock()
        mock_filing.filing_date = "2025-01-15"
        mock_filing.obj.return_value = mock_filing_obj
        mock_company = MagicMock()
        mock_company.get_filings.return_value = [mock_filing]
        monkeypatch.setattr("nuri.collectors.superinvestors.SUPERINVESTORS", {"Test": "000"})
        import sys

        monkeypatch.setitem(sys.modules, "edgar",
                            MagicMock(Company=lambda cik: mock_company, set_identity=MagicMock()))
        assert SuperinvestorCollector().collect() == []

    def test_collect_nan_ticker(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_infotable = pd.DataFrame({"Ticker": [None, "AAPL"], "Value": [500000, 500000],
                                        "SharesPrnAmount": [100, 200], "Issuer": ["Unknown", "Apple Inc"]})
        mock_filing_obj = MagicMock()
        mock_filing_obj.infotable = mock_infotable
        mock_filing = MagicMock()
        mock_filing.filing_date = "2025-01-15"
        mock_filing.obj.return_value = mock_filing_obj
        mock_company = MagicMock()
        mock_company.get_filings.return_value = [mock_filing]
        monkeypatch.setattr("nuri.collectors.superinvestors.SUPERINVESTORS", {"Test": "000"})
        import sys

        monkeypatch.setitem(sys.modules, "edgar",
                            MagicMock(Company=lambda cik: mock_company, set_identity=MagicMock()))
        results = SuperinvestorCollector().collect()
        assert all(r["ticker"] == "AAPL" for r in results)

    def test_collect_company_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        monkeypatch.setattr("nuri.collectors.superinvestors.SUPERINVESTORS", {"Test": "000"})
        import sys

        monkeypatch.setitem(sys.modules, "edgar",
                            MagicMock(Company=MagicMock(side_effect=RuntimeError("network")), set_identity=MagicMock()))
        assert SuperinvestorCollector().collect() == []

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        c = SuperinvestorCollector()
        assert c.save([]) == 0
        assert c.save(None) == 0

    def test_save_records(self, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        count = SuperinvestorCollector().save([{
            "investor": "Buffett", "filing_date": "2025-01-15",
            "ticker": "AAPL", "shares": 1000.0, "market_value": 200000.0,
            "portfolio_pct": 25.5, "issuer_name": "Apple Inc",
        }])
        assert count == 1

    def test_print_summary_no_data(self, db_with_portfolio, capsys):
        from nuri.collectors.superinvestors import print_summary

        print_summary()
        assert "슈퍼투자자 데이터가 없습니다" in capsys.readouterr().out

    def test_print_summary_with_data(self, db_with_portfolio, capsys):
        from nuri.collectors.superinvestors import print_summary

        with get_db(db_with_portfolio) as conn:
            conn.execute(
                "INSERT INTO superinvestors (investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name) "
                "VALUES ('Warren Buffett', '2025-01-15', 'AAPL', 1000, 200000, 25.5, 'Apple Inc')"
            )
        print_summary()
        out = capsys.readouterr().out
        assert "Warren Buffett" in out

    def test_print_summary_with_overlap(self, db_with_portfolio, capsys):
        from nuri.collectors.superinvestors import print_summary

        with get_db(db_with_portfolio) as conn:
            conn.execute(
                "INSERT INTO superinvestors (investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name) "
                "VALUES ('Warren Buffett', '2025-01-15', 'AAPL', 1000, 200000, 25.5, 'Apple Inc')"
            )
        print_summary()
        assert "슈퍼투자자도 보유" in capsys.readouterr().out

    def test_detect_changes(self, db_with_portfolio):
        from nuri.collectors.superinvestors import detect_changes

        with get_db(db_with_portfolio) as conn:
            conn.execute("INSERT INTO superinvestors VALUES (NULL, 'Buffett', '2025-01-15', 'AAPL', 1000, 200000, 25.0, 'Apple Inc')")
            conn.execute("INSERT INTO superinvestors VALUES (NULL, 'Buffett', '2025-01-15', 'MSFT', 500, 100000, 12.0, 'Microsoft')")
            conn.execute("INSERT INTO superinvestors VALUES (NULL, 'Buffett', '2025-04-15', 'AAPL', 2000, 400000, 50.0, 'Apple Inc')")
            conn.execute("INSERT INTO superinvestors VALUES (NULL, 'Buffett', '2025-04-15', 'NVDA', 300, 60000, 15.0, 'NVIDIA')")
        df = detect_changes("Buffett", db_path=db_with_portfolio)
        changes = set(df["change_type"].unique())
        assert "NEW" in changes
        assert "CLOSED" in changes

    def test_detect_changes_insufficient_quarters(self, db_with_portfolio):
        from nuri.collectors.superinvestors import detect_changes

        assert detect_changes("Nobody", db_path=db_with_portfolio).empty


class TestExternalCollector_R24:
    def test_save_external_success(self, db_with_portfolio):
        from nuri.collectors.external import save_external

        assert save_external("tipranks", "AAPL", "consensus", "Strong Buy", db_path=db_with_portfolio) is True

    def test_save_external_unknown_source(self, db_with_portfolio):
        from nuri.collectors.external import save_external

        assert save_external("unknown_source", "AAPL", "test", "val", db_path=db_with_portfolio) is False

    def test_save_external_with_date(self, db_with_portfolio):
        from nuri.collectors.external import save_external

        assert save_external("tipranks", "AAPL", "consensus", "Buy", target_date="2025-01-15", db_path=db_with_portfolio) is True

    def test_save_external_with_numeric(self, db_with_portfolio):
        from nuri.collectors.external import save_external

        assert save_external("tipranks", "AAPL", "target_price", "250.0", numeric_value=250.0, db_path=db_with_portfolio) is True

    def test_save_tipranks(self, db_with_portfolio):
        from nuri.collectors.external import get_external, save_tipranks

        save_tipranks("AAPL", "Strong Buy", 250.0, 30, upside_pct=15.5, db_path=db_with_portfolio)
        data = get_external("AAPL", source="tipranks", db_path=db_with_portfolio)
        assert len(data) >= 3

    def test_save_superinvestor(self, db_with_portfolio):
        from nuri.collectors.external import get_external, save_superinvestor

        save_superinvestor("AAPL", 14, "buying", details="Buffett +10%", db_path=db_with_portfolio)
        data = get_external("AAPL", source="dataroma", db_path=db_with_portfolio)
        assert len(data) >= 2

    def test_get_external_all_sources(self, db_with_portfolio):
        from nuri.collectors.external import get_external, save_external

        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=db_with_portfolio)
        save_external("dataroma", "AAPL", "count", "5", db_path=db_with_portfolio)
        assert len(get_external("AAPL", db_path=db_with_portfolio)) >= 2

    def test_get_external_summary(self, db_with_portfolio):
        from nuri.collectors.external import get_external_summary, save_external

        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=db_with_portfolio)
        assert get_external_summary(db_path=db_with_portfolio)["total_records"] >= 1

    def test_print_ticker_external_no_data(self, db_with_portfolio, capsys):
        from nuri.collectors.external import print_ticker_external

        print_ticker_external("ZZZZ", db_path=db_with_portfolio)
        assert "외부 데이터 없음" in capsys.readouterr().out

    def test_print_ticker_external_with_data(self, db_with_portfolio, capsys):
        from nuri.collectors.external import print_ticker_external, save_external

        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=db_with_portfolio)
        print_ticker_external("AAPL", db_path=db_with_portfolio)
        assert "AAPL" in capsys.readouterr().out

    def test_print_summary(self, db_with_portfolio, capsys):
        from nuri.collectors.external import print_summary, save_external

        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=db_with_portfolio)
        print_summary(db_path=db_with_portfolio)
        assert "외부 데이터 요약" in capsys.readouterr().out

    def test_print_summary_empty(self, db_with_portfolio, capsys):
        from nuri.collectors.external import print_summary

        print_summary(db_path=db_with_portfolio)
        assert "0건" in capsys.readouterr().out


class TestInstitutionalCollector_R24:
    def test_collect_kr(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.institutional import InstitutionalCollector

        mock_df = pd.DataFrame({"기관합계": [1000000], "외국인합계": [500000], "개인": [-200000]},
                               index=pd.to_datetime(["2025-01-30"]))
        mock_stock = MagicMock()
        mock_stock.get_market_trading_value_by_date.return_value = mock_df
        import sys

        monkeypatch.setitem(sys.modules, "pykrx", MagicMock(stock=mock_stock))
        monkeypatch.setitem(sys.modules, "pykrx.stock", mock_stock)
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
        collector = InstitutionalCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["005930.KS"] if market == "kr" else [])
        results = collector.collect()
        assert len(results) >= 1

    def test_collect_kr_empty(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.institutional import InstitutionalCollector

        mock_stock = MagicMock()
        mock_stock.get_market_trading_value_by_date.return_value = pd.DataFrame()
        import sys

        monkeypatch.setitem(sys.modules, "pykrx", MagicMock())
        monkeypatch.setitem(sys.modules, "pykrx.stock", mock_stock)
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
        assert InstitutionalCollector().collect() == []

    def test_collect_kr_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.institutional import InstitutionalCollector

        mock_stock = MagicMock()
        mock_stock.get_market_trading_value_by_date.side_effect = Exception("API error")
        import sys

        monkeypatch.setitem(sys.modules, "pykrx", MagicMock())
        monkeypatch.setitem(sys.modules, "pykrx.stock", mock_stock)
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
        assert InstitutionalCollector().collect() == []

    def test_collect_us_with_finnhub(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.institutional import InstitutionalCollector

        monkeypatch.setenv("FINNHUB_API_KEY", "test_key")
        mock_stock = MagicMock()
        mock_stock.get_market_trading_value_by_date.return_value = pd.DataFrame()
        import sys

        monkeypatch.setitem(sys.modules, "pykrx", MagicMock())
        monkeypatch.setitem(sys.modules, "pykrx.stock", mock_stock)
        mock_client = MagicMock()
        mock_client.ownership.return_value = {"ownership": [{"data": "test"}]}
        mock_finnhub = MagicMock()
        mock_finnhub.Client.return_value = mock_client
        monkeypatch.setitem(sys.modules, "finnhub", mock_finnhub)
        results = InstitutionalCollector().collect()
        us_results = [r for r in results if r["market"] == "US"]
        assert len(us_results) >= 1

    def test_collect_us_finnhub_import_error(self, monkeypatch, db_with_portfolio):
        import sys

        from nuri.collectors.institutional import InstitutionalCollector

        monkeypatch.delitem(sys.modules, "finnhub", raising=False)
        original_import = __import__

        def mock_import(name, *args, **kwargs):
            if name == "finnhub":
                raise ImportError("No module named 'finnhub'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)
        assert InstitutionalCollector()._collect_us(["AAPL"], "test_key") == []

    def test_collect_us_finnhub_ticker_error(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.institutional import InstitutionalCollector

        mock_client = MagicMock()
        mock_client.ownership.side_effect = Exception("API error")
        mock_finnhub = MagicMock()
        mock_finnhub.Client.return_value = mock_client
        import sys

        monkeypatch.setitem(sys.modules, "finnhub", mock_finnhub)
        assert InstitutionalCollector()._collect_us(["AAPL"], "key") == []

    def test_save(self, db_with_portfolio):
        from nuri.collectors.institutional import InstitutionalCollector

        c = InstitutionalCollector()
        assert c.save([]) == 0
        assert c.save([{"ticker": "005930.KS", "date": "2025-01-30", "market": "KR",
                         "institution_net": 1000000, "foreign_net": 500000,
                         "individual_net": -200000, "source": "pykrx"}]) == 1


# Remaining R24 classes are extensive -- adding edge cases and remaining collectors


class TestMacroCollector_R24:
    def test_collect_fred(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_series = pd.Series([4.5, 4.3], index=pd.to_datetime(["2025-01-15", "2025-01-16"]))
        mock_fred = MagicMock()
        mock_fred.get_series.return_value = mock_series
        import sys

        monkeypatch.setitem(sys.modules, "fredapi", MagicMock(Fred=MagicMock(return_value=mock_fred)))
        collector = MacroCollector()
        collector.api_key = "test_fred_key"
        results = collector._collect_fred(days=30)
        assert len(results) > 0

    def test_collect_fred_series_failure(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_fred = MagicMock()
        mock_fred.get_series.side_effect = Exception("FRED API error")
        import sys

        monkeypatch.setitem(sys.modules, "fredapi", MagicMock(Fred=MagicMock(return_value=mock_fred)))
        collector = MacroCollector()
        collector.api_key = "test_key"
        assert collector._collect_fred(days=30) == []

    def test_collect_yfinance_fallback(self, monkeypatch, db_with_portfolio):
        import yfinance as yf

        from nuri.collectors.macro import MacroCollector

        mock_df = pd.DataFrame({
            "Date": pd.to_datetime(["2025-01-15"]),
            "Close": [4.5], "Open": [4.4], "High": [4.6], "Low": [4.3], "Volume": [0],
        })
        monkeypatch.setattr(yf, "download", lambda *a, **kw: mock_df)
        collector = MacroCollector()
        collector.api_key = ""
        assert len(collector._collect_yfinance(days=30)) > 0

    def test_collect_yfinance_empty_df(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_result = MagicMock()
        mock_result.to_df.return_value = pd.DataFrame()
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert MacroCollector()._collect_yfinance(days=30) == []

    def test_collect_yfinance_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_obb = MagicMock()
        mock_obb.equity.price.historical.side_effect = Exception("connection error")
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert MacroCollector()._collect_yfinance(days=30) == []

    def test_collect_prefers_fred(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_series = pd.Series([4.5], index=pd.to_datetime(["2025-01-15"]))
        mock_fred = MagicMock()
        mock_fred.get_series.return_value = mock_series
        import sys

        monkeypatch.setitem(sys.modules, "fredapi", MagicMock(Fred=MagicMock(return_value=mock_fred)))
        collector = MacroCollector()
        collector.api_key = "real_key"
        results = collector.collect(days=30)
        assert all(r["source"] == "FRED" for r in results)

    def test_collect_nan_value_skipped(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_df = pd.DataFrame({"date": pd.to_datetime(["2025-01-15", "2025-01-16"]), "close": [float("nan"), 4.3]})
        mock_result = MagicMock()
        mock_result.to_df.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        results = MacroCollector()._collect_yfinance(days=30)
        for r in results:
            assert not pd.isna(r["value"])

    def test_save(self, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        assert MacroCollector().save([{"indicator": "vix", "date": "2025-01-30", "value": 18.5, "source": "test"}]) == 1


class TestStockCollector_R24:
    def test_collect_ticker_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_df = pd.DataFrame({"date": pd.to_datetime(["2025-01-15"]), "open": [190.0], "high": [195.0],
                                "low": [189.0], "close": [194.0], "volume": [50000000], "adj_close": [194.0]})
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        df = StockCollector()._collect_ticker("AAPL", "2025-01-01", "2025-01-30")
        assert df is not None and not df.empty

    def test_collect_ticker_empty(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame()
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert StockCollector()._collect_ticker("AAPL", "2025-01-01", "2025-01-30") is None

    def test_collect_ticker_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_obb = MagicMock()
        mock_obb.equity.price.historical.side_effect = Exception("provider error")
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert StockCollector()._collect_ticker("AAPL", "2025-01-01", "2025-01-30") is None

    def test_collect_ticker_no_adj_close(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_df = pd.DataFrame({"date": pd.to_datetime(["2025-01-15"]), "open": [190.0], "high": [195.0],
                                "low": [189.0], "close": [194.0], "volume": [50000000]})
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        df = StockCollector()._collect_ticker("AAPL", "2025-01-01", "2025-01-30")
        assert df is not None and "adj_close" in df.columns

    def test_collect_no_tickers(self, monkeypatch, tmp_path):
        import nuri.core.db as db_mod
        from nuri.collectors.stock import StockCollector

        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        assert StockCollector().collect(period="5d").empty

    def test_period_to_start_date(self):
        from nuri.collectors.stock import StockCollector

        result = StockCollector._period_to_start_date("1mo")
        assert len(result) == 10

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        assert StockCollector().save(pd.DataFrame()) == 0


class TestFearGreedCollector_R24:
    def test_collect_api_success(self, monkeypatch):
        from nuri.collectors.fear_greed import FearGreedCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"fear_and_greed": {"score": 55.0}}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", MagicMock(return_value=mock_resp))
        results = FearGreedCollector().collect()
        assert len(results) == 1 and results[0]["value"] == 55.0

    def test_collect_api_value_key(self, monkeypatch):
        from nuri.collectors.fear_greed import FearGreedCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"fear_and_greed": {"value": 72.0}}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", MagicMock(return_value=mock_resp))
        assert FearGreedCollector().collect()[0]["value"] == 72.0

    def test_collect_api_no_data(self, monkeypatch):
        from nuri.collectors.fear_greed import FearGreedCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", MagicMock(return_value=mock_resp))
        assert FearGreedCollector().collect() == []

    def test_collect_api_fail_scrape_fallback(self, monkeypatch):
        from nuri.collectors.fear_greed import FearGreedCollector

        call_count = [0]

        def mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("API down")
            mock_resp = MagicMock()
            mock_resp.text = '<html><text class="market-fng-gauge__dial-number-value">45</text></html>'
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", mock_get)
        results = FearGreedCollector().collect()
        assert results[0]["value"] == 45.0

    def test_collect_both_fail(self, monkeypatch):
        from nuri.collectors.fear_greed import FearGreedCollector

        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", MagicMock(side_effect=Exception("all down")))
        assert FearGreedCollector().collect() == []

    def test_scrape_no_score_found(self, monkeypatch):
        from nuri.collectors.fear_greed import FearGreedCollector

        call_count = [0]

        def mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("API down")
            mock_resp = MagicMock()
            mock_resp.text = "<html><body>No score here</body></html>"
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", mock_get)
        assert FearGreedCollector().collect() == []

    def test_save(self, db_with_portfolio):
        from nuri.collectors.fear_greed import FearGreedCollector

        assert FearGreedCollector().save([{"indicator": "fear_greed", "date": "2025-01-30", "value": 55.0, "source": "CNN"}]) == 1


class TestARKCollector_R24:
    def test_collect_csv_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.ark import ARKCollector

        csv_text = "Date,Fund,Direction,Ticker,CUSIP,Name,Shares,% of ETF\n"
        csv_text += "01/15/2025,ARKK,Buy,AAPL,123456,Apple Inc,1000,2.5\n"
        csv_text += "01/15/2025,ARKK,Sell,NVDA,654321,NVIDIA,500,1.3\n"
        mock_resp = MagicMock()
        mock_resp.text = csv_text
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.ark.requests.get", MagicMock(return_value=mock_resp))
        results = ARKCollector().collect()
        assert "AAPL" in [r["ticker"] for r in results]

    def test_collect_csv_empty_ticker(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.ark import ARKCollector

        csv_text = "Date,Fund,Direction,Ticker,CUSIP,Name,Shares,% of ETF\n01/15/2025,ARKK,Buy,,123456,Unknown,1000,2.5\n"
        mock_resp = MagicMock()
        mock_resp.text = csv_text
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.ark.requests.get", MagicMock(return_value=mock_resp))
        assert ARKCollector().collect() == []

    def test_collect_all_urls_fail(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.ark import ARKCollector

        monkeypatch.setattr("nuri.collectors.ark.requests.get", MagicMock(side_effect=Exception("fail")))
        assert ARKCollector().collect() == []

    def test_save(self, db_with_portfolio):
        from nuri.collectors.ark import ARKCollector

        assert ARKCollector().save([{"date": "2025-01-15", "ticker": "AAPL", "direction": "Buy",
                                     "shares": 1000, "weight": 2.5, "fund": "ARKK"}]) == 1


class TestEventsCollector_R24:
    def test_collect_fomc(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.events import EventsCollector

        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame()
        mock_obb = MagicMock()
        mock_obb.equity.calendar.earnings.return_value = mock_result
        mock_obb.equity.calendar.dividend.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        results = EventsCollector().collect()
        fomc = [r for r in results if r["event_type"] == "fomc"]
        assert len(fomc) == 8

    def test_collect_ticker_events_earnings(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.events import EventsCollector

        earnings_df = pd.DataFrame({"report_date": pd.to_datetime(["2025-04-25"])})
        dividend_df = pd.DataFrame({"ex_dividend_date": pd.to_datetime(["2025-05-10"])})
        mock_obb = MagicMock()
        mock_obb.equity.calendar.earnings.return_value = MagicMock(to_dataframe=MagicMock(return_value=earnings_df))
        mock_obb.equity.calendar.dividend.return_value = MagicMock(to_dataframe=MagicMock(return_value=dividend_df))
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        results = EventsCollector()._collect_ticker_events("AAPL")
        assert len(results) == 2

    def test_collect_ticker_events_with_index_date(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.events import EventsCollector

        earnings_df = pd.DataFrame({"dummy": [1]}, index=pd.to_datetime(["2025-04-25"]))
        mock_obb = MagicMock()
        mock_obb.equity.calendar.earnings.return_value = MagicMock(to_dataframe=MagicMock(return_value=earnings_df))
        mock_obb.equity.calendar.dividend.side_effect = Exception("no dividend")
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        results = EventsCollector()._collect_ticker_events("AAPL")
        assert len(results) == 1

    def test_collect_ticker_events_no_date(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.events import EventsCollector

        earnings_df = pd.DataFrame({"dummy": [1]}, index=[0])
        mock_obb = MagicMock()
        mock_obb.equity.calendar.earnings.return_value = MagicMock(to_dataframe=MagicMock(return_value=earnings_df))
        mock_obb.equity.calendar.dividend.return_value = MagicMock(to_dataframe=MagicMock(return_value=pd.DataFrame()))
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert EventsCollector()._collect_ticker_events("AAPL") == []

    def test_save(self, db_with_portfolio):
        from nuri.collectors.events import EventsCollector

        c = EventsCollector()
        assert c.save([]) == 0
        assert c.save([{"date": "2025-03-17", "event_type": "fomc", "ticker": None, "description": "FOMC", "importance": 3}]) == 1

    def test_save_deduplicates(self, db_with_portfolio):
        from nuri.collectors.events import EventsCollector

        c = EventsCollector()
        record = {"date": "2025-03-17", "event_type": "fomc", "ticker": None, "description": "FOMC", "importance": 3}
        c.save([record])
        c.save([record])
        rows = query("SELECT * FROM events WHERE event_type = 'fomc' AND date = '2025-03-17'", db_path=db_with_portfolio)
        assert len(rows) == 1


class TestFundamentalCollector_R24:
    def test_collect_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fundamental import FundamentalCollector

        mock_df = pd.DataFrame([{"market_cap": 3e12, "pe_ratio": 28.5, "forward_pe": 25.0, "price_to_book": 15.0,
                                  "peg_ratio_ttm": 1.5, "return_on_equity": 0.35, "return_on_assets": 0.15,
                                  "gross_margin": 0.45, "operating_margin": 0.30, "profit_margin": 0.25,
                                  "revenue_growth": 0.08, "earnings_growth": 0.12, "debt_to_equity": 1.2,
                                  "current_ratio": 1.5, "dividend_yield": 0.005, "beta": 1.1}])
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.fundamental.metrics.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        results = FundamentalCollector().collect()
        assert len(results) >= 1

    def test_collect_empty_df(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fundamental import FundamentalCollector

        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame()
        mock_obb = MagicMock()
        mock_obb.equity.fundamental.metrics.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert FundamentalCollector().collect() == []

    def test_collect_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fundamental import FundamentalCollector

        mock_obb = MagicMock()
        mock_obb.equity.fundamental.metrics.side_effect = Exception("API error")
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert FundamentalCollector().collect() == []

    def test_collect_nan_values(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fundamental import FundamentalCollector

        mock_df = pd.DataFrame([{"market_cap": float("nan"), "pe_ratio": 28.5, "forward_pe": None,
                                  "price_to_book": None, "peg_ratio_ttm": None, "return_on_equity": None,
                                  "return_on_assets": None, "gross_margin": None, "operating_margin": None,
                                  "profit_margin": None, "revenue_growth": None, "earnings_growth": None,
                                  "debt_to_equity": None, "current_ratio": None, "dividend_yield": None, "beta": None}])
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.fundamental.metrics.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        results = FundamentalCollector().collect()
        assert results[0]["market_cap"] is None

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


class TestEstimatesCollector_R24:
    def test_collect_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.estimates import EstimatesCollector

        mock_df = pd.DataFrame([{"recommendation": "Buy", "target_high": 300.0, "target_low": 200.0,
                                  "target_consensus": 250.0, "target_median": 248.0,
                                  "number_of_analysts": 30, "current_price": 190.0}])
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.estimates.consensus.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        results = EstimatesCollector().collect()
        assert results[0]["recommendation"] == "Buy"

    def test_collect_empty(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.estimates import EstimatesCollector

        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame()
        mock_obb = MagicMock()
        mock_obb.equity.estimates.consensus.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert EstimatesCollector().collect() == []

    def test_collect_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.estimates import EstimatesCollector

        mock_obb = MagicMock()
        mock_obb.equity.estimates.consensus.side_effect = Exception("fail")
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert EstimatesCollector().collect() == []

    def test_collect_no_tickers(self, monkeypatch, tmp_path):
        import nuri.core.db as db_mod
        from nuri.collectors.estimates import EstimatesCollector

        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        assert EstimatesCollector().collect() == []

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.estimates import EstimatesCollector

        c = EstimatesCollector()
        assert c.save([]) == 0
        assert c.save(None) == 0

    def test_safe_float(self):
        from nuri.collectors.estimates import _safe_float

        assert _safe_float(123.45) == 123.45
        assert _safe_float(float("nan")) is None

    def test_safe_int(self):
        from nuri.collectors.estimates import _safe_int

        assert _safe_int(30) == 30
        assert _safe_int(float("nan")) is None


class TestFilingsCollector_R24:
    def test_parse_10k_success(self, monkeypatch):
        from nuri.collectors.filings import parse_10k

        inc_df = pd.DataFrame({"concept": ["Revenue", "NetIncome", "OperatingIncome"],
                                "dimension": [False, False, False], "is_breakdown": [False, False, False],
                                "2024": [100e9, 20e9, 30e9]})
        bs_df = pd.DataFrame({"concept": ["TotalAssets", "TotalLiabilities", "CashAndCashEquivalents"],
                               "dimension": [False, False, False], "is_breakdown": [False, False, False],
                               "2024": [400e9, 250e9, 50e9]})
        mock_obj = MagicMock()
        mock_obj.income_statement = MagicMock(to_dataframe=MagicMock(return_value=inc_df))
        mock_obj.balance_sheet = MagicMock(to_dataframe=MagicMock(return_value=bs_df))
        mock_filing = MagicMock()
        mock_filing.filing_date = "2025-02-15"
        mock_filing.obj.return_value = mock_obj
        mock_company = MagicMock()
        mock_company.get_filings.return_value = [mock_filing]
        import sys

        monkeypatch.setitem(sys.modules, "edgar",
                            MagicMock(Company=lambda ticker: mock_company, set_identity=MagicMock()))
        result = parse_10k("AAPL")
        assert result is not None and result["revenue"] == 100e9

    def test_parse_10k_no_filings(self, monkeypatch):
        from nuri.collectors.filings import parse_10k

        mock_company = MagicMock()
        mock_company.get_filings.return_value = []
        import sys

        monkeypatch.setitem(sys.modules, "edgar",
                            MagicMock(Company=lambda t: mock_company, set_identity=MagicMock()))
        assert parse_10k("AAPL") is None

    def test_parse_10k_exception(self, monkeypatch):
        import sys

        from nuri.collectors.filings import parse_10k

        monkeypatch.setitem(sys.modules, "edgar",
                            MagicMock(Company=MagicMock(side_effect=Exception("EDGAR error")), set_identity=MagicMock()))
        assert parse_10k("AAPL") is None

    def test_parse_10k_no_data_fields(self, monkeypatch):
        from nuri.collectors.filings import parse_10k

        mock_obj = MagicMock()
        mock_obj.income_statement = None
        mock_obj.balance_sheet = None
        mock_filing = MagicMock()
        mock_filing.filing_date = "2025-02-15"
        mock_filing.obj.return_value = mock_obj
        mock_company = MagicMock()
        mock_company.get_filings.return_value = [mock_filing]
        import sys

        monkeypatch.setitem(sys.modules, "edgar",
                            MagicMock(Company=lambda t: mock_company, set_identity=MagicMock()))
        assert parse_10k("AAPL") is None

    def test_collect_filings(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.filings import collect_filings

        monkeypatch.setattr("nuri.collectors.filings.parse_10k",
                            lambda ticker: {"ticker": ticker, "filing_date": "2025-02-15", "form": "10-K", "revenue": 100e9})
        assert len(collect_filings(tickers=["AAPL", "NVDA"])) == 2

    def test_collect_filings_some_none(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.filings import collect_filings

        def mock_parse(ticker):
            return {"ticker": "AAPL", "filing_date": "2025-02-15", "form": "10-K", "revenue": 100e9} if ticker == "AAPL" else None

        monkeypatch.setattr("nuri.collectors.filings.parse_10k", mock_parse)
        assert len(collect_filings(tickers=["AAPL", "NVDA"])) == 1

    def test_print_filings_empty(self, capsys):
        from nuri.collectors.filings import print_filings

        print_filings([])
        assert "10-K 데이터 없음" in capsys.readouterr().out

    def test_print_filings_with_data(self, capsys):
        from nuri.collectors.filings import print_filings

        print_filings([{"ticker": "AAPL", "filing_date": "2025-02-15", "revenue": 100e9, "net_income": 20e9, "total_assets": 400e9, "cash": 50e9}])
        assert "AAPL" in capsys.readouterr().out

    def test_print_filings_missing_fields(self, capsys):
        from nuri.collectors.filings import print_filings

        print_filings([{"ticker": "XYZ", "filing_date": "2025-01-01"}])
        assert "XYZ" in capsys.readouterr().out


class TestNewsCollector_R24:
    def test_collect_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.news import NewsCollector

        news_df = pd.DataFrame({"title": ["Apple beats"], "url": ["https://example.com/1"], "source": ["Reuters"]},
                               index=pd.to_datetime(["2025-01-28"]))
        mock_obb = MagicMock()
        mock_obb.news.company.return_value = MagicMock(to_dataframe=MagicMock(return_value=news_df))
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        results = NewsCollector().collect()
        assert results[0]["title"] == "Apple beats"

    def test_collect_no_url(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.news import NewsCollector

        news_df = pd.DataFrame({"title": ["No link"], "url": [""], "source": ["Unknown"]},
                               index=pd.to_datetime(["2025-01-28"]))
        mock_obb = MagicMock()
        mock_obb.news.company.return_value = MagicMock(to_dataframe=MagicMock(return_value=news_df))
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert NewsCollector().collect() == []

    def test_collect_date_in_column(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.news import NewsCollector

        news_df = pd.DataFrame({"title": ["News"], "url": ["https://example.com/1"], "source": ["Reuters"], "date": ["2025-01-28"]})
        mock_obb = MagicMock()
        mock_obb.news.company.return_value = MagicMock(to_dataframe=MagicMock(return_value=news_df))
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        results = NewsCollector().collect()
        assert results[0]["date"] == "2025-01-28"

    def test_collect_empty(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.news import NewsCollector

        mock_obb = MagicMock()
        mock_obb.news.company.return_value = MagicMock(to_dataframe=MagicMock(return_value=pd.DataFrame()))
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert NewsCollector().collect() == []

    def test_collect_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.news import NewsCollector

        mock_obb = MagicMock()
        mock_obb.news.company.side_effect = Exception("API error")
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert NewsCollector().collect() == []


class TestEtfFlowsCollector_R24:
    def test_collect_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        mock_df = pd.DataFrame([{"name": "Tech", "total_assets": 50e9, "volume_avg": 20000000, "nav_price": 200.0}])
        mock_obb = MagicMock()
        mock_obb.etf.info.return_value = MagicMock(to_df=MagicMock(return_value=mock_df))
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        results = EtfFlowsCollector().collect()
        assert len(results) > 0

    def test_collect_empty(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        mock_obb = MagicMock()
        mock_obb.etf.info.return_value = MagicMock(to_df=MagicMock(return_value=pd.DataFrame()))
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert EtfFlowsCollector().collect() == []

    def test_collect_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        mock_obb = MagicMock()
        mock_obb.etf.info.side_effect = Exception("ETF API error")
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert EtfFlowsCollector().collect() == []

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        c = EtfFlowsCollector()
        assert c.save([]) == 0
        assert c.save(None) == 0

    def test_analyze_sector_rotation_no_data(self, db_with_portfolio):
        from nuri.collectors.etf_flows import analyze_sector_rotation

        assert analyze_sector_rotation(db_path=db_with_portfolio) is None

    def test_analyze_sector_rotation_with_data(self, db_with_portfolio):
        from nuri.collectors.etf_flows import _upsert_etf_flows, analyze_sector_rotation

        records = []
        for ticker in ["XLK", "XLF"]:
            for d in ["2025-01-15", "2025-01-30"]:
                records.append({"ticker": ticker, "date": d, "name": f"{ticker} ETF",
                                "total_assets": 50e9, "volume_avg": 20000000, "nav_price": 200.0})
        _upsert_etf_flows(records, db_path=db_with_portfolio)
        assert analyze_sector_rotation(db_path=db_with_portfolio) is not None

    def test_analyze_sector_rotation_with_volume_trend(self, db_with_portfolio):
        from nuri.collectors.etf_flows import _upsert_etf_flows, analyze_sector_rotation

        records = [{"ticker": "XLK", "date": f"2025-01-{d:02d}", "name": "Tech",
                     "total_assets": 50e9 + d * 1e9, "volume_avg": 20000000 + d * 1000000, "nav_price": 200 + d}
                   for d in range(1, 9)]
        _upsert_etf_flows(records, db_path=db_with_portfolio)
        assert analyze_sector_rotation(db_path=db_with_portfolio) is not None

    def test_print_sector_rotation_none(self, capsys):
        from nuri.collectors.etf_flows import print_sector_rotation

        print_sector_rotation(None)
        assert "데이터 없음" in capsys.readouterr().out

    def test_print_sector_rotation_with_data(self, capsys):
        from nuri.collectors.etf_flows import print_sector_rotation

        df = pd.DataFrame([{"ticker": "XLK", "sector": "Technology", "aum_current": 50e9,
                            "aum_prev": 48e9, "aum_change_pct": 4.17, "volume_trend_pct": 10.0}])
        print_sector_rotation(df)
        assert "XLK" in capsys.readouterr().out


class TestStockKRCollector_R24:
    def test_collect_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock_kr import StockKRCollector

        mock_ohlcv = pd.DataFrame({"시가": [60000], "고가": [61000], "저가": [59000], "종가": [60500], "거래량": [1000000]},
                                  index=pd.to_datetime(["2025-01-29"]))
        monkeypatch.setattr("nuri.collectors.stock_kr.krx.get_market_ohlcv", MagicMock(return_value=mock_ohlcv))
        df = StockKRCollector().collect(days=5)
        assert not df.empty

    def test_collect_empty(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock_kr import StockKRCollector

        monkeypatch.setattr("nuri.collectors.stock_kr.krx.get_market_ohlcv", MagicMock(return_value=pd.DataFrame()))
        assert StockKRCollector().collect(days=5).empty

    def test_collect_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock_kr import StockKRCollector

        monkeypatch.setattr("nuri.collectors.stock_kr.krx.get_market_ohlcv", MagicMock(side_effect=Exception("pykrx error")))
        assert StockKRCollector().collect(days=5).empty

    def test_collect_no_kr_tickers(self, monkeypatch, tmp_path):
        import nuri.core.db as db_mod
        from nuri.collectors.stock_kr import StockKRCollector

        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        upsert_portfolio([{"account": "test", "ticker": "AAPL", "quantity": 10, "avg_price": 190, "currency": "USD", "sector": "Tech"}], path)
        assert StockKRCollector().collect(days=5).empty

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.stock_kr import StockKRCollector

        assert StockKRCollector().save(pd.DataFrame()) == 0


class TestWallStreetCollector_R24:
    def test_collect_ratings(self, monkeypatch, db_with_portfolio):
        import yfinance as yf

        from nuri.collectors.wallstreet import WallStreetCollector

        mock_info = {"shortPercentOfFloat": 0.05, "shortRatio": 2.5}
        mock_ud = pd.DataFrame({"Firm": ["GS"], "ToGrade": ["Buy"], "FromGrade": ["Hold"],
                                "Action": ["up"], "currentPriceTarget": [250.0]},
                               index=pd.to_datetime(["2025-01-28"]))
        mock_eh = pd.DataFrame({"epsActual": [1.50], "epsEstimate": [1.40], "surprisePercent": [7.14]},
                               index=pd.to_datetime(["2025-01-28"]))
        mock_ins = pd.DataFrame({"Start Date": ["2025-01-20"], "Text": ["Sale of shares"], "Insider": ["CEO"],
                                 "Position": ["Chief Executive"], "Shares": [5000], "Value": [1000000]})

        class MockTicker:
            def __init__(self, ticker):
                self.ticker = ticker
                self.info = mock_info
                self.upgrades_downgrades = mock_ud
                self.earnings_history = mock_eh
                self.insider_transactions = mock_ins
                self.recommendations = None

        monkeypatch.setattr(yf, "Ticker", MockTicker)
        monkeypatch.setattr("nuri.collectors.wallstreet.get_tickers", lambda: ["AAPL"])
        data = WallStreetCollector().collect()
        assert len(data["ratings"]) >= 1

    def test_collect_purchase_type(self, monkeypatch, db_with_portfolio):
        import yfinance as yf

        from nuri.collectors.wallstreet import WallStreetCollector

        mock_ins = pd.DataFrame({"Start Date": ["2025-01-20"], "Text": ["Purchase of shares"],
                                 "Insider": ["CFO"], "Position": ["CFO"], "Shares": [1000], "Value": [200000]})

        class MockTicker:
            def __init__(self, ticker):
                self.ticker = ticker
                self.info = {}
                self.upgrades_downgrades = None
                self.earnings_history = None
                self.insider_transactions = mock_ins
                self.recommendations = None

        monkeypatch.setattr(yf, "Ticker", MockTicker)
        monkeypatch.setattr("nuri.collectors.wallstreet.get_tickers", lambda: ["AAPL"])
        assert WallStreetCollector().collect()["insiders"][0]["transaction_type"] == "purchase"

    def test_collect_other_transaction_type(self, monkeypatch, db_with_portfolio):
        import yfinance as yf

        from nuri.collectors.wallstreet import WallStreetCollector

        mock_ins = pd.DataFrame({"Start Date": ["2025-01-20"], "Text": ["Gift of shares"],
                                 "Insider": ["Board"], "Position": ["Director"], "Shares": [500], "Value": [100000]})

        class MockTicker:
            def __init__(self, ticker):
                self.ticker = ticker
                self.info = {}
                self.upgrades_downgrades = None
                self.earnings_history = None
                self.insider_transactions = mock_ins
                self.recommendations = None

        monkeypatch.setattr(yf, "Ticker", MockTicker)
        monkeypatch.setattr("nuri.collectors.wallstreet.get_tickers", lambda: ["AAPL"])
        assert WallStreetCollector().collect()["insiders"][0]["transaction_type"] == "other"

    def test_collect_exception_per_ticker(self, monkeypatch, db_with_portfolio):
        import yfinance as yf

        from nuri.collectors.wallstreet import WallStreetCollector

        class BadTicker:
            def __init__(self, ticker):
                raise Exception("bad ticker")

        monkeypatch.setattr(yf, "Ticker", BadTicker)
        monkeypatch.setattr("nuri.collectors.wallstreet.get_tickers", lambda: ["AAPL"])
        assert WallStreetCollector().collect()["ratings"] == []

    def test_save(self, db_with_portfolio):
        from nuri.collectors.wallstreet import WallStreetCollector

        data = {"ratings": [{"ticker": "AAPL", "date": "2025-01-28", "firm": "GS", "to_grade": "Buy",
                              "from_grade": "Hold", "action": "up", "target_price": 250.0}],
                "earnings": [{"ticker": "AAPL", "quarter": "2025-01-28", "eps_actual": 1.5, "eps_estimate": 1.4, "surprise_pct": 7.14}],
                "insiders": [{"ticker": "AAPL", "date": "2025-01-20", "insider_name": "CEO", "position": "CEO",
                               "transaction_type": "sale", "shares": 5000, "value": 1000000}],
                "short_interest": [{"ticker": "AAPL", "short_pct_float": 5.0, "days_to_cover": 2.5}]}
        assert WallStreetCollector().save(data) >= 4

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.wallstreet import WallStreetCollector

        assert WallStreetCollector().save({"ratings": [], "earnings": [], "insiders": [], "short_interest": []}) == 0


class TestRedditCollector_R24:
    def test_collect_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.reddit import RedditCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [
            {"title": "$AAPL moon!", "selftext": "Buy AAPL", "created_utc": 1706400000},
            {"title": "NVDA earnings", "selftext": "NVDA beat", "created_utc": 1706400001},
        ]}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.reddit.requests.get", lambda url, **kw: mock_resp)
        results = RedditCollector().collect(days=1)
        assert "wsb_post_count" in [r["indicator"] for r in results]

    def test_collect_api_failure(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.reddit import RedditCollector

        monkeypatch.setattr("nuri.collectors.reddit.requests.get", MagicMock(side_effect=Exception("fail")))
        assert RedditCollector().collect() == []

    def test_collect_no_posts(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.reddit import RedditCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.reddit.requests.get", MagicMock(return_value=mock_resp))
        assert RedditCollector().collect() == []

    def test_count_mentions_noise_filter(self, db_with_portfolio):
        from nuri.collectors.reddit import RedditCollector

        counts = RedditCollector()._count_mentions(
            [{"title": "I AM going to BUY the DIP", "selftext": "AAPL NVDA"}], {"AAPL", "NVDA"})
        assert counts["AAPL"] >= 1
        assert counts.get("AM", 0) == 0

    def test_fetch_posts_pagination(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.reddit import RedditCollector

        call_count = [0]

        def mock_get(url, **kwargs):
            call_count[0] += 1
            mock_resp = MagicMock()
            if call_count[0] <= 2:
                mock_resp.json.return_value = {"data": [{"title": f"Post {call_count[0]}", "selftext": "", "created_utc": 1706400000 + call_count[0]}]}
            else:
                mock_resp.json.return_value = {"data": []}
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        monkeypatch.setattr("nuri.collectors.reddit.requests.get", mock_get)
        assert len(RedditCollector()._fetch_posts(days=1)) == 2

    def test_save(self, db_with_portfolio):
        from nuri.collectors.reddit import RedditCollector

        assert RedditCollector().save([{"indicator": "wsb_post_count", "date": "2025-01-30", "value": 100.0, "source": "Reddit_WSB"}]) == 1


class TestFREDCalendarCollector_R24:
    def test_collect_fallback(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        c = FREDCalendarCollector()
        c.api_key = ""
        assert isinstance(c.collect(days_ahead=365), list)

    def test_collect_invalid_days(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        c = FREDCalendarCollector()
        c.api_key = ""
        assert isinstance(c.collect(days_ahead=-1), list)

    def test_collect_fred_api_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"release_dates": [
            {"release_id": 10, "date": "2026-04-15"},
            {"release_id": 50, "date": "2026-04-18"},
        ]}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.fred_calendar.requests.get", MagicMock(return_value=mock_resp))
        c = FREDCalendarCollector()
        c.api_key = "test_key"
        results = c._collect_fred_api(days_ahead=30)
        assert len(results) == 2

    def test_collect_fred_api_failure_fallback(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        monkeypatch.setattr("nuri.collectors.fred_calendar.requests.get", MagicMock(side_effect=Exception("FRED down")))
        c = FREDCalendarCollector()
        c.api_key = "test_key"
        assert isinstance(c.collect(days_ahead=365), list)

    def test_save(self, db_with_portfolio):
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        c = FREDCalendarCollector()
        assert c.save([]) == 0
        assert c.save([{"date": "2026-04-15", "event_type": "economic", "ticker": None, "description": "FRED: CPI", "importance": 3}]) == 1

    def test_save_deduplicates(self, db_with_portfolio):
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        c = FREDCalendarCollector()
        record = {"date": "2026-04-15", "event_type": "economic", "ticker": None, "description": "FRED: CPI", "importance": 3}
        c.save([record])
        c.save([record])
        rows = query("SELECT * FROM events WHERE description = 'FRED: CPI'", db_path=db_with_portfolio)
        assert len(rows) == 1


# ##############################################################################
# Source: test_coverage_round24.py -- edge cases
# ##############################################################################


class TestSuperinvestorDetectChangesEdgeCases:
    def test_detect_unchanged(self, db_with_portfolio):
        from nuri.collectors.superinvestors import detect_changes

        with get_db(db_with_portfolio) as conn:
            conn.execute("INSERT INTO superinvestors VALUES (NULL, 'X', '2025-01-15', 'AAPL', 1000, 200000, 50.0, 'Apple')")
            conn.execute("INSERT INTO superinvestors VALUES (NULL, 'X', '2025-04-15', 'AAPL', 1000, 200000, 50.0, 'Apple')")
        assert "UNCHANGED" in detect_changes("X", db_path=db_with_portfolio)["change_type"].values

    def test_detect_decreased(self, db_with_portfolio):
        from nuri.collectors.superinvestors import detect_changes

        with get_db(db_with_portfolio) as conn:
            conn.execute("INSERT INTO superinvestors VALUES (NULL, 'Y', '2025-01-15', 'AAPL', 1000, 200000, 50.0, 'Apple')")
            conn.execute("INSERT INTO superinvestors VALUES (NULL, 'Y', '2025-04-15', 'AAPL', 500, 100000, 25.0, 'Apple')")
        assert "DECREASED" in detect_changes("Y", db_path=db_with_portfolio)["change_type"].values

    def test_detect_prev_shares_zero(self, db_with_portfolio):
        from nuri.collectors.superinvestors import detect_changes

        with get_db(db_with_portfolio) as conn:
            conn.execute("INSERT INTO superinvestors VALUES (NULL, 'Z', '2025-01-15', 'AAPL', 0, 0, 0, 'Apple')")
            conn.execute("INSERT INTO superinvestors VALUES (NULL, 'Z', '2025-04-15', 'AAPL', 500, 100000, 50.0, 'Apple')")
        assert "INCREASED" in detect_changes("Z", db_path=db_with_portfolio)["change_type"].values


class TestExternalEdgeCases:
    def test_save_external_db_error(self, monkeypatch, db_with_portfolio):
        from contextlib import contextmanager

        from nuri.collectors.external import save_external

        @contextmanager
        def bad_db(path=None):
            raise Exception("DB write error")
            yield  # pragma: no cover

        monkeypatch.setattr("nuri.collectors.external.get_db", bad_db)
        assert save_external("tipranks", "AAPL", "consensus", "Buy", db_path=db_with_portfolio) is False


class TestMacroCollectorEdgeCases:
    def test_collect_uses_yfinance_when_no_fred_key(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_df = pd.DataFrame({"date": pd.to_datetime(["2025-01-15"]), "close": [4.5]})
        mock_result = MagicMock()
        mock_result.to_df.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        collector = MacroCollector()
        collector.api_key = ""
        assert isinstance(collector.collect(days=30), list)

    def test_collect_fred_returns_empty_falls_to_yfinance(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_fred = MagicMock()
        mock_fred.get_series.return_value = pd.Series(dtype=float)
        import sys

        monkeypatch.setitem(sys.modules, "fredapi", MagicMock(Fred=MagicMock(return_value=mock_fred)))
        mock_df = pd.DataFrame({"date": pd.to_datetime(["2025-01-15"]), "close": [4.5]})
        mock_result = MagicMock()
        mock_result.to_df.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        collector = MacroCollector()
        collector.api_key = "real_key"
        assert isinstance(collector.collect(days=30), list)


class TestStockCollectorEdgeCases:
    def test_collect_full_flow(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_df = pd.DataFrame({"date": pd.to_datetime(["2025-01-15"]), "open": [190.0], "high": [195.0],
                                "low": [189.0], "close": [194.0], "volume": [50000000], "adj_close": [194.0]})
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert not StockCollector().collect(period="5d").empty


class TestCollectFilingsDefaultTickers:
    def test_collect_filings_default(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.filings import collect_filings

        def mock_parse(ticker):
            return {"ticker": ticker, "filing_date": "2025-02-15", "form": "10-K", "revenue": 50e9} if not ticker.endswith(".KS") else None

        monkeypatch.setattr("nuri.collectors.filings.parse_10k", mock_parse)
        results = collect_filings()
        assert all(not r["ticker"].endswith(".KS") for r in results)


class TestFetchPostsNoLastUTC:
    def test_fetch_posts_no_last_utc(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.reddit import RedditCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [{"title": "Test", "selftext": "", "created_utc": None}]}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.reddit.requests.get", MagicMock(return_value=mock_resp))
        assert len(RedditCollector()._fetch_posts(days=1)) == 1


class TestEventsCollectorDividendNoDate:
    def test_dividend_no_date(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.events import EventsCollector

        mock_obb = MagicMock()
        mock_obb.equity.calendar.earnings.return_value = MagicMock(to_dataframe=MagicMock(return_value=pd.DataFrame()))
        mock_obb.equity.calendar.dividend.return_value = MagicMock(to_dataframe=MagicMock(return_value=pd.DataFrame({"ex_dividend_date": [None]})))
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert isinstance(EventsCollector()._collect_ticker_events("AAPL"), list)


class TestCollectNoUSTickets:
    def test_no_us_tickers(self, monkeypatch, tmp_path):
        import nuri.core.db as db_mod
        from nuri.collectors.reddit import RedditCollector

        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        assert RedditCollector().collect() == []


class TestWallStreetSaveShortInterest:
    def test_save_short_no_days_to_cover(self, db_with_portfolio):
        from nuri.collectors.wallstreet import _save_short_interest

        assert _save_short_interest([{"ticker": "AAPL", "short_pct_float": 5.0}], db_path=db_with_portfolio) == 1


class TestEtfFlowsNanValues:
    def test_collect_nan_assets(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        mock_df = pd.DataFrame([{"name": "Test ETF", "total_assets": float("nan"), "volume_avg": float("nan"), "nav_price": float("nan")}])
        mock_obb = MagicMock()
        mock_obb.etf.info.return_value = MagicMock(to_df=MagicMock(return_value=mock_df))
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        results = EtfFlowsCollector().collect()
        assert len(results) > 0
        assert results[0]["total_assets"] is None


# ##############################################################################
# Source: test_uncovered.py
# ##############################################################################


class TestEventsCollector_Uncovered:
    def test_save_empty(self, db_path):
        from nuri.collectors.events import EventsCollector

        assert EventsCollector().save([]) == 0

    def test_save_records(self, db_path):
        from nuri.collectors.events import EventsCollector

        count = EventsCollector().save([{
            "date": "2025-06-01", "event_type": "earnings",
            "ticker": "AAPL", "description": "Q2 earnings", "importance": "high",
        }])
        assert count >= 0


class TestNewsCollector_Uncovered:
    def test_save_empty(self, db_path):
        from nuri.collectors.news import NewsCollector

        assert NewsCollector().save([]) == 0


class TestInstitutionalCollector_Uncovered:
    def test_instantiate(self):
        from nuri.collectors.institutional import InstitutionalCollector

        assert InstitutionalCollector().name == "institutional"

    def test_save_empty(self, db_path):
        from nuri.collectors.institutional import InstitutionalCollector

        assert InstitutionalCollector().save([]) == 0

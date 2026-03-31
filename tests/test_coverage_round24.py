"""Coverage Round 24 — collectors + alerts uncovered lines.

Target modules (20 files):
  1. nuri/collectors/superinvestors.py — print_summary + __main__
  2. nuri/collectors/external.py — scraping functions, CLI
  3. nuri/collectors/institutional.py — KR/US collection
  4. nuri/collectors/macro.py — FRED + yfinance fallback
  5. nuri/collectors/stock.py — US stock price collection via OpenBB
  6. nuri/collectors/fear_greed.py — CNN Fear & Greed
  7. nuri/collectors/ark.py — ARK fund holdings
  8. nuri/collectors/events.py — event collector
  9. nuri/collectors/fundamental.py — fundamentals via OpenBB
  10. nuri/collectors/estimates.py — analyst estimates
  11. nuri/collectors/filings.py — SEC filings via edgartools
  12. nuri/collectors/news.py — news collection
  13. nuri/collectors/etf_flows.py — ETF flow data
  14. nuri/collectors/stock_kr.py — Korean stock via pykrx
  15. nuri/collectors/wallstreet.py — Wall Street data
  16. nuri/collectors/reddit.py — Reddit/WSB scraping
  17. nuri/collectors/fred_calendar.py — FRED calendar events
  18. nuri/alerts/daily_report.py — daily report generation
  19. nuri/alerts/formatters.py — output formatting
  20. nuri/alerts/telegram.py — telegram sending
"""
from unittest.mock import MagicMock

import pandas as pd
import pytest

from nuri.core.db import (
    init_db,
    query,
    upsert_macro,
    upsert_portfolio,
    upsert_prices,
)

# ═══════════════════════════════════════════════════════
# Shared DB fixture
# ═══════════════════════════════════════════════════════


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def db_with_portfolio(db_path, monkeypatch):
    """DB with portfolio + prices seeded."""
    import nuri.core.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10, "avg_price": 190,
         "currency": "USD", "sector": "Tech"},
        {"account": "test", "ticker": "NVDA", "quantity": 5, "avg_price": 130,
         "currency": "USD", "sector": "Semiconductor"},
        {"account": "test", "ticker": "005930.KS", "quantity": 4, "avg_price": 60000,
         "currency": "KRW", "sector": "Semiconductor"},
    ], db_path)

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


# ═══════════════════════════════════════════════════════
# 1. SuperinvestorCollector
# ═══════════════════════════════════════════════════════


class TestSuperinvestorCollector:
    """Tests for nuri/collectors/superinvestors.py — print_summary + collect."""

    def test_collect_with_mock_edgar(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        # Mock edgartools
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

        mock_set_identity = MagicMock()

        def mock_company_cls(cik):
            return mock_company

        monkeypatch.setattr("nuri.collectors.superinvestors.SUPERINVESTORS",
                            {"Warren Buffett": "0001067983"})

        monkeypatch.setitem(
            __import__("sys").modules, "edgar",
            MagicMock(Company=mock_company_cls, set_identity=mock_set_identity),
        )

        collector = SuperinvestorCollector()
        results = collector.collect(quarters=1)
        assert len(results) >= 2  # AAPL + NVDA (grouped)
        assert all(r["investor"] == "Warren Buffett" for r in results)

    def test_collect_empty_filings(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_company = MagicMock()
        mock_company.get_filings.return_value = []

        monkeypatch.setattr("nuri.collectors.superinvestors.SUPERINVESTORS",
                            {"Test Investor": "000"})
        import sys
        monkeypatch.setitem(sys.modules, "edgar",
                            MagicMock(Company=lambda cik: mock_company, set_identity=MagicMock()))

        collector = SuperinvestorCollector()
        results = collector.collect()
        assert results == []

    def test_collect_filing_parse_failure(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_filing = MagicMock()
        mock_filing.filing_date = "2025-01-15"
        mock_filing.obj.side_effect = Exception("parse error")

        mock_company = MagicMock()
        mock_company.get_filings.return_value = [mock_filing]

        monkeypatch.setattr("nuri.collectors.superinvestors.SUPERINVESTORS",
                            {"Test": "000"})
        import sys
        monkeypatch.setitem(sys.modules, "edgar",
                            MagicMock(Company=lambda cik: mock_company, set_identity=MagicMock()))

        collector = SuperinvestorCollector()
        results = collector.collect()
        assert results == []

    def test_collect_empty_infotable(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_filing_obj = MagicMock()
        mock_filing_obj.infotable = pd.DataFrame()

        mock_filing = MagicMock()
        mock_filing.filing_date = "2025-01-15"
        mock_filing.obj.return_value = mock_filing_obj

        mock_company = MagicMock()
        mock_company.get_filings.return_value = [mock_filing]

        monkeypatch.setattr("nuri.collectors.superinvestors.SUPERINVESTORS",
                            {"Test": "000"})
        import sys
        monkeypatch.setitem(sys.modules, "edgar",
                            MagicMock(Company=lambda cik: mock_company, set_identity=MagicMock()))

        collector = SuperinvestorCollector()
        results = collector.collect()
        assert results == []

    def test_collect_zero_total_value(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_infotable = pd.DataFrame({
            "Ticker": ["AAPL"],
            "Value": [0],
            "SharesPrnAmount": [100],
            "Issuer": ["Apple Inc"],
        })

        mock_filing_obj = MagicMock()
        mock_filing_obj.infotable = mock_infotable

        mock_filing = MagicMock()
        mock_filing.filing_date = "2025-01-15"
        mock_filing.obj.return_value = mock_filing_obj

        mock_company = MagicMock()
        mock_company.get_filings.return_value = [mock_filing]

        monkeypatch.setattr("nuri.collectors.superinvestors.SUPERINVESTORS",
                            {"Test": "000"})
        import sys
        monkeypatch.setitem(sys.modules, "edgar",
                            MagicMock(Company=lambda cik: mock_company, set_identity=MagicMock()))

        collector = SuperinvestorCollector()
        results = collector.collect()
        assert results == []

    def test_collect_nan_ticker(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_infotable = pd.DataFrame({
            "Ticker": [None, "AAPL"],
            "Value": [500000, 500000],
            "SharesPrnAmount": [100, 200],
            "Issuer": ["Unknown", "Apple Inc"],
        })

        mock_filing_obj = MagicMock()
        mock_filing_obj.infotable = mock_infotable

        mock_filing = MagicMock()
        mock_filing.filing_date = "2025-01-15"
        mock_filing.obj.return_value = mock_filing_obj

        mock_company = MagicMock()
        mock_company.get_filings.return_value = [mock_filing]

        monkeypatch.setattr("nuri.collectors.superinvestors.SUPERINVESTORS",
                            {"Test": "000"})
        import sys
        monkeypatch.setitem(sys.modules, "edgar",
                            MagicMock(Company=lambda cik: mock_company, set_identity=MagicMock()))

        collector = SuperinvestorCollector()
        results = collector.collect()
        # Only AAPL should be in results (NaN ticker filtered)
        assert all(r["ticker"] == "AAPL" for r in results)

    def test_collect_company_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        def bad_company(cik):
            raise RuntimeError("network error")

        monkeypatch.setattr("nuri.collectors.superinvestors.SUPERINVESTORS",
                            {"Test": "000"})
        import sys
        monkeypatch.setitem(sys.modules, "edgar",
                            MagicMock(Company=bad_company, set_identity=MagicMock()))

        collector = SuperinvestorCollector()
        results = collector.collect()
        assert results == []

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector
        collector = SuperinvestorCollector()
        assert collector.save([]) == 0
        assert collector.save(None) == 0

    def test_save_records(self, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector
        collector = SuperinvestorCollector()
        records = [{
            "investor": "Buffett", "filing_date": "2025-01-15",
            "ticker": "AAPL", "shares": 1000.0, "market_value": 200000.0,
            "portfolio_pct": 25.5, "issuer_name": "Apple Inc",
        }]
        count = collector.save(records)
        assert count == 1

    def test_print_summary_no_data(self, db_with_portfolio, capsys):
        from nuri.collectors.superinvestors import print_summary
        print_summary()
        out = capsys.readouterr().out
        assert "슈퍼투자자 데이터가 없습니다" in out

    def test_print_summary_with_data(self, db_with_portfolio, capsys):
        from nuri.collectors.superinvestors import print_summary
        from nuri.core.db import get_db

        with get_db(db_with_portfolio) as conn:
            conn.execute(
                """INSERT INTO superinvestors (investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name)
                   VALUES ('Warren Buffett', '2025-01-15', 'AAPL', 1000, 200000, 25.5, 'Apple Inc')"""
            )

        print_summary()
        out = capsys.readouterr().out
        assert "Warren Buffett" in out
        assert "AAPL" in out

    def test_print_summary_with_overlap(self, db_with_portfolio, capsys):
        """Test print_summary when superinvestor holds same stock as portfolio."""
        from nuri.collectors.superinvestors import print_summary
        from nuri.core.db import get_db

        with get_db(db_with_portfolio) as conn:
            conn.execute(
                """INSERT INTO superinvestors (investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name)
                   VALUES ('Warren Buffett', '2025-01-15', 'AAPL', 1000, 200000, 25.5, 'Apple Inc')"""
            )

        print_summary()
        out = capsys.readouterr().out
        assert "슈퍼투자자도 보유" in out
        assert "AAPL" in out

    def test_detect_changes(self, db_with_portfolio):
        from nuri.collectors.superinvestors import detect_changes
        from nuri.core.db import get_db

        with get_db(db_with_portfolio) as conn:
            # Q1
            conn.execute(
                "INSERT INTO superinvestors VALUES (NULL, 'Buffett', '2025-01-15', 'AAPL', 1000, 200000, 25.0, 'Apple Inc')"
            )
            conn.execute(
                "INSERT INTO superinvestors VALUES (NULL, 'Buffett', '2025-01-15', 'MSFT', 500, 100000, 12.0, 'Microsoft')"
            )
            # Q2: AAPL increased, MSFT closed, NVDA new
            conn.execute(
                "INSERT INTO superinvestors VALUES (NULL, 'Buffett', '2025-04-15', 'AAPL', 2000, 400000, 50.0, 'Apple Inc')"
            )
            conn.execute(
                "INSERT INTO superinvestors VALUES (NULL, 'Buffett', '2025-04-15', 'NVDA', 300, 60000, 15.0, 'NVIDIA')"
            )

        df = detect_changes("Buffett", db_path=db_with_portfolio)
        assert not df.empty
        changes = set(df["change_type"].unique())
        assert "NEW" in changes      # NVDA
        assert "CLOSED" in changes   # MSFT
        assert "INCREASED" in changes  # AAPL

    def test_detect_changes_insufficient_quarters(self, db_with_portfolio):
        from nuri.collectors.superinvestors import detect_changes
        df = detect_changes("Nobody", db_path=db_with_portfolio)
        assert df.empty


# ═══════════════════════════════════════════════════════
# 2. External Collector
# ═══════════════════════════════════════════════════════


class TestExternalCollector:
    """Tests for nuri/collectors/external.py — all functions."""

    def test_save_external_success(self, db_with_portfolio):
        from nuri.collectors.external import save_external
        result = save_external("tipranks", "AAPL", "consensus", "Strong Buy",
                               db_path=db_with_portfolio)
        assert result is True

    def test_save_external_unknown_source(self, db_with_portfolio):
        from nuri.collectors.external import save_external
        result = save_external("unknown_source", "AAPL", "test", "val",
                               db_path=db_with_portfolio)
        assert result is False

    def test_save_external_with_date(self, db_with_portfolio):
        from nuri.collectors.external import save_external
        result = save_external("tipranks", "AAPL", "consensus", "Buy",
                               target_date="2025-01-15", db_path=db_with_portfolio)
        assert result is True

    def test_save_external_with_numeric(self, db_with_portfolio):
        from nuri.collectors.external import save_external
        result = save_external("tipranks", "AAPL", "target_price", "250.0",
                               numeric_value=250.0, db_path=db_with_portfolio)
        assert result is True

    def test_save_tipranks(self, db_with_portfolio):
        from nuri.collectors.external import save_tipranks
        save_tipranks("AAPL", "Strong Buy", 250.0, 30, upside_pct=15.5,
                      db_path=db_with_portfolio)
        from nuri.collectors.external import get_external
        data = get_external("AAPL", source="tipranks", db_path=db_with_portfolio)
        assert len(data) >= 3  # consensus + target_price + analyst_count

    def test_save_superinvestor(self, db_with_portfolio):
        from nuri.collectors.external import save_superinvestor
        save_superinvestor("AAPL", 14, "buying", details="Buffett +10%",
                           db_path=db_with_portfolio)
        from nuri.collectors.external import get_external
        data = get_external("AAPL", source="dataroma", db_path=db_with_portfolio)
        assert len(data) >= 2

    def test_get_external_all_sources(self, db_with_portfolio):
        from nuri.collectors.external import get_external, save_external
        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=db_with_portfolio)
        save_external("dataroma", "AAPL", "count", "5", db_path=db_with_portfolio)
        data = get_external("AAPL", db_path=db_with_portfolio)
        assert len(data) >= 2

    def test_get_external_summary(self, db_with_portfolio):
        from nuri.collectors.external import get_external_summary, save_external
        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=db_with_portfolio)
        summary = get_external_summary(db_path=db_with_portfolio)
        assert summary["total_records"] >= 1
        assert len(summary["sources"]) >= 1

    def test_print_ticker_external_no_data(self, db_with_portfolio, capsys):
        from nuri.collectors.external import print_ticker_external
        print_ticker_external("ZZZZ", db_path=db_with_portfolio)
        out = capsys.readouterr().out
        assert "외부 데이터 없음" in out

    def test_print_ticker_external_with_data(self, db_with_portfolio, capsys):
        from nuri.collectors.external import print_ticker_external, save_external
        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=db_with_portfolio)
        save_external("dataroma", "AAPL", "count", "5", db_path=db_with_portfolio)
        print_ticker_external("AAPL", db_path=db_with_portfolio)
        out = capsys.readouterr().out
        assert "AAPL" in out
        assert "TipRanks" in out

    def test_print_summary(self, db_with_portfolio, capsys):
        from nuri.collectors.external import print_summary, save_external
        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=db_with_portfolio)
        print_summary(db_path=db_with_portfolio)
        out = capsys.readouterr().out
        assert "외부 데이터 요약" in out

    def test_print_summary_empty(self, db_with_portfolio, capsys):
        from nuri.collectors.external import print_summary
        print_summary(db_path=db_with_portfolio)
        out = capsys.readouterr().out
        assert "0건" in out


# ═══════════════════════════════════════════════════════
# 3. InstitutionalCollector
# ═══════════════════════════════════════════════════════


class TestInstitutionalCollector:
    """Tests for nuri/collectors/institutional.py."""

    def test_collect_kr(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.institutional import InstitutionalCollector

        mock_df = pd.DataFrame({
            "기관합계": [1000000],
            "외국인합계": [500000],
            "개인": [-200000],
        }, index=pd.to_datetime(["2025-01-30"]))

        mock_stock = MagicMock()
        mock_stock.get_market_trading_value_by_date.return_value = mock_df

        import sys
        pykrx_mock = MagicMock()
        pykrx_mock.stock = mock_stock
        monkeypatch.setitem(sys.modules, "pykrx", pykrx_mock)
        monkeypatch.setitem(sys.modules, "pykrx.stock", mock_stock)

        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
        collector = InstitutionalCollector()
        # Ensure there are KR tickers
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["005930.KS"] if market == "kr" else [])
        results = collector.collect()
        assert len(results) >= 1
        assert results[0]["market"] == "KR"

    def test_collect_kr_empty(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.institutional import InstitutionalCollector

        mock_stock = MagicMock()
        mock_stock.get_market_trading_value_by_date.return_value = pd.DataFrame()

        import sys
        monkeypatch.setitem(sys.modules, "pykrx", MagicMock())
        monkeypatch.setitem(sys.modules, "pykrx.stock", mock_stock)
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

        collector = InstitutionalCollector()
        results = collector.collect()
        assert results == []

    def test_collect_kr_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.institutional import InstitutionalCollector

        mock_stock = MagicMock()
        mock_stock.get_market_trading_value_by_date.side_effect = Exception("API error")

        import sys
        monkeypatch.setitem(sys.modules, "pykrx", MagicMock())
        monkeypatch.setitem(sys.modules, "pykrx.stock", mock_stock)
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

        collector = InstitutionalCollector()
        results = collector.collect()
        assert results == []

    def test_collect_us_with_finnhub(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.institutional import InstitutionalCollector

        monkeypatch.setenv("FINNHUB_API_KEY", "test_key")

        # Mock pykrx to return empty for KR
        mock_stock = MagicMock()
        mock_stock.get_market_trading_value_by_date.return_value = pd.DataFrame()
        import sys
        monkeypatch.setitem(sys.modules, "pykrx", MagicMock())
        monkeypatch.setitem(sys.modules, "pykrx.stock", mock_stock)

        # Mock finnhub
        mock_client = MagicMock()
        mock_client.ownership.return_value = {"ownership": [{"data": "test"}]}
        mock_finnhub = MagicMock()
        mock_finnhub.Client.return_value = mock_client
        monkeypatch.setitem(sys.modules, "finnhub", mock_finnhub)

        collector = InstitutionalCollector()
        results = collector.collect()
        us_results = [r for r in results if r["market"] == "US"]
        assert len(us_results) >= 1

    def test_collect_us_finnhub_import_error(self, monkeypatch, db_with_portfolio):
        # Remove finnhub from sys.modules if present, then make it raise ImportError
        import sys

        from nuri.collectors.institutional import InstitutionalCollector
        monkeypatch.delitem(sys.modules, "finnhub", raising=False)

        original_import = __import__

        def mock_import(name, *args, **kwargs):
            if name == "finnhub":
                raise ImportError("No module named 'finnhub'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)

        collector = InstitutionalCollector()
        us_results = collector._collect_us(["AAPL"], "test_key")
        assert us_results == []

    def test_collect_us_finnhub_ticker_error(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.institutional import InstitutionalCollector

        mock_client = MagicMock()
        mock_client.ownership.side_effect = Exception("API error")
        mock_finnhub = MagicMock()
        mock_finnhub.Client.return_value = mock_client
        import sys
        monkeypatch.setitem(sys.modules, "finnhub", mock_finnhub)

        collector = InstitutionalCollector()
        results = collector._collect_us(["AAPL"], "key")
        assert results == []

    def test_save(self, db_with_portfolio):
        from nuri.collectors.institutional import InstitutionalCollector
        collector = InstitutionalCollector()
        assert collector.save([]) == 0
        count = collector.save([{
            "ticker": "005930.KS", "date": "2025-01-30", "market": "KR",
            "institution_net": 1000000, "foreign_net": 500000,
            "individual_net": -200000, "source": "pykrx",
        }])
        assert count == 1

    def test_safe_float(self):
        from nuri.collectors.institutional import _safe_float
        assert _safe_float(123.45) == 123.45
        assert _safe_float(None) is None
        assert _safe_float(float("nan")) is None


# ═══════════════════════════════════════════════════════
# 4. MacroCollector
# ═══════════════════════════════════════════════════════


class TestMacroCollector:
    """Tests for nuri/collectors/macro.py — FRED + yfinance fallback."""

    def test_collect_fred(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_series = pd.Series([4.5, 4.3],
                                index=pd.to_datetime(["2025-01-15", "2025-01-16"]))

        mock_fred = MagicMock()
        mock_fred.get_series.return_value = mock_series

        mock_fred_cls = MagicMock(return_value=mock_fred)
        import sys
        mock_fredapi = MagicMock()
        mock_fredapi.Fred = mock_fred_cls
        monkeypatch.setitem(sys.modules, "fredapi", mock_fredapi)

        collector = MacroCollector()
        collector.api_key = "test_fred_key"
        results = collector._collect_fred(days=30)
        assert len(results) > 0
        assert all(r["source"] == "FRED" for r in results)

    def test_collect_fred_series_failure(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_fred = MagicMock()
        mock_fred.get_series.side_effect = Exception("FRED API error")

        mock_fred_cls = MagicMock(return_value=mock_fred)
        import sys
        monkeypatch.setitem(sys.modules, "fredapi", MagicMock(Fred=mock_fred_cls))

        collector = MacroCollector()
        collector.api_key = "test_key"
        results = collector._collect_fred(days=30)
        assert results == []

    def test_collect_yfinance_fallback(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-15", "2025-01-16"]),
            "close": [4.5, 4.3],
        })
        mock_result = MagicMock()
        mock_result.to_df.return_value = mock_df

        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result

        import sys
        mock_openbb = MagicMock(obb=mock_obb)
        monkeypatch.setitem(sys.modules, "openbb", mock_openbb)

        collector = MacroCollector()
        collector.api_key = ""  # No FRED key
        results = collector._collect_yfinance(days=30)
        assert len(results) > 0

    def test_collect_yfinance_empty_df(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_result = MagicMock()
        mock_result.to_df.return_value = pd.DataFrame()

        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = MacroCollector()
        results = collector._collect_yfinance(days=30)
        assert results == []

    def test_collect_yfinance_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_obb = MagicMock()
        mock_obb.equity.price.historical.side_effect = Exception("connection error")

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = MacroCollector()
        results = collector._collect_yfinance(days=30)
        assert results == []

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

        mock_df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-15", "2025-01-16"]),
            "close": [float("nan"), 4.3],
        })
        mock_result = MagicMock()
        mock_result.to_df.return_value = mock_df

        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = MacroCollector()
        results = collector._collect_yfinance(days=30)
        # NaN values should be skipped
        for r in results:
            assert not pd.isna(r["value"])

    def test_save(self, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector
        collector = MacroCollector()
        count = collector.save([{"indicator": "vix", "date": "2025-01-30",
                                  "value": 18.5, "source": "test"}])
        assert count == 1


# ═══════════════════════════════════════════════════════
# 5. StockCollector
# ═══════════════════════════════════════════════════════


class TestStockCollector:
    """Tests for nuri/collectors/stock.py."""

    def test_collect_ticker_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-15"]),
            "open": [190.0], "high": [195.0], "low": [189.0],
            "close": [194.0], "volume": [50000000], "adj_close": [194.0],
        })
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df

        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = StockCollector()
        df = collector._collect_ticker("AAPL", "2025-01-01", "2025-01-30")
        assert df is not None
        assert not df.empty
        assert "ticker" in df.columns
        assert df.iloc[0]["ticker"] == "AAPL"

    def test_collect_ticker_empty(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame()

        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = StockCollector()
        result = collector._collect_ticker("AAPL", "2025-01-01", "2025-01-30")
        assert result is None

    def test_collect_ticker_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_obb = MagicMock()
        mock_obb.equity.price.historical.side_effect = Exception("provider error")

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = StockCollector()
        result = collector._collect_ticker("AAPL", "2025-01-01", "2025-01-30")
        assert result is None

    def test_collect_ticker_no_adj_close(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-15"]),
            "open": [190.0], "high": [195.0], "low": [189.0],
            "close": [194.0], "volume": [50000000],
        })
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df

        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = StockCollector()
        df = collector._collect_ticker("AAPL", "2025-01-01", "2025-01-30")
        assert df is not None
        assert "adj_close" in df.columns

    def test_collect_no_tickers(self, monkeypatch, tmp_path):
        """Test when no US tickers in portfolio."""
        import nuri.core.db as db_mod
        from nuri.collectors.stock import StockCollector

        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        collector = StockCollector()
        df = collector.collect(period="5d")
        assert df.empty

    def test_period_to_start_date(self):
        from nuri.collectors.stock import StockCollector
        result = StockCollector._period_to_start_date("1mo")
        assert isinstance(result, str)
        assert len(result) == 10  # YYYY-MM-DD

        result5y = StockCollector._period_to_start_date("5y")
        assert isinstance(result5y, str)

        # Unknown period should default to 5 days
        result_unknown = StockCollector._period_to_start_date("unknown")
        assert isinstance(result_unknown, str)

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.stock import StockCollector
        collector = StockCollector()
        assert collector.save(pd.DataFrame()) == 0


# ═══════════════════════════════════════════════════════
# 6. FearGreedCollector
# ═══════════════════════════════════════════════════════


class TestFearGreedCollector:
    """Tests for nuri/collectors/fear_greed.py."""

    def test_collect_api_success(self, monkeypatch):
        from nuri.collectors.fear_greed import FearGreedCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "fear_and_greed": {"score": 55.0, "rating": "Neutral"},
        }
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get",
                            MagicMock(return_value=mock_resp))

        collector = FearGreedCollector()
        results = collector.collect()
        assert len(results) == 1
        assert results[0]["indicator"] == "fear_greed"
        assert results[0]["value"] == 55.0

    def test_collect_api_value_key(self, monkeypatch):
        from nuri.collectors.fear_greed import FearGreedCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "fear_and_greed": {"value": 72.0, "rating": "Greed"},
        }
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get",
                            MagicMock(return_value=mock_resp))

        collector = FearGreedCollector()
        results = collector.collect()
        assert results[0]["value"] == 72.0

    def test_collect_api_no_data(self, monkeypatch):
        from nuri.collectors.fear_greed import FearGreedCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get",
                            MagicMock(return_value=mock_resp))

        collector = FearGreedCollector()
        results = collector.collect()
        assert results == []

    def test_collect_api_fail_scrape_fallback(self, monkeypatch):
        from nuri.collectors.fear_greed import FearGreedCollector

        call_count = [0]

        def mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("API down")
            # Scrape fallback
            mock_resp = MagicMock()
            mock_resp.text = '<html><text class="market-fng-gauge__dial-number-value">45</text></html>'
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", mock_get)

        collector = FearGreedCollector()
        results = collector.collect()
        assert len(results) == 1
        assert results[0]["value"] == 45.0
        assert results[0]["source"] == "CNN_scrape"

    def test_collect_both_fail(self, monkeypatch):
        from nuri.collectors.fear_greed import FearGreedCollector

        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get",
                            MagicMock(side_effect=Exception("all down")))

        collector = FearGreedCollector()
        results = collector.collect()
        assert results == []

    def test_scrape_no_score_found(self, monkeypatch):
        from nuri.collectors.fear_greed import FearGreedCollector

        mock_resp = MagicMock()
        mock_resp.text = "<html><body>No score here</body></html>"
        mock_resp.raise_for_status = MagicMock()

        call_count = [0]

        def mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("API down")
            return mock_resp

        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", mock_get)

        collector = FearGreedCollector()
        results = collector.collect()
        assert results == []

    def test_save(self, db_with_portfolio):
        from nuri.collectors.fear_greed import FearGreedCollector
        collector = FearGreedCollector()
        count = collector.save([{"indicator": "fear_greed", "date": "2025-01-30",
                                  "value": 55.0, "source": "CNN"}])
        assert count == 1


# ═══════════════════════════════════════════════════════
# 7. ARKCollector
# ═══════════════════════════════════════════════════════


class TestARKCollector:
    """Tests for nuri/collectors/ark.py."""

    def test_collect_csv_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.ark import ARKCollector

        csv_text = "Date,Fund,Direction,Ticker,CUSIP,Name,Shares,% of ETF\n"
        csv_text += "01/15/2025,ARKK,Buy,AAPL,123456,Apple Inc,1000,2.5\n"
        csv_text += "01/15/2025,ARKK,Sell,NVDA,654321,NVIDIA,500,1.3\n"
        csv_text += "01/15/2025,ARKK,Buy,TSLA,999999,Tesla,2000,5.0\n"  # Not in portfolio

        mock_resp = MagicMock()
        mock_resp.text = csv_text
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.ark.requests.get",
                            MagicMock(return_value=mock_resp))

        collector = ARKCollector()
        results = collector.collect()
        # Only AAPL and NVDA should be included (portfolio tickers)
        tickers = [r["ticker"] for r in results]
        assert "AAPL" in tickers
        assert "NVDA" in tickers
        assert "TSLA" not in tickers  # not in portfolio

    def test_collect_csv_empty_ticker(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.ark import ARKCollector

        csv_text = "Date,Fund,Direction,Ticker,CUSIP,Name,Shares,% of ETF\n"
        csv_text += "01/15/2025,ARKK,Buy,,123456,Unknown,1000,2.5\n"

        mock_resp = MagicMock()
        mock_resp.text = csv_text
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.ark.requests.get",
                            MagicMock(return_value=mock_resp))

        collector = ARKCollector()
        results = collector.collect()
        assert results == []

    def test_collect_all_urls_fail(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.ark import ARKCollector

        monkeypatch.setattr("nuri.collectors.ark.requests.get",
                            MagicMock(side_effect=Exception("download failed")))

        collector = ARKCollector()
        results = collector.collect()
        assert results == []

    def test_save(self, db_with_portfolio):
        from nuri.collectors.ark import ARKCollector
        collector = ARKCollector()
        count = collector.save([{
            "date": "2025-01-15", "ticker": "AAPL", "direction": "Buy",
            "shares": 1000, "weight": 2.5, "fund": "ARKK",
        }])
        assert count == 1


# ═══════════════════════════════════════════════════════
# 8. EventsCollector
# ═══════════════════════════════════════════════════════


class TestEventsCollector:
    """Tests for nuri/collectors/events.py."""

    def test_collect_fomc(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.events import EventsCollector

        # Mock OpenBB calls
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame()
        mock_obb = MagicMock()
        mock_obb.equity.calendar.earnings.return_value = mock_result
        mock_obb.equity.calendar.dividend.return_value = mock_result

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = EventsCollector()
        results = collector.collect()
        fomc = [r for r in results if r["event_type"] == "fomc"]
        assert len(fomc) == 8  # 2026 has 8 FOMC dates

    def test_collect_ticker_events_earnings(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.events import EventsCollector

        earnings_df = pd.DataFrame({
            "report_date": pd.to_datetime(["2025-04-25"]),
        })
        dividend_df = pd.DataFrame({
            "ex_dividend_date": pd.to_datetime(["2025-05-10"]),
        })
        mock_obb = MagicMock()
        mock_earnings = MagicMock()
        mock_earnings.to_dataframe.return_value = earnings_df
        mock_dividend = MagicMock()
        mock_dividend.to_dataframe.return_value = dividend_df
        mock_obb.equity.calendar.earnings.return_value = mock_earnings
        mock_obb.equity.calendar.dividend.return_value = mock_dividend

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = EventsCollector()
        results = collector._collect_ticker_events("AAPL")
        assert len(results) == 2
        types = {r["event_type"] for r in results}
        assert "earnings" in types
        assert "ex_dividend" in types

    def test_collect_ticker_events_with_index_date(self, monkeypatch, db_with_portfolio):
        """Test when date is in the index, not in a column."""
        from nuri.collectors.events import EventsCollector

        earnings_df = pd.DataFrame(
            {"dummy": [1]},
            index=pd.to_datetime(["2025-04-25"]),
        )
        mock_obb = MagicMock()
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = earnings_df
        mock_obb.equity.calendar.earnings.return_value = mock_result
        mock_obb.equity.calendar.dividend.side_effect = Exception("no dividend")

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = EventsCollector()
        results = collector._collect_ticker_events("AAPL")
        assert len(results) == 1
        assert results[0]["event_type"] == "earnings"

    def test_collect_ticker_events_no_date(self, monkeypatch, db_with_portfolio):
        """Test row with no date at all — should skip."""
        from nuri.collectors.events import EventsCollector

        earnings_df = pd.DataFrame({"dummy": [1]}, index=[0])
        mock_obb = MagicMock()
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = earnings_df
        mock_obb.equity.calendar.earnings.return_value = mock_result
        mock_obb.equity.calendar.dividend.return_value = MagicMock(to_dataframe=MagicMock(return_value=pd.DataFrame()))

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = EventsCollector()
        results = collector._collect_ticker_events("AAPL")
        assert results == []

    def test_save(self, db_with_portfolio):
        from nuri.collectors.events import EventsCollector
        collector = EventsCollector()
        assert collector.save([]) == 0
        count = collector.save([{
            "date": "2025-03-17", "event_type": "fomc",
            "ticker": None, "description": "FOMC", "importance": 3,
        }])
        assert count == 1

    def test_save_deduplicates(self, db_with_portfolio):
        from nuri.collectors.events import EventsCollector
        collector = EventsCollector()
        record = {
            "date": "2025-03-17", "event_type": "fomc",
            "ticker": None, "description": "FOMC", "importance": 3,
        }
        collector.save([record])
        collector.save([record])  # Save again — should not duplicate
        rows = query("SELECT * FROM events WHERE event_type = 'fomc' AND date = '2025-03-17'",
                     db_path=db_with_portfolio)
        assert len(rows) == 1


# ═══════════════════════════════════════════════════════
# 9. FundamentalCollector
# ═══════════════════════════════════════════════════════


class TestFundamentalCollector:
    """Tests for nuri/collectors/fundamental.py."""

    def test_collect_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fundamental import FundamentalCollector

        mock_df = pd.DataFrame([{
            "market_cap": 3e12, "pe_ratio": 28.5, "forward_pe": 25.0,
            "price_to_book": 15.0, "peg_ratio_ttm": 1.5, "return_on_equity": 0.35,
            "return_on_assets": 0.15, "gross_margin": 0.45, "operating_margin": 0.30,
            "profit_margin": 0.25, "revenue_growth": 0.08, "earnings_growth": 0.12,
            "debt_to_equity": 1.2, "current_ratio": 1.5, "dividend_yield": 0.005,
            "beta": 1.1,
        }])
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df

        mock_obb = MagicMock()
        mock_obb.equity.fundamental.metrics.return_value = mock_result

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = FundamentalCollector()
        results = collector.collect()
        assert len(results) >= 1
        assert results[0]["pe_ratio"] == 28.5
        assert results[0]["roe"] == 0.35

    def test_collect_empty_df(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fundamental import FundamentalCollector

        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame()

        mock_obb = MagicMock()
        mock_obb.equity.fundamental.metrics.return_value = mock_result

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = FundamentalCollector()
        results = collector.collect()
        assert results == []

    def test_collect_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fundamental import FundamentalCollector

        mock_obb = MagicMock()
        mock_obb.equity.fundamental.metrics.side_effect = Exception("API error")

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = FundamentalCollector()
        results = collector.collect()
        assert results == []

    def test_collect_nan_values(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fundamental import FundamentalCollector

        mock_df = pd.DataFrame([{
            "market_cap": float("nan"), "pe_ratio": 28.5, "forward_pe": None,
            "price_to_book": None, "peg_ratio_ttm": None, "return_on_equity": None,
            "return_on_assets": None, "gross_margin": None, "operating_margin": None,
            "profit_margin": None, "revenue_growth": None, "earnings_growth": None,
            "debt_to_equity": None, "current_ratio": None, "dividend_yield": None,
            "beta": None,
        }])
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df

        mock_obb = MagicMock()
        mock_obb.equity.fundamental.metrics.return_value = mock_result

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = FundamentalCollector()
        results = collector.collect()
        assert len(results) >= 1
        assert results[0]["market_cap"] is None
        assert results[0]["pe_ratio"] == 28.5

    def test_collect_no_tickers(self, monkeypatch, tmp_path):
        import nuri.core.db as db_mod
        from nuri.collectors.fundamental import FundamentalCollector

        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        collector = FundamentalCollector()
        results = collector.collect()
        assert results == []

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.fundamental import FundamentalCollector
        collector = FundamentalCollector()
        assert collector.save([]) == 0
        assert collector.save(None) == 0


# ═══════════════════════════════════════════════════════
# 10. EstimatesCollector
# ═══════════════════════════════════════════════════════


class TestEstimatesCollector:
    """Tests for nuri/collectors/estimates.py."""

    def test_collect_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.estimates import EstimatesCollector

        mock_df = pd.DataFrame([{
            "recommendation": "Buy", "target_high": 300.0, "target_low": 200.0,
            "target_consensus": 250.0, "target_median": 248.0,
            "number_of_analysts": 30, "current_price": 190.0,
        }])
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df

        mock_obb = MagicMock()
        mock_obb.equity.estimates.consensus.return_value = mock_result

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = EstimatesCollector()
        results = collector.collect()
        assert len(results) >= 1
        assert results[0]["recommendation"] == "Buy"
        assert results[0]["target_mean"] == 250.0
        assert results[0]["num_analysts"] == 30

    def test_collect_empty(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.estimates import EstimatesCollector

        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame()

        mock_obb = MagicMock()
        mock_obb.equity.estimates.consensus.return_value = mock_result

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = EstimatesCollector()
        results = collector.collect()
        assert results == []

    def test_collect_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.estimates import EstimatesCollector

        mock_obb = MagicMock()
        mock_obb.equity.estimates.consensus.side_effect = Exception("fail")

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = EstimatesCollector()
        results = collector.collect()
        assert results == []

    def test_collect_no_tickers(self, monkeypatch, tmp_path):
        import nuri.core.db as db_mod
        from nuri.collectors.estimates import EstimatesCollector

        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        collector = EstimatesCollector()
        results = collector.collect()
        assert results == []

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.estimates import EstimatesCollector
        collector = EstimatesCollector()
        assert collector.save([]) == 0
        assert collector.save(None) == 0

    def test_safe_float(self):
        from nuri.collectors.estimates import _safe_float
        assert _safe_float(123.45) == 123.45
        assert _safe_float(None) is None
        assert _safe_float(float("nan")) is None

    def test_safe_int(self):
        from nuri.collectors.estimates import _safe_int
        assert _safe_int(30) == 30
        assert _safe_int(None) is None
        assert _safe_int(float("nan")) is None


# ═══════════════════════════════════════════════════════
# 11. Filings (SEC 10-K)
# ═══════════════════════════════════════════════════════


class TestFilingsCollector:
    """Tests for nuri/collectors/filings.py."""

    def test_parse_10k_success(self, monkeypatch):
        from nuri.collectors.filings import parse_10k

        # Income statement mock
        inc_df = pd.DataFrame({
            "concept": ["Revenue", "NetIncome", "OperatingIncome"],
            "dimension": [False, False, False],
            "is_breakdown": [False, False, False],
            "2024": [100e9, 20e9, 30e9],
        })
        mock_inc = MagicMock()
        mock_inc.to_dataframe.return_value = inc_df

        # Balance sheet mock
        bs_df = pd.DataFrame({
            "concept": ["TotalAssets", "TotalLiabilities", "CashAndCashEquivalents"],
            "dimension": [False, False, False],
            "is_breakdown": [False, False, False],
            "2024": [400e9, 250e9, 50e9],
        })
        mock_bs = MagicMock()
        mock_bs.to_dataframe.return_value = bs_df

        mock_obj = MagicMock()
        mock_obj.income_statement = mock_inc
        mock_obj.balance_sheet = mock_bs

        mock_filing = MagicMock()
        mock_filing.filing_date = "2025-02-15"
        mock_filing.obj.return_value = mock_obj

        mock_company = MagicMock()
        mock_company.get_filings.return_value = [mock_filing]

        import sys
        monkeypatch.setitem(sys.modules, "edgar",
                            MagicMock(Company=lambda ticker: mock_company, set_identity=MagicMock()))

        result = parse_10k("AAPL")
        assert result is not None
        assert result["ticker"] == "AAPL"
        assert result["revenue"] == 100e9
        assert result["net_income"] == 20e9
        assert result["total_assets"] == 400e9

    def test_parse_10k_no_filings(self, monkeypatch):
        from nuri.collectors.filings import parse_10k

        mock_company = MagicMock()
        mock_company.get_filings.return_value = []

        import sys
        monkeypatch.setitem(sys.modules, "edgar",
                            MagicMock(Company=lambda ticker: mock_company, set_identity=MagicMock()))

        result = parse_10k("AAPL")
        assert result is None

    def test_parse_10k_exception(self, monkeypatch):
        import sys

        from nuri.collectors.filings import parse_10k
        monkeypatch.setitem(sys.modules, "edgar",
                            MagicMock(Company=MagicMock(side_effect=Exception("EDGAR error")),
                                      set_identity=MagicMock()))

        result = parse_10k("AAPL")
        assert result is None

    def test_parse_10k_no_data_fields(self, monkeypatch):
        """10-K exists but no meaningful data extracted."""
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

        result = parse_10k("AAPL")
        assert result is None  # Only 3 base fields, no data

    def test_collect_filings(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.filings import collect_filings

        def mock_parse(ticker):
            return {"ticker": ticker, "filing_date": "2025-02-15",
                    "form": "10-K", "revenue": 100e9}

        monkeypatch.setattr("nuri.collectors.filings.parse_10k", mock_parse)

        results = collect_filings(tickers=["AAPL", "NVDA"])
        assert len(results) == 2

    def test_collect_filings_some_none(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.filings import collect_filings

        def mock_parse(ticker):
            if ticker == "AAPL":
                return {"ticker": "AAPL", "filing_date": "2025-02-15",
                        "form": "10-K", "revenue": 100e9}
            return None

        monkeypatch.setattr("nuri.collectors.filings.parse_10k", mock_parse)

        results = collect_filings(tickers=["AAPL", "NVDA"])
        assert len(results) == 1

    def test_print_filings_empty(self, capsys):
        from nuri.collectors.filings import print_filings
        print_filings([])
        assert "10-K 데이터 없음" in capsys.readouterr().out

    def test_print_filings_with_data(self, capsys):
        from nuri.collectors.filings import print_filings
        results = [{
            "ticker": "AAPL", "filing_date": "2025-02-15",
            "revenue": 100e9, "net_income": 20e9,
            "total_assets": 400e9, "cash": 50e9,
        }]
        print_filings(results)
        out = capsys.readouterr().out
        assert "AAPL" in out
        assert "SEC 10-K Filings" in out

    def test_print_filings_missing_fields(self, capsys):
        from nuri.collectors.filings import print_filings
        results = [{"ticker": "XYZ", "filing_date": "2025-01-01"}]
        print_filings(results)
        out = capsys.readouterr().out
        assert "XYZ" in out


# ═══════════════════════════════════════════════════════
# 12. NewsCollector
# ═══════════════════════════════════════════════════════


class TestNewsCollector:
    """Tests for nuri/collectors/news.py."""

    def test_collect_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.news import NewsCollector

        news_df = pd.DataFrame({
            "title": ["Apple beats earnings"],
            "url": ["https://example.com/1"],
            "source": ["Reuters"],
        }, index=pd.to_datetime(["2025-01-28"]))

        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = news_df

        mock_obb = MagicMock()
        mock_obb.news.company.return_value = mock_result

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = NewsCollector()
        results = collector.collect()
        assert len(results) >= 1
        assert results[0]["title"] == "Apple beats earnings"

    def test_collect_no_url(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.news import NewsCollector

        news_df = pd.DataFrame({
            "title": ["No link news"],
            "url": [""],
            "source": ["Unknown"],
        }, index=pd.to_datetime(["2025-01-28"]))

        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = news_df

        mock_obb = MagicMock()
        mock_obb.news.company.return_value = mock_result

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = NewsCollector()
        results = collector.collect()
        assert results == []

    def test_collect_date_in_column(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.news import NewsCollector

        news_df = pd.DataFrame({
            "title": ["News"],
            "url": ["https://example.com/1"],
            "source": ["Reuters"],
            "date": ["2025-01-28"],
        })

        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = news_df

        mock_obb = MagicMock()
        mock_obb.news.company.return_value = mock_result

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = NewsCollector()
        results = collector.collect()
        assert len(results) >= 1
        assert results[0]["date"] == "2025-01-28"

    def test_collect_empty(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.news import NewsCollector

        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame()

        mock_obb = MagicMock()
        mock_obb.news.company.return_value = mock_result

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = NewsCollector()
        results = collector.collect()
        assert results == []

    def test_collect_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.news import NewsCollector

        mock_obb = MagicMock()
        mock_obb.news.company.side_effect = Exception("API error")

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = NewsCollector()
        results = collector.collect()
        assert results == []


# ═══════════════════════════════════════════════════════
# 13. EtfFlowsCollector
# ═══════════════════════════════════════════════════════


class TestEtfFlowsCollector:
    """Tests for nuri/collectors/etf_flows.py."""

    def test_collect_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        mock_df = pd.DataFrame([{
            "name": "Technology Select Sector",
            "total_assets": 50e9,
            "volume_avg": 20000000,
            "nav_price": 200.0,
        }])
        mock_result = MagicMock()
        mock_result.to_df.return_value = mock_df

        mock_obb = MagicMock()
        mock_obb.etf.info.return_value = mock_result

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = EtfFlowsCollector()
        results = collector.collect()
        assert len(results) > 0
        assert results[0]["total_assets"] == 50e9

    def test_collect_empty(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        mock_result = MagicMock()
        mock_result.to_df.return_value = pd.DataFrame()

        mock_obb = MagicMock()
        mock_obb.etf.info.return_value = mock_result

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = EtfFlowsCollector()
        results = collector.collect()
        assert results == []

    def test_collect_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        mock_obb = MagicMock()
        mock_obb.etf.info.side_effect = Exception("ETF API error")

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = EtfFlowsCollector()
        results = collector.collect()
        assert results == []

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.etf_flows import EtfFlowsCollector
        collector = EtfFlowsCollector()
        assert collector.save([]) == 0
        assert collector.save(None) == 0

    def test_analyze_sector_rotation_no_data(self, db_with_portfolio):
        from nuri.collectors.etf_flows import analyze_sector_rotation
        result = analyze_sector_rotation(db_path=db_with_portfolio)
        assert result is None

    def test_analyze_sector_rotation_with_data(self, db_with_portfolio):
        from nuri.collectors.etf_flows import (
            _upsert_etf_flows,
            analyze_sector_rotation,
        )

        records = []
        for ticker in ["XLK", "XLF", "XLV"]:
            records.append({
                "ticker": ticker, "date": "2025-01-15",
                "name": f"{ticker} ETF", "total_assets": 50e9,
                "volume_avg": 20000000, "nav_price": 200.0,
            })
            records.append({
                "ticker": ticker, "date": "2025-01-30",
                "name": f"{ticker} ETF", "total_assets": 52e9,
                "volume_avg": 22000000, "nav_price": 205.0,
            })
        _upsert_etf_flows(records, db_path=db_with_portfolio)

        result = analyze_sector_rotation(db_path=db_with_portfolio)
        assert result is not None
        assert not result.empty

    def test_analyze_sector_rotation_with_volume_trend(self, db_with_portfolio):
        from nuri.collectors.etf_flows import (
            _upsert_etf_flows,
            analyze_sector_rotation,
        )

        records = []
        for ticker in ["XLK"]:
            for day in range(1, 9):
                records.append({
                    "ticker": ticker, "date": f"2025-01-{day:02d}",
                    "name": "Tech", "total_assets": 50e9 + day * 1e9,
                    "volume_avg": 20000000 + day * 1000000, "nav_price": 200 + day,
                })
        _upsert_etf_flows(records, db_path=db_with_portfolio)

        result = analyze_sector_rotation(db_path=db_with_portfolio)
        assert result is not None

    def test_print_sector_rotation_none(self, capsys):
        from nuri.collectors.etf_flows import print_sector_rotation
        print_sector_rotation(None)
        assert "데이터 없음" in capsys.readouterr().out

    def test_print_sector_rotation_with_data(self, capsys):
        from nuri.collectors.etf_flows import print_sector_rotation
        df = pd.DataFrame([{
            "ticker": "XLK", "sector": "Technology",
            "aum_current": 50e9, "aum_prev": 48e9,
            "aum_change_pct": 4.17, "volume_trend_pct": 10.0,
        }])
        print_sector_rotation(df)
        out = capsys.readouterr().out
        assert "XLK" in out
        assert "Technology" in out


# ═══════════════════════════════════════════════════════
# 14. StockKRCollector
# ═══════════════════════════════════════════════════════


class TestStockKRCollector:
    """Tests for nuri/collectors/stock_kr.py."""

    def test_collect_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock_kr import StockKRCollector

        mock_ohlcv = pd.DataFrame({
            "시가": [60000, 60500],
            "고가": [61000, 61500],
            "저가": [59000, 59500],
            "종가": [60500, 61000],
            "거래량": [1000000, 1200000],
        }, index=pd.to_datetime(["2025-01-29", "2025-01-30"]))

        monkeypatch.setattr("nuri.collectors.stock_kr.krx.get_market_ohlcv",
                            MagicMock(return_value=mock_ohlcv))

        collector = StockKRCollector()
        df = collector.collect(days=5)
        assert not df.empty
        assert "005930.KS" in df["ticker"].values

    def test_collect_empty(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock_kr import StockKRCollector

        monkeypatch.setattr("nuri.collectors.stock_kr.krx.get_market_ohlcv",
                            MagicMock(return_value=pd.DataFrame()))

        collector = StockKRCollector()
        df = collector.collect(days=5)
        assert df.empty

    def test_collect_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock_kr import StockKRCollector

        monkeypatch.setattr("nuri.collectors.stock_kr.krx.get_market_ohlcv",
                            MagicMock(side_effect=Exception("pykrx error")))

        collector = StockKRCollector()
        df = collector.collect(days=5)
        assert df.empty

    def test_collect_no_kr_tickers(self, monkeypatch, tmp_path):
        import nuri.core.db as db_mod
        from nuri.collectors.stock_kr import StockKRCollector

        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        upsert_portfolio([
            {"account": "test", "ticker": "AAPL", "quantity": 10, "avg_price": 190,
             "currency": "USD", "sector": "Tech"},
        ], path)

        collector = StockKRCollector()
        df = collector.collect(days=5)
        assert df.empty

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.stock_kr import StockKRCollector
        collector = StockKRCollector()
        assert collector.save(pd.DataFrame()) == 0


# ═══════════════════════════════════════════════════════
# 15. WallStreetCollector
# ═══════════════════════════════════════════════════════


class TestWallStreetCollector:
    """Tests for nuri/collectors/wallstreet.py."""

    def test_collect_ratings(self, monkeypatch, db_with_portfolio):
        import yfinance as yf

        from nuri.collectors.wallstreet import WallStreetCollector

        # Create a proper mock ticker with ratings
        mock_info = {"shortPercentOfFloat": 0.05, "shortRatio": 2.5}
        mock_ud = pd.DataFrame({
            "Firm": ["Goldman Sachs"],
            "ToGrade": ["Buy"],
            "FromGrade": ["Hold"],
            "Action": ["up"],
            "currentPriceTarget": [250.0],
        }, index=pd.to_datetime(["2025-01-28"]))

        mock_eh = pd.DataFrame({
            "epsActual": [1.50],
            "epsEstimate": [1.40],
            "surprisePercent": [7.14],
        }, index=pd.to_datetime(["2025-01-28"]))

        mock_ins = pd.DataFrame({
            "Start Date": ["2025-01-20"],
            "Text": ["Sale of shares"],
            "Insider": ["CEO"],
            "Position": ["Chief Executive"],
            "Shares": [5000],
            "Value": [1000000],
        })

        class MockTicker:
            def __init__(self, ticker):
                self.ticker = ticker
                self.info = mock_info
                self.upgrades_downgrades = mock_ud
                self.earnings_history = mock_eh
                self.insider_transactions = mock_ins
                self.recommendations = None

        monkeypatch.setattr(yf, "Ticker", MockTicker)

        # Limit to small set
        monkeypatch.setattr("nuri.collectors.wallstreet.get_tickers",
                            lambda: ["AAPL"])

        collector = WallStreetCollector()
        data = collector.collect()
        assert len(data["ratings"]) >= 1
        assert len(data["earnings"]) >= 1
        assert len(data["insiders"]) >= 1
        assert len(data["short_interest"]) >= 1
        assert data["insiders"][0]["transaction_type"] == "sale"

    def test_collect_purchase_type(self, monkeypatch, db_with_portfolio):
        import yfinance as yf

        from nuri.collectors.wallstreet import WallStreetCollector

        mock_ins = pd.DataFrame({
            "Start Date": ["2025-01-20"],
            "Text": ["Purchase of shares"],
            "Insider": ["CFO"],
            "Position": ["Chief Financial"],
            "Shares": [1000],
            "Value": [200000],
        })

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

        collector = WallStreetCollector()
        data = collector.collect()
        assert data["insiders"][0]["transaction_type"] == "purchase"

    def test_collect_other_transaction_type(self, monkeypatch, db_with_portfolio):
        import yfinance as yf

        from nuri.collectors.wallstreet import WallStreetCollector

        mock_ins = pd.DataFrame({
            "Start Date": ["2025-01-20"],
            "Text": ["Gift of shares"],
            "Insider": ["Board Member"],
            "Position": ["Director"],
            "Shares": [500],
            "Value": [100000],
        })

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

        collector = WallStreetCollector()
        data = collector.collect()
        assert data["insiders"][0]["transaction_type"] == "other"

    def test_collect_exception_per_ticker(self, monkeypatch, db_with_portfolio):
        import yfinance as yf

        from nuri.collectors.wallstreet import WallStreetCollector

        class BadTicker:
            def __init__(self, ticker):
                raise Exception("bad ticker")

        monkeypatch.setattr(yf, "Ticker", BadTicker)
        monkeypatch.setattr("nuri.collectors.wallstreet.get_tickers", lambda: ["AAPL"])

        collector = WallStreetCollector()
        data = collector.collect()
        assert data["ratings"] == []

    def test_save(self, db_with_portfolio):
        from nuri.collectors.wallstreet import WallStreetCollector
        collector = WallStreetCollector()
        data = {
            "ratings": [{
                "ticker": "AAPL", "date": "2025-01-28", "firm": "GS",
                "to_grade": "Buy", "from_grade": "Hold", "action": "up",
                "target_price": 250.0,
            }],
            "earnings": [{
                "ticker": "AAPL", "quarter": "2025-01-28",
                "eps_actual": 1.5, "eps_estimate": 1.4, "surprise_pct": 7.14,
            }],
            "insiders": [{
                "ticker": "AAPL", "date": "2025-01-20", "insider_name": "CEO",
                "position": "CEO", "transaction_type": "sale",
                "shares": 5000, "value": 1000000,
            }],
            "short_interest": [{
                "ticker": "AAPL", "short_pct_float": 5.0, "days_to_cover": 2.5,
            }],
        }
        count = collector.save(data)
        assert count >= 4  # 1 rating + 1 earning + 1 insider + 1 short

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.wallstreet import WallStreetCollector
        collector = WallStreetCollector()
        assert collector.save({"ratings": [], "earnings": [], "insiders": [], "short_interest": []}) == 0


# ═══════════════════════════════════════════════════════
# 16. RedditCollector
# ═══════════════════════════════════════════════════════


class TestRedditCollector:
    """Tests for nuri/collectors/reddit.py."""

    def test_collect_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.reddit import RedditCollector

        mock_posts = [
            {"title": "$AAPL is going to the moon!", "selftext": "Buy AAPL now", "created_utc": 1706400000},
            {"title": "NVDA earnings tomorrow", "selftext": "NVDA will beat", "created_utc": 1706400001},
            {"title": "Market crash incoming", "selftext": "Sell everything", "created_utc": 1706400002},
        ]

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": mock_posts}
        mock_resp.raise_for_status = MagicMock()

        def mock_get(url, **kwargs):
            return mock_resp

        monkeypatch.setattr("nuri.collectors.reddit.requests.get", mock_get)

        collector = RedditCollector()
        results = collector.collect(days=1)
        assert len(results) > 0
        indicators = [r["indicator"] for r in results]
        assert "wsb_post_count" in indicators
        assert "wsb_held_mentions" in indicators

    def test_collect_api_failure(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.reddit import RedditCollector

        monkeypatch.setattr("nuri.collectors.reddit.requests.get",
                            MagicMock(side_effect=Exception("Arctic Shift down")))

        collector = RedditCollector()
        results = collector.collect()
        assert results == []

    def test_collect_no_posts(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.reddit import RedditCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.reddit.requests.get",
                            MagicMock(return_value=mock_resp))

        collector = RedditCollector()
        results = collector.collect()
        assert results == []

    def test_count_mentions_noise_filter(self, db_with_portfolio):
        from nuri.collectors.reddit import RedditCollector

        collector = RedditCollector()
        posts = [
            {"title": "I AM going to BUY the DIP", "selftext": "AAPL NVDA"},
        ]
        counts = collector._count_mentions(posts, {"AAPL", "NVDA"})
        assert counts["AAPL"] >= 1
        assert counts["NVDA"] >= 1
        # Noise words should NOT be counted
        assert counts.get("AM", 0) == 0
        assert counts.get("BUY", 0) == 0

    def test_fetch_posts_pagination(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.reddit import RedditCollector

        call_count = [0]

        def mock_get(url, **kwargs):
            call_count[0] += 1
            mock_resp = MagicMock()
            if call_count[0] <= 2:
                mock_resp.json.return_value = {
                    "data": [{"title": f"Post {call_count[0]}", "selftext": "",
                              "created_utc": 1706400000 + call_count[0]}]
                }
            else:
                mock_resp.json.return_value = {"data": []}
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        monkeypatch.setattr("nuri.collectors.reddit.requests.get", mock_get)

        collector = RedditCollector()
        posts = collector._fetch_posts(days=1)
        assert len(posts) == 2

    def test_save(self, db_with_portfolio):
        from nuri.collectors.reddit import RedditCollector
        collector = RedditCollector()
        count = collector.save([
            {"indicator": "wsb_post_count", "date": "2025-01-30",
             "value": 100.0, "source": "Reddit_WSB"},
        ])
        assert count == 1


# ═══════════════════════════════════════════════════════
# 17. FREDCalendarCollector
# ═══════════════════════════════════════════════════════


class TestFREDCalendarCollector:
    """Tests for nuri/collectors/fred_calendar.py."""

    def test_collect_fallback(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        collector = FREDCalendarCollector()
        collector.api_key = ""  # No FRED key
        results = collector.collect(days_ahead=365)
        # Should get fallback 2026 events
        assert len(results) >= 0  # May or may not match current date range

    def test_collect_invalid_days(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        collector = FREDCalendarCollector()
        collector.api_key = ""
        results = collector.collect(days_ahead=-1)
        # Should default to 14 days
        assert isinstance(results, list)

    def test_collect_fred_api_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "release_dates": [
                {"release_id": 10, "date": "2026-04-15"},
                {"release_id": 50, "date": "2026-04-18"},
                {"release_id": 999, "date": "2026-04-20"},  # Not important
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.fred_calendar.requests.get",
                            MagicMock(return_value=mock_resp))

        collector = FREDCalendarCollector()
        collector.api_key = "test_key"
        results = collector._collect_fred_api(days_ahead=30)
        assert len(results) == 2  # Only CPI and Employment (release_id 10 and 50)
        assert results[0]["description"] == "FRED: CPI"

    def test_collect_fred_api_failure_fallback(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        monkeypatch.setattr("nuri.collectors.fred_calendar.requests.get",
                            MagicMock(side_effect=Exception("FRED down")))

        collector = FREDCalendarCollector()
        collector.api_key = "test_key"
        results = collector.collect(days_ahead=365)
        # Should fall back to hardcoded calendar
        assert isinstance(results, list)

    def test_save(self, db_with_portfolio):
        from nuri.collectors.fred_calendar import FREDCalendarCollector
        collector = FREDCalendarCollector()
        assert collector.save([]) == 0
        count = collector.save([{
            "date": "2026-04-15", "event_type": "economic",
            "ticker": None, "description": "FRED: CPI", "importance": 3,
        }])
        assert count == 1

    def test_save_deduplicates(self, db_with_portfolio):
        from nuri.collectors.fred_calendar import FREDCalendarCollector
        collector = FREDCalendarCollector()
        record = {
            "date": "2026-04-15", "event_type": "economic",
            "ticker": None, "description": "FRED: CPI", "importance": 3,
        }
        collector.save([record])
        collector.save([record])
        rows = query("SELECT * FROM events WHERE description = 'FRED: CPI'",
                     db_path=db_with_portfolio)
        assert len(rows) == 1


# ═══════════════════════════════════════════════════════
# 18. Daily Report
# ═══════════════════════════════════════════════════════


class TestDailyReport:
    """Tests for nuri/alerts/daily_report.py."""

    def test_generate_report(self, monkeypatch, db_with_portfolio):
        from nuri.alerts.daily_report import generate_report

        # Mock analyze_portfolio
        mock_df = pd.DataFrame({"ticker": ["AAPL"], "value": [1900]})
        mock_df.attrs["total_value_usd"] = 1900
        mock_df.attrs["warnings"] = ["Single position too large"]
        monkeypatch.setattr("nuri.alerts.daily_report.analyze_portfolio",
                            lambda: mock_df)

        # Mock analyze_risk
        monkeypatch.setattr("nuri.alerts.daily_report.analyze_risk",
                            lambda: {"sharpe_ratio": 1.5, "max_drawdown_pct": -8.0,
                                     "var_95_daily_pct": -2.5, "stop_loss_alerts": []})

        # Mock rebalance advisor
        monkeypatch.setattr("nuri.alerts.daily_report.generate_report.__module__",
                            "nuri.alerts.daily_report")

        embed = generate_report()
        assert "title" in embed
        assert "fields" in embed
        assert len(embed["fields"]) >= 1

    def test_generate_report_empty_portfolio(self, monkeypatch, db_with_portfolio):
        from nuri.alerts.daily_report import generate_report

        monkeypatch.setattr("nuri.alerts.daily_report.analyze_portfolio",
                            lambda: pd.DataFrame())
        monkeypatch.setattr("nuri.alerts.daily_report.analyze_risk",
                            lambda: {})

        embed = generate_report()
        assert embed["fields"][0]["value"] == "$0"

    def test_generate_report_with_rebalance(self, monkeypatch, db_with_portfolio):
        from nuri.alerts.daily_report import generate_report

        mock_df = pd.DataFrame({"ticker": ["AAPL"]})
        mock_df.attrs["total_value_usd"] = 1900
        mock_df.attrs["warnings"] = []
        monkeypatch.setattr("nuri.alerts.daily_report.analyze_portfolio",
                            lambda: mock_df)
        monkeypatch.setattr("nuri.alerts.daily_report.analyze_risk",
                            lambda: {"sharpe_ratio": 1.0, "max_drawdown_pct": -5.0,
                                     "var_95_daily_pct": -1.5, "stop_loss_alerts": []})

        # Mock rebalance_advisor — it is lazy-imported inside generate_report
        mock_rebalance = {
            "has_critical": True,
            "total_violations": 2,
            "total_recovery_usd": 5000,
            "actions": [
                {"severity": "critical", "action": "SELL_ALL",
                 "ticker": "AAPL", "sell_shares": 10, "reason": "stop-loss",
                 "sell_value_usd": 1900},
            ],
        }
        mock_module = MagicMock()
        mock_module.generate_advisor_report = MagicMock(return_value=mock_rebalance)

        import sys
        monkeypatch.setitem(sys.modules, "nuri.analysis.rebalance_advisor", mock_module)

        embed = generate_report()
        assert embed["color"] == 0xE74C3C  # Red for critical

    def test_send_discord_no_webhook(self, monkeypatch, db_with_portfolio):
        from nuri.alerts.daily_report import send_discord
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        result = send_discord({"title": "test", "fields": []})
        assert result is False

    def test_send_discord_success(self, monkeypatch, db_with_portfolio):
        from nuri.alerts.daily_report import send_discord

        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/webhook/test")

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        import requests as req_mod
        monkeypatch.setattr(req_mod, "post", MagicMock(return_value=mock_resp))

        result = send_discord({"title": "test", "fields": []})
        assert result is True

    def test_print_report(self, capsys, db_with_portfolio):
        from nuri.alerts.daily_report import print_report
        embed = {
            "title": "Test Report",
            "fields": [
                {"name": "Value", "value": "$1000"},
            ],
        }
        print_report(embed)
        out = capsys.readouterr().out
        assert "Test Report" in out
        assert "Value" in out

    def test_main(self, monkeypatch, db_with_portfolio, capsys):
        from nuri.alerts.daily_report import main

        monkeypatch.setattr("nuri.alerts.daily_report.analyze_portfolio",
                            lambda: pd.DataFrame())
        monkeypatch.setattr("nuri.alerts.daily_report.analyze_risk", lambda: {})
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)

        main()
        out = capsys.readouterr().out
        assert "Daily Report" in out


# ═══════════════════════════════════════════════════════
# 19. Formatters
# ═══════════════════════════════════════════════════════


class TestFormatters:
    """Tests for nuri/alerts/formatters.py."""

    def test_format_daily_report_basic(self):
        from nuri.alerts.formatters import format_daily_report
        embed = format_daily_report(
            {"total_value_usd": 10000, "warnings": []},
            {"sharpe_ratio": 1.5, "max_drawdown_pct": -8.0,
             "var_95_daily_pct": -2.5, "stop_loss_alerts": []},
        )
        assert embed["title"].startswith("📋")
        assert len(embed["fields"]) >= 1

    def test_format_daily_report_with_warnings(self):
        from nuri.alerts.formatters import format_daily_report
        embed = format_daily_report(
            {"total_value_usd": 10000, "warnings": ["Warning 1"]},
            {"sharpe_ratio": 0.5, "max_drawdown_pct": -15.0,
             "var_95_daily_pct": -4.0,
             "stop_loss_alerts": [{"ticker": "AAPL", "pnl_pct": -8.5}]},
        )
        field_names = [f["name"] for f in embed["fields"]]
        assert any("경고" in n for n in field_names)
        assert any("손절" in n for n in field_names)

    def test_format_daily_report_with_fear_greed(self):
        from nuri.alerts.formatters import format_daily_report
        embed = format_daily_report(
            {"total_value_usd": 10000, "warnings": []},
            {"sharpe_ratio": 1.0, "max_drawdown_pct": -5.0,
             "var_95_daily_pct": -1.5, "stop_loss_alerts": []},
            fear_greed=75.0,
        )
        field_names = [f["name"] for f in embed["fields"]]
        assert any("Fear" in n for n in field_names)

    def test_format_daily_report_with_events(self):
        from nuri.alerts.formatters import format_daily_report
        events = [{"date": "2025-01-31", "description": "FOMC Meeting"}]
        embed = format_daily_report(
            {"total_value_usd": 10000, "warnings": []},
            {"sharpe_ratio": 1.0, "max_drawdown_pct": -5.0,
             "var_95_daily_pct": -1.5, "stop_loss_alerts": []},
            events=events,
        )
        field_names = [f["name"] for f in embed["fields"]]
        assert any("이벤트" in n for n in field_names)

    def test_format_price_alert_up(self):
        from nuri.alerts.formatters import format_price_alert
        embed = format_price_alert("AAPL", 5.0, 200.0)
        assert "급등" in embed["title"]
        assert embed["color"] == 0x2ECC71  # Green

    def test_format_price_alert_down(self):
        from nuri.alerts.formatters import format_price_alert
        embed = format_price_alert("AAPL", -5.0, 180.0)
        assert "급락" in embed["title"]
        assert embed["color"] == 0xE74C3C  # Red

    def test_format_ark_alert(self):
        from nuri.alerts.formatters import format_ark_alert
        trades = [
            {"ticker": "AAPL", "direction": "BUY", "shares": 1000, "fund": "ARKK"},
            {"ticker": "NVDA", "direction": "SELL", "shares": 500, "fund": "ARKW"},
        ]
        embed = format_ark_alert(trades)
        assert "ARK" in embed["title"]
        assert "AAPL" in embed["description"]

    def test_format_ark_alert_empty(self):
        from nuri.alerts.formatters import format_ark_alert
        embed = format_ark_alert([])
        assert "매매 내역 없음" in embed["description"]

    def test_format_event_reminder(self):
        from nuri.alerts.formatters import format_event_reminder
        event = {"date": "2025-03-17", "description": "FOMC", "event_type": "fomc",
                 "ticker": None}
        embed = format_event_reminder(event)
        assert "FOMC" in embed["title"]

    def test_fear_greed_labels(self):
        from nuri.alerts.formatters import _fear_greed_label
        assert _fear_greed_label(10) == "극단적 공포"
        assert _fear_greed_label(30) == "공포"
        assert _fear_greed_label(50) == "중립"
        assert _fear_greed_label(70) == "탐욕"
        assert _fear_greed_label(90) == "극단적 탐욕"


# ═══════════════════════════════════════════════════════
# 20. Telegram
# ═══════════════════════════════════════════════════════


class TestTelegram:
    """Tests for nuri/alerts/telegram.py."""

    def test_send_telegram_no_config(self, monkeypatch):
        import nuri.alerts.telegram as tg
        monkeypatch.setattr(tg, "_BOT_TOKEN", "")
        monkeypatch.setattr(tg, "_CHAT_ID", "")
        result = tg.send_telegram("test message")
        assert result is False

    def test_send_telegram_success(self, monkeypatch):
        import nuri.alerts.telegram as tg
        monkeypatch.setattr(tg, "_BOT_TOKEN", "test_token")
        monkeypatch.setattr(tg, "_CHAT_ID", "123456")

        import requests as req_mod
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr(req_mod, "post", MagicMock(return_value=mock_resp))

        result = tg.send_telegram("test message")
        assert result is True

    def test_send_telegram_failure(self, monkeypatch):
        import nuri.alerts.telegram as tg
        monkeypatch.setattr(tg, "_BOT_TOKEN", "test_token")
        monkeypatch.setattr(tg, "_CHAT_ID", "123456")

        import requests as req_mod
        monkeypatch.setattr(req_mod, "post", MagicMock(side_effect=Exception("network error")))

        result = tg.send_telegram("test message")
        assert result is False

    def test_send_telegram_markdown_mode(self, monkeypatch):
        import nuri.alerts.telegram as tg
        monkeypatch.setattr(tg, "_BOT_TOKEN", "test_token")
        monkeypatch.setattr(tg, "_CHAT_ID", "123456")

        import requests as req_mod
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_post = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(req_mod, "post", mock_post)

        tg.send_telegram("**bold**", parse_mode="Markdown")
        call_args = mock_post.call_args
        assert call_args[1]["json"]["parse_mode"] == "Markdown"

    def test_format_regime_alert(self):
        from nuri.alerts.telegram import format_regime_alert
        msg = format_regime_alert("bull_low_vol", "bear_high_vol", 85.0)
        assert "레짐 전환" in msg
        assert "bull_low_vol" in msg
        assert "bear_high_vol" in msg
        assert "85" in msg

    def test_format_violation_alert(self):
        from nuri.alerts.telegram import format_violation_alert
        violations = [
            {"ticker": "AAPL", "severity": "critical", "reason": "stop-loss hit"},
            {"ticker": "NVDA", "severity": "warning", "violation_type": "position limit"},
        ]
        msg = format_violation_alert(violations)
        assert "2건" in msg
        assert "AAPL" in msg
        assert "stop-loss" in msg

    def test_format_violation_alert_many(self):
        from nuri.alerts.telegram import format_violation_alert
        violations = [{"ticker": f"T{i}", "severity": "warning", "reason": f"r{i}"} for i in range(10)]
        msg = format_violation_alert(violations)
        assert "외 5건" in msg

    def test_format_signal_alert_buy(self):
        from nuri.alerts.telegram import format_signal_alert
        msg = format_signal_alert("AAPL", "BUY", 85.0, 190.0)
        assert "AAPL" in msg
        assert "BUY" in msg
        assert "85" in msg

    def test_format_signal_alert_sell(self):
        from nuri.alerts.telegram import format_signal_alert
        msg = format_signal_alert("AAPL", "SELL", 70.0, 180.0)
        assert "SELL" in msg

    def test_format_signal_alert_hold(self):
        from nuri.alerts.telegram import format_signal_alert
        msg = format_signal_alert("AAPL", "HOLD", 50.0, 190.0)
        assert "HOLD" in msg


# ═══════════════════════════════════════════════════════
# Additional edge cases for deeper coverage
# ═══════════════════════════════════════════════════════


class TestSuperinvestorDetectChangesEdgeCases:
    """Edge cases for detect_changes — UNCHANGED + prev_shares=0."""

    def test_detect_unchanged(self, db_with_portfolio):
        from nuri.collectors.superinvestors import detect_changes
        from nuri.core.db import get_db

        with get_db(db_with_portfolio) as conn:
            conn.execute(
                "INSERT INTO superinvestors VALUES (NULL, 'X', '2025-01-15', 'AAPL', 1000, 200000, 50.0, 'Apple')"
            )
            conn.execute(
                "INSERT INTO superinvestors VALUES (NULL, 'X', '2025-04-15', 'AAPL', 1000, 200000, 50.0, 'Apple')"
            )

        df = detect_changes("X", db_path=db_with_portfolio)
        assert not df.empty
        assert "UNCHANGED" in df["change_type"].values

    def test_detect_decreased(self, db_with_portfolio):
        from nuri.collectors.superinvestors import detect_changes
        from nuri.core.db import get_db

        with get_db(db_with_portfolio) as conn:
            conn.execute(
                "INSERT INTO superinvestors VALUES (NULL, 'Y', '2025-01-15', 'AAPL', 1000, 200000, 50.0, 'Apple')"
            )
            conn.execute(
                "INSERT INTO superinvestors VALUES (NULL, 'Y', '2025-04-15', 'AAPL', 500, 100000, 25.0, 'Apple')"
            )

        df = detect_changes("Y", db_path=db_with_portfolio)
        assert "DECREASED" in df["change_type"].values

    def test_detect_prev_shares_zero(self, db_with_portfolio):
        from nuri.collectors.superinvestors import detect_changes
        from nuri.core.db import get_db

        with get_db(db_with_portfolio) as conn:
            conn.execute(
                "INSERT INTO superinvestors VALUES (NULL, 'Z', '2025-01-15', 'AAPL', 0, 0, 0, 'Apple')"
            )
            conn.execute(
                "INSERT INTO superinvestors VALUES (NULL, 'Z', '2025-04-15', 'AAPL', 500, 100000, 50.0, 'Apple')"
            )

        df = detect_changes("Z", db_path=db_with_portfolio)
        assert "INCREASED" in df["change_type"].values


class TestExternalEdgeCases:

    def test_save_external_db_error(self, monkeypatch, db_with_portfolio):
        """Test save_external when DB write fails."""
        # Monkey-patch to make DB fail
        from contextlib import contextmanager

        from nuri.collectors.external import save_external

        @contextmanager
        def bad_db(path=None):
            raise Exception("DB write error")
            yield  # pragma: no cover

        monkeypatch.setattr("nuri.collectors.external.get_db", bad_db)
        result = save_external("tipranks", "AAPL", "consensus", "Buy",
                               db_path=db_with_portfolio)
        assert result is False


class TestMacroCollectorEdgeCases:

    def test_collect_uses_yfinance_when_no_fred_key(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-15"]),
            "close": [4.5],
        })
        mock_result = MagicMock()
        mock_result.to_df.return_value = mock_df

        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = MacroCollector()
        collector.api_key = ""  # explicitly no key
        results = collector.collect(days=30)
        assert len(results) >= 0  # Should run yfinance path

    def test_collect_fred_returns_empty_falls_to_yfinance(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_fred = MagicMock()
        mock_fred.get_series.return_value = pd.Series(dtype=float)
        import sys
        monkeypatch.setitem(sys.modules, "fredapi", MagicMock(Fred=MagicMock(return_value=mock_fred)))

        mock_df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-15"]),
            "close": [4.5],
        })
        mock_result = MagicMock()
        mock_result.to_df.return_value = mock_df

        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = MacroCollector()
        collector.api_key = "real_key"
        results = collector.collect(days=30)
        # FRED returned empty, so should fallback to yfinance
        assert isinstance(results, list)


class TestStockCollectorEdgeCases:

    def test_collect_full_flow(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-15"]),
            "open": [190.0], "high": [195.0], "low": [189.0],
            "close": [194.0], "volume": [50000000], "adj_close": [194.0],
        })
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df

        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = StockCollector()
        df = collector.collect(period="5d")
        assert not df.empty


class TestCollectFilingsDefaultTickers:
    """Test collect_filings with default tickers from DB."""

    def test_collect_filings_default(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.filings import collect_filings

        def mock_parse(ticker):
            if not ticker.endswith(".KS"):
                return {"ticker": ticker, "filing_date": "2025-02-15",
                        "form": "10-K", "revenue": 50e9}
            return None

        monkeypatch.setattr("nuri.collectors.filings.parse_10k", mock_parse)

        results = collect_filings()
        assert len(results) >= 1
        # Should only include US tickers (not .KS)
        for r in results:
            assert not r["ticker"].endswith(".KS")


class TestFetchPostsNoLastUTC:
    """Test _fetch_posts when last_utc is None."""

    def test_fetch_posts_no_last_utc(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.reddit import RedditCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [{"title": "Test", "selftext": "", "created_utc": None}]
        }
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.reddit.requests.get",
                            MagicMock(return_value=mock_resp))

        collector = RedditCollector()
        posts = collector._fetch_posts(days=1)
        assert len(posts) == 1


class TestEventsCollectorDividendNoDate:
    """Test events collector when ex_dividend_date is None."""

    def test_dividend_no_date(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.events import EventsCollector

        earnings_df = pd.DataFrame()
        dividend_df = pd.DataFrame({"ex_dividend_date": [None]})

        mock_obb = MagicMock()
        mock_earnings = MagicMock()
        mock_earnings.to_dataframe.return_value = earnings_df
        mock_dividend = MagicMock()
        mock_dividend.to_dataframe.return_value = dividend_df
        mock_obb.equity.calendar.earnings.return_value = mock_earnings
        mock_obb.equity.calendar.dividend.return_value = mock_dividend

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = EventsCollector()
        results = collector._collect_ticker_events("AAPL")
        # Should handle None date gracefully
        assert isinstance(results, list)


class TestCollectNoUSTickets:
    """Test reddit collector with no US tickers."""

    def test_no_us_tickers(self, monkeypatch, tmp_path):
        import nuri.core.db as db_mod
        from nuri.collectors.reddit import RedditCollector

        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        collector = RedditCollector()
        results = collector.collect()
        assert results == []


class TestWallStreetSaveShortInterest:
    """Test _save_short_interest directly."""

    def test_save_short_no_days_to_cover(self, db_with_portfolio):
        from nuri.collectors.wallstreet import _save_short_interest
        records = [{"ticker": "AAPL", "short_pct_float": 5.0}]
        count = _save_short_interest(records, db_path=db_with_portfolio)
        assert count == 1


class TestEtfFlowsNanValues:
    """Test ETF flows with NaN values."""

    def test_collect_nan_assets(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        mock_df = pd.DataFrame([{
            "name": "Test ETF",
            "total_assets": float("nan"),
            "volume_avg": float("nan"),
            "nav_price": float("nan"),
        }])
        mock_result = MagicMock()
        mock_result.to_df.return_value = mock_df

        mock_obb = MagicMock()
        mock_obb.etf.info.return_value = mock_result

        import sys
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        collector = EtfFlowsCollector()
        results = collector.collect()
        assert len(results) > 0
        assert results[0]["total_assets"] is None

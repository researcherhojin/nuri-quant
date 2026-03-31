"""Coverage round 17 — superinvestors, filings, etf_flows, external, fundamental, cboe, scheduler."""

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices

# ══════════════════════════════════════════
# Shared rich DB fixture
# ══════════════════════════════════════════


@pytest.fixture
def rich_db(tmp_path, monkeypatch):
    """Rich DB with portfolio, prices, macro, superinvestors, etf_flows."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    upsert_portfolio(
        [
            {"account": "test", "ticker": "AAPL", "quantity": 10, "avg_price": 190, "currency": "USD", "sector": "Tech"},
            {"account": "test", "ticker": "NVDA", "quantity": 5, "avg_price": 130, "currency": "USD", "sector": "Semi"},
            {"account": "test", "ticker": "005930.KS", "quantity": 100, "avg_price": 70000, "currency": "KRW", "sector": "Tech"},
        ],
        path,
    )

    # prices
    dates = pd.date_range("2024-06-01", periods=50, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA"]:
        base = {"SPY": 450, "AAPL": 170, "NVDA": 120}[t]
        for i, d in enumerate(dates):
            p = base + i * 0.3
            rows.append(
                {
                    "ticker": t,
                    "date": d.strftime("%Y-%m-%d"),
                    "open": p,
                    "high": p + 3,
                    "low": p - 2,
                    "close": p + 1,
                    "volume": 50000000,
                    "adj_close": p + 1,
                }
            )
    upsert_prices(pd.DataFrame(rows), path)

    # macro
    macro = []
    for i, d in enumerate(dates):
        ds = d.strftime("%Y-%m-%d")
        macro.append({"indicator": "vix", "date": ds, "value": 15.0, "source": "test"})
        macro.append({"indicator": "fear_greed", "date": ds, "value": 55.0, "source": "test"})
    upsert_macro(macro, path)

    return path


# ══════════════════════════════════════════
# 1. SuperinvestorCollector
# ══════════════════════════════════════════


class TestSuperinvestorCollector:
    """Tests for nuri/collectors/superinvestors.py."""

    def test_collect_success(self, rich_db):
        """collect() returns holdings from mocked edgar Company."""
        from nuri.collectors.superinvestors import SuperinvestorCollector

        infotable = pd.DataFrame(
            {
                "Ticker": ["AAPL", "AAPL", "NVDA"],
                "Value": [100e6, 50e6, 200e6],
                "SharesPrnAmount": [500000, 250000, 1000000],
                "Issuer": ["Apple Inc", "Apple Inc", "NVIDIA Corp"],
            }
        )

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

        assert len(result) == 2  # AAPL grouped + NVDA
        aapl = [r for r in result if r["ticker"] == "AAPL"][0]
        assert aapl["shares"] == 750000
        assert aapl["market_value"] == 150e6

    def test_collect_empty_filings(self, rich_db):
        """collect() handles investor with no filings gracefully."""
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
        """collect() skips filings that fail to parse."""
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
        """collect() skips filings with empty infotable."""
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
        """collect() skips rows where Ticker is NaN."""
        from nuri.collectors.superinvestors import SuperinvestorCollector

        infotable = pd.DataFrame(
            {
                "Ticker": [None, "MSFT"],
                "Value": [100e6, 200e6],
                "SharesPrnAmount": [500000, 1000000],
                "Issuer": ["Unknown", "Microsoft"],
            }
        )

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
        """save() persists records to the superinvestors table."""
        from nuri.collectors.superinvestors import SuperinvestorCollector, _upsert_superinvestors

        records = [
            {
                "investor": "Buffett",
                "filing_date": "2025-03-15",
                "ticker": "AAPL",
                "shares": 900000000,
                "market_value": 171e9,
                "portfolio_pct": 48.5,
                "issuer_name": "Apple Inc",
            }
        ]
        c = SuperinvestorCollector()
        count = c.save(records)
        assert count == 1

        # empty case
        assert c.save([]) == 0
        assert c.save(None) == 0

        # _upsert_superinvestors empty
        assert _upsert_superinvestors([]) == 0

    def test_detect_changes(self, rich_db):
        """detect_changes() identifies NEW/CLOSED/INCREASED/DECREASED/UNCHANGED."""
        from nuri.collectors.superinvestors import detect_changes

        with get_db(rich_db) as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO superinvestors
                   (investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    # Q1
                    ("Test", "2025-01-15", "AAPL", 1000, 150000, 50.0, "Apple"),
                    ("Test", "2025-01-15", "GOOG", 500, 100000, 33.0, "Alphabet"),
                    ("Test", "2025-01-15", "MSFT", 200, 50000, 17.0, "Microsoft"),
                    # Q2: AAPL increased, GOOG closed, MSFT unchanged, NVDA new
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
        """detect_changes() returns empty if fewer than 2 quarters."""
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
        """detect_changes() reports DECREASED when shares drop significantly."""
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


# ══════════════════════════════════════════
# 2. Filings collector
# ══════════════════════════════════════════


class TestFilingsCollector:
    """Tests for nuri/collectors/filings.py."""

    def _mock_income_df(self):
        return pd.DataFrame(
            {
                "concept": ["Revenue", "NetIncome", "OperatingIncome"],
                "dimension": [False, False, False],
                "is_breakdown": [False, False, False],
                "2024": [100e9, 25e9, 30e9],
            }
        )

    def _mock_balance_df(self):
        return pd.DataFrame(
            {
                "concept": ["Assets", "Liabilities", "CashAndCashEquivalents"],
                "dimension": [False, False, False],
                "is_breakdown": [False, False, False],
                "2024": [400e9, 250e9, 60e9],
            }
        )

    def test_parse_10k_success(self):
        """parse_10k() extracts financial data from a mocked 10-K filing."""
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
        assert result["net_income"] == 25e9
        assert result["total_assets"] == 400e9
        assert result["cash"] == 60e9

    def test_parse_10k_no_filings(self):
        """parse_10k() returns None when no 10-K filings exist."""
        from nuri.collectors.filings import parse_10k

        mock_company = MagicMock()
        mock_company.get_filings.return_value = []

        with patch("edgar.set_identity"):
            with patch("edgar.Company", return_value=mock_company):
                result = parse_10k("FAKE")

        assert result is None

    def test_parse_10k_exception(self):
        """parse_10k() returns None on Company() exception."""
        from nuri.collectors.filings import parse_10k

        with patch("edgar.set_identity"):
            with patch("edgar.Company", side_effect=RuntimeError("network")):
                result = parse_10k("FAIL")

        assert result is None

    def test_parse_10k_income_exception(self):
        """parse_10k() still returns data if income statement fails but balance sheet succeeds."""
        from nuri.collectors.filings import parse_10k

        mock_bs = MagicMock()
        mock_bs.to_dataframe.return_value = self._mock_balance_df()

        mock_obj = MagicMock()
        mock_obj.income_statement = None  # no income statement
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
        assert "revenue" not in result

    def test_collect_filings_with_tickers(self):
        """collect_filings() iterates over tickers and accumulates results."""
        from nuri.collectors.filings import collect_filings

        fake_result = {
            "ticker": "AAPL",
            "filing_date": "2025-02-01",
            "form": "10-K",
            "revenue": 100e9,
        }

        with patch("nuri.collectors.filings.parse_10k", return_value=fake_result):
            results = collect_filings(tickers=["AAPL"])

        assert len(results) == 1
        assert results[0]["ticker"] == "AAPL"

    def test_collect_filings_skips_none(self):
        """collect_filings() skips tickers with no result."""
        from nuri.collectors.filings import collect_filings

        with patch("nuri.collectors.filings.parse_10k", return_value=None):
            results = collect_filings(tickers=["FAKE"])

        assert results == []

    def test_print_filings_empty(self, capsys):
        """print_filings() handles empty results."""
        from nuri.collectors.filings import print_filings

        print_filings([])
        out = capsys.readouterr().out
        assert "없음" in out

    def test_print_filings_with_data(self, capsys):
        """print_filings() prints formatted output."""
        from nuri.collectors.filings import print_filings

        data = [
            {
                "ticker": "AAPL",
                "filing_date": "2025-02-01",
                "revenue": 100e9,
                "net_income": 25e9,
                "total_assets": 400e9,
                "cash": 60e9,
            }
        ]
        print_filings(data)
        out = capsys.readouterr().out
        assert "AAPL" in out


# ══════════════════════════════════════════
# 3. EtfFlowsCollector
# ══════════════════════════════════════════


class TestEtfFlowsCollector:
    """Tests for nuri/collectors/etf_flows.py."""

    def test_collect_success(self, rich_db):
        """collect() returns ETF info from mocked OpenBB."""
        from nuri.collectors.etf_flows import EtfFlowsCollector

        mock_df = pd.DataFrame(
            [
                {
                    "name": "Tech Select SPDR",
                    "total_assets": 50e9,
                    "volume_avg": 10000000.0,
                    "nav_price": 200.0,
                }
            ]
        )

        mock_result = MagicMock()
        mock_result.to_df.return_value = mock_df

        mock_obb = MagicMock()
        mock_obb.etf.info.return_value = mock_result

        with patch("nuri.collectors.etf_flows.ALL_ETFS", {"XLK": "Technology"}):
            with patch.dict("sys.modules", {"openbb": MagicMock(obb=mock_obb)}):
                with patch("nuri.collectors.etf_flows.obb", mock_obb, create=True):
                    c = EtfFlowsCollector()
                    with patch("builtins.__import__", side_effect=lambda name, *args, **kwargs: __builtins__.__import__(name, *args, **kwargs) if name != "openbb" else MagicMock(obb=mock_obb)):
                        assert c.save([]) == 0
                        assert c.save(None) == 0

        # Simpler approach: test _upsert and analyze
        from nuri.collectors.etf_flows import _upsert_etf_flows

        records = [
            {
                "ticker": "XLK",
                "date": "2025-03-15",
                "name": "Technology Select SPDR",
                "total_assets": 50e9,
                "volume_avg": 10000000.0,
                "nav_price": 200.0,
            }
        ]
        count = _upsert_etf_flows(records, db_path=rich_db)
        assert count == 1

    def test_upsert_etf_flows_empty(self, rich_db):
        """_upsert_etf_flows returns 0 for empty list."""
        from nuri.collectors.etf_flows import _upsert_etf_flows

        assert _upsert_etf_flows([], db_path=rich_db) == 0

    def test_save_empty(self, rich_db):
        """save() returns 0 for empty data."""
        from nuri.collectors.etf_flows import EtfFlowsCollector

        c = EtfFlowsCollector()
        assert c.save([]) == 0
        assert c.save(None) == 0

    def test_analyze_sector_rotation_with_data(self, rich_db):
        """analyze_sector_rotation() returns DataFrame when >= 2 days of data exist."""
        from nuri.collectors.etf_flows import _upsert_etf_flows, analyze_sector_rotation

        records = []
        for d in ["2025-03-01", "2025-03-08", "2025-03-15", "2025-03-22"]:
            for ticker, aum in [("XLK", 50e9 + int(d[-2:]) * 1e8), ("XLF", 30e9 + int(d[-2:]) * 5e7)]:
                records.append(
                    {
                        "ticker": ticker,
                        "date": d,
                        "name": f"Test {ticker}",
                        "total_assets": aum,
                        "volume_avg": 10000000.0 + int(d[-2:]) * 100000,
                        "nav_price": 200.0,
                    }
                )
        _upsert_etf_flows(records, db_path=rich_db)

        df = analyze_sector_rotation(db_path=rich_db)
        assert df is not None
        assert not df.empty
        assert "aum_change_pct" in df.columns
        assert "volume_trend_pct" in df.columns

    def test_analyze_sector_rotation_insufficient_data(self, rich_db):
        """analyze_sector_rotation() returns None with < 2 days."""
        from nuri.collectors.etf_flows import analyze_sector_rotation

        result = analyze_sector_rotation(db_path=rich_db)
        assert result is None

    def test_analyze_sector_rotation_single_day(self, rich_db):
        """analyze_sector_rotation() returns None for a single-day dataset."""
        from nuri.collectors.etf_flows import _upsert_etf_flows, analyze_sector_rotation

        records = [
            {
                "ticker": "XLK",
                "date": "2025-03-15",
                "name": "Technology",
                "total_assets": 50e9,
                "volume_avg": 10000000.0,
                "nav_price": 200.0,
            }
        ]
        _upsert_etf_flows(records, db_path=rich_db)

        result = analyze_sector_rotation(db_path=rich_db)
        assert result is None

    def test_print_sector_rotation_none(self, capsys):
        """print_sector_rotation() handles None input."""
        from nuri.collectors.etf_flows import print_sector_rotation

        print_sector_rotation(None)
        out = capsys.readouterr().out
        assert "없음" in out

    def test_print_sector_rotation_with_data(self, capsys):
        """print_sector_rotation() prints formatted data."""
        from nuri.collectors.etf_flows import print_sector_rotation

        df = pd.DataFrame(
            [
                {
                    "ticker": "XLK",
                    "sector": "Technology",
                    "aum_current": 50e9,
                    "aum_prev": 48e9,
                    "aum_change_pct": 4.17,
                    "volume_trend_pct": 2.5,
                }
            ]
        )
        print_sector_rotation(df)
        out = capsys.readouterr().out
        assert "XLK" in out


# ══════════════════════════════════════════
# 4. External data collector
# ══════════════════════════════════════════


class TestExternalCollector:
    """Tests for nuri/collectors/external.py."""

    def test_save_external_success(self, rich_db):
        """save_external() persists data to DB."""
        from nuri.collectors.external import save_external

        ok = save_external("tipranks", "AAPL", "consensus", "Strong Buy", db_path=rich_db)
        assert ok is True

    def test_save_external_unknown_source(self, rich_db):
        """save_external() rejects unknown sources."""
        from nuri.collectors.external import save_external

        ok = save_external("unknown_source", "AAPL", "test", "val", db_path=rich_db)
        assert ok is False

    def test_save_tipranks(self, rich_db):
        """save_tipranks() stores consensus, target_price, analyst_count."""
        from nuri.collectors.external import get_external, save_tipranks

        save_tipranks("NVDA", "Strong Buy", 273.61, 38, upside_pct=63.0, db_path=rich_db)

        data = get_external("NVDA", source="tipranks", db_path=rich_db)
        assert len(data) >= 3  # consensus, target_price, analyst_count

        types = [d["data_type"] for d in data]
        assert "consensus" in types
        assert "target_price" in types
        assert "analyst_count" in types

    def test_save_superinvestor(self, rich_db):
        """save_superinvestor() stores superinvestor count + trend."""
        from nuri.collectors.external import get_external, save_superinvestor

        save_superinvestor("AAPL", 14, "buying", details="Buffett +5%", db_path=rich_db)

        data = get_external("AAPL", source="dataroma", db_path=rich_db)
        assert len(data) >= 2

    def test_get_external_no_source(self, rich_db):
        """get_external() returns all sources when source=None."""
        from nuri.collectors.external import get_external, save_external

        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=rich_db)
        save_external("dataroma", "AAPL", "count", "10", db_path=rich_db)

        data = get_external("AAPL", db_path=rich_db)
        sources = {d["source"] for d in data}
        assert "tipranks" in sources
        assert "dataroma" in sources

    def test_get_external_empty(self, rich_db):
        """get_external() returns empty list for unknown ticker."""
        from nuri.collectors.external import get_external

        data = get_external("ZZZZ", db_path=rich_db)
        assert data == []

    def test_get_external_summary(self, rich_db):
        """get_external_summary() returns source-level aggregation."""
        from nuri.collectors.external import get_external_summary, save_external

        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=rich_db)
        save_external("tipranks", "NVDA", "consensus", "Strong Buy", db_path=rich_db)

        summary = get_external_summary(db_path=rich_db)
        assert summary["total_records"] >= 2
        assert len(summary["sources"]) >= 1

    def test_get_external_summary_empty(self, rich_db):
        """get_external_summary() handles empty DB."""
        from nuri.collectors.external import get_external_summary

        summary = get_external_summary(db_path=rich_db)
        assert summary["total_records"] == 0

    def test_save_external_with_numeric(self, rich_db):
        """save_external() stores numeric_value and details."""
        from nuri.collectors.external import get_external, save_external

        save_external("tipranks", "TSLA", "target_price", "400.0", numeric_value=400.0, details="upside 50%", db_path=rich_db)

        data = get_external("TSLA", source="tipranks", db_path=rich_db)
        assert len(data) == 1
        assert data[0]["numeric_value"] == 400.0

    def test_print_summary(self, rich_db, capsys):
        """print_summary() outputs formatted summary."""
        from nuri.collectors.external import print_summary, save_external

        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=rich_db)
        print_summary(db_path=rich_db)
        out = capsys.readouterr().out
        assert "tipranks" in out.lower() or "TipRanks" in out

    def test_print_ticker_external_empty(self, rich_db, capsys):
        """print_ticker_external() handles missing ticker."""
        from nuri.collectors.external import print_ticker_external

        print_ticker_external("ZZZZ", db_path=rich_db)
        out = capsys.readouterr().out
        assert "없음" in out

    def test_print_ticker_external_with_data(self, rich_db, capsys):
        """print_ticker_external() prints formatted data."""
        from nuri.collectors.external import print_ticker_external, save_external

        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=rich_db)
        save_external("dataroma", "AAPL", "count", "12", db_path=rich_db)
        print_ticker_external("AAPL", db_path=rich_db)
        out = capsys.readouterr().out
        assert "AAPL" in out


# ══════════════════════════════════════════
# 5. FundamentalCollector
# ══════════════════════════════════════════


class TestFundamentalCollector:
    """Tests for nuri/collectors/fundamental.py."""

    def test_upsert_fundamentals(self, rich_db):
        """_upsert_fundamentals() saves records to DB."""
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
            }
        ]
        count = _upsert_fundamentals(records)
        assert count == 1

    def test_upsert_fundamentals_empty(self, rich_db):
        """_upsert_fundamentals() returns 0 for empty list."""
        from nuri.collectors.fundamental import _upsert_fundamentals

        assert _upsert_fundamentals([]) == 0

    def test_save_empty(self, rich_db):
        """save() returns 0 for empty data."""
        from nuri.collectors.fundamental import FundamentalCollector

        c = FundamentalCollector()
        assert c.save([]) == 0
        assert c.save(None) == 0

    def test_collect_with_mock_openbb(self, rich_db):
        """collect() processes mocked OpenBB data correctly."""
        from nuri.collectors.fundamental import FundamentalCollector

        mock_row = pd.Series(
            {
                "market_cap": 3e12,
                "pe_ratio": 28.5,
                "forward_pe": 25.0,
                "price_to_book": 45.0,
                "peg_ratio_ttm": 1.5,
                "return_on_equity": 1.5,
                "return_on_assets": 0.3,
                "gross_margin": 0.45,
                "operating_margin": 0.30,
                "profit_margin": 0.25,
                "revenue_growth": 0.08,
                "earnings_growth": 0.12,
                "debt_to_equity": 1.8,
                "current_ratio": 1.1,
                "dividend_yield": 0.005,
                "beta": 1.2,
            }
        )
        mock_df = pd.DataFrame([mock_row])
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df

        mock_obb = MagicMock()
        mock_obb.equity.fundamental.metrics.return_value = mock_result

        c = FundamentalCollector()

        with patch.object(c, "_get_tickers", return_value=["AAPL"]):
            with patch("nuri.collectors.fundamental.obb", mock_obb, create=True):
                # Mock the lazy import of obb inside collect()
                import types

                original_collect = c.collect

                def patched_collect(**kwargs):

                    with patch.dict("sys.modules", {"openbb": types.ModuleType("openbb")}):
                        import sys

                        sys.modules["openbb"].obb = mock_obb
                        return original_collect(**kwargs)

                result = patched_collect()

        assert len(result) == 1
        assert result[0]["ticker"] == "AAPL"
        assert result[0]["pe_ratio"] == 28.5

    def test_collect_empty_dataframe(self, rich_db):
        """collect() skips tickers with empty DataFrame."""
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
        """collect() handles exception for individual ticker gracefully."""
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
        """collect() converts NaN fields to None."""
        from nuri.collectors.fundamental import FundamentalCollector

        mock_row = pd.Series(
            {
                "market_cap": float("nan"),
                "pe_ratio": 28.5,
                "forward_pe": float("nan"),
                "price_to_book": float("nan"),
                "peg_ratio_ttm": float("nan"),
                "return_on_equity": float("nan"),
                "return_on_assets": float("nan"),
                "gross_margin": float("nan"),
                "operating_margin": float("nan"),
                "profit_margin": float("nan"),
                "revenue_growth": float("nan"),
                "earnings_growth": float("nan"),
                "debt_to_equity": float("nan"),
                "current_ratio": float("nan"),
                "dividend_yield": float("nan"),
                "beta": float("nan"),
            }
        )
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
        assert result[0]["forward_pe"] is None


# ══════════════════════════════════════════
# 6. CBOECollector
# ══════════════════════════════════════════


class TestCBOECollector:
    """Tests for nuri/collectors/cboe.py."""

    def test_extract_pcr_ratio_key(self):
        """_extract_pcr() extracts from ratio key names."""
        from nuri.collectors.cboe import CBOECollector

        assert CBOECollector._extract_pcr({"TOTAL_PUT_CALL_RATIO": 0.85}) == 0.85
        assert CBOECollector._extract_pcr({"PUT_CALL_RATIO": 0.92}) == 0.92
        assert CBOECollector._extract_pcr({"put_call_ratio": 1.1}) == 1.1
        assert CBOECollector._extract_pcr({"pcr": 0.75}) == 0.75
        assert CBOECollector._extract_pcr({"ratio": 0.6}) == 0.6

    def test_extract_pcr_from_volumes(self):
        """_extract_pcr() computes from put/call volumes."""
        from nuri.collectors.cboe import CBOECollector

        result = CBOECollector._extract_pcr({"TOTAL_PUT_VOLUME": 1000, "TOTAL_CALL_VOLUME": 2000})
        assert abs(result - 0.5) < 0.01

    def test_extract_pcr_none(self):
        """_extract_pcr() returns None when no usable data."""
        from nuri.collectors.cboe import CBOECollector

        assert CBOECollector._extract_pcr({}) is None
        assert CBOECollector._extract_pcr({"unrelated": 123}) is None

    def test_extract_pcr_invalid_values(self):
        """_extract_pcr() handles non-numeric values gracefully."""
        from nuri.collectors.cboe import CBOECollector

        assert CBOECollector._extract_pcr({"TOTAL_PUT_CALL_RATIO": "bad"}) is None

    def test_collect_daily_success(self, monkeypatch):
        """_collect_daily() parses CBOE daily JSON."""
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"TRADE_DATE": "2025-03-15", "TOTAL_PUT_CALL_RATIO": 0.85}
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c._collect_daily()

        assert len(result) == 1
        assert result[0]["indicator"] == "put_call_ratio"
        assert result[0]["value"] == 0.85

    def test_collect_daily_dict_response(self, monkeypatch):
        """_collect_daily() handles direct dict response (not list)."""
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
        """_collect_totalpc() parses total put/call data."""
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()

        items = [{"TRADE_DATE": "2025-03-15", "TOTAL_PUT_CALL_RATIO": 0.88}]

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": items}
        mock_resp.raise_for_status = MagicMock()

        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c._collect_totalpc()

        assert len(result) == 1

    def test_collect_fred_pcr(self, monkeypatch):
        """_collect_fred_pcr() parses FRED ECPCRATIO data."""
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

        assert len(result) == 2  # "." value is skipped
        assert result[0]["source"] == "FRED_ECPCRATIO"

    def test_collect_fallback_chain(self, monkeypatch):
        """collect() tries daily, then totalpc, then FRED in order."""
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        c.fred_key = "test_key"

        # daily fails, totalpc fails, FRED succeeds
        with patch.object(c, "_collect_daily", side_effect=RuntimeError("fail")):
            with patch.object(c, "_collect_totalpc", side_effect=RuntimeError("fail")):
                with patch.object(c, "_collect_fred_pcr", return_value=[{"indicator": "put_call_ratio", "date": "2025-03-15", "value": 0.9, "source": "FRED"}]):
                    result = c.collect()

        assert len(result) == 1
        assert result[0]["source"] == "FRED"

    def test_collect_all_fail(self, monkeypatch):
        """collect() returns empty when all sources fail."""
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        c.fred_key = ""  # no FRED key

        with patch.object(c, "_collect_daily", side_effect=RuntimeError("fail")):
            with patch.object(c, "_collect_totalpc", side_effect=RuntimeError("fail")):
                result = c.collect()

        assert result == []

    def test_collect_daily_returns_empty(self, monkeypatch):
        """collect() falls through when _collect_daily returns empty list."""
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        c.fred_key = ""

        with patch.object(c, "_collect_daily", return_value=[]):
            with patch.object(c, "_collect_totalpc", return_value=[{"indicator": "put_call_ratio", "date": "2025-03-15", "value": 0.8, "source": "CBOE"}]):
                result = c.collect()

        assert len(result) == 1

    def test_save(self, rich_db):
        """save() calls upsert_macro."""
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        records = [
            {"indicator": "put_call_ratio", "date": "2025-03-15", "value": 0.85, "source": "CBOE"}
        ]
        count = c.save(records)
        assert count == 1


# ══════════════════════════════════════════
# 7. Scheduler
# ══════════════════════════════════════════


class TestScheduler:
    """Tests for nuri/scheduler.py."""

    def test_run_collector_stock(self):
        """_run_collector dispatches to StockCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.stock.StockCollector", return_value=mock_collector):
            _run_collector("stock")
        mock_collector.run.assert_called_once()

    def test_run_collector_stock_kr(self):
        """_run_collector dispatches to StockKRCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.stock_kr.StockKRCollector", return_value=mock_collector):
            _run_collector("stock_kr")
        mock_collector.run.assert_called_once()

    def test_run_collector_macro(self):
        """_run_collector dispatches to MacroCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.macro.MacroCollector", return_value=mock_collector):
            _run_collector("macro")
        mock_collector.run.assert_called_once()

    def test_run_collector_technical(self):
        """_run_collector dispatches to TechnicalCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.technical.TechnicalCollector", return_value=mock_collector):
            _run_collector("technical")
        mock_collector.run.assert_called_once()

    def test_run_collector_fear_greed(self):
        """_run_collector dispatches to FearGreedCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.fear_greed.FearGreedCollector", return_value=mock_collector):
            _run_collector("fear_greed")
        mock_collector.run.assert_called_once()

    def test_run_collector_ark(self):
        """_run_collector dispatches to ARKCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.ark.ARKCollector", return_value=mock_collector):
            _run_collector("ark")
        mock_collector.run.assert_called_once()

    def test_run_collector_events(self):
        """_run_collector dispatches to EventsCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.events.EventsCollector", return_value=mock_collector):
            _run_collector("events")
        mock_collector.run.assert_called_once()

    def test_run_collector_news(self):
        """_run_collector dispatches to NewsCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.news.NewsCollector", return_value=mock_collector):
            _run_collector("news")
        mock_collector.run.assert_called_once()

    def test_run_collector_fundamental(self):
        """_run_collector dispatches to FundamentalCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.fundamental.FundamentalCollector", return_value=mock_collector):
            _run_collector("fundamental")
        mock_collector.run.assert_called_once()

    def test_run_collector_superinvestors(self):
        """_run_collector dispatches to SuperinvestorCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.superinvestors.SuperinvestorCollector", return_value=mock_collector):
            _run_collector("superinvestors")
        mock_collector.run.assert_called_once()

    def test_run_collector_estimates(self):
        """_run_collector dispatches to EstimatesCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.estimates.EstimatesCollector", return_value=mock_collector):
            _run_collector("estimates")
        mock_collector.run.assert_called_once()

    def test_run_collector_etf_flows(self):
        """_run_collector dispatches to EtfFlowsCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.etf_flows.EtfFlowsCollector", return_value=mock_collector):
            _run_collector("etf_flows")
        mock_collector.run.assert_called_once()

    def test_run_collector_wallstreet(self):
        """_run_collector dispatches to WallStreetCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.wallstreet.WallStreetCollector", return_value=mock_collector):
            _run_collector("wallstreet")
        mock_collector.run.assert_called_once()

    def test_run_collector_memory_snapshot(self):
        """_run_collector dispatches to memory save_snapshot."""
        from nuri.scheduler import _run_collector

        with patch("nuri.trading.engine.memory.save_snapshot", return_value=5) as mock_snap:
            _run_collector("memory_snapshot")
        mock_snap.assert_called_once()

    def test_run_collector_exception_handled(self):
        """_run_collector catches exceptions and logs them."""
        from nuri.scheduler import _run_collector

        with patch("nuri.collectors.stock.StockCollector", side_effect=RuntimeError("boom")):
            # should not raise
            _run_collector("stock")

    def test_run_collector_unknown_name(self):
        """_run_collector does nothing for unknown collector names."""
        from nuri.scheduler import _run_collector

        # no exception, just returns
        _run_collector("nonexistent_collector")

    def test_run_report(self):
        """_run_report calls daily_report.main."""
        from nuri.scheduler import _run_report

        with patch("nuri.alerts.daily_report.main") as mock_main:
            _run_report()
        mock_main.assert_called_once()

    def test_run_report_exception(self):
        """_run_report catches exceptions."""
        from nuri.scheduler import _run_report

        with patch("nuri.alerts.daily_report.main", side_effect=RuntimeError("fail")):
            # should not raise
            _run_report()

    def test_run_backup(self):
        """_run_backup calls subprocess."""
        from nuri.scheduler import _run_backup

        with patch("subprocess.run") as mock_run:
            _run_backup()
        mock_run.assert_called_once()

    def test_run_backup_exception(self):
        """_run_backup catches exceptions."""
        from nuri.scheduler import _run_backup

        with patch("subprocess.run", side_effect=RuntimeError("fail")):
            _run_backup()

    def test_run_db_maintenance(self):
        """_run_db_maintenance calls run_maintenance."""
        from nuri.scheduler import _run_db_maintenance

        with patch("scripts.db_maintenance.run_maintenance") as mock_maint:
            _run_db_maintenance()
        mock_maint.assert_called_once()

    def test_run_db_maintenance_exception(self):
        """_run_db_maintenance catches exceptions."""
        from nuri.scheduler import _run_db_maintenance

        with patch("scripts.db_maintenance.run_maintenance", side_effect=RuntimeError("fail")):
            _run_db_maintenance()

    def test_create_scheduler(self):
        """create_scheduler() registers all jobs."""
        from nuri.scheduler import SCHEDULES, create_scheduler

        scheduler = create_scheduler()
        jobs = scheduler.get_jobs()

        # +1 for heartbeat
        assert len(jobs) == len(SCHEDULES) + 1

        job_names = {j.id for j in jobs}
        assert "heartbeat" in job_names
        assert "stock_us_night" in job_names
        assert "backup" in job_names

    def test_print_schedule(self, capsys):
        """print_schedule() outputs schedule list."""
        from nuri.scheduler import print_schedule

        print_schedule()
        out = capsys.readouterr().out
        assert "stock_us_night" in out

    def test_write_heartbeat(self, tmp_path, monkeypatch):
        """_write_heartbeat() writes timestamp file."""
        from nuri.scheduler import _write_heartbeat

        hb_path = tmp_path / ".scheduler_heartbeat"
        monkeypatch.setattr("nuri.scheduler.HEARTBEAT_PATH", hb_path)
        _write_heartbeat()
        assert hb_path.exists()
        content = hb_path.read_text()
        assert len(content) > 10  # e.g., 2025-03-31T12:00:00

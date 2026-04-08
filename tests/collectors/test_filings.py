"""Per-collector tests for filings.

Split from tests/test_collectors_all.py for module-level isolation.
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd


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



class TestFilingsCollectorParse10K:
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



class TestFilingsCollectorMoreParse10K:
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



class TestCollectFilingsDefaultTickers:
    def test_collect_filings_default(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.filings import collect_filings

        def mock_parse(ticker):
            return {"ticker": ticker, "filing_date": "2025-02-15", "form": "10-K", "revenue": 50e9} if not ticker.endswith(".KS") else None

        monkeypatch.setattr("nuri.collectors.filings.parse_10k", mock_parse)
        results = collect_filings()
        assert all(not r["ticker"].endswith(".KS") for r in results)

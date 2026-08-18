"""Per-collector tests for superinvestors.

Split from tests/test_collectors_all.py for module-level isolation.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from nuri.core.db import (
    get_db,
)


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
        records = [
            {
                "investor": "Warren Buffett",
                "ticker": "AAPL",
                "shares": 900000000,
                "market_value": 171000000000,
                "portfolio_pct": 48.5,
                "filing_date": "2026-02-14",
                "issuer_name": "Apple Inc.",
            }
        ]
        count = c.save(records)
        assert count == 1


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


class TestSuperinvestorsCollect:
    def test_collect_with_infotable(self):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_info = MagicMock()
        mock_info.infotable = pd.DataFrame(
            [
                {
                    "nameOfIssuer": "Apple Inc",
                    "cusip": "037833100",
                    "value": 171000,
                    "sshPrnamt": 900000,
                    "sshPrnamtType": "SH",
                },
            ]
        )
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
        mock_info.infotable = pd.DataFrame(
            [
                {
                    "nameOfIssuer": "Apple Inc",
                    "cusip": "037833100",
                    "value": 171000,
                    "sshPrnamt": 900000,
                    "sshPrnamtType": "SH",
                },
            ]
        )
        mock_filing = MagicMock()
        mock_filing.filing_date = "2026-02-14"
        mock_filing.obj.return_value = mock_info
        mock_co = MagicMock()
        mock_co.get_filings.return_value = [mock_filing]
        with patch("edgar.Company", return_value=mock_co), patch("edgar.set_identity"):
            c = SuperinvestorCollector()
            c.run(num_quarters=1)


class TestSuperinvestorsMultiple:
    def test_collect_multi_investor(self):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_info = MagicMock()
        mock_info.infotable = pd.DataFrame(
            [
                {"nameOfIssuer": "Apple", "cusip": "037", "value": 100, "sshPrnamt": 1000, "sshPrnamtType": "SH"},
            ]
        )
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


class TestSuperinvestorCollectorEdgarFlow:
    def test_collect_success(self, rich_db):
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

        # 모듈 상수가 아니라 **클래스 속성**을 패치한다 — `collect()` 가 `self.investors`
        # 를 읽으므로(#1098 은행 수집기가 같은 코드를 재사용한다) 모듈 상수 패치는
        # 클래스 정의 시점에 이미 바인딩된 값을 바꾸지 못한다.
        with patch.object(SuperinvestorCollector, "investors", {"TestInvestor": "0001234567"}):
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

        mock_changes = pd.DataFrame(
            [
                {
                    "ticker": "AAPL",
                    "filing_date": "2024-05-15",
                    "change_type": "INCREASED",
                    "shares_change": 20000,
                }
            ]
        )

        with (
            patch("nuri.collectors.superinvestors.detect_changes", return_value=mock_changes),
            patch("nuri.collectors.superinvestors.SUPERINVESTORS", {"Warren Buffett": "0000000001"}),
        ):
            results = backtest_superinvestor(investor="Warren Buffett", hold_days=30, db_path=rich_db)
        assert isinstance(results, list)


# ##############################################################################
# Source: test_coverage_round20.py
# ##############################################################################


class TestSuperinvestorCollectorEdgarMoreScenarios:
    def test_collect_with_mock_edgar(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_infotable = pd.DataFrame(
            {
                "Ticker": ["AAPL", "NVDA", "AAPL"],
                "Value": [1000000, 500000, 200000],
                "SharesPrnAmount": [5000, 3000, 1000],
                "Issuer": ["Apple Inc", "NVIDIA", "Apple Inc"],
            }
        )
        mock_filing_obj = MagicMock()
        mock_filing_obj.infotable = mock_infotable
        mock_filing = MagicMock()
        mock_filing.filing_date = "2025-01-15"
        mock_filing.obj.return_value = mock_filing_obj
        mock_company = MagicMock()
        mock_company.get_filings.return_value = [mock_filing]

        monkeypatch.setattr("nuri.collectors.superinvestors.SUPERINVESTORS", {"Warren Buffett": "0001067983"})
        import sys

        monkeypatch.setitem(sys.modules, "edgar", MagicMock(Company=lambda cik: mock_company, set_identity=MagicMock()))

        collector = SuperinvestorCollector()
        results = collector.collect(quarters=1)
        assert len(results) >= 2

    def test_collect_empty_filings(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_company = MagicMock()
        mock_company.get_filings.return_value = []
        monkeypatch.setattr("nuri.collectors.superinvestors.SUPERINVESTORS", {"Test": "000"})
        import sys

        monkeypatch.setitem(sys.modules, "edgar", MagicMock(Company=lambda cik: mock_company, set_identity=MagicMock()))
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

        monkeypatch.setitem(sys.modules, "edgar", MagicMock(Company=lambda cik: mock_company, set_identity=MagicMock()))
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

        monkeypatch.setitem(sys.modules, "edgar", MagicMock(Company=lambda cik: mock_company, set_identity=MagicMock()))
        assert SuperinvestorCollector().collect() == []

    def test_collect_zero_total_value(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_infotable = pd.DataFrame(
            {"Ticker": ["AAPL"], "Value": [0], "SharesPrnAmount": [100], "Issuer": ["Apple Inc"]}
        )
        mock_filing_obj = MagicMock()
        mock_filing_obj.infotable = mock_infotable
        mock_filing = MagicMock()
        mock_filing.filing_date = "2025-01-15"
        mock_filing.obj.return_value = mock_filing_obj
        mock_company = MagicMock()
        mock_company.get_filings.return_value = [mock_filing]
        monkeypatch.setattr("nuri.collectors.superinvestors.SUPERINVESTORS", {"Test": "000"})
        import sys

        monkeypatch.setitem(sys.modules, "edgar", MagicMock(Company=lambda cik: mock_company, set_identity=MagicMock()))
        assert SuperinvestorCollector().collect() == []

    def test_collect_nan_ticker(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_infotable = pd.DataFrame(
            {
                "Ticker": [None, "AAPL"],
                "Value": [500000, 500000],
                "SharesPrnAmount": [100, 200],
                "Issuer": ["Unknown", "Apple Inc"],
            }
        )
        mock_filing_obj = MagicMock()
        mock_filing_obj.infotable = mock_infotable
        mock_filing = MagicMock()
        mock_filing.filing_date = "2025-01-15"
        mock_filing.obj.return_value = mock_filing_obj
        mock_company = MagicMock()
        mock_company.get_filings.return_value = [mock_filing]
        monkeypatch.setattr("nuri.collectors.superinvestors.SUPERINVESTORS", {"Test": "000"})
        import sys

        monkeypatch.setitem(sys.modules, "edgar", MagicMock(Company=lambda cik: mock_company, set_identity=MagicMock()))
        results = SuperinvestorCollector().collect()
        assert all(r["ticker"] == "AAPL" for r in results)

    def test_collect_company_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        monkeypatch.setattr("nuri.collectors.superinvestors.SUPERINVESTORS", {"Test": "000"})
        import sys

        monkeypatch.setitem(
            sys.modules,
            "edgar",
            MagicMock(Company=MagicMock(side_effect=RuntimeError("network")), set_identity=MagicMock()),
        )
        assert SuperinvestorCollector().collect() == []

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        c = SuperinvestorCollector()
        assert c.save([]) == 0
        assert c.save(None) == 0

    def test_save_records(self, db_with_portfolio):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        count = SuperinvestorCollector().save(
            [
                {
                    "investor": "Buffett",
                    "filing_date": "2025-01-15",
                    "ticker": "AAPL",
                    "shares": 1000.0,
                    "market_value": 200000.0,
                    "portfolio_pct": 25.5,
                    "issuer_name": "Apple Inc",
                }
            ]
        )
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
            conn.execute(
                "INSERT INTO superinvestors (id, investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name) VALUES (NULL, 'Buffett', '2025-01-15', 'AAPL', 1000, 200000, 25.0, 'Apple Inc')"
            )
            conn.execute(
                "INSERT INTO superinvestors (id, investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name) VALUES (NULL, 'Buffett', '2025-01-15', 'MSFT', 500, 100000, 12.0, 'Microsoft')"
            )
            conn.execute(
                "INSERT INTO superinvestors (id, investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name) VALUES (NULL, 'Buffett', '2025-04-15', 'AAPL', 2000, 400000, 50.0, 'Apple Inc')"
            )
            conn.execute(
                "INSERT INTO superinvestors (id, investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name) VALUES (NULL, 'Buffett', '2025-04-15', 'NVDA', 300, 60000, 15.0, 'NVIDIA')"
            )
        df = detect_changes("Buffett", db_path=db_with_portfolio)
        changes = set(df["change_type"].unique())
        assert "NEW" in changes
        assert "CLOSED" in changes

    def test_detect_changes_insufficient_quarters(self, db_with_portfolio):
        from nuri.collectors.superinvestors import detect_changes

        assert detect_changes("Nobody", db_path=db_with_portfolio).empty


class TestSuperinvestorDetectChangesEdgeCases:
    def test_detect_unchanged(self, db_with_portfolio):
        from nuri.collectors.superinvestors import detect_changes

        with get_db(db_with_portfolio) as conn:
            conn.execute(
                "INSERT INTO superinvestors (id, investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name) VALUES (NULL, 'X', '2025-01-15', 'AAPL', 1000, 200000, 50.0, 'Apple')"
            )
            conn.execute(
                "INSERT INTO superinvestors (id, investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name) VALUES (NULL, 'X', '2025-04-15', 'AAPL', 1000, 200000, 50.0, 'Apple')"
            )
        assert "UNCHANGED" in detect_changes("X", db_path=db_with_portfolio)["change_type"].values

    def test_detect_decreased(self, db_with_portfolio):
        from nuri.collectors.superinvestors import detect_changes

        with get_db(db_with_portfolio) as conn:
            conn.execute(
                "INSERT INTO superinvestors (id, investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name) VALUES (NULL, 'Y', '2025-01-15', 'AAPL', 1000, 200000, 50.0, 'Apple')"
            )
            conn.execute(
                "INSERT INTO superinvestors (id, investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name) VALUES (NULL, 'Y', '2025-04-15', 'AAPL', 500, 100000, 25.0, 'Apple')"
            )
        assert "DECREASED" in detect_changes("Y", db_path=db_with_portfolio)["change_type"].values

    def test_detect_prev_shares_zero(self, db_with_portfolio):
        from nuri.collectors.superinvestors import detect_changes

        with get_db(db_with_portfolio) as conn:
            conn.execute(
                "INSERT INTO superinvestors (id, investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name) VALUES (NULL, 'Z', '2025-01-15', 'AAPL', 0, 0, 0, 'Apple')"
            )
            conn.execute(
                "INSERT INTO superinvestors (id, investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name) VALUES (NULL, 'Z', '2025-04-15', 'AAPL', 500, 100000, 50.0, 'Apple')"
            )
        assert "INCREASED" in detect_changes("Z", db_path=db_with_portfolio)["change_type"].values


class TestCollectFiltersNaTicker:
    """`collect()` 가 ticker NaN/empty 인 row 를 skip (line 110)."""

    def test_nan_ticker_skipped(self, monkeypatch):
        """edgar 가 ticker=NaN 가진 infotable 반환 → continue 분기 활성화."""
        from nuri.collectors.superinvestors import SuperinvestorCollector

        # 빈 ticker 1 row + 정상 ticker 1 row mix.
        # groupby 는 NaN 키 row 를 drop 하므로 NaN ticker 는 line 110 cover 못함.
        # 빈 문자열 ticker 는 groupby 에 포함됨 → `not ticker` truthy 분기 진입.
        infotable = pd.DataFrame(
            [
                {"Ticker": "", "Value": 1000, "SharesPrnAmount": 10, "Issuer": "Unknown"},
                {"Ticker": "MSFT", "Value": 5000, "SharesPrnAmount": 50, "Issuer": "Microsoft"},
            ]
        )

        # Filing object mock
        filing_mock = MagicMock()
        filing_mock.filing_date = "2026-04-01"
        filing_obj = MagicMock()
        filing_obj.infotable = infotable
        filing_mock.obj.return_value = filing_obj

        # Company.get_filings → list of filings (truthy list, len > 0)
        company_mock = MagicMock()
        company_mock.get_filings.return_value = [filing_mock]

        # SUPERINVESTORS dict 짧게
        monkeypatch.setattr("nuri.collectors.superinvestors.SUPERINVESTORS", {"Test Whale": "0001234567"})

        # `from edgar import Company, set_identity` 는 함수 내부 import → sys.modules mock
        import sys

        edgar_mock = MagicMock()
        edgar_mock.Company = lambda cik: company_mock
        edgar_mock.set_identity = lambda *a, **kw: None
        monkeypatch.setitem(sys.modules, "edgar", edgar_mock)

        c = SuperinvestorCollector()
        results = c.collect(quarters=1)
        # 빈 ticker row 는 skip, MSFT 만 살아 있어야 함
        tickers = [r["ticker"] for r in results]
        assert "MSFT" in tickers
        assert "" not in tickers


class TestPrintInvestorPortfolioContinueOnEmpty:
    """`print_investor_portfolio` 가 investor distinct 에 있지만 holdings query
    가 빈 결과 → continue (line 293)."""

    def test_skips_investors_without_rows(self, monkeypatch, capsys):
        from nuri.collectors import superinvestors

        def fake_query(sql, params=(), db_path=None):
            if "DISTINCT investor" in sql:
                return [{"investor": "AAA"}, {"investor": "BBB"}]
            if "DISTINCT ticker FROM portfolio" in sql:
                return []
            # holdings query
            if "FROM superinvestors" in sql and "ORDER BY portfolio_pct DESC" in sql:
                return []  # 빈 holdings → continue 분기 (line 293)
            return []

        monkeypatch.setattr(superinvestors, "query", fake_query)
        superinvestors.print_summary()
        out = capsys.readouterr().out
        # 헤더만 출력, 각 investor 의 본문은 continue 로 skip
        assert "슈퍼투자자 포트폴리오" in out
        assert "공시일" not in out  # body 부분 미출력

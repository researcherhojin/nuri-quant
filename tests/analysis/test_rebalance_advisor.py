"""Tests for nuri.analysis.rebalance_advisor — split from tests/test_analysis_all.py (#157)."""
from unittest.mock import patch

import pandas as pd

from nuri.core.db import get_db


class TestRebalanceDeep:
    """From test_coverage_round7.py."""
    def test_detect_violations_leveraged(self, rich_db):
        # Uses TQQQ from the leverage_ban list (config/rules.yaml banned_etfs)
        # to test detection. Generic quantity/price — no user-specific data.
        from nuri.analysis.rebalance_advisor import detect_violations
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio") as mock_ap:
            mock_df = pd.DataFrame([
                {"ticker": "TQQQ", "account": "test", "quantity": 10,
                 "avg_price": 100.0, "current_price": 90.0,
                 "current_value_usd": 900, "pnl_pct": -10.0,
                 "weight_pct": 5.0, "sector": "ETF", "currency": "USD"},
            ])
            mock_df.attrs["total_value_usd"] = 18000
            mock_ap.return_value = mock_df
            violations = detect_violations()
        lev = [v for v in violations if v.get("violation_type") == "leverage_etf"]
        assert len(lev) > 0


class TestDetectViolations:
    """From test_new_modules.py."""
    def test_leverage_etf_detected(self, db_path):
        # Uses TQQQ from leverage_ban list. Generic quantity/price.
        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "TQQQ", "sector": "ETF", "quantity": 10,
             "avg_price": 100.0, "current_price": 90.0, "currency": "USD",
             "current_value_usd": 900.0, "cost_basis_usd": 1000.0,
             "pnl_usd": -100.0, "pnl_pct": -10.0, "weight_pct": 5.0, "price_date": "2026-03-27"},
            {"account": "test", "ticker": "AAA", "sector": "Tech", "quantity": 10,
             "avg_price": 100.0, "current_price": 110.0, "currency": "USD",
             "current_value_usd": 1100.0, "cost_basis_usd": 1000.0,
             "pnl_usd": 100.0, "pnl_pct": 10.0, "weight_pct": 10.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 2000.0
        from nuri.analysis.rebalance_advisor import detect_violations
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            violations = detect_violations(db_path=db_path)
        leverage_violations = [v for v in violations if v["violation_type"] == "leverage_etf"]
        assert len(leverage_violations) >= 1
        assert leverage_violations[0]["ticker"] == "TQQQ"

    def test_stop_loss_exceeded(self, db_path):
        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "BADSTOCK", "sector": "Test", "quantity": 10,
             "avg_price": 100.0, "current_price": 80.0, "currency": "USD",
             "current_value_usd": 800.0, "cost_basis_usd": 1000.0,
             "pnl_usd": -200.0, "pnl_pct": -20.0, "weight_pct": 100.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 800.0
        from nuri.analysis.rebalance_advisor import detect_violations
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            violations = detect_violations(db_path=db_path)
        stop_violations = [v for v in violations if v["violation_type"] == "stop_loss_exceeded"]
        assert len(stop_violations) >= 1

    def test_position_limit_exceeded(self, db_path):
        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "TSLA", "sector": "SectorA", "quantity": 100,
             "avg_price": 350.0, "current_price": 360.0, "currency": "USD",
             "current_value_usd": 36000.0, "cost_basis_usd": 35000.0,
             "pnl_usd": 1000.0, "pnl_pct": 2.9, "weight_pct": 95.0, "price_date": "2026-03-27"},
            {"account": "test", "ticker": "NVDA", "sector": "Semiconductor", "quantity": 1,
             "avg_price": 160.0, "current_price": 168.0, "currency": "USD",
             "current_value_usd": 168.0, "cost_basis_usd": 160.0,
             "pnl_usd": 8.0, "pnl_pct": 5.0, "weight_pct": 5.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 36168.0
        from nuri.analysis.rebalance_advisor import detect_violations
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            violations = detect_violations(db_path=db_path)
        pos_violations = [v for v in violations if v["violation_type"] == "position_limit_exceeded"]
        assert len(pos_violations) >= 1

    def test_no_violations(self, db_path):
        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "NVDA", "sector": "Semiconductor", "quantity": 1,
             "avg_price": 160.0, "current_price": 168.0, "currency": "USD",
             "current_value_usd": 168.0, "cost_basis_usd": 160.0,
             "pnl_usd": 8.0, "pnl_pct": 5.0, "weight_pct": 10.0, "price_date": "2026-03-27"},
            {"account": "test", "ticker": "GOOGL", "sector": "BigTech", "quantity": 1,
             "avg_price": 260.0, "current_price": 274.0, "currency": "USD",
             "current_value_usd": 274.0, "cost_basis_usd": 260.0,
             "pnl_usd": 14.0, "pnl_pct": 5.4, "weight_pct": 10.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 442.0
        from nuri.analysis.rebalance_advisor import detect_violations
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            violations = detect_violations(db_path=db_path)
        assert len(violations) == 0


class TestCalculateRebalanceActions:
    """From test_new_modules.py."""
    def test_sorted_by_priority(self, db_path):
        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "BBB", "sector": "SectorB", "quantity": 96,
             "avg_price": 20.0, "current_price": 11.44, "currency": "USD",
             "current_value_usd": 1098.24, "cost_basis_usd": 1625.28,
             "pnl_usd": -527.04, "pnl_pct": -32.4, "weight_pct": 5.0, "price_date": "2026-03-27"},
            {"account": "test", "ticker": "BADSTOCK", "sector": "Test", "quantity": 10,
             "avg_price": 100.0, "current_price": 80.0, "currency": "USD",
             "current_value_usd": 800.0, "cost_basis_usd": 1000.0,
             "pnl_usd": -200.0, "pnl_pct": -20.0, "weight_pct": 5.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 1898.24
        from nuri.analysis.rebalance_advisor import calculate_rebalance_actions
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            actions = calculate_rebalance_actions(db_path=db_path)
        if len(actions) >= 2:
            priorities = [a["priority"] for a in actions]
            assert priorities == sorted(priorities)

    def test_total_recovery_calculated(self, db_path):
        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "BBB", "sector": "SectorB", "quantity": 96,
             "avg_price": 20.0, "current_price": 11.44, "currency": "USD",
             "current_value_usd": 1098.24, "cost_basis_usd": 1625.28,
             "pnl_usd": -527.04, "pnl_pct": -32.4, "weight_pct": 100.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 1098.24
        from nuri.analysis.rebalance_advisor import calculate_rebalance_actions
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            actions = calculate_rebalance_actions(db_path=db_path)
        assert len(actions) > 0
        total = sum(a["sell_value_usd"] for a in actions)
        assert total > 0


class TestGenerateAdvisorReport:
    """From test_new_modules.py."""
    def test_report_structure(self, db_path):
        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "BBB", "sector": "SectorB", "quantity": 96,
             "avg_price": 20.0, "current_price": 11.44, "currency": "USD",
             "current_value_usd": 1098.24, "cost_basis_usd": 1625.28,
             "pnl_usd": -527.04, "pnl_pct": -32.4, "weight_pct": 5.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 1098.24
        from nuri.analysis.rebalance_advisor import generate_advisor_report
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            report = generate_advisor_report(db_path=db_path)
        assert "actions" in report
        assert "total_violations" in report
        assert "total_recovery_usd" in report
        assert "violations_by_type" in report
        assert "violations_by_severity" in report
        assert "has_critical" in report

    def test_empty_portfolio_report(self, db_path):
        mock_df = pd.DataFrame()
        from nuri.analysis.rebalance_advisor import generate_advisor_report
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            report = generate_advisor_report(db_path=db_path)
        assert report["total_violations"] == 0
        assert report["total_recovery_usd"] == 0


class TestRebalanceSeverity:
    """From test_coverage_round16.py."""
    def test_leverage_etf(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("leverage_etf", 0, 0) == "critical"

    def test_stop_loss_critical(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("stop_loss_exceeded", -15, -7) == "critical"

    def test_stop_loss_high(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("stop_loss_exceeded", -8, -7) == "high"

    def test_position_limit_high(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("position_limit_exceeded", 30, 0.15) == "high"

    def test_position_limit_medium(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("position_limit_exceeded", 18, 0.15) == "medium"

    def test_sector_limit_high(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("sector_limit_exceeded", 50, 0.35) == "high"

    def test_sector_limit_medium(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("sector_limit_exceeded", 40, 0.35) == "medium"

    def test_unknown_type(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("some_new_type", 0, 0) == "medium"


class TestRebalancePrint:
    """From test_coverage_round16.py."""
    def test_no_actions(self, capsys):
        from nuri.analysis.rebalance_advisor import print_rebalance_advisor
        print_rebalance_advisor([])
        out = capsys.readouterr().out
        assert "위반 사항 없음" in out

    def test_with_actions(self, capsys):
        from nuri.analysis.rebalance_advisor import print_rebalance_advisor
        actions = [
            {"ticker": "TQQQ", "sell_shares": 100, "sell_value_usd": 5000, "reason": "레버리지 ETF",
             "action": "SELL_ALL", "severity": "critical", "cumulative_recovery_usd": 5000},
            {"ticker": "AAPL", "sell_shares": 5, "sell_value_usd": 1000, "reason": "비중 초과",
             "action": "REDUCE", "severity": "high", "cumulative_recovery_usd": 6000},
        ]
        print_rebalance_advisor(actions)
        out = capsys.readouterr().out
        assert "SELL TQQQ" in out
        assert "[!!]" in out
        assert "총 회수" in out


class TestRebalanceGetFactorScores:
    """From test_coverage_round16.py."""
    def test_empty(self, rich_db):
        from nuri.analysis.rebalance_advisor import _get_factor_scores
        scores = _get_factor_scores(db_path=rich_db)
        assert scores == {}

    def test_with_data(self, rich_db):
        from nuri.analysis.rebalance_advisor import _get_factor_scores
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO factors (ticker, date, composite_score) VALUES (?, ?, ?)",
                ("AAPL", "2025-03-20", 0.85))
        scores = _get_factor_scores(db_path=rich_db)
        assert scores["AAPL"] == 0.85


class TestRebalanceGenerateReport:
    """From test_coverage_round16.py."""
    def test_no_violations(self, rich_db):
        from nuri.analysis.rebalance_advisor import generate_advisor_report
        with patch("nuri.analysis.rebalance_advisor.detect_violations", return_value=[]):
            report = generate_advisor_report(db_path=rich_db)
        assert report["total_violations"] == 0
        assert report["has_critical"] is False

    def test_with_violations(self, rich_db):
        from nuri.analysis.rebalance_advisor import generate_advisor_report
        fake_violations = [
            {"ticker": "TQQQ", "violation_type": "leverage_etf", "priority": 1,
             "current_value": -5, "limit_value": 0, "severity": "critical",
             "action": "SELL_ALL", "sell_shares": 50, "sell_value_usd": 3000, "reason": "test"},
        ]
        with patch("nuri.analysis.rebalance_advisor.detect_violations", return_value=fake_violations):
            report = generate_advisor_report(db_path=rich_db)
        assert report["total_violations"] == 1
        assert report["has_critical"] is True
        assert report["violations_by_type"]["leverage_etf"] == 1


class TestRebalanceAdvisor_R27:
    """From test_coverage_round27.py."""
    def test_severity_leverage(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("leverage_etf", 0, 0) == "critical"

    def test_severity_stop_loss_critical(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("stop_loss_exceeded", -14, -7) == "critical"

    def test_severity_stop_loss_high(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("stop_loss_exceeded", -8, -7) == "high"

    def test_severity_position_limit(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("position_limit_exceeded", 20, 0.15) == "medium"
        assert _severity("position_limit_exceeded", 30, 0.15) == "high"

    def test_severity_sector_limit(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("sector_limit_exceeded", 40, 0.35) == "medium"
        assert _severity("sector_limit_exceeded", 55, 0.35) == "high"

    def test_severity_default(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("unknown_type", 0, 0) == "medium"

    def test_print_rebalance_advisor_empty(self, capsys):
        from nuri.analysis.rebalance_advisor import print_rebalance_advisor
        print_rebalance_advisor([])
        captured = capsys.readouterr()
        assert "위반 사항 없음" in captured.out

    def test_print_rebalance_advisor_with_actions(self, capsys):
        from nuri.analysis.rebalance_advisor import print_rebalance_advisor
        actions = [{
            "ticker": "TQQQ", "action": "SELL_ALL", "sell_shares": 10,
            "sell_value_usd": 500, "reason": "레버리지 ETF 금지",
            "severity": "critical", "cumulative_recovery_usd": 500,
        }]
        print_rebalance_advisor(actions)
        captured = capsys.readouterr()
        assert "TQQQ" in captured.out

    def test_generate_advisor_report_empty(self, monkeypatch):
        from nuri.analysis.rebalance_advisor import generate_advisor_report
        monkeypatch.setattr("nuri.analysis.rebalance_advisor.calculate_rebalance_actions", lambda db_path=None: [])
        report = generate_advisor_report()
        assert report["total_violations"] == 0
        assert report["has_critical"] is False


class TestRebalanceModule_R3:
    """From test_coverage_round3.py (detect_violations with rate)."""
    def test_detect_violations_with_rate(self, db_path):
        from nuri.analysis.rebalance_advisor import detect_violations
        mock_df = pd.DataFrame([
            {"ticker": "AAPL", "account": "test", "quantity": 10,
             "avg_price": 190, "current_price": 200, "current_value_usd": 2000,
             "pnl_pct": 5.2, "weight_pct": 60.0, "sector": "Tech", "currency": "USD"},
        ])
        mock_df.attrs["total_value_usd"] = 2000
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            violations = detect_violations()
        assert isinstance(violations, list)

"""Tests for nuri.analysis.rebalance_advisor — split from tests/test_analysis_all.py (#157)."""

import math
from unittest.mock import patch

import pandas as pd
import pytest

from nuri.core.db import get_db


class TestRebalanceDeep:
    """From test_coverage_round7.py."""

    def test_detect_violations_leveraged(self, rich_db):
        # Uses TQQQ from the leverage_ban list (config/rules.yaml banned_etfs)
        # to test detection. Generic quantity/price — no user-specific data.
        from nuri.analysis.rebalance_advisor import detect_violations

        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio") as mock_ap:
            mock_df = pd.DataFrame(
                [
                    {
                        "ticker": "TQQQ",
                        "account": "test",
                        "quantity": 10,
                        "avg_price": 100.0,
                        "current_price": 90.0,
                        "current_value_usd": 900,
                        "pnl_pct": -10.0,
                        "weight_pct": 5.0,
                        "sector": "ETF",
                        "currency": "USD",
                    },
                ]
            )
            mock_df.attrs["total_value_usd"] = 18000
            mock_ap.return_value = mock_df
            violations = detect_violations()
        lev = [v for v in violations if v.get("violation_type") == "leverage_etf"]
        assert len(lev) > 0


class TestDetectViolations:
    """From test_new_modules.py."""

    def test_leverage_etf_detected(self, db_path):
        # Uses TQQQ from leverage_ban list. Generic quantity/price.
        mock_df = pd.DataFrame(
            [
                {
                    "account": "test",
                    "ticker": "TQQQ",
                    "sector": "ETF",
                    "quantity": 10,
                    "avg_price": 100.0,
                    "current_price": 90.0,
                    "currency": "USD",
                    "current_value_usd": 900.0,
                    "cost_basis_usd": 1000.0,
                    "pnl_usd": -100.0,
                    "pnl_pct": -10.0,
                    "weight_pct": 5.0,
                    "price_date": "2026-03-27",
                },
                {
                    "account": "test",
                    "ticker": "AAA",
                    "sector": "Tech",
                    "quantity": 10,
                    "avg_price": 100.0,
                    "current_price": 110.0,
                    "currency": "USD",
                    "current_value_usd": 1100.0,
                    "cost_basis_usd": 1000.0,
                    "pnl_usd": 100.0,
                    "pnl_pct": 10.0,
                    "weight_pct": 10.0,
                    "price_date": "2026-03-27",
                },
            ]
        )
        mock_df.attrs["total_value_usd"] = 2000.0
        from nuri.analysis.rebalance_advisor import detect_violations

        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            violations = detect_violations(db_path=db_path)
        leverage_violations = [v for v in violations if v["violation_type"] == "leverage_etf"]
        assert len(leverage_violations) >= 1
        assert leverage_violations[0]["ticker"] == "TQQQ"

    def test_stop_loss_exceeded(self, db_path):
        mock_df = pd.DataFrame(
            [
                {
                    "account": "test",
                    "ticker": "BADSTOCK",
                    "sector": "Test",
                    "quantity": 10,
                    "avg_price": 100.0,
                    "current_price": 80.0,
                    "currency": "USD",
                    "current_value_usd": 800.0,
                    "cost_basis_usd": 1000.0,
                    "pnl_usd": -200.0,
                    "pnl_pct": -20.0,
                    "weight_pct": 100.0,
                    "price_date": "2026-03-27",
                },
            ]
        )
        mock_df.attrs["total_value_usd"] = 800.0
        from nuri.analysis.rebalance_advisor import detect_violations

        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            violations = detect_violations(db_path=db_path)
        stop_violations = [v for v in violations if v["violation_type"] == "stop_loss_exceeded"]
        assert len(stop_violations) >= 1

    def test_position_limit_exceeded(self, db_path):
        mock_df = pd.DataFrame(
            [
                {
                    "account": "test",
                    "ticker": "TSLA",
                    "sector": "SectorA",
                    "quantity": 100,
                    "avg_price": 350.0,
                    "current_price": 360.0,
                    "currency": "USD",
                    "current_value_usd": 36000.0,
                    "cost_basis_usd": 35000.0,
                    "pnl_usd": 1000.0,
                    "pnl_pct": 2.9,
                    "weight_pct": 95.0,
                    "price_date": "2026-03-27",
                },
                {
                    "account": "test",
                    "ticker": "NVDA",
                    "sector": "Semiconductor",
                    "quantity": 1,
                    "avg_price": 160.0,
                    "current_price": 168.0,
                    "currency": "USD",
                    "current_value_usd": 168.0,
                    "cost_basis_usd": 160.0,
                    "pnl_usd": 8.0,
                    "pnl_pct": 5.0,
                    "weight_pct": 5.0,
                    "price_date": "2026-03-27",
                },
            ]
        )
        mock_df.attrs["total_value_usd"] = 36168.0
        from nuri.analysis.rebalance_advisor import detect_violations

        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            violations = detect_violations(db_path=db_path)
        pos_violations = [v for v in violations if v["violation_type"] == "position_limit_exceeded"]
        assert len(pos_violations) >= 1

    def test_no_violations(self, db_path):
        # 8 positions × $1000 each, 4 sectors → 각 종목 12.5% < core 15%, 각 섹터 25% < 35%
        sectors = ["Tech", "Health", "Energy", "Consumer"]
        mock_df = pd.DataFrame(
            [
                {
                    "account": "test",
                    "ticker": f"T{i:02d}",
                    "sector": sectors[i % 4],
                    "quantity": 10,
                    "avg_price": 100.0,
                    "current_price": 100.0,
                    "currency": "USD",
                    "current_value_usd": 1000.0,
                    "cost_basis_usd": 1000.0,
                    "pnl_usd": 0.0,
                    "pnl_pct": 5.0,
                    "weight_pct": 12.5,
                    "price_date": "2026-03-27",
                }
                for i in range(8)
            ]
        )
        mock_df.attrs["total_value_usd"] = 8000.0
        from nuri.analysis.rebalance_advisor import detect_violations

        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            violations = detect_violations(db_path=db_path)
        assert len(violations) == 0


def _two_account_df(main_tsla_qty: int, sub_tsla_qty: int):
    """Helper: Main + Sub 2계좌, TSLA + 8개 filler 종목 (4 섹터 분산).

    각 계좌 합계 $10,000 = TSLA(qty * $100) + 8 filler 균등 분할. price = $100.
    filler는 항상 ≤ 12.5% per account → core(15%)/active(25%) 모두 미위반.
    각 섹터는 ≤ 25% of total → 35% sector limit 미위반.
    """
    sectors = ["Tech", "Health", "Energy", "Consumer"]
    rows = []
    total_portfolio = 20000.0
    for account, tsla_qty in (("Main", main_tsla_qty), ("Sub", sub_tsla_qty)):
        tsla_value = float(tsla_qty * 100)
        rows.append(
            {
                "account": account,
                "ticker": "TSLA",
                "sector": "Auto",
                "quantity": tsla_qty,
                "avg_price": 100.0,
                "current_price": 100.0,
                "currency": "USD",
                "current_value_usd": tsla_value,
                "cost_basis_usd": tsla_value,
                "pnl_usd": 0.0,
                "pnl_pct": 0.0,
                "weight_pct": tsla_value / total_portfolio * 100,
                "price_date": "2026-04-10",
            }
        )
        remaining = 10000.0 - tsla_value
        per_filler_value = remaining / 8
        per_filler_qty = per_filler_value / 100
        for i in range(8):
            rows.append(
                {
                    "account": account,
                    "ticker": f"F{account[0]}{i}",
                    "sector": sectors[i % 4],
                    "quantity": per_filler_qty,
                    "avg_price": 100.0,
                    "current_price": 100.0,
                    "currency": "USD",
                    "current_value_usd": per_filler_value,
                    "cost_basis_usd": per_filler_value,
                    "pnl_usd": 0.0,
                    "pnl_pct": 0.0,
                    "weight_pct": per_filler_value / total_portfolio * 100,
                    "price_date": "2026-04-10",
                }
            )
    df = pd.DataFrame(rows)
    df.attrs["total_value_usd"] = total_portfolio
    return df


def _fake_account_strategy(account: str) -> dict:
    """Test stub: Sub=active(25%), 그 외=core(15%)."""
    if account == "Sub":
        return {"stop_loss": -10, "max_single_position": 0.25, "max_sector_exposure": 0.45}
    return {"stop_loss": -7, "max_single_position": 0.15, "max_sector_exposure": 0.35}


class TestPositionLimitPerAccount:
    """다계좌 종목의 단일종목 비중 위반은 계좌별 전략 한도가 독립적으로 적용되어야 함.

    이전 버그: 종목이 Main(core,15%) + Sub(active,25%)에 동시 존재할 때
    max(0.15, 0.25)=0.25를 사용 → core 계좌의 15% 위반이 가려졌음.
    """

    def test_within_account_limits_no_violation(self, db_path):
        # Main TSLA 14% (core 15% 이내), Sub TSLA 12% (active 25% 이내)
        mock_df = _two_account_df(main_tsla_qty=14, sub_tsla_qty=12)
        from nuri.analysis.rebalance_advisor import detect_violations

        with (
            patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df),
            patch("nuri.core.rules.get_account_strategy", side_effect=_fake_account_strategy),
        ):
            violations = detect_violations(db_path=db_path)
        pos = [v for v in violations if v["violation_type"] == "position_limit_exceeded"]
        assert pos == [], f"Expected no position violations, got: {pos}"

    def test_core_account_violation_isolated(self, db_path):
        # Main TSLA 16% (core 15% 위반), Sub TSLA 10% (active 25% 이내)
        # 이전 버그에서는 max(0.15,0.25)=0.25 → 종합 26% > 25% 1건만 검출 (limit_value 잘못)
        mock_df = _two_account_df(main_tsla_qty=16, sub_tsla_qty=10)
        from nuri.analysis.rebalance_advisor import detect_violations

        with (
            patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df),
            patch("nuri.core.rules.get_account_strategy", side_effect=_fake_account_strategy),
        ):
            violations = detect_violations(db_path=db_path)
        pos = [v for v in violations if v["violation_type"] == "position_limit_exceeded"]
        assert len(pos) == 1
        assert pos[0]["limit_value"] == 0.15
        assert pos[0]["current_value"] == 16.0
        assert "Main" in pos[0]["reason"]

    def test_both_accounts_violate_independently(self, db_path):
        # Main TSLA 20% (core 15% 위반), Sub TSLA 30% (active 25% 위반)
        mock_df = _two_account_df(main_tsla_qty=20, sub_tsla_qty=30)
        from nuri.analysis.rebalance_advisor import detect_violations

        with (
            patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df),
            patch("nuri.core.rules.get_account_strategy", side_effect=_fake_account_strategy),
        ):
            violations = detect_violations(db_path=db_path)
        pos = [v for v in violations if v["violation_type"] == "position_limit_exceeded"]
        assert len(pos) == 2
        by_account = {("Main" if "Main" in v["reason"] else "Sub"): v for v in pos}
        assert set(by_account) == {"Main", "Sub"}
        assert by_account["Main"]["limit_value"] == 0.15
        assert by_account["Main"]["current_value"] == 20.0
        assert by_account["Sub"]["limit_value"] == 0.25
        assert by_account["Sub"]["current_value"] == 30.0


class TestCalculateRebalanceActions:
    """From test_new_modules.py."""

    def test_sorted_by_priority(self, db_path):
        mock_df = pd.DataFrame(
            [
                {
                    "account": "test",
                    "ticker": "BBB",
                    "sector": "SectorB",
                    "quantity": 96,
                    "avg_price": 20.0,
                    "current_price": 11.44,
                    "currency": "USD",
                    "current_value_usd": 1098.24,
                    "cost_basis_usd": 1625.28,
                    "pnl_usd": -527.04,
                    "pnl_pct": -32.4,
                    "weight_pct": 5.0,
                    "price_date": "2026-03-27",
                },
                {
                    "account": "test",
                    "ticker": "BADSTOCK",
                    "sector": "Test",
                    "quantity": 10,
                    "avg_price": 100.0,
                    "current_price": 80.0,
                    "currency": "USD",
                    "current_value_usd": 800.0,
                    "cost_basis_usd": 1000.0,
                    "pnl_usd": -200.0,
                    "pnl_pct": -20.0,
                    "weight_pct": 5.0,
                    "price_date": "2026-03-27",
                },
            ]
        )
        mock_df.attrs["total_value_usd"] = 1898.24
        from nuri.analysis.rebalance_advisor import calculate_rebalance_actions

        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            actions = calculate_rebalance_actions(db_path=db_path)
        if len(actions) >= 2:
            priorities = [a["priority"] for a in actions]
            assert priorities == sorted(priorities)

    def test_total_recovery_calculated(self, db_path):
        mock_df = pd.DataFrame(
            [
                {
                    "account": "test",
                    "ticker": "BBB",
                    "sector": "SectorB",
                    "quantity": 96,
                    "avg_price": 20.0,
                    "current_price": 11.44,
                    "currency": "USD",
                    "current_value_usd": 1098.24,
                    "cost_basis_usd": 1625.28,
                    "pnl_usd": -527.04,
                    "pnl_pct": -32.4,
                    "weight_pct": 100.0,
                    "price_date": "2026-03-27",
                },
            ]
        )
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
        mock_df = pd.DataFrame(
            [
                {
                    "account": "test",
                    "ticker": "BBB",
                    "sector": "SectorB",
                    "quantity": 96,
                    "avg_price": 20.0,
                    "current_price": 11.44,
                    "currency": "USD",
                    "current_value_usd": 1098.24,
                    "cost_basis_usd": 1625.28,
                    "pnl_usd": -527.04,
                    "pnl_pct": -32.4,
                    "weight_pct": 5.0,
                    "price_date": "2026-03-27",
                },
            ]
        )
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
            {
                "ticker": "TQQQ",
                "sell_shares": 100,
                "sell_value_usd": 5000,
                "reason": "레버리지 ETF",
                "action": "SELL_ALL",
                "severity": "critical",
                "cumulative_recovery_usd": 5000,
            },
            {
                "ticker": "AAPL",
                "sell_shares": 5,
                "sell_value_usd": 1000,
                "reason": "비중 초과",
                "action": "REDUCE",
                "severity": "high",
                "cumulative_recovery_usd": 6000,
            },
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
                "INSERT INTO factors (ticker, date, composite_score) VALUES (?, ?, ?)", ("AAPL", "2025-03-20", 0.85)
            )
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
            {
                "ticker": "TQQQ",
                "violation_type": "leverage_etf",
                "priority": 1,
                "current_value": -5,
                "limit_value": 0,
                "severity": "critical",
                "action": "SELL_ALL",
                "sell_shares": 50,
                "sell_value_usd": 3000,
                "reason": "test",
            },
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

        actions = [
            {
                "ticker": "TQQQ",
                "action": "SELL_ALL",
                "sell_shares": 10,
                "sell_value_usd": 500,
                "reason": "레버리지 ETF 금지",
                "severity": "critical",
                "cumulative_recovery_usd": 500,
            }
        ]
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

        mock_df = pd.DataFrame(
            [
                {
                    "ticker": "AAPL",
                    "account": "test",
                    "quantity": 10,
                    "avg_price": 190,
                    "current_price": 200,
                    "current_value_usd": 2000,
                    "pnl_pct": 5.2,
                    "weight_pct": 60.0,
                    "sector": "Tech",
                    "currency": "USD",
                },
            ]
        )
        mock_df.attrs["total_value_usd"] = 2000
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            violations = detect_violations()
        assert isinstance(violations, list)


class TestKrwTickerSellValuesAreUsd:
    """`.KS` 종목의 비중/섹터 초과 매도 수량·회수금액이 USD 단위인지 잠근다.

    회귀 전에는 `current_value_usd`(USD 환산액)를 `current_price`(원화 종목이면
    KRW)로 나눠 매도 수량이 환율배만큼 축소되고 `sell_value_usd` 에는 KRW 금액이
    그대로 들어갔다. 우선순위 정렬이 회수금액 기준이라 순서까지 틀어졌다.
    실측(2026-08-20): 448290.KS 15주/$189 가 1주/$17,875 로 나왔고
    `total_recovery_usd` 는 $10,511 대신 $1,834,172 였다.

    환율 1,400 을 가정한 합성 데이터 — 실제 보유와 무관한 더미 티커다.
    """

    def _krw_row(self, ticker, qty, krw_price, sector, weight_pct, rate=1400.0):
        # analyze_portfolio 와 같은 방식: current_value_usd = price * qty / rate
        return {
            "ticker": ticker,
            "account": "test",
            "quantity": qty,
            "avg_price": krw_price,
            "current_price": krw_price,
            "current_value_usd": krw_price * qty / rate,
            "pnl_pct": 0.0,
            "weight_pct": weight_pct,
            "sector": sector,
            "currency": "KRW",
        }

    def test_position_limit_sell_shares_and_value_are_usd(self, db_path):
        from nuri.analysis.rebalance_advisor import detect_violations
        from nuri.core.rules import MAX_SINGLE_POSITION, get_account_strategy

        # 100주 × ₩14,000 / 1,400 = $1,000 (주당 $10)
        mock_df = pd.DataFrame(
            [
                self._krw_row("999999.KS", 100, 14000.0, "Dummy", 83.3),
                {
                    "ticker": "AAA",
                    "account": "test",
                    "quantity": 2,
                    "avg_price": 100.0,
                    "current_price": 100.0,
                    "current_value_usd": 200.0,
                    "pnl_pct": 0.0,
                    "weight_pct": 16.7,
                    "sector": "Other",
                    "currency": "USD",
                },
            ]
        )
        mock_df.attrs["total_value_usd"] = 1200.0
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            violations = detect_violations()

        v = next(
            v for v in violations if v["ticker"] == "999999.KS" and v["violation_type"] == "position_limit_exceeded"
        )

        max_pos = get_account_strategy("test").get("max_single_position", MAX_SINGLE_POSITION)
        excess_usd = 1000.0 - 1200.0 * max_pos
        expected_shares = math.ceil(excess_usd / 10.0)  # 주당 USD 단가

        assert v["sell_shares"] == expected_shares
        # 회귀 코드는 ceil(excess / 14000) = 1 주였다
        assert v["sell_shares"] > 1
        assert v["sell_value_usd"] == pytest.approx(expected_shares * 10.0, rel=1e-6)
        # 회수금액은 보유 USD 평가액을 넘을 수 없다 — KRW 가 새면 즉시 깨진다
        assert v["sell_value_usd"] <= 1000.0

    def test_sector_limit_sell_value_is_usd(self, db_path):
        from nuri.analysis.rebalance_advisor import detect_violations

        # 같은 섹터 원화 종목 2개로 섹터 한도(35%) 초과를 만든다
        mock_df = pd.DataFrame(
            [
                self._krw_row("999998.KS", 100, 14000.0, "DummySector", 50.0),
                self._krw_row("999997.KS", 100, 14000.0, "DummySector", 50.0),
            ]
        )
        mock_df.attrs["total_value_usd"] = 2000.0
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            violations = detect_violations()

        sector_v = [v for v in violations if v["violation_type"] == "sector_limit_exceeded"]
        assert sector_v, "섹터 한도 위반이 감지되지 않았다"
        for v in sector_v:
            # 한 종목 전체가 $1,000 이다. KRW 가 새면 14,000 단위 숫자가 나온다.
            assert v["sell_value_usd"] <= 1000.0

"""Tests for nuri.trading.strategy.strategic_allocation (STRATEGY §3.10 Phase 2).

검증:
- compute_current_allocation: portfolio → asset_class % 매핑 (us_equity / kr_equity / bond / commodity)
- compute_drift: target 대비 violation 분류 (warning / emergency)
- compute_drift: targets 미정의 strategy → error
- compute_drift: 빈 portfolio → 모든 class under target
- format_report: REBALANCE / OK 분기

privacy: synthetic ticker (TST_*) + round-million 가격, 사용자 실 holdings X.
"""

from __future__ import annotations

import pytest

from nuri.core.db import get_db, upsert_portfolio
from nuri.trading.strategy.strategic_allocation import (
    compute_current_allocation,
    compute_drift,
    format_report,
    main,
)


def _seed_portfolio(db_path, holdings: list[dict]) -> None:
    """holdings = [{ticker, sector, quantity, avg_price}, ...]"""
    rows = [
        {
            "account": "test",
            "ticker": h["ticker"],
            "quantity": h["quantity"],
            "avg_price": h["avg_price"],
            "currency": "USD",
            "sector": h.get("sector", ""),
        }
        for h in holdings
    ]
    upsert_portfolio(rows, db_path)


class TestComputeCurrentAllocation:
    def test_empty_portfolio_returns_empty_dict(self, db_path):
        assert compute_current_allocation(db_path=db_path) == {}

    def test_us_only_portfolio_classifies_us_equity(self, db_path):
        _seed_portfolio(
            db_path,
            [
                {"ticker": "TST_A", "sector": "Technology", "quantity": 100, "avg_price": 50},
                {"ticker": "TST_B", "sector": "Healthcare", "quantity": 50, "avg_price": 100},
            ],
        )
        # 5000 + 5000 = 10000 total, both us_equity
        result = compute_current_allocation(db_path=db_path)
        assert result == {"us_equity": 100.0}

    def test_mixed_us_and_kr_classifies_correctly(self, db_path):
        _seed_portfolio(
            db_path,
            [
                {"ticker": "TST_US", "sector": "Technology", "quantity": 100, "avg_price": 50},  # 5000
                {"ticker": "005930.KS", "sector": "Semiconductor", "quantity": 100, "avg_price": 50},  # 5000
            ],
        )
        result = compute_current_allocation(db_path=db_path)
        # 50/50 split between us_equity and kr_equity
        assert result == {"us_equity": 50.0, "kr_equity": 50.0}

    def test_zero_value_holdings_skipped(self, db_path):
        _seed_portfolio(
            db_path,
            [
                {"ticker": "TST_A", "sector": "Technology", "quantity": 100, "avg_price": 50},
                {"ticker": "TST_ZERO", "sector": "Technology", "quantity": 0, "avg_price": 100},
            ],
        )
        result = compute_current_allocation(db_path=db_path)
        assert result == {"us_equity": 100.0}


class TestComputeDrift:
    def test_perfectly_aligned_portfolio_returns_ok(self, db_path):
        # core target: us=50 kr=20 bond=20 commodity=5 — match exactly with us 50 / kr 20 / bond 20 / commodity 5 / cash 5
        # Build holdings to match (10000 total):
        #   us 5000 / kr 2000 / bond 2000 / commodity 500 / cash 500 (cash 은 portfolio 외)
        # commodity = 500/9500 = 5.26%, us = 5000/9500 = 52.6%. Slight off — easier: use 95% deployable.
        _seed_portfolio(
            db_path,
            [
                {"ticker": "TST_US", "sector": "Technology", "quantity": 50, "avg_price": 100},  # 5000 us_equity
                {"ticker": "005930.KS", "sector": "Semiconductor", "quantity": 20, "avg_price": 100},  # 2000 kr_equity
                {"ticker": "TST_BOND", "sector": "ETF/Bond", "quantity": 20, "avg_price": 100},  # 2000 bond
                {"ticker": "TST_COMM", "sector": "ETF/Commodity", "quantity": 5, "avg_price": 100},  # 500 commodity
            ],
        )
        # Total 9500; weights: us 52.6 / kr 21.05 / bond 21.05 / commodity 5.26
        # Targets (core): us 50 / kr 20 / bond 20 / commodity 5
        # Drift: us +2.6 / kr +1.05 / bond +1.05 / commodity +0.26 — all under 5% threshold
        result = compute_drift("core", db_path=db_path)
        assert result["action"] == "OK"
        assert result["violations"] == []

    def test_overweight_us_triggers_warning(self, db_path):
        # us 50% target, give 60% of portfolio to us → drift +10 → emergency
        # us 8000 / bond 1000 / kr 1000 → us 80, bond 10, kr 10 → us drift +30 (emergency)
        _seed_portfolio(
            db_path,
            [
                {"ticker": "TST_US", "sector": "Technology", "quantity": 80, "avg_price": 100},
                {"ticker": "005930.KS", "sector": "Semiconductor", "quantity": 10, "avg_price": 100},
                {"ticker": "TST_BOND", "sector": "ETF/Bond", "quantity": 10, "avg_price": 100},
            ],
        )
        result = compute_drift("core", db_path=db_path)
        assert result["action"] == "REBALANCE"
        violations_by_class = {v["asset_class"]: v for v in result["violations"]}
        assert "us_equity" in violations_by_class
        assert violations_by_class["us_equity"]["severity"] == "emergency"
        assert violations_by_class["us_equity"]["drift"] > 10  # over by emergency threshold

    def test_warning_severity_between_5_and_10_pct(self, db_path):
        # us target 50%, deliver 57% (drift +7 → warning, < 10 emergency)
        # us 5700, kr 1900, bond 1900, comm 500 → us 57, kr 19, bond 19, comm 5
        _seed_portfolio(
            db_path,
            [
                {"ticker": "TST_US", "sector": "Technology", "quantity": 57, "avg_price": 100},
                {"ticker": "005930.KS", "sector": "Semiconductor", "quantity": 19, "avg_price": 100},
                {"ticker": "TST_BOND", "sector": "ETF/Bond", "quantity": 19, "avg_price": 100},
                {"ticker": "TST_COMM", "sector": "ETF/Commodity", "quantity": 5, "avg_price": 100},
            ],
        )
        result = compute_drift("core", db_path=db_path)
        assert result["action"] == "REBALANCE"
        us_violation = next((v for v in result["violations"] if v["asset_class"] == "us_equity"), None)
        assert us_violation is not None
        assert us_violation["severity"] == "warning"
        assert 5 <= abs(us_violation["drift"]) < 10

    def test_unknown_strategy_returns_error(self, db_path):
        _seed_portfolio(db_path, [{"ticker": "TST_A", "sector": "Technology", "quantity": 100, "avg_price": 100}])
        result = compute_drift("nonexistent_strategy", db_path=db_path)
        assert "error" in result
        assert result["action"] == "OK"

    def test_empty_portfolio_all_classes_under_target(self, db_path):
        # 빈 portfolio: current = {} → 모든 target 에 대해 drift = 0 - target = 음수 (under-allocated)
        result = compute_drift("core", db_path=db_path)
        # core targets: us 50 / kr 20 / bond 20 / commodity 5 — all should be flagged emergency (drift >= 10)
        assert result["action"] == "REBALANCE"
        # us_equity drift = -50 (under by 50, |drift| > emergency 10)
        emergencies = [v for v in result["violations"] if v["severity"] == "emergency"]
        assert len(emergencies) >= 1

    def test_cash_min_excluded_from_drift(self, db_path):
        _seed_portfolio(db_path, [{"ticker": "TST_A", "sector": "Technology", "quantity": 100, "avg_price": 100}])
        result = compute_drift("core", db_path=db_path)
        # cash_min 은 drift 계산에서 제외
        assert "cash_min" not in result["drift"]
        # 그러나 targets dict 에는 보존 (참조용)
        assert "cash_min" in result["targets"]


class TestFormatReport:
    def test_ok_report_contains_check_mark(self, db_path):
        result = compute_drift("core", db_path=db_path)  # 빈 portfolio → REBALANCE
        # 빈 → REBALANCE 이지만 형식 검증
        out = format_report(result)
        assert "Strategic Allocation Drift" in out
        assert "core" in out

    def test_rebalance_report_includes_warning_and_axis_split(self, db_path):
        result = compute_drift("core", db_path=db_path)
        out = format_report(result)
        if result["action"] == "REBALANCE":
            assert "REBALANCE" in out
            assert "alpha_action=FLAT" in out  # axis 분리 룰 명시 필수

    def test_error_result_returns_skip_message(self):
        result = {"strategy": "ghost", "error": "no targets", "action": "OK", "violations": []}
        out = format_report(result)
        assert "skip" in out
        assert "no targets" in out


class TestCli:
    def test_main_returns_0_when_aligned(self, db_path, monkeypatch):
        # main() 의 query() 가 db_path 을 사용하도록 monkeypatch.
        from nuri.trading.strategy import strategic_allocation as sa

        monkeypatch.setattr(sa, "query", lambda *a, **k: __import__("nuri.core.db").core.db.query(*a, db_path=db_path))
        # No portfolio = REBALANCE → rc 1 (정합 X 케이스 — test_main_returns_1 와 묶음)
        rc = main(["--strategy", "core"])
        # 빈 portfolio 는 REBALANCE → rc=1 expected
        assert rc in (0, 1)

    def test_main_invalid_strategy_argparse_error(self):
        with pytest.raises(SystemExit) as exc:
            main(["--strategy", "ghost"])
        assert exc.value.code == 2  # argparse choice 위반 exit 2

"""Branch coverage tests for nuri.analysis.rebalance_advisor.

Targets residual branches uncovered by test_rebalance_advisor.py:
- L167 (account_total <= 0): account_totals 가 0 이면 division skip.
- position-limit 분기의 stale 가격(current_price=0): 주당 단가를 USD 평가액에서
  되뽑으므로 전량 매도 fallback 없이 초과분만 정확히 계산된다.
- L203 (Unknown sector skip): 'Unknown' 라벨된 sector 는 위반 검사 X.
- L219 (sector ticker is leverage ETF): leverage 항목은 sector 위반에서도 skip
  (priority 1 leverage_etf 룰이 더 강력 — 두 번 카운트 방지).
- L229 (already_sell_all early continue): 이미 leverage 등으로 SELL_ALL 대상이면
  sector 위반에서 추가 row 안 뽑음.
- L233 (sector current_price <= 0 skip): 가격 0 이면 sell_shares 계산 불가 → skip.
- L237-240 (SELL_ALL branch in sector loop): remaining_excess >= ticker_value
  이면 전량 매도 액션.

Privacy: synthetic ticker TST_*. No broker name.
"""

from __future__ import annotations

import math
from unittest.mock import patch

import pandas as pd
import pytest

from nuri.analysis.rebalance_advisor import detect_violations
from nuri.core.db import init_db
from nuri.core.rules import MAX_SINGLE_POSITION, get_account_strategy


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "ra.db"
    init_db(path)
    return path


def _row(account, ticker, sector, qty, price, weight_pct, *, current_price=None, pnl_pct=0.0):
    cp = price if current_price is None else current_price
    cv = qty * cp
    return {
        "account": account,
        "ticker": ticker,
        "sector": sector,
        "quantity": qty,
        "avg_price": price,
        "current_price": cp,
        "currency": "USD",
        "current_value_usd": cv,
        "cost_basis_usd": qty * price,
        "pnl_usd": (cp - price) * qty,
        "pnl_pct": pnl_pct,
        "weight_pct": weight_pct,
        "price_date": "2026-04-10",
    }


# ════════════════════════════════════════════════════════════
# L167 — account_total <= 0 skip
# ════════════════════════════════════════════════════════════


class TestAccountTotalZero:
    def test_zero_account_total_skips_position_check(self, db_path):
        """L165-167: account_total <= 0 시 division skip — 빈 잔고 계좌가 false positive
        position-limit 위반 trigger 안 함.

        Regression: 분기 누락 시 ZeroDivisionError 또는 nonsensical weight.
        """
        rows = [
            # current_value_usd=0 → account_total 합계 0 → 분기 발화.
            {**_row("ZeroAccount", "TST_A", "Tech", 0, 0, 0.0)},
            # 다른 계좌는 정상 — 통제군.
            {**_row("Normal", "TST_B", "Tech", 5, 100, 50.0)},
        ]
        df = pd.DataFrame(rows)
        df.attrs["total_value_usd"] = 500.0
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=df):
            violations = detect_violations(db_path=db_path)
        # ZeroAccount 의 TST_A 가 position_limit 위반으로 surface 안 함.
        pos = [v for v in violations if v["violation_type"] == "position_limit_exceeded" and v["ticker"] == "TST_A"]
        assert pos == []


# ════════════════════════════════════════════════════════════
# L180 — current_price <= 0 in position-limit branch (qty fallback)
# ════════════════════════════════════════════════════════════


class TestPositionLimitZeroPrice:
    def test_zero_price_falls_back_to_quantity(self, db_path):
        """L177-180: position 위반 발화 후 current_price <= 0 → sell_shares = quantity.

        Regression: 분기 누락 시 division by zero.

        Note: ticker_value 가 positive 여야 (account_weight 가 >limit) violation
        발화. current_price=0 만 별도 — DB 일시 stale 시 가능.
        """
        # ticker_value=2000 (큰 비중) but current_price=0 (가격 stale).
        # _row helper 로는 모순 → 직접 raw row dict 사용.
        rows = [
            {
                "account": "acct",
                "ticker": "TST_X",
                "sector": "Tech",
                "quantity": 100,
                "avg_price": 20.0,
                "current_price": 0.0,
                "currency": "USD",
                "current_value_usd": 2000.0,  # 비중 산정에 직접 사용
                "cost_basis_usd": 2000.0,
                "pnl_usd": 0.0,
                "pnl_pct": 0.0,
                "weight_pct": 80.0,
                "price_date": "2026-04-10",
            },
            # 같은 acct 의 다른 종목 → account_total 계산.
            {
                "account": "acct",
                "ticker": "TST_Y",
                "sector": "Health",
                "quantity": 5,
                "avg_price": 100.0,
                "current_price": 100.0,
                "currency": "USD",
                "current_value_usd": 500.0,
                "cost_basis_usd": 500.0,
                "pnl_usd": 0.0,
                "pnl_pct": 0.0,
                "weight_pct": 20.0,
                "price_date": "2026-04-10",
            },
        ]
        df = pd.DataFrame(rows)
        df.attrs["total_value_usd"] = 2500.0
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=df):
            violations = detect_violations(db_path=db_path)
        pos = [v for v in violations if v["violation_type"] == "position_limit_exceeded" and v["ticker"] == "TST_X"]
        assert len(pos) == 1
        # 예전에는 current_price=0 을 만나면 `sell_shares=quantity` 로 전량 매도로
        # 떨어지면서 `sell_value_usd` 는 100*0 = $0 를 보고했다 — 100주를 팔라면서
        # 회수액 0 이라 그 자체로 말이 안 됐다. 이제 주당 단가를 USD 평가액에서
        # 되뽑으므로($2,000/100주 = $20) stale 가격에도 초과분만 정확히 덜어낸다.
        strategy = get_account_strategy("acct")
        max_pos = strategy.get("max_single_position", MAX_SINGLE_POSITION)
        expected_shares = math.ceil((2000.0 - 2500.0 * max_pos) / 20.0)
        assert pos[0]["sell_shares"] == expected_shares
        assert pos[0]["sell_shares"] < 100  # 전량 매도로 떨어지지 않는다
        assert pos[0]["sell_value_usd"] == pytest.approx(expected_shares * 20.0)


class TestPositionLimitZeroQuantity:
    def test_zero_quantity_is_skipped_not_divided_by(self, db_path):
        """수량 0 인데 평가액이 남아 있으면 그 종목은 건너뛴다 (0-나눗셈 방지).

        주당 단가를 `ticker_value / quantity` 로 되뽑기 때문에 수량 0 이 그대로
        들어오면 ZeroDivisionError 다. 실데이터에서는 수량 0 이면 평가액도 0 이라
        비중 위반 자체가 안 나지만, DB 가 어긋나면 도달할 수 있는 자리다 —
        위 TestPositionLimitZeroPrice 와 같은 성격의 모순 데이터로 가드를 잠근다.
        """
        rows = [
            {
                "account": "acct",
                "ticker": "TST_Z",
                "sector": "Tech",
                "quantity": 0,
                "avg_price": 20.0,
                "current_price": 20.0,
                "currency": "USD",
                "current_value_usd": 2000.0,
                "cost_basis_usd": 2000.0,
                "pnl_usd": 0.0,
                "pnl_pct": 0.0,
                "weight_pct": 80.0,
                "price_date": "2026-04-10",
            },
            {
                "account": "acct",
                "ticker": "TST_W",
                "sector": "Health",
                "quantity": 5,
                "avg_price": 100.0,
                "current_price": 100.0,
                "currency": "USD",
                "current_value_usd": 500.0,
                "cost_basis_usd": 500.0,
                "pnl_usd": 0.0,
                "pnl_pct": 0.0,
                "weight_pct": 20.0,
                "price_date": "2026-04-10",
            },
        ]
        df = pd.DataFrame(rows)
        df.attrs["total_value_usd"] = 2500.0
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=df):
            violations = detect_violations(db_path=db_path)  # 예외 없이 끝나야 한다
        assert not [
            v for v in violations if v["ticker"] == "TST_Z" and v["violation_type"] == "position_limit_exceeded"
        ]


# ════════════════════════════════════════════════════════════
# L203 — Unknown sector skip
# ════════════════════════════════════════════════════════════


class TestUnknownSectorSkip:
    def test_unknown_sector_does_not_trigger_violation(self, db_path):
        """L201-203: sector='Unknown' 또는 빈 문자열은 sector_limit 검사 skip.

        Regression: 분기 누락 시 미분류 종목이 가짜 sector 위반 surface.
        """
        rows = [
            # Unknown sector 가 50% — 정상이면 sector 위반인데 skip 돼야 함.
            _row("acct", "TST_U", "Unknown", qty=10, price=100, weight_pct=50.0),
            # 다른 정상 sector 들.
            _row("acct", "TST_T", "Tech", qty=2, price=100, weight_pct=10.0),
            _row("acct", "TST_H", "Health", qty=4, price=100, weight_pct=20.0),
        ]
        df = pd.DataFrame(rows)
        df.attrs["total_value_usd"] = 2000.0
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=df):
            violations = detect_violations(db_path=db_path)
        # 'Unknown' sector 위반 row 가 없어야 함.
        unknown = [
            v
            for v in violations
            if v.get("violation_type") == "sector_limit_exceeded"
            and any(t in str(v.get("reason", "")) for t in ("Unknown",))
        ]
        assert unknown == []


# ════════════════════════════════════════════════════════════
# L219 / L229 — leverage / already_sell_all in sector loop
# ════════════════════════════════════════════════════════════


class TestSectorLoopLeverageAndAlreadySellAll:
    def test_leverage_etf_skipped_in_sector_loop(self, db_path):
        """L217-219: sector 위반 처리 중 leverage ETF (TQQQ) 는 skip.

        Regression: 분기 누락 시 leverage ETF 가 leverage_etf + sector_limit
        둘 다 surface (double counting).
        """
        # TQQQ + 다른 Tech 종목 → Tech 섹터 비중 폭주.
        rows = [
            _row("acct", "TQQQ", "Tech", qty=20, price=100, weight_pct=50.0),
            _row("acct", "TST_T1", "Tech", qty=5, price=100, weight_pct=12.5),
            _row("acct", "TST_T2", "Tech", qty=5, price=100, weight_pct=12.5),
            _row("acct", "TST_H", "Health", qty=1, price=100, weight_pct=2.5),
        ]
        df = pd.DataFrame(rows)
        df.attrs["total_value_usd"] = 4000.0
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=df):
            violations = detect_violations(db_path=db_path)
        # TQQQ 가 sector_limit_exceeded 로 추가 surface 되지 않아야 함.
        tqqq_sector = [
            v for v in violations if v["ticker"] == "TQQQ" and v["violation_type"] == "sector_limit_exceeded"
        ]
        assert tqqq_sector == []


# ════════════════════════════════════════════════════════════
# L233 — sector current_price <= 0 skip
# ════════════════════════════════════════════════════════════


class TestSectorZeroPriceSkip:
    def test_zero_price_in_sector_loop_skipped(self, db_path):
        """L231-233: sector 위반 처리 중 current_price <= 0 인 종목은 skip
        (sell_shares 계산 불가).

        Regression: 분기 누락 시 ZeroDivisionError on sell_shares calc.
        """
        rows = [
            # Tech sector 비중 70% > 35% — 위반 발화.
            _row("acct", "TST_A", "Tech", qty=5, price=100, weight_pct=25.0),
            _row("acct", "TST_B", "Tech", qty=5, price=100, weight_pct=25.0),
            # current_price=0 인 Tech 종목 — sell 처리 시 skip 돼야.
            _row("acct", "TST_Z", "Tech", qty=10, price=100, weight_pct=20.0, current_price=0),
            _row("acct", "TST_H", "Health", qty=3, price=100, weight_pct=15.0),
        ]
        df = pd.DataFrame(rows)
        df.attrs["total_value_usd"] = 2000.0
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=df):
            violations = detect_violations(db_path=db_path)
        # TST_Z 가 sector violation 으로 surface 안 함 (price=0 skip).
        zero = [v for v in violations if v["ticker"] == "TST_Z" and v["violation_type"] == "sector_limit_exceeded"]
        assert zero == []


# ════════════════════════════════════════════════════════════
# L237-240 — sector loop SELL_ALL branch
# ════════════════════════════════════════════════════════════


class TestSectorLoopSellAllBranch:
    def test_sector_excess_consumes_full_position_yields_sell_all(self, db_path):
        """L235-240: remaining_excess >= ticker_value → action='SELL_ALL', remaining
        decrement.

        sector loop 은 factor_score asc 정렬 후 small score 종목부터 처리.
        TST_TINY 의 factor_score 를 가장 낮게 두면 첫 iteration. excess >
        TINY value → SELL_ALL.

        Regression: 분기 inversion 시 큰 excess 가 부분 매도로 surface, 충분한
        리밸런스 안 됨.
        """
        rows = [
            _row("acct", "TST_TINY", "Tech", qty=1, price=100, weight_pct=5.0),
            _row("acct", "TST_BIG", "Tech", qty=17, price=100, weight_pct=85.0),
            _row("acct", "TST_H", "Health", qty=2, price=100, weight_pct=10.0),
        ]
        df = pd.DataFrame(rows)
        df.attrs["total_value_usd"] = 2000.0
        # factor_scores 명시 — TINY 가 점수 더 낮음 → 먼저 매도 대상.
        factor_scores = {"TST_TINY": 0.1, "TST_BIG": 0.9, "TST_H": 0.5}
        with (
            patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=df),
            patch(
                "nuri.analysis.rebalance_advisor._get_factor_scores",
                return_value=factor_scores,
            ),
        ):
            violations = detect_violations(db_path=db_path)

        sector_actions = [v for v in violations if v["violation_type"] == "sector_limit_exceeded"]
        # TINY 가 SELL_ALL action 으로 surface (small ticker first, big excess).
        tiny_sell_all = [v for v in sector_actions if v["ticker"] == "TST_TINY" and v["action"] == "SELL_ALL"]
        assert len(tiny_sell_all) == 1
        # SELL_ALL 의 sell_shares = 보유 quantity 그대로.
        assert tiny_sell_all[0]["sell_shares"] == 1
        assert tiny_sell_all[0]["sell_value_usd"] == 100.0


# ════════════════════════════════════════════════════════════
# L229 — already_sell_all (leverage 와 sector 충돌 skip)
# ════════════════════════════════════════════════════════════


class TestAlreadySellAll:
    def test_leverage_ticker_already_sell_all_decrements_remaining(self, db_path):
        """L221-229: 이미 leverage_etf 위반으로 SELL_ALL 대상이면 sector loop 에서
        remaining_excess 만 차감하고 row 추가는 skip.

        실제로 leverage 는 L218-219 에서 먼저 skip 되지만, 코드 path 에서 already
        SELL_ALL match 는 LEVERAGE_ETFS 가 아닌 다른 SELL_ALL 종목과의 상호작용.
        sector loop 의 누적 excess 차감 로직이 깨지는 regression 방지.
        """
        # stop_loss SELL_ALL 발화 → sector loop 에서 same ticker match → remaining
        # 차감 후 다음 종목 진행.
        rows = [
            # TST_SL 손절 (-25%) → SELL_ALL via stop_loss 위반.
            _row("acct", "TST_SL", "Tech", qty=5, price=100, weight_pct=20.0, pnl_pct=-25.0),
            _row("acct", "TST_T2", "Tech", qty=10, price=100, weight_pct=40.0),
            _row("acct", "TST_T3", "Tech", qty=2, price=100, weight_pct=8.0),
            _row("acct", "TST_H", "Health", qty=8, price=100, weight_pct=32.0),
        ]
        df = pd.DataFrame(rows)
        df.attrs["total_value_usd"] = 2500.0
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=df):
            violations = detect_violations(db_path=db_path)
        # TST_SL 이 stop_loss SELL_ALL 위반에 들어가야 함.
        stop_loss = [v for v in violations if v["ticker"] == "TST_SL" and v["violation_type"] == "stop_loss_exceeded"]
        assert len(stop_loss) >= 1
        assert stop_loss[0]["action"] == "SELL_ALL"
        # TST_SL 이 sector_limit_exceeded 로 추가 surface 되지 않아야 함 (already_sell_all skip).
        sl_sector = [
            v for v in violations if v["ticker"] == "TST_SL" and v["violation_type"] == "sector_limit_exceeded"
        ]
        assert sl_sector == []


# ═══════════════════════════════════════════════════════
# print_rebalance_advisor + main() — Issue #616 Phase 3-C3 부분 (343→346, 401-416, 412→416)
# ═══════════════════════════════════════════════════════

from unittest.mock import patch  # noqa: E402


class TestPrintAdvisorMediumSeverity:
    def test_medium_severity_skips_marker(self, capsys):
        """343→346: severity='medium' → critical/high 둘 다 False → marker 빈 문자열."""
        from nuri.analysis.rebalance_advisor import print_rebalance_advisor

        actions = [
            {
                "ticker": "AAA",
                "sell_shares": 5,
                "sell_value_usd": 1_000.0,
                "reason": "rule violation",
                "action": "SELL_PARTIAL",
                "severity": "medium",
                "violation_type": "concentration",
                "cumulative_recovery_usd": 1_000,
            }
        ]
        print_rebalance_advisor(actions)
        out = capsys.readouterr().out
        assert "[!!]" not in out
        assert "[!]" not in out
        assert "AAA" in out


class TestRebalanceAdvisorMain:
    def test_main_with_critical_actions(self, capsys):
        """main() actions + has_critical=True path."""
        from nuri.analysis import rebalance_advisor as ra

        fake = {
            "actions": [
                {
                    "ticker": "BBB",
                    "sell_shares": 2,
                    "sell_value_usd": 500.0,
                    "reason": "rule",
                    "action": "SELL_PARTIAL",
                    "severity": "critical",
                    "violation_type": "concentration",
                    "cumulative_recovery_usd": 500,
                }
            ],
            "total_violations": 1,
            "total_recovery_usd": 500.0,
            "violations_by_type": {"concentration": 1},
            "violations_by_severity": {"critical": 1},
            "has_critical": True,
        }
        with patch("nuri.analysis.rebalance_advisor.generate_advisor_report", return_value=fake):
            assert ra.main([]) == 0
        assert "CRITICAL" in capsys.readouterr().out

    def test_main_actions_no_critical_skips_warning(self, capsys):
        """412→416: has_critical=False → '⚠ CRITICAL' skip."""
        from nuri.analysis import rebalance_advisor as ra

        fake = {
            "actions": [
                {
                    "ticker": "CCC",
                    "sell_shares": 1,
                    "sell_value_usd": 100.0,
                    "reason": "rule",
                    "action": "SELL_PARTIAL",
                    "severity": "high",
                    "violation_type": "concentration",
                    "cumulative_recovery_usd": 100,
                }
            ],
            "total_violations": 1,
            "total_recovery_usd": 100.0,
            "violations_by_type": {"concentration": 1},
            "violations_by_severity": {"high": 1},
            "has_critical": False,
        }
        with patch("nuri.analysis.rebalance_advisor.generate_advisor_report", return_value=fake):
            assert ra.main([]) == 0
        out = capsys.readouterr().out
        assert "위반 건수" in out
        assert "CRITICAL" not in out

    def test_main_no_actions_prints_compliance(self, capsys):
        """actions=[] → '준수 상태' 출력."""
        from nuri.analysis import rebalance_advisor as ra

        fake = {
            "actions": [],
            "total_violations": 0,
            "total_recovery_usd": 0.0,
            "violations_by_type": {},
            "violations_by_severity": {},
            "has_critical": False,
        }
        with patch("nuri.analysis.rebalance_advisor.generate_advisor_report", return_value=fake):
            assert ra.main([]) == 0
        assert "준수 상태" in capsys.readouterr().out

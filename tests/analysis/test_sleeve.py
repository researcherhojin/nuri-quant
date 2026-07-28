"""§3.11 실험 슬리브 소속·사용률 (#834).

핵심은 **소속 판별**이다. 티커가 BUY 추천에 등장했다는 사실만으로 슬리브로 보면
기존 보유가 통째로 오분류된다 — 실측(2026-07-28) 상 사전등록일 이후 BUY 추천 종목이
전부 이미 보유 중이었고, 다수는 측정 모드보다 한참 앞서 열린 포지션이었다. 사용률이
허구가 되고 그 숫자가 신규 매수를 차단하므로, 오분류는 조용한 오작동이다.

합성 티커 TST_* + placeholder 계좌만 (privacy — `tests/CLAUDE.md`).
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from nuri.analysis import sleeve
from nuri.core.db import get_db, init_db

DECLARED = "2026-07-08"


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "sleeve.db"
    init_db(path)
    return path


def _seed(db_path, *, holdings, buy_recs):
    """holdings: [(account, ticker, first_buy_date)] · buy_recs: [(ticker, date)]"""
    with get_db(db_path) as conn:
        for account, ticker, fbd in holdings:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, first_buy_date) "
                "VALUES (?, ?, 10, 100.0, 'USD', ?)",
                (account, ticker, fbd),
            )
        for i, (ticker, date) in enumerate(buy_recs, start=1):
            conn.execute(
                "INSERT INTO recommendations (id, date, ticker, action) VALUES (?, ?, ?, 'BUY')",
                (i, date, ticker),
            )
            conn.execute(
                "INSERT INTO agent_decisions "
                "(decision_id, ticker, as_of_date, action, conviction, inputs_json, rationale_json, status) "
                "VALUES (?, ?, ?, 'BUY', 50, '{}', '{}', 'emitted')",
                (f"rec_{i}", ticker, date),
            )


class TestSleeveCaps:
    def test_caps_come_from_rules_yaml_only(self):
        """상한의 canonical 소스는 rules.yaml 뿐 — 하드코딩 금지 (§3.11 lock)."""
        caps = sleeve.sleeve_caps()
        assert set(caps) >= {"core", "active", "swing", "long_term", "pension"}
        assert caps["pension"] == 0, "연금은 실험 슬리브 대상이 아니다"
        assert caps["long_term"] == 0


class TestMembership:
    def test_preexisting_holding_is_not_sleeve_even_if_recommended(self, db_path):
        """**핵심 회귀** — 측정 모드 이전부터 보유한 종목은 BUY 추천이 있어도 슬리브가 아니다.

        Gotcha-Test Pair: `first_buy_date >= declared_date` 조건을 빼면 이 테스트가 FAIL.
        실측상 그 조건이 없으면 보유 20건 중 10건이 슬리브로 잡힌다.
        """
        _seed(
            db_path,
            holdings=[("Brokerage Alpha", "TST_A", "2025-01-15")],  # 측정 모드보다 한참 앞섬
            buy_recs=[("TST_A", "2026-07-20")],
        )
        assert sleeve.sleeve_members(db_path=db_path) == set()

    def test_new_position_with_recommendation_is_sleeve(self, db_path):
        _seed(
            db_path,
            holdings=[("Brokerage Alpha", "TST_B", "2026-07-20")],
            buy_recs=[("TST_B", "2026-07-15")],
        )
        assert sleeve.sleeve_members(db_path=db_path) == {("Brokerage Alpha", "TST_B")}

    def test_new_position_without_recommendation_is_not_sleeve(self, db_path):
        """추천 없이 산 종목은 시스템 자본이 아니다 — 사용자 재량 매수."""
        _seed(db_path, holdings=[("Brokerage Alpha", "TST_C", "2026-07-20")], buy_recs=[])
        assert sleeve.sleeve_members(db_path=db_path) == set()

    def test_recommendation_before_declared_date_does_not_qualify(self, db_path):
        """사전등록일 이전 추천은 판정 창 밖이다."""
        _seed(
            db_path,
            holdings=[("Brokerage Alpha", "TST_D", "2026-07-20")],
            buy_recs=[("TST_D", "2026-06-01")],
        )
        assert sleeve.sleeve_members(db_path=db_path) == set()


class TestUtilization:
    def _fake_portfolio(self, rows):
        return pd.DataFrame(rows)

    def test_over_cap_is_flagged_without_any_sell_action(self, db_path):
        """상한 초과는 `over=True` 로만 표면화된다 — SELL/청산 필드가 없어야 한다 (#429 축).

        Gotcha-Test Pair: 초과를 alpha 신호로 승격시키면 이 테스트가 FAIL.
        """
        _seed(
            db_path,
            holdings=[("Brokerage Alpha", "TST_B", "2026-07-20")],
            buy_recs=[("TST_B", "2026-07-15")],
        )
        df = self._fake_portfolio(
            [
                {"account": "Brokerage Alpha", "ticker": "TST_B", "current_value_usd": 5000.0},
                {"account": "Brokerage Alpha", "ticker": "TST_A", "current_value_usd": 5000.0},
            ]
        )
        with (
            patch("nuri.analysis.portfolio.analyze_portfolio", return_value=df),
            patch("nuri.core.rules.get_account_strategy_name", return_value="core"),  # cap 10%
        ):
            rows = sleeve.sleeve_utilization(db_path=db_path)

        assert len(rows) == 1
        r = rows[0]
        assert r["used_pct"] == 50.0, "5000/10000"
        assert r["over"] is True, "cap 10% 를 초과했는데 미표시"
        for forbidden in ("action", "sell_shares", "sell_value_usd", "alpha_action"):
            assert forbidden not in r, f"슬리브 초과가 alpha/매도 필드({forbidden})를 노출하면 안 된다"

    def test_empty_sleeve_reports_zero_not_missing(self, db_path):
        """슬리브가 비면 0% 로 보고한다 — 행 자체가 사라지면 대시보드가 침묵한다."""
        _seed(db_path, holdings=[("Brokerage Alpha", "TST_A", "2025-01-15")], buy_recs=[])
        df = self._fake_portfolio([{"account": "Brokerage Alpha", "ticker": "TST_A", "current_value_usd": 1000.0}])
        with (
            patch("nuri.analysis.portfolio.analyze_portfolio", return_value=df),
            patch("nuri.core.rules.get_account_strategy_name", return_value="core"),
        ):
            rows = sleeve.sleeve_utilization(db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["used_pct"] == 0.0
        assert rows[0]["over"] is False

    def test_strategy_without_cap_is_skipped(self, db_path):
        """상한이 정의되지 않은 전략은 판정 대상이 아니다."""
        df = self._fake_portfolio([{"account": "misc", "ticker": "X", "current_value_usd": 100.0}])
        with (
            patch("nuri.analysis.portfolio.analyze_portfolio", return_value=df),
            patch("nuri.core.rules.get_account_strategy_name", return_value="__undefined__"),
        ):
            assert sleeve.sleeve_utilization(db_path=db_path) == []


class TestHeadroom:
    def test_headroom_is_cap_minus_used(self, db_path):
        _seed(db_path, holdings=[("Brokerage Alpha", "TST_B", "2026-07-20")], buy_recs=[("TST_B", "2026-07-15")])
        df = pd.DataFrame(
            [
                {"account": "Brokerage Alpha", "ticker": "TST_B", "current_value_usd": 500.0},
                {"account": "Brokerage Alpha", "ticker": "TST_A", "current_value_usd": 9500.0},
            ]
        )
        with (
            patch("nuri.analysis.portfolio.analyze_portfolio", return_value=df),
            patch("nuri.core.rules.get_account_strategy_name", return_value="core"),  # 10% of 10000 = 1000
        ):
            assert sleeve.sleeve_headroom("Brokerage Alpha", db_path=db_path) == 500.0

    def test_unknown_account_has_no_limit(self, db_path):
        df = pd.DataFrame([{"account": "Brokerage Alpha", "ticker": "X", "current_value_usd": 100.0}])
        with (
            patch("nuri.analysis.portfolio.analyze_portfolio", return_value=df),
            patch("nuri.core.rules.get_account_strategy_name", return_value="core"),
        ):
            assert sleeve.sleeve_headroom("Brokerage Beta", db_path=db_path) is None


class TestDegenerateInputs:
    def test_empty_portfolio_yields_no_rows(self, db_path):
        """빈 포트폴리오(CI · 신규 설치)는 예외가 아니라 빈 결과다 — 게이트가 조용히 통과."""
        with patch("nuri.analysis.portfolio.analyze_portfolio", return_value=pd.DataFrame()):
            assert sleeve.sleeve_utilization(db_path=db_path) == []
            assert sleeve.sleeve_headroom("Brokerage Alpha", db_path=db_path) is None

    def test_zero_equity_account_is_skipped_not_divided_by_zero(self, db_path):
        df = pd.DataFrame([{"account": "Brokerage Alpha", "ticker": "X", "current_value_usd": 0.0}])
        with (
            patch("nuri.analysis.portfolio.analyze_portfolio", return_value=df),
            patch("nuri.core.rules.get_account_strategy_name", return_value="core"),
        ):
            assert sleeve.sleeve_utilization(db_path=db_path) == []

    def test_missing_measurement_mode_block_is_loud(self):
        """§3.11 블록이 사라지면 조용히 상한 없음으로 통과하지 않고 즉시 터진다.

        Gotcha-Test Pair: `raise` 를 `return {}` 로 바꾸면 상한이 사라져 FAIL.
        """
        with patch.dict("nuri.core.rules.RULES", {"measurement_mode": {}}, clear=False):
            with pytest.raises(RuntimeError, match="measurement_mode"):
                sleeve.sleeve_caps()

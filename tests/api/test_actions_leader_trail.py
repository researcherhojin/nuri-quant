"""Lock-tests for leader-trail wiring in /api/actions (#679 → codecov patch 100%).

- `_build_actions`: leader_trail_triggered 종목에 '⭐ 리더 N일선 이탈' reason 부여.
- `_get_targets_status`: check_leader_trail_signals 예외 시 안전 폴백 (빈 set).
"""

from unittest.mock import patch


def _invoke_build_actions(*, recommendations, siege_violations, portfolio_map, targets_status=None):
    """_build_actions 를 mock 된 helper 로 실행 (TestPRABucketRouting 패턴 재사용)."""
    from nuri.api.routes import actions as actions_mod

    with (
        patch.object(actions_mod, "_get_recommendations", return_value=recommendations),
        patch.object(actions_mod, "_get_siege_violations", return_value=siege_violations),
        patch.object(actions_mod, "_get_targets_status", return_value=targets_status or {}),
        patch.object(actions_mod, "_get_portfolio_map", return_value=portfolio_map),
        patch.object(actions_mod, "_get_short_interest", return_value=None),
        patch.object(actions_mod, "has_recent_catalyst", return_value=(False, "no data")),
        patch.object(actions_mod, "check_divergence", return_value=(False, 0.0, None)),
    ):
        return actions_mod._build_actions()


class TestLeaderTrailWiring:
    def test_leader_trail_triggered_adds_reason(self):
        """리더 50일선 이탈 종목은 '리더 … 이탈' reason 으로 청산 검토 surface."""
        result = _invoke_build_actions(
            recommendations=[
                {
                    "ticker": "GRW",
                    "action": "HOLD",
                    "confidence": 62,
                    "agreement": 90,
                    "scoring_detail": None,
                    "agent_verdicts": None,
                    "alpha_action": None,
                    "portfolio_action": None,
                }
            ],
            siege_violations=[],
            portfolio_map={
                "GRW": {
                    "current_price": 130.0,
                    "avg_price": 100.0,
                    "quantity": 10,
                    "pnl_pct": 30.0,
                    "position_pct": 5.0,
                    "account": "Main",
                }
            },
            targets_status={
                "GRW": {
                    "is_leader": True,
                    "leader_trail_triggered": True,
                    "target_1": None,
                    "target_2": None,
                    "stop_loss": 93.0,
                    "trailing_stop_pct": -15,
                }
            },
        )
        all_items = result["urgent"] + result["check"] + result["hold"] + result["portfolio"]
        grw = next(i for i in all_items if i["ticker"] == "GRW")
        assert any("리더" in r and "이탈" in r for r in grw["reasons"])


class TestGetTargetsStatusLeaderTrailException:
    @patch("nuri.trading.recommend.price_targets.calculate_portfolio_targets", return_value=[])
    @patch("nuri.trading.recommend.price_targets.check_leader_trail_signals", side_effect=Exception("boom"))
    def test_leader_trail_exception_falls_back(self, _mock_lt, _mock_cpt):
        """check_leader_trail_signals 가 터져도 _get_targets_status 는 폴백 (크래시 없음)."""
        from nuri.api.routes.actions import _get_targets_status

        assert _get_targets_status() == {}

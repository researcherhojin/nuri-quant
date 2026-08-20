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
                ("GRW", "Main"): {
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


class TestAnUnmatchableKeyIsNeverBuilt:
    """계좌를 모르는 타겟 행은 dict 에 넣지 않는다 (#1121).

    키는 `(ticker, account_label)` 이고 소비자(`_build_actions`)는 항상 라벨 **문자열**로
    조회한다. 그런데 생산자는 `labels.get(row.get("account"), row.get("account"))` 였고,
    account 가 없으면 그게 None 을 돌려줘 `(ticker, None)` 키가 만들어졌다. 그 키는
    어떤 조회와도 안 맞으므로 그 타겟은 들어가 있으면서 영영 안 읽힌다 — 없는 것보다
    나쁜 상태다(dict 크기는 늘어서 "있다"고 보인다).

    Pylance 가 이 자리를 `tuple[Unknown, str | None]` vs `tuple[str, str]` 로 잡아냈다.
    타입 오류가 가리키던 게 실제 도달 가능한 결함이었다.
    """

    @patch("nuri.trading.recommend.price_targets.check_leader_trail_signals", return_value=[])
    def test_a_target_row_without_an_account_is_skipped(self, _mock_lt):
        from nuri.api.routes import actions as actions_mod

        rows = [
            {"ticker": "AAAA", "account": "main", "stop_loss": 1.0},
            {"ticker": "BBBB", "stop_loss": 2.0},          # account 키 자체가 없다
            {"ticker": "CCCC", "account": None, "stop_loss": 3.0},
            {"ticker": "DDDD", "account": "", "stop_loss": 4.0},
        ]
        with (
            patch("nuri.trading.recommend.price_targets.calculate_portfolio_targets", return_value=rows),
            # `_get_account_labels` 는 `_get_targets_status` **안에서** import 된다 —
            # actions 모듈에 패치하면 아무 효과가 없다. 원본 모듈을 패치해야 한다.
            patch("nuri.api.routes.dashboard._get_account_labels", return_value={"main": "Main"}),
        ):
            targets = actions_mod._get_targets_status()

        assert list(targets) == [("AAAA", "Main")], f"맞출 수 없는 키가 들어갔다: {list(targets)}"
        assert all(isinstance(a, str) and isinstance(b, str) for a, b in targets)

    @patch("nuri.api.routes.dashboard._get_account_labels", return_value={"main": "Main"})
    def test_both_collections_key_on_the_same_label(self, _mock_labels):
        """타겟과 리더-트레일이 **같은 키 규약**을 쓴다 — 한쪽만 바꾸면 매칭이 끊긴다.

        `leader_trail_triggered` 는 `key in _leader_trail` 로 정해진다. 한쪽이 라벨
        (`Main`)을, 다른 쪽이 원 계좌명(`main`)을 쓰면 두 집합이 영영 안 만나 이 플래그가
        항상 False 가 된다 — 값이 있는데 늘 꺼져 있는, 이번 주 내내 고친 그 모양이다.

        앞의 테스트(account 없는 행 skip)만으로는 이 축이 안 잡힌다: account 가 없는 행은
        옛 방식에서도 매칭 불가라 결과가 같기 때문이다. 그래서 account 가 **있는** 행으로
        규약 일치를 본다.
        """
        from nuri.api.routes import actions as actions_mod

        with (
            patch(
                "nuri.trading.recommend.price_targets.calculate_portfolio_targets",
                return_value=[{"ticker": "AAAA", "account": "main", "stop_loss": 1.0}],
            ),
            patch(
                "nuri.trading.recommend.price_targets.check_leader_trail_signals",
                return_value=[{"ticker": "AAAA", "account": "main"}],
            ),
        ):
            targets = actions_mod._get_targets_status()

        assert ("AAAA", "Main") in targets, f"라벨 규약이 갈라졌다: {list(targets)}"
        assert targets[("AAAA", "Main")]["leader_trail_triggered"] is True, (
            "두 집합이 같은 키를 만들지 못해 리더-트레일 플래그가 켜지지 않았다"
        )

"""Lock-test for /api/targets leader-trail exception fallback (#679 → codecov patch 100%).

check_leader_trail_signals 가 예외를 던져도 get_portfolio_targets 는 빈 시그널로 폴백.
"""

from unittest.mock import patch


@patch("nuri.trading.recommend.price_targets.calculate_portfolio_targets", return_value=[])
@patch("nuri.trading.recommend.price_targets.check_trailing_stop_signals", return_value=[])
@patch("nuri.trading.recommend.price_targets.check_take_profit_signals", return_value=[])
@patch("nuri.trading.recommend.price_targets.check_leader_trail_signals", side_effect=Exception("boom"))
def test_leader_trail_exception_falls_back(_mock_lt, _mock_tp, _mock_ts, _mock_cpt):
    from nuri.api.routes.targets import get_portfolio_targets

    result = get_portfolio_targets()
    assert result["targets"] == []
    assert result["count"] == 0

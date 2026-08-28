"""환율이 없을 때 API 가 **통화 혼합 합계를 지어내지 않는다** (#1284).

## 무엇이 잘못됐었나

#1283 이 Python 4곳의 `or 1400` 을 걷었지만, 응답 형태가 바뀌는 4곳은 프론트와 같이
움직여야 해서 남겨 뒀다 — `actions.py` 비중%, `dashboard.py` 의 계좌 평가액·현금 합계,
그리고 `page.tsx` 의 `d.exchange_rate || 1400`. 마지막 것이 특히 나빴다: 백엔드가
`exchange_rate: null` 로 부재를 **정직하게** 알려주는데 프론트가 그 신호를 버리고
헤드라인 총액을 지어냈다.

## 핵심 규칙 — 분모가 미상이면 비율도 미상이다

총 자산·계좌별 평가액·비중%·자산배분은 전부 "원화 자산 + 달러 자산" 을 분모로 쓴다.
원화 보유가 하나라도 있고 환율이 없으면 **그 합계 전체가 미상**이고, 따라서 달러
종목의 비중조차 말할 수 없다. 부분합을 분모로 쓰면 남은 종목 비중이 조용히 부풀려진다.

반대로 **환산이 필요 없는 것은 그대로 정확하다** — 달러 전용 계좌, 원화 현금이 없는
계좌, 원화 보유가 전혀 없는 포트폴리오. 그래서 아래 테스트마다 대조군이 붙는다.
"""

import pytest

from nuri.core.db import get_db, upsert_macro

# 합성 종목 — 실제 보유와 무관하다 (public repo, `tests/CLAUDE.md` privacy).
KR_TICKER = "999999.KS"
KQ_TICKER = "888888.KQ"
KR_BY_CURRENCY = "YYYY"
US_TICKER = "ZZZZ"


def _seed(db_path, ticker, qty, price, currency, account="acct_a"):
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?,?,?,?,?)",
            (account, ticker, qty, price, currency),
        )
        conn.execute(
            "INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close) VALUES (?,?,?,?,?,?,?,?)",
            (ticker, "2026-08-29", price, price, price, price, 1000, price),
        )


def _rate(value=1380.0):
    upsert_macro([{"indicator": "usd_krw", "date": "2026-08-29", "value": value, "source": "test"}])


class TestFxAvailabilityRule:
    """`cross_currency_unavailable` — 규칙이 한 곳에 있어야 소비자마다 갈리지 않는다."""

    def test_rate_present_is_always_available(self):
        from nuri.core.fx import cross_currency_unavailable

        assert cross_currency_unavailable(1380.0, True) is None
        assert cross_currency_unavailable(1380.0, False) is None

    def test_no_rate_without_krw_exposure_is_fine(self):
        """대조군 — 원화 자산이 없으면 환율은 애초에 필요 없다."""
        from nuri.core.fx import cross_currency_unavailable

        assert cross_currency_unavailable(None, False) is None

    def test_no_rate_with_krw_exposure_is_unavailable(self):
        from nuri.core.fx import cross_currency_unavailable

        reason = cross_currency_unavailable(None, True)
        assert reason and "USD/KRW" in reason, "사유 없이 미상만 내면 결함처럼 보인다"

    @pytest.mark.parametrize(
        ("ticker", "currency", "expected"),
        [
            (KR_TICKER, "KRW", True),
            (KQ_TICKER, "KRW", True),
            (KR_BY_CURRENCY, "KRW", True),  # 접미사 없이 통화만 KRW
            (KR_TICKER, "USD", True),  # 통화가 틀려도 접미사가 KR
            (US_TICKER, "USD", False),
        ],
    )
    def test_krw_holding_predicate(self, ticker, currency, expected):
        """정본 술어 — 접미사 **또는** 통화. 한쪽만 보면 절반을 놓친다 (#1283 codex P1)."""
        from nuri.core.fx import is_krw_holding

        assert is_krw_holding(ticker, currency) is expected


class TestDashboardAccountValues:
    def test_krw_account_is_unknown_without_a_rate(self, db_path, monkeypatch):
        """Mutation lock: `or 1400` 을 되살리면 숫자가 나와 FAIL."""
        import nuri.api.routes.dashboard as dash

        monkeypatch.setattr(dash, "_get_account_labels", lambda: {"acct_a": "Brokerage Alpha"})
        _seed(db_path, KR_TICKER, 10, 100_000.0, "KRW")
        result = dash._get_account_values(exchange_rate=None)
        assert result[0]["value"] is None

    def test_usd_account_stays_exact_without_a_rate(self, db_path, monkeypatch):
        """대조군 — 환산이 필요 없는 계좌까지 지우면 알 수 있는 것을 버리는 것이다."""
        import nuri.api.routes.dashboard as dash

        monkeypatch.setattr(dash, "_get_account_labels", lambda: {"acct_b": "Brokerage Beta"})
        _seed(db_path, US_TICKER, 10, 250.0, "USD", account="acct_b")
        result = dash._get_account_values(exchange_rate=None)
        assert result[0]["value"] == 2500.0

    def test_currency_only_krw_is_also_unknown(self, db_path, monkeypatch):
        """접미사가 없어도 통화가 KRW 면 환산 대상이다 (#1283 codex P1 과 같은 축)."""
        import nuri.api.routes.dashboard as dash

        monkeypatch.setattr(dash, "_get_account_labels", lambda: {"acct_a": "Brokerage Alpha"})
        _seed(db_path, KR_BY_CURRENCY, 10, 100_000.0, "KRW")
        result = dash._get_account_values(exchange_rate=None)
        assert result[0]["value"] is None, "통화만 KRW 인 보유를 달러로 오분류했다"

    def test_rate_present_computes_as_before(self, db_path, monkeypatch):
        """대조군 — 환율이 있으면 예전과 같은 숫자."""
        import nuri.api.routes.dashboard as dash

        monkeypatch.setattr(dash, "_get_account_labels", lambda: {"acct_a": "Brokerage Alpha"})
        _seed(db_path, KR_TICKER, 10, 138_000.0, "KRW")
        result = dash._get_account_values(exchange_rate=1380.0)
        assert result[0]["value"] == 1000.0


class TestAllocationRefusesUnknownInputs:
    def test_unknown_account_value_blocks_allocation(self):
        """Mutation lock: `None` 을 0 으로 접으면 배분이 나와 FAIL."""
        from nuri.api.routes.dashboard import _compute_actual_allocation

        assert _compute_actual_allocation([{"value": None}], 5000) is None

    def test_unknown_cash_blocks_allocation(self):
        from nuri.api.routes.dashboard import _compute_actual_allocation

        assert _compute_actual_allocation([{"value": 10000}], None) is None

    def test_known_inputs_still_compute(self):
        """대조군 — 전부 알면 예전과 같다."""
        from nuri.api.routes.dashboard import _compute_actual_allocation

        assert _compute_actual_allocation([{"value": 10000}], 0) == {
            "long": 100,
            "short": 0,
            "cash": 0,
        }


class TestDashboardSurfacesTheReason:
    def test_reason_is_present_when_conversion_is_blocked(self, db_path, monkeypatch):
        """`exchange_rate: null` 만으로는 부족하다 — 프론트가 그 신호를 버렸다."""
        import nuri.api.routes.dashboard as dash

        monkeypatch.setattr(dash, "_get_account_labels", lambda: {"acct_a": "Brokerage Alpha"})
        _seed(db_path, KR_TICKER, 10, 100_000.0, "KRW")
        result = dash._build_dashboard()
        assert result["exchange_rate"] is None
        assert result["fx_unavailable"], "값을 못 냈는데 이유를 말하지 않는다"
        assert result["actual_allocation"] is None

    def test_no_reason_when_rate_is_present(self, db_path, monkeypatch):
        """대조군 — 정상일 때 사유가 뜨면 그 사유는 곧 무시된다 (false-red)."""
        import nuri.api.routes.dashboard as dash

        monkeypatch.setattr(dash, "_get_account_labels", lambda: {"acct_a": "Brokerage Alpha"})
        _rate()
        _seed(db_path, KR_TICKER, 10, 138_000.0, "KRW")
        result = dash._build_dashboard()
        assert result["fx_unavailable"] is None


class TestActionWeightsShareOneDenominator:
    """비중%의 분모는 **포트폴리오 전체**라, 원화 하나가 미상이면 전부 미상이다."""

    def test_us_weight_is_unknown_when_a_krw_position_cannot_convert(self, db_path, monkeypatch):
        """가장 놓치기 쉬운 축 — 달러 종목은 정확한데 **비중은 말할 수 없다**.

        Mutation lock: `weights_unavailable` 를 무시하고 부분합을 분모로 쓰면,
        US 종목이 100% 라는 거짓 비중이 나와 FAIL.
        """
        import nuri.api.routes.actions as act

        monkeypatch.setattr(act, "_get_real_accounts", lambda: set())
        _seed(db_path, KR_TICKER, 10, 100_000.0, "KRW")
        _seed(db_path, US_TICKER, 10, 250.0, "USD")

        holdings = act._get_portfolio_map()
        assert holdings[US_TICKER]["position_pct"] is None, (
            "환율 없이 달러 종목 비중을 냈다 — 분모(전체 자산)를 모르는데 비율을 주장했다"
        )
        assert holdings[KR_TICKER]["position_pct"] is None

    def test_us_only_portfolio_keeps_exact_weights(self, db_path, monkeypatch):
        """대조군 — 원화가 없으면 환율과 무관하게 비중이 정확하다."""
        import nuri.api.routes.actions as act

        monkeypatch.setattr(act, "_get_real_accounts", lambda: set())
        _seed(db_path, US_TICKER, 10, 250.0, "USD")
        _seed(db_path, "WWWW", 10, 250.0, "USD")

        holdings = act._get_portfolio_map()
        assert holdings[US_TICKER]["position_pct"] == pytest.approx(50.0)

    def test_weights_computed_when_rate_present(self, db_path, monkeypatch):
        """대조군 — 환율이 있으면 예전과 같이 계산된다."""
        import nuri.api.routes.actions as act

        monkeypatch.setattr(act, "_get_real_accounts", lambda: set())
        _rate()
        _seed(db_path, KR_TICKER, 10, 138_000.0, "KRW")  # = 1000 USD
        _seed(db_path, US_TICKER, 4, 250.0, "USD")  # = 1000 USD

        holdings = act._get_portfolio_map()
        assert holdings[US_TICKER]["position_pct"] == pytest.approx(50.0)

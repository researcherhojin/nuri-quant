"""ExecutionFirewall 이 받는 포트폴리오 스냅샷 (#1107).

## 왜 이 파일이 있나

`execution_blocks` 는 도입 이래 프로덕션 **0행**이다. firewall 이 안 불려서가 아니라
**산술적으로 아무것도 못 막는 상태**였기 때문이다: 유일한 빌더가

    SELECT ticker, qty, current_price FROM holdings WHERE qty > 0

를 조회했는데 **`holdings` 테이블은 존재하지 않는다** (실제는 `portfolio`, 컬럼도
`quantity`/`avg_price` 이고 `current_price` 는 없다). 예외가 `except Exception` 에 삼켜져
`total_value=100_000, positions={}` 라는 허구가 흘렀고, 빈 포트폴리오를 상대로는
집중도·섹터·현금 게이트가 전부 통과한다.

**틀린 숫자가 아니라 그럴듯한 숫자라 화면 어디도 이상해 보이지 않았다.**
그래서 이 파일은 형태가 아니라 **판정 결과**를 잠근다 — 허구였다면 통과했을 매수가
실제 상태에서는 막히는지.
"""

from __future__ import annotations

import pandas as pd
import pytest
import yaml

from nuri.analysis.portfolio import portfolio_state
from nuri.core.db import get_db, init_db, upsert_prices
from nuri.core.timezone import today_kst


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _seed(db_path, rows, prices, rate: float = 1400.0):
    with get_db(db_path) as conn:
        # 환율이 없으면 `get_exchange_rate` 가 StaleExchangeRateError 를 던진다 — 의도된
        # 가드다(낡은 환율로 KR 종목을 환산하느니 크게 실패한다). 픽스처가 그걸 채운다.
        conn.execute(
            "INSERT INTO macro (indicator, date, value) VALUES ('usd_krw', ?, ?)",
            (today_kst(), rate),
        )
        conn.executemany(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
            "VALUES (:account, :ticker, :quantity, :avg_price, :currency, :sector)",
            rows,
        )
    d = today_kst()
    upsert_prices(
        pd.DataFrame(
            [
                {
                    "ticker": t,
                    "date": d,
                    "open": c,
                    "high": c,
                    "low": c,
                    "close": c,
                    "volume": 1000,
                    "adj_close": c,
                }
                for t, c in prices.items()
            ]
        ),
        db_path=db_path,
    )


def _decision_id(db_path=None) -> str:
    """`execution_blocks.decision_id` 는 `agent_decisions` 를 참조하는 FK 다 —
    없는 id 로 부르면 게이트 판정이 아니라 IntegrityError 가 난다 (실제로 밟았다)."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO agent_decisions "
            "(decision_id, ticker, as_of_date, action, conviction, inputs_json, rationale_json, status) "
            "VALUES ('probe-decision', 'ZZZZ', ?, 'BUY', 50.0, '{}', '{}', 'emitted')",
            (today_kst(),),
        )
    return "probe-decision"


def _cash_yaml(tmp_path, accounts):
    p = tmp_path / "portfolio.yaml"
    p.write_text(yaml.safe_dump({"accounts": accounts}), encoding="utf-8")
    return p


class TestItReadsTheTableThatExists:
    def test_positions_come_from_the_portfolio_table(self, db_path, tmp_path):
        """`holdings` 가 아니라 `portfolio` 를 읽는다 — 그 오타 하나가 게이트를 넉 달 무력화했다."""
        _seed(
            db_path,
            [
                {
                    "account": "A",
                    "ticker": "AAAA",
                    "quantity": 10,
                    "avg_price": 90.0,
                    "currency": "USD",
                    "sector": "Tech",
                }
            ],
            {"AAAA": 100.0},
        )

        st = portfolio_state(db_path=db_path, config_path=_cash_yaml(tmp_path, {}))

        assert st["positions"] == {"AAAA": {"value": 1000.0, "sector": "Tech"}}
        assert st["total_value"] == 1000.0

    def test_an_empty_portfolio_is_not_papered_over_with_a_default(self, db_path, tmp_path):
        """빈 포트폴리오는 `total_value=0` 이지 `100_000` 이 아니다.

        옛 빌더는 조회가 실패하면 10만 달러를 지어냈다. 그 값에 비하면 어떤 매수도
        작아 보여 집중도 게이트가 영원히 통과한다.
        """
        _seed(db_path, [], {})

        st = portfolio_state(db_path=db_path, config_path=_cash_yaml(tmp_path, {}))

        assert st["total_value"] == 0.0
        assert st["positions"] == {}


class TestNormalization:
    def test_multi_account_same_ticker_is_summed(self, db_path, tmp_path):
        """firewall 의 position_limit 은 **종목** 단위다 — 계좌별로 쪼개 보면 캡이 헐거워진다."""
        _seed(
            db_path,
            [
                {
                    "account": "A",
                    "ticker": "AAAA",
                    "quantity": 10,
                    "avg_price": 1.0,
                    "currency": "USD",
                    "sector": "Tech",
                },
                {
                    "account": "B",
                    "ticker": "AAAA",
                    "quantity": 5,
                    "avg_price": 1.0,
                    "currency": "USD",
                    "sector": "Tech",
                },
            ],
            {"AAAA": 100.0},
        )

        st = portfolio_state(db_path=db_path, config_path=_cash_yaml(tmp_path, {}))

        assert st["positions"]["AAAA"]["value"] == 1500.0

    def test_korean_tickers_are_converted_to_usd(self, db_path, tmp_path):
        """`.KS` 는 계좌 통화와 무관하게 KRW 다 (#764). 환산 없이 더하면 KR 종목이
        포트폴리오를 통째로 지배해 모든 게이트가 무의미해진다."""
        _seed(
            db_path,
            [
                {
                    "account": "A",
                    "ticker": "005930.KS",
                    "quantity": 10,
                    "avg_price": 50000.0,
                    "currency": "KRW",
                    "sector": "Tech",
                }
            ],
            {"005930.KS": 70000.0},
        )

        st = portfolio_state(db_path=db_path, config_path=_cash_yaml(tmp_path, {}))

        # 700,000 KRW → USD. 정확한 환율은 DB 에 따라 다르므로 자릿수만 본다.
        assert 100.0 < st["positions"]["005930.KS"]["value"] < 10_000.0


class TestCash:
    def test_cash_sums_usd_and_krw_across_accounts(self, db_path, tmp_path):
        _seed(db_path, [], {})
        cfg = _cash_yaml(tmp_path, {"A": {"cash_usd": 1000.0}, "B": {"cash_usd": 500.0, "cash_krw": 1_400_000.0}})

        st = portfolio_state(db_path=db_path, config_path=cfg)

        assert st["cash"] > 1500.0, "KRW 현금이 누락됐다"

    def test_unreadable_cash_becomes_zero_not_generous(self, db_path, tmp_path):
        """현금을 못 읽으면 0 이다.

        `cash_reserve` / `leverage_cap` 게이트가 이 값을 쓴다 — 모르는 현금을 넉넉하다고
        가정하면 두 게이트가 있으나 마나가 된다. 보수적으로 발화하는 쪽이 맞다.
        """
        _seed(db_path, [], {})

        st = portfolio_state(db_path=db_path, config_path=tmp_path / "does-not-exist.yaml")

        assert st["cash"] == 0.0

    def test_a_missing_exchange_rate_raises_instead_of_guessing(self, db_path, tmp_path):
        """환율이 없으면 예외 — 조용히 잘못된 통화로 합산하느니 크게 실패한다.

        옛 빌더는 `except Exception` 으로 전부 삼켜 허구를 흘렸다. 이 경로가 다시
        삼키게 되면 KR 종목이 원화 액면으로 더해져 포트폴리오를 통째로 지배한다.
        """
        from nuri.analysis.portfolio import StaleExchangeRateError

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES ('A', 'AAAA', 1, 1.0, 'USD', 'Tech')"
            )

        with pytest.raises(StaleExchangeRateError):
            portfolio_state(db_path=db_path, config_path=_cash_yaml(tmp_path, {}))


class TestTheFirewallActuallyBlocksNow:
    """이 클래스가 이 PR 의 이유다 — 형태가 아니라 **판정**을 잠근다.

    ⚠️ `ExecutionFirewall.run()` 은 `db_path` 를 안 받고 **전역 DB** 에 쓴다. conftest 의
    autouse 픽스처가 그걸 이미 per-test 복사본으로 격리하므로 이 클래스는 db_path 를
    넘기지 않는다. 둘을 섞으면 결정은 픽스처 DB 에, 차단 기록은 전역 DB 에 앉아
    `execution_blocks.decision_id` FK 가 깨진다 (실제로 밟았다).
    """

    def _state(self, tmp_path):
        _seed(
            None,
            [
                {
                    "account": "A",
                    "ticker": "AAAA",
                    "quantity": 100,
                    "avg_price": 90.0,
                    "currency": "USD",
                    "sector": "Tech",
                }
            ],
            {"AAAA": 100.0},
        )
        return portfolio_state(config_path=_cash_yaml(tmp_path, {"A": {"cash_usd": 5000.0}}))

    #: 판정이 갈리는 규모 (실측). 허구 상태는 **$10,000 까지 전부 통과**시키고 $20,000 에서야
    #: `position_cap` 하나로 막는다 — 총액 10만을 지어냈으니 당연하다. 실 상태(총 1만)는
    #: $500 부터 막는다. 3,000 은 그 사이 어디든 되지만, 실 상태에서 게이트 4개가 모두
    #: 발화하는 지점이라 대비가 가장 선명하다.
    PROPOSED = 3_000.0

    def _check(self, state):
        from nuri.agents.actors.execution_firewall import ExecutionFirewall

        return ExecutionFirewall().run(
            {
                "action": "check",
                "decision_id": _decision_id(),
                "ticker": "ZZZZ",
                "trade_action": "BUY",
                "proposed_position_value": self.PROPOSED,
                "sector": "Tech",
                "portfolio_state": state,
            }
        )

    def test_an_oversized_buy_is_blocked_on_the_real_state(self, tmp_path):
        """총 1만 달러 포트폴리오에 3천 달러 매수 → 게이트 4개 발화."""
        st = self._state(tmp_path)
        assert st["total_value"] == 10_000.0

        result = self._check(st)

        assert result.outcome.value == "block", f"실 상태에서 과대 매수가 통과했다: {result.output}"
        fired = {b.get("type") for b in (result.output.get("blocks") or [])}
        # 이 둘은 **실 포지션이 있어야** 발화한다 — 허구의 `positions={}` 에서는 계산 자체가 안 된다.
        assert {"position_cap", "sector_concentration"} <= fired, fired

    def test_the_old_fiction_would_have_let_it_through(self, tmp_path):
        """카나리아 — 허구 상태(`total_value=100_000, positions={}`)에서는 같은 매수가 통과한다.

        이 대비가 없으면 위 테스트가 "firewall 이 원래 잘 막는다" 를 재확인할 뿐이고,
        빌더 수정이 무엇을 바꿨는지 증명하지 못한다.
        """
        self._state(tmp_path)  # 결정 FK 와 환율만 필요 — 상태는 허구를 쓴다
        fiction = {"total_value": 100_000.0, "cash": 50_000.0, "positions": {}, "vix": 15.0}

        result = self._check(fiction)

        assert result.outcome.value != "block", (
            "허구 상태에서도 막혔다 — 이 카나리아의 전제가 깨졌으니 위 테스트의 의미를 재확인할 것"
        )

    def test_a_block_leaves_a_row_in_the_ledger(self, tmp_path):
        """`execution_blocks` 는 도입 이래 프로덕션 0행이었다 — 행이 생기는지가 살아있음 증명이다."""
        from nuri.core.db import query

        self._check(self._state(tmp_path))

        assert query("SELECT COUNT(*) AS c FROM execution_blocks")[0]["c"] > 0

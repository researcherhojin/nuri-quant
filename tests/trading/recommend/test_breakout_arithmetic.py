"""돌파는 **직전** 고점 대비다 (#1100 결함 A).

## 왜 이 파일이 있나

`high_30d = max(closes[-30:])` 는 **오늘 종가를 포함**한다. 자기를 포함한 max 와 자기를
비교하므로 `breakout_pct` 가 **양수가 될 수학적 가능성이 없다**. 프로덕션 실측(2026-08-18):
753종목 중 양수 **0건**, max 정확히 `0.0000`.

그 결과 `_score_ticker` 의

    if bo >= 0: breakout_pct = min(100.0, 70.0 + bo * 10.0)

이 **오직 70.0 만** 반환했다 — 70~100 구간이 통째로 dead range 이고, 0.20 가중치의 최대
기여가 20 이 아니라 14 였다. 이게 BUY 임계 70 을 도달 불가로 만든 세 원인 중 하나다
(천장 산술 23.4 + 25.0 + 7.5 + 14.0 = 69.9 < 70, 관측 max 69.3, 후보 0건).

**틀린 값이 아니라 "항상 같은 값"이라 화면 어디도 이상해 보이지 않았다.** 그래서 회귀는
분포가 아니라 **양수가 나올 수 있는가**로 잠근다.
"""

from __future__ import annotations

import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_prices
from nuri.core.timezone import today_kst
from nuri.trading.recommend.buy_candidate_emitter import _get_price_signals, _score_ticker

WEIGHTS = {"factor_composite": 0.40, "momentum_5d": 0.25, "technical_rsi": 0.15, "breakout_30d": 0.20}


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _seed(db_path, ticker: str, closes: list[float]):
    """마지막 봉이 오늘이 되도록 앵커링 — 리터럴 날짜는 이 레포에서 두 번 터졌다."""
    dates = pd.bdate_range(end=today_kst(), periods=len(closes)).strftime("%Y-%m-%d")
    upsert_prices(
        pd.DataFrame(
            [
                {
                    "ticker": ticker,
                    "date": d,
                    "open": c,
                    "high": c,
                    "low": c,
                    "close": c,
                    "volume": 1000,
                    "adj_close": c,
                }
                for d, c in zip(dates, closes)
            ]
        ),
        db_path=db_path,
    )


class TestBreakoutCanBePositive:
    def test_a_new_high_reads_as_a_positive_breakout(self, db_path):
        """오늘이 직전 30봉 고점을 넘으면 양수여야 한다 — 고치기 전에는 산술적으로 불가능했다."""
        _seed(db_path, "AAAA", [100.0] * 34 + [110.0])

        got = _get_price_signals(db_path=db_path)["AAAA"]

        assert got["breakout_pct"] == pytest.approx(10.0), "직전 고점 100 대비 110 = +10%"

    def test_the_dead_score_range_is_now_reachable(self, db_path):
        """70~100 구간이 실행된다 — 이 단언이 dead range 였는지를 직접 본다."""
        _seed(db_path, "BBBB", [100.0] * 34 + [110.0])
        price = _get_price_signals(db_path=db_path)["BBBB"]

        _, sources = _score_ticker("BBBB", {"composite": 0.5}, price, None, WEIGHTS)

        assert sources["breakout"] > 70.0, "돌파 점수가 여전히 70 상한에 붙어 있다"

    def test_sitting_at_the_prior_high_is_exactly_flat(self, db_path):
        """경계 — 직전 고점과 같으면 0. 양수로 새면 돌파가 아닌 것도 돌파가 된다."""
        _seed(db_path, "CCCC", [100.0] * 35)

        assert _get_price_signals(db_path=db_path)["CCCC"]["breakout_pct"] == pytest.approx(0.0)

    def test_below_the_prior_high_stays_negative(self, db_path):
        """카나리아 — 전부 양수로 만들어 버리는 반대 방향 회귀를 잡는다."""
        _seed(db_path, "DDDD", [100.0] * 34 + [90.0])

        assert _get_price_signals(db_path=db_path)["DDDD"]["breakout_pct"] == pytest.approx(-10.0)

    def test_todays_close_does_not_set_its_own_bar(self, db_path):
        """오늘이 유일한 최고가여도 직전 고점과 비교한다 — 자기참조 회귀의 직접 잠금.

        오늘을 포함한 max 로 되돌리면 이 종목의 breakout 은 0 이 된다.
        """
        _seed(db_path, "EEEE", [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 999.0])

        assert _get_price_signals(db_path=db_path)["EEEE"]["breakout_pct"] > 0


class TestTheRangeStaysDescriptive:
    def test_high_and_low_still_include_today(self, db_path):
        """`high_30d`/`low_30d` 는 30일 **구간 표시**라 오늘을 포함한다 — 돌파 기준만 바뀐다."""
        _seed(db_path, "FFFF", [100.0] * 34 + [110.0])

        got = _get_price_signals(db_path=db_path)["FFFF"]

        assert got["high_30d"] == pytest.approx(110.0)
        assert got["low_30d"] == pytest.approx(100.0)

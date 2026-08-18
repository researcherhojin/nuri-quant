"""RSI 스냅샷은 티커별 최신이다 — 전역 MAX(date) 하루치가 아니라 (#1101 Codex P1).

전역 `MAX(date)` 하루치만 읽으면 **시장이 섞이는 순간 한쪽이 통째로 빠진다**: KR 은 KST
당일, US 는 전일 날짜로 signals 가 갈라지므로 최신 날짜 하나를 고르면 다른 시장 전부가
스냅샷에서 사라진다. universe 확장 직후엔 backfill 날짜 간극 때문에 **751행을 쓰고도
emitter 가 보유분만 읽는** 형태로 재현됐다 — 커버리지를 넓힌 수정이 소비 지점에서
무효가 되는, 이 레포가 반복해 밟은 "배선은 됐는데 도달 못 하는" 모양이다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from nuri.core.db import get_db, init_db
from nuri.core.timezone import kst_now, today_kst
from nuri.trading.recommend.buy_candidate_emitter import _get_rsi_snapshot


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _seed(db_path, ticker: str, days_ago: int, rsi: float | None = 55.0):
    d = (kst_now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO signals (ticker, date, rsi_14) VALUES (?, ?, ?)",
            (ticker, d, rsi),
        )


class TestPerTickerLatest:
    def test_mixed_dates_keep_both_markets(self, db_path):
        """오늘 찍힌 티커와 3일 전 티커가 **둘 다** 스냅샷에 든다.

        전역 MAX(date) 방식으로 되돌리면 3일 전 티커가 빠져 이 테스트가 FAIL 한다 —
        그게 정확히 751행을 쓰고도 보유분만 읽히던 회귀다.
        """
        _seed(db_path, "HELD", 0)
        _seed(db_path, "UNIV", 3)

        got = _get_rsi_snapshot(db_path=db_path)

        assert set(got) == {"HELD", "UNIV"}

    def test_each_ticker_gets_its_own_latest_row(self, db_path):
        """같은 티커의 여러 날짜 중 최신 값을 고른다."""
        _seed(db_path, "AAAA", 3, rsi=40.0)
        _seed(db_path, "AAAA", 1, rsi=62.0)

        assert _get_rsi_snapshot(db_path=db_path)["AAAA"] == pytest.approx(62.0)

    def test_stale_rows_are_dropped_not_served(self, db_path):
        """7일 컷오프 — 상장폐지 종목의 마지막 RSI 가 영원히 남으면 안 된다.

        컷오프가 없으면 낡은 값이 신선한 값과 구분 없이 점수에 들어간다. 없는 값은
        `_score_ticker` 가 중립 50 으로 치므로, 낡은 값보다 없는 값이 낫다.
        """
        _seed(db_path, "DEAD", 10)
        _seed(db_path, "LIVE", 1)

        assert set(_get_rsi_snapshot(db_path=db_path)) == {"LIVE"}

    def test_null_rsi_rows_do_not_shadow_older_values(self, db_path):
        """최신 행의 rsi 가 NULL 이면 그 티커의 직전 non-null 값을 쓴다.

        NULL 행이 GROUP BY 의 최신을 차지하며 값을 가리면, 데이터가 부분 결손인 날마다
        티커가 스냅샷에서 사라진다 — WHERE 가 NULL 을 먼저 걷어내므로 그렇지 않다.
        """
        _seed(db_path, "AAAA", 2, rsi=48.0)
        _seed(db_path, "AAAA", 1, rsi=None)

        assert _get_rsi_snapshot(db_path=db_path)["AAAA"] == pytest.approx(48.0)

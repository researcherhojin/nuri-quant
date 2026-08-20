"""Tests for factors_momentum — split from test_quant_all.py."""

from datetime import timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from nuri.core.timezone import kst_now, today_kst
from tests.quant._helpers import (  # noqa: F401
    _insert_spy_data,
    _insert_spy_data_trend,
    _seed_macro,
    _seed_portfolio,
    _seed_prices,
    _seed_spy_data,
)


class TestMomentum:
    """(from test_factors.py)."""

    def test_compute_with_data(self, factor_data):
        from nuri.quant.factors.momentum import compute_momentum

        result = compute_momentum()
        assert not result.empty
        assert "momentum_score" in result.columns
        for score in result["momentum_score"]:
            assert 0 <= score <= 1

    def test_empty_db(self, db_path_mp):
        from nuri.quant.factors.momentum import compute_momentum

        result = compute_momentum()
        assert result.empty

    def test_with_tickers_filter(self, factor_data):
        from nuri.quant.factors.momentum import compute_momentum

        result = compute_momentum(tickers=["AAPL"])
        assert len(result) <= 1

    def _seed_signals(self, db_path, rows):
        """rows: list of (ticker, date, rsi_14)."""
        with get_db(db_path) as conn:
            conn.executemany("INSERT INTO signals (ticker, date, rsi_14) VALUES (?,?,?)", rows)

    def _seed_bars(self, db_path, ticker, days=30):
        dates = pd.bdate_range(end=kst_now().date(), periods=days)
        with get_db(db_path) as conn:
            conn.executemany(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                [(ticker, d.strftime("%Y-%m-%d"), 100, 101, 99, 100 + i * 0.5, 1000) for i, d in enumerate(dates)],
            )

    def test_a_stale_rsi_is_not_treated_as_the_current_value(self, db_path_mp):
        """`RSI_MAX_AGE_DAYS` 보다 낡은 RSI 는 중립 50 으로 떨어진다 (#1073).

        이전 쿼리는 `ORDER BY date DESC LIMIT 1` 로 **나이 제한 없이** 마지막 행을 집었다.
        `technical` 이 멈춘 종목의 마지막 RSI 가 무기한 현재값 행세를 했고, dev 스냅샷
        실측에서 signals 를 가진 46종목 중 29종목이 7일보다 낡았으며 가장 낡은 값은
        128일 전이었다. RSI 는 모멘텀의 0.3, 모멘텀은 composite 의 0.30 이므로 BUY 점수의
        9% 를 그 값이 만든다.
        """
        from nuri.quant.factors.momentum import compute_momentum

        self._seed_bars(db_path_mp, "STALE")
        old = (kst_now() - timedelta(days=90)).strftime("%Y-%m-%d")
        self._seed_signals(db_path_mp, [("STALE", old, 95.0)])

        df = compute_momentum()

        assert float(df.loc["STALE", "rsi_14"]) == 50, "90일 낡은 RSI 가 현재값으로 쓰였다"

    def test_a_fresh_rsi_is_used(self, db_path_mp):
        """컷오프 안쪽 값은 그대로 쓴다 — 위 테스트가 전부를 50 으로 만드는 걸로 통과하면 안 된다."""
        from nuri.quant.factors.momentum import compute_momentum

        self._seed_bars(db_path_mp, "FRESH")
        recent = (kst_now() - timedelta(days=1)).strftime("%Y-%m-%d")
        self._seed_signals(db_path_mp, [("FRESH", recent, 95.0)])

        df = compute_momentum()

        assert float(df.loc["FRESH", "rsi_14"]) == 95.0

    def test_an_rsi_of_zero_is_an_observation_not_a_missing_value(self, db_path_mp):
        """RSI 0.0 이 중립 50 으로 덮이지 않는다 (#1073).

        이전 코드는 `... if not rows.empty and rows.iloc[0]["rsi_14"] else 50` 였다.
        `bool(0.0) is False` 라 실제 관측값 0 이 조용히 50 으로 바뀐다 — 방향이 정반대인
        값이라, 최악의 과매도 종목이 중립으로 보고된다.
        """
        from nuri.quant.factors.momentum import compute_momentum

        self._seed_bars(db_path_mp, "ZERO")
        recent = (kst_now() - timedelta(days=1)).strftime("%Y-%m-%d")
        self._seed_signals(db_path_mp, [("ZERO", recent, 0.0)])

        df = compute_momentum()

        assert float(df.loc["ZERO", "rsi_14"]) == 0.0, "관측된 RSI 0 이 50 으로 덮였다"

    def test_a_null_rsi_does_not_poison_the_score_with_nan(self, db_path_mp):
        """NULL rsi_14 가 NaN 으로 점수에 전파되지 않는다 (#1073).

        배치 조회로 바꾸면 컬럼이 float64 가 되어 NULL 이 NaN 이 된다. `bool(nan) is True`
        라 결측 검사를 통과하고, NaN 은 정규화를 거쳐 momentum_score 로, 다시
        composite_score 로 전파돼 NULL 로 저장된다. 단일 행이던 이전 코드는 pandas 가
        객체 `None` 을 주는 덕에 **우연히** 안전했다 — 그 우연에 기대지 않는다.
        """
        from nuri.quant.factors.momentum import compute_momentum

        recent = (kst_now() - timedelta(days=1)).strftime("%Y-%m-%d")
        for t in ("NULLRSI", "OTHER"):
            self._seed_bars(db_path_mp, t)
        self._seed_signals(db_path_mp, [("NULLRSI", recent, None), ("OTHER", recent, 60.0)])

        df = compute_momentum()

        assert float(df.loc["NULLRSI", "rsi_14"]) == 50
        assert not bool(df["momentum_score"].isna().any()), "NaN 이 momentum_score 로 전파됐다"

    def test_rsi_is_read_in_one_query_not_one_per_ticker(self, db_path_mp):
        """N+1 방지 — 티커 수와 무관하게 signals 조회는 1회다 (#1073).

        이전엔 루프 안에서 티커마다 조회했다. 유니버스가 18종목이던 시절엔 안 보였지만
        #1104 이후 채점 대상이 750종목대라 매 실행 750 왕복이 된다.
        """
        import nuri.quant.factors.momentum as mom

        for t in ("A", "B", "C"):
            self._seed_bars(db_path_mp, t)
        recent = (kst_now() - timedelta(days=1)).strftime("%Y-%m-%d")
        self._seed_signals(db_path_mp, [(t, recent, 55.0) for t in ("A", "B", "C")])

        calls = []
        original = mom.query_df

        def counting(sql, *args, **kwargs):
            calls.append(sql)
            return original(sql, *args, **kwargs)

        with patch.object(mom, "query_df", counting):
            mom.compute_momentum()

        signal_queries = [c for c in calls if "signals" in c]
        assert len(signal_queries) == 1, f"signals 를 {len(signal_queries)}회 조회했다"

    def test_insufficient_data(self, db_path_mp):
        prices = pd.DataFrame(
            [
                {
                    "ticker": "SHORT",
                    "date": f"2024-01-{i + 1:02d}",
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "close": 100,
                    "volume": 1000,
                    "adj_close": 100,
                }
                for i in range(5)
            ]
        )
        upsert_prices(prices, db_path_mp)
        from nuri.quant.factors.momentum import compute_momentum

        result = compute_momentum()
        assert "SHORT" not in result.index if not result.empty else True

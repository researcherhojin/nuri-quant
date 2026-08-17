"""Tests for factors_composite — split from test_quant_all.py."""

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


class TestComposite:
    """(from test_factors.py)."""

    def test_weights_sum_to_one(self):
        from nuri.quant.factors.composite import WEIGHTS

        assert abs(sum(WEIGHTS.values()) - 1.0) < 0.001

    def test_compute_with_data(self, factor_data, monkeypatch):
        from nuri.quant.factors import composite as comp_mod

        empty_df = pd.DataFrame()
        monkeypatch.setattr(comp_mod, "compute_value", lambda: empty_df, raising=False)
        monkeypatch.setattr(comp_mod, "compute_quality", lambda: empty_df, raising=False)
        from nuri.quant.factors.momentum import compute_momentum as _cm

        monkeypatch.setattr(comp_mod, "compute_momentum", _cm, raising=False)
        result = comp_mod.compute_composite()
        if not result.empty:
            assert "composite_score" in result.columns
            for score in result["composite_score"]:
                assert 0 <= score <= 1

    def test_compute_manual(self, factor_data):
        from nuri.quant.factors.composite import WEIGHTS

        m, v, q, s = 0.7, 0.5, 0.6, 0.5
        expected = m * WEIGHTS["momentum"] + v * WEIGHTS["value"] + q * WEIGHTS["quality"] + s * WEIGHTS["sentiment"]
        assert 0 < expected < 1

    def test_print_composite_empty(self, capsys):
        from nuri.quant.factors.composite import print_composite

        print_composite(pd.DataFrame())
        output = capsys.readouterr().out
        assert "없습니다" in output

    def test_save_composite_empty_returns_zero(self, db_path_mp):
        from nuri.quant.factors.composite import save_composite

        assert save_composite(pd.DataFrame()) == 0

    def test_save_composite_writes_factors_table(self, db_path_mp):
        """save_composite 가 factors 테이블에 INSERT OR REPLACE — idempotent."""
        from nuri.core.db import get_db
        from nuri.quant.factors.composite import save_composite

        df = pd.DataFrame(
            [
                {
                    "momentum_score": 0.7,
                    "value_score": 0.5,
                    "quality_score": 0.6,
                    "sentiment_score": 0.5,
                    "composite_score": 0.58,
                },
                {
                    "momentum_score": 0.4,
                    "value_score": 0.6,
                    "quality_score": 0.5,
                    "sentiment_score": 0.5,
                    "composite_score": 0.49,
                },
            ],
            index=["AAA", "BBB"],
        )
        df.index.name = "ticker"
        n = save_composite(df)
        assert n == 2

        with get_db(db_path_mp) as conn:
            rows = conn.execute("SELECT ticker, composite_score FROM factors").fetchall()
        assert len(rows) == 2

    def test_print_composite_with_data(self, capsys):
        from nuri.quant.factors.composite import print_composite

        df = pd.DataFrame(
            [
                {
                    "momentum_score": 0.7,
                    "value_score": 0.5,
                    "quality_score": 0.6,
                    "sentiment_score": 0.5,
                    "composite_score": 0.58,
                }
            ],
            index=["AAPL"],
        )
        print_composite(df)
        output = capsys.readouterr().out
        assert "AAPL" in output
        assert "멀티팩터" in output


class TestSentimentIsNotFabricated:
    """센티먼트가 없거나 노후하면 **0.5 로 메우지 않고 성분을 뺀다** (STRATEGY §2.6).

    이전 동작: `fg_score = ... if fg_rows else 0.5`. 0.5 는 중립이라 무해해 보이지만
    실측 0.637 과 비교하면 0-100 스케일 **2.74점** 차이고, `buy_signals.yaml` 의
    `quality_bar.base_threshold: 70` 앞에서 통과 **개수**를 움직인다. 신선도 검사도
    없어 수집기가 죽으면 옛 값이 무기한 현재값 행세를 했다 (VIX 는 #1017 에서 해결).
    """

    def test_renormalized_weights_still_sum_to_one(self):
        """재정규화의 핵심 — 합이 1.0 이어야 다른 날·다른 티커와 비교 가능하다."""
        from nuri.quant.factors.composite import _effective_weights

        w = _effective_weights(None)
        assert w["sentiment"] == 0.0
        assert abs(sum(w.values()) - 1.0) < 1e-9
        # 30/25/25 를 비례 재배분 → 37.5/31.25/31.25
        assert w["momentum"] == pytest.approx(0.375)
        assert w["value"] == pytest.approx(0.3125)
        assert w["quality"] == pytest.approx(0.3125)

    def test_present_sentiment_keeps_the_configured_weights(self):
        """대조군 — 값이 있으면 원래 비중 그대로. 없으면 이 테스트가 공허하다."""
        from nuri.quant.factors.composite import WEIGHTS, _effective_weights

        assert _effective_weights(0.63) is WEIGHTS

    def test_missing_row_yields_none_not_a_number(self, tmp_path, monkeypatch):
        """행이 없으면 `None`. 0.5 로 되돌리면 FAIL.

        Gotcha-Test Pair: `_market_sentiment` 을 `else 0.5` 로 되돌리면 FAIL.
        """
        import nuri.core.db as db_mod
        from nuri.quant.factors import composite as comp

        path = tmp_path / "s.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        assert comp._market_sentiment() is None

    def test_stale_row_is_treated_as_unknown(self, tmp_path, monkeypatch):
        """`sentiment_max_age_business_days` 를 넘긴 값은 현재값이 아니다.

        Gotcha-Test Pair: `_market_sentiment` 의 age 검사를 지우면 0.42 가 읽혀 FAIL.
        """
        import nuri.core.db as db_mod
        from nuri.quant.factors import composite as comp

        path = tmp_path / "s.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        stale = str(np.busday_offset(today_kst(), -(comp.SENTIMENT_MAX_AGE_BUSINESS_DAYS + 1), roll="backward"))
        upsert_macro([{"indicator": "fear_greed", "date": stale, "value": 42.0, "source": "test"}], path)
        assert comp._market_sentiment() is None

    def test_fresh_row_is_used(self, tmp_path, monkeypatch):
        """경계 — 임계 이내면 유효. 과하게 노후 판정하면 센티먼트가 상시 빠진다."""
        import nuri.core.db as db_mod
        from nuri.quant.factors import composite as comp

        path = tmp_path / "s.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        fresh = str(np.busday_offset(today_kst(), -comp.SENTIMENT_MAX_AGE_BUSINESS_DAYS, roll="backward"))
        upsert_macro([{"indicator": "fear_greed", "date": fresh, "value": 63.7, "source": "test"}], path)
        assert comp._market_sentiment() == pytest.approx(0.637)

    def test_malformed_row_degrades_instead_of_raising(self, tmp_path, monkeypatch):
        """깨진 date 는 상류 데이터 결함 — 팩터 계산 전체를 죽이면 안 된다."""
        import nuri.core.db as db_mod
        from nuri.quant.factors import composite as comp

        path = tmp_path / "s.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        upsert_macro([{"indicator": "fear_greed", "date": "not-a-date", "value": 50.0, "source": "test"}], path)
        assert comp._market_sentiment() is None


class TestFactorDateIsAMarketDate:
    """`factors.date` 는 쓴 날이 아니라 **시장 데이터 날짜**다 (#1071, Codex P1).

    잡은 매일 08:10 KST 에 돈다. `today_kst()` 로 찍으면 주말·휴장에도 금요일 종가로
    계산한 행이 "당일" 라벨을 달고 들어가고, 소비자(`buy_candidate_emitter`)는
    `WHERE date = (SELECT MAX(date) FROM factors)` 로 무조건 그걸 집는다. 그러면
    신선도 정책이 낡음을 잡는 게 아니라 **세탁한다** — 가격 수집이 멈춰도 파생 테이블은
    매일 갱신돼 PASS 로 보이고, 그 사이 가중치 0.40 짜리 입력이 옛 가격으로 점수를 만든다.

    시장일로 찍으면 주말 실행은 같은 행을 덮어쓰기만 하므로(date+ticker UNIQUE) 가짜
    신선도가 안 생기고, `MAX(date)` 는 그대로 최신을 집는다.
    """

    @staticmethod
    def _df():
        df = pd.DataFrame(
            [
                {
                    "momentum_score": 0.7,
                    "value_score": 0.5,
                    "quality_score": 0.6,
                    "sentiment_score": 0.5,
                    "composite_score": 0.58,
                }
            ],
            index=["AAA"],
        )
        df.index.name = "ticker"
        return df

    def test_uses_the_latest_price_date_not_today(self, db_path_mp):
        """Mutation lock: `_market_as_of()` 를 `today_kst()` 로 되돌리면 FAIL."""
        from nuri.core.db import get_db
        from nuri.core.timezone import today_kst
        from nuri.quant.factors.composite import save_composite

        with get_db(db_path_mp) as conn:
            conn.execute("INSERT INTO prices (ticker, date, close) VALUES ('SPY', '2026-08-14', 100)")

        save_composite(self._df())

        with get_db(db_path_mp) as conn:
            dates = [r[0] for r in conn.execute("SELECT DISTINCT date FROM factors").fetchall()]
        assert dates == ["2026-08-14"]
        assert today_kst() not in dates, "쓴 날짜로 찍혔다 — 주말이면 가짜 신선도가 된다"

    def test_repeat_runs_on_the_same_market_date_are_idempotent(self, db_path_mp):
        """주말 이틀 연속 실행이 행을 늘리지 않는다 — 같은 시장일이면 덮어쓴다."""
        from nuri.core.db import get_db
        from nuri.quant.factors.composite import save_composite

        with get_db(db_path_mp) as conn:
            conn.execute("INSERT INTO prices (ticker, date, close) VALUES ('SPY', '2026-08-14', 100)")

        save_composite(self._df())
        save_composite(self._df())

        with get_db(db_path_mp) as conn:
            assert conn.execute("SELECT COUNT(*) FROM factors").fetchone()[0] == 1

    def test_explicit_as_of_wins(self, db_path_mp):
        """호출자가 명시하면 그걸 쓴다 (백필 경로)."""
        from nuri.core.db import get_db
        from nuri.quant.factors.composite import save_composite

        with get_db(db_path_mp) as conn:
            conn.execute("INSERT INTO prices (ticker, date, close) VALUES ('SPY', '2026-08-14', 100)")

        save_composite(self._df(), as_of="2026-01-02")

        with get_db(db_path_mp) as conn:
            assert [r[0] for r in conn.execute("SELECT DISTINCT date FROM factors").fetchall()] == ["2026-01-02"]

    def test_falls_back_to_today_when_no_prices(self, db_path_mp):
        """가격이 하나도 없으면 오늘로 떨어진다 — 계산이 비어 여기 도달하지 않지만 방어."""
        from nuri.core.db import get_db
        from nuri.core.timezone import today_kst
        from nuri.quant.factors.composite import save_composite

        save_composite(self._df())

        with get_db(db_path_mp) as conn:
            assert [r[0] for r in conn.execute("SELECT DISTINCT date FROM factors").fetchall()] == [today_kst()]

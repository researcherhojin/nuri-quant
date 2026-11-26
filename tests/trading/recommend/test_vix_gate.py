"""Regression tests for nuri.trading.recommend.vix_gate.latest_vix."""

from __future__ import annotations

import pandas as pd
import pytest

from nuri.core.db import get_db, init_db
from nuri.core.timezone import today_kst
from nuri.trading.recommend import vix_gate
from nuri.trading.recommend.candidates import _check_vix_gate
from nuri.trading.recommend.vix_gate import latest_vix


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "vix_gate.db"
    init_db(path)
    return path


class TestLatestVixNonFiniteFailSafe:
    """NULL / NaN / Inf VIX 값은 미상(None)으로 처리되어 게이트가 평온으로 열리지 않아야 한다."""

    def test_sql_null_vix_returns_none(self, db_path):
        """macro.value 가 SQL NULL 이면 TypeError 로 죽거나 nan 을 내지 않고 None 을 반환한다."""
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (indicator, date, value, source) VALUES ('vix', ?, NULL, 'test')",
                (today_kst(),),
            )

        assert latest_vix(db_path=db_path) is None

    @pytest.mark.parametrize("sql_expr", ["'nan'", "'inf'", "'-inf'", "9e999", "-9e999"])
    def test_sql_non_finite_vix_returns_none(self, db_path, sql_expr):
        """DB 에 문자열 'nan'/'inf' 또는 IEEE ±Inf 가 들어가도 None 을 반환한다."""
        with get_db(db_path) as conn:
            conn.execute(
                f"INSERT INTO macro (indicator, date, value, source) VALUES ('vix', ?, {sql_expr}, 'test')",
                (today_kst(),),
            )

        assert latest_vix(db_path=db_path) is None

    @pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
    def test_dataframe_non_finite_vix_returns_none(self, monkeypatch, bad_value):
        """query_df 가 float('nan')/float('inf')/-inf 를 돌려줘도 None 을 반환한다."""
        fake_df = pd.DataFrame([{"date": today_kst(), "value": bad_value}])
        monkeypatch.setattr(vix_gate, "query_df", lambda *a, **kw: fake_df)

        assert latest_vix() is None

    @pytest.mark.parametrize("bad_value", [None, float("nan"), float("inf"), float("-inf")])
    def test_candidates_vix_gate_treats_non_finite_as_caution_not_normal(self, monkeypatch, bad_value):
        """하류 _check_vix_gate 가 NULL/NaN/Inf VIX 를 normal(평온)로 통과시키지 않고 caution 으로 강등한다."""
        fake_df = pd.DataFrame([{"date": today_kst(), "value": bad_value}])
        monkeypatch.setattr(vix_gate, "query_df", lambda *a, **kw: fake_df)

        result = _check_vix_gate()
        assert result["gate"] == "caution"
        assert result["vix"] is None

    def test_finite_vix_still_returns_float(self, db_path):
        """정상 유한 VIX 값은 그대로 float 로 반환한다."""
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (indicator, date, value, source) VALUES ('vix', ?, 18.5, 'test')",
                (today_kst(),),
            )

        assert latest_vix(db_path=db_path) == pytest.approx(18.5)

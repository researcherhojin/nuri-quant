# cspell:ignore vmod
"""Tests for factors_value — split from test_quant_all.py."""

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


class TestValue:
    """(from test_factors.py)."""

    def test_empty_when_no_data(self, db_path_mp):
        from nuri.quant.factors.value import compute_value

        result = compute_value(tickers=["FAKE"])
        assert result.empty

    def test_normalization_logic(self):
        scores = {"AAPL": {"pe_ratio": 15.0, "pb_ratio": 2.0}, "MSFT": {"pe_ratio": 30.0, "pb_ratio": 5.0}}
        df = pd.DataFrame(scores).T
        for col in ["pe_ratio", "pb_ratio"]:
            valid = df[col].dropna()
            inverted = 1 / valid.clip(lower=0.01)
            col_min, col_max = inverted.min(), inverted.max()
            if col_max > col_min:
                df[col + "_norm"] = (inverted - col_min) / (col_max - col_min)
            else:
                df[col + "_norm"] = 0.5
        norm_cols = [c for c in df.columns if c.endswith("_norm")]
        df["value_score"] = df[norm_cols].mean(axis=1)
        assert float(df.loc["AAPL", "value_score"]) > float(df.loc["MSFT", "value_score"])


class TestValueDbRead:
    """#349 regression lock-in — compute_value 가 fundamentals 테이블 read 로 동작.

    이전 구현은 `obb.equity.fundamental.ratios` 를 호출 → broken OpenBB 로 silent 0.5 상수.
    """

    def _seed_fundamentals(self, db_path, rows: list[tuple]) -> None:
        """rows: list of (ticker, date, pe_ratio, price_to_book)."""
        from nuri.core.db import get_db

        with get_db(db_path) as conn:
            for ticker, date, pe, pb in rows:
                conn.execute(
                    "INSERT OR REPLACE INTO fundamentals (ticker, date, pe_ratio, price_to_book) VALUES (?, ?, ?, ?)",
                    (ticker, date, pe, pb),
                )

    def test_value_score_non_constant_when_fundamentals_vary(self, db_path_mp):
        """3 티커의 PE/PB 가 다르면 value_score 도 차별화되어야 한다."""
        from nuri.quant.factors.value import compute_value

        self._seed_fundamentals(
            db_path_mp,
            [
                ("AAPL", "2026-04-15", 15.0, 2.0),  # 저평가
                ("MSFT", "2026-04-15", 30.0, 5.0),  # 중간
                ("NVDA", "2026-04-15", 60.0, 10.0),  # 고평가
            ],
        )
        df = compute_value(tickers=["AAPL", "MSFT", "NVDA"])
        assert not df.empty
        assert "value_score" in df.columns
        # 핵심 회귀 방어: score 가 상수화되면 이 assert 가 깨진다
        assert df["value_score"].nunique() > 1, (
            "value_score 가 상수 (이전 0.5 버그 재발) — fundamentals read 로 source 가 되었는지 확인"
        )
        # 낮은 PE/PB = 높은 가치 스코어 (역수 정규화)
        assert float(df.loc["AAPL", "value_score"]) > float(df.loc["MSFT", "value_score"])
        assert float(df.loc["MSFT", "value_score"]) > float(df.loc["NVDA", "value_score"])

    def test_a_loss_maker_is_not_the_cheapest_stock(self, db_path_mp):
        """음수 PE 가 최고 가치 점수를 받지 않는다 (#1102).

        이전 구현은 `1 / valid.clip(lower=0.01)` 이라 **음수 PE 가 0.01 로 클립돼 역수 100**
        = 그 시장의 최댓값이 됐다. 적자기업이 정의상 `pe_ratio_norm == 1.0`, 즉 가장 싼
        종목이 됐고, 실측에서 비양수 PE 25종목이 예외 없이 1.0 이었다.
        적자는 싼 게 아니라 이 척도로 **잴 수 없는 것**이다.
        """
        from nuri.quant.factors.value import compute_value

        self._seed_fundamentals(
            db_path_mp,
            [
                ("CHEAP", "2026-04-15", 8.0, 1.0),
                ("MID", "2026-04-15", 25.0, 3.0),
                ("RICH", "2026-04-15", 60.0, 8.0),
                ("LOSS", "2026-04-15", -30.0, 4.0),  # 적자
            ],
        )
        df = compute_value(tickers=["CHEAP", "MID", "RICH", "LOSS"])

        assert float(df.loc["LOSS", "value_score"]) < float(df.loc["CHEAP", "value_score"]), (
            "적자기업이 실제 저PE 종목보다 싸다고 채점됐다"
        )
        # 비양수 PE 는 컬럼 수준에서 **관측 불가(NaN)** 로 남고, 중립값 0.5 는 평균 직전에
        # 한 번만 대입된다. 그래서 LOSS 의 value_score 는 (중립 + 실제 PB 순위)/2 다.
        assert pd.isna(df.loc["LOSS", "pe_ratio_norm"]), "비양수 PE 가 관측값 행세를 했다"
        assert float(df.loc["LOSS", "value_score"]) == pytest.approx(
            (0.5 + float(df.loc["LOSS", "pb_ratio_norm"])) / 2, abs=1e-4
        )

    def test_one_extreme_outlier_does_not_flatten_everyone_else(self, db_path_mp):
        """극단값 하나가 나머지의 변별력을 지우지 않는다 (#1102).

        min-max 는 양 끝값 2개에 앵커링돼서, 한 종목이 척도를 정하면 나머지가 뭉개진다.
        실측에서 KR `pe_ratio_norm` 은 그렇게 **중앙값 0.00045** 가 됐다 — 값이 틀린 게
        아니라 순위를 만들지 못하는 값이라 화면 어디도 이상해 보이지 않았다.
        백분위는 극단값이 순위 하나만 차지하므로 이 앵커링이 원천적으로 없다.
        """
        from nuri.quant.factors.value import compute_value

        rows = [(f"T{i:02d}", "2026-04-15", 10.0 + i, 1.0 + i * 0.1) for i in range(10)]
        rows.append(("MOON", "2026-04-15", 5000.0, 900.0))  # 극단값
        self._seed_fundamentals(db_path_mp, rows)

        df = compute_value(tickers=[r[0] for r in rows])
        normal = df.drop(index="MOON")["value_score"]

        assert normal.max() - normal.min() > 0.5, (
            f"극단값 하나가 나머지를 압축했다 (spread={normal.max() - normal.min():.4f})"
        )

    def test_the_neutral_fill_sits_at_the_median(self, db_path_mp):
        """미관측에 쓰는 0.5 가 실제로 중앙값이다 (#1102).

        `composite.py` 는 value/quality 가 없는 티커에 0.5 를 채운다. min-max 시절 그 0.5
        는 **92 백분위**여서, 데이터가 없다는 이유만으로 상위 8% 에 앉았다. 백분위 척도에서는
        0.5 가 정의상 중앙값이라 그 대입이 비로소 중립이다.
        """
        from nuri.quant.factors.value import compute_value

        rows = [(f"T{i:02d}", "2026-04-15", 5.0 + i * 3, 0.5 + i * 0.4) for i in range(21)]
        self._seed_fundamentals(db_path_mp, rows)

        df = compute_value(tickers=[r[0] for r in rows])

        assert float(df["value_score"].median()) == pytest.approx(0.5, abs=0.05), (
            f"중앙값이 0.5 가 아니다 ({df['value_score'].median():.4f}) — 0.5 대입이 중립이 아니게 된다"
        )

    def test_kr_included_and_normalized_per_market(self, db_path_mp):
        """#757: KR(.KS) 도 value_score 를 받되 정규화는 시장별로 분리.

        - KR 종목이 차별화된 score 를 받는다 (과거: composite 에서 flat 0.5).
        - US score 는 KR 추가와 무관하게 불변 (시장별 정규화 → cross-market 왜곡 없음).
        - 각 시장 안에서 저PE/PB = 고가치.
        """
        from nuri.quant.factors.value import compute_value

        self._seed_fundamentals(
            db_path_mp,
            [
                ("AAPL", "2026-04-15", 15.0, 2.0),
                ("MSFT", "2026-04-15", 30.0, 5.0),
                ("NVDA", "2026-04-15", 60.0, 10.0),
                ("1111.KS", "2026-04-15", 8.0, 0.8),  # 저PE KR
                ("2222.KS", "2026-04-15", 12.0, 1.2),
                ("3333.KS", "2026-04-15", 20.0, 2.5),  # 고PE KR
            ],
        )
        us = ["AAPL", "MSFT", "NVDA"]
        kr = ["1111.KS", "2222.KS", "3333.KS"]
        df_all = compute_value(tickers=us + kr)
        df_us_only = compute_value(tickers=us)

        # KR 차별화 + 시장 내 저PE=고가치
        assert df_all.loc[kr, "value_score"].nunique() > 1
        assert float(df_all.loc["1111.KS", "value_score"]) > float(df_all.loc["3333.KS", "value_score"])

        # US 불변: KR 을 섞어도 US score 가 그대로 (시장별 정규화 보장)
        for t in us:
            assert float(df_all.loc[t, "value_score"]) == pytest.approx(float(df_us_only.loc[t, "value_score"]))

    def test_normalize_value_columns_skips_absent_column(self):
        """_normalize_value_columns: df 에 없는 컬럼은 건너뛴다 (col in df.columns False 분기)."""
        from nuri.quant.factors.value import _normalize_value_columns

        df = pd.DataFrame({"pe_ratio": [15.0, 30.0]}, index=["A", "B"])  # pb_ratio 없음
        out = _normalize_value_columns(df)
        assert "pe_ratio_norm" in out.columns
        assert "pb_ratio_norm" not in out.columns

    def test_value_reads_latest_date_per_ticker(self, db_path_mp):
        """동일 ticker 여러 날짜 → 가장 최신 row 만 사용."""
        from nuri.quant.factors.value import compute_value

        self._seed_fundamentals(
            db_path_mp,
            [
                ("AAPL", "2026-04-10", 100.0, 20.0),  # old (should be ignored)
                ("AAPL", "2026-04-15", 15.0, 2.0),  # latest — 저평가
                ("MSFT", "2026-04-15", 30.0, 5.0),
            ],
        )
        df = compute_value(tickers=["AAPL", "MSFT"])
        # 최신 AAPL (PE 15) 가 MSFT (PE 30) 보다 저평가 → value_score 더 큼.
        # 만약 old row (PE 100) 를 사용했다면 MSFT (PE 30) 가 더 커진다.
        assert float(df.loc["AAPL", "value_score"]) > float(df.loc["MSFT", "value_score"])

    def test_no_tickers_returns_empty(self, db_path_mp, monkeypatch):
        """get_tickers() 가 빈 리스트 → empty (line 24)."""
        from nuri.quant.factors import value as vmod

        monkeypatch.setattr("nuri.core.db.get_tickers", lambda **kw: [])
        df = vmod.compute_value()
        assert df.empty

    def test_skips_rows_with_both_none(self, db_path_mp):
        """pe/pb 둘 다 None → skip (line 48 continue)."""
        from nuri.quant.factors.value import compute_value

        self._seed_fundamentals(
            db_path_mp,
            [
                ("AAPL", "2026-04-15", 15.0, 2.0),
                ("MSFT", "2026-04-15", 30.0, 5.0),
                ("ZZZ", "2026-04-15", None, None),
            ],
        )
        df = compute_value(tickers=["AAPL", "MSFT", "ZZZ"])
        assert "ZZZ" not in df.index

    def test_single_ticker_assigns_05_for_value(self, db_path_mp):
        """단일 ticker → valid 1 → else: 0.5 (line 71)."""
        from nuri.quant.factors.value import compute_value

        self._seed_fundamentals(db_path_mp, [("AAPL", "2026-04-15", 15.0, 2.0)])
        df = compute_value(tickers=["AAPL"])
        # valid 가 단일이면 0.5 fallback (line 71 else 분기)
        assert df.loc["AAPL", "pe_ratio_norm"] == 0.5
        assert df.loc["AAPL", "pb_ratio_norm"] == 0.5

    def test_constant_column_assigns_05(self, db_path_mp):
        """동일 PE/PB 값 2개 → col_min == col_max → 0.5 (line 69)."""
        from nuri.quant.factors.value import compute_value

        self._seed_fundamentals(
            db_path_mp,
            [
                ("AAPL", "2026-04-15", 15.0, None),
                ("MSFT", "2026-04-15", 15.0, None),
            ],
        )
        df = compute_value(tickers=["AAPL", "MSFT"])
        assert (df["pe_ratio_norm"] == 0.5).all()

    def test_value_source_has_no_openbb_import(self):
        """아키텍처 회귀 방어: value.py 가 OpenBB 를 다시 import 하지 않는지 확인.

        §2.3 "Loose coupling via data" — factors 모듈은 DB query 만 사용. 단순 string
        match 는 docstring 을 잡아 false positive 발생 — AST 로 실제 import 노드만 검사.
        """
        import ast
        from pathlib import Path

        tree = ast.parse(Path("nuri/quant/factors/value.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert "openbb" not in (node.module or "").lower(), (
                    f"value.py `from {node.module} import ...` 재도입됨 (§2.3 위배)"
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert "openbb" not in alias.name.lower(), f"value.py `import {alias.name}` 재도입됨 (§2.3 위배)"

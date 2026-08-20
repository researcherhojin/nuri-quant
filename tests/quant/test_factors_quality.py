# cspell:ignore qmod
"""Tests for factors_quality — split from test_quant_all.py."""

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


class TestQuality:
    """(from test_factors.py)."""

    def test_empty_when_no_data(self, db_path_mp):
        from nuri.quant.factors.quality import compute_quality

        result = compute_quality(tickers=["FAKE"])
        assert result.empty

    def test_normalization_logic(self):
        scores = {"AAPL": {"roe": 0.30, "operating_margin": 0.25}, "MSFT": {"roe": 0.15, "operating_margin": 0.10}}
        df = pd.DataFrame(scores).T
        for col in ["roe", "operating_margin"]:
            valid = df[col].dropna()
            col_min, col_max = valid.min(), valid.max()
            if col_max > col_min:
                df[col + "_norm"] = (valid - col_min) / (col_max - col_min)
            else:
                df[col + "_norm"] = 0.5
        norm_cols = [c for c in df.columns if c.endswith("_norm")]
        df["quality_score"] = df[norm_cols].mean(axis=1)
        assert float(df.loc["AAPL", "quality_score"]) > float(df.loc["MSFT", "quality_score"])


class TestQualityDbRead:
    """#349 regression lock-in — compute_quality 가 fundamentals 테이블 read 로 동작.

    이전 구현은 `obb.equity.fundamental.ratios` 를 호출 → broken OpenBB 로 silent 0.5 상수.
    아래 테스트는 seed 한 fundamentals 값 차이가 quality_score 에 반영되는지 검증한다.
    revert 시 (API call 로 되돌리면) fundamentals seed 는 무시되어 score 가 상수화 → fail.
    """

    def _seed_fundamentals(self, db_path, rows: list[tuple]) -> None:
        """rows: list of (ticker, date, roe, operating_margin)."""
        from nuri.core.db import get_db

        with get_db(db_path) as conn:
            for ticker, date, roe, margin in rows:
                conn.execute(
                    "INSERT OR REPLACE INTO fundamentals (ticker, date, roe, operating_margin) VALUES (?, ?, ?, ?)",
                    (ticker, date, roe, margin),
                )

    def test_quality_score_non_constant_when_fundamentals_vary(self, db_path_mp):
        """3 티커의 ROE/margin 이 다르면 quality_score 도 차별화되어야 한다."""
        from nuri.quant.factors.quality import compute_quality

        self._seed_fundamentals(
            db_path_mp,
            [
                ("AAPL", "2026-04-15", 0.30, 0.35),
                ("MSFT", "2026-04-15", 0.20, 0.25),
                ("NVDA", "2026-04-15", 0.45, 0.50),
            ],
        )
        df = compute_quality(tickers=["AAPL", "MSFT", "NVDA"])
        assert not df.empty
        assert "quality_score" in df.columns
        # 핵심 회귀 방어: score 가 상수화되면 이 assert 가 깨진다
        assert df["quality_score"].nunique() > 1, (
            "quality_score 가 상수 (이전 0.5 버그 재발) — fundamentals read 로 source 가 되었는지 확인"
        )
        # NVDA (최고 ROE + margin) > AAPL > MSFT 순서 검증
        assert float(df.loc["NVDA", "quality_score"]) > float(df.loc["AAPL", "quality_score"])
        assert float(df.loc["AAPL", "quality_score"]) > float(df.loc["MSFT", "quality_score"])

    def test_a_missing_roe_is_not_a_quality_bonus(self, db_path_mp):
        """ROE 가 없다는 이유만으로 최고 퀄리티가 되지 않는다 (#1102).

        이전 구현은 `valid = df[col].dropna()` 로 만든 시리즈를 `df[col + "_norm"]` 에
        대입해서, 결측 행에는 값이 **안 들어가고 NaN 이 남았다**. 그다음
        `mean(axis=1)` 이 기본 `skipna=True` 라 그 종목은 살아남은 컬럼 하나로만 채점됐다.
        관측 1개의 평균은 2개보다 분산이 2배라 꼬리를 독점한다 — 실측에서 MO 는 ROE 결측
        + 최고 영업이익률만으로 `quality_score = 1.0000` 이었고, ROE 가 실제로 있는
        VICI 는 0.5035 였다. 자본잠식 종목 31개 중 27개가 ROE 결측이라 `value.py` 의
        클립 보너스와 **같은 종목에 겹쳐** 쌓였고, 유니버스 확장 시뮬레이션에서 상위 25개가
        전부 그 조합이었다.
        """
        from nuri.quant.factors.quality import compute_quality

        rows = [(f"T{i:02d}", "2026-04-15", 0.05 + i * 0.02, 0.05 + i * 0.03) for i in range(10)]
        rows.append(("NOROE", "2026-04-15", None, 0.99))  # 최고 마진, ROE 결측
        self._seed_fundamentals(db_path_mp, rows)

        df = compute_quality(tickers=[r[0] for r in rows])

        assert float(df.loc["NOROE", "quality_score"]) < 1.0, "결측이 만점을 만들었다"
        best_observed = df.drop(index="NOROE")["quality_score"].max()
        assert float(df.loc["NOROE", "quality_score"]) <= best_observed + 0.13, (
            "두 축을 다 관측한 최상위 종목보다 결측 종목이 크게 앞섰다"
        )

    def test_one_extreme_roe_does_not_flatten_everyone_else(self, db_path_mp):
        """극단 ROE 하나가 나머지의 변별력을 지우지 않는다 (#1102).

        실측: US `roe` 최댓값 84.57 (자본잠식 종목의 산술 부산물) 대 최솟값 −1.19 라
        범위가 85.76 이 되어, 정상적인 ROE 0.153 이 0.0156 으로 정규화됐다 —
        `roe_norm` 의 99.4% 가 [0, 0.1] 에 몰렸다. 거의-0 상수와 거의-1 상수의 평균은
        거의-0.5 상수이므로, #1102 의 증상이 유니버스를 넓혀도 그대로 살아남는 경로였다.
        """
        from nuri.quant.factors.quality import compute_quality

        rows = [(f"T{i:02d}", "2026-04-15", 0.05 + i * 0.02, 0.10 + i * 0.02) for i in range(10)]
        rows.append(("BLOWUP", "2026-04-15", 84.57, 0.30))  # 자본잠식 부산물
        self._seed_fundamentals(db_path_mp, rows)

        df = compute_quality(tickers=[r[0] for r in rows])
        normal = df.drop(index="BLOWUP")["roe_norm"]

        assert normal.max() - normal.min() > 0.5, (
            f"극단 ROE 하나가 나머지를 압축했다 (spread={normal.max() - normal.min():.4f})"
        )

    def test_quality_reads_latest_date_per_ticker(self, db_path_mp):
        """동일 ticker 여러 날짜 → 가장 최신 row 만 사용."""
        from nuri.quant.factors.quality import compute_quality

        self._seed_fundamentals(
            db_path_mp,
            [
                ("AAPL", "2026-04-10", 0.10, 0.10),  # old (should be ignored)
                ("AAPL", "2026-04-15", 0.30, 0.35),  # latest
                ("MSFT", "2026-04-15", 0.20, 0.25),
            ],
        )
        df = compute_quality(tickers=["AAPL", "MSFT"])
        # min-max 정규화 → AAPL roe=0.30 이 max → AAPL quality_score 가 더 큼.
        # 만약 old row (0.10) 를 사용했다면 MSFT (0.20) 가 더 커진다.
        assert float(df.loc["AAPL", "quality_score"]) > float(df.loc["MSFT", "quality_score"])

    def test_no_tickers_returns_empty(self, db_path_mp, monkeypatch):
        """tickers=None + get_tickers() 가 빈 리스트 → empty df (line 24)."""
        from nuri.quant.factors import quality as qmod

        monkeypatch.setattr("nuri.core.db.get_tickers", lambda **kw: [])
        df = qmod.compute_quality()
        assert df.empty

    def test_kr_tickers_included_per_market(self, db_path_mp, monkeypatch):
        """#757: KR(.KS) 종목이 fundamentals 가 있으면 quality_score 를 받는다.

        과거엔 default ticker 목록에서 .KS 를 제외해 KR 이 composite 에서 flat 0.5.
        이제 KR 포함 + 시장별 정규화. (get_tickers() default 경로 검증.)
        """
        from nuri.quant.factors import quality as qmod

        self._seed_fundamentals(
            db_path_mp,
            [
                ("005930.KS", "2026-04-15", 0.18, 0.22),
                ("000660.KS", "2026-04-15", 0.09, 0.11),
            ],
        )
        monkeypatch.setattr("nuri.core.db.get_tickers", lambda **kw: ["005930.KS", "000660.KS"])
        df = qmod.compute_quality()
        assert not df.empty
        assert set(df.index) == {"005930.KS", "000660.KS"}
        # 시장 내 정규화 → 고ROE/고마진(005930.KS)이 더 높은 quality
        assert float(df.loc["005930.KS", "quality_score"]) > float(df.loc["000660.KS", "quality_score"])

    def test_kr_included_and_normalized_per_market(self, db_path_mp):
        """#757: KR 추가가 US quality_score 를 바꾸지 않는다 (시장별 정규화)."""
        from nuri.quant.factors.quality import compute_quality

        self._seed_fundamentals(
            db_path_mp,
            [
                ("AAPL", "2026-04-15", 0.30, 0.35),
                ("MSFT", "2026-04-15", 0.20, 0.25),
                ("NVDA", "2026-04-15", 0.45, 0.50),
                ("1111.KS", "2026-04-15", 0.12, 0.10),
                ("2222.KS", "2026-04-15", 0.25, 0.20),
                ("3333.KS", "2026-04-15", 0.40, 0.38),
            ],
        )
        us = ["AAPL", "MSFT", "NVDA"]
        kr = ["1111.KS", "2222.KS", "3333.KS"]
        df_all = compute_quality(tickers=us + kr)
        df_us_only = compute_quality(tickers=us)

        assert df_all.loc[kr, "quality_score"].nunique() > 1
        assert float(df_all.loc["3333.KS", "quality_score"]) > float(df_all.loc["1111.KS", "quality_score"])
        for t in us:
            assert float(df_all.loc[t, "quality_score"]) == pytest.approx(float(df_us_only.loc[t, "quality_score"]))

    def test_normalize_quality_columns_skips_absent_column(self):
        """_normalize_quality_columns: df 에 없는 컬럼은 건너뛴다 (col in df.columns False 분기)."""
        from nuri.quant.factors.quality import _normalize_quality_columns

        df = pd.DataFrame({"roe": [0.30, 0.10]}, index=["A", "B"])  # operating_margin 없음
        out = _normalize_quality_columns(df)
        assert "roe_norm" in out.columns
        assert "operating_margin_norm" not in out.columns

    def test_skips_rows_with_both_none(self, db_path_mp):
        """roe/margin 둘 다 None 인 row 는 skip (line 49 continue)."""
        from nuri.quant.factors.quality import compute_quality

        self._seed_fundamentals(
            db_path_mp,
            [
                ("AAPL", "2026-04-15", 0.30, 0.35),
                ("MSFT", "2026-04-15", 0.20, 0.25),
                ("ZZZ", "2026-04-15", None, None),  # skipped
            ],
        )
        df = compute_quality(tickers=["AAPL", "MSFT", "ZZZ"])
        assert "ZZZ" not in df.index

    def test_constant_column_assigns_05(self, db_path_mp):
        """모든 ticker 의 ROE 가 같으면 col_max == col_min → norm = 0.5 (line 68)."""
        from nuri.quant.factors.quality import compute_quality

        # ROE 가 모두 동일 → col_min == col_max → 0.5 fallback
        self._seed_fundamentals(
            db_path_mp,
            [
                ("AAPL", "2026-04-15", 0.20, None),
                ("MSFT", "2026-04-15", 0.20, None),
            ],
        )
        df = compute_quality(tickers=["AAPL", "MSFT"])
        assert (df["roe_norm"] == 0.5).all()

    def test_no_norm_cols_returns_constant_05(self, db_path_mp):
        """단일 ticker → valid<2 → norm 컬럼 없음 → quality_score = 0.5 (line 74)."""
        from nuri.quant.factors.quality import compute_quality

        # 단일 ticker (valid 1) → 정규화 미발생 → norm_cols 비어있음
        self._seed_fundamentals(db_path_mp, [("AAPL", "2026-04-15", 0.20, 0.10)])
        df = compute_quality(tickers=["AAPL"])
        assert df.loc["AAPL", "quality_score"] == 0.5

    def test_quality_source_has_no_openbb_import(self):
        """아키텍처 회귀 방어: quality.py 가 OpenBB 를 다시 import 하지 않는지 확인.

        §2.3 "Loose coupling via data" — factors 모듈은 DB query 만 사용. 단순 string
        match 는 docstring 을 잡아 false positive 발생 — AST 로 실제 import 노드만 검사.
        """
        import ast
        from pathlib import Path

        tree = ast.parse(Path("nuri/quant/factors/quality.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert "openbb" not in (node.module or "").lower(), (
                    f"quality.py `from {node.module} import ...` 재도입됨 (§2.3 위배)"
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert "openbb" not in alias.name.lower(), f"quality.py `import {alias.name}` 재도입됨 (§2.3 위배)"

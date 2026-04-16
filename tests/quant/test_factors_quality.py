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
        scores = {"AAPL": {"roe": 0.30, "operating_margin": 0.25},
                  "MSFT": {"roe": 0.15, "operating_margin": 0.10}}
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
        assert df.loc["AAPL", "quality_score"] > df.loc["MSFT", "quality_score"]


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
                    "INSERT OR REPLACE INTO fundamentals (ticker, date, roe, operating_margin)"
                    " VALUES (?, ?, ?, ?)",
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
            "quality_score 가 상수 (이전 0.5 버그 재발) — "
            "fundamentals read 로 source 가 되었는지 확인"
        )
        # NVDA (최고 ROE + margin) > AAPL > MSFT 순서 검증
        assert df.loc["NVDA", "quality_score"] > df.loc["AAPL", "quality_score"]
        assert df.loc["AAPL", "quality_score"] > df.loc["MSFT", "quality_score"]

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
        assert df.loc["AAPL", "quality_score"] > df.loc["MSFT", "quality_score"]

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
                    assert "openbb" not in alias.name.lower(), (
                        f"quality.py `import {alias.name}` 재도입됨 (§2.3 위배)"
                    )

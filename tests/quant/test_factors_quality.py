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

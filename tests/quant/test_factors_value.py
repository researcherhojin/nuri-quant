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
        scores = {"AAPL": {"pe_ratio": 15.0, "pb_ratio": 2.0},
                  "MSFT": {"pe_ratio": 30.0, "pb_ratio": 5.0}}
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
        assert df.loc["AAPL", "value_score"] > df.loc["MSFT", "value_score"]

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

    def test_insufficient_data(self, db_path_mp):
        prices = pd.DataFrame([{
            "ticker": "SHORT", "date": f"2024-01-{i+1:02d}",
            "open": 100, "high": 101, "low": 99, "close": 100,
            "volume": 1000, "adj_close": 100,
        } for i in range(5)])
        upsert_prices(prices, db_path_mp)
        from nuri.quant.factors.momentum import compute_momentum
        result = compute_momentum()
        assert "SHORT" not in result.index if not result.empty else True

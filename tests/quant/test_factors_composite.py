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
        expected = (m * WEIGHTS["momentum"] + v * WEIGHTS["value"] +
                    q * WEIGHTS["quality"] + s * WEIGHTS["sentiment"])
        assert 0 < expected < 1

    def test_print_composite_empty(self, capsys):
        from nuri.quant.factors.composite import print_composite
        print_composite(pd.DataFrame())
        output = capsys.readouterr().out
        assert "없습니다" in output

    def test_print_composite_with_data(self, capsys):
        from nuri.quant.factors.composite import print_composite
        df = pd.DataFrame([{
            "momentum_score": 0.7, "value_score": 0.5,
            "quality_score": 0.6, "sentiment_score": 0.5, "composite_score": 0.58,
        }], index=["AAPL"])
        print_composite(df)
        output = capsys.readouterr().out
        assert "AAPL" in output
        assert "멀티팩터" in output

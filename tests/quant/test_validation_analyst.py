"""Tests for validation_analyst — split from test_quant_all.py."""
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


class TestAnalystBacktest:
    """C-3 (from test_validation.py)."""

    def test_insufficient_data_message(self, db_path):
        from nuri.quant.validation.analyst_backtest import validate_estimates
        results = validate_estimates(min_elapsed_days=90, db_path=db_path)
        assert results == []


class TestAnalystBacktest_Extra:
    """(from test_coverage_extra.py)."""

    def test_validate_estimates(self, db_path):
        from nuri.quant.validation.analyst_backtest import validate_estimates
        results = validate_estimates(db_path=db_path)
        assert isinstance(results, list)

    def test_estimate_result_class(self):
        from nuri.quant.validation.analyst_backtest import EstimateResult
        r = EstimateResult(
            ticker="AAPL", estimate_date="2026-01-01", recommendation="Buy",
            target_mean=200.0, price_at_estimate=180.0, actual_price=195.0,
            actual_date="2026-04-01", target_gap_pct=11.1, actual_return_pct=8.3,
            target_hit=False,
        )
        assert r.target_hit is False
        assert r.ticker == "AAPL"


class TestAnalystBacktestData:
    """(from test_coverage_round12.py)."""

    def test_with_estimates_data(self, rich_db):
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO estimates "
                "(ticker, date, recommendation, target_high, target_low, "
                "target_mean, target_median, num_analysts, current_price) "
                "VALUES ('AAPL', '2025-06-01', 'buy', 250, 180, 220, 215, 30, 190)")
        from nuri.quant.validation.analyst_backtest import validate_estimates
        results = validate_estimates()
        assert isinstance(results, list)

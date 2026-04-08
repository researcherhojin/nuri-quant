"""Tests for validation_scorecard — split from test_quant_all.py."""
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


class TestSignalScorecard_R19:
    """(from test_coverage_round19.py)."""

    def test_generate_scorecard_with_results(self):
        from nuri.quant.validation.signal_backtest import SignalResult, generate_scorecard
        results = [
            SignalResult(signal_id="rsi_oversold", ticker="AAPL",
                         entry_date="2025-01-01", entry_price=100.0,
                         exit_date="2025-01-21", exit_price=110.0,
                         return_pct=10.0, holding_days=20, won=True),
            SignalResult(signal_id="rsi_oversold", ticker="AAPL",
                         entry_date="2025-02-01", entry_price=110.0,
                         exit_date="2025-02-21", exit_price=105.0,
                         return_pct=-4.55, holding_days=20, won=False),
        ]
        scorecards = generate_scorecard(results)
        assert len(scorecards) >= 2
        aggregate = [s for s in scorecards if s.ticker is None]
        assert len(aggregate) == 1
        assert aggregate[0].total_trades == 2
        assert aggregate[0].win_rate == 0.5

    def test_print_scorecard_empty(self, capsys):
        from nuri.quant.validation.signal_backtest import print_scorecard
        print_scorecard([])
        captured = capsys.readouterr()
        assert "없습니다" in captured.out

"""Tests for validation_report — split from test_quant_all.py."""
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


class TestGenerateValidationReport:
    """C-4 (from test_scorecard.py)."""

    @pytest.fixture
    def report_dir(self, tmp_path):
        d = tmp_path / "2026-03-28"
        d.mkdir()
        sig_data = pd.DataFrame([
            {"ticker": None, "signal_id": "rsi_oversold", "total_trades": 50, "win_rate": 0.65,
             "profit_factor": 2.1, "avg_return": 5.2, "median_return": 3.8},
            {"ticker": None, "signal_id": "macd_golden", "total_trades": 30, "win_rate": 0.55,
             "profit_factor": 1.5, "avg_return": 2.1, "median_return": 1.5},
            {"ticker": None, "signal_id": "bb_bounce", "total_trades": 40, "win_rate": 0.45,
             "profit_factor": 0.8, "avg_return": -1.0, "median_return": -0.5},
        ])
        sig_data.to_csv(d / "signal_scorecard.csv", index=False)
        return d

    @pytest.fixture
    def full_report_dir(self, report_dir):
        si_data = pd.DataFrame([
            {"investor": "Buffett", "total_follows": 20, "win_rate": 0.70, "avg_return": 12.0, "avg_excess_return": 5.0},
            {"investor": "Dalio", "total_follows": 15, "win_rate": 0.55, "avg_return": 6.0, "avg_excess_return": -1.0},
        ])
        si_data.to_csv(report_dir / "superinvestor_scorecard.csv", index=False)
        an_data = pd.DataFrame([
            {"recommendation": "Strong Buy", "target_hit": True, "actual_return_pct": 15.0},
            {"recommendation": "Strong Buy", "target_hit": True, "actual_return_pct": 8.0},
            {"recommendation": "Buy", "target_hit": False, "actual_return_pct": -3.0},
            {"recommendation": "Hold", "target_hit": False, "actual_return_pct": 1.0},
        ])
        an_data.to_csv(report_dir / "analyst_results.csv", index=False)
        return report_dir

    def test_with_signal_only(self, report_dir):
        from nuri.quant.validation.scorecard import generate_validation_report
        path = generate_validation_report(output_dir=report_dir)
        assert path is not None
        assert path.exists()
        assert path.suffix == ".html"
        content = path.read_text()
        assert "rsi_oversold" in content

    def test_with_all_sections(self, full_report_dir):
        from nuri.quant.validation.scorecard import generate_validation_report
        path = generate_validation_report(output_dir=full_report_dir)
        assert path is not None
        content = path.read_text()
        assert "Buffett" in content

    def test_no_csv_returns_none(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        from nuri.quant.validation.scorecard import generate_validation_report
        path = generate_validation_report(output_dir=d)
        assert path is None

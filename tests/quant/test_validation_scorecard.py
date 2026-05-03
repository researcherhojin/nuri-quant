"""Tests for validation_scorecard — split from test_quant_all.py."""

# cspell:ignore Munger
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
            SignalResult(
                signal_id="rsi_oversold",
                ticker="AAPL",
                entry_date="2025-01-01",
                entry_price=100.0,
                exit_date="2025-01-21",
                exit_price=110.0,
                return_pct=10.0,
                holding_days=20,
                won=True,
            ),
            SignalResult(
                signal_id="rsi_oversold",
                ticker="AAPL",
                entry_date="2025-02-01",
                entry_price=110.0,
                exit_date="2025-02-21",
                exit_price=105.0,
                return_pct=-4.55,
                holding_days=20,
                won=False,
            ),
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


class TestValidationScorecardReport:
    """C-4 generate_validation_report — output_dir branches + missing CSV guard."""

    def test_returns_none_when_signal_csv_missing(self, tmp_path):
        """signal_scorecard.csv 가 없으면 None (line 38)."""
        from nuri.quant.validation.scorecard import generate_validation_report

        # tmp_path 에 아무 csv 도 없음
        result = generate_validation_report(output_dir=tmp_path)
        assert result is None

    def test_default_output_dir_uses_today(self, tmp_path, monkeypatch):
        """output_dir=None → REPORT_DIR/today_kst() 사용 (lines 27-29).
        실제로는 csv 가 없으므로 None 반환하지만 28-29 라인은 실행됨."""
        from nuri.quant.validation import scorecard as sc_mod

        # REPORT_DIR 을 임시 경로로 redirect
        monkeypatch.setattr(sc_mod, "REPORT_DIR", tmp_path)
        result = sc_mod.generate_validation_report()  # output_dir 인자 누락
        assert result is None  # csv 없으니까 None

    def test_full_report_with_all_csvs(self, tmp_path):
        """signal + si + analyst CSV 모두 있으면 HTML 생성 (lines 108-148)."""
        from nuri.quant.validation.scorecard import generate_validation_report

        # signal_scorecard.csv (필수)
        sig = pd.DataFrame(
            [
                {
                    "signal_id": "rsi_oversold",
                    "ticker": None,
                    "profit_factor": 2.5,
                    "win_rate": 0.6,
                    "total_trades": 10,
                    "avg_return": 5.0,
                    "median_return": 4.0,
                },
                {
                    "signal_id": "macd_golden",
                    "ticker": None,
                    "profit_factor": 0.8,
                    "win_rate": 0.4,
                    "total_trades": 8,
                    "avg_return": -2.0,
                    "median_return": -1.0,
                },
            ]
        )
        sig.to_csv(tmp_path / "signal_scorecard.csv", index=False)

        # superinvestor_scorecard.csv
        si = pd.DataFrame(
            [
                {
                    "investor": "Buffett",
                    "avg_excess_return": 3.5,
                    "avg_return": 8.0,
                    "win_rate": 0.65,
                    "total_follows": 20,
                },
                {
                    "investor": "Munger",
                    "avg_excess_return": -1.0,
                    "avg_return": 2.0,
                    "win_rate": 0.45,
                    "total_follows": 15,
                },
            ]
        )
        si.to_csv(tmp_path / "superinvestor_scorecard.csv", index=False)

        # analyst_results.csv
        an = pd.DataFrame(
            [
                {"ticker": "AAA", "recommendation": "buy", "target_hit": True, "actual_return_pct": 8.5},
                {"ticker": "BBB", "recommendation": "buy", "target_hit": False, "actual_return_pct": -3.0},
                {"ticker": "CCC", "recommendation": "hold", "target_hit": True, "actual_return_pct": 2.0},
            ]
        )
        an.to_csv(tmp_path / "analyst_results.csv", index=False)

        result = generate_validation_report(output_dir=tmp_path)
        assert result is not None
        assert result.exists()
        assert result.suffix == ".html"

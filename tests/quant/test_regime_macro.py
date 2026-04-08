"""Tests for regime_macro — split from test_quant_all.py."""
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


class TestMacroScore:
    """D-2 (from test_regime.py)."""

    def test_score_range(self, db_path):
        from nuri.quant.regime.macro_score import compute_macro_score
        score = compute_macro_score(db_path=db_path)
        assert 0 <= score.total_score <= 100

    def test_favorable_conditions(self, db_path):
        from nuri.quant.regime.macro_score import compute_macro_score
        date = "2025-01-15"
        upsert_macro([
            {"indicator": "us_10y_yield", "date": date, "value": 4.0, "source": "test"},
            {"indicator": "us_2y_yield", "date": date, "value": 3.0, "source": "test"},
            {"indicator": "vix", "date": date, "value": 14.0, "source": "test"},
            {"indicator": "fear_greed", "date": date, "value": 55.0, "source": "test"},
            {"indicator": "unemployment", "date": date, "value": 3.8, "source": "test"},
            {"indicator": "cpi_yoy", "date": date, "value": 2.1, "source": "test"},
            {"indicator": "fed_funds_rate", "date": date, "value": 2.0, "source": "test"},
        ], db_path)
        score = compute_macro_score(date=date, db_path=db_path)
        assert score.total_score > 65
        assert score.interpretation == "Favorable"

    def test_adverse_conditions(self, db_path):
        from nuri.quant.regime.macro_score import compute_macro_score
        date = "2025-06-15"
        upsert_macro([
            {"indicator": "us_10y_yield", "date": date, "value": 3.0, "source": "test"},
            {"indicator": "us_2y_yield", "date": date, "value": 4.5, "source": "test"},
            {"indicator": "vix", "date": date, "value": 35.0, "source": "test"},
            {"indicator": "fear_greed", "date": date, "value": 10.0, "source": "test"},
            {"indicator": "unemployment", "date": date, "value": 7.0, "source": "test"},
            {"indicator": "cpi_yoy", "date": date, "value": 6.5, "source": "test"},
            {"indicator": "fed_funds_rate", "date": date, "value": 5.5, "source": "test"},
        ], db_path)
        score = compute_macro_score(date=date, db_path=db_path)
        assert score.total_score < 35
        assert score.interpretation in ("Cautious", "Adverse")


class TestMacroScoreWarnings:
    """(from test_data_integrity.py)."""

    def test_empty_db_has_all_warnings(self, db_path):
        from nuri.quant.regime.macro_score import compute_macro_score
        score = compute_macro_score(db_path=db_path)
        assert score.warnings is not None
        assert len(score.warnings) == 8

    def test_partial_data_partial_warnings(self, db_path):
        date = "2025-01-15"
        upsert_macro([
            {"indicator": "vix", "date": date, "value": 15.0, "source": "test"},
            {"indicator": "fear_greed", "date": date, "value": 50.0, "source": "test"},
        ], db_path)
        from nuri.quant.regime.macro_score import compute_macro_score
        score = compute_macro_score(date=date, db_path=db_path)
        assert score.warnings is not None
        warning_names = [w.split(":")[0] for w in score.warnings]
        assert "vix" not in warning_names
        assert "sentiment" not in warning_names
        assert len(score.warnings) == 6

    def test_full_data_no_warnings(self, db_path):
        date = "2025-01-15"
        upsert_macro([
            {"indicator": "us_10y_yield", "date": date, "value": 4.0, "source": "test"},
            {"indicator": "us_2y_yield", "date": date, "value": 3.0, "source": "test"},
            {"indicator": "us_3m_yield", "date": date, "value": 2.5, "source": "test"},
            {"indicator": "vix", "date": date, "value": 15.0, "source": "test"},
            {"indicator": "put_call_ratio", "date": date, "value": 0.85, "source": "test"},
            {"indicator": "fear_greed", "date": date, "value": 55.0, "source": "test"},
            {"indicator": "unemployment", "date": date, "value": 3.8, "source": "test"},
            {"indicator": "cpi_yoy", "date": date, "value": 2.1, "source": "test"},
            {"indicator": "fed_funds_rate", "date": date, "value": 2.0, "source": "test"},
        ], db_path)
        from nuri.quant.regime.macro_score import compute_macro_score
        score = compute_macro_score(date=date, db_path=db_path)
        assert score.warnings is None

    def test_score_still_50_when_missing(self, db_path):
        from nuri.quant.regime.macro_score import compute_macro_score
        score = compute_macro_score(db_path=db_path)
        assert score.total_score == 50.0


class TestMacroScoreExtended:
    """(from test_coverage_final.py)."""

    def test_compute(self, rich_db):
        from nuri.quant.regime.macro_score import compute_macro_score
        score = compute_macro_score(db_path=rich_db)
        assert hasattr(score, "total_score")
        assert 0 <= score.total_score <= 100

    def test_print(self, rich_db, capsys):
        from nuri.quant.regime.macro_score import compute_macro_score, print_macro_score
        score = compute_macro_score(db_path=rich_db)
        print_macro_score(score)
        output = capsys.readouterr().out
        assert "Macro" in output or "매크로" in output

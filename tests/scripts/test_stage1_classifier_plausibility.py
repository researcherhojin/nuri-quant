"""E3-2 Stage 1 plausibility script smoke tests.

codex Round 1 권장 — light tests for sample date generation cutoff +
forward anchor behavior + Round 2 P1 output invariant lock-in.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_macro, upsert_prices

# scripts/ 는 패키지가 아니라 stand-alone — importlib 로 명시 dynamic load
# (sys.path manipulation 은 runtime OK 지만 Pylance 정적 분석에서 미탐).
# sys.modules 등록 필수 — @dataclass 의 cls.__module__ lookup path.
_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "stage1_classifier_plausibility.py"
_spec = importlib.util.spec_from_file_location("stage1_classifier_plausibility", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
s1 = importlib.util.module_from_spec(_spec)
sys.modules["stage1_classifier_plausibility"] = s1
_spec.loader.exec_module(s1)


@pytest.fixture
def db_path(tmp_path):
    """tests/quant/conftest.py 의 db_path 와 동일 — tests/scripts 스코프 외라 로컬 정의."""
    p = tmp_path / "test.db"
    init_db(p)
    return p


def _seed_spy_and_vix(db_path, n_days: int, start_date: str = "2025-01-01"):
    """SPY prices (n_days 거래일) + VIX (동일 dates) seed."""
    dates = pd.bdate_range(start=start_date, periods=n_days)
    rng = np.random.default_rng(42)
    close = 200 + np.linspace(0, 50, n_days) + rng.normal(0, 0.5, n_days)
    df = pd.DataFrame({
        "ticker": "SPY",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.999, "high": close * 1.001, "low": close * 0.999,
        "close": close, "volume": [50_000_000] * n_days, "adj_close": close,
    })
    upsert_prices(df, db_path)
    upsert_macro(
        [{"indicator": "vix", "date": d.strftime("%Y-%m-%d"), "value": 18.0, "source": "test"}
         for d in dates],
        db_path=db_path,
    )
    return [d.strftime("%Y-%m-%d") for d in dates]


class TestGenerateSampleDates:
    """codex Round 1 P1 — cutoff = (latest SPY) - 21 거래일 보장."""

    def test_cutoff_excludes_recent_21_trading_days(self, db_path):
        """SPY 최근 21 거래일 안쪽 sample 은 절대 포함되면 안 됨 (forward 측정 불가)."""
        from unittest.mock import patch

        from nuri.core.db import query
        all_dates = _seed_spy_and_vix(db_path, n_days=100)
        # cutoff = all_dates[-22] (most recent 21 days excluded)
        expected_cutoff = all_dates[-22]

        # _generate_sample_dates uses default db (data/portfolio.db) — patch query module-level
        from nuri.quant.regime import classifier as _clf  # noqa: F401  ensures module loaded
        with patch.object(s1, "query", side_effect=lambda *a, **kw: query(*a, **kw, db_path=db_path)):
            sample_dates = s1._generate_sample_dates(n=12)

        assert sample_dates, "should generate at least 1 sample"
        for d in sample_dates:
            assert d <= expected_cutoff, (
                f"sample {d} is past cutoff {expected_cutoff} — forward 21d not measurable"
            )


class TestForwardAnchorBehavior:
    """codex Round 1 P1 — forward 21 trading days anchor 가 정확히 +21번째 거래일."""

    def test_forward_close_is_exactly_n_trading_days_later(self, db_path):
        """entry_date 의 SPY 다음 21번째 거래일 close 를 정확히 가져오는지."""
        from unittest.mock import patch

        from nuri.core.db import query
        all_dates = _seed_spy_and_vix(db_path, n_days=100)
        entry_idx = 30  # mid-range
        entry_date = all_dates[entry_idx]
        expected_exit_date = all_dates[entry_idx + 21]

        with patch.object(s1, "query", side_effect=lambda *a, **kw: query(*a, **kw, db_path=db_path)):
            result = s1._get_spy_forward_close(entry_date, n_trading_days=21)

        assert result is not None
        actual_exit_date, _close = result
        assert actual_exit_date == expected_exit_date, (
            f"expected exit_date={expected_exit_date}, got {actual_exit_date}"
        )

    def test_forward_close_returns_none_when_insufficient_data(self, db_path):
        """SPY 가 entry 이후 21 거래일 미만이면 None — silent partial 금지."""
        from unittest.mock import patch

        from nuri.core.db import query
        all_dates = _seed_spy_and_vix(db_path, n_days=100)
        # entry = 95번째 → 이후 SPY 5 거래일만 → 21 부족
        entry_date = all_dates[95]

        with patch.object(s1, "query", side_effect=lambda *a, **kw: query(*a, **kw, db_path=db_path)):
            result = s1._get_spy_forward_close(entry_date, n_trading_days=21)

        assert result is None, "insufficient data should return None, not partial"


class TestRenderMarkdownInvariants:
    """codex Round 2 P1 — render_markdown 의 output invariants lock-in.

    Round 1 P1 fix 가 향후 PR 에서 실수로 제거되지 않도록 hard-lock.
    """

    def _build_results(self):
        # 3 sampled, 2 with return (1 N/A — usable 분리 검증)
        return [
            s1.SampleResult(date="2025-06-30", regime="bull_low_vol", confidence=0.8,
                            exit_date="2025-07-29", forward_return_pct=2.5),
            s1.SampleResult(date="2025-07-31", regime="recovery", confidence=0.6,
                            exit_date="2025-08-29", forward_return_pct=-1.2),
            s1.SampleResult(date="2026-04-01", regime="bull_low_vol", confidence=0.7,
                            exit_date=None, forward_return_pct=None),  # data not yet available
        ]

    def test_render_includes_recency_bias_disclosure(self):
        """codex Round 1 P1.1 — recency-bias framing must appear in output."""
        results = self._build_results()
        agg = s1.aggregate(results)
        md = s1.render_markdown(results, agg)
        assert "recency-biased" in md, "recency-bias disclosure missing — codex Round 1 P1.1 regression"
        assert "broad historical 아님" in md, "explicit non-broad-historical caveat missing"

    def test_render_shows_sampled_vs_usable_counts(self):
        """codex Round 1 P1.3 — sampled N vs usable N_ret 분리 표시."""
        results = self._build_results()
        agg = s1.aggregate(results)
        md = s1.render_markdown(results, agg)
        # sampled=3, usable=2 (1 has None forward_return)
        assert "Sampled N=3" in md, f"sampled count missing or wrong\n{md}"
        assert "usable N_ret=2" in md, f"usable count missing or wrong (should differ from sampled)\n{md}"

    def test_render_includes_exit_date_column(self):
        """codex Round 1 P1.2 — exit_date 컬럼 transparency."""
        results = self._build_results()
        agg = s1.aggregate(results)
        md = s1.render_markdown(results, agg)
        assert "exit_date" in md, "exit_date column missing — Round 1 P1.2 regression"
        assert "21 trading days" in md, "21 trading days header missing"
        assert "2025-07-29" in md, "specific exit_date value not rendered in row"
        assert "N/A" in md, "missing-data row should show N/A for exit_date"

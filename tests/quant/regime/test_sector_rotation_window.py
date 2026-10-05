"""#1631 — 섹터 순환 감지는 SPY 와 섹터 ETF 의 20일 창이 같은 날로 끝날 때만 본다."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_prices
from nuri.quant.regime.classifier import _detect_sector_rotation


def _seed(db_path, ticker: str, end: str, start_close: float, end_close: float) -> None:
    dates = pd.bdate_range(end=end, periods=21)
    close = np.linspace(start_close, end_close, 21)
    upsert_prices(
        pd.DataFrame(
            {
                "ticker": ticker,
                "date": [d.strftime("%Y-%m-%d") for d in dates],
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": [1_000_000] * 21,
                "adj_close": close,
            }
        ),
        db_path,
    )


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "rot.db"
    init_db(path)
    _seed(path, "SPY", "2026-10-02", 100.0, 101.0)  # 횡보 (+1%)
    return path


class TestSectorRotationWindowAlignment:
    def test_etf_window_ending_on_the_same_day_counts(self, db):
        _seed(db, "XLK", "2026-10-02", 100.0, 105.0)  # +5%
        assert _detect_sector_rotation(db_path=db) is True

    def test_stale_etf_window_is_skipped(self, db):
        """ETF 수집이 5주 전에 멈춘 DB: 옛 창의 +5% 를 오늘 SPY 횡보와 비교하면 안 된다."""
        _seed(db, "XLK", "2026-08-27", 100.0, 105.0)
        assert _detect_sector_rotation(db_path=db) is False

    def test_explicit_date_aligns_both_windows(self, db):
        """date= 로 과거를 보면 그 시점 기준으로 둘 다 잘리므로 정렬이 다시 맞는다."""
        _seed(db, "XLK", "2026-08-27", 100.0, 105.0)
        _seed(db, "SPY", "2026-08-27", 100.0, 101.0)
        assert _detect_sector_rotation(db_path=db, date="2026-08-27") is True

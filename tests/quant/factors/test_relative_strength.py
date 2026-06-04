"""Lock-tests for RS + 거래대금 leadership 팩터 (P2 shadow).

- known-answer: 최고 trailing 수익률 → RS percentile 최상위
- 120d 히스토리 floor: lookback 미만 종목 제외
- 거래대금 surge: 최근 거래대금 급증 → surge > 1
- KR/US 동일 lookback (통화-무관 — surge·percentile 모두 ratio/rank)
- 빈 prices / 데이터 부족 → 빈 DataFrame
"""

from __future__ import annotations

import pandas as pd
import pytest

from nuri.quant.factors.relative_strength import compute_leadership, leadership_snapshot


def _seed(db_path, rows):
    from nuri.core.db import get_db

    with get_db(db_path) as conn:
        conn.executemany("INSERT INTO prices (ticker, date, close, volume) VALUES (?, ?, ?, ?)", rows)


def _series(ticker, closes, vols, start="2024-01-01"):
    dates = pd.date_range(start, periods=len(closes), freq="B")
    return [(ticker, d.strftime("%Y-%m-%d"), float(c), int(v)) for d, c, v in zip(dates, closes, vols)]


class TestComputeLeadership:
    def test_rs_percentile_ranks_trailing_return(self, db_path):
        # 15일 패널, lookback=10. WINNER 상승 > FLAT 평탄 > LOSER 하락.
        rows = []
        rows += _series("WINNER", [100 + i * 5 for i in range(15)], [1000] * 15)  # 강한 상승
        rows += _series("FLAT", [100] * 15, [1000] * 15)  # 평탄
        rows += _series("LOSER", [100 - i * 2 for i in range(15)], [1000] * 15)  # 하락
        _seed(db_path, rows)

        df = compute_leadership(lookback=10, surge_window=3, db_path=db_path)
        assert set(df.index) == {"WINNER", "FLAT", "LOSER"}
        # 3종목 cross-sectional rank → 33.33 / 66.67 / 100
        assert df.loc["WINNER", "rs_percentile"] == pytest.approx(100.0)
        assert df.loc["LOSER", "rs_percentile"] == pytest.approx(33.33, abs=0.1)
        assert df.loc["WINNER", "rs_percentile"] > df.loc["FLAT", "rs_percentile"] > df.loc["LOSER", "rs_percentile"]

    def test_120d_floor_excludes_short_history(self, db_path):
        rows = []
        rows += _series("LONG", [100 + i for i in range(15)], [1000] * 15)
        rows += _series("SHORT", [100 + i for i in range(5)], [1000] * 5)  # 5일 < lookback 10
        _seed(db_path, rows)

        df = compute_leadership(lookback=10, surge_window=3, db_path=db_path)
        assert "LONG" in df.index
        assert "SHORT" not in df.index  # 히스토리 부족 → 제외

    def test_dollar_volume_surge_detects_recent_spike(self, db_path):
        # 최근 3일 거래대금이 baseline 대비 급증 → surge > 1
        vols = [1000] * 12 + [10000] * 3  # 마지막 3일 10배
        _seed(db_path, _series("SURGE", [100] * 15, vols))
        _seed(db_path, _series("CALM", [100] * 15, [1000] * 15))  # 평탄

        df = compute_leadership(lookback=10, surge_window=3, db_path=db_path)
        assert df.loc["SURGE", "dollar_volume_surge"] > 1.5
        assert df.loc["CALM", "dollar_volume_surge"] == pytest.approx(1.0, abs=0.01)

    def test_surge_is_currency_agnostic_ratio(self, db_path):
        # KR(고가 KRW)·US(저가 USD) 동일 패턴 → 동일 surge (비율이라 통화 무관)
        pattern_v = [1000] * 12 + [3000] * 3
        _seed(db_path, _series("US", [100] * 15, pattern_v))
        _seed(db_path, _series("005930.KS", [70000] * 15, pattern_v))
        df = compute_leadership(lookback=10, surge_window=3, db_path=db_path)
        assert df.loc["US", "dollar_volume_surge"] == pytest.approx(
            df.loc["005930.KS", "dollar_volume_surge"], rel=1e-6
        )

    def test_empty_prices(self, db_path):
        assert compute_leadership(db_path=db_path).empty

    def test_insufficient_rows(self, db_path):
        _seed(db_path, _series("A", [100] * 5, [1000] * 5))  # 5 rows < default lookback 120
        assert compute_leadership(db_path=db_path).empty

    def test_all_below_floor_despite_enough_matrix_rows(self, db_path):
        # 매트릭스 행수는 lookback 이상이나 각 종목 non-NaN < lookback (staggered 구간)
        _seed(db_path, _series("A", [100] * 8, [1000] * 8, start="2024-01-01"))
        _seed(db_path, _series("B", [100] * 8, [1000] * 8, start="2024-02-01"))  # 비중첩 구간
        # 합쳐 16 날짜(> lookback 10)지만 각 종목 8 non-NaN < 10 → 전부 floor 미달
        assert compute_leadership(lookback=10, surge_window=3, db_path=db_path).empty


class TestLeadershipSnapshot:
    def test_snapshot_maps_ticker_to_tuple(self, db_path):
        _seed(db_path, _series("A", [100 + i for i in range(15)], [1000] * 15))
        snap = leadership_snapshot(lookback=10, surge_window=3, db_path=db_path)
        assert "A" in snap
        rs, surge = snap["A"]
        assert isinstance(rs, float) and isinstance(surge, float)

    def test_snapshot_empty_when_no_data(self, db_path):
        assert leadership_snapshot(lookback=10, db_path=db_path) == {}

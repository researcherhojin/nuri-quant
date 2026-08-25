"""evidence_data 로더 단위 테스트 (#1224 U5a-1).

이동한 3함수(load_latest_scorecard / load_drift_map / detect_portfolio_violations)는
기존 test_evidence_charts*.py 가 별칭 경유로 잠근다 — 여기는 신규 쿼리 로더와
load_portfolio_grouped 의 위반 판정만 직접 잠근다.
"""

from unittest.mock import patch

import pandas as pd
import pytest

from nuri.analysis import evidence_data as ed
from nuri.core.db import upsert_macro, upsert_prices


def _seed_spy(db_path, n: int = 60) -> None:
    dates = pd.bdate_range(end=pd.Timestamp.today(), periods=n)
    upsert_prices(
        pd.DataFrame(
            {
                "ticker": "SPY",
                "date": dates.strftime("%Y-%m-%d"),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": [100.0 + i for i in range(n)],
                "volume": 1_000_000,
                "adj_close": [100.0 + i for i in range(n)],
            }
        ),
        db_path=db_path,
    )


class TestLoadSpyWithSma:
    def test_empty_db_returns_empty(self, db_path):
        assert ed.load_spy_with_sma(db_path=db_path).empty

    def test_seeded_sorted_asc_with_sma(self, db_path):
        _seed_spy(db_path, n=60)
        spy = ed.load_spy_with_sma(db_path=db_path)
        assert len(spy) == 60
        assert spy["date"].is_monotonic_increasing
        # 60행 → sma50 은 마지막 행에서 유효(최근 50개 close 110..159 의 평균), sma200 은 전부 NaN
        assert spy["sma50"].iloc[-1] == pytest.approx(134.5)
        assert int(spy["sma200"].isna().sum()) == 60

    def test_limit_takes_latest_rows(self, db_path):
        _seed_spy(db_path, n=60)
        spy = ed.load_spy_with_sma(db_path=db_path, limit=10)
        assert len(spy) == 10
        # DESC LIMIT 후 asc 정렬 — 최신 10행이어야 한다 (close 가 단조 증가 seed)
        assert spy["close"].iloc[0] == 150.0


class TestLoadMacroHistories:
    def test_vix_empty_and_seeded(self, db_path):
        assert ed.load_vix_history(db_path=db_path).empty
        upsert_macro(
            [
                {"indicator": "vix", "date": "2026-08-20", "value": 18.0, "source": "test"},
                {"indicator": "vix", "date": "2026-08-21", "value": 19.5, "source": "test"},
            ],
            db_path=db_path,
        )
        vix = ed.load_vix_history(db_path=db_path)
        assert list(vix["value"]) == [18.0, 19.5]
        assert vix["date"].is_monotonic_increasing

    def test_fear_greed_empty_and_limit(self, db_path):
        assert ed.load_fear_greed_history(db_path=db_path).empty
        upsert_macro(
            [
                {"indicator": "fear_greed", "date": f"2026-08-{d:02d}", "value": float(40 + d), "source": "test"}
                for d in (19, 20, 21)
            ],
            db_path=db_path,
        )
        fg = ed.load_fear_greed_history(db_path=db_path, limit=2)
        # 최신 2행만, asc 정렬
        assert list(fg["value"]) == [60.0, 61.0]


class TestLoadLatestScorecard:
    def test_skips_non_dir_and_returns_none_when_no_scorecard(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ed, "REPORT_DIR", tmp_path)
        (tmp_path / "stray.txt").write_text("x")  # 파일 엔트리 → continue
        (tmp_path / "2026-08-21").mkdir()  # scorecard 없는 날짜 dir
        # 루프 소진 → None
        assert ed.load_latest_scorecard() is None


class TestLoadPortfolioGrouped:
    def test_empty_portfolio_returns_empty(self, db_path):
        assert ed.load_portfolio_grouped(db_path=db_path).empty

    def test_violation_precedence_and_grouping(self, db_path):
        # 형태는 analyze_portfolio 실반환에서 복사 (mock-shape 규칙, tests/CLAUDE.md)
        df = pd.DataFrame(
            [
                # 손절+비중 동시 위반 → stop_loss 우선
                {"ticker": "AAA", "current_value_usd": 5000, "pnl_pct": -12.0, "weight_pct": 20.0, "sector": "Tech"},
                # 비중만 위반
                {"ticker": "BBB", "current_value_usd": 4000, "pnl_pct": 3.0, "weight_pct": 16.0, "sector": "Health"},
                # 정상 — 두 계좌 분산 보유 (grouping 확인)
                {"ticker": "CCC", "current_value_usd": 500, "pnl_pct": 2.0, "weight_pct": 4.0, "sector": "Energy"},
                {"ticker": "CCC", "current_value_usd": 500, "pnl_pct": 4.0, "weight_pct": 4.0, "sector": "Energy"},
            ]
        )
        with patch("nuri.analysis.portfolio.analyze_portfolio", return_value=df):
            grouped = ed.load_portfolio_grouped(db_path=db_path)

        by_ticker = grouped.set_index("ticker")
        assert by_ticker.loc["AAA", "violation"] == "stop_loss"
        assert by_ticker.loc["BBB", "violation"] == "overweight"
        assert by_ticker.loc["CCC", "violation"] is None
        # CCC 합산: value sum / pnl mean / weight sum
        assert by_ticker.loc["CCC", "current_value_usd"] == 1000
        assert by_ticker.loc["CCC", "pnl_pct"] == pytest.approx(3.0)
        assert by_ticker.loc["CCC", "weight_pct"] == pytest.approx(8.0)

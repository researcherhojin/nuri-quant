"""nuri/quant/regime/classifier.py 의 4 partial branches 닫기 (#616 Phase 2).

Branches:
- 455→460: event hint 가 알려진 case 매칭 안 됨 → 모든 elif False → regime 그대로
- 492→498: vix=None → if vix is not None: False → checks 에 VIX-BB 라인 안 추가
- 600→602: print_regime 에서 d.get("vix") None → 출력 skip
- 602→604: print_regime 에서 d.get("fear_greed") None → 출력 skip

`# pragma: no cover` 미사용 (CLAUDE.md ★).
"""

from __future__ import annotations

import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_macro, upsert_prices
from nuri.quant.regime.classifier import RegimeState, classify_regime, print_regime


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "classifier_branches.db"
    init_db(path)
    return path


def _bdates(start: str, n: int) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range(start, periods=n)]


def _seed_spy(db_path, dates, closes):
    df = pd.DataFrame(
        {
            "ticker": "SPY",
            "date": dates,
            "open": closes,
            "high": [c * 1.005 for c in closes],
            "low": [c * 0.995 for c in closes],
            "close": closes,
            "volume": [50_000_000] * len(closes),
            "adj_close": closes,
        }
    )
    upsert_prices(df, db_path)


class TestClassifierBranches:
    """4 partials in classifier.py."""

    def test_classify_no_vix_skips_vix_check(self, db_path):
        """Branch 492→498: vix=None → if vix is not None: False → checks 에 vix-bb 라인 미추가.

        macro 테이블에 vix indicator 자체 없음 → classify_regime 가 vix=None
        → confidence 계산 시 vix-bb 라인 skip → 4번째 check 빠짐.
        """
        # 250 일 SPY (충분) + macro 에 vix 없음
        dates = _bdates("2024-01-02", 250)
        closes = [100.0 + i * 0.1 for i in range(250)]
        _seed_spy(db_path, dates, closes)
        # macro: fear_greed 만 시드 (vix 없음)
        upsert_macro(
            [{"indicator": "fear_greed", "date": d, "value": 55.0, "source": "test"} for d in dates],
            db_path,
        )

        state = classify_regime(date=dates[-1], db_path=db_path)
        assert state is not None
        # vix 분기 미진입 → details.vix is None
        assert state.details.get("vix") is None

    def test_print_regime_no_vix_skips_print(self, capsys):
        """Branch 600→602: print_regime 에서 d.get("vix") None → 출력 skip → 602."""
        state = RegimeState(
            date="2026-01-01",
            trend="bull",
            volatility="low",
            regime="bull_low_vol",
            confidence=0.75,
            details={
                "spy_close": 500.0,
                "sma50": 490.0,
                "sma200": 480.0,
                "sma_diff_pct": 2.1,
                "vix": None,  # 600 False
                "fear_greed": None,  # 602 False
                "rsi": None,
                "bb_width": 0.05,
            },
        )
        print_regime(state)
        out = capsys.readouterr().out
        # vix / fear_greed 라인 미출력
        assert "VIX:" not in out
        assert "Fear&Greed:" not in out

    def test_print_regime_vix_only_skips_fear_greed(self, capsys):
        """Branch 602→604: vix 는 있지만 fear_greed=None → print 단계 분기 separately."""
        state = RegimeState(
            date="2026-01-01",
            trend="bull",
            volatility="low",
            regime="bull_low_vol",
            confidence=0.75,
            details={
                "spy_close": 500.0,
                "sma50": 490.0,
                "sma200": 480.0,
                "sma_diff_pct": 2.1,
                "vix": 18.5,  # 600 True
                "fear_greed": None,  # 602 False
                "rsi": None,
                "bb_width": 0.05,
            },
        )
        print_regime(state)
        out = capsys.readouterr().out
        assert "VIX:" in out
        assert "Fear&Greed:" not in out

    def test_event_hint_unknown_falls_through_to_base_regime(self, db_path, monkeypatch):
        """Branch 455→460: event hint 가 알려진 case (`euphoria`/`stagflation`/`bear_high_vol`/
        `sector_rotation`) 매칭 안 됨 → 모든 elif False → 460 (regime=base).

        EventScore 가 hint='unknown_label' 반환하도록 mock → all elif False → fall-through.
        """
        # 250 일 SPY 시드 (classify 진입 가능)
        dates = _bdates("2024-01-02", 250)
        closes = [100.0 + i * 0.1 for i in range(250)]
        _seed_spy(db_path, dates, closes)
        upsert_macro(
            [{"indicator": "vix", "date": d, "value": 18.0, "source": "test"} for d in dates],
            db_path,
        )

        # EventScore mock: regime_hint = unknown
        from dataclasses import dataclass

        @dataclass
        class FakeEventScore:
            score: float = 5.0
            regime_hint: str = "unknown_hint_value"  # 매칭 case 모두 False

        monkeypatch.setattr(
            "nuri.quant.regime.event_score.compute_event_score",
            lambda *a, **kw: FakeEventScore(),
        )

        state = classify_regime(date=dates[-1], db_path=db_path)
        assert state is not None
        # special_regime 미설정 → base_regime 사용
        assert state.details.get("special_regime") is None

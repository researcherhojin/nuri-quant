"""classifier.py branch coverage — Issue #616 Phase 3-C2.

455→460: event_score hint 이 elif chain 에 매치 안 됨 → special_regime fallback.
"""

from __future__ import annotations


class TestEventScoreHintFallthrough:
    def test_unknown_hint_falls_through_to_base_regime(self, tmp_path, monkeypatch):
        """455→460: hint='bear_high_vol' but score > -15 → 모든 elif False → fall through.

        line 452 의 두번째 조건 (`es.score <= -15`) False, 그 후 455 `sector_rotation` False
        → 460 의 `regime = special_regime if special_regime else base_regime` 로 떨어짐.
        """
        from dataclasses import dataclass

        from nuri.core.db import init_db, upsert_prices

        p = tmp_path / "cls.db"
        init_db(p)

        # SPY 가격 200+일 (classify_regime 동작 조건). 최신 데이터 (freshness check 통과).
        import numpy as np
        import pandas as pd

        from nuri.core.timezone import today_kst

        dates = pd.bdate_range(end=today_kst(), periods=300)
        close = np.linspace(400, 480, 300)  # 우상향 → bull
        upsert_prices(
            pd.DataFrame(
                {
                    "ticker": "SPY",
                    "date": [d.strftime("%Y-%m-%d") for d in dates],
                    "open": close * 0.99,
                    "high": close * 1.01,
                    "low": close * 0.98,
                    "close": close,
                    "volume": [1_000_000] * 300,
                    "adj_close": close,
                }
            ),
            p,
        )

        @dataclass
        class FakeES:
            event_count: int = 5
            score: float = -10  # |score|=10 ≥ 10, but > -15 → 452 elif False
            regime_hint: str = "bear_high_vol"
            category_breakdown: dict | None = None
            dominant_category: str | None = None
            date: str = "2024-01-02"

        # 직접 patch — special_regime 분기 진입 보장.
        monkeypatch.setattr(
            "nuri.quant.regime.event_score.compute_event_score",
            lambda **kw: FakeES(),
        )
        # detect 함수들 None 반환 → special_regime is None → event_score path 진입.
        monkeypatch.setattr(
            "nuri.quant.regime.classifier._detect_euphoria",
            lambda *a, **kw: False,
        )
        monkeypatch.setattr(
            "nuri.quant.regime.classifier._detect_stagflation",
            lambda *a, **kw: False,
        )
        monkeypatch.setattr(
            "nuri.quant.regime.classifier._detect_recovery",
            lambda *a, **kw: False,
        )
        monkeypatch.setattr(
            "nuri.quant.regime.classifier._detect_sector_rotation",
            lambda *a, **kw: False,
        )

        from nuri.quant.regime.classifier import classify_regime

        result = classify_regime(db_path=p)
        # special_regime None → base_regime 그대로 반환.
        assert result is not None
        # 460 line 의 fallback 이 동작했는지 (special_regime 미설정 → base regime).
        assert "_" in result.regime  # base regime 형식 (e.g., bull_low_vol)

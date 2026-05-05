"""nuri/trading/agents/wallstreet.py 의 6 partial branches 닫기 (#616 Phase 2).

각 분기는 yfinance mock 의 특정 데이터 shape 으로 트리거:
- 88→91: upgrades=0 + downgrades=0 → if/elif/elif 모두 False
- 96→103: targets 가 모두 NaN → empty Series → if False
- 116→119: surprise NaN → 3 elif 모두 False
- 137→133: insider text 가 매칭 키워드 (purchase/buy/sale/sell) 없음 → continue
- 143→147: insider buys/sells 둘 다 작아 두 elif False
- 164→184: consensus total=0 → if False

`# pragma: no cover` 미사용 (CLAUDE.md ★).
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from nuri.core.db import init_db


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "wallstreet_branches.db"
    init_db(path)
    return path


def _patch_ticker(monkeypatch, *, ud=None, eh=None, ins=None, rec=None):
    """yfinance.Ticker 를 4 가지 데이터 슬롯만 가진 MockTicker 로 대체."""

    class MockTicker:
        def __init__(self, ticker):
            self.upgrades_downgrades = ud
            self.earnings_history = eh
            self.insider_transactions = ins
            self.recommendations = rec

    import yfinance

    monkeypatch.setattr(yfinance, "Ticker", MockTicker)


class TestWallStreetBranches:
    """6 partial branches in wallstreet.py — yfinance mock + 분기 강제."""

    def test_zero_upgrades_zero_downgrades_skips_all_elif(self, db_path, monkeypatch):
        """Branch 88→91: upgrades=0 AND downgrades=0 → 3 elif (`>`, `<`, `> 0 or > 0`)
        모두 False → 91 (data_points 진행).

        Action 컬럼 임의 값 (action mapping 안 됨) + priceTargetAction 임의 값 →
        upgrades / downgrades 모두 0.
        """
        ud = pd.DataFrame(
            [
                {"Action": "init", "priceTargetAction": "main", "currentPriceTarget": 100.0},
                {"Action": "reit", "priceTargetAction": "main", "currentPriceTarget": 105.0},
            ],
            index=[datetime.now()] * 2,
        )
        _patch_ticker(monkeypatch, ud=ud)

        from nuri.trading.agents.wallstreet import WallStreetAgent

        v = WallStreetAgent().analyze("ZERO", db_path=db_path)
        # 등급변경 메시지 없음 (모든 elif False) — 분기 88→91 통과
        assert "업그레이드" not in v.reasoning
        assert "다운그레이드" not in v.reasoning

    def test_targets_all_nan_skips_avg_target(self, db_path, monkeypatch):
        """Branch 96→103: targets 가 모두 NaN → notna() 필터 후 empty Series →
        `if not targets.empty:` False → 103 (다음 try block).
        """
        ud = pd.DataFrame(
            [
                {"Action": "main", "priceTargetAction": "", "currentPriceTarget": float("nan")},
                {"Action": "main", "priceTargetAction": "", "currentPriceTarget": float("nan")},
            ],
            index=[datetime.now()] * 2,
        )
        _patch_ticker(monkeypatch, ud=ud)

        from nuri.trading.agents.wallstreet import WallStreetAgent

        v = WallStreetAgent().analyze("NAN_TGT", db_path=db_path)
        # avg_target 키 없음 (전체 NaN → empty)
        assert "avg_target" not in v.data_points

    def test_surprise_nan_skips_all_elif(self, db_path, monkeypatch):
        """Branch 116→119: surprise=NaN → 3 elif (`>`, `<`, `<=`) 모두 False (NaN 비교).
        → 119 (data_points 진행).
        """
        eh = pd.DataFrame([{"surprisePercent": float("nan"), "epsActual": 0.0, "epsEstimate": 0.0}])
        _patch_ticker(monkeypatch, eh=eh)

        from nuri.trading.agents.wallstreet import WallStreetAgent

        v = WallStreetAgent().analyze("NAN_SURP", db_path=db_path)
        # 실적 메시지 없음 (모든 elif False)
        assert "서프라이즈" not in v.reasoning
        assert "미스" not in v.reasoning
        assert "부합" not in v.reasoning

    def test_insider_text_no_keyword_continues(self, db_path, monkeypatch):
        """Branch 137→133: insider Text 가 매칭 키워드 없음 → 두 if/elif 모두 False
        → for loop 다음 iteration (133).
        """
        ins = pd.DataFrame(
            [
                {"Text": "Form 4 filed"},  # 키워드 없음 → continue
                {"Text": "Routine disclosure"},  # 키워드 없음 → continue
                {"Text": "Quarterly report"},  # 키워드 없음 → continue
            ]
        )
        _patch_ticker(monkeypatch, ins=ins)

        from nuri.trading.agents.wallstreet import WallStreetAgent

        v = WallStreetAgent().analyze("NO_KW", db_path=db_path)
        # 내부자 메시지 없음 (buys=0, sells=0)
        assert "내부자" not in v.reasoning

    def test_insider_low_volume_skips_both_elif(self, db_path, monkeypatch):
        """Branch 143→147: buys / sells 모두 margin 미달 → 두 elif False → 147."""
        ins = pd.DataFrame(
            [
                {"Text": "Purchase of 100 shares"},
                {"Text": "Sale of 100 shares"},
            ]
        )
        _patch_ticker(monkeypatch, ins=ins)

        from nuri.trading.agents.wallstreet import WallStreetAgent

        v = WallStreetAgent().analyze("LOW_INS", db_path=db_path)
        # buys=1, sells=1 — margin 미달 → 메시지 없음
        assert "순매수" not in v.reasoning
        assert "순매도" not in v.reasoning

    def test_consensus_zero_total_skips_all_branches(self, db_path, monkeypatch):
        """Branch 164→184: total=0 (모든 카테고리 0) → if False → 184 (try 종료)."""
        rec = pd.DataFrame([{"strongBuy": 0, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0}])
        _patch_ticker(monkeypatch, rec=rec)

        from nuri.trading.agents.wallstreet import WallStreetAgent

        v = WallStreetAgent().analyze("ZERO_REC", db_path=db_path)
        # 컨센서스 메시지 없음 (total=0)
        assert "컨센서스" not in v.reasoning

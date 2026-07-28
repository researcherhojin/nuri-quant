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

    def test_mixed_rating_changes_are_reported_without_scoring(self, db_path, monkeypatch):
        """라인 89: 업/다운이 둘 다 있으나 어느 쪽도 margin(2)을 못 넘김.

        점수는 0 이지만 "등급변경이 있었다" 는 사실은 근거에 남아야 한다 — 여기가
        비면 애널리스트 활동이 활발한 종목과 아무 커버리지 없는 종목이 같은 얼굴이
        된다 (후자는 아래 `if not reasons` 로 '데이터 부족' HOLD).
        """
        ud = pd.DataFrame(
            [
                {"Action": "up", "priceTargetAction": "", "currentPriceTarget": float("nan")},
                {"Action": "down", "priceTargetAction": "", "currentPriceTarget": float("nan")},
            ],
            index=[datetime.now()] * 2,
        )
        _patch_ticker(monkeypatch, ud=ud)

        from nuri.trading.agents.wallstreet import WallStreetAgent

        v = WallStreetAgent().analyze("MIXED", db_path=db_path)
        assert "등급변경 혼조(1↑/1↓)" in v.reasoning
        assert v.action == "HOLD", "점수 0 인데 방향이 잡혔다"
        assert "데이터 부족" not in v.reasoning

    def test_strong_signals_reach_the_buy_branch(self, db_path, monkeypatch):
        """라인 189: score >= score_buy(3) → BUY + confidence 공식.

        업그레이드 우세(+2) + 실적 서프라이즈(+2) = 4. BUY 분기는 이 에이전트가
        낼 수 있는 유일한 매수 신호라, 한 번도 실행되지 않은 채로 두면 confidence
        공식이 cap 을 넘기거나 normalize 에서 깨져도 아무도 모른다.
        """
        ud = pd.DataFrame(
            [{"Action": "up", "priceTargetAction": "raises", "currentPriceTarget": float("nan")}] * 2,
            index=[datetime.now()] * 2,
        )
        eh = pd.DataFrame([{"surprisePercent": 0.20, "epsActual": 1.2, "epsEstimate": 1.0}])
        _patch_ticker(monkeypatch, ud=ud, eh=eh)

        from nuri.trading.agents.wallstreet import WallStreetAgent

        v = WallStreetAgent().analyze("STRONG", db_path=db_path)
        assert v.action == "BUY"
        # raw = min(buy_cap 85, buy_base 45 + score 4 × 10 = 85) = 85 → cap 에 정확히 걸림.
        # 표출값은 base.normalize_confidence 가 agents.yaml 스케일로 재매핑한 결과다.
        from nuri.trading.agents.wallstreet import WallStreetAgent as _W

        assert v.confidence == pytest.approx(round(_W().normalize_confidence(85.0), 1))
        assert 0 <= v.confidence <= 100

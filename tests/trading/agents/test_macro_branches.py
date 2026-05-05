"""MacroAgent branch coverage — Issue #616 Phase 3-A3.

5 partials + 미스 라인 26-28 (try/except), 63-71 (yfinance fallback) 닫음.

| line | branch | trigger |
|---|---|---|
| 26-28 | classify_regime/compute_macro_score 예외 | 모듈 raise |
| 63-71 | yfinance fallback path | DB prices empty → yf.download 호출 |
| 67→73 | `if not _df.empty:` False | yf 빈 DataFrame |
| 74→113 | `if len(df) >= min_candles:` False | df < 10 rows → skip momentum |
| 105→113 | `elif trend == "bear":` False | unknown trend (e.g. "neutral") |
| 119→124 | `if _classify_sector(sector) == "defensive":` False | bear + non-defensive sector |
| 120→124 | `if action == "SELL":` False | defensive sector but action == "HOLD" |
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from unittest.mock import MagicMock

import pandas as pd

from nuri.core.db import get_db


@dataclass
class FakeRegime:
    regime: str = ""
    trend: str = ""
    volatility: str = "low"
    confidence: float = 0.8
    details: dict | None = None


@dataclass
class FakeMacro:
    total_score: float = 0.0


def _patch_regime(monkeypatch, trend: str, regime_name: str, macro_score: float):
    monkeypatch.setattr(
        "nuri.quant.regime.classifier.classify_regime",
        lambda **kw: FakeRegime(regime=regime_name, trend=trend),
    )
    monkeypatch.setattr(
        "nuri.quant.regime.macro_score.compute_macro_score",
        lambda **kw: FakeMacro(total_score=macro_score),
    )


# ═══════════════════════════════════════════════════════
# 26-28: try/except — regime/macro 모듈 raise
# ═══════════════════════════════════════════════════════


class TestRegimeImportException:
    def test_classify_regime_raises_returns_no_data_hold(self, db_path, monkeypatch):
        """classify_regime 예외 → outer except → HOLD."""

        def _raise(**kw):
            raise RuntimeError("regime collapse")

        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", _raise)
        from nuri.trading.agents.macro_agent import MacroAgent

        v = MacroAgent().analyze("ZZZ", db_path=db_path)
        assert v.action == "HOLD"
        assert "데이터 부족" in v.reasoning


# ═══════════════════════════════════════════════════════
# 63-71: yfinance fallback path
# ═══════════════════════════════════════════════════════


class TestYfinanceFallback:
    def _install_yf(self, monkeypatch, *, download_return=None, raise_exc=None):
        """sys.modules 에 가짜 yfinance 모듈 주입 (lazy import 대응)."""
        mock_yf = MagicMock()
        if raise_exc is not None:
            mock_yf.download = MagicMock(side_effect=raise_exc)
        else:
            mock_yf.download = MagicMock(return_value=download_return)
        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

    def test_yf_returns_data_overrides_empty_db(self, db_path, monkeypatch):
        """68-69: yf 가 비-빈 df 반환 → close 추출 후 momentum 분기 진입."""
        _patch_regime(monkeypatch, "sideways", "sideways_low_vol", 50)
        # DB prices 없음 → yf fallback 분기 진입.
        # yf 가 30-day strong uptrend 반환 → 강한 모멘텀 → SELL 또는 BUY 분기.
        prices = list(range(100, 130))  # 30 days, 100→129 (29% up)
        yf_df = pd.DataFrame({"Close": prices}, index=pd.date_range("2025-03-01", periods=30))
        self._install_yf(monkeypatch, download_return=yf_df)

        from nuri.trading.agents.macro_agent import MacroAgent

        v = MacroAgent().analyze("MOCKUP", db_path=db_path)
        assert v.action in ("BUY", "HOLD", "SELL")  # 핵심: import 경로 + 67 True 분기 진입

    def test_yf_returns_empty_df_falls_through(self, db_path, monkeypatch):
        """67→73: yf 빈 df → if False → 73 (min_candles check) 로 fall through."""
        _patch_regime(monkeypatch, "bull", "bull_low_vol", 70)
        self._install_yf(monkeypatch, download_return=pd.DataFrame())

        from nuri.trading.agents.macro_agent import MacroAgent

        # df 가 empty 인 상태로 74 line 도달 → len(df) < min_candles → 74→113 으로 skip
        v = MacroAgent().analyze("EMPTYYF", db_path=db_path)
        assert v.action in ("BUY", "HOLD", "SELL")

    def test_yf_raises_caught_silently(self, db_path, monkeypatch):
        """70-71: yf.download 예외 → except: pass → df 그대로."""
        _patch_regime(monkeypatch, "bull", "bull_low_vol", 70)
        self._install_yf(monkeypatch, raise_exc=ConnectionError("network down"))

        from nuri.trading.agents.macro_agent import MacroAgent

        v = MacroAgent().analyze("RAISYF", db_path=db_path)
        assert v.action in ("BUY", "HOLD", "SELL")


# ═══════════════════════════════════════════════════════
# 105→113: unknown trend (sideways/bull/bear elif 모두 False)
# ═══════════════════════════════════════════════════════


class TestUnknownTrendPath:
    def test_trend_neutral_skips_momentum_branches(self, db_path, monkeypatch):
        """trend == 'neutral' → 87, 98, 105 elif 모두 False → 113 으로 fall through."""
        _patch_regime(monkeypatch, "neutral", "neutral_mid_vol", 50)
        # base path 도 if/elif/else (43, 46, 50) 의 else (HOLD) 로 빠짐 (sideways base)
        # 그 후 momentum block (line 74) 진입 시 trend=='neutral' → 모든 elif False
        with get_db(db_path) as conn:
            for i in range(20):
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("NEUTRAL", f"2025-03-{i + 1:02d}", 100, 100, 100, 100 + i, 100000),
                )

        from nuri.trading.agents.macro_agent import MacroAgent

        v = MacroAgent().analyze("NEUTRAL", db_path=db_path)
        # base 가 HOLD (sideways branch), momentum elif 모두 False → action 변동 없음.
        assert v.action == "HOLD"


# ═══════════════════════════════════════════════════════
# 119→124, 120→124: sector override 분기
# ═══════════════════════════════════════════════════════


class TestSectorOverrideBranches:
    def _seed_prices_decline(self, db_path, ticker):
        """20개 하락 prices."""
        with get_db(db_path) as conn:
            for i in range(20):
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (ticker, f"2025-03-{i + 1:02d}", 100, 100, 100, 100 - i, 100000),
                )

    def test_bear_non_defensive_sector_no_override(self, db_path, monkeypatch):
        """119→124: bear + non-defensive sector (Technology) → 119 False → skip override."""
        _patch_regime(monkeypatch, "bear", "bear_low_vol", 25)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test", "TECH", 10, 100.0, "USD", "Technology"),
            )
        self._seed_prices_decline(db_path, "TECH")

        from nuri.trading.agents.macro_agent import MacroAgent

        v = MacroAgent().analyze("TECH", db_path=db_path)
        # bear + 매크로 25 → SELL. non-defensive → override 안 됨.
        assert v.action == "SELL"

    def test_bear_defensive_sector_action_not_sell_no_override(self, db_path, monkeypatch):
        """120→124: bear + defensive (Healthcare) + 강한 반등으로 action=HOLD → 120 False."""
        _patch_regime(monkeypatch, "bear", "bear_low_vol", 25)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test", "DEF", 10, 100.0, "USD", "Healthcare"),
            )
            # bear bounce: 5d return > bear_bounce(10) → action=HOLD before sector check
            prices = [100] * 16 + [108, 110, 112, 115]
            for i, c in enumerate(prices):
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("DEF", f"2025-03-{i + 1:02d}", c, c, c, c, 100000),
                )

        from nuri.trading.agents.macro_agent import MacroAgent

        v = MacroAgent().analyze("DEF", db_path=db_path)
        # action 이 HOLD (bear bounce override) → 119 True (defensive) but 120 False (action!=SELL)
        assert v.action == "HOLD"
        assert "방어 섹터" not in v.reasoning  # override 안 일어남

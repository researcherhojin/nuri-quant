"""Bucket E3 — branch coverage gaps in recommend/candidates, recommend/rebalance,
and execution/broker after PR #593-#595.

Each test cites the exact source lines it locks. All tests behavioural — no
isinstance/None/smoke. DB tests use `tmp_path` + `init_db(path)` per
`tests/CLAUDE.md` isolation rule.

Targets:
- candidates.py: 239 (SHADOW skip), 255-256 (scored stats path), 262-267 (3 tier
  branches), 277-283 (SELL+catalyst both branches), 322-337 (regime_stats vs
  pf_normalized fallback), 358-359 (drift mult), 366-372 (tier note branches),
  374 (scorecard_stale note), 376 (total_trades note), 380 (drift critical note),
  427-428 (conflict-detection exception swallow).
- rebalance.py: 110-111 (signal_map TIER_ACTIONABLE), 155-157 (minimal HOLD),
  218-225 (main() entrypoint).
- broker.py: 141 (_request returns r.json()), 230-245 (main() entrypoint).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import (
    get_db,
    init_db,
    upsert_macro,
    upsert_portfolio,
    upsert_prices,
)

# ════════════════════════════════════════════════════════════════════
# Fixture — DB with enough price history that compute_indicators succeeds
# (>= 50 bars, ideally 200+ for SMA200 to populate)
# ════════════════════════════════════════════════════════════════════


@pytest.fixture
def db_with_one_ticker(tmp_path):
    """Single-ticker DB with 250 bdays of clean price + a recent VIX reading.

    250 bars > 200 SMA window so all indicators compute. compute_indicators는
    내부에서 SMA-200까지 사용하므로 200+ 권장.
    """
    path = tmp_path / "test.db"
    init_db(path)

    upsert_portfolio(
        [
            {
                "account": "test",
                "ticker": "TESTX",
                "quantity": 10,
                "avg_price": 100.0,
                "currency": "USD",
                "sector": "Technology",
            }
        ],
        path,
    )

    dates = pd.bdate_range("2024-01-01", periods=250)
    np.random.seed(7)
    base = np.linspace(100, 130, 250) + np.random.normal(0, 1.5, 250)
    df = pd.DataFrame(
        {
            "ticker": "TESTX",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": base * 0.99,
            "high": base * 1.02,
            "low": base * 0.98,
            "close": base,
            "volume": [1_000_000] * 250,
            "adj_close": base,
        }
    )
    upsert_prices(df, path)

    # 평온한 VIX (<25 → "normal")
    upsert_macro(
        [{"indicator": "vix", "date": "2024-12-30", "value": 15.0, "source": "test"}],
        path,
    )
    return path


# ════════════════════════════════════════════════════════════════════
# candidates.py
# ════════════════════════════════════════════════════════════════════


class TestShadowSignalSkipped:
    """Line 238-239: `if not is_actionable(signal_id): continue` — structural
    barrier preventing SHADOW signals from polluting candidate emission.

    Two locks:
    1. SHADOW signal_ids (yield_curve_inversion, hy_oas_widening) never appear
       in `screen_candidates()` output (high-level invariant).
    2. If a future signal slips into `SIGNAL_DEFINITIONS` with `actionable=False`
       (e.g. someone removes `scope: market_wide` without unsetting `actionable`),
       line 239 must skip it. Lock-test 2 forces this path by stubbing
       `is_actionable` to return False for an existing actionable signal.
    """

    def test_shadow_never_in_candidates(self, db_with_one_ticker, monkeypatch):
        from nuri.core.signal_config import list_shadow_signals
        from nuri.trading.recommend import candidates as cnd
        from nuri.trading.recommend.candidates import screen_candidates

        called_for: list[str] = []

        def fake_detect(df, signal_id):
            called_for.append(signal_id)
            return [len(df) - 1]

        monkeypatch.setattr(cnd, "detect_signal_entries", fake_detect)
        monkeypatch.setattr(cnd, "_load_scorecard", lambda: ({}, None))
        monkeypatch.setattr(cnd, "_get_regime_context", lambda *a, **kw: None)
        monkeypatch.setattr(cnd, "_get_drift_map", lambda *a, **kw: {})

        result = screen_candidates(lookback_days=5, db_path=db_with_one_ticker)

        shadow = list_shadow_signals()
        assert shadow, "SHADOW signal set must be non-empty for this lock"
        emitted_signals = {c.signal_id for c in result}
        assert not (emitted_signals & shadow), "SHADOW signals must never appear as candidates"

    def test_actionable_false_signal_skipped(self, db_with_one_ticker, monkeypatch):
        """Line 238-239 lock: if a SIGNAL_DEFINITIONS entry returns
        is_actionable=False, the candidate loop must `continue` past it
        (no detect_signal_entries call, no Candidate emitted).

        We monkeypatch `is_actionable` at the import path used inside
        screen_candidates (`nuri.core.signal_config.is_actionable`) to mark
        `rsi_oversold` non-actionable, then verify it does NOT emit despite
        a stubbed detect_signal_entries that would otherwise trigger.
        """
        from nuri.trading.recommend import candidates as cnd
        from nuri.trading.recommend.candidates import screen_candidates

        target = "rsi_oversold"
        called_for: list[str] = []

        def fake_detect(df, signal_id):
            called_for.append(signal_id)
            return [len(df) - 1]  # would emit if reached

        def fake_actionable(sid):
            # `target` is the only signal blocked here
            return sid != target

        monkeypatch.setattr(cnd, "detect_signal_entries", fake_detect)
        monkeypatch.setattr(cnd, "_load_scorecard", lambda: ({}, None))
        monkeypatch.setattr(cnd, "_get_regime_context", lambda *a, **kw: None)
        monkeypatch.setattr(cnd, "_get_drift_map", lambda *a, **kw: {})
        monkeypatch.setattr("nuri.core.signal_config.is_actionable", fake_actionable)

        result = screen_candidates(lookback_days=5, db_path=db_with_one_ticker)

        # Lock 1: target signal NEVER emits a Candidate (line 239 `continue` path)
        assert not any(c.signal_id == target for c in result)
        # Lock 2: detect_signal_entries was NOT called for target (proves
        # `continue` happened *before* detection — not after)
        assert target not in called_for


class TestScoredStatsPath:
    """Lines 254-256: `unscored=False` path — scorecard 에 stats 가 있을 때
    `win_rate=stats.get("win_rate")`, `pf=stats.get("profit_factor")`.

    Lock: scoring_detail.win_rate 가 0.0 이 아니라 scorecard 값과 일치.
    """

    def test_scorecard_values_used(self, db_with_one_ticker, monkeypatch):
        from nuri.trading.recommend import candidates as cnd
        from nuri.trading.recommend.candidates import screen_candidates

        # 30+ trades + PF>=1.0 → TIER_ACTIONABLE 로 가야 lines 255-256 + 267 동시 hit
        scorecard = {
            "rsi_oversold": {
                "win_rate": 0.65,
                "profit_factor": 1.8,
                "avg_return": 0.04,
                "total_trades": 50,
            }
        }

        # detect_signal_entries — rsi_oversold 만 마지막 bar 매칭
        def fake_detect(df, signal_id):
            return [len(df) - 1] if signal_id == "rsi_oversold" else []

        monkeypatch.setattr(cnd, "detect_signal_entries", fake_detect)
        monkeypatch.setattr(cnd, "_load_scorecard", lambda: (scorecard, 1))
        monkeypatch.setattr(cnd, "_get_regime_context", lambda *a, **kw: None)
        monkeypatch.setattr(cnd, "_get_drift_map", lambda *a, **kw: {})

        result = screen_candidates(lookback_days=5, db_path=db_with_one_ticker)

        rsi = [c for c in result if c.signal_id == "rsi_oversold"]
        assert rsi, "rsi_oversold candidate must be emitted"
        c = rsi[0]
        assert c.unscored is False
        assert c.win_rate == pytest.approx(0.65, abs=0.01)
        assert c.profit_factor == pytest.approx(1.8, abs=0.01)
        assert c.tier == "actionable"  # 50 trades >= 30, pf >= 1.0
        # Line 376: stats.get("total_trades") truthy → notes 에 "과거 50건"
        assert "과거 50건" in c.notes


class TestTierLowSampleAndAvoid:
    """Lines 262-267: tier branches.

    - elif total_trades < 30: TIER_ADVISORY (lines 262-263)
    - elif pf < 1.0: TIER_AVOID (lines 264-265)
    - else: TIER_ACTIONABLE (lines 266-267)

    Plus lines 369-372 (note rendering for each tier).
    """

    def test_low_sample_tier_advisory(self, db_with_one_ticker, monkeypatch):
        from nuri.trading.recommend import candidates as cnd
        from nuri.trading.recommend.candidates import screen_candidates

        # total_trades < 30 → ADVISORY (line 262-263)
        scorecard = {
            "rsi_oversold": {
                "win_rate": 0.7,
                "profit_factor": 2.5,
                "avg_return": 0.05,
                "total_trades": 10,  # < 30
            }
        }

        def fake_detect(df, signal_id):
            return [len(df) - 1] if signal_id == "rsi_oversold" else []

        monkeypatch.setattr(cnd, "detect_signal_entries", fake_detect)
        monkeypatch.setattr(cnd, "_load_scorecard", lambda: (scorecard, None))
        monkeypatch.setattr(cnd, "_get_regime_context", lambda *a, **kw: None)
        monkeypatch.setattr(cnd, "_get_drift_map", lambda *a, **kw: {})

        result = screen_candidates(lookback_days=5, db_path=db_with_one_ticker)
        rsi = [c for c in result if c.signal_id == "rsi_oversold"]
        assert rsi
        c = rsi[0]
        assert c.tier == "advisory"
        # Line 370: low-sample note 표시
        assert "low-sample" in c.notes
        assert c.confidence == 0.0  # advisory → confidence=0 (line 320)

    def test_negative_edge_tier_avoid(self, db_with_one_ticker, monkeypatch):
        """Line 264-265, 371-372: PF<1.0 + 30+ trades → TIER_AVOID."""
        from nuri.trading.recommend import candidates as cnd
        from nuri.trading.recommend.candidates import screen_candidates

        scorecard = {
            "rsi_oversold": {
                "win_rate": 0.4,
                "profit_factor": 0.8,  # < 1.0
                "avg_return": -0.02,
                "total_trades": 100,  # >= 30
            }
        }

        def fake_detect(df, signal_id):
            return [len(df) - 1] if signal_id == "rsi_oversold" else []

        monkeypatch.setattr(cnd, "detect_signal_entries", fake_detect)
        monkeypatch.setattr(cnd, "_load_scorecard", lambda: (scorecard, None))
        monkeypatch.setattr(cnd, "_get_regime_context", lambda *a, **kw: None)
        monkeypatch.setattr(cnd, "_get_drift_map", lambda *a, **kw: {})

        result = screen_candidates(lookback_days=5, db_path=db_with_one_ticker)
        rsi = [c for c in result if c.signal_id == "rsi_oversold"]
        assert rsi
        c = rsi[0]
        assert c.tier == "avoid"
        # Line 372: negative-edge note (PF=0.80)
        assert "negative-edge" in c.notes
        assert "0.80" in c.notes


class TestSellCatalystBranches:
    """Lines 276-283: SELL signal + actionable tier → catalyst check 호출.

    - has_recent_catalyst=True (line 282-283): tier 유지, catalyst note 기록
    - has_recent_catalyst=False (line 279-281): tier → ADVISORY, downgrade note

    line 366-368: tier=ADVISORY + catalyst_note startswith "SELL 근거 없음" → 그
    이유 우선 노출.
    """

    def test_sell_with_catalyst_keeps_actionable(self, db_with_one_ticker, monkeypatch):
        # rsi_overbought 가 SELL_SIGNALS 에 있는지 확인하고 사용 (없으면 스킵)
        from nuri.quant.validation.signal_backtest import SELL_SIGNALS
        from nuri.trading.recommend import candidates as cnd
        from nuri.trading.recommend.candidates import screen_candidates

        if "rsi_overbought" not in SELL_SIGNALS:
            pytest.skip("rsi_overbought not classified as SELL")

        scorecard = {
            "rsi_overbought": {
                "win_rate": 0.6,
                "profit_factor": 1.5,
                "avg_return": 0.03,
                "total_trades": 50,
            }
        }

        def fake_detect(df, signal_id):
            return [len(df) - 1] if signal_id == "rsi_overbought" else []

        monkeypatch.setattr(cnd, "detect_signal_entries", fake_detect)
        monkeypatch.setattr(cnd, "_load_scorecard", lambda: (scorecard, None))
        monkeypatch.setattr(cnd, "_get_regime_context", lambda *a, **kw: None)
        monkeypatch.setattr(cnd, "_get_drift_map", lambda *a, **kw: {})
        # has_recent_catalyst → True
        monkeypatch.setattr(
            "nuri.core.catalyst.has_recent_catalyst",
            lambda ticker, db_path=None: (True, "earnings beat"),
        )

        result = screen_candidates(lookback_days=5, db_path=db_with_one_ticker)
        sells = [c for c in result if c.signal_id == "rsi_overbought"]
        assert sells
        c = sells[0]
        assert c.direction == "SELL"
        assert c.tier == "actionable"
        assert c.scoring_detail and c.scoring_detail["catalyst_note"].startswith("catalyst:")

    def test_sell_without_catalyst_downgrades_to_advisory(self, db_with_one_ticker, monkeypatch):
        from nuri.quant.validation.signal_backtest import SELL_SIGNALS
        from nuri.trading.recommend import candidates as cnd
        from nuri.trading.recommend.candidates import screen_candidates

        if "rsi_overbought" not in SELL_SIGNALS:
            pytest.skip("rsi_overbought not classified as SELL")

        scorecard = {
            "rsi_overbought": {
                "win_rate": 0.6,
                "profit_factor": 1.5,
                "avg_return": 0.03,
                "total_trades": 50,
            }
        }

        def fake_detect(df, signal_id):
            return [len(df) - 1] if signal_id == "rsi_overbought" else []

        monkeypatch.setattr(cnd, "detect_signal_entries", fake_detect)
        monkeypatch.setattr(cnd, "_load_scorecard", lambda: (scorecard, None))
        monkeypatch.setattr(cnd, "_get_regime_context", lambda *a, **kw: None)
        monkeypatch.setattr(cnd, "_get_drift_map", lambda *a, **kw: {})
        # has_recent_catalyst → False
        monkeypatch.setattr(
            "nuri.core.catalyst.has_recent_catalyst",
            lambda ticker, db_path=None: (False, "no recent earnings"),
        )

        result = screen_candidates(lookback_days=5, db_path=db_with_one_ticker)
        sells = [c for c in result if c.signal_id == "rsi_overbought"]
        assert sells
        c = sells[0]
        assert c.direction == "SELL"
        assert c.tier == "advisory"  # tier downgraded (line 280)
        # Line 366-368: catalyst-부재 사유가 우선 노출
        assert "SELL 근거 없음" in c.notes


class TestRegimeStatsConfidencePath:
    """Lines 322-331: sig_in_regime trades >= 5 → regime-specific confidence.
    Lines 332-337: else → general pf_normalized confidence.

    Exists in test_candidates.py but doesn't lock the *value*. Here we lock the
    formula `confidence = regime_wr * 60 + pf_cap * 40`.
    """

    def test_regime_specific_confidence_formula(self, db_with_one_ticker, monkeypatch):
        from nuri.trading.recommend import candidates as cnd
        from nuri.trading.recommend.candidates import screen_candidates

        scorecard = {
            "rsi_oversold": {
                "win_rate": 0.5,
                "profit_factor": 1.5,
                "avg_return": 0.02,
                "total_trades": 50,
            }
        }
        regime_ctx = {
            "regime": "bull_low_vol",
            "recommended": [],
            "avoid": [],
            "position": "normal",
            "regime_stats": {
                # trades >= 5 → 데이터 기반 path
                "rsi_oversold": {"win_rate": 0.8, "pf": 4.0, "trades": 10},
            },
        }

        def fake_detect(df, signal_id):
            return [len(df) - 1] if signal_id == "rsi_oversold" else []

        monkeypatch.setattr(cnd, "detect_signal_entries", fake_detect)
        monkeypatch.setattr(cnd, "_load_scorecard", lambda: (scorecard, None))
        monkeypatch.setattr(cnd, "_get_regime_context", lambda *a, **kw: regime_ctx)
        monkeypatch.setattr(cnd, "_get_drift_map", lambda *a, **kw: {})

        result = screen_candidates(lookback_days=5, db_path=db_with_one_ticker)
        rsi = [c for c in result if c.signal_id == "rsi_oversold"]
        assert rsi
        c = rsi[0]
        # 0.8 * 60 + min(4.0/5.0, 1.0) * 40 = 48 + 32 = 80
        assert c.scoring_detail["base_confidence"] == pytest.approx(80.0)
        assert c.scoring_detail["regime_win_rate"] == pytest.approx(0.8)
        assert c.scoring_detail["regime_pf"] == pytest.approx(4.0)


class TestDriftMultiplierApplied:
    """Lines 357-359: drift_status in DRIFT_MULTIPLIERS → confidence *= mult.
    Line 379-380: drift_status in (critical, degrading) → notes 에 표시.
    """

    def test_critical_drift_halves_confidence(self, db_with_one_ticker, monkeypatch):
        from nuri.trading.recommend import candidates as cnd
        from nuri.trading.recommend.candidates import screen_candidates

        scorecard = {
            "rsi_oversold": {
                "win_rate": 0.6,
                "profit_factor": 2.0,
                "avg_return": 0.03,
                "total_trades": 50,
            }
        }
        # critical drift → multiplier=0.3
        drift_map = {"rsi_oversold": {"status": "critical", "drift_pct": -45.0}}

        def fake_detect(df, signal_id):
            return [len(df) - 1] if signal_id == "rsi_oversold" else []

        monkeypatch.setattr(cnd, "detect_signal_entries", fake_detect)
        monkeypatch.setattr(cnd, "_load_scorecard", lambda: (scorecard, None))
        monkeypatch.setattr(cnd, "_get_regime_context", lambda *a, **kw: None)
        monkeypatch.setattr(cnd, "_get_drift_map", lambda *a, **kw: drift_map)

        result = screen_candidates(lookback_days=5, db_path=db_with_one_ticker)
        rsi = [c for c in result if c.signal_id == "rsi_oversold"]
        assert rsi
        c = rsi[0]
        assert c.scoring_detail["drift_multiplier"] == 0.3
        assert c.scoring_detail["drift_status"] == "critical"
        # Line 379-380: notes 에 drift 표시
        assert "성과critical" in c.notes
        # Line 354: drift_status 가 dataclass field 에도 기록
        assert c.drift_status == "critical"


class TestStaleScorecard:
    """Line 374: scorecard_stale → notes 에 "스코어카드 N일 전".

    scorecard_age_days > 7 트리거 (line 197 → scorecard_stale=True).
    """

    def test_stale_scorecard_note(self, db_with_one_ticker, monkeypatch):
        from nuri.trading.recommend import candidates as cnd
        from nuri.trading.recommend.candidates import screen_candidates

        scorecard = {
            "rsi_oversold": {
                "win_rate": 0.6,
                "profit_factor": 2.0,
                "avg_return": 0.03,
                "total_trades": 50,
            }
        }

        def fake_detect(df, signal_id):
            return [len(df) - 1] if signal_id == "rsi_oversold" else []

        monkeypatch.setattr(cnd, "detect_signal_entries", fake_detect)
        # age=10 > 7 → stale
        monkeypatch.setattr(cnd, "_load_scorecard", lambda: (scorecard, 10))
        monkeypatch.setattr(cnd, "_get_regime_context", lambda *a, **kw: None)
        monkeypatch.setattr(cnd, "_get_drift_map", lambda *a, **kw: {})

        result = screen_candidates(lookback_days=5, db_path=db_with_one_ticker)
        rsi = [c for c in result if c.signal_id == "rsi_oversold"]
        assert rsi
        c = rsi[0]
        # Line 374: stale note
        assert "10일 전" in c.notes


class TestConflictDetectionExceptionSwallowed:
    """Lines 426-428: conflict detection raises → except logs and continues.

    Lock: 후보는 여전히 정상 반환되고, 로그에는 'Conflict detection 실패' 가 찍힘.
    """

    def test_conflict_detect_exception_does_not_break_screen(self, db_with_one_ticker, monkeypatch, caplog):
        from nuri.trading.recommend import candidates as cnd
        from nuri.trading.recommend.candidates import screen_candidates

        scorecard = {
            "rsi_oversold": {
                "win_rate": 0.6,
                "profit_factor": 2.0,
                "avg_return": 0.03,
                "total_trades": 50,
            }
        }

        def fake_detect(df, signal_id):
            return [len(df) - 1] if signal_id == "rsi_oversold" else []

        def boom(*args, **kwargs):
            raise RuntimeError("synthetic conflict error")

        monkeypatch.setattr(cnd, "detect_signal_entries", fake_detect)
        monkeypatch.setattr(cnd, "_load_scorecard", lambda: (scorecard, None))
        monkeypatch.setattr(cnd, "_get_regime_context", lambda *a, **kw: None)
        monkeypatch.setattr(cnd, "_get_drift_map", lambda *a, **kw: {})
        monkeypatch.setattr("nuri.trading.engine.conflicts.detect_conflicts", boom)

        with caplog.at_level("DEBUG", logger="nuri.trading.recommend.candidates"):
            result = screen_candidates(lookback_days=5, db_path=db_with_one_ticker)

        # 후보는 정상 반환
        assert any(c.signal_id == "rsi_oversold" for c in result)
        # 로그에 swallow 흔적
        assert any("Conflict detection 실패" in rec.message for rec in caplog.records)


# ════════════════════════════════════════════════════════════════════
# rebalance.py
# ════════════════════════════════════════════════════════════════════


class TestRebalanceSignalMapActionable:
    """Lines 109-111: signal_map populated only for `regime_fit AND
    tier == TIER_ACTIONABLE` candidates. Lock: actionable 후보의 signal_id 가
    해당 ticker 의 signals 에 등장.
    """

    def test_actionable_candidate_signal_attached(self, tmp_path, monkeypatch):
        from nuri.trading.recommend.candidates import (
            TIER_ACTIONABLE,
            TIER_ADVISORY,
            Candidate,
        )
        from nuri.trading.recommend.rebalance import regime_aware_rebalance

        path = tmp_path / "test.db"
        init_db(path)

        @dataclass
        class MockRegime:
            regime: str = "bull_low_vol"

        @dataclass
        class MockStrategy:
            position_sizing: str = "normal"

        base_df = pd.DataFrame(
            {
                "ticker": ["AAPL"],
                "sector": ["Technology"],
                "current_weight": [10.0],
                "optimal_weight": [20.0],
                "trade_value_usd": [5000],
                "action": ["BUY"],
            }
        )

        # 두 후보: 하나는 actionable, 하나는 advisory → signal_map 에 actionable
        # 만 들어가야 함 (line 110 구문 정확도 lock)
        candidates_list = [
            Candidate(
                ticker="AAPL",
                signal_id="rsi_oversold",
                signal_date="2026-05-04",
                direction="BUY",
                confidence=70.0,
                win_rate=0.6,
                profit_factor=1.8,
                regime_fit=True,
                price=180.0,
                notes="",
                tier=TIER_ACTIONABLE,
            ),
            Candidate(
                ticker="AAPL",
                signal_id="bb_bounce",
                signal_date="2026-05-04",
                direction="BUY",
                confidence=0.0,
                win_rate=0.0,
                profit_factor=0.0,
                regime_fit=True,
                price=180.0,
                notes="",
                tier=TIER_ADVISORY,  # filter out
                unscored=True,
            ),
        ]

        monkeypatch.setattr("nuri.analysis.rebalance.analyze_rebalance", lambda **kw: base_df)
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: MockRegime(),
        )
        monkeypatch.setattr(
            "nuri.quant.regime.strategy_map.map_regime_to_strategy",
            lambda *a, **kw: MockStrategy(),
        )
        monkeypatch.setattr(
            "nuri.trading.recommend.candidates.screen_candidates",
            lambda **kw: candidates_list,
        )
        monkeypatch.setattr(
            "nuri.trading.engine.conflicts.detect_conflicts",
            lambda *a, **kw: [],
        )

        actions = regime_aware_rebalance(db_path=path)

        aapl = [a for a in actions if a.ticker == "AAPL"][0]
        assert "rsi_oversold(BUY)" in aapl.signals
        assert all("bb_bounce" not in s for s in aapl.signals), (
            "advisory tier candidate must not pollute signal_map (line 110)"
        )


class TestRebalanceMinimalBlocksNewBuys:
    """Lines 154-157: position == "minimal" + diff > 0 (would-be BUY) → HOLD,
    adj_w pinned to cur_w, regime_note '신규 매수 차단'.
    """

    def test_minimal_position_blocks_new_buy(self, tmp_path, monkeypatch):
        from nuri.trading.recommend.rebalance import regime_aware_rebalance

        path = tmp_path / "test.db"
        init_db(path)

        @dataclass
        class MockRegime:
            regime: str = "bear_high_vol"

        @dataclass
        class MockStrategy:
            position_sizing: str = "minimal"

        # diff>0 (would-be BUY) but minimal position 이라 HOLD 강제. conflict
        # tickers 와 별도 path: line 150 (conflict) → False, line 154 (minimal)
        # → True 가 분기되도록 conflict_tickers 가 비어 있어야 함.
        base_df = pd.DataFrame(
            {
                "ticker": ["NEW"],
                "sector": ["Technology"],
                "current_weight": [5.0],
                "optimal_weight": [25.0],  # diff > 0 (would-be BUY)
                "trade_value_usd": [10000],
                "action": ["BUY"],
            }
        )

        monkeypatch.setattr("nuri.analysis.rebalance.analyze_rebalance", lambda **kw: base_df)
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: MockRegime(),
        )
        monkeypatch.setattr(
            "nuri.quant.regime.strategy_map.map_regime_to_strategy",
            lambda *a, **kw: MockStrategy(),
        )
        monkeypatch.setattr(
            "nuri.trading.recommend.candidates.screen_candidates",
            lambda **kw: [],
        )
        monkeypatch.setattr(
            "nuri.trading.engine.conflicts.detect_conflicts",
            lambda *a, **kw: [],
        )

        actions = regime_aware_rebalance(db_path=path)
        new_act = [a for a in actions if a.ticker == "NEW"][0]
        assert new_act.action == "HOLD"  # line 155
        assert new_act.target_weight == new_act.current_weight  # line 156: adj_w=cur_w
        assert "신규 매수 차단" in new_act.regime_note  # line 157


class TestRebalanceMain:
    """Lines 217-228: main() entrypoint — argparse + regime_aware_rebalance +
    print_rebalance.
    """

    def test_main_default_args(self, monkeypatch, capsys):
        from nuri.trading.recommend import rebalance as rb

        # regime_aware_rebalance 와 print_rebalance 를 stub 해서 main() 의 본질
        # (argparse → 호출 wiring) 만 lock
        called: dict = {}

        def fake_rebalance(method):
            called["method"] = method
            return ["sentinel"]

        def fake_print(actions):
            called["actions"] = actions

        monkeypatch.setattr(rb, "regime_aware_rebalance", fake_rebalance)
        monkeypatch.setattr(rb, "print_rebalance", fake_print)

        rc = rb.main([])
        assert rc == 0
        assert called["method"] == "rp"  # default
        assert called["actions"] == ["sentinel"]

    def test_main_method_mvo(self, monkeypatch):
        from nuri.trading.recommend import rebalance as rb

        called: dict = {}
        monkeypatch.setattr(
            rb,
            "regime_aware_rebalance",
            lambda method: called.setdefault("method", method) or [],
        )
        monkeypatch.setattr(rb, "print_rebalance", lambda actions: None)

        rc = rb.main(["--method", "mvo"])
        assert rc == 0
        assert called["method"] == "mvo"

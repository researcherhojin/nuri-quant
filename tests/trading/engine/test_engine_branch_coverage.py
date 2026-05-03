"""Lock-tests filling coverage gaps in nuri/trading/engine/.

Targets specific missing branches identified in coverage report 2026-05-04.
"""
# cspell:ignore siege

from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import patch

import pytest

from nuri.core.db import get_db, init_db


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "test.db"
    init_db(p)
    return p


# ─── decisions.py: regime/context branches + outcome neutral ───────────


@dataclass
class _FakeVerdict:
    agent_name: str
    ticker: str = "AAA"
    action: str = "BUY"
    confidence: float = 60.0
    reasoning: str = "test"
    data_points: dict | None = None
    alpha_action: str | None = None
    portfolio_action: str | None = None


@dataclass
class _FakeResult:
    ticker: str = "AAA"
    final_action: str = "BUY"
    final_confidence: float = 70.0
    agreement_rate: float = 0.7
    dissent: list = field(default_factory=list)
    reasoning: str = "synthetic"
    verdicts: list = field(default_factory=lambda: [_FakeVerdict("technical"), _FakeVerdict("risk")])
    divergence_flag: bool = False
    divergence_reason: str = ""
    penalty_applied: bool = False
    pre_penalty_action: str | None = None
    scoring_detail: dict | None = None


class TestSnapshotMarketContext:
    def test_regime_payload_consumed(self, db_path):
        """Lines 234-237: regime payload JSON parsed."""
        from nuri.trading.engine.decisions import _snapshot_market_context

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO pipeline_events (event_type, step, payload, timestamp) VALUES (?, ?, ?, datetime('now'))",
                ("regime_changed", "test", json.dumps({"regime": "bull_low_vol"})),
            )
        ctx = _snapshot_market_context(db_path=db_path)
        assert ctx.get("regime") == "bull_low_vol"

    def test_regime_payload_invalid_json_swallowed(self, db_path):
        """Lines 238-239: malformed JSON → except branch."""
        from nuri.trading.engine.decisions import _snapshot_market_context

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO pipeline_events (event_type, step, payload, timestamp) VALUES (?, ?, ?, datetime('now'))",
                ("regime_changed", "test", "not-json"),
            )
        ctx = _snapshot_market_context(db_path=db_path)
        # No regime extracted, but no crash
        assert "regime" not in ctx or ctx.get("regime") is None

    def test_macro_score_exception_swallowed(self, db_path, monkeypatch):
        """Lines 247-248: compute_macro_score raises → swallowed."""
        from nuri.trading.engine.decisions import _snapshot_market_context

        def boom(**kw):
            raise RuntimeError("synthetic")

        monkeypatch.setattr("nuri.quant.regime.macro_score.compute_macro_score", boom)
        ctx = _snapshot_market_context(db_path=db_path)
        # No macro_score recorded
        assert "macro_score" not in ctx

    def test_vix_and_fear_greed_recorded(self, db_path):
        """Lines 218 + 226: VIX + F&G insertion paths."""
        from nuri.trading.engine.decisions import _snapshot_market_context

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "vix", 22.0),
            )
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "fear_greed", 45.0),
            )
        ctx = _snapshot_market_context(db_path=db_path)
        assert ctx.get("vix") == 22.0
        assert ctx.get("fear_greed") == 45.0


class TestRecordDecisionRegimeContext:
    def test_record_decision_with_regime_in_evidence(self, db_path):
        """Line 102: regime context added to evidence_records."""
        from nuri.trading.engine.decisions import record_decision

        # Seed regime in events so context.regime is populated
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO pipeline_events (event_type, step, payload, timestamp) VALUES (?, ?, ?, datetime('now'))",
                ("regime_changed", "test", json.dumps({"regime": "bull_low_vol"})),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("AAA", "2025-03-25", 100.0),
            )

        result = _FakeResult(ticker="AAA")
        decision_id = record_decision(result, db_path=db_path)
        assert decision_id > 0


class TestTrackOutcomesNeutral:
    def test_neutral_outcome_for_hold(self, db_path):
        """Line 171: action != BUY/SELL → neutral outcome."""
        from datetime import datetime, timedelta

        from nuri.trading.engine.decisions import track_decision_outcomes

        old_date = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%d")

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO decisions (date, ticker, action, confidence, entry_price, outcome) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (old_date, "AAA", "HOLD", 50.0, 100.0, "pending"),
            )
            # Add a price 90d later so pnl_90d is computed
            target_date = (datetime.strptime(old_date, "%Y-%m-%d") + timedelta(days=90)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("AAA", target_date, 110.0),
            )

        updated = track_decision_outcomes(db_path=db_path)
        assert updated >= 1

        with get_db(db_path) as conn:
            row = conn.execute("SELECT outcome FROM decisions WHERE ticker = ?", ("AAA",)).fetchone()
        # HOLD action → neutral
        assert row[0] == "neutral"


# ─── conflicts.py: empty input early returns ──────────────────────────


class TestConflictsBranches:
    def test_no_candidates_returns_empty_list(self, db_path, monkeypatch):
        """Lines 39-44: candidates=None → screen_candidates([]) → return []."""
        from nuri.trading.engine.conflicts import detect_conflicts

        # screen_candidates returns [] → detect_conflicts short-circuits
        monkeypatch.setattr(
            "nuri.trading.recommend.candidates.screen_candidates",
            lambda **kw: [],
        )
        result = detect_conflicts(db_path=db_path)
        assert result == []

    def test_only_non_actionable_filtered_out(self, db_path, monkeypatch):
        """Lines 53-56: actionable filter strips advisory/avoid → empty list."""
        from unittest.mock import MagicMock

        from nuri.trading.engine.conflicts import detect_conflicts
        from nuri.trading.recommend.candidates import TIER_ADVISORY

        adv = MagicMock(
            ticker="AAA",
            tier=TIER_ADVISORY,
            direction="BUY",
            signal_id="adv1",
            regime_fit=True,
            profit_factor=1.0,
        )
        monkeypatch.setattr(
            "nuri.trading.recommend.candidates.screen_candidates",
            lambda **kw: [adv],
        )
        result = detect_conflicts(db_path=db_path)
        assert result == []


# ─── certification / gate / memory / remediation: deleted pure smoke ──
# 이전에 있던 4개 `test_module_imports` 는 import 만 검증 → 컴파일 가능 여부만
# 보장하고 실제 로직 회귀를 잡지 못함. coverage 도 import-time 코드 (모듈
# top-level constant) 만 1줄 늘려 의미 없음. 다른 파일/E2E 테스트가 같은
# import 를 이미 트리거 — 중복. 재작성 가능한 behavior 가 없는 모듈은 별도
# behavioral 테스트가 추가될 때 함께 만든다.

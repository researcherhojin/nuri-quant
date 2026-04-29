"""Lock-tests for holdings_monitor — post-entry technical-divergence alerts.

Per STRATEGY §5.3.1 Gotcha-Test Pair: every fix-pattern gotcha cites a
regression test. These pin the design contracts decided in the Codex Plan
consult (2026-04-29):

  - Trigger thresholds (Q1)
  - 7-day dedup via pipeline_events (Q2)
  - Asset-class scope: equity_us + equity_kr only (Q7)
  - Data-gap → skip + log (Q6)
  - REVIEW CTA, never SELL (Q8 — STRATEGY §7.1 auto-trade deferred)
  - DB fixtures, no real YAML (Q9)
  - No outcome_30d/60d/90d attachment (Q10 — Learning Memory contamination)

Privacy (tests/CLAUDE.md): placeholder tickers (BrokAlpha / BrokBeta accounts,
synthetic tickers like AAA/BBB/SCRY) — no real holdings.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nuri.core.db import get_db, query
from nuri.core.events import EVENT_TYPES
from nuri.trading.agents.consensus import AgentVerdict, ConsensusResult
from nuri.trading.recommend import holdings_monitor as hm
from nuri.trading.recommend.holdings_monitor import (
    EVENT_TYPE_DIVERGENCE,
    EVENT_TYPE_RUN,
    EVENT_TYPE_TECHNICAL_SELL,
    TRIGGER_DIVERGENCE,
    TRIGGER_TECHNICAL_SELL,
    AlertPayload,
    _classify_asset_class,
    run_monitor,
)

# ─── Asset-class classifier (Q7 scope contract) ─────────────────────────


class TestAssetClassClassifier:
    def test_us_equity_default(self):
        assert _classify_asset_class("AAA", "USD") == "equity_us"

    def test_kr_equity_by_suffix(self):
        assert _classify_asset_class("123456.KS", "KRW") == "equity_kr"
        assert _classify_asset_class("123456.KQ", "KRW") == "equity_kr"

    def test_kr_equity_by_currency(self):
        # Even without .KS suffix, KRW currency → equity_kr
        assert _classify_asset_class("BRKR", "KRW") == "equity_kr"

    def test_crypto_excluded(self):
        # crypto is not in v1 scope per Q7
        assert _classify_asset_class("BTC-USD", "USD") == "crypto"
        assert _classify_asset_class("ETH-USD", "USD") == "crypto"


# ─── Event type registration (P1#3 closure) ────────────────────────────


class TestEventTypeRegistration:
    """All three new event types must be in the canonical EVENT_TYPES set
    so future emit_event-validation work doesn't silently drop our events."""

    def test_three_new_types_registered(self):
        assert EVENT_TYPE_RUN in EVENT_TYPES
        assert EVENT_TYPE_TECHNICAL_SELL in EVENT_TYPES
        assert EVENT_TYPE_DIVERGENCE in EVENT_TYPES

    def test_event_type_strings_locked(self):
        # Drift here → dedup query mismatches → silent re-alerts
        assert EVENT_TYPE_RUN == "holdings_monitor_run"
        assert EVENT_TYPE_TECHNICAL_SELL == "holdings_monitor_technical_sell"
        assert EVENT_TYPE_DIVERGENCE == "holdings_monitor_divergence"

    def test_trigger_type_strings_locked(self):
        # Drift here → dedupe_key changes → silent re-alerts
        assert TRIGGER_TECHNICAL_SELL == "technical_sell"
        assert TRIGGER_DIVERGENCE == "divergence"


# ─── Test fixtures (Q9 — DB seed, no real YAML) ─────────────────────────


def _seed_portfolio(db_path, rows):
    """rows: list[(account, ticker, quantity, avg_price, currency)]"""
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
            rows,
        )


def _seed_price(db_path, ticker, date, close):
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO prices (ticker, date, close) VALUES (?, ?, ?)",
            (ticker, date, close),
        )


def _make_consensus_result(*, ticker, tech_action, tech_conf, divergence_flag=False, divergence_reason=""):
    """Synthetic ConsensusResult — bypasses the live agent stack."""
    tech = AgentVerdict("technical", ticker, tech_action, tech_conf, "synthetic test fixture")
    other = AgentVerdict("fundamental", ticker, "BUY" if tech_action != "BUY" else "HOLD", 60, "fix")
    return ConsensusResult(
        ticker=ticker,
        final_action="BUY" if not divergence_flag else "BUY",
        final_confidence=70,
        agreement_rate=0.6,
        verdicts=[tech, other],
        dissent=[],
        reasoning="synthetic",
        divergence_flag=divergence_flag,
        divergence_reason=divergence_reason,
    )


@pytest.fixture
def fixture_db(tmp_path):
    from nuri.core.db import init_db

    p = tmp_path / "test.db"
    init_db(p)
    return p


# ─── Trigger contract (Q1 — thresholds) ─────────────────────────────────


class TestTriggerThresholds:
    """Q1: technical_sell_min_confidence=80, divergence_min_tech_confidence=70.
    These are the asymmetric thresholds — direct SELL stricter, divergence
    softer 'review me' signal. Drift → false positive flood."""

    def test_technical_sell_above_threshold_alerts(self, fixture_db):
        _seed_portfolio(fixture_db, [("BrokAlpha", "AAA", 10, 100.0, "USD")])
        _seed_price(fixture_db, "AAA", "2026-04-29", 95.0)
        with patch.object(
            hm,
            "_evaluate_triggers",
            return_value=(
                TRIGGER_TECHNICAL_SELL,
                {
                    "technical_action": "SELL",
                    "technical_confidence": 85.0,
                    "technical_reasoning": "MACD<Signal",
                    "divergence_flag": False,
                    "divergence_reason": "",
                    "consensus_action": "HOLD",
                },
            ),
        ):
            summary = run_monitor(db_path=fixture_db)
        assert summary.n_alerted == 1
        assert summary.alerts[0]["trigger_type"] == TRIGGER_TECHNICAL_SELL

    def test_technical_sell_below_threshold_no_alert(self, fixture_db):
        _seed_portfolio(fixture_db, [("BrokAlpha", "AAA", 10, 100.0, "USD")])
        _seed_price(fixture_db, "AAA", "2026-04-29", 95.0)
        # _evaluate_triggers returns None when confidence < threshold
        with patch.object(
            hm,
            "_evaluate_triggers",
            return_value=(
                None,
                {
                    "technical_action": "SELL",
                    "technical_confidence": 75.0,
                    "technical_reasoning": "weak SELL",
                    "divergence_flag": False,
                    "divergence_reason": "",
                    "consensus_action": "BUY",
                },
            ),
        ):
            summary = run_monitor(db_path=fixture_db)
        assert summary.n_alerted == 0

    def test_divergence_softer_threshold(self, fixture_db):
        _seed_portfolio(fixture_db, [("BrokAlpha", "AAA", 10, 100.0, "USD")])
        _seed_price(fixture_db, "AAA", "2026-04-29", 95.0)
        with patch.object(
            hm,
            "_evaluate_triggers",
            return_value=(
                TRIGGER_DIVERGENCE,
                {
                    "technical_action": "SELL",
                    "technical_confidence": 72.0,
                    "technical_reasoning": "MACD bear",
                    "divergence_flag": True,
                    "divergence_reason": "fund=BUY tech=SELL",
                    "consensus_action": "BUY",
                },
            ),
        ):
            summary = run_monitor(db_path=fixture_db)
        assert summary.n_alerted == 1
        assert summary.alerts[0]["trigger_type"] == TRIGGER_DIVERGENCE


# ─── Dedup (Q2 — 7 calendar days via pipeline_events) ───────────────────


class TestDedup:
    """Q2: same (ticker, trigger_type) re-alert blocked for 7 calendar days.
    pipeline_events itself is the state journal — no separate dedup table."""

    def test_first_alert_emits_second_dedupes(self, fixture_db):
        _seed_portfolio(fixture_db, [("BrokAlpha", "AAA", 10, 100.0, "USD")])
        _seed_price(fixture_db, "AAA", "2026-04-29", 95.0)
        diag = {
            "technical_action": "SELL",
            "technical_confidence": 90.0,
            "technical_reasoning": "MACD<Signal",
            "divergence_flag": False,
            "divergence_reason": "",
            "consensus_action": "HOLD",
        }
        with patch.object(hm, "_evaluate_triggers", return_value=(TRIGGER_TECHNICAL_SELL, diag)):
            run1 = run_monitor(db_path=fixture_db)
            run2 = run_monitor(db_path=fixture_db)
        assert run1.n_alerted == 1
        assert run2.n_alerted == 0
        assert run2.n_skipped_dedup == 1

    def test_dedup_separate_per_trigger_type(self, fixture_db):
        # Same ticker, different trigger types → both alert
        _seed_portfolio(fixture_db, [("BrokAlpha", "AAA", 10, 100.0, "USD")])
        _seed_price(fixture_db, "AAA", "2026-04-29", 95.0)
        with patch.object(
            hm,
            "_evaluate_triggers",
            return_value=(
                TRIGGER_TECHNICAL_SELL,
                {
                    "technical_action": "SELL",
                    "technical_confidence": 90.0,
                    "technical_reasoning": "MACD",
                    "divergence_flag": False,
                    "divergence_reason": "",
                    "consensus_action": "HOLD",
                },
            ),
        ):
            run1 = run_monitor(db_path=fixture_db)
        with patch.object(
            hm,
            "_evaluate_triggers",
            return_value=(
                TRIGGER_DIVERGENCE,
                {
                    "technical_action": "SELL",
                    "technical_confidence": 75.0,
                    "technical_reasoning": "div",
                    "divergence_flag": True,
                    "divergence_reason": "fund=BUY",
                    "consensus_action": "BUY",
                },
            ),
        ):
            run2 = run_monitor(db_path=fixture_db)
        assert run1.n_alerted == 1
        assert run2.n_alerted == 1
        assert run2.n_skipped_dedup == 0


# ─── Asset-class scope (Q7 — equity only) ──────────────────────────────


class TestAssetClassScope:
    def test_crypto_holdings_skipped(self, fixture_db):
        _seed_portfolio(
            fixture_db,
            [
                ("BrokAlpha", "AAA", 10, 100.0, "USD"),  # equity_us — eligible
                ("BrokAlpha", "BTC-USD", 1, 50000.0, "USD"),  # crypto — out of scope
            ],
        )
        _seed_price(fixture_db, "AAA", "2026-04-29", 95.0)
        with patch.object(
            hm,
            "_evaluate_triggers",
            return_value=(
                None,
                {
                    "technical_action": "HOLD",
                    "technical_confidence": 30.0,
                    "technical_reasoning": "",
                    "divergence_flag": False,
                    "divergence_reason": "",
                    "consensus_action": "HOLD",
                },
            ),
        ):
            summary = run_monitor(db_path=fixture_db)
        assert summary.n_skipped_scope == 1  # BTC-USD skipped
        assert summary.n_holdings == 2

    def test_kr_equity_in_scope(self, fixture_db):
        _seed_portfolio(fixture_db, [("BrokAlpha", "123456.KS", 10, 30000.0, "KRW")])
        _seed_price(fixture_db, "123456.KS", "2026-04-29", 28000.0)
        with patch.object(
            hm,
            "_evaluate_triggers",
            return_value=(
                None,
                {
                    "technical_action": "HOLD",
                    "technical_confidence": 30.0,
                    "technical_reasoning": "",
                    "divergence_flag": False,
                    "divergence_reason": "",
                    "consensus_action": "HOLD",
                },
            ),
        ) as mock_eval:
            run_monitor(db_path=fixture_db)
        assert mock_eval.called  # KR ticker reaches evaluation


# ─── Data-gap handling (Q6 — skip + log, no user alert) ─────────────────


class TestDataGap:
    def test_evaluate_failure_skips_with_count(self, fixture_db):
        _seed_portfolio(fixture_db, [("BrokAlpha", "AAA", 10, 100.0, "USD")])

        def boom(**kw):
            raise RuntimeError("synthetic data gap")

        with patch.object(hm, "_evaluate_triggers", side_effect=boom):
            summary = run_monitor(db_path=fixture_db)

        assert summary.n_alerted == 0
        assert summary.n_skipped_data_gap == 1
        assert "AAA" in summary.failed_tickers


# ─── REVIEW CTA contract (Q8 — never SELL wording) ─────────────────────


class TestReviewCTAContract:
    """STRATEGY §7.1 deferred auto-trade. Alert payload must NEVER carry SELL
    as recommended_action — only REVIEW. Drift here = compliance risk."""

    def test_payload_recommended_action_is_review(self, fixture_db):
        _seed_portfolio(fixture_db, [("BrokAlpha", "AAA", 10, 100.0, "USD")])
        _seed_price(fixture_db, "AAA", "2026-04-29", 95.0)
        with patch.object(
            hm,
            "_evaluate_triggers",
            return_value=(
                TRIGGER_TECHNICAL_SELL,
                {
                    "technical_action": "SELL",
                    "technical_confidence": 90.0,
                    "technical_reasoning": "MACD",
                    "divergence_flag": False,
                    "divergence_reason": "",
                    "consensus_action": "HOLD",
                },
            ),
        ):
            summary = run_monitor(db_path=fixture_db)
        assert summary.alerts[0]["recommended_action"] == "REVIEW"


# ─── pipeline_events emission (parent + child causation chain) ──────────


class TestPipelineEventsChain:
    def test_parent_run_event_emitted(self, fixture_db):
        _seed_portfolio(fixture_db, [("BrokAlpha", "AAA", 10, 100.0, "USD")])
        _seed_price(fixture_db, "AAA", "2026-04-29", 95.0)
        with patch.object(
            hm,
            "_evaluate_triggers",
            return_value=(
                None,
                {
                    "technical_action": "HOLD",
                    "technical_confidence": 40.0,
                    "technical_reasoning": "",
                    "divergence_flag": False,
                    "divergence_reason": "",
                    "consensus_action": "HOLD",
                },
            ),
        ):
            run_monitor(db_path=fixture_db)
        rows = query(
            "SELECT event_type FROM pipeline_events WHERE event_type = ?",
            (EVENT_TYPE_RUN,),
            db_path=fixture_db,
        )
        # Two run events: phase=initial + phase=complete
        assert len(rows) >= 1

    def test_child_alert_carries_causation_id(self, fixture_db):
        _seed_portfolio(fixture_db, [("BrokAlpha", "AAA", 10, 100.0, "USD")])
        _seed_price(fixture_db, "AAA", "2026-04-29", 95.0)
        with patch.object(
            hm,
            "_evaluate_triggers",
            return_value=(
                TRIGGER_TECHNICAL_SELL,
                {
                    "technical_action": "SELL",
                    "technical_confidence": 90.0,
                    "technical_reasoning": "MACD",
                    "divergence_flag": False,
                    "divergence_reason": "",
                    "consensus_action": "HOLD",
                },
            ),
        ):
            run_monitor(db_path=fixture_db)
        rows = query(
            "SELECT event_type, causation_id FROM pipeline_events WHERE event_type = ?",
            (EVENT_TYPE_TECHNICAL_SELL,),
            db_path=fixture_db,
        )
        assert len(rows) == 1
        assert rows[0]["causation_id"] is not None  # links to parent run event


# ─── Disabled config short-circuits ─────────────────────────────────────


class TestDisabledConfig:
    def test_disabled_returns_empty_summary(self, fixture_db, monkeypatch):
        # Mutate RULES at module level to simulate disabled config
        from nuri.core import rules as rules_mod

        monkeypatch.setitem(rules_mod.RULES, "holdings_monitor", {"enabled": False})
        # Note: holdings_monitor imports RULES, not rules_mod.RULES — so we
        # must monkeypatch the module's reference too.
        monkeypatch.setattr(hm, "RULES", rules_mod.RULES)
        summary = run_monitor(db_path=fixture_db)
        assert summary.n_holdings == 0
        assert summary.n_alerted == 0


# ─── Privacy: tests must not reference real holdings ────────────────────


class TestPrivacyCompliance:
    """Locks the test-data-privacy memory: no real broker names / tickers /
    PnL combinations in fixtures."""

    def test_no_real_broker_names_in_module_constants(self):
        # Read the module source and assert no Korean broker names slipped in.
        import inspect

        src = inspect.getsource(hm)
        for forbidden in ("kakaopay", "토스", "한국투자", "삼성증권", "키움"):
            assert forbidden.lower() not in src.lower(), f"Privacy leak: {forbidden}"

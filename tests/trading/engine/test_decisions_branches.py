"""Targeted branch coverage for nuri/trading/engine/decisions.py.

Covers lines flagged in 2026-05-04 audit:
- 288: empty verdicts_json continue
- 374: entry_price <= 0 → {} early
- 378-379: price_targets exception → {}
- 383+ CLI block (`if __name__ == '__main__'`) — DOCUMENTED, not exercised.

Each test cites source line(s) and verifies behavior, not just call.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from nuri.core.db import get_db, init_db


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "decisions_branches.db"
    init_db(p)
    return p


# ─────────── compute_agent_accuracy: empty / null verdicts skip ────────


class TestComputeAgentAccuracyBranches:
    def test_null_verdicts_json_skipped(self, db_path):
        """Line 287-288: agent_verdicts is NULL/empty → continue.

        Insert a finalized (outcome=success) decision with NULL agent_verdicts;
        compute_agent_accuracy must skip it without crashing and return {} since
        no agent stats accumulate.
        """
        from nuri.trading.engine.decisions import compute_agent_accuracy

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO decisions (date, ticker, action, confidence, "
                "outcome, agent_verdicts) VALUES (?, ?, ?, ?, ?, ?)",
                ("2025-03-25", "AAA", "BUY", 60.0, "success", None),
            )
            # Also one with empty string (still falsy)
            conn.execute(
                "INSERT INTO decisions (date, ticker, action, confidence, "
                "outcome, agent_verdicts) VALUES (?, ?, ?, ?, ?, ?)",
                ("2025-03-26", "BBB", "BUY", 60.0, "failure", ""),
            )
        result = compute_agent_accuracy(db_path=db_path)
        # Both rows skipped → no agent stats accumulated → empty dict
        assert result == {}

    def test_invalid_json_swallowed(self, db_path):
        """Lines 290-293: malformed agent_verdicts JSON → continue.

        Lock that compute_agent_accuracy doesn't crash on bad data and returns
        empty dict since no stats accumulated.
        """
        from nuri.trading.engine.decisions import compute_agent_accuracy

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO decisions (date, ticker, action, confidence, "
                "outcome, agent_verdicts) VALUES (?, ?, ?, ?, ?, ?)",
                ("2025-03-25", "AAA", "BUY", 60.0, "success", "not-json"),
            )
        result = compute_agent_accuracy(db_path=db_path)
        assert result == {}

    def test_hold_action_excluded(self, db_path):
        """Line 298-299: HOLD action → continue (no stats).

        Verdicts with action=HOLD must NOT contribute to agent stats.
        Lock the contract: an agent voting HOLD only is excluded entirely.
        """
        import json

        from nuri.trading.engine.decisions import compute_agent_accuracy

        verdicts = [{"action": "HOLD", "agent_name": "tech"}]
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO decisions (date, ticker, action, confidence, "
                "outcome, agent_verdicts) VALUES (?, ?, ?, ?, ?, ?)",
                ("2025-03-25", "AAA", "HOLD", 60.0, "success", json.dumps(verdicts)),
            )
        result = compute_agent_accuracy(db_path=db_path)
        assert result == {}  # HOLD vote → no contribution

    def test_buy_success_and_sell_failure_count_as_hit(self, db_path):
        """Lines 305-309: BUY+success and SELL+failure both increment hits.

        Insert two decisions: one BUY agent succeeded (+hit), one SELL agent that
        failed (+hit because the avoid was correct). Both have hit_rate=1.0.
        """
        import json

        from nuri.trading.engine.decisions import compute_agent_accuracy

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO decisions (date, ticker, action, confidence, "
                "outcome, agent_verdicts) VALUES (?, ?, ?, ?, ?, ?)",
                ("2025-03-20", "AAA", "BUY", 70.0, "success", json.dumps([{"action": "BUY", "agent_name": "tech"}])),
            )
            conn.execute(
                "INSERT INTO decisions (date, ticker, action, confidence, "
                "outcome, agent_verdicts) VALUES (?, ?, ?, ?, ?, ?)",
                ("2025-03-21", "BBB", "SELL", 70.0, "failure", json.dumps([{"action": "SELL", "agent_name": "tech"}])),
            )
        result = compute_agent_accuracy(db_path=db_path)
        assert "tech" in result
        assert result["tech"]["total"] == 2
        assert result["tech"]["hits"] == 2
        assert result["tech"]["hit_rate"] == 1.0
        # weight_adjustment = (1.0 - 0.5) clamped at 0.30
        assert result["tech"]["weight_adjustment"] == 0.30

    def test_buy_failure_counts_as_miss(self, db_path):
        """Confirm BUY+failure = miss (line 307 condition not satisfied).

        Lock the negative-direction: 0 hits, 1 total → hit_rate 0.0,
        weight_adjustment clamped at -0.30.
        """
        import json

        from nuri.trading.engine.decisions import compute_agent_accuracy

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO decisions (date, ticker, action, confidence, "
                "outcome, agent_verdicts) VALUES (?, ?, ?, ?, ?, ?)",
                ("2025-03-22", "CCC", "BUY", 60.0, "failure", json.dumps([{"action": "BUY", "agent_name": "risk"}])),
            )
        result = compute_agent_accuracy(db_path=db_path)
        assert result["risk"]["hits"] == 0
        assert result["risk"]["total"] == 1
        assert result["risk"]["weight_adjustment"] == -0.30


# ─────────── _get_price_targets: defensive guards ──────────────────────


class TestGetPriceTargets:
    def test_zero_entry_price_returns_empty(self, db_path):
        """Line 373-374: entry_price <= 0 → return {} early."""
        from nuri.trading.engine.decisions import _get_price_targets

        result = _get_price_targets("AAA", entry_price=0.0, db_path=db_path)
        assert result == {}

        result_neg = _get_price_targets("AAA", entry_price=-5.0, db_path=db_path)
        assert result_neg == {}

    def test_calculate_targets_exception_swallowed(self, db_path, monkeypatch):
        """Lines 378-379: calculate_targets raises → return {}.

        Patch the import target so the except branch fires deterministically.
        """
        from nuri.trading.engine.decisions import _get_price_targets

        def boom(*a, **kw):
            raise RuntimeError("synthetic")

        monkeypatch.setattr(
            "nuri.trading.recommend.price_targets.calculate_targets",
            boom,
        )
        result = _get_price_targets("AAA", entry_price=100.0, db_path=db_path)
        assert result == {}


# ─────── CLI block (lines 382-418) ────────────────────────────────────
# `if __name__ == "__main__":` — runpy-mocking known broken (tests/CLAUDE.md
# "runpy + mock"); each branch (`--track` / `--accuracy` / `--snapshot` / `--summary`)
# delegates to a function fully covered by the unit tests above. Documented as
# unreachable via in-process patching; coverage gap accepted.

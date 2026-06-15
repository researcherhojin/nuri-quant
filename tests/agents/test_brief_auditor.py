"""BriefAuditor tests — Discord-as-dev-loop self-quality actor.

Each check (C1 conflict / C2 noise / C3 identical_conv) tested with synthetic
agent_decisions rows. Dedupe verified with pre-existing #incidents content_preview.

Privacy: synthetic tickers TST_A/TST_B (never real holdings).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nuri.agents.actors.brief_auditor import (
    BriefAuditor,
    _check_conflict,
    _check_identical_conv,
    _check_noise,
    _make_issue_id,
)
from nuri.agents.base import Outcome
from nuri.core.db import init_db, log_agent_message, log_decision


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "ba.db"
    init_db(path)
    return path


@pytest.fixture
def patched_db(db_path):
    """Redirect every DB call in brief_auditor + base to the test DB."""
    from nuri.core import db as db_module

    def make_redirect(fn):
        def wrapped(*args, **kwargs):
            kwargs.setdefault("db_path", db_path)
            return fn(*args, **kwargs)

        return wrapped

    patches = [
        patch("nuri.agents.base.log_agent_audit", side_effect=make_redirect(db_module.log_agent_audit)),
        patch("nuri.agents.base.start_agent_run", side_effect=make_redirect(db_module.start_agent_run)),
        patch("nuri.agents.base.finish_agent_run", side_effect=make_redirect(db_module.finish_agent_run)),
        patch("nuri.agents.actors.brief_auditor.query", side_effect=make_redirect(db_module.query)),
    ]
    for p in patches:
        p.start()
    yield db_path
    for p in patches:
        p.stop()


def _seed_decision(
    db_path,
    *,
    decision_id: str,
    ticker: str,
    action: str,
    conviction: float,
    status: str = "emitted",
):
    """Insert a minimal agent_decisions row."""
    log_decision(
        decision_id=decision_id,
        ticker=ticker,
        as_of_date="2026-05-02",
        action=action,
        conviction=conviction,
        inputs={
            "regime_run_id": "r1",
            "hypothesis_id": "h1",
            "causal_audit_id": "c1",
        },
        rationale={"causal_certainty": 0.8, "regime_top_prob": 0.8, "top2_margin": 0.6},
        status=status,
        run_id="run-test",
        db_path=db_path,
    )


# ─── pure check functions (no DB) ─────────────────────────


def test_check_conflict_detects_buy_and_sell_same_ticker():
    decisions = [
        {"ticker": "TST_A", "action": "BUY", "decision_id": "d1", "conviction": 0.81, "created_at": "2026-05-02 00:00"},
        {
            "ticker": "TST_A",
            "action": "SELL",
            "decision_id": "d2",
            "conviction": 0.81,
            "created_at": "2026-05-02 06:00",
        },
    ]
    issues = _check_conflict(decisions)
    assert len(issues) == 1
    assert issues[0]["type"] == "conflict"
    assert issues[0]["affected"] == ["TST_A"]
    assert "d1" in issues[0]["evidence"]
    assert "d2" in issues[0]["evidence"]


def test_check_conflict_no_issue_when_only_buy():
    decisions = [
        {"ticker": "TST_A", "action": "BUY", "decision_id": "d1", "conviction": 0.81, "created_at": "2026-05-02 00:00"},
        {"ticker": "TST_A", "action": "BUY", "decision_id": "d2", "conviction": 0.82, "created_at": "2026-05-02 06:00"},
    ]
    assert _check_conflict(decisions) == []


def test_check_noise_above_threshold():
    decisions = [
        {"ticker": "TST_A", "action": "BUY", "decision_id": f"d{i}", "conviction": 0.81, "created_at": "2026-05-02"}
        for i in range(5)
    ]
    issues = _check_noise(decisions)
    assert len(issues) == 1
    assert issues[0]["type"] == "noise"
    assert issues[0]["n_decisions"] == 5


def test_check_noise_at_threshold_no_issue():
    decisions = [
        {"ticker": "TST_A", "action": "BUY", "decision_id": f"d{i}", "conviction": 0.81, "created_at": "2026-05-02"}
        for i in range(3)
    ]
    assert _check_noise(decisions) == []


def test_check_identical_conv_detects_broken_scoring():
    decisions = [
        {"ticker": f"TST_{i}", "action": "BUY", "decision_id": f"d{i}", "conviction": 0.810, "created_at": "2026-05-02"}
        for i in range(6)
    ]
    issues = _check_identical_conv(decisions)
    assert len(issues) == 1
    assert issues[0]["type"] == "identical_conv"
    assert issues[0]["n_decisions"] == 6


def test_check_identical_conv_skips_with_spread():
    decisions = [
        {
            "ticker": f"TST_{i}",
            "action": "BUY",
            "decision_id": f"d{i}",
            "conviction": 0.81 + i * 0.01,
            "created_at": "2026-05-02",
        }
        for i in range(6)
    ]
    assert _check_identical_conv(decisions) == []


def test_check_identical_conv_skips_below_min_samples():
    decisions = [
        {"ticker": f"TST_{i}", "action": "BUY", "decision_id": f"d{i}", "conviction": 0.810, "created_at": "2026-05-02"}
        for i in range(3)
    ]
    assert _check_identical_conv(decisions) == []


def test_make_issue_id_deterministic():
    a = _make_issue_id("conflict", ["TST_B", "TST_A"])
    b = _make_issue_id("conflict", ["TST_A", "TST_B"])
    assert a == b == _make_issue_id("conflict", ["TST_A", "TST_B"])


def test_make_issue_id_differs_by_type():
    a = _make_issue_id("conflict", ["TST_A"])
    b = _make_issue_id("noise", ["TST_A"])
    assert a != b


# ─── full actor run with patched DB ─────────────────────────


def test_audit_finds_conflict_and_emits_warn(patched_db):
    _seed_decision(patched_db, decision_id="dc-1", ticker="TST_A", action="BUY", conviction=0.81)
    _seed_decision(patched_db, decision_id="dc-2", ticker="TST_A", action="SELL", conviction=0.82)

    with patch("nuri.agents.actors.brief_auditor._emit_incident", return_value=True) as emit:
        result = BriefAuditor().run({"hours": 24, "db_path": patched_db})

    assert result.outcome == Outcome.WARN
    assert result.output["decisions_audited"] == 2
    assert result.output["issues_found"] == 1
    assert result.output["issues_emitted"] == 1
    assert emit.called


def test_audit_passes_when_no_issues(patched_db):
    _seed_decision(patched_db, decision_id="dc-1", ticker="TST_A", action="BUY", conviction=0.81)
    _seed_decision(patched_db, decision_id="dc-2", ticker="TST_B", action="SELL", conviction=0.85)

    with patch("nuri.agents.actors.brief_auditor._emit_incident", return_value=True):
        result = BriefAuditor().run({"hours": 24, "db_path": patched_db})

    assert result.outcome == Outcome.PASS
    assert result.output["issues_found"] == 0
    assert result.output["issues_emitted"] == 0


def test_audit_skips_hold_status_only_emitted_buy_sell(patched_db):
    _seed_decision(patched_db, decision_id="dc-1", ticker="TST_A", action="HOLD", conviction=0.81)
    _seed_decision(patched_db, decision_id="dc-2", ticker="TST_A", action="HOLD", conviction=0.81)

    with patch("nuri.agents.actors.brief_auditor._emit_incident", return_value=True):
        result = BriefAuditor().run({"hours": 24, "db_path": patched_db})

    assert result.output["decisions_audited"] == 0
    assert result.outcome == Outcome.PASS


def test_audit_dedupes_against_recent_outbox_stage(patched_db):
    """Codex Round 6: dedupe via outbox dedupe_key (no longer agent_messages)."""
    from nuri.core.db import stage_outbox

    _seed_decision(patched_db, decision_id="dc-1", ticker="TST_A", action="BUY", conviction=0.81)
    _seed_decision(patched_db, decision_id="dc-2", ticker="TST_A", action="SELL", conviction=0.82)

    issue_id = _make_issue_id("conflict", ["TST_A"])
    # 자가점검은 #ops 로 stage → dedupe 도 #ops 를 조회해야 매칭 (채널 일치 lock).
    stage_outbox(
        channel="ops",
        payload={"summary": "prior brief_quality issue"},
        dedupe_key=f"brief_quality:{issue_id}",
        actor_name="brief-auditor",
        db_path=patched_db,
    )

    with patch("nuri.agents.actors.brief_auditor._emit_incident", return_value=True) as emit:
        result = BriefAuditor().run({"hours": 24, "db_path": patched_db})

    assert result.output["issues_found"] == 1
    assert result.output["issues_emitted"] == 0
    assert result.output["issues_dedupe_skipped"] == 1
    assert not emit.called


class TestEmitIncidentExceptionPath:
    """Lock-tests for _emit_incident exception (lines 256-275)."""

    def test_emit_incident_success(self, patched_db):
        """stage_incident → True (lines 256-273)."""
        from nuri.agents.actors.brief_auditor import _emit_incident

        with patch(
            "nuri.agents.discord.outbox.stage_incident",
            return_value=42,
        ):
            ok = _emit_incident(
                issue={
                    "type": "conflict",
                    "issue_id": "abc",
                    "affected": ["AAPL"],
                    "n_decisions": 2,
                    "evidence": [],
                    "suggested_fix": "fix",
                },
                run_id="run123",
                db_path=patched_db,
            )
        assert ok is True

    def test_emit_incident_exception_returns_false(self, patched_db):
        """stage_incident raise → False (line 274-275)."""
        from nuri.agents.actors.brief_auditor import _emit_incident

        with patch(
            "nuri.agents.discord.outbox.stage_incident",
            side_effect=RuntimeError("outbox full"),
        ):
            ok = _emit_incident(
                issue={
                    "type": "noise",
                    "issue_id": "x",
                    "affected": ["MSFT"],
                    "n_decisions": 5,
                    "evidence": [],
                    "suggested_fix": "fix",
                },
                run_id="run456",
                db_path=patched_db,
            )
        assert ok is False


class TestBriefAuditorCli:
    def test_cli_main(self, patched_db, capsys, monkeypatch):
        """main() prints summary (lines 278-295)."""
        from nuri.agents.actors.brief_auditor import main

        class FakeRes:
            output = {
                "decisions_audited": 10,
                "issues_found": 2,
                "issues_emitted": 1,
                "issues_dedupe_skipped": 1,
                "issues": [
                    {"issue_id": "id1", "type": "conflict", "affected": ["AAPL"]},
                ],
            }

        class FakeAuditor:
            def run(self, *a, **kw):
                return FakeRes()

        monkeypatch.setattr("nuri.agents.actors.brief_auditor.BriefAuditor", FakeAuditor)
        rc = main(["--hours", "12"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "audited=10" in out
        assert "id1" in out

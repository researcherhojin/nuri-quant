"""Discord outbox tests — single-writer pattern (Codex Round 6, 2026-05-02).

Coverage:
    - stage_outbox / dedupe skip vs replace
    - claim_pending_outbox lease + priority + scheduled_for ordering
    - mark_outbox_sent / mark_outbox_failed claim_token isolation
    - Lease expiry → re-claim by another dispatcher
    - bucket_brief_digest / bucket_generic_digest layout
    - ChannelDispatcher quiet-period gate (#brief)
    - ChannelDispatcher publish path (mock webhook)
    - OutboxWatchdog threshold breach → direct ops alert (mock webhook)

Privacy: synthetic tickers TST_A/TST_B (never real holdings).
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from nuri.agents.actors.channel_dispatcher import ChannelDispatcher
from nuri.agents.actors.outbox_watchdog import OutboxWatchdog
from nuri.agents.base import Outcome
from nuri.agents.discord.outbox import (
    bucket_brief_digest,
    bucket_generic_digest,
    stage_brief,
    stage_incident,
)
from nuri.core.db import (
    claim_pending_outbox,
    init_db,
    mark_outbox_failed,
    mark_outbox_sent,
    outbox_health,
    stage_outbox,
)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "outbox.db"
    init_db(path)
    return path


@pytest.fixture
def patched_db(db_path):
    """Redirect DB calls in dispatcher / watchdog to test DB."""
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
        patch(
            "nuri.agents.actors.channel_dispatcher.claim_pending_outbox",
            side_effect=make_redirect(db_module.claim_pending_outbox),
        ),
        patch(
            "nuri.agents.actors.channel_dispatcher.mark_outbox_sent",
            side_effect=make_redirect(db_module.mark_outbox_sent),
        ),
        patch(
            "nuri.agents.actors.channel_dispatcher.mark_outbox_failed",
            side_effect=make_redirect(db_module.mark_outbox_failed),
        ),
        patch("nuri.agents.actors.channel_dispatcher.query", side_effect=make_redirect(db_module.query)),
        patch("nuri.agents.actors.outbox_watchdog.outbox_health", side_effect=make_redirect(db_module.outbox_health)),
    ]
    for p in patches:
        p.start()
    yield db_path
    for p in patches:
        p.stop()


# ─── stage / dedupe ──────────────────────────────────────


def test_stage_dedupe_skip_returns_none_for_duplicate(db_path):
    i1 = stage_outbox("brief", {"kind": "BUY", "ticker": "TST_A"}, dedupe_key="key1", db_path=db_path)
    i2 = stage_outbox("brief", {"kind": "BUY", "ticker": "TST_A"}, dedupe_key="key1", db_path=db_path)
    assert i1 is not None
    assert i2 is None


def test_stage_dedupe_replace_updates_payload(db_path):
    i1 = stage_outbox("brief", {"v": 1}, dedupe_key="k", db_path=db_path)
    i2 = stage_outbox("brief", {"v": 2}, dedupe_key="k", db_path=db_path, dedupe_strategy="replace")
    assert i1 == i2

    _, rows = claim_pending_outbox("brief", db_path=db_path)
    assert rows[0]["payload"]["v"] == 2


def test_stage_invalid_channel_raises(db_path):
    with pytest.raises(ValueError):
        stage_outbox("nope", {}, db_path=db_path)


def test_stage_brief_helper_routes_to_brief_channel(db_path):
    stage_brief({"kind": "BUY", "ticker": "TST_A"}, db_path=db_path)
    _, rows = claim_pending_outbox("brief", db_path=db_path)
    assert len(rows) == 1
    _, ops_rows = claim_pending_outbox("ops", db_path=db_path)
    assert ops_rows == []


# ─── claim / priority / lease ────────────────────────────


def test_claim_priority_high_first(db_path):
    stage_outbox("ops", {"x": "normal"}, priority="normal", db_path=db_path)
    stage_outbox("ops", {"x": "high"}, priority="high", db_path=db_path)
    stage_outbox("ops", {"x": "low"}, priority="low", db_path=db_path)
    _, rows = claim_pending_outbox("ops", db_path=db_path)
    assert [r["payload"]["x"] for r in rows] == ["high", "normal", "low"]


def test_mark_sent_only_with_correct_token(db_path):
    stage_outbox("ops", {"x": 1}, db_path=db_path)
    token1, rows = claim_pending_outbox("ops", db_path=db_path)
    assert mark_outbox_sent([rows[0]["id"]], "wrong-token", db_path=db_path) == 0
    assert mark_outbox_sent([rows[0]["id"]], token1, db_path=db_path) == 1


def test_lease_expiry_allows_reclaim(db_path):
    # stage + claim
    stage_outbox("ops", {"x": 1}, db_path=db_path)
    token1, rows1 = claim_pending_outbox("ops", db_path=db_path)
    assert len(rows1) == 1

    # 두 번째 claim 즉시 = 빈 결과 (lease 유효)
    _, rows2 = claim_pending_outbox("ops", db_path=db_path)
    assert rows2 == []

    # claimed_at 을 6분 전으로 강제 backdate 해서 lease 만료 시뮬레이션
    from nuri.core.db import get_db

    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE discord_outbox SET claimed_at = datetime('now','-6 minutes') WHERE id = ?",
            (rows1[0]["id"],),
        )
    _, rows3 = claim_pending_outbox("ops", db_path=db_path)
    assert len(rows3) == 1


def test_scheduled_for_future_not_claimed_yet(db_path):
    from nuri.core.db import get_db

    stage_outbox("ops", {"x": 1}, db_path=db_path)
    # backdate scheduled_for to future
    with get_db(db_path) as conn:
        conn.execute("UPDATE discord_outbox SET scheduled_for = datetime('now','+1 hour')")
    _, rows = claim_pending_outbox("ops", db_path=db_path)
    assert rows == []


def test_mark_failed_clears_claim_token_for_retry(db_path):
    stage_outbox("ops", {"x": 1}, db_path=db_path)
    token1, rows1 = claim_pending_outbox("ops", db_path=db_path)
    assert mark_outbox_failed([rows1[0]["id"]], token1, error="boom", db_path=db_path) == 1
    # status='failed' 인 row 는 다음 claim 안 잡힘 (현재 정책: failed terminal until manual requeue)
    _, rows2 = claim_pending_outbox("ops", db_path=db_path)
    assert rows2 == []


# ─── digest layout ───────────────────────────────────────


def test_bucket_brief_digest_groups_by_actionability():
    events = [
        {"kind": "BUY", "ticker": "TST_A", "conviction": 0.81},
        {"kind": "SELL", "ticker": "TST_B", "conviction": 0.77},
        {"kind": "BLOCK", "ticker": "TST_A", "reason": "vix"},
        {"kind": "HOLD", "ticker": "TST_C", "conviction": 0.45},
    ]
    embed = bucket_brief_digest(events)
    field_names = [f["name"] for f in embed["fields"]]
    assert any("Action Now" in n for n in field_names)
    assert any("Blocked / Conflict" in n for n in field_names)
    assert any("Lower Priority" in n for n in field_names)
    assert "BUY 1" in embed["description"]
    assert "SELL 1" in embed["description"]
    assert "BLOCK 1" in embed["description"]


def test_bucket_brief_digest_empty_returns_no_op_embed():
    embed = bucket_brief_digest([])
    assert embed["fields"] == []
    assert "0 opinions" in embed["title"]


def test_bucket_generic_digest_groups_by_kind():
    events = [
        {"kind": "freshness_warn", "summary": "prices stale 25h"},
        {"kind": "freshness_warn", "summary": "vix stale 26h"},
        {"kind": "rate_limit", "summary": "kis 429"},
    ]
    embed = bucket_generic_digest(events, channel_label="Ops")
    field_names = [f["name"] for f in embed["fields"]]
    assert any("freshness_warn (2)" in n for n in field_names)
    assert any("rate_limit (1)" in n for n in field_names)


# ─── dispatcher ──────────────────────────────────────────


def test_dispatcher_brief_quiet_period_skips_recent_stage(patched_db):
    stage_brief({"kind": "BUY", "ticker": "TST_A", "conviction": 0.8}, db_path=patched_db)
    result = ChannelDispatcher().run({"channel": "brief", "db_path": patched_db})
    assert result.outcome == Outcome.PASS
    assert result.output["skipped"] == "quiet-period"


def test_dispatcher_brief_high_priority_bypasses_quiet_period(patched_db):
    stage_brief(
        {"kind": "SELL", "ticker": "TST_A", "conviction": 0.9, "reason": "stop-loss"},
        priority="high",
        db_path=patched_db,
    )
    mock_pub = MagicMock()
    mock_pub.publish_embed.return_value = MagicMock(ok=True, http_status=204, error=None)
    with patch("nuri.agents.discord.publisher.DiscordPublisher", return_value=mock_pub):
        result = ChannelDispatcher().run({"channel": "brief", "db_path": patched_db})
    assert result.outcome == Outcome.PASS
    assert result.output.get("marked_sent_n") == 1


def test_dispatcher_force_bypass(patched_db):
    stage_brief({"kind": "BUY", "ticker": "TST_A", "conviction": 0.8}, db_path=patched_db)
    mock_pub = MagicMock()
    mock_pub.publish_embed.return_value = MagicMock(ok=True, http_status=204, error=None)
    with patch("nuri.agents.discord.publisher.DiscordPublisher", return_value=mock_pub):
        result = ChannelDispatcher().run({"channel": "brief", "force": True, "db_path": patched_db})
    assert result.output.get("marked_sent_n") == 1


def test_dispatcher_no_pending_passes(patched_db):
    result = ChannelDispatcher().run({"channel": "ops", "db_path": patched_db})
    assert result.outcome == Outcome.PASS
    assert result.output["skipped"] == "no-pending"


def test_dispatcher_ops_does_not_quiet_period(patched_db):
    stage_outbox("ops", {"kind": "freshness_warn", "summary": "x"}, db_path=patched_db)
    mock_pub = MagicMock()
    mock_pub.publish_embed.return_value = MagicMock(ok=True, http_status=204, error=None)
    with patch("nuri.agents.discord.publisher.DiscordPublisher", return_value=mock_pub):
        result = ChannelDispatcher().run({"channel": "ops", "db_path": patched_db})
    assert result.output.get("marked_sent_n") == 1


def test_dispatcher_publish_failure_marks_failed(patched_db):
    stage_outbox("ops", {"kind": "x", "summary": "y"}, db_path=patched_db)
    mock_pub = MagicMock()
    mock_pub.publish_embed.return_value = MagicMock(ok=False, http_status=500, error="server error")
    with patch("nuri.agents.discord.publisher.DiscordPublisher", return_value=mock_pub):
        result = ChannelDispatcher().run({"channel": "ops", "db_path": patched_db})
    assert result.outcome == Outcome.WARN
    health = outbox_health(db_path=patched_db)
    assert health["by_channel"]["ops"].get("failed", 0) == 1


def test_dispatcher_quiet_period_dispatches_after_age(patched_db):
    stage_brief({"kind": "BUY", "ticker": "TST_A", "conviction": 0.8}, db_path=patched_db)
    # backdate created_at past quiet-period
    from nuri.core.db import get_db

    with get_db(patched_db) as conn:
        conn.execute("UPDATE discord_outbox SET created_at = datetime('now','-2 minutes')")
    mock_pub = MagicMock()
    mock_pub.publish_embed.return_value = MagicMock(ok=True, http_status=204, error=None)
    with patch("nuri.agents.discord.publisher.DiscordPublisher", return_value=mock_pub):
        result = ChannelDispatcher().run({"channel": "brief", "db_path": patched_db})
    assert result.output.get("marked_sent_n") == 1


# ─── watchdog ────────────────────────────────────────────


def test_watchdog_clean_when_no_backlog(patched_db):
    result = OutboxWatchdog().run({"db_path": patched_db})
    assert result.outcome == Outcome.PASS
    assert result.output["breaches"] == []


def test_watchdog_breach_on_old_pending(patched_db):
    stage_outbox("ops", {"x": 1}, db_path=patched_db)
    from nuri.core.db import get_db

    with get_db(patched_db) as conn:
        conn.execute("UPDATE discord_outbox SET scheduled_for = datetime('now','-45 minutes')")

    mock_pub = MagicMock()
    mock_pub.publish_embed.return_value = MagicMock(ok=True, http_status=204, error=None)
    with patch("nuri.agents.discord.publisher.DiscordPublisher", return_value=mock_pub):
        result = OutboxWatchdog().run({"db_path": patched_db})
    assert result.outcome == Outcome.WARN
    assert any(b["kind"] == "oldest_pending_age" for b in result.output["breaches"])


def test_watchdog_breach_on_pending_count(patched_db):
    for i in range(120):
        stage_outbox("ops", {"i": i}, db_path=patched_db)
    mock_pub = MagicMock()
    mock_pub.publish_embed.return_value = MagicMock(ok=True, http_status=204, error=None)
    with patch("nuri.agents.discord.publisher.DiscordPublisher", return_value=mock_pub):
        result = OutboxWatchdog().run({"db_path": patched_db})
    assert any(b["kind"] == "pending_count" for b in result.output["breaches"])


# ─── outbox_health ──────────────────────────────────────


def test_outbox_health_shows_per_channel_counts(db_path):
    stage_outbox("brief", {"x": 1}, db_path=db_path)
    stage_outbox("brief", {"x": 2}, db_path=db_path)
    stage_outbox("ops", {"x": 3}, db_path=db_path)
    h = outbox_health(db_path=db_path)
    assert h["by_channel"]["brief"]["pending"] == 2
    assert h["by_channel"]["ops"]["pending"] == 1
    assert h["oldest_pending_age_seconds"] is not None

"""ChannelDispatcher actor 테스트 (Codex Round 6, single-writer Discord).

검증:
- channel 검증 (invalid → ValueError)
- quiet-period gate (#brief 만 — 60s 이내 skip)
- high-priority bypass quiet-period
- claim → bucket → publish lifecycle
- success / failure / exception path
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nuri.agents.actors.channel_dispatcher import ChannelDispatcher, main
from nuri.agents.base import Outcome
from nuri.core.db import init_db


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "dispatcher.db"
    init_db(p)
    return p


@pytest.fixture
def patched_base(db_path):
    """base.run() audit DB redirect."""
    from nuri.core import db as db_module

    def _wrap(fn):
        def w(*a, **kw):
            kw.setdefault("db_path", db_path)
            return fn(*a, **kw)

        return w

    with (
        patch("nuri.agents.base.log_agent_audit", side_effect=_wrap(db_module.log_agent_audit)),
        patch("nuri.agents.base.start_agent_run", side_effect=_wrap(db_module.start_agent_run)),
        patch("nuri.agents.base.finish_agent_run", side_effect=_wrap(db_module.finish_agent_run)),
    ):
        yield db_path


class TestChannelDispatcherValidation:
    def test_invalid_channel_raises(self, patched_base):
        actor = ChannelDispatcher()
        with pytest.raises(Exception):
            actor.run({"channel": "unknown_channel", "db_path": patched_base})


class TestChannelDispatcherClaim:
    def test_no_pending_returns_skip(self, patched_base):
        """pending 없음 → skipped='no-pending' (lines 119-123)."""
        actor = ChannelDispatcher()
        result = actor.run({"channel": "ops", "db_path": patched_base})
        assert result.outcome == Outcome.PASS
        assert result.output["skipped"] == "no-pending"

    def test_publish_success(self, patched_base):
        """claim → bucket → publish OK → mark sent (lines 117-169)."""
        from nuri.core.db import stage_outbox

        stage_outbox(
            channel="ops",
            payload={"event": "test_event", "ticker": "AAPL", "msg": "hello"},
            actor_name="test_actor",
            db_path=patched_base,
        )

        # Mock DiscordPublisher.publish_embed to return success
        fake_result = MagicMock()
        fake_result.ok = True
        fake_result.http_status = 204
        fake_result.error = None

        fake_publisher = MagicMock()
        fake_publisher.publish_embed.return_value = fake_result

        with patch(
            "nuri.agents.discord.publisher.DiscordPublisher",
            return_value=fake_publisher,
        ):
            actor = ChannelDispatcher()
            result = actor.run({"channel": "ops", "db_path": patched_base})

        assert result.outcome == Outcome.PASS
        assert result.output["http_status"] == 204
        assert result.output["claimed_n"] >= 1

    def test_publish_failure_marks_failed(self, patched_base):
        """publish_embed returns ok=False → WARN + mark_outbox_failed (lines 171-187)."""
        from nuri.core.db import stage_outbox

        stage_outbox(
            channel="ops",
            payload={"event": "test_event"},
            actor_name="test_actor",
            db_path=patched_base,
        )

        fake_result = MagicMock()
        fake_result.ok = False
        fake_result.http_status = 500
        fake_result.error = "rate limited"

        fake_publisher = MagicMock()
        fake_publisher.publish_embed.return_value = fake_result

        with patch(
            "nuri.agents.discord.publisher.DiscordPublisher",
            return_value=fake_publisher,
        ):
            actor = ChannelDispatcher()
            result = actor.run({"channel": "ops", "db_path": patched_base})

        assert result.outcome == Outcome.WARN
        assert result.output["http_status"] == 500

    def test_publish_exception_path(self, patched_base):
        """DiscordPublisher 가 raise → ERROR + mark_outbox_failed (lines 144-155)."""
        from nuri.core.db import stage_outbox

        stage_outbox(
            channel="ops",
            payload={"event": "test_event"},
            actor_name="test_actor",
            db_path=patched_base,
        )

        with patch(
            "nuri.agents.discord.publisher.DiscordPublisher",
            side_effect=RuntimeError("import failed"),
        ):
            actor = ChannelDispatcher()
            result = actor.run({"channel": "ops", "db_path": patched_base})

        assert result.outcome == Outcome.ERROR
        assert "import failed" in result.output.get("error", "")


class TestChannelDispatcherQuietPeriod:
    def test_brief_recent_stage_skipped(self, patched_base):
        """#brief 채널 last_stage 60s 이내 → quiet-period skip (lines 100-114)."""
        from nuri.core.db import stage_outbox

        stage_outbox(
            channel="brief",
            payload={"event": "stage1"},
            actor_name="test_actor",
            priority="normal",
            db_path=patched_base,
        )
        actor = ChannelDispatcher()
        result = actor.run({"channel": "brief", "db_path": patched_base})
        assert result.outcome == Outcome.PASS
        # 새로 들어간 row 가 quiet-period 안이라 skip
        assert result.output["skipped"] == "quiet-period"

    def test_brief_high_priority_bypasses_quiet(self, patched_base):
        """#brief 에 high priority 가 있으면 quiet-period 무시 (line 102)."""
        from nuri.core.db import stage_outbox

        stage_outbox(
            channel="brief",
            payload={"event": "urgent"},
            actor_name="test_actor",
            priority="high",
            db_path=patched_base,
        )
        fake_result = MagicMock()
        fake_result.ok = True
        fake_result.http_status = 204
        fake_result.error = None
        fake_publisher = MagicMock()
        fake_publisher.publish_embed.return_value = fake_result

        with patch(
            "nuri.agents.discord.publisher.DiscordPublisher",
            return_value=fake_publisher,
        ):
            actor = ChannelDispatcher()
            result = actor.run({"channel": "brief", "db_path": patched_base})
        # quiet-period bypassed → claimed
        assert result.outcome == Outcome.PASS
        assert result.output.get("skipped") != "quiet-period"

    def test_brief_force_bypasses_quiet(self, patched_base):
        """force=True → quiet-period bypass."""
        from nuri.core.db import stage_outbox

        stage_outbox(
            channel="brief",
            payload={"event": "stage1"},
            actor_name="test_actor",
            db_path=patched_base,
        )
        fake_result = MagicMock()
        fake_result.ok = True
        fake_result.http_status = 204
        fake_result.error = None
        fake_publisher = MagicMock()
        fake_publisher.publish_embed.return_value = fake_result

        with patch(
            "nuri.agents.discord.publisher.DiscordPublisher",
            return_value=fake_publisher,
        ):
            actor = ChannelDispatcher()
            result = actor.run({"channel": "brief", "db_path": patched_base, "force": True})
        assert result.output.get("skipped") != "quiet-period"


class TestChannelDispatcherCli:
    def test_cli_runs(self, patched_base, monkeypatch, capsys):
        """CLI main(): argparse + run + print (lines 191-201)."""

        # Patch ChannelDispatcher to a minimal stub
        class FakeResult:
            output = {"channel": "ops", "skipped": "no-pending"}

        class FakeActor:
            def run(self, *a, **kw):
                return FakeResult()

        monkeypatch.setattr(
            "nuri.agents.actors.channel_dispatcher.ChannelDispatcher",
            FakeActor,
        )
        rc = main(["ops"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "ops:" in out

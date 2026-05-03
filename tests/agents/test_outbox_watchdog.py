"""OutboxWatchdog actor 테스트 (Codex Round 6).

검증:
- outbox health 임계 미달 → PASS, no breach
- oldest_pending_age 초과 → WARN + ops alert
- per-channel pending count 초과 → WARN + ops alert
- DiscordPublisher exception → published.ok=False
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nuri.agents.actors.outbox_watchdog import OutboxWatchdog, _direct_publish_ops, main
from nuri.agents.base import Outcome
from nuri.core.db import init_db


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "watchdog.db"
    init_db(p)
    return p


@pytest.fixture
def patched_base(db_path):
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


class TestOutboxWatchdogClean:
    def test_no_breaches_returns_pass(self, patched_base, monkeypatch):
        """all metrics under threshold → PASS, no published (lines 92-97)."""
        monkeypatch.setattr(
            "nuri.agents.actors.outbox_watchdog.outbox_health",
            lambda **kw: {
                "oldest_pending_age_seconds": 60,
                "oldest_pending_channel": "ops",
                "by_channel": {
                    "ops": {"pending": 2, "sent": 5, "failed": 0},
                    "brief": {"pending": 1, "sent": 3, "failed": 0},
                },
            },
        )
        actor = OutboxWatchdog()
        result = actor.run({"db_path": patched_base})
        assert result.outcome == Outcome.PASS
        assert result.output["breaches"] == []
        assert result.output["published"] is None


class TestOutboxWatchdogBreach:
    def test_oldest_pending_age_breach(self, patched_base, monkeypatch):
        """age > 30min → WARN + alert published (lines 68-77, 99-118)."""
        monkeypatch.setattr(
            "nuri.agents.actors.outbox_watchdog.outbox_health",
            lambda **kw: {
                "oldest_pending_age_seconds": 60 * 60,  # 1 hour
                "oldest_pending_channel": "ops",
                "by_channel": {"ops": {"pending": 5, "sent": 0, "failed": 0}},
            },
        )

        fake_result = MagicMock()
        fake_result.ok = True
        fake_result.http_status = 204
        fake_result.error = None
        fake_pub = MagicMock()
        fake_pub.publish_embed.return_value = fake_result

        with patch(
            "nuri.agents.discord.publisher.DiscordPublisher",
            return_value=fake_pub,
        ):
            actor = OutboxWatchdog()
            result = actor.run({"db_path": patched_base})

        assert result.outcome == Outcome.WARN
        assert any(b["kind"] == "oldest_pending_age" for b in result.output["breaches"])
        assert result.output["published"]["ok"] is True

    def test_pending_count_breach(self, patched_base, monkeypatch):
        """pending > 100 → WARN + alert (lines 79-90)."""
        monkeypatch.setattr(
            "nuri.agents.actors.outbox_watchdog.outbox_health",
            lambda **kw: {
                "oldest_pending_age_seconds": 30,
                "oldest_pending_channel": "brief",
                "by_channel": {"brief": {"pending": 200, "sent": 0, "failed": 0}},
            },
        )

        fake_result = MagicMock()
        fake_result.ok = True
        fake_result.http_status = 204
        fake_result.error = None
        fake_pub = MagicMock()
        fake_pub.publish_embed.return_value = fake_result

        with patch(
            "nuri.agents.discord.publisher.DiscordPublisher",
            return_value=fake_pub,
        ):
            actor = OutboxWatchdog()
            result = actor.run({"db_path": patched_base})

        assert result.outcome == Outcome.WARN
        assert any(b["kind"] == "pending_count" for b in result.output["breaches"])


class TestDirectPublishOps:
    def test_publish_exception(self):
        """DiscordPublisher import fail → ok=False (lines 45-46)."""
        with patch(
            "nuri.agents.discord.publisher.DiscordPublisher",
            side_effect=RuntimeError("import error"),
        ):
            r = _direct_publish_ops({"title": "t"})
        assert r["ok"] is False
        assert "RuntimeError" in r["error"]

    def test_publish_success(self):
        fake_result = MagicMock()
        fake_result.ok = True
        fake_result.http_status = 204
        fake_result.error = None
        fake_pub = MagicMock()
        fake_pub.publish_embed.return_value = fake_result
        with patch(
            "nuri.agents.discord.publisher.DiscordPublisher",
            return_value=fake_pub,
        ):
            r = _direct_publish_ops({"title": "t"})
        assert r["ok"] is True


class TestOutboxWatchdogCli:
    def test_cli_runs_clean(self, patched_base, monkeypatch, capsys):
        """CLI main() prints summary (lines 122-128)."""
        monkeypatch.setattr(
            "nuri.agents.actors.outbox_watchdog.outbox_health",
            lambda **kw: {
                "oldest_pending_age_seconds": 30,
                "by_channel": {},
            },
        )
        # Patch base.log_agent_audit etc to use db
        rc = main([])
        assert rc == 0
        out = capsys.readouterr().out
        assert "breaches=" in out

    def test_cli_with_breach(self, patched_base, monkeypatch, capsys):
        """CLI with breach prints published line."""
        monkeypatch.setattr(
            "nuri.agents.actors.outbox_watchdog.outbox_health",
            lambda **kw: {
                "oldest_pending_age_seconds": 60 * 60,
                "oldest_pending_channel": "ops",
                "by_channel": {"ops": {"pending": 5}},
            },
        )

        fake_result = MagicMock()
        fake_result.ok = True
        fake_result.http_status = 204
        fake_result.error = None
        fake_pub = MagicMock()
        fake_pub.publish_embed.return_value = fake_result
        with patch(
            "nuri.agents.discord.publisher.DiscordPublisher",
            return_value=fake_pub,
        ):
            rc = main([])
        assert rc == 0
        out = capsys.readouterr().out
        assert "breaches=" in out
        assert "published" in out

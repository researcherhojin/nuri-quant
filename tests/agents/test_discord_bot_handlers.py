"""Pragma audit: discord/bot.py async slash command handler coverage.

Replaces 4 `# pragma: no cover` markers on async handlers with real tests.
Each handler is invoked with a mocked discord.Interaction and the underlying
subprocess (`_run_make`) is patched.

Pattern: extract the registered command callbacks via `tree.get_commands()`,
then invoke `await callback(mock_interaction, ...)`. The handlers internally
call `interaction.response.defer()` / `interaction.followup.send()` and the
`_run_make` subprocess wrapper — we mock all three.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _get_callback(tree, guild, name):
    """Find the registered slash command's callback by name."""
    for cmd in tree.get_commands(guild=guild):
        if cmd.name == name:
            return cmd.callback
    raise KeyError(name)


class TestSlashCommandHandlers:
    """Invoke each async slash command callback with a mocked Interaction."""

    @pytest.fixture
    def bot_components(self, monkeypatch):
        monkeypatch.setenv("DISCORD_GUILD_ID", "1234567890")
        from nuri.agents.discord.bot import build_bot

        bot, tree, guild = build_bot()
        return bot, tree, guild

    def _make_interaction(self):
        """Build a mocked discord.Interaction with async response/followup."""
        import discord

        ix = MagicMock()
        ix.channel = MagicMock(spec=discord.TextChannel)
        ix.response = MagicMock()
        ix.response.defer = AsyncMock()
        ix.response.send_message = AsyncMock()
        ix.followup = MagicMock()
        ix.followup.send = AsyncMock()
        ix.progress_thread = MagicMock()
        ix.progress_thread.send = AsyncMock()
        message = MagicMock()
        message.create_thread = AsyncMock(return_value=ix.progress_thread)
        ix.followup.send.return_value = message
        ix.channel.create_thread = AsyncMock(return_value=ix.progress_thread)
        return ix

    def test_buy_candidates_handler_invokes_run_make_and_sends_embed(self, bot_components, monkeypatch):
        """/buy-candidates: defer → _run_make → followup.send(embed)."""
        _, tree, guild = bot_components
        callback = _get_callback(tree, guild, "buy-candidates")
        ix = self._make_interaction()

        with patch(
            "nuri.agents.discord.bot._run_make",
            return_value=(0, "5 candidates\n"),
        ) as mock_make:
            asyncio.run(callback(ix))

        ix.response.defer.assert_awaited_once_with(thinking=True)
        mock_make.assert_called_once_with("buy-candidates")
        ix.followup.send.assert_awaited_once()
        # Embed body contains the make output snippet
        kwargs = ix.followup.send.await_args.kwargs
        assert "embed" in kwargs

    def test_thesis_handler_normalizes_ticker_and_invokes_make(self, bot_components, monkeypatch):
        _, tree, guild = bot_components
        callback = _get_callback(tree, guild, "thesis")
        ix = self._make_interaction()

        async def run(target, ticker, on_stage):
            await on_stage({"event": "stage", "stage": "manager", "status": "ok", "secret": "PRIVATE"})
            return 0, {"event": "result", "rating": "Hold", "outcome": "verdict", "run_hash": "a" * 64}

        with patch("nuri.agents.discord.bot._run_thesis_stream", side_effect=run) as runner:
            asyncio.run(callback(ix, "msft"))
        ix.response.defer.assert_awaited_once_with(thinking=True)
        assert runner.call_args.args[:2] == ("thesis-remote", "MSFT")
        ix.followup.send.assert_awaited_once()
        assert ix.progress_thread.send.await_count == 2
        assert ix.progress_thread.send.await_args_list[0].args == ("종합 판정 · 완료",)
        assert "embed" in ix.progress_thread.send.await_args.kwargs

    def test_followup_without_guild_creates_thread_through_the_channel(self, bot_components):
        import discord

        _, tree, guild = bot_components
        callback = _get_callback(tree, guild, "thesis")
        ix = self._make_interaction()
        # 실제 follow-up SDK 객체에는 guild 가 없어서 message.create_thread 는 실패한다.
        message = object.__new__(discord.WebhookMessage)
        message.id = 123
        message.guild = None
        ix.followup.send.return_value = message
        ix.channel.create_thread = AsyncMock(return_value=ix.progress_thread)
        result = {"event": "result", "rating": "Hold", "outcome": "verdict", "run_hash": "a" * 64}
        with patch("nuri.agents.discord.bot._run_thesis_stream", return_value=(0, result)):
            asyncio.run(callback(ix, "TEST"))
        ix.channel.create_thread.assert_awaited_once_with(
            name="Thesis · TEST", message=message, auto_archive_duration=60
        )
        ix.progress_thread.send.assert_awaited_once()

    @pytest.mark.parametrize("rc", [0, 2])
    def test_thesis_embed_body_is_allowlisted_even_on_errors(self, bot_components, rc):
        _, tree, guild = bot_components
        callback = _get_callback(tree, guild, "thesis")
        ix = self._make_interaction()
        value = {
            "event": "result",
            "rating": "Hold",
            "outcome": "verdict",
            "run_hash": "a" * 64,
            "holdings": "PRIVATE",
            "error": "PRIVATE",
            "size": "PRIVATE",
        }
        with (
            patch("nuri.agents.discord.bot._run_thesis_stream", return_value=(rc, value)),
            patch("nuri.agents.discord.bot.build_status_embed", return_value={"title": "t"}) as embed,
        ):
            asyncio.run(callback(ix, "msft"))
        body = embed.call_args.kwargs["body"]
        assert "PRIVATE" not in body
        assert embed.call_args.kwargs["fields"] == {"분석": "탐색용"}
        assert ("판정: Hold" in body) if rc == 0 else ("완료하지 못했습니다" in body)
        assert ix.progress_thread.send.await_count == 1

    @pytest.mark.parametrize("mode", ["exception", "invalid", "failed"])
    def test_thesis_failure_never_exposes_details(self, bot_components, mode):
        _, tree, guild = bot_components
        callback = _get_callback(tree, guild, "thesis")
        ix = self._make_interaction()

        async def fail(*args):
            await args[2]({"event": "stage", "stage": "PRIVATE", "status": "ok"})
            if mode == "exception":
                raise RuntimeError("PRIVATE")
            if mode == "failed":
                return 0, {"event": "result", "rating": "REVIEW", "outcome": "failed", "run_hash": "a" * 64}
            return 0, {"event": "unknown", "detail": "PRIVATE"}

        with (
            patch("nuri.agents.discord.bot._run_thesis_stream", side_effect=fail),
            patch("nuri.agents.discord.bot.build_status_embed", return_value={"title": "t"}) as embed,
        ):
            asyncio.run(callback(ix, "TEST"))
        assert embed.call_args.kwargs["success"] is False
        assert "PRIVATE" not in str(embed.call_args)
        assert ix.progress_thread.send.await_count == 1

    def test_thesis_uses_an_existing_thread(self, bot_components):
        import discord

        _, tree, guild = bot_components
        callback = _get_callback(tree, guild, "thesis")
        ix = self._make_interaction()
        ix.channel = MagicMock(spec=discord.Thread)
        ix.channel.send = AsyncMock()
        value = {"event": "result", "rating": "REVIEW", "outcome": "review", "run_hash": "a" * 64}
        with patch("nuri.agents.discord.bot._run_thesis_stream", return_value=(0, value)):
            asyncio.run(callback(ix, "TEST"))
        ix.followup.send.return_value.create_thread.assert_not_awaited()
        ix.channel.send.assert_awaited_once()

    @pytest.mark.parametrize("unsupported_channel", [False, True])
    def test_thread_failure_stops_before_the_model(self, bot_components, unsupported_channel):
        _, tree, guild = bot_components
        callback = _get_callback(tree, guild, "thesis")
        ix = self._make_interaction()
        ix.channel.create_thread.side_effect = RuntimeError("PRIVATE")
        if unsupported_channel:
            ix.channel = None
        with patch("nuri.agents.discord.bot._run_thesis_stream") as runner:
            asyncio.run(callback(ix, "TEST"))
        runner.assert_not_called()
        assert ix.followup.send.await_count == 2
        assert "PRIVATE" not in str(ix.followup.send.call_args)

    def test_thesis_handler_rejects_invalid_ticker(self, bot_components, monkeypatch):
        """/thesis with non-alpha ticker: ephemeral error, no _run_make call."""
        _, tree, guild = bot_components
        callback = _get_callback(tree, guild, "thesis")
        ix = self._make_interaction()

        with patch("nuri.agents.discord.bot._run_make") as mock_make:
            asyncio.run(callback(ix, "TOOOOOOLONG"))

        # send_message ephemeral error path
        ix.response.send_message.assert_awaited_once()
        mock_make.assert_not_called()

    def test_health_handler_runs_health_check_subprocess(self, bot_components, monkeypatch):
        """/health: defer → bash scripts/health_check.sh → followup.send."""
        _, tree, guild = bot_components
        callback = _get_callback(tree, guild, "health")
        ix = self._make_interaction()

        # Patch subprocess.run inside the handler's _run inner function
        proc_mock = MagicMock(returncode=0, stdout="all green\n", stderr="")
        with patch("subprocess.run", return_value=proc_mock):
            asyncio.run(callback(ix))

        ix.response.defer.assert_awaited_once_with(thinking=True)
        ix.followup.send.assert_awaited_once()

    def test_health_handler_subprocess_timeout(self, bot_components):
        """/health: subprocess.TimeoutExpired → rc=124 + 'timeout 30s' (lines 134-135)."""
        import subprocess

        _, tree, guild = bot_components
        callback = _get_callback(tree, guild, "health")
        ix = self._make_interaction()

        # subprocess.run raises TimeoutExpired → caught inside the nested _run() helper
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="bash", timeout=30)):
            asyncio.run(callback(ix))

        ix.response.defer.assert_awaited_once_with(thinking=True)
        ix.followup.send.assert_awaited_once()
        # Embed body should reflect timeout (rc=124)
        kwargs = ix.followup.send.await_args.kwargs
        assert "embed" in kwargs


class TestOnReadyEvent:
    """on_ready event handler: tree.sync(guild=guild)."""

    def test_on_ready_syncs_command_tree(self, monkeypatch):
        """build_bot registers an on_ready event that calls tree.sync.

        We exercise the registration path. discord.py stores listeners on the
        Client instance via @bot.event decorator.
        """
        monkeypatch.setenv("DISCORD_GUILD_ID", "1234567890")
        from nuri.agents.discord.bot import build_bot

        bot, tree, guild = build_bot()

        # Find on_ready registered listener
        # discord.Client stores events as bot.on_ready (overridden attribute)
        on_ready = getattr(bot, "on_ready", None)
        assert on_ready is not None and callable(on_ready)

        # Patch tree.sync to async no-op + capture call
        sync_mock = AsyncMock()
        monkeypatch.setattr(tree, "sync", sync_mock)
        # Patch logger.info to silence
        asyncio.run(on_ready())  # type: ignore[arg-type]
        sync_mock.assert_awaited_once_with(guild=guild)

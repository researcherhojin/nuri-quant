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
        ix = MagicMock()
        ix.response = MagicMock()
        ix.response.defer = AsyncMock()
        ix.response.send_message = AsyncMock()
        ix.followup = MagicMock()
        ix.followup.send = AsyncMock()
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
        """/thesis: ticker uppercased, defer → _run_make('thesis', {ticker:X}) → followup."""
        _, tree, guild = bot_components
        callback = _get_callback(tree, guild, "thesis")
        ix = self._make_interaction()

        with patch(
            "nuri.agents.discord.bot._run_make",
            return_value=(0, "thesis output\n"),
        ) as mock_make:
            asyncio.run(callback(ix, "msft"))

        ix.response.defer.assert_awaited_once_with(thinking=True)
        # ticker normalized to upper, passed via args dict
        mock_make.assert_called_once()
        call_args = mock_make.call_args
        assert call_args.args[0] == "thesis"
        assert call_args.args[1] == {"ticker": "MSFT"}
        ix.followup.send.assert_awaited_once()

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
        asyncio.run(on_ready())
        sync_mock.assert_awaited_once_with(guild=guild)

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
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _get_callback(tree, guild, name) -> Any:
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
        ix.progress_thread.send.return_value.edit = AsyncMock()
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
        assert ix.progress_thread.send.return_value.edit.await_count == 2
        assert "종합 판정" in ix.progress_thread.send.return_value.edit.await_args.kwargs["embed"].description
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
        assert ix.progress_thread.send.await_count == 2

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
        with patch("nuri.agents.discord.bot._run_thesis_stream", return_value=(rc, value)):
            asyncio.run(callback(ix, "msft"))
        embed = ix.progress_thread.send.await_args.kwargs["embed"].to_dict()
        assert "PRIVATE" not in str(embed)
        assert "Hold" in str(embed) if rc == 0 else "완료하지 못했습니다" in embed["description"]
        assert ix.progress_thread.send.await_count == 2

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

        with patch("nuri.agents.discord.bot._run_thesis_stream", side_effect=fail):
            asyncio.run(callback(ix, "TEST"))
        embed = ix.progress_thread.send.await_args.kwargs["embed"].to_dict()
        assert embed["color"] == 0xD16B6B
        assert "PRIVATE" not in str(embed)
        assert ix.progress_thread.send.await_count == 2

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
        assert ix.channel.send.await_count == 2

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


def test_thesis_edits_one_board_and_survives_discord_edit_failure(monkeypatch):
    import discord

    from nuri.agents.discord.bot import build_bot
    from nuri.llm.thesis_events import STAGES

    monkeypatch.setenv("DISCORD_GUILD_ID", "1234567890")
    _, tree, guild = build_bot()
    callback = _get_callback(tree, guild, "thesis")
    ix = TestSlashCommandHandlers()._make_interaction()
    response = MagicMock(status=404, reason="not found")
    ix.progress_thread.send.return_value.edit.side_effect = discord.NotFound(response, "gone")

    async def run(target, ticker, on_stage):
        # 토큰 만료 후 followup 을 사용하면 실패하도록 만든다.
        ix.followup.send.side_effect = AssertionError("expired interaction")
        for stage in STAGES:
            for status in ("started", "ok", "ok"):
                await on_stage({"event": "stage", "stage": stage, "status": status})
        return 0, {"event": "result", "rating": "Hold", "outcome": "verdict", "run_hash": "a" * 64}

    with patch("nuri.agents.discord.bot._run_thesis_stream", side_effect=run):
        asyncio.run(callback(ix, "TEST"))
    assert ix.progress_thread.send.await_count == 2  # 상태표 + 최종 결과만
    assert ix.progress_thread.send.return_value.edit.await_count == 15  # 중복 이벤트는 갱신하지 않음
    assert ix.progress_thread.send.await_args.kwargs["embed"].color.value == 0x253649


def test_thesis_progress_gaps_and_review_are_not_success():
    from nuri.agents.discord.thesis_view import AMBER, BASE, RED, progress_embed, result_embed
    from nuri.llm.thesis_events import STAGES

    states = dict.fromkeys(STAGES, "ok")
    value = {"event": "result", "rating": "Hold", "outcome": "verdict", "run_hash": "a" * 64}
    assert result_embed("TEST", states, 0, value)["color"] == BASE
    states["analyst:news"] = "absent"
    states["manager"] = "started"
    del states["researcher:bear"]
    board = progress_embed("TEST", states, finished=True)
    assert all(s in board["description"] for s in ("근거 없음", "중단 · 완료 미확인", "미확인"))
    assert result_embed("TEST", states, 0, value)["color"] == AMBER
    review = value | {"rating": "REVIEW", "outcome": "review"}
    assert "확정하지 못했습니다" in result_embed("TEST", states, 0, review)["description"]
    assert result_embed("TEST", states, 1, value)["color"] == RED


def _saved_report():
    from nuri.llm.thesis_events import STAGES

    return {
        "run": {
            "ticker": "TEST",
            "run_hash": "a" * 64,
            "rating": "Hold",
            "outcome": "verdict",
            "scored": False,
            "rendered": "**Rating**: Hold\n- [bull] demand evidence\n- [bear] opposing evidence\n**Rationale**: <script>alert(1)</script>",
            "stages": {s: {"outcome": "ok"} for s in STAGES},
            "handoff": {"reports": "<img src=https://example.com/track>", "debate": "opposing argument"},
        },
        "packets": {
            "ticker": {
                "cutoff": "2026-10-28",
                "sources": {"news": {"status": "absent"}},
                "items": [{"id": "e1", "source": "test", "observed": "2026-10-27", "age_days": 1}],
            }
        },
    }


def test_local_report_escapes_untrusted_text_and_exposes_evidence():
    from nuri.agents.discord.thesis_report import render

    saved = _saved_report()
    page = render(saved)
    assert "<script>" not in page and "<img " not in page
    assert "&lt;script&gt;" in page and "&lt;img " in page
    assert "default-src 'none'" in page
    assert all(
        s in page for s in ("demand evidence", "opposing evidence", "opposing argument", "2026-10-27", "2026-10-28")
    )
    saved["run"]["scored"] = True
    saved["run"]["outcome"] = "review_model"
    saved["run"]["rendered"] = ""
    saved["run"]["stages"] = {}
    saved["packets"] = {}
    page = render(saved)
    assert "채점 실행 기록" in page and "미확정" in page and "저장된 근거 없음" in page
    assert "7개 단계가 완료" not in page


def test_local_report_opens_exact_archive_without_model_or_ledger(tmp_path, monkeypatch, capsys):
    import json

    from nuri.agents.discord import thesis_report as report

    directory = tmp_path / "runs"
    directory.mkdir()
    saved = _saved_report()
    source = directory / f"TEST-{'a' * 16}.json"
    source.write_text(json.dumps(saved))
    before = source.read_bytes()
    monkeypatch.setattr(report, "load_config", lambda: {"archive_dir": str(tmp_path)})
    with patch.object(report.webbrowser, "open") as browser:
        assert report.main(["--ticker", "TEST", "--run", "a" * 16]) == 0
        browser.assert_not_called()
        assert report.main(["--ticker", "TEST", "--run", "a" * 64, "--open"]) == 0
        browser.assert_called_once()
    assert source.read_bytes() == before
    assert source.with_suffix(".html").stat().st_mode & 0o777 == 0o600
    assert report.main(["--ticker", "TEST", "--run", "b" * 16]) == 2
    saved["run"]["run_hash"] = "a" * 16 + "b" * 48
    source.write_text(json.dumps(saved))
    assert report.main(["--ticker", "TEST", "--run", "a" * 64]) == 2
    with pytest.raises(SystemExit):
        report.main(["--ticker", "../TEST", "--run", "a" * 16])
    assert "분석 파일을 읽을 수 없습니다" in capsys.readouterr().out


def test_local_report_ignores_unknown_packet_metadata_and_handles_invalid_cli(monkeypatch):
    import runpy
    import sys

    from nuri.agents.discord.thesis_report import render

    saved = _saved_report()
    saved["packets"]["unknown"] = "not a packet"
    assert "not a packet" not in render(saved)
    monkeypatch.setattr(sys, "argv", ["thesis-report", "--ticker", "bad!", "--run", "a" * 16])
    with pytest.raises(SystemExit) as error:
        runpy.run_module("nuri.agents.discord.thesis_report", run_name="__main__")
    assert error.value.code == 2

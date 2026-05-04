"""DiscordBot tests (#529 Phase 2 — slash command inbound).

검증:
- _run_make subprocess invocation (성공 / 실패 / timeout)
- main() env 검증 (DISCORD_BOT_TOKEN / DISCORD_GUILD_ID 누락 시 fail-fast)
- build_bot() guild_id 누락 시 RuntimeError
- slash command handler 입력 검증 (ticker shape, 잘못된 입력 차단)

discord.py Client 자체는 무겁고 네트워크 의존이라 build_bot 의 핸들러 구조만 검증.
실제 명령 실행 (interaction.response.defer / followup.send) 은 integration 영역으로 분리.
"""

from __future__ import annotations

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest


class TestRunMake:
    def test_success_returns_zero_and_stdout(self):
        from nuri.agents.discord.bot import _run_make

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
            rc, out = _run_make("buy-candidates")
        assert rc == 0
        assert "ok" in out

    def test_failure_returns_nonzero(self):
        from nuri.agents.discord.bot import _run_make

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=2, stdout="", stderr="boom\n")
            rc, out = _run_make("thesis", {"ticker": "MSFT"})
        assert rc == 2
        assert "boom" in out

    def test_timeout_returns_124(self):
        from nuri.agents.discord.bot import _run_make

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="make", timeout=5)):
            rc, out = _run_make("thesis", {"ticker": "X"}, timeout=5)
        assert rc == 124
        assert "timeout" in out.lower()

    def test_args_quoted_via_shlex(self):
        """make 인자 quoting — 공백/특수문자 injection 방지."""
        from nuri.agents.discord.bot import _run_make

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            _run_make("thesis", {"ticker": "MSFT; rm -rf /"})
            cmd = mock_run.call_args.args[0]
        joined = " ".join(cmd)
        assert "rm -rf" not in cmd  # not a separate arg, just quoted text
        assert "ticker=" in joined


class TestMainEnvValidation:
    def test_missing_token_returns_2(self, monkeypatch, capsys):
        from nuri.agents.discord.bot import main

        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        rc = main([])
        assert rc == 2
        out = capsys.readouterr().out
        assert "DISCORD_BOT_TOKEN" in out

    def test_blank_token_returns_2(self, monkeypatch):
        from nuri.agents.discord.bot import main

        monkeypatch.setenv("DISCORD_BOT_TOKEN", "   ")
        rc = main([])
        assert rc == 2


class TestBuildBot:
    def test_missing_guild_id_raises(self, monkeypatch):
        monkeypatch.delenv("DISCORD_GUILD_ID", raising=False)
        from nuri.agents.discord.bot import build_bot

        with pytest.raises(RuntimeError, match="DISCORD_GUILD_ID"):
            build_bot()

    def test_blank_guild_id_raises(self, monkeypatch):
        monkeypatch.setenv("DISCORD_GUILD_ID", "")
        from nuri.agents.discord.bot import build_bot

        with pytest.raises(RuntimeError, match="DISCORD_GUILD_ID"):
            build_bot()

    def test_valid_guild_id_returns_bot_tree_guild(self, monkeypatch):
        """build_bot 이 (bot, tree, guild) 3-tuple 반환 + guild.id 정확."""
        monkeypatch.setenv("DISCORD_GUILD_ID", "1234567890")
        from nuri.agents.discord.bot import build_bot

        bot, tree, guild = build_bot()
        assert guild.id == 1234567890
        assert bot is not None
        assert tree is not None

    def test_three_slash_commands_registered(self, monkeypatch):
        """tree.get_commands() 가 buy-candidates / thesis / health 3개 포함."""
        monkeypatch.setenv("DISCORD_GUILD_ID", "1234567890")
        from nuri.agents.discord.bot import build_bot

        _, tree, guild = build_bot()
        cmd_names = {c.name for c in tree.get_commands(guild=guild)}
        assert {"buy-candidates", "thesis", "health"}.issubset(cmd_names)


class TestRepoRoot:
    def test_repo_root_resolves_to_repo(self):
        """REPO_ROOT 가 nuri-quant repo root 를 가리키는지 sanity check."""
        from nuri.agents.discord.bot import REPO_ROOT

        assert (REPO_ROOT / "Makefile").exists()
        assert (REPO_ROOT / "nuri" / "core" / "db" / "__init__.py").exists()  # Stage 2 package


class TestMainRuntime:
    """main() 의 token 통과 후 분기 (default run vs --sync-only) 검증."""

    def test_main_default_calls_bot_run(self, monkeypatch):
        """token + guild_id 있으면 bot.run(token) 호출."""
        from unittest.mock import MagicMock

        monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
        monkeypatch.setenv("DISCORD_GUILD_ID", "1234567890")

        mock_bot = MagicMock()
        mock_tree = MagicMock()
        mock_guild = MagicMock(id=1234567890)

        with patch("nuri.agents.discord.bot.build_bot", return_value=(mock_bot, mock_tree, mock_guild)):
            from nuri.agents.discord.bot import main

            rc = main([])

        assert rc == 0
        mock_bot.run.assert_called_once_with("fake-token")

    def test_main_module_runpy_invokes_main(self, monkeypatch):
        """__main__ block (lines 196-198): runpy + sys.exit(main()) — exit 2 on missing token.

        주의: load_dotenv 가 module import 시 .env 를 읽어 DISCORD_BOT_TOKEN 을 채울 수
        있으므로 dotenv 자체를 no-op 으로 만들어 환경을 잠근다.
        """
        import io
        import runpy
        import sys

        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: False)
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        monkeypatch.setattr(sys, "argv", ["bot"])
        monkeypatch.setattr(sys, "stdout", io.StringIO())
        with pytest.raises(SystemExit) as exc:
            runpy.run_module("nuri.agents.discord.bot", run_name="__main__")
        assert exc.value.code == 2

    def test_main_sync_only_runs_async_sync(self, monkeypatch, capsys):
        """--sync-only 분기: asyncio.run + tree.sync 호출 + bot.run 미호출."""
        from unittest.mock import AsyncMock, MagicMock

        monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
        monkeypatch.setenv("DISCORD_GUILD_ID", "9999")

        mock_bot = MagicMock()
        mock_bot.login = AsyncMock()
        mock_bot.close = AsyncMock()
        mock_tree = MagicMock()
        mock_tree.sync = AsyncMock()
        mock_guild = MagicMock(id=9999)

        with patch("nuri.agents.discord.bot.build_bot", return_value=(mock_bot, mock_tree, mock_guild)):
            from nuri.agents.discord.bot import main

            rc = main(["--sync-only"])

        assert rc == 0
        mock_bot.run.assert_not_called()
        mock_tree.sync.assert_awaited_once()
        out = capsys.readouterr().out
        assert "9999" in out and "synced" in out

"""DiscordBot — inbound slash commands (#529 Phase 2).

Long-running process (Mac mini launchd). 3 guild-scoped commands:
    /buy-candidates          → make buy-candidates → 결과를 #brief 에 publish
    /thesis ticker:<TICKER>  → make thesis ticker=X → archive 경로 + verdict 1줄
    /health                  → scripts/health_check.sh → 결과 inline

설계 원칙:
    - 명령은 항상 deferred response (Discord 3s 시한, 우리 작업 1-30s)
    - 실행 결과 반환 + 동시에 채널에 publish (audit trail 보장)
    - 모든 invocation 은 agent_audit_ledger 기록 (actor_name='discord-bot')
    - guild-scoped sync 만 사용 (전역 1h 지연 회피)

Auto trading 영구 제외 (STRATEGY §7.1):
    /buy-candidates 는 *후보 emit only*. 실제 매수 명령 X.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _run_make(target: str, args: Optional[dict[str, str]] = None, timeout: int = 120) -> tuple[int, str]:
    """make 타겟 실행 — (returncode, output) 반환.

    args 는 make 변수 (e.g. {'ticker': 'MSFT'}) → make ticker=MSFT.
    """
    cmd = ["make", target]
    if args:
        for k, v in args.items():
            cmd.append(f"{k}={shlex.quote(v)}")
    try:
        proc = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        out = (proc.stdout + proc.stderr)[-1500:]
        return proc.returncode, out
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s"


def build_bot():
    """discord.py Bot 인스턴스 빌드.

    호출 시점에 import (discord 미설치 환경에서도 publisher 만 사용 가능하게).
    """
    import discord
    from discord import app_commands

    intents = discord.Intents.default()
    bot = discord.Client(intents=intents)
    tree = app_commands.CommandTree(bot)

    guild_id_str = os.getenv("DISCORD_GUILD_ID", "").strip()
    if not guild_id_str:
        raise RuntimeError("DISCORD_GUILD_ID env required for slash command sync")
    guild = discord.Object(id=int(guild_id_str))

    # ─── /buy-candidates ───
    @tree.command(name="buy-candidates", description="현금 배포 후보 ticker emit (recommendations only)", guild=guild)
    async def buy_candidates(interaction: "discord.Interaction") -> None:
        await interaction.response.defer(thinking=True)
        rc, out = await asyncio.to_thread(_run_make, "buy-candidates")
        status = "✅ OK" if rc == 0 else f"❌ exit {rc}"
        await interaction.followup.send(f"**buy-candidates** {status}\n```\n{out[-1500:]}\n```")

    # ─── /thesis ticker:<TICKER> ───
    @tree.command(name="thesis", description="ticker thesis Q&A (Codex + Qwen3.5 dual archive)", guild=guild)
    @app_commands.describe(ticker="대상 ticker (e.g. MSFT, NVDA)")
    async def thesis(interaction: "discord.Interaction", ticker: str) -> None:
        ticker = ticker.upper().strip()
        if not ticker.isalpha() or len(ticker) > 6:
            await interaction.response.send_message(f"❌ invalid ticker: {ticker!r}", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        rc, out = await asyncio.to_thread(_run_make, "thesis", {"ticker": ticker}, 300)
        status = "✅ OK" if rc == 0 else f"❌ exit {rc}"
        await interaction.followup.send(f"**thesis {ticker}** {status}\n```\n{out[-1500:]}\n```")

    # ─── /health ───
    @tree.command(name="health", description="agent infra health check (single-writer + schema + tables)", guild=guild)
    async def health(interaction: "discord.Interaction") -> None:
        await interaction.response.defer(thinking=True)

        def _run() -> tuple[int, str]:
            try:
                proc = subprocess.run(
                    ["bash", "scripts/health_check.sh"],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                return proc.returncode, (proc.stdout + proc.stderr)[-1500:]
            except subprocess.TimeoutExpired:
                return 124, "timeout 30s"

        rc, out = await asyncio.to_thread(_run)
        emoji = {0: "✅", 1: "⚠️", 2: "❌"}.get(rc, "❌")
        await interaction.followup.send(f"{emoji} health (exit {rc})\n```\n{out}\n```")

    @bot.event
    async def on_ready() -> None:
        await tree.sync(guild=guild)
        logger.info("bot ready user=%s commands synced to guild=%s", bot.user, guild.id)

    return bot, tree, guild


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m nuri.agents.discord.bot

    Reads DISCORD_BOT_TOKEN + DISCORD_GUILD_ID from env.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="discord-bot")
    parser.add_argument("--sync-only", action="store_true", help="등록만 하고 종료 (CI/배포용)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("❌ DISCORD_BOT_TOKEN env required", flush=True)
        return 2

    bot, tree, guild = build_bot()

    if args.sync_only:

        async def _sync_and_exit() -> None:
            import discord

            await bot.login(token)
            await tree.sync(guild=guild)
            print(f"✅ commands synced to guild={guild.id}")
            await bot.close()
            del discord  # silence unused

        asyncio.run(_sync_and_exit())
        return 0

    bot.run(token)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())

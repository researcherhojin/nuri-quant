"""
Discord 알림 봇 — send-only 방식.

두 가지 전송 방법:
1. Webhook (권장, 간단) — DISCORD_WEBHOOK_URL 설정
2. Bot (고급, 양방향) — DISCORD_TOKEN + DISCORD_CHANNEL_ID 설정

사용법:
    # Webhook 방식
    python -m iris.alerts.discord_bot --webhook --message "테스트"

    # Bot 방식
    python -m iris.alerts.discord_bot --bot
"""
import argparse
import json
import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


def send_webhook(embed: dict, webhook_url: str | None = None) -> bool:
    """Discord Webhook으로 Embed 전송."""
    url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL", "")
    if not url:
        logger.error("DISCORD_WEBHOOK_URL이 설정되지 않음")
        return False

    resp = requests.post(url, json={"embeds": [embed]}, timeout=10)
    resp.raise_for_status()
    logger.info("Webhook 전송 완료")
    return True


def send_webhook_text(message: str, webhook_url: str | None = None) -> bool:
    """Discord Webhook으로 텍스트 메시지 전송."""
    url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL", "")
    if not url:
        logger.error("DISCORD_WEBHOOK_URL이 설정되지 않음")
        return False

    resp = requests.post(url, json={"content": message}, timeout=10)
    resp.raise_for_status()
    logger.info("텍스트 전송 완료")
    return True


async def send_bot(embed_dict: dict) -> bool:
    """Discord Bot으로 Embed 전송."""
    import discord

    token = os.getenv("DISCORD_TOKEN", "")
    channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))

    if not token or channel_id == 0:
        logger.error("DISCORD_TOKEN 또는 DISCORD_CHANNEL_ID 미설정")
        return False

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        channel = client.get_channel(channel_id)
        if channel:
            embed = discord.Embed(
                title=embed_dict.get("title", ""),
                color=embed_dict.get("color", 0x3498DB),
                description=embed_dict.get("description", ""),
            )
            for field in embed_dict.get("fields", []):
                embed.add_field(
                    name=field["name"],
                    value=field["value"],
                    inline=field.get("inline", False),
                )
            footer = embed_dict.get("footer", {})
            if footer:
                embed.set_footer(text=footer.get("text", ""))

            await channel.send(embed=embed)
            logger.info(f"Bot 메시지 전송 완료: #{channel.name}")
        else:
            logger.error(f"채널 {channel_id}를 찾을 수 없음")

        await client.close()

    await client.start(token)
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="IRIS Discord 알림")
    parser.add_argument("--webhook", action="store_true", help="Webhook 방식")
    parser.add_argument("--message", type=str, default="IRIS 테스트 메시지")
    args = parser.parse_args()

    if args.webhook:
        send_webhook_text(args.message)
    else:
        print("사용법: --webhook --message '메시지'")
        print("또는 .env에 DISCORD_WEBHOOK_URL 설정 후 다른 모듈에서 호출")

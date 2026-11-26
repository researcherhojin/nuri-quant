"""
Discord 알림 봇 — send-only 방식.

두 가지 전송 방법:
1. Webhook (권장, 간단) — DISCORD_WEBHOOK_URL 설정
2. Bot (고급, 양방향) — DISCORD_TOKEN + DISCORD_CHANNEL_ID 설정

사용법:
    # Webhook 방식
    python -m nuri.alerts.discord_bot --webhook --message "테스트"

    # Bot 방식
    python -m nuri.alerts.discord_bot --bot
"""

import argparse
import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

DISCORD_CONTENT_MAX_LEN = 2000
_WEBHOOK_MAX_RETRIES = 2
_WEBHOOK_MAX_RETRY_AFTER_SEC = 5.0


def _retry_delay_seconds(resp, attempt: int) -> float:
    """429 Retry-After 또는 5xx 지수 백오프 대기 시간(초) 계산."""
    status = getattr(resp, "status_code", None)
    if status == 429:
        headers = getattr(resp, "headers", None) or {}
        raw = headers.get("Retry-After") or headers.get("retry-after")
        if raw is not None:
            try:
                return max(0.0, min(float(raw), _WEBHOOK_MAX_RETRY_AFTER_SEC))
            except (TypeError, ValueError):
                pass
    return min(float(2**attempt), _WEBHOOK_MAX_RETRY_AFTER_SEC)


def _post_webhook(url: str, payload: dict) -> None:
    """Discord Webhook POST — 429 / 5xx 한정 유한 재시도 포함."""
    import time

    for attempt in range(_WEBHOOK_MAX_RETRIES + 1):
        resp = requests.post(url, json=payload, timeout=10)
        status = getattr(resp, "status_code", None)
        is_retryable = isinstance(status, int) and (status == 429 or 500 <= status < 600)
        if is_retryable and attempt < _WEBHOOK_MAX_RETRIES:
            delay = _retry_delay_seconds(resp, attempt)
            logger.warning(
                "Discord Webhook HTTP %d — %.1f초 후 재시도 (%d/%d)",
                status,
                delay,
                attempt + 1,
                _WEBHOOK_MAX_RETRIES,
            )
            time.sleep(delay)
            continue
        resp.raise_for_status()
        return


def _truncate_discord_content(message: str) -> str:
    """Discord 메시지 2000자 제한 적용 (초과 시 끝을 '…'로 절단)."""
    if len(message) <= DISCORD_CONTENT_MAX_LEN:
        return message
    return message[: DISCORD_CONTENT_MAX_LEN - 1] + "…"


def send_webhook(embed: dict, webhook_url: str | None = None) -> bool:
    """Discord Webhook으로 Embed 전송."""
    url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL", "")
    if not url:
        logger.error("DISCORD_WEBHOOK_URL이 설정되지 않음")
        return False

    _post_webhook(url, {"embeds": [embed]})
    logger.info("Webhook 전송 완료")
    return True


def send_webhook_text(message: str, webhook_url: str | None = None) -> bool:
    """Discord Webhook으로 텍스트 메시지 전송."""
    url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL", "")
    if not url:
        logger.error("DISCORD_WEBHOOK_URL이 설정되지 않음")
        return False

    _post_webhook(url, {"content": _truncate_discord_content(message)})
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

            await channel.send(embed=embed)  # type: ignore[union-attr]
            logger.info(f"Bot 메시지 전송 완료: #{getattr(channel, 'name', channel_id)}")
        else:
            logger.error(f"채널 {channel_id}를 찾을 수 없음")

        await client.close()

    await client.start(token)
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Nuri-Quant Discord 알림")
    parser.add_argument("--webhook", action="store_true", help="Webhook 방식")
    parser.add_argument("--message", type=str, default="Nuri-Quant 테스트 메시지")
    args = parser.parse_args()

    if args.webhook:
        send_webhook_text(args.message)
    else:
        print("사용법: --webhook --message '메시지'")
        print("또는 .env에 DISCORD_WEBHOOK_URL 설정 후 다른 모듈에서 호출")

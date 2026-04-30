"""DiscordPublisher — outbound webhook (#529 Phase 2).

Layer 분류:
    Pure utility (not an Actor) — caller (any actor) chooses to publish.
    Audit 는 nuri.core.db.log_agent_message() 영구 기록.

설계 원칙 (Codex Round 5):
    - sync + async 둘 다 지원 (legacy alerts 모듈 호환 위해 sync 도 제공)
    - 1회 retry (Discord 5xx / 429 일시 장애 흡수)
    - 절대 raise X (publish 실패가 actor pipeline 을 죽이지 않게) — 결과는 PublishResult
    - DISCORD_WEBHOOK_<CHANNEL> env 누락 시 graceful skip + audit 에 'webhook missing' 기록
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

import httpx

from nuri.core.db import log_agent_message

logger = logging.getLogger(__name__)


class Channel(str, Enum):
    """4-채널 enum — DB CHECK 제약과 동일 string."""

    BRIEF = "brief"
    OPS = "ops"
    INCIDENTS = "incidents"
    ROLLOUT = "rollout"

    @property
    def env_var(self) -> str:
        return f"DISCORD_WEBHOOK_{self.value.upper()}"


@dataclass
class PublishResult:
    """publish() 반환 — caller 가 결과 확인 가능."""

    channel: Channel
    ok: bool
    http_status: Optional[int]
    retry_count: int
    error: Optional[str] = None


class DiscordPublisher:
    """Multi-channel Discord webhook publisher.

    Usage (sync):
        pub = DiscordPublisher()
        result = pub.publish_text(Channel.OPS, "freshness FAIL: prices stale 150h")

    Usage (async):
        result = await pub.apublish_text(Channel.OPS, "...")

    Embed:
        result = pub.publish_embed(Channel.BRIEF, embed={"title": "...", ...})
    """

    DEFAULT_TIMEOUT = 10.0
    MAX_RETRIES = 1  # Discord 5xx / 429 일시 장애만 흡수

    def __init__(self, timeout: float | None = None) -> None:
        self.timeout = timeout or self.DEFAULT_TIMEOUT

    # ─── public sync API ───
    def publish_text(
        self,
        channel: Channel,
        content: str,
        actor_name: Optional[str] = None,
        run_id: Optional[str] = None,
        decision_id: Optional[str] = None,
    ) -> PublishResult:
        return self._publish(
            channel,
            payload={"content": content},
            preview=content,
            actor_name=actor_name,
            run_id=run_id,
            decision_id=decision_id,
        )

    def publish_embed(
        self,
        channel: Channel,
        embed: dict[str, Any],
        actor_name: Optional[str] = None,
        run_id: Optional[str] = None,
        decision_id: Optional[str] = None,
    ) -> PublishResult:
        preview = embed.get("title", "") + " | " + (embed.get("description", "") or "")
        return self._publish(
            channel,
            payload={"embeds": [embed]},
            preview=preview,
            actor_name=actor_name,
            run_id=run_id,
            decision_id=decision_id,
        )

    # ─── public async API ───
    async def apublish_text(
        self,
        channel: Channel,
        content: str,
        actor_name: Optional[str] = None,
        run_id: Optional[str] = None,
        decision_id: Optional[str] = None,
    ) -> PublishResult:
        return await self._apublish(
            channel,
            payload={"content": content},
            preview=content,
            actor_name=actor_name,
            run_id=run_id,
            decision_id=decision_id,
        )

    async def apublish_embed(
        self,
        channel: Channel,
        embed: dict[str, Any],
        actor_name: Optional[str] = None,
        run_id: Optional[str] = None,
        decision_id: Optional[str] = None,
    ) -> PublishResult:
        preview = embed.get("title", "") + " | " + (embed.get("description", "") or "")
        return await self._apublish(
            channel,
            payload={"embeds": [embed]},
            preview=preview,
            actor_name=actor_name,
            run_id=run_id,
            decision_id=decision_id,
        )

    # ─── internal ───
    def _resolve_url(self, channel: Channel) -> Optional[str]:
        url = os.getenv(channel.env_var, "").strip()
        return url or None

    def _publish(
        self,
        channel: Channel,
        payload: dict[str, Any],
        preview: str,
        actor_name: Optional[str],
        run_id: Optional[str],
        decision_id: Optional[str],
    ) -> PublishResult:
        url = self._resolve_url(channel)
        if not url:
            return self._record_skip(channel, preview, actor_name, run_id, decision_id)

        last_status: Optional[int] = None
        last_err: Optional[str] = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(url, json=payload)
                last_status = resp.status_code
                if 200 <= resp.status_code < 300:
                    log_agent_message(
                        channel=channel.value,
                        content_preview=preview,
                        actor_name=actor_name,
                        run_id=run_id,
                        decision_id=decision_id,
                        http_status=resp.status_code,
                        retry_count=attempt,
                    )
                    return PublishResult(channel, True, resp.status_code, attempt)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.MAX_RETRIES:
                    time.sleep(0.5)
                    continue
                last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                break
            except httpx.HTTPError as exc:
                last_err = f"{type(exc).__name__}: {exc}"
                if attempt < self.MAX_RETRIES:
                    time.sleep(0.5)
                    continue
                break

        log_agent_message(
            channel=channel.value,
            content_preview=preview,
            actor_name=actor_name,
            run_id=run_id,
            decision_id=decision_id,
            http_status=last_status,
            retry_count=self.MAX_RETRIES,
            error_message=last_err,
        )
        logger.warning("discord publish failed channel=%s err=%s", channel.value, last_err)
        return PublishResult(channel, False, last_status, self.MAX_RETRIES, last_err)

    async def _apublish(
        self,
        channel: Channel,
        payload: dict[str, Any],
        preview: str,
        actor_name: Optional[str],
        run_id: Optional[str],
        decision_id: Optional[str],
    ) -> PublishResult:
        import asyncio

        url = self._resolve_url(channel)
        if not url:
            return self._record_skip(channel, preview, actor_name, run_id, decision_id)

        last_status: Optional[int] = None
        last_err: Optional[str] = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, json=payload)
                last_status = resp.status_code
                if 200 <= resp.status_code < 300:
                    log_agent_message(
                        channel=channel.value,
                        content_preview=preview,
                        actor_name=actor_name,
                        run_id=run_id,
                        decision_id=decision_id,
                        http_status=resp.status_code,
                        retry_count=attempt,
                    )
                    return PublishResult(channel, True, resp.status_code, attempt)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.MAX_RETRIES:
                    await asyncio.sleep(0.5)
                    continue
                last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                break
            except httpx.HTTPError as exc:
                last_err = f"{type(exc).__name__}: {exc}"
                if attempt < self.MAX_RETRIES:
                    await asyncio.sleep(0.5)
                    continue
                break

        log_agent_message(
            channel=channel.value,
            content_preview=preview,
            actor_name=actor_name,
            run_id=run_id,
            decision_id=decision_id,
            http_status=last_status,
            retry_count=self.MAX_RETRIES,
            error_message=last_err,
        )
        logger.warning("discord publish failed channel=%s err=%s", channel.value, last_err)
        return PublishResult(channel, False, last_status, self.MAX_RETRIES, last_err)

    def _record_skip(
        self,
        channel: Channel,
        preview: str,
        actor_name: Optional[str],
        run_id: Optional[str],
        decision_id: Optional[str],
    ) -> PublishResult:
        msg = f"webhook missing: env {channel.env_var} not set"
        log_agent_message(
            channel=channel.value,
            content_preview=preview,
            actor_name=actor_name,
            run_id=run_id,
            decision_id=decision_id,
            http_status=None,
            error_message=msg,
        )
        logger.info("discord publish skipped channel=%s reason=%s", channel.value, msg)
        return PublishResult(channel, False, None, 0, msg)


# Module-level convenience
_singleton: Optional[DiscordPublisher] = None


def publish(
    channel: Channel | str,
    content: str,
    actor_name: Optional[str] = None,
    run_id: Optional[str] = None,
    decision_id: Optional[str] = None,
) -> PublishResult:
    """Module-level sync publish — quick caller path.

    Usage:
        from nuri.agents.discord import publish, Channel
        publish(Channel.OPS, "freshness FAIL: prices stale")
    """
    global _singleton
    if _singleton is None:
        _singleton = DiscordPublisher()
    if isinstance(channel, str):
        channel = Channel(channel)
    return _singleton.publish_text(channel, content, actor_name, run_id, decision_id)


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m nuri.agents.discord.publisher <channel> <message>"""
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="discord-publisher")
    parser.add_argument("channel", choices=[c.value for c in Channel])
    parser.add_argument("message", help="text to publish")
    args = parser.parse_args(argv)

    result = publish(Channel(args.channel), args.message, actor_name="cli")
    if result.ok:
        print(f"✅ {args.channel}: HTTP {result.http_status} retry={result.retry_count}")
        return 0
    print(f"❌ {args.channel}: {result.error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())

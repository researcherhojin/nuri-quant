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
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

from nuri.core.db import log_agent_message

logger = logging.getLogger(__name__)

# .env auto-load — `python -m nuri.agents.discord.publisher ...` 단독 실행도 환경변수 로드.
load_dotenv(Path(__file__).resolve().parents[3] / ".env")


class Channel(str, Enum):
    """6-채널 enum — DB CHECK 제약과 동일 string. agent_control/agent_dev_log 는 E1 #582.

    BRIEF/OPS/INCIDENTS/ROLLOUT — 기존 알림 routing.
    AGENT_CONTROL — agent loop 의 HITL gate (사용자 ✅/❌ reaction 응답).
    AGENT_DEV_LOG — agent loop transcript (Codex spec → Claude patch → Qwen review).
    """

    BRIEF = "brief"
    OPS = "ops"
    INCIDENTS = "incidents"
    ROLLOUT = "rollout"
    AGENT_CONTROL = "agent_control"
    AGENT_DEV_LOG = "agent_dev_log"

    @property
    def env_var(self) -> str:
        # agent_control → DISCORD_WEBHOOK_AGENT_CONTROL (underscore-aware uppercase).
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

    @staticmethod
    def _enrich_embed_payload(payload: dict[str, Any], actor_name: Optional[str]) -> dict[str, Any]:
        """First embed 에 author=actor_name 자동 주입 (caller 가 author 미지정 시만).

        Discord embed 의 author 는 title 위에 표시 → 같은 채널의 여러 actor emit 을
        한눈에 구분 (사용자 통증 2026-05-03 — '어느 actor 가 publish 했는지' 채널만
        보고 알기 어려움). caller 가 author 를 직접 set 했으면 존중 + 미주입.
        """
        if not actor_name:
            return payload
        embeds = payload.get("embeds")
        if not embeds:
            return payload
        first = embeds[0]
        if not isinstance(first, dict) or "author" in first:
            return payload
        new_first = dict(first)
        new_first["author"] = {"name": actor_name[:256]}  # Discord author.name 제한
        new_payload = dict(payload)
        new_payload["embeds"] = [new_first, *list(embeds[1:])]
        return new_payload

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
                    resp = client.post(url, json=self._enrich_embed_payload(payload, actor_name))
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
                break  # pragma: no cover — final-attempt exit, retry path covered

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
                    resp = await client.post(url, json=self._enrich_embed_payload(payload, actor_name))
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
                break  # pragma: no cover — final-attempt exit, retry path covered

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


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())

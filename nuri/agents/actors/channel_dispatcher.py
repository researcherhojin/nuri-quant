"""ChannelDispatcher — single-writer Discord dispatcher (Codex Round 6, 2026-05-02).

Why this exists (사용자 통증 2026-05-02):
#brief 채널에 NVDA BUY/BUY/SELL 같은 conviction 으로 따로 발송 → 노이즈 폭발.
Codex 권고: per-event publish 패턴 폐기, dispatcher 가 outbox 의 pending event 들을
종합해서 1 embed 만 발송 (single-writer 패턴).

Layer: B (deterministic aggregation, ZERO LLM).

흐름:
    1. claim_pending_outbox(channel) — lease + claim_token 으로 atomically pending 픽업
    2. quiet-period gate (#brief 만): 마지막 stage 이후 60s 미경과 면 skip ("아직 더 올 수 있음")
    3. payload list → bucket_brief_digest() / bucket_generic_digest() 로 1 embed
    4. DiscordPublisher.publish_embed → success → mark_outbox_sent
                                       failure → mark_outbox_failed (재시도 가능)

Quiet-period (Codex 권고):
    daily cron 이 아니라 run-scoped flush. 마지막 #brief stage 이후 QUIET_PERIOD_SECONDS
    (60s) 동안 새 stage 가 없으면 "사용자가 받아도 되는 시점" 으로 판단해 dispatch.
    cron 은 단지 polling — 1분마다 깨어나서 quiet-period 체크.

#ops / #incidents / #rollout 은 quiet-period 무시하고 cron 주기마다 무조건 dispatch.
"""

from __future__ import annotations

from typing import Any, Optional

from nuri.agents.base import Actor, ActorResult, Layer, Outcome, RunContext
from nuri.agents.discord.outbox import bucket_brief_digest, bucket_generic_digest
from nuri.core.db import (
    claim_pending_outbox,
    mark_outbox_failed,
    mark_outbox_sent,
    query,
)

# #brief 의 quiet-period — 마지막 stage 이후 N초 동안 새 stage 없을 때만 dispatch.
QUIET_PERIOD_SECONDS = 60

# 1회 dispatch 당 최대 events. embed 가 너무 커지지 않게.
MAX_EVENTS_PER_DIGEST = 50

_CHANNEL_LABELS = {
    "brief": "Brief",
    "ops": "Ops",
    "incidents": "Incidents",
    "rollout": "Research Rollout",
}


def _last_stage_age_seconds(channel: str, db_path: Optional[Any]) -> Optional[int]:
    """가장 최근 pending row 의 created_at 으로부터 경과 초. row 없으면 None."""
    rows = query(
        """SELECT CAST((julianday('now') - julianday(MAX(created_at))) * 86400 AS INTEGER) AS age_s
             FROM discord_outbox
            WHERE channel = ? AND status = 'pending'""",
        (channel,),
        db_path=db_path,
    )
    if not rows:
        return None
    val = rows[0]["age_s"]
    return int(val) if val is not None else None


def _has_high_priority_pending(channel: str, db_path: Optional[Any]) -> bool:
    """high priority pending 이 1건이라도 있으면 quiet-period bypass."""
    rows = query(
        """SELECT 1 FROM discord_outbox
            WHERE channel = ? AND status = 'pending' AND priority = 'high'
            LIMIT 1""",
        (channel,),
        db_path=db_path,
    )
    return bool(rows)


class ChannelDispatcher(Actor):
    """Dispatch one channel's pending outbox to Discord as ONE digest embed.

    Usage:
        ChannelDispatcher().run({"channel": "brief"})
    """

    name = "channel-dispatcher"
    version = "0.1.0"
    layer = Layer.B

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        channel = input_data.get("channel")
        if channel not in ("brief", "ops", "incidents", "rollout"):
            raise ValueError(f"channel must be brief/ops/incidents/rollout, got {channel!r}")
        db_path = input_data.get("db_path")
        force = bool(input_data.get("force", False))

        # Quiet-period gate (#brief only)
        if channel == "brief" and not force:
            if not _has_high_priority_pending(channel, db_path):
                age = _last_stage_age_seconds(channel, db_path)
                if age is not None and age < QUIET_PERIOD_SECONDS:
                    return ActorResult(
                        output={
                            "channel": channel,
                            "skipped": "quiet-period",
                            "last_stage_age_seconds": age,
                            "threshold": QUIET_PERIOD_SECONDS,
                        },
                        outcome=Outcome.PASS,
                        input_summary=f"dispatch {channel} skipped quiet-period age={age}s",
                    )

        # Claim
        claim_token, claimed = claim_pending_outbox(channel, limit=MAX_EVENTS_PER_DIGEST, db_path=db_path)
        if not claimed:
            return ActorResult(
                output={"channel": channel, "skipped": "no-pending"},
                outcome=Outcome.PASS,
                input_summary=f"dispatch {channel} nothing pending",
            )

        ids = [r["id"] for r in claimed]
        payloads = [r["payload"] for r in claimed]

        # Compose 1 embed
        if channel == "brief":
            embed = bucket_brief_digest(payloads)
        else:
            embed = bucket_generic_digest(payloads, channel_label=_CHANNEL_LABELS[channel])

        # Send
        try:
            from nuri.agents.discord.publisher import Channel, DiscordPublisher

            result = DiscordPublisher().publish_embed(
                Channel(channel),
                embed=embed,
                actor_name=self.name,
                run_id=ctx.run_id,
            )
        except Exception as exc:  # noqa: BLE001 — webhook missing / module load
            mark_outbox_failed(ids, claim_token, error=f"publish exception: {exc!r}", db_path=db_path)
            return ActorResult(
                output={
                    "channel": channel,
                    "claimed_n": len(ids),
                    "error": str(exc)[:200],
                },
                outcome=Outcome.ERROR,
                sample_n=len(ids),
                input_summary=f"dispatch {channel} failed exc",
            )

        if result.ok:
            n_sent = mark_outbox_sent(ids, claim_token, db_path=db_path)
            return ActorResult(
                output={
                    "channel": channel,
                    "claimed_n": len(ids),
                    "marked_sent_n": n_sent,
                    "http_status": result.http_status,
                },
                outcome=Outcome.PASS,
                sample_n=len(ids),
                input_summary=f"dispatch {channel} sent={n_sent}",
            )
        else:
            mark_outbox_failed(
                ids,
                claim_token,
                error=result.error or f"HTTP {result.http_status}",
                db_path=db_path,
            )
            return ActorResult(
                output={
                    "channel": channel,
                    "claimed_n": len(ids),
                    "http_status": result.http_status,
                    "error": result.error,
                },
                outcome=Outcome.WARN,
                sample_n=len(ids),
                input_summary=f"dispatch {channel} failed http={result.http_status}",
            )


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m nuri.agents.actors.channel_dispatcher <channel> [--force]"""
    import argparse

    parser = argparse.ArgumentParser(prog="channel-dispatcher")
    parser.add_argument("channel", choices=["brief", "ops", "incidents", "rollout"])
    parser.add_argument("--force", action="store_true", help="bypass quiet-period gate")
    args = parser.parse_args(argv)

    result = ChannelDispatcher().run({"channel": args.channel, "force": args.force})
    print(f"{args.channel}: {result.output}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())

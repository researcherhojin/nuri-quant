"""OutboxWatchdog — alerts when discord_outbox health degrades (Codex Round 6).

Why this exists:
`scheduler.py` 의 `_run_*` 함수들은 모두 exception 흡수 (silent failure 패턴) →
ChannelDispatcher 가 죽어도 사용자가 모름. Watchdog 이 outbox 의 backlog /
oldest_pending_age 를 측정해서 threshold 넘으면 #ops 직접 발송 (recursion 방지
위해 outbox 안 쓰고 webhook 직접).

Layer: A (enforcement-style threshold check, ZERO LLM).

Thresholds (config 가능, 일단 conservative 로 시작):
    OLDEST_PENDING_ALERT_SECONDS = 30 * 60   # 30분
    PENDING_COUNT_ALERT_THRESHOLD = 100      # 한 채널에 100건 이상 backlog
"""

from __future__ import annotations

from typing import Any

from nuri.agents.base import Actor, ActorResult, Layer, Outcome, RunContext
from nuri.core.db import outbox_health
from nuri.core.timezone import kst_now, today_kst

OLDEST_PENDING_ALERT_SECONDS = 30 * 60  # 30분
PENDING_COUNT_ALERT_THRESHOLD = 100  # backlog 한도

# Watchdog 자체 alert 의 dedupe — 같은 issue 가 30분 안에 반복 emit 되지 않게
# (DB 안 거치고 caller 가 cron 빈도 조절. 여기는 1회 직접 발송만)


def _direct_publish_ops(embed: dict[str, Any]) -> dict[str, Any]:
    """Watchdog 전용 직접 발송 — outbox 안 거침 (recursion 방지).

    DiscordPublisher 가 webhook 미설정 시 graceful skip.
    """
    try:
        from nuri.agents.discord.publisher import Channel, DiscordPublisher

        result = DiscordPublisher().publish_embed(
            Channel.OPS,
            embed=embed,
            actor_name="outbox-watchdog",
        )
        return {"ok": result.ok, "http_status": result.http_status, "error": result.error}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "http_status": None, "error": f"{type(exc).__name__}: {exc}"}


class OutboxWatchdog(Actor):
    """Read outbox_health(); alert #ops directly if thresholds breached.

    Output:
        breaches: list of {channel, kind, value, threshold}
        published: {ok, http_status, error} or None
    """

    name = "outbox-watchdog"
    version = "0.1.0"
    layer = Layer.A

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        db_path = input_data.get("db_path")
        health = outbox_health(db_path=db_path)

        breaches: list[dict[str, Any]] = []

        # Check 1 — oldest_pending_age across channels
        age = health.get("oldest_pending_age_seconds")
        if age is not None and age > OLDEST_PENDING_ALERT_SECONDS:
            breaches.append(
                {
                    "channel": health.get("oldest_pending_channel"),
                    "kind": "oldest_pending_age",
                    "value": age,
                    "threshold": OLDEST_PENDING_ALERT_SECONDS,
                }
            )

        # Check 2 — per-channel pending count
        for channel, statuses in health.get("by_channel", {}).items():
            pending = int(statuses.get("pending", 0))
            if pending > PENDING_COUNT_ALERT_THRESHOLD:
                breaches.append(
                    {
                        "channel": channel,
                        "kind": "pending_count",
                        "value": pending,
                        "threshold": PENDING_COUNT_ALERT_THRESHOLD,
                    }
                )

        if not breaches:
            return ActorResult(
                output={"health": health, "breaches": [], "published": None},
                outcome=Outcome.PASS,
                input_summary="outbox watchdog clean",
            )

        # Compose alert embed (직접 #ops 발송)
        lines = [f"  - {b['channel']}: {b['kind']}={b['value']} > {b['threshold']}" for b in breaches]
        embed = {
            "title": f"Outbox Watchdog — {len(breaches)} breach(es)",
            "description": (
                f"Discord outbox health degraded ({today_kst()} {kst_now().strftime('%H:%M')} KST):\n"
                + "\n".join(lines)
                + "\n\nDispatcher 가 멈췄거나 webhook 발송이 반복 실패 중일 가능성. "
                + "`make scheduler-status` 또는 `python -m nuri.agents.actors.channel_dispatcher <channel> --force` 확인."
            ),
            "color": 0xE74C3C,
            "footer": {"text": "outbox-watchdog • direct emit (bypasses outbox)"},
        }
        published = _direct_publish_ops(embed)

        return ActorResult(
            output={"health": health, "breaches": breaches, "published": published},
            outcome=Outcome.WARN,
            sample_n=len(breaches),
            input_summary=f"watchdog {len(breaches)} breach published={published.get('ok')}",
        )


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m nuri.agents.actors.outbox_watchdog"""
    result = OutboxWatchdog().run({})
    print(f"breaches={len(result.output['breaches'])} health={result.output['health']}")
    if result.output.get("published"):
        print(f"published: {result.output['published']}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())

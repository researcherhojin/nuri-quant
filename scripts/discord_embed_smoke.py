"""Discord embed visual smoke test (#529 Phase 2 polish).

publish 4 sample embeds to #brief so user can visually verify formatting:
    1. status_embed success → Buy Candidates OK (green)
    2. status_embed fail    → Health Check fail (red)
    3. freshness_embed      → 3-check sample (mixed PASS/WARN/FAIL → red)
    4. actor_outcome_embed  → freshness-gatekeeper warn (amber)

Usage:
    make discord-test-embed
    # 또는 직접:
    .venv/bin/python scripts/discord_embed_smoke.py

ENV:
    DISCORD_WEBHOOK_BRIEF — 미설정 시 graceful skip (publisher 가 audit 에 'webhook missing' 기록).
"""

from __future__ import annotations

import sys

from nuri.agents.discord.embeds import (
    build_actor_outcome_embed,
    build_freshness_embed,
    build_status_embed,
)
from nuri.agents.discord.publisher import Channel, DiscordPublisher


def main() -> int:
    pub = DiscordPublisher()

    samples = [
        (
            "status (success)",
            build_status_embed(
                title="Buy Candidates",
                success=True,
                body="3 candidates passed all 10 SIEGE gates:\n- AAPL\n- NVDA\n- MSFT",
                fields={"exit": "0", "host": "Ehbebeui-MacBookPro.local"},
            ),
        ),
        (
            "status (failure)",
            build_status_embed(
                title="Health Check",
                success=False,
                body="single_writer.lock missing — pipeline halted.\n5 tables out of sync.",
                fields={"exit": "2", "host": "Ehbebeui-Macmini.local"},
            ),
        ),
        (
            "freshness",
            build_freshness_embed(
                [
                    {"key": "prices", "status": "PASS", "age_hours": 2.5},
                    {"key": "vix", "status": "WARN", "age_hours": 30.0},
                    {"key": "recommendations", "status": "FAIL", "age_hours": 200.5},
                ]
            ),
        ),
        (
            "actor outcome",
            build_actor_outcome_embed(
                actor_name="freshness-gatekeeper",
                outcome="warn",
                summary="VIX stale (30h > 24h SLA). Soft penalty: position cap 80%.",
                run_id="run-2026-04-30-smoke",
            ),
        ),
    ]

    rc = 0
    for label, embed_dict in samples:
        try:
            result = pub.publish_embed(Channel.BRIEF, embed_dict, actor_name="embed-smoke")
            status = "ok" if result.ok else f"fail ({result.error})"
            if not result.ok and result.error and "missing" not in result.error.lower():
                rc = 1  # webhook present 인데 실패 → 비정상
        except Exception as exc:  # noqa: BLE001 — smoke 는 audit/DB 부재 환경도 내성
            status = f"audit error ({type(exc).__name__}: {exc})"
        print(f"  [{label}] {status}", flush=True)

    return rc


if __name__ == "__main__":
    sys.exit(main())

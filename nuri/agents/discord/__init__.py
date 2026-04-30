"""nuri.agents.discord — multi-channel Discord bridge (#529 Phase 2).

publisher.py — outbound webhook (httpx async, 1 retry, audit-logged)
bot.py       — inbound discord.py Bot (slash commands → pipeline trigger)

채널 routing (4채널, env: DISCORD_WEBHOOK_<CHANNEL>):
    BRIEF      — 일별 시장 요약, premarket
    OPS        — freshness 경고, rollback 알림 (Layer A actor 결과)
    INCIDENTS  — 시스템 장애 (KIS 토큰 만료, scheduler heartbeat 끊김)
    ROLLOUT    — hypothesis canary 결과, walk-forward validation

Lazy import 으로 `python -m nuri.agents.discord.publisher` 시 runpy 경고 회피.
caller 는 `from nuri.agents.discord.publisher import publish` 직접 사용 가능.
"""

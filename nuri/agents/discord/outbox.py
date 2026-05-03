"""Discord outbox public API + digest layout helpers (Codex Round 6, 2026-05-02).

Caller-facing convenience wrapping `nuri.core.db.discord_outbox_ops`. 모든 actor 가
`stage_brief()` / `stage_ops()` / `stage_incident()` / `stage_rollout()` 4개 helper
하나만 호출하면 됨 — channel string 실수 / payload 형식 mismatch 방지.

**중요 invariant (Codex 단호한 권고)**:
모든 channel emit 은 **이 모듈** 또는 watchdog (recursion 방지) 만 직접 publish.
actor 가 `DiscordPublisher` 를 직접 호출하면 single-writer 깨짐 → CI 검사 추가
(future) + code review 차단.

Layout helpers:
    bucket_brief_digest(events) — Codex 권장 actionability bucket layout 으로
    여러 BUY/SELL/HOLD/BLOCK event 를 1 embed dict 로 합친다. dispatcher 가 호출.
"""

from __future__ import annotations

from typing import Any, Optional

from nuri.core.db import stage_outbox
from nuri.core.timezone import kst_now, today_kst

# Discord embed limits — agents/discord/embeds.py 와 동일 (Single source of truth
# 아니지만 import 순환 회피 위해 중복 정의)
_TITLE_MAX = 256
_DESC_MAX = 4000
_FIELD_NAME_MAX = 256
_FIELD_VALUE_MAX = 1024
_MAX_FIELDS = 25

_PRIORITY_BY_ACTION = {
    "BUY": 0,
    "SELL": 0,
    "BLOCK": 1,
    "CONFLICT": 1,
    "HOLD": 2,
    "INFO": 2,
}

# 사용자가 본 통증의 색상 단서 — bucket 별 색
_BUCKET_COLORS = {
    "Action Now": 0x2ECC71,  # green
    "Blocked / Conflict": 0xE74C3C,  # red
    "Lower Priority": 0x95A5A6,  # gray
}


def _truncate(text: str, limit: int) -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def stage_brief(
    payload: dict[str, Any],
    dedupe_key: Optional[str] = None,
    priority: str = "normal",
    actor_name: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Any] = None,
) -> Optional[int]:
    """Stage one event into #brief outbox. Dispatcher 가 종합해서 발송."""
    return stage_outbox(
        "brief",
        payload,
        priority=priority,
        dedupe_key=dedupe_key,
        actor_name=actor_name,
        run_id=run_id,
        db_path=db_path,
    )


def stage_ops(
    payload: dict[str, Any],
    dedupe_key: Optional[str] = None,
    priority: str = "normal",
    actor_name: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Any] = None,
) -> Optional[int]:
    """Stage one event into #ops outbox."""
    return stage_outbox(
        "ops",
        payload,
        priority=priority,
        dedupe_key=dedupe_key,
        actor_name=actor_name,
        run_id=run_id,
        db_path=db_path,
    )


def stage_incident(
    payload: dict[str, Any],
    dedupe_key: Optional[str] = None,
    priority: str = "normal",
    actor_name: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Any] = None,
) -> Optional[int]:
    """Stage one event into #incidents outbox."""
    return stage_outbox(
        "incidents",
        payload,
        priority=priority,
        dedupe_key=dedupe_key,
        actor_name=actor_name,
        run_id=run_id,
        db_path=db_path,
    )


def stage_rollout(
    payload: dict[str, Any],
    dedupe_key: Optional[str] = None,
    priority: str = "normal",
    actor_name: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Any] = None,
) -> Optional[int]:
    """Stage one event into #research-rollout outbox."""
    return stage_outbox(
        "rollout",
        payload,
        priority=priority,
        dedupe_key=dedupe_key,
        actor_name=actor_name,
        run_id=run_id,
        db_path=db_path,
    )


def stage_agent_control(
    payload: dict[str, Any],
    dedupe_key: Optional[str] = None,
    priority: str = "normal",
    actor_name: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Any] = None,
) -> Optional[int]:
    """Stage one event into #agent-control outbox (HITL gate, E1 #582).

    agent loop 의 verdict (PASS / NEEDS_REWORK / ABSTAIN) 를 사용자 ✅/❌ 응답
    대상으로 publish. inbound (E4) 가 reaction 잡으면 dedupe_key 로 매칭.
    """
    return stage_outbox(
        "agent_control",
        payload,
        priority=priority,
        dedupe_key=dedupe_key,
        actor_name=actor_name,
        run_id=run_id,
        db_path=db_path,
    )


def stage_agent_dev_log(
    payload: dict[str, Any],
    dedupe_key: Optional[str] = None,
    priority: str = "normal",
    actor_name: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Any] = None,
) -> Optional[int]:
    """Stage one event into #agent-dev-log outbox (transcript, E2 #578).

    Codex (Architect, spec) → Claude (Builder, patch) → Qwen (Adversarial Reviewer)
    각 단계의 산출물을 read-only transcript 로 publish.
    """
    return stage_outbox(
        "agent_dev_log",
        payload,
        priority=priority,
        dedupe_key=dedupe_key,
        actor_name=actor_name,
        run_id=run_id,
        db_path=db_path,
    )


# ─── digest layout (Codex Round 6 actionability bucket pattern) ──────────


def _classify_event(payload: dict[str, Any]) -> str:
    """Map event payload → bucket name.

    payload['kind']: BUY/SELL/HOLD/BLOCK/CONFLICT/INFO
    """
    kind = (payload.get("kind") or "").upper()
    pri = _PRIORITY_BY_ACTION.get(kind, 2)
    if pri == 0:
        return "Action Now"
    if pri == 1:
        return "Blocked / Conflict"
    return "Lower Priority"


def _format_event_line(payload: dict[str, Any]) -> str:
    """Compact one-line per event (Codex format).

    `NVDA | SELL | conv 0.81 | regime bear 0.72 | causal 0.68 | reason: stop-loss`
    """
    kind = (payload.get("kind") or "?").upper()
    ticker = payload.get("ticker", "?")
    parts = [str(ticker), kind]
    if "conviction" in payload:
        parts.append(f"conv {float(payload['conviction']):.2f}")
    for opt in ("regime", "causal", "horizon", "reason", "note"):
        if opt in payload and payload[opt] is not None:
            parts.append(f"{opt}: {payload[opt]}")
    return " | ".join(parts)


def bucket_brief_digest(
    events: list[dict[str, Any]],
    title_prefix: str = "Nuri Brief Digest",
) -> dict[str, Any]:
    """Compose multiple stage_brief() payloads into ONE digest embed.

    Codex layout:
        Title:       "Nuri Brief Digest | YYYY-MM-DD HH:MM KST | N opinions"
        Description: "BUY 2 | SELL 1 | BLOCK 2 | manual execute only"
        Fields:      Action Now / Blocked|Conflict / Lower Priority
                     each = compact one-line list, hard cap to fit Discord limits

    Returns Discord embed dict — caller passes to DiscordPublisher.publish_embed.
    """
    if not events:
        return {
            "title": _truncate(
                f"{title_prefix} | {today_kst()} {kst_now().strftime('%H:%M')} KST | 0 opinions", _TITLE_MAX
            ),
            "description": "(no pending events)",
            "color": _BUCKET_COLORS["Lower Priority"],
            "fields": [],
            "footer": {"text": "manual execute only"},
        }

    counts = {"BUY": 0, "SELL": 0, "BLOCK": 0, "CONFLICT": 0, "HOLD": 0, "INFO": 0}
    buckets: dict[str, list[str]] = {
        "Action Now": [],
        "Blocked / Conflict": [],
        "Lower Priority": [],
    }
    for ev in events:
        kind = (ev.get("kind") or "").upper()
        if kind in counts:
            counts[kind] += 1
        bucket = _classify_event(ev)
        buckets[bucket].append(_format_event_line(ev))

    n = len(events)
    title = f"{title_prefix} | {today_kst()} {kst_now().strftime('%H:%M')} KST | {n} opinions"

    desc_parts = []
    for kind in ("BUY", "SELL", "BLOCK", "CONFLICT", "HOLD"):
        if counts[kind]:
            desc_parts.append(f"{kind} {counts[kind]}")
    desc = " | ".join(desc_parts) + " | manual execute only" if desc_parts else "manual execute only"

    fields = []
    for bucket_name in ("Action Now", "Blocked / Conflict", "Lower Priority"):
        lines = buckets[bucket_name]
        if not lines:
            continue
        # Truncate per-line to keep value < 1024
        body_lines: list[str] = []
        running = 0
        for ln in lines:
            ln_trunc = _truncate(ln, 200)
            if running + len(ln_trunc) + 1 > _FIELD_VALUE_MAX:
                hidden = len(lines) - len(body_lines)
                body_lines.append(f"… (+{hidden} more)")
                break
            body_lines.append(ln_trunc)
            running += len(ln_trunc) + 1
        fields.append(
            {
                "name": _truncate(f"{bucket_name} ({len(lines)})", _FIELD_NAME_MAX),
                "value": _truncate("\n".join(body_lines), _FIELD_VALUE_MAX),
                "inline": False,
            }
        )
        if len(fields) >= _MAX_FIELDS:
            break

    color = (
        _BUCKET_COLORS["Action Now"]
        if buckets["Action Now"]
        else (
            _BUCKET_COLORS["Blocked / Conflict"] if buckets["Blocked / Conflict"] else _BUCKET_COLORS["Lower Priority"]
        )
    )

    return {
        "title": _truncate(title, _TITLE_MAX),
        "description": _truncate(desc, _DESC_MAX),
        "color": color,
        "fields": fields,
        "footer": {"text": "manual execute only — STRATEGY §7.1"},
    }


def bucket_generic_digest(
    events: list[dict[str, Any]],
    channel_label: str,
    color: int = 0x3498DB,
) -> dict[str, Any]:
    """Generic digest for #ops / #incidents / #rollout.

    No actionability bucketing — group by 'kind' or 'category' if present,
    otherwise flat list.
    """
    if not events:
        return {
            "title": _truncate(
                f"{channel_label} Digest | {today_kst()} {kst_now().strftime('%H:%M')} KST | 0 events", _TITLE_MAX
            ),
            "description": "(no pending events)",
            "color": color,
            "fields": [],
            "footer": {"text": "auto digest"},
        }

    n = len(events)
    title = f"{channel_label} Digest | {today_kst()} {kst_now().strftime('%H:%M')} KST | {n} events"

    by_group: dict[str, list[str]] = {}
    for ev in events:
        group = str(ev.get("kind") or ev.get("category") or "general")
        line = ev.get("summary") or _format_event_line(ev)
        by_group.setdefault(group, []).append(str(line))

    fields = []
    for group, lines in by_group.items():
        body_lines: list[str] = []
        running = 0
        for ln in lines:
            ln_trunc = _truncate(ln, 200)
            if running + len(ln_trunc) + 1 > _FIELD_VALUE_MAX:
                hidden = len(lines) - len(body_lines)
                body_lines.append(f"… (+{hidden} more)")
                break
            body_lines.append(ln_trunc)
            running += len(ln_trunc) + 1
        fields.append(
            {
                "name": _truncate(f"{group} ({len(lines)})", _FIELD_NAME_MAX),
                "value": _truncate("\n".join(body_lines), _FIELD_VALUE_MAX),
                "inline": False,
            }
        )
        if len(fields) >= _MAX_FIELDS:
            break

    return {
        "title": _truncate(title, _TITLE_MAX),
        "description": _truncate(f"{n} aggregated events", _DESC_MAX),
        "color": color,
        "fields": fields,
        "footer": {"text": "auto digest"},
    }

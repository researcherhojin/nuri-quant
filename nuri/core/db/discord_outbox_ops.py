"""Discord outbox writes — single-writer outbox for channel digests (Codex Round 6, 2026-05-02).

Why this exists (사용자 통증 2026-05-02):
#brief 채널에 NVDA BUY/BUY/SELL 같은 conviction 으로 따로 발송 → 노이즈 폭발.
Codex 권고: per-event publish 패턴 폐기, outbox stage → cron/quiet-period dispatcher
가 종합 1 embed 발송. 본 모듈은 outbox 의 storage layer.

State machine:
    pending → claim_pending() → claimed (claim_token + claimed_at)
                              → mark_sent() → sent
                              → mark_failed() → failed (재시도 또는 dropped)

Lease semantics:
    dispatcher crash 시 claimed_at 이 stale (> CLAIM_LEASE_SECONDS) 이면 다른
    dispatcher 가 다시 claim 가능 → at-least-once 발송. 멱등성은 caller (digest
    dedupe_key) 책임.

Layer: 데이터 레이어 (액터 호출 X). caller = `nuri/agents/discord/outbox.py` (stage)
+ `nuri/agents/actors/channel_dispatcher.py` (claim/mark).
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any, Optional

from .connection import get_db

_CHANNELS = ("brief", "ops", "incidents", "rollout", "agent_control", "agent_dev_log")
_PRIORITIES = ("high", "normal", "low")
_STATUSES = ("pending", "claimed", "sent", "failed", "dropped")

# Lease 만료 — claimed 상태에서 이 시간 지나면 다른 dispatcher 가 재claim
CLAIM_LEASE_SECONDS = 300  # 5분


def stage_outbox(
    channel: str,
    payload: dict[str, Any],
    priority: str = "normal",
    dedupe_key: Optional[str] = None,
    scheduled_for: Optional[str] = None,
    actor_name: Optional[str] = None,
    run_id: Optional[str] = None,
    dedupe_strategy: str = "skip",
    db_path: Optional[Path] = None,
) -> Optional[int]:
    """Stage one Discord embed/text payload for later digest dispatch.

    payload: dict — Discord embed dict or {"content": "..."}. JSON-serialized 저장.
    priority:
        high   — scheduled_for=now (즉시 dispatcher 픽업)
        normal — 다음 cron 주기
        low    — 후순위
    dedupe_key: caller 의 멱등성 키. 같은 key 의 pending row 가 있으면:
        dedupe_strategy='skip'    — return None (이미 stage 됨)
        dedupe_strategy='replace' — 기존 pending payload 를 새 것으로 덮음
    scheduled_for: 'YYYY-MM-DD HH:MM:SS' or None (now). future timestamp 면 그
        시점 이후 dispatcher 가 픽업.
    """
    if channel not in _CHANNELS:
        raise ValueError(f"channel must be {_CHANNELS}, got {channel!r}")
    if priority not in _PRIORITIES:
        raise ValueError(f"priority must be {_PRIORITIES}, got {priority!r}")
    if dedupe_strategy not in ("skip", "replace"):
        raise ValueError(f"dedupe_strategy must be skip|replace, got {dedupe_strategy!r}")

    payload_json = json.dumps(payload, default=str)
    sched = scheduled_for  # None → DB default datetime('now')

    with get_db(db_path) as conn:
        if dedupe_key:
            existing = conn.execute(
                """SELECT id FROM discord_outbox
                    WHERE channel = ? AND dedupe_key = ? AND status = 'pending'
                    LIMIT 1""",
                (channel, dedupe_key),
            ).fetchone()
            if existing is not None:
                if dedupe_strategy == "skip":
                    return None
                conn.execute(
                    """UPDATE discord_outbox
                          SET payload_json = ?, priority = ?,
                              scheduled_for = COALESCE(?, scheduled_for),
                              actor_name = COALESCE(?, actor_name),
                              run_id = COALESCE(?, run_id)
                        WHERE id = ?""",
                    (payload_json, priority, sched, actor_name, run_id, existing["id"]),
                )
                return int(existing["id"])

        if sched is None:
            cursor = conn.execute(
                """INSERT INTO discord_outbox
                       (channel, payload_json, priority, dedupe_key,
                        actor_name, run_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (channel, payload_json, priority, dedupe_key, actor_name, run_id),
            )
        else:
            cursor = conn.execute(
                """INSERT INTO discord_outbox
                       (channel, payload_json, priority, dedupe_key,
                        scheduled_for, actor_name, run_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (channel, payload_json, priority, dedupe_key, sched, actor_name, run_id),
            )
        return int(cursor.lastrowid or 0)


def claim_pending_outbox(
    channel: str,
    limit: int = 100,
    db_path: Optional[Path] = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Atomically claim up to `limit` ready pending rows for `channel`.

    Returns (claim_token, rows). 빈 배열 = 처리할 것 없음.

    "Ready" = status='pending' AND scheduled_for <= now()
        OR  status='claimed' AND claimed_at < now() - CLAIM_LEASE_SECONDS
                                                    (lease 만료 → 재claim).
    Priority order: high > normal > low, scheduled_for 오름차순 (오래된 것 먼저).
    Same claim_token 으로 mark_sent / mark_failed 호출 → 다른 dispatcher 침범 방지.
    """
    if channel not in _CHANNELS:
        raise ValueError(f"channel must be {_CHANNELS}, got {channel!r}")
    claim_token = secrets.token_hex(8)

    with get_db(db_path) as conn:
        rows = conn.execute(
            """SELECT id FROM discord_outbox
                WHERE channel = ?
                  AND (
                       (status = 'pending' AND scheduled_for <= datetime('now'))
                    OR (status = 'claimed' AND claimed_at < datetime('now', ?))
                  )
                ORDER BY
                    CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                    scheduled_for ASC,
                    id ASC
                LIMIT ?""",
            (channel, f"-{CLAIM_LEASE_SECONDS} seconds", limit),
        ).fetchall()
        if not rows:
            return claim_token, []

        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"""UPDATE discord_outbox
                   SET status = 'claimed',
                       claim_token = ?,
                       claimed_at = datetime('now'),
                       attempt_count = attempt_count + 1
                 WHERE id IN ({placeholders})""",
            (claim_token, *ids),
        )

        claimed = conn.execute(
            f"""SELECT id, channel, payload_json, priority, dedupe_key,
                       scheduled_for, attempt_count, actor_name, run_id, created_at
                  FROM discord_outbox
                 WHERE id IN ({placeholders})
                 ORDER BY
                     CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                     scheduled_for ASC,
                     id ASC""",
            ids,
        ).fetchall()

    result = []
    for r in claimed:
        d = dict(r)
        try:
            d["payload"] = json.loads(d.pop("payload_json"))
        except json.JSONDecodeError:
            d["payload"] = {}
        result.append(d)
    return claim_token, result


def mark_outbox_sent(
    ids: list[int],
    claim_token: str,
    db_path: Optional[Path] = None,
) -> int:
    """Mark claimed rows as sent. claim_token 일치하는 row 만 업데이트 (lease 보호).

    Returns updated row count.
    """
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    with get_db(db_path) as conn:
        cursor = conn.execute(
            f"""UPDATE discord_outbox
                   SET status = 'sent', sent_at = datetime('now'), last_error = NULL
                 WHERE id IN ({placeholders}) AND claim_token = ?""",
            (*ids, claim_token),
        )
        return int(cursor.rowcount or 0)


def mark_outbox_failed(
    ids: list[int],
    claim_token: str,
    error: str,
    drop: bool = False,
    db_path: Optional[Path] = None,
) -> int:
    """Mark claimed rows as failed (or dropped if drop=True).

    failed → 후속 claim 가능 (재시도). dropped → terminal.
    claim_token 일치하는 row 만 업데이트.
    """
    if not ids:
        return 0
    new_status = "dropped" if drop else "failed"
    placeholders = ",".join("?" for _ in ids)
    with get_db(db_path) as conn:
        cursor = conn.execute(
            f"""UPDATE discord_outbox
                   SET status = ?, last_error = ?, claim_token = NULL, claimed_at = NULL
                 WHERE id IN ({placeholders}) AND claim_token = ?""",
            (new_status, error[:500], *ids, claim_token),
        )
        return int(cursor.rowcount or 0)


def outbox_health(db_path: Optional[Path] = None) -> dict[str, Any]:
    """Watchdog metrics — channel × status 별 count + oldest pending age.

    Returns:
        {
          'by_channel': {channel: {status: count, ...}, ...},
          'oldest_pending_age_seconds': int (across all channels) or None,
          'oldest_pending_channel': str or None,
        }
    """
    with get_db(db_path) as conn:
        rows = conn.execute(
            """SELECT channel, status, COUNT(*) AS n
                 FROM discord_outbox
                GROUP BY channel, status"""
        ).fetchall()
        by_channel: dict[str, dict[str, int]] = {c: {} for c in _CHANNELS}
        for r in rows:
            by_channel[r["channel"]][r["status"]] = int(r["n"])

        oldest = conn.execute(
            """SELECT channel,
                      CAST((julianday('now') - julianday(scheduled_for)) * 86400 AS INTEGER) AS age_s
                 FROM discord_outbox
                WHERE status = 'pending'
                ORDER BY scheduled_for ASC
                LIMIT 1"""
        ).fetchone()

    return {
        "by_channel": by_channel,
        "oldest_pending_age_seconds": int(oldest["age_s"]) if oldest else None,
        "oldest_pending_channel": oldest["channel"] if oldest else None,
    }

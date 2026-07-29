#!/usr/bin/env python3
"""고아 agent run 정리 — `started` 인 채 완료를 보고하지 않은 원장 행 (#942).

프로세스가 kill 되면 `finish_agent_run()` 이 호출되지 못해 `agent_run_ledger` 에
`status='started' AND finished_at IS NULL` 행이 남는다. 2026-06 FD exhaustion
사태(#778/#779) 때 63 행이 그렇게 남았다.

이 행들은 **늙기만 한다.** `SREIncidentAgent._detect_orphan_run` 은 나이만 보므로
매 스캔마다 critical 을 재발화하고, dedupe 가 target 단위라 같은 actor 에 진짜
orphan 이 새로 생겨도 묻힌다 — 알림이 상시 켜져 있으면 아무도 안 본다.

정리 원칙:
  - **삭제하지 않는다.** 그때 완료를 못 한 건 사실이므로 기록으로 남긴다.
  - status 는 `timeout` — 실패했다는 증거는 없고, 완료를 보고하지 않았을 뿐이다.
  - `finished_at` 은 **`started_at` 그대로** 둔다. `datetime('now')` 로 찍으면
    40일짜리 duration 이 생겨 원장이 거짓말을 한다.

Usage:
    python scripts/ops/reap_orphan_runs.py                # dry-run (기본)
    python scripts/ops/reap_orphan_runs.py --apply
    python scripts/ops/reap_orphan_runs.py --older-than 24 --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nuri.core.db import get_db, query  # noqa: E402

DEFAULT_OLDER_THAN_HOURS = 24
REAP_REASON = "reaped by scripts/ops/reap_orphan_runs.py (#942) — 프로세스가 완료를 보고하지 않음"


def find_orphans(older_than_hours: int, db_path: Optional[Path] = None) -> list[dict]:
    """`started` + `finished_at IS NULL` + 지정 시간 초과 행."""
    rows = query(
        """SELECT run_id, actor_name, started_at,
                  (julianday('now') - julianday(started_at)) * 24.0 AS age_hours
             FROM agent_run_ledger
            WHERE status = 'started' AND finished_at IS NULL
              AND datetime(started_at) < datetime('now', ?)
            ORDER BY started_at""",
        (f"-{int(older_than_hours * 60)} minutes",),
        db_path=db_path,
    )
    return [dict(r) for r in rows]


def reap(orphans: list[dict], db_path: Optional[Path] = None) -> int:
    """timeout 으로 마감. finished_at = started_at (duration 을 날조하지 않는다)."""
    if not orphans:
        return 0
    with get_db(db_path) as conn:
        for o in orphans:
            conn.execute(
                """UPDATE agent_run_ledger
                      SET status = 'timeout',
                          finished_at = started_at,
                          error_message = ?
                    WHERE run_id = ? AND status = 'started' AND finished_at IS NULL""",
                (REAP_REASON, o["run_id"]),
            )
    return len(orphans)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="고아 agent run 정리 (#942)")
    ap.add_argument("--apply", action="store_true", help="실제 반영 (기본은 dry-run)")
    ap.add_argument("--older-than", type=int, default=DEFAULT_OLDER_THAN_HOURS, help="시간 (기본 24)")
    ap.add_argument("--db-path", type=Path, default=None)
    args = ap.parse_args(argv)

    orphans = find_orphans(args.older_than, db_path=args.db_path)
    if not orphans:
        print(f"고아 run 없음 ({args.older_than}h 초과 기준)")
        return 0

    by_actor: dict[str, int] = {}
    for o in orphans:
        by_actor[o["actor_name"]] = by_actor.get(o["actor_name"], 0) + 1
    print(f"고아 run {len(orphans)}건 ({args.older_than}h 초과):")
    for actor, n in sorted(by_actor.items()):
        print(f"  {actor}: {n}건")
    print(f"  가장 오래된: {orphans[0]['started_at']} ({orphans[0]['age_hours']:.1f}h)")
    print(f"  가장 최근  : {orphans[-1]['started_at']} ({orphans[-1]['age_hours']:.1f}h)")

    if not args.apply:
        print("\ndry-run — 반영하려면 --apply")
        return 0

    n = reap(orphans, db_path=args.db_path)
    print(f"\n✓ {n}건 timeout 으로 마감 (삭제 아님, finished_at = started_at)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

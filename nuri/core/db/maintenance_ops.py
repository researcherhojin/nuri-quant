"""유지보수 발굴 후보 원장 writes/reads — maintenance_candidates (#1308 Phase 0).

## Shadow mode 의 계약

이 원장은 **로컬이 전부다**. staged → 사람 approve/reject → 사람이 손으로 이슈화한 뒤
published 표기. GitHub 쓰기는 어디에도 없다 — 자동 발행은 "proposal-only" 가 아니라
그 자체가 리뷰·평판·privacy 비용이 있는 외부 쓰기다 (이슈 본문, codex challenge 반영).

## 재검출은 중복이 아니라 신호다

같은 fingerprint 는 영원히 1행 (`UNIQUE`) — 재검출 시 `last_seen_at`/`seen_count` 만
갱신한다. 이 설계가 곧 4주 Reflect 의 측정이다: novelty = 새 fingerprint 비율,
precision = 리뷰된 것 중 승인 비율, 검토 지연 = reviewed_at − created_at. 건수 목표는
일부러 없다 (Goodhart — "실행당 결함 ≥1건" 은 쉬운 잡동사니 양산 유인).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from .connection import get_db

logger = logging.getLogger(__name__)

#: 리뷰 동사 → 상태. publish 는 **사람이 손으로 이슈를 만든 뒤** 표기하는 것이지
#: 자동 발행이 아니다 (Phase 0 불변).
REVIEW_VERDICTS = ("approved", "rejected", "published")


def stage_maintenance_candidate(
    axis: str,
    title: str,
    detail: str,
    fingerprint: str,
    run_id: str,
    db_path: Optional[Path] = None,
) -> tuple[str, int]:
    """후보 1건 staged — 기존 fingerprint 면 재검출 갱신. ("staged"|"seen", row id) 반환.

    privacy 스캔은 **호출자(actor)가 staging 전에** 끝냈어야 한다 — 여기는 저장만 한다.
    (스캔을 여기 두면 db_path 격리 테스트가 스캐너 subprocess 에 묶인다.)
    """
    from nuri.core.timezone import kst_now

    now = kst_now().isoformat()
    with get_db(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM maintenance_candidates WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE maintenance_candidates SET last_seen_at = ?, seen_count = seen_count + 1 WHERE id = ?",
                (now, existing[0]),
            )
            return ("seen", int(existing[0]))
        cur = conn.execute(
            """INSERT INTO maintenance_candidates
               (created_at, axis, title, detail, fingerprint, run_id, status, last_seen_at)
               VALUES (?, ?, ?, ?, ?, ?, 'staged', ?)""",
            (now, axis, title, detail, fingerprint, run_id, now),
        )
        return ("staged", int(cur.lastrowid or 0))


def review_maintenance_candidate(
    candidate_id: int,
    verdict: str,
    note: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> bool:
    """사람 리뷰 기록. 미존재 id 는 False — 조용히 성공으로 위장하지 않는다."""
    from nuri.core.timezone import kst_now

    if verdict not in REVIEW_VERDICTS:
        raise ValueError(f"verdict must be one of {REVIEW_VERDICTS}, got {verdict!r}")
    with get_db(db_path) as conn:
        cur = conn.execute(
            "UPDATE maintenance_candidates SET status = ?, reviewed_at = ?, review_note = ? WHERE id = ?",
            (verdict, kst_now().isoformat(), note, candidate_id),
        )
        return cur.rowcount > 0


def list_maintenance_candidates(status: Optional[str] = None, db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    from nuri.core.db import query

    if status:
        return query(
            "SELECT * FROM maintenance_candidates WHERE status = ? ORDER BY created_at DESC",
            (status,),
            db_path=db_path,
            readonly=True,
        )
    return query(
        "SELECT * FROM maintenance_candidates ORDER BY created_at DESC",
        db_path=db_path,
        readonly=True,
    )


def maintenance_review_stats(db_path: Optional[Path] = None) -> dict[str, Any]:
    """4주 Reflect 지표 — precision · novelty · 검토 지연(중앙값, 시간).

    - precision: 리뷰된 것(approved/rejected/published) 중 approved+published 비율.
      리뷰 0건이면 None — 0.0 으로 표기하면 "전부 기각" 과 구분이 안 된다.
    - novelty: 전체 검출(seen_count 합) 중 고유 fingerprint 비율.
    - review_latency_h_median: reviewed_at − created_at 중앙값 (시간).
    """
    from nuri.core.db import query

    rows = query(
        "SELECT status, seen_count, created_at, reviewed_at FROM maintenance_candidates",
        db_path=db_path,
        readonly=True,
    )
    total_detections = sum(r["seen_count"] for r in rows)
    reviewed = [r for r in rows if r["status"] in REVIEW_VERDICTS]
    accepted = [r for r in reviewed if r["status"] in ("approved", "published")]

    latencies: list[float] = []
    for r in reviewed:
        if r["reviewed_at"] and r["created_at"]:
            from datetime import datetime

            delta = datetime.fromisoformat(r["reviewed_at"]) - datetime.fromisoformat(r["created_at"])
            latencies.append(delta.total_seconds() / 3600)
    latencies.sort()
    median = latencies[len(latencies) // 2] if latencies else None

    return {
        "candidates": len(rows),
        "detections": total_detections,
        "reviewed": len(reviewed),
        "precision": (len(accepted) / len(reviewed)) if reviewed else None,
        "novelty": (len(rows) / total_detections) if total_detections else None,
        "review_latency_h_median": median,
        "staged_pending": sum(1 for r in rows if r["status"] == "staged"),
    }

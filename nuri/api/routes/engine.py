"""SIEGE-inspired engine API: gate, conflicts, memory, certifications."""

import json
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from nuri.api.auth import require_write_auth
from nuri.core.db import query

router = APIRouter(tags=["engine"])


@router.get("/gate")
def get_gate():
    """파이프라인 게이트 상태 (전 단계)."""
    from nuri.trading.engine.gate import check_all_gates

    gates = check_all_gates()
    return {phase: asdict(result) for phase, result in gates.items()}


@router.get("/gate/{phase}")
def get_gate_phase(phase: str):
    """특정 단계 게이트 상태."""
    from nuri.trading.engine.gate import check_gate

    result = check_gate(phase)
    return asdict(result)


@router.get("/conflicts")
def get_conflicts():
    """시그널 충돌 감지."""
    from nuri.trading.engine.conflicts import detect_conflicts

    conflicts = detect_conflicts()
    return {
        "conflicts": [asdict(c) for c in conflicts],
        "count": len(conflicts),
        "high": len([c for c in conflicts if c.severity == "high"]),
    }


@router.get("/memory")
def get_memory():
    """전략 학습 메모리 — 성과 변화 감지."""
    from nuri.trading.engine.memory import detect_drift

    drifts = detect_drift()
    return {
        "drifts": [asdict(d) for d in drifts],
        "critical": len([d for d in drifts if d.status == "critical"]),
        "degrading": len([d for d in drifts if d.status == "degrading"]),
    }


@router.post("/memory/snapshot")
def post_memory_snapshot(user=Depends(require_write_auth)):
    """전략 성과 스냅샷 저장 (인증 필요)."""
    from nuri.trading.engine.memory import save_snapshot

    n = save_snapshot()
    return {"saved": n}


# ─── V1: SIEGE certifications history API (E4-0a instrumentation 소비) ───
# E4-0a (PR #410) 가 매 certify() 실행을 certifications 테이블에 persist.
# 이 endpoint 는 dashboard V2 timeline chart + CLI siege_history.py 와 같은
# observation loop 를 API 로 노출. Read-only, auth 불필요 (dashboard public read).


def _format_cert_row(row: dict) -> dict:
    """certifications row → API response shape. conditions_json 은 parsed list 로."""
    try:
        conditions = json.loads(row.get("conditions_json") or "[]")
    except json.JSONDecodeError:
        conditions = []
    return {
        "id": row["id"],
        "timestamp": row["timestamp"],
        "certified": bool(row["certified"]),
        "score": row["score"],
        "total_conditions": row["total_conditions"],
        "passed": row["passed"],
        "failed": row["failed"],
        "warnings": row["warnings"],
        "regime": row["regime"],
        "portfolio_hash": row["portfolio_hash"],
        "caller": row["caller"],
        "created_at": row["created_at"],
        "conditions": conditions,
    }


@router.get("/certifications")
def get_certifications_history(
    limit: int = Query(30, ge=1, le=500),
    caller: Optional[str] = Query(None, description="caller 필터 (예: cli, api:actions:health)"),
    regime: Optional[str] = Query(None, description="regime 필터"),
    since: Optional[str] = Query(None, description="ISO timestamp 이후만 (YYYY-MM-DDTHH:MM:SS)"),
):
    """SIEGE 인증 실행 history (E4-0a 이후 persist 된 모든 row).

    - 최신순 정렬 (id DESC)
    - 필터: `caller`, `regime`, `since` (optional)
    - `limit` 1-500 (default 30 — dashboard timeline 용)
    - Response 에 `conditions_json` 을 parsed `conditions` 리스트로 제공 (JSON double-encode 방지)
    """
    where: list[str] = []
    params: list = []
    if caller:
        where.append("caller = ?")
        params.append(caller)
    if regime:
        where.append("regime = ?")
        params.append(regime)
    if since:
        where.append("timestamp >= ?")
        params.append(since)

    sql = "SELECT id, timestamp, certified, score, total_conditions, passed, failed, warnings, regime, portfolio_hash, caller, created_at, conditions_json FROM certifications"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    rows = query(sql, params)

    # Summary: 각 caller / regime 분포 + 최근 hash 변경 count (portfolio transition 감지)
    total_query = "SELECT COUNT(*) AS c FROM certifications"
    total_rows = query(total_query)
    total = total_rows[0]["c"] if total_rows else 0

    return {
        "items": [_format_cert_row(r) for r in rows],
        "count": len(rows),
        "total_in_db": total,
        "filters": {"caller": caller, "regime": regime, "since": since, "limit": limit},
    }


@router.get("/certifications/summary")
def get_certifications_summary(days: int = Query(30, ge=1, le=365)):
    """최근 N일간 집계 — dashboard overview 카드 용.

    Returns:
        - `certified_rate`: PASS 비율
        - `avg_score`: 평균 score
        - `by_caller`: caller 별 run count
        - `by_regime`: regime 별 run count
        - `latest`: 가장 최근 cert 1건 요약
    """
    from nuri.core.timezone import kst_now

    cutoff = (kst_now().replace(tzinfo=None) - __import__("datetime").timedelta(days=days)).isoformat()

    rows = query(
        """SELECT certified, score, regime, caller, timestamp FROM certifications
           WHERE timestamp >= ? ORDER BY id DESC""",
        (cutoff,),
    )

    if not rows:
        return {
            "days": days,
            "count": 0,
            "certified_rate": None,
            "avg_score": None,
            "by_caller": {},
            "by_regime": {},
            "latest": None,
        }

    certified_n = sum(1 for r in rows if r["certified"])
    total = len(rows)

    by_caller: dict = {}
    for r in rows:
        k = r["caller"] or "(none)"
        by_caller[k] = by_caller.get(k, 0) + 1

    by_regime: dict = {}
    for r in rows:
        k = r["regime"] or "(none)"
        by_regime[k] = by_regime.get(k, 0) + 1

    latest = rows[0]
    return {
        "days": days,
        "count": total,
        "certified_rate": round(certified_n / total * 100, 1),
        "avg_score": round(sum(r["score"] for r in rows) / total, 1),
        "by_caller": by_caller,
        "by_regime": by_regime,
        "latest": {
            "timestamp": latest["timestamp"],
            "certified": bool(latest["certified"]),
            "score": latest["score"],
            "regime": latest["regime"],
            "caller": latest["caller"],
        },
    }


@router.get("/certifications/{cert_id}")
def get_certification(cert_id: int):
    """단일 certification detail — timeline 클릭 시 modal 렌더용."""
    rows = query(
        "SELECT id, timestamp, certified, score, total_conditions, passed, failed, warnings, regime, portfolio_hash, caller, created_at, conditions_json FROM certifications WHERE id = ?",
        (cert_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"certification id={cert_id} 없음")
    return _format_cert_row(rows[0])

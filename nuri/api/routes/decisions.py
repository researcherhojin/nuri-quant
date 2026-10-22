"""Decision Intelligence API — 의사결정 저널 조회 + lineage."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from nuri.core.db import get_decision_ledger, get_decision_with_evidence, get_decisions
from nuri.core.rules import RULES
from nuri.quant.validation.decision_alpha import sample_membership
from nuri.trading.engine.decisions import get_decision_summary

router = APIRouter(tags=["decisions"])


@router.get("/decisions")
def list_decisions(
    ticker: Optional[str] = Query(None, description="종목 필터"),
    outcome: Optional[str] = Query(None, description="결과 필터 (pending/success/failure)"),
    limit: int = Query(100, ge=1, le=500),
):
    """의사결정 목록 조회."""
    decisions = get_decisions(
        ticker=ticker.upper() if ticker else None,
        outcome=outcome,
        limit=limit,
    )
    summary = get_decision_summary()
    return {"decisions": decisions, "count": len(decisions), "summary": summary}


@router.get("/decisions/{decision_id}")
def get_decision_detail(decision_id: int):
    """의사결정 상세 + evidence chain (lineage) + 측정 원장 (#1909).

    `pnl_*` 은 벤치마크 미보정 가격 수익률이다. alpha 는 `outcomes` (decision_outcomes) 에만 있고,
    그 결정이 §3.11 판정 표본인지는 `measurement.sample` 이 말한다.
    """
    decision = get_decision_with_evidence(decision_id)
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")
    ledger = get_decision_ledger(decision["ticker"], decision["date"])
    rec = ledger["recommendation"]
    mm = RULES["measurement_mode"]
    decision["signals"] = rec["signals"] if rec else None
    decision["outcomes"] = ledger["outcomes"]
    decision["measurement"] = {
        **sample_membership(rec),
        "benchmark": mm["benchmark"],
        "primary_window_days": mm["primary_window_days"],
        "declared_date": mm["declared_date"],
    }
    return decision

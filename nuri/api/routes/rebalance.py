"""리밸런싱 API."""
from dataclasses import asdict

from fastapi import APIRouter, Query

router = APIRouter(tags=["rebalance"])


@router.get("/rebalance")
def get_rebalance(method: str = Query("rp", pattern="^(mvo|rp)$")):
    """레짐 적응 리밸런싱 제안."""
    try:
        from nuri.trading.recommend.rebalance import regime_aware_rebalance
        actions = regime_aware_rebalance(method=method)
        return {
            "actions": [asdict(a) for a in actions],
            "method": method,
            "actionable": len([a for a in actions if a.action != "HOLD"]),
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/tracking")
def get_tracking():
    """추천 추적 리포트."""
    from nuri.trading.recommend.tracker import get_tracking_report
    return get_tracking_report()

"""외부 분석 데이터 API — TipRanks, Dataroma, Macrotrends 등 저장/조회."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from nuri.api.auth import require_write_auth

router = APIRouter(tags=["external"])


class ExternalInput(BaseModel):
    source: str
    ticker: str
    data_type: str
    value: str
    numeric_value: float | None = None
    details: str = ""


@router.get("/external")
def get_external_summary():
    """외부 데이터 전체 요약."""
    from nuri.collectors.external import get_external_summary

    return get_external_summary()


@router.get("/external/{ticker}")
def get_ticker_external(ticker: str):
    """종목별 외부 데이터 조회."""
    from nuri.collectors.external import get_external

    data = get_external(ticker.upper())
    return {"ticker": ticker.upper(), "data": data, "count": len(data)}


@router.post("/external")
def save_external_data(item: ExternalInput, user=Depends(require_write_auth)):
    """외부 분석 데이터 저장 (인증 필요)."""
    from nuri.collectors.external import save_external
    from nuri.core.db import audit_log

    ok = save_external(
        source=item.source,
        ticker=item.ticker.upper(),
        data_type=item.data_type,
        value=item.value,
        numeric_value=item.numeric_value,
        details=item.details,
    )
    if ok:
        audit_log(
            "INSERT",
            "external_analysis",
            item.ticker.upper(),
            f"{item.source}/{item.data_type}={item.value}",
            user_id=user.get("sub", "unknown"),
        )
    return {"ok": ok}


@router.post("/external/tipranks")
def save_tipranks_batch(items: list[dict], user=Depends(require_write_auth)):
    """TipRanks 데이터 일괄 저장."""
    from nuri.collectors.external import save_tipranks

    count = 0
    for item in items:
        try:
            save_tipranks(
                ticker=item["ticker"].upper(),
                consensus=item["consensus"],
                target_price=float(item["target_price"]),
                analyst_count=int(item.get("analyst_count", 0)),
                upside_pct=item.get("upside_pct"),
            )
            count += 1
        except Exception:
            pass
    return {"saved": count, "total": len(items)}

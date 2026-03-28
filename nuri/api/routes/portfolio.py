"""포트폴리오 + 리스크 API."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from nuri.api.auth import require_write_auth
from nuri.core.db import query, upsert_portfolio

router = APIRouter(tags=["portfolio"])


class HoldingInput(BaseModel):
    account: str
    ticker: str
    quantity: float
    avg_price: float
    currency: str = "USD"
    sector: str = ""


@router.get("/portfolio")
def get_portfolio():
    """종목별 보유 현황."""
    rows = query("""
        SELECT p.ticker, p.account, p.quantity, p.avg_price, p.currency, p.sector,
               pr.close as latest_price, pr.date as price_date
        FROM portfolio p
        LEFT JOIN (
            SELECT ticker, close, date FROM prices
            WHERE (ticker, date) IN (SELECT ticker, MAX(date) FROM prices GROUP BY ticker)
        ) pr ON p.ticker = pr.ticker
        ORDER BY p.ticker
    """)
    return {"holdings": rows, "count": len(rows)}


@router.post("/portfolio")
def add_holding(holding: HoldingInput, user=Depends(require_write_auth)):
    """보유 종목 추가/수정 (인증 필요)."""
    record = holding.model_dump()
    record["ticker"] = record["ticker"].upper()
    upsert_portfolio([record])
    return {"ok": True, "ticker": record["ticker"]}


@router.delete("/portfolio/{account}/{ticker}")
def delete_holding(account: str, ticker: str, user=Depends(require_write_auth)):
    """보유 종목 삭제 (인증 필요)."""
    from nuri.core.db import get_db
    ticker = ticker.upper()
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM portfolio WHERE account=? AND ticker=?",
            (account, ticker),
        )
    if cur.rowcount == 0:
        return {"ok": False, "error": "Not found"}
    return {"ok": True, "deleted": ticker}


@router.get("/risk")
def get_risk():
    """리스크 지표."""
    try:
        from nuri.analysis.risk import analyze_risk
        metrics = analyze_risk()
        # numpy → Python 변환
        result = {}
        for k, v in metrics.items():
            if hasattr(v, "item"):
                result[k] = v.item()
            elif isinstance(v, (list, dict, str, int, float, bool, type(None))):
                result[k] = v
            else:
                result[k] = str(v)
        return result
    except Exception as e:
        return {"error": str(e)}

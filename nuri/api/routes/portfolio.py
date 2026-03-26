"""포트폴리오 + 리스크 API."""
from fastapi import APIRouter

from nuri.core.db import query, query_df

router = APIRouter(tags=["portfolio"])


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

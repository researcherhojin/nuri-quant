"""포트폴리오 + 리스크 API."""
import re
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from nuri.api.auth import require_write_auth
from nuri.core.db import query, upsert_portfolio

router = APIRouter(tags=["portfolio"])

# ticker 포맷: 영문 대문자 1~10자 + 선택적 .KS 접미사 + 선택적 숫자(한국 종목)
_TICKER_PATTERN = re.compile(r"^[A-Z0-9]{1,10}(\.[A-Z]{1,3})?$")

# 허용 계좌명
_VALID_ACCOUNTS = {"test", "demo", "sample", "pension", "irp", "test"}


class CurrencyEnum(str, Enum):
    USD = "USD"
    KRW = "KRW"


class HoldingInput(BaseModel):
    account: str
    ticker: str
    quantity: float
    avg_price: float
    currency: CurrencyEnum = CurrencyEnum.USD
    sector: str = ""

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        v = v.upper().strip()
        if not _TICKER_PATTERN.match(v):
            raise ValueError(f"유효하지 않은 ticker 포맷: {v} (영문+숫자 1~10자, 선택적 .KS)")
        return v

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("quantity는 0보다 커야 합니다")
        if v > 100_000:
            raise ValueError("quantity 최대 100,000주")
        return v

    @field_validator("avg_price")
    @classmethod
    def validate_avg_price(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("avg_price는 0보다 커야 합니다")
        if v > 10_000_000:
            raise ValueError("avg_price 최대 10,000,000")
        return v

    @field_validator("account")
    @classmethod
    def validate_account(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in _VALID_ACCOUNTS:
            raise ValueError(f"유효하지 않은 계좌: {v} (허용: {', '.join(sorted(_VALID_ACCOUNTS))})")
        return v

    @field_validator("sector")
    @classmethod
    def validate_sector(cls, v: str) -> str:
        if len(v) > 50:
            raise ValueError("sector 최대 50자")
        return v.strip()


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

    account = account.lower().strip()
    ticker = ticker.upper().strip()

    if account not in _VALID_ACCOUNTS:
        raise HTTPException(status_code=400, detail=f"유효하지 않은 계좌: {account}")
    if not _TICKER_PATTERN.match(ticker):
        raise HTTPException(status_code=400, detail=f"유효하지 않은 ticker: {ticker}")

    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM portfolio WHERE account=? AND ticker=?",
            (account, ticker),
        )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="종목 미발견")
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

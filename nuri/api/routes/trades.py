"""매매 실행 추적 API — 추천에 대한 실제 매매 기록."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from nuri.api.auth import require_write_auth
from nuri.core.db import audit_log, get_trades, upsert_trade

router = APIRouter(tags=["trades"])


class TradeInput(BaseModel):
    """매매 실행 기록 입력."""
    recommendation_id: Optional[int] = None
    ticker: str
    action: str
    executed_at: str
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    exit_date: Optional[str] = None
    exit_reason: Optional[str] = None
    shares: Optional[float] = None
    notes: Optional[str] = None

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        v = v.upper().strip()
        if not v or len(v) > 15:
            raise ValueError("ticker는 1~15자")
        return v

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        v = v.upper().strip()
        if v not in ("BUY", "SELL"):
            raise ValueError("action은 BUY 또는 SELL")
        return v

    @field_validator("executed_at")
    @classmethod
    def validate_executed_at(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            try:
                datetime.strptime(v, "%Y-%m-%d %H:%M")
            except ValueError:
                raise ValueError("executed_at 형식: YYYY-MM-DD 또는 YYYY-MM-DD HH:MM")
        return v


class TradeUpdateInput(BaseModel):
    """매매 종료 정보 업데이트."""
    exit_price: Optional[float] = None
    exit_date: Optional[str] = None
    exit_reason: Optional[str] = None
    notes: Optional[str] = None


@router.post("/trades")
def create_trade(trade: TradeInput, user=Depends(require_write_auth)):
    """매매 실행 기록 저장."""
    data = trade.model_dump(exclude_none=True)
    trade_id = upsert_trade(data)
    audit_log("INSERT", "trades", trade.ticker,
              f"action={trade.action} shares={trade.shares}",
              user_id=user.get("sub", "unknown"))
    return {"ok": True, "trade_id": trade_id}


@router.get("/trades")
def list_trades(ticker: Optional[str] = Query(None, description="종목 필터")):
    """매매 실행 기록 조회."""
    trades = get_trades(ticker=ticker.upper() if ticker else None)
    return {"trades": trades, "count": len(trades)}


@router.put("/trades/{trade_id}")
def update_trade(trade_id: int, update: TradeUpdateInput, user=Depends(require_write_auth)):
    """매매 종료 정보 업데이트 (exit_price, exit_date, exit_reason)."""
    data = update.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(status_code=400, detail="업데이트할 필드 없음")
    data["id"] = trade_id
    upsert_trade(data)
    audit_log("UPDATE", "trades", "",
              f"trade_id={trade_id}", user_id=user.get("sub", "unknown"))
    return {"ok": True, "trade_id": trade_id}

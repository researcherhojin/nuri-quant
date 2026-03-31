"""포트폴리오 + 리스크 API."""
import csv
import io
import logging
import re
from enum import Enum
from typing import Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from nuri.api.auth import require_write_auth
from nuri.core.db import audit_log, query, upsert_portfolio
from nuri.core.portfolio_sync import sync_portfolio_to_yaml

logger = logging.getLogger(__name__)

# PUT에서 허용하는 컬럼명 (동적 SQL 방어)
_UPDATABLE_COLUMNS = {"quantity", "avg_price", "currency", "sector"}

router = APIRouter(tags=["portfolio"])

# ticker 포맷: 영문 대문자 1~10자 + 선택적 .KS 접미사 + 선택적 숫자(한국 종목)
_TICKER_PATTERN = re.compile(r"^[A-Z0-9]{1,10}(\.[A-Z]{1,3})?$")

# 허용 계좌명
_VALID_ACCOUNTS = {"kakaopay", "mirae", "toss", "pension", "irp", "test", "sample"}


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


class HoldingUpdate(BaseModel):
    """보유 종목 수정용 모델. 모든 필드 optional — 전달된 필드만 업데이트."""
    quantity: Optional[float] = None
    avg_price: Optional[float] = None
    currency: Optional[CurrencyEnum] = None
    sector: Optional[str] = None

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if v <= 0:
                raise ValueError("quantity는 0보다 커야 합니다")
            if v > 100_000:
                raise ValueError("quantity 최대 100,000주")
        return v

    @field_validator("avg_price")
    @classmethod
    def validate_avg_price(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if v <= 0:
                raise ValueError("avg_price는 0보다 커야 합니다")
            if v > 10_000_000:
                raise ValueError("avg_price 최대 10,000,000")
        return v

    @field_validator("sector")
    @classmethod
    def validate_sector(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 50:
            raise ValueError("sector 최대 50자")
        return v.strip() if v is not None else v


def _try_sync_yaml():
    """YAML 동기화 시도. 실패해도 DB 변경은 유지."""
    try:
        sync_portfolio_to_yaml()
    except Exception:
        logger.exception("portfolio.yaml 동기화 실패 — DB 변경은 정상 반영됨")


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
    audit_log("INSERT", "portfolio", record["ticker"],
              f"account={record['account']} qty={record['quantity']} avg={record['avg_price']}",
              user_id=user.get("sub", "unknown"))
    _try_sync_yaml()
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
    audit_log("DELETE", "portfolio", ticker,
              f"account={account}", user_id=user.get("sub", "unknown"))
    _try_sync_yaml()
    return {"ok": True, "deleted": ticker}


@router.put("/portfolio/{account}/{ticker}")
def update_holding(account: str, ticker: str, update: HoldingUpdate, user=Depends(require_write_auth)):
    """보유 종목 수정 (인증 필요). 전달된 필드만 업데이트."""
    from nuri.core.db import get_db

    account = account.lower().strip()
    ticker = ticker.upper().strip()

    if account not in _VALID_ACCOUNTS:
        raise HTTPException(status_code=400, detail=f"유효하지 않은 계좌: {account}")
    if not _TICKER_PATTERN.match(ticker):
        raise HTTPException(status_code=400, detail=f"유효하지 않은 ticker: {ticker}")

    # 변경할 필드만 추출
    changes = update.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status_code=400, detail="수정할 필드가 없습니다")

    # 허용 컬럼 검증 (동적 SQL 방어)
    invalid_cols = set(changes.keys()) - _UPDATABLE_COLUMNS
    if invalid_cols:  # pragma: no cover — Pydantic이 먼저 필터링, 방어 코드
        raise HTTPException(status_code=400, detail=f"수정 불가 필드: {invalid_cols}")

    # SET 절 동적 생성
    set_clauses = [f"{col} = ?" for col in changes]
    set_clauses.append("updated_at = datetime('now')")
    values = list(changes.values()) + [account, ticker]

    with get_db() as conn:
        cur = conn.execute(
            f"UPDATE portfolio SET {', '.join(set_clauses)} WHERE account=? AND ticker=?",
            values,
        )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="종목 미발견")

    audit_log("UPDATE", "portfolio", ticker,
              f"account={account} changes={changes}",
              user_id=user.get("sub", "unknown"))
    _try_sync_yaml()
    return {"ok": True, "ticker": ticker, "updated": changes}


# ─── Import / Export ───

_CSV_REQUIRED = {"account", "ticker", "quantity", "avg_price"}
_CSV_OPTIONAL = {"currency", "sector"}
_CSV_ALL = _CSV_REQUIRED | _CSV_OPTIONAL
_MAX_IMPORT_ROWS = 500


@router.post("/portfolio/import")
def import_portfolio(file: UploadFile, user=Depends(require_write_auth)):
    """CSV 파일로 포트폴리오 일괄 등록 (인증 필요).

    CSV 필수 컬럼: account, ticker, quantity, avg_price
    CSV 선택 컬럼: currency (default USD), sector (default "")
    """
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="CSV 파일만 지원합니다 (.csv)")

    try:
        content = file.file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="UTF-8 인코딩 파일만 지원합니다")

    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV 헤더가 없습니다")

    headers = {h.strip().lower() for h in reader.fieldnames}
    missing = _CSV_REQUIRED - headers
    if missing:
        raise HTTPException(status_code=400, detail=f"필수 컬럼 누락: {', '.join(sorted(missing))}")

    records = []
    errors = []
    for i, row in enumerate(reader, start=2):
        if i - 1 > _MAX_IMPORT_ROWS:
            raise HTTPException(status_code=400, detail=f"최대 {_MAX_IMPORT_ROWS}행까지 지원")

        # 공백 정리 + 키 소문자화
        row = {k.strip().lower(): v.strip() for k, v in row.items() if k}

        # 필수 필드 비어있는지 체크
        empty = [col for col in _CSV_REQUIRED if not row.get(col)]
        if empty:
            errors.append(f"행 {i}: 빈 필드 {', '.join(empty)}")
            continue

        ticker = row["ticker"].upper()
        if not _TICKER_PATTERN.match(ticker):
            errors.append(f"행 {i}: 유효하지 않은 ticker '{ticker}'")
            continue

        account = row["account"].lower()
        if account not in _VALID_ACCOUNTS:
            errors.append(f"행 {i}: 유효하지 않은 계좌 '{account}'")
            continue

        try:
            qty = float(row["quantity"])
            avg = float(row["avg_price"])
        except ValueError:
            errors.append(f"행 {i}: 숫자 변환 실패 (quantity/avg_price)")
            continue

        if qty <= 0 or avg <= 0:
            errors.append(f"행 {i}: quantity/avg_price는 0보다 커야 합니다")
            continue

        records.append({
            "account": account,
            "ticker": ticker,
            "quantity": qty,
            "avg_price": avg,
            "currency": row.get("currency", "USD").upper() or "USD",
            "sector": row.get("sector", ""),
        })

    if not records and errors:
        raise HTTPException(status_code=400, detail=f"유효한 행 없음: {'; '.join(errors[:5])}")

    count = upsert_portfolio(records)
    audit_log("IMPORT", "portfolio", f"{count} records",
              f"file={file.filename}", user_id=user.get("sub", "unknown"))
    _try_sync_yaml()
    return {"ok": True, "imported": count, "errors": errors}


@router.get("/portfolio/export")
def export_portfolio(format: str = "csv"):
    """포트폴리오 CSV/YAML 다운로드."""
    rows = query(
        "SELECT account, ticker, quantity, avg_price, currency, sector "
        "FROM portfolio ORDER BY account, ticker"
    )

    if format == "yaml":
        # 계좌별 그룹핑
        accounts: dict = {}
        for r in rows:
            acct = r["account"]
            if acct not in accounts:
                accounts[acct] = {"currency": r["currency"], "holdings": []}
            accounts[acct]["holdings"].append({
                "ticker": r["ticker"],
                "qty": r["quantity"],
                "avg": r["avg_price"],
                **({"sector": r["sector"]} if r["sector"] else {}),
            })
        from nuri.core.portfolio_sync import _HoldingFlowDumper
        content = yaml.dump(
            {"accounts": accounts}, Dumper=_HoldingFlowDumper,
            allow_unicode=True, default_flow_style=False, sort_keys=False,
        )
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="application/x-yaml",
            headers={"Content-Disposition": "attachment; filename=portfolio.yaml"},
        )

    if format != "csv":
        raise HTTPException(status_code=400, detail="format은 csv 또는 yaml만 지원")

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["account", "ticker", "quantity", "avg_price", "currency", "sector"])
    writer.writeheader()
    for r in rows:
        writer.writerow({
            "account": r["account"],
            "ticker": r["ticker"],
            "quantity": r["quantity"],
            "avg_price": r["avg_price"],
            "currency": r["currency"],
            "sector": r["sector"] or "",
        })
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=portfolio.csv"},
    )


# ─── Sample Data ───

_SAMPLE_PORTFOLIO = [
    {"account": "sample", "ticker": "AAPL", "quantity": 10, "avg_price": 190.0, "currency": "USD", "sector": "BigTech"},
    {"account": "sample", "ticker": "NVDA", "quantity": 5, "avg_price": 130.0, "currency": "USD", "sector": "Semiconductor"},
    {"account": "sample", "ticker": "GOOGL", "quantity": 3, "avg_price": 170.0, "currency": "USD", "sector": "BigTech"},
    {"account": "sample", "ticker": "TSLA", "quantity": 8, "avg_price": 250.0, "currency": "USD", "sector": "EV/AI"},
    {"account": "sample", "ticker": "VOO", "quantity": 2, "avg_price": 500.0, "currency": "USD", "sector": "ETF"},
]


@router.post("/portfolio/sample")
def load_sample_portfolio(user=Depends(require_write_auth)):
    """샘플 포트폴리오 로드 (기존 sample 계좌 데이터 교체)."""
    from nuri.core.db import get_db

    # 기존 sample 계좌 데이터 삭제
    with get_db() as conn:
        conn.execute("DELETE FROM portfolio WHERE account='sample'")

    count = upsert_portfolio(_SAMPLE_PORTFOLIO)
    audit_log("SAMPLE", "portfolio", f"{count} records",
              "loaded sample portfolio", user_id=user.get("sub", "unknown"))
    _try_sync_yaml()
    return {"ok": True, "loaded": count}


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

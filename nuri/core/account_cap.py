"""Per-account position cap derivation — #518 phase 2a (E2 multi-account fix).

같은 티커가 여러 계좌에 동시 보유되면 각 계좌의 strategy.max_single_position
기준으로 독립 cap 을 가진다. Brokerage Alpha Main (core 15%) 과 Brokerage Alpha
Sub (active 25%) 은 동일 NVDA 보유라도 2 개의 독립 slot — held_add 모드 emit
시 (ticker, account) tuple 단위로 cap 계산한다.

Cost basis (qty × avg_price) 를 사용 — current price drift 가 cap 결정에
관여하지 않도록. 매수 권고는 "추가로 얼마나 더 살 수 있나" 결정이므로 cost
대비 헤드룸이 직관적이다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from nuri.core.db import query
from nuri.core.rules import get_account_strategy


def derive_position_cap(
    ticker: str,
    account: str,
    db_path: Optional[Path] = None,
) -> dict:
    """Per-account cap derivation.

    Args:
        ticker: 평가 대상 티커.
        account: 계좌 ID (portfolio.yaml accounts key).
        db_path: 테스트용 DB path override.

    Returns:
        dict with keys:
            - account: 계좌 ID (echo)
            - ticker: 티커 (echo)
            - current_pct: 현재 포지션 % (cost basis, 같은 계좌 내)
            - cap_max_pct: max_single_position × 100 (전략별)
            - headroom_pct: max(0, cap_max_pct - current_pct)
    """
    strategy = get_account_strategy(account)
    cap_max_pct = float(strategy.get("max_single_position", 0.15)) * 100

    rows = query(
        "SELECT ticker, quantity, avg_price FROM portfolio WHERE account = ?",
        (account,),
        db_path=db_path,
    )

    account_total = sum(float(r["quantity"]) * float(r["avg_price"]) for r in rows if r["quantity"] and r["avg_price"])
    position_value = sum(
        float(r["quantity"]) * float(r["avg_price"])
        for r in rows
        if r["ticker"] == ticker and r["quantity"] and r["avg_price"]
    )
    current_pct = (position_value / account_total * 100) if account_total > 0 else 0.0

    return {
        "account": account,
        "ticker": ticker,
        "current_pct": round(current_pct, 2),
        "cap_max_pct": round(cap_max_pct, 2),
        "headroom_pct": round(max(0.0, cap_max_pct - current_pct), 2),
    }

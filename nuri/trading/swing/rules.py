# pyright: reportArgumentType=false, reportCallIssue=false, reportAttributeAccessIssue=false, reportOperatorIssue=false, reportOptionalMemberAccess=false, reportOptionalSubscript=false, reportOptionalOperand=false
"""
스윙 트레이드 규칙 엔진.

스캐너 결과 + 멀티 에이전트 합의 → 진입 판정.
보유 중인 포지션 → 청산 조건 체크.

규칙:
- 진입: scanner score ≥ 20 + agent consensus BUY + confidence ≥ 50
- 목표 수익: +10% (take profit)
- 손절: -5% (stop loss)
- 최대 보유: 7 거래일
- 반대 시그널: agent consensus SELL → 조기 청산

사용법:
    python -m nuri.trading.swing.rules
    python -m nuri.trading.swing.rules --check   # 보유 포지션 청산 체크
"""

import argparse
import logging
from dataclasses import dataclass
from datetime import datetime

from nuri.core.db import get_db, init_db, query
from nuri.core.rules import (
    SWING_MAX_HOLD_DAYS,
    SWING_MIN_AGENT_CONFIDENCE,
    SWING_MIN_SCAN_SCORE,
    SWING_STOP_LOSS,
    TAKE_PROFIT_SWING,
)
from nuri.core.timezone import kst_now, today_kst

logger = logging.getLogger(__name__)

TAKE_PROFIT_PCT = float(TAKE_PROFIT_SWING.get("target_2", 10))
STOP_LOSS_PCT = float(SWING_STOP_LOSS)
MAX_HOLD_DAYS = int(SWING_MAX_HOLD_DAYS)
MIN_SCAN_SCORE = int(SWING_MIN_SCAN_SCORE)
MIN_AGENT_CONFIDENCE = int(SWING_MIN_AGENT_CONFIDENCE)


@dataclass
class SwingEntry:
    """스윙 진입 판정."""

    ticker: str
    price: float
    scan_signal: str
    scan_score: float
    agent_action: str
    agent_confidence: float
    agent_agreement: float
    approved: bool
    reason: str


@dataclass
class SwingExit:
    """스윙 청산 판정."""

    ticker: str
    entry_price: float
    current_price: float
    return_pct: float
    hold_days: int
    exit_reason: str  # "take_profit", "stop_loss", "max_hold", "agent_sell", "hold"
    should_exit: bool


def evaluate_entries(scan_results=None, market: str = "us", db_path=None) -> list[SwingEntry]:
    """스캐너 결과 → 멀티 에이전트 분석 → 진입 판정."""
    if scan_results is None:
        from nuri.trading.swing.scanner import scan_market

        scan_results = scan_market(market=market)

    if not scan_results:
        return []

    from nuri.trading.agents.consensus import analyze_ticker

    entries = []
    for sr in scan_results:
        if sr.score < MIN_SCAN_SCORE:
            continue

        # 이미 오픈 포지션이 있는지 확인
        existing = query(
            "SELECT id FROM swing_trades WHERE ticker = ? AND status = 'open'",
            (sr.ticker,),
            db_path=db_path,
        )
        if existing:
            continue

        # 멀티 에이전트 합의
        consensus = analyze_ticker(sr.ticker, db_path=db_path)

        approved = (
            consensus.final_action == "BUY"
            and consensus.final_confidence >= MIN_AGENT_CONFIDENCE
            and sr.score >= MIN_SCAN_SCORE
        )

        reason_parts = [f"scan: {sr.signal}(score={sr.score:.0f})"]
        reason_parts.append(
            f"agents: {consensus.final_action}(conf={consensus.final_confidence:.0f}, agree={consensus.agreement_rate:.0%})"
        )
        if not approved:
            if consensus.final_action != "BUY":
                reason_parts.append(f"거부: 에이전트 {consensus.final_action}")
            if consensus.final_confidence < MIN_AGENT_CONFIDENCE:
                reason_parts.append(f"거부: 신뢰도 {consensus.final_confidence:.0f} < {MIN_AGENT_CONFIDENCE}")

        entries.append(
            SwingEntry(
                ticker=sr.ticker,
                price=sr.price,
                scan_signal=sr.signal,
                scan_score=sr.score,
                agent_action=consensus.final_action,
                agent_confidence=consensus.final_confidence,
                agent_agreement=consensus.agreement_rate,
                approved=approved,
                reason="; ".join(reason_parts),
            )
        )

    return entries


def save_entries(entries: list[SwingEntry], db_path=None) -> int:
    """승인된 진입을 swing_trades에 저장."""
    approved = [e for e in entries if e.approved]
    if not approved:
        return 0

    today = today_kst()
    records = [
        {
            "ticker": e.ticker,
            "entry_date": today,
            "entry_price": e.price,
            "entry_signal": e.scan_signal,
            "agent_action": e.agent_action,
            "agent_confidence": e.agent_confidence,
            "agent_agreement": e.agent_agreement,
        }
        for e in approved
    ]

    with get_db(db_path) as conn:
        conn.executemany(
            """INSERT OR IGNORE INTO swing_trades
               (ticker, entry_date, entry_price, entry_signal,
                agent_action, agent_confidence, agent_agreement)
               VALUES (:ticker, :entry_date, :entry_price, :entry_signal,
                       :agent_action, :agent_confidence, :agent_agreement)""",
            records,
        )
        return len(records)


def check_exits(db_path=None) -> list[SwingExit]:
    """오픈 포지션 청산 조건 체크."""
    open_trades = query(
        "SELECT * FROM swing_trades WHERE status = 'open'",
        db_path=db_path,
    )
    if not open_trades:
        return []

    from nuri.trading.agents.consensus import analyze_ticker

    today = kst_now().replace(tzinfo=None)
    exits = []

    for trade in open_trades:
        ticker = trade["ticker"]
        entry_price = trade["entry_price"]
        entry_date = datetime.strptime(trade["entry_date"], "%Y-%m-%d")
        hold_days = (today - entry_date).days

        # 현재 가격
        price_row = query(
            "SELECT close, date FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (ticker,),
            db_path=db_path,
        )

        # prices에 없으면 yfinance에서 직접 가져오기
        if not price_row or not price_row[0]["close"]:
            try:
                import yfinance as yf

                data = yf.download(ticker, period="5d", progress=False)
                if not data.empty:
                    current_price = float(data["Close"].squeeze().iloc[-1])
                else:
                    continue
            except Exception:
                continue
        else:
            current_price = price_row[0]["close"]

        return_pct = (current_price - entry_price) / entry_price * 100

        # 청산 조건 체크 (우선순위순)
        exit_reason = "hold"
        should_exit = False

        if return_pct >= TAKE_PROFIT_PCT:
            exit_reason = "take_profit"
            should_exit = True
        elif return_pct <= STOP_LOSS_PCT:
            exit_reason = "stop_loss"
            should_exit = True
        elif hold_days >= MAX_HOLD_DAYS:
            exit_reason = "max_hold"
            should_exit = True
        else:
            # 에이전트 재분석 — SELL이면 조기 청산
            try:
                consensus = analyze_ticker(ticker, db_path=db_path)
                if consensus.final_action == "SELL" and consensus.final_confidence >= 70:
                    exit_reason = "agent_sell"
                    should_exit = True
            except Exception:
                pass

        exits.append(
            SwingExit(
                ticker=ticker,
                entry_price=entry_price,
                current_price=round(current_price, 2),
                return_pct=round(return_pct, 2),
                hold_days=hold_days,
                exit_reason=exit_reason,
                should_exit=should_exit,
            )
        )

        # 청산 실행
        if should_exit:
            with get_db(db_path) as conn:
                conn.execute(
                    "UPDATE swing_trades SET status='closed', exit_date=?, exit_price=?, "
                    "exit_reason=?, return_pct=? WHERE id=?",
                    (today.strftime("%Y-%m-%d"), current_price, exit_reason, round(return_pct, 2), trade["id"]),
                )

    return exits


def print_entries(entries: list[SwingEntry]) -> None:
    if not entries:
        print("진입 후보 없음")
        return

    approved = [e for e in entries if e.approved]
    rejected = [e for e in entries if not e.approved]

    print(f"\n{'=' * 85}")
    print(f"  Swing Trade Entries — {len(approved)} approved, {len(rejected)} rejected")
    print(f"{'=' * 85}")

    if approved:
        print("\n  APPROVED:")
        print(f"  {'Ticker':<8} {'Price':>10} {'Signal':<14} {'Score':>6} {'Agent':>6} {'Conf':>5} {'Agree':>6}")
        print(f"  {'-' * 58}")
        for e in approved:
            print(
                f"  {e.ticker:<8} ${e.price:>9,.2f} {e.scan_signal:<14} {e.scan_score:>5.0f} "
                f"{e.agent_action:>6} {e.agent_confidence:>4.0f} {e.agent_agreement:>5.0%}"
            )

    if rejected:
        print(f"\n  REJECTED ({len(rejected)}):")
        for e in rejected[:5]:
            print(f"    {e.ticker}: {e.reason}")
    print()


def print_exits(exits: list[SwingExit]) -> None:
    if not exits:
        print("오픈 포지션 없음")
        return

    print(f"\n{'=' * 70}")
    print(f"  Swing Trade Positions — {len(exits)} open")
    print(f"{'=' * 70}")
    print(f"  {'Ticker':<8} {'Entry':>10} {'Current':>10} {'Return':>8} {'Days':>5} {'Action':<12}")
    print(f"  {'-' * 55}")

    for e in exits:
        action = e.exit_reason.upper() if e.should_exit else "HOLD"
        color_prefix = "+" if e.return_pct > 0 else ""
        print(
            f"  {e.ticker:<8} ${e.entry_price:>9,.2f} ${e.current_price:>9,.2f} "
            f"{color_prefix}{e.return_pct:.1f}% {e.hold_days:>5} {action:<12}"
        )
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Nuri-Quant Swing Trade Rules")
    parser.add_argument("--check", action="store_true", help="보유 포지션 청산 체크")
    parser.add_argument("--market", choices=["us", "kr"], default="us")
    args = parser.parse_args()

    init_db()

    if args.check:
        exits = check_exits()
        print_exits(exits)
    else:
        entries = evaluate_entries(market=args.market)
        print_entries(entries)

        approved = [e for e in entries if e.approved]
        if approved:
            n = save_entries(entries)
            logger.info(f"진입 {n}건 저장")

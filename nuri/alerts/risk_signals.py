"""Mechanical risk signals → #brief (Tier 1a: stop-loss breach).

브리프가 지금까지 aggregate INFO summary 1건만 stage 해 "행동 가능한 신호가
안 보인다"는 통증(늦은 손절 = 처분효과, Shefrin & Statman 1985)의 첫 해소.

여기서 표면화하는 것은 **결정론적 룰 신호**(예측 아님): row PnL 이 계좌별
`config/rules.yaml` stop_loss threshold 를 이탈하면 SELL 로 stage. 예측 alpha
(consensus BUY/SELL) 는 §3.11 측정 진행 중이라 Tier 2 로 분리 — 여기 미포함.

Axis (#429): stop-loss breach 는 유일한 mechanical `alpha_action=FLAT` → 정당한
urgent SELL. 집중도/드리프트(REBALANCE) 는 alpha 축이 아니므로 여기 없음.

Privacy: Discord 는 사용자 private 채널이므로 ticker+PnL 노출 OK (DecisionCompiler
`_publish_brief` 선례와 동일). repo 로는 절대 안 감(mini gitignored DB). 테스트는
합성 티커(TST_*)만.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any, Literal, Optional

from nuri.core.db import query
from nuri.core.rules import get_account_strategy_name, get_stop_loss_for_account
from nuri.core.ticker_names import get_ticker_name, is_kr_ticker
from nuri.core.timezone import today_kst

logger = logging.getLogger(__name__)

Session = Literal["kr", "us"]


def scan_stop_breaches(
    session: Optional[Session] = None,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """보유 종목 중 손절선 이탈(row PnL < 계좌 threshold) 목록.

    Args:
        session: "kr" → `.KS` only, "us" → non-`.KS` only, None → 전체.
        db_path: 테스트 격리용.

    Returns:
        [{ticker, account, avg, current, pnl_pct, threshold}] — worst 우선 정렬.
        pension 계좌(장기 buy-and-hold, daily action 대상 아님)는 제외.
    """
    rows = query(
        """
        SELECT p.account, p.ticker, p.avg_price, p.quantity, pr.close AS current
        FROM portfolio p
        LEFT JOIN (
            SELECT ticker, close FROM prices
            WHERE (ticker, date) IN (SELECT ticker, MAX(date) FROM prices GROUP BY ticker)
        ) pr ON p.ticker = pr.ticker
        WHERE p.quantity > 0
        """,
        db_path=db_path,
    )

    breaches: list[dict[str, Any]] = []
    for r in rows:
        ticker = str(r["ticker"])
        # KR 판정은 `is_kr_ticker()` 경유 — `.KS` 만 보면 `.KQ`(KOSDAQ) 홀딩이
        # KR 세션 스캔에서 통째로 빠지고 US 세션에 섞인다(#764 split-brain 재발).
        if session == "kr" and not is_kr_ticker(ticker):
            continue
        if session == "us" and is_kr_ticker(ticker):
            continue
        if get_account_strategy_name(r["account"]) == "pension":
            continue

        avg = r["avg_price"]
        current = r["current"]
        # avg/current 0·None → 손절 계산 무의미. current==0 (상장폐지/거래정지/
        # 불량 price) 을 걸러야 (0-avg)/avg = -100% false SELL 방지 (risk_agent
        # 와 동일하게 truthiness 가드).
        if not avg or not current:
            continue

        pnl_pct = (current - avg) / avg * 100
        threshold = get_stop_loss_for_account(r["account"])
        if pnl_pct < threshold:
            qty = r["quantity"] or 0
            breaches.append(
                {
                    "ticker": ticker,
                    "account": r["account"],
                    "avg": float(avg),
                    "current": float(current),
                    "pnl_pct": pnl_pct,
                    "threshold": threshold,
                    # 평가손실 금액 — 같은 -20% 라도 100만원과 5천만원은 다른 결정이다.
                    # 통화는 티커 기준(KR=KRW / 그 외=USD), 렌더러가 기호를 붙인다.
                    "qty": float(qty),
                    "loss_amount": (float(current) - float(avg)) * float(qty),
                    **_breach_age(ticker, float(avg), threshold, db_path=db_path),
                }
            )

    breaches.sort(key=lambda b: b["pnl_pct"])  # 가장 깊은 손실 우선
    return breaches


def _breach_age(
    ticker: str,
    avg: float,
    threshold: float,
    db_path: Optional[Path] = None,
    lookback: int = 180,
) -> dict[str, Any]:
    """가장 최근 **연속** 이탈 구간의 길이·시작일·시작 시점 손익률.

    "며칠째인가"가 없으면 8일 연속 같은 줄이 8번 오고 사용자는 새 신호와 구별하지
    못한다(처분효과 방어가 알림 피로로 뒤집히는 지점). outbox 발송 이력이 아니라
    **가격 이력**으로 센다 — outbox 는 보존기간에 따라 지워지지만 가격은 남고,
    같은 입력이면 같은 답이 나온다.

    최신 bar 부터 과거로 훑다가 손절가 위로 올라온 첫 bar 에서 멈춘다(중간에
    회복했다가 재이탈했으면 재이탈 구간만 센다). 가격 이력이 없으면 빈 dict.
    """
    stop_level = avg * (1 + threshold / 100)
    rows = query(
        "SELECT date, close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT ?",
        (ticker, lookback),
        db_path=db_path,
    )
    first_date: Optional[str] = None
    first_pnl: Optional[float] = None
    days = 0
    for row in rows:
        close = row["close"]
        if not close or close >= stop_level:
            break
        days += 1
        first_date = str(row["date"])
        first_pnl = (close - avg) / avg * 100
    if not days:
        return {}
    return {"breach_days": days, "first_breach_date": first_date, "first_breach_pnl_pct": first_pnl}


def _build_breach_payload(breach: dict[str, Any], date: str) -> dict[str, Any]:
    """손절 이탈 1건 → #brief SELL payload (DecisionCompiler `_publish_brief` 형식).

    `summary` 가 렌더 계약이다(#571) — 의미를 아는 쪽은 producer 다. 3줄 카드:

        1줄 종목·행동·**경과일**   2줄 현재가·평단·손실률·**평가손실 금액**
        3줄 룰 임계·이탈폭·최초 이탈일 대비 추가 하락

    이전 payload 는 `price_levels{entry=평단, stop}` 만 실어 보냈다. 이미 손절선을
    40% 아래로 뚫은 포지션에 "entry" 를 보여주는 건 방향이 거꾸로다 — 지금 필요한
    건 진입가가 아니라 **현재 얼마이고 얼마를 잃고 있는지**다. 그래서 price_levels
    대신 구조화 필드로 싣는다.

    어조: 매도를 지시하지 않는다. 시스템은 권고만 하고 집행은 사용자다(§7.1) —
    digest footer 가 이미 "manual execute only" 를 달고 있어 카드마다 반복하지 않는다.
    """
    # outbox 는 이 모듈에서 항상 함수 안에서 import 한다(`stage_brief` 와 동일 패턴).
    from nuri.agents.discord.outbox import format_money

    threshold = breach["threshold"]
    ticker = breach["ticker"]
    name = get_ticker_name(ticker)
    label = f"{ticker} {name}" if name else str(ticker)

    pnl = breach["pnl_pct"]
    days = breach.get("breach_days")
    age = f"{days}일째" if days else "오늘 이탈"

    head = f"🔴 {label} · 손절선 이탈 {age}"
    money = (
        f"　현재 {format_money(breach['current'], ticker)} / 평단 {format_money(breach['avg'], ticker)} ({pnl:+.1f}%)"
    )
    if breach.get("loss_amount"):
        money += f" · 평가손실 {format_money(breach['loss_amount'], ticker)}"

    rule = f"　룰 {threshold}% 손절선 · 이탈폭 {pnl - threshold:+.1f}%p"
    first_pnl = breach.get("first_breach_pnl_pct")
    if breach.get("first_breach_date") and first_pnl is not None:
        rule += f" · 최초 이탈 {breach['first_breach_date'][5:]} 이후 {pnl - first_pnl:+.1f}%p"

    return {
        "kind": "SELL",
        "ticker": ticker,
        "summary": "\n".join([head, money, rule]),
        # note → 같은 티커가 여러 계좌에 있을 때 어느 계좌인지 구분 (계좌별 avg 다름).
        "note": breach["account"],
        "reason": f"손절선 돌파 ({pnl:+.1f}% < {threshold}%)",
        "date": date,
        "current": breach["current"],
        "avg": breach["avg"],
        "loss_amount": breach.get("loss_amount"),
        "breach_days": days,
    }


def stage_stop_breach_briefs(
    session: Optional[Session] = None,
    date: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """손절선 이탈 종목을 #brief outbox 에 SELL 로 stage. staged 건수 반환.

    dedupe_key=`stop-breach:{ticker}:{account}:{date}` — (ticker, account) × 하루
    1건(같은 이탈이 이틀 지속되면 매일 재알림: 처분효과 방어 = 자를 때까지 상기).
    """
    from nuri.agents.discord.outbox import stage_brief

    d = date or today_kst()
    breaches = scan_stop_breaches(session, db_path=db_path)
    staged = 0
    for b in breaches:
        payload = _build_breach_payload(b, d)
        # dedupe_key 에 account 포함 — 같은 티커가 여러 계좌에서 이탈해도 각각
        # 별개 brief (계좌별 avg 다름). non-None 만 카운트(dedupe skip → None).
        outbox_id = stage_brief(
            payload=payload,
            dedupe_key=f"stop-breach:{b['ticker']}:{b['account']}:{d}",
            priority="high",
            actor_name="risk-signals",
            db_path=db_path,
        )
        if outbox_id is not None:
            staged += 1
    if staged:
        logger.info("stop-breach briefs staged: %d (session=%s)", staged, session or "all")
    return staged


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Stop-loss breach → #brief (Tier 1a)")
    parser.add_argument("--session", choices=("kr", "us"), default=None, help="세션 필터 (기본: 전체)")
    parser.add_argument("--dry-run", action="store_true", help="stage 없이 이탈 목록만 출력")
    args = parser.parse_args(argv)

    breaches = scan_stop_breaches(args.session)
    if not breaches:
        print("stop-loss breach 없음")
        return 0
    for b in breaches:
        print(
            f"  {b['ticker']} [{b['account']}] {b['pnl_pct']:+.1f}% < {b['threshold']}% (avg {b['avg']:.2f} → {b['current']:.2f})"
        )
    if args.dry_run:
        print(f"[dry-run] {len(breaches)}건 — stage 안 함")
        return 0
    staged = stage_stop_breach_briefs(args.session)
    print(f"staged {staged}건 → #brief")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

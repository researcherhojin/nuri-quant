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
        if session == "kr" and not ticker.endswith(".KS"):
            continue
        if session == "us" and ticker.endswith(".KS"):
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
            breaches.append(
                {
                    "ticker": ticker,
                    "account": r["account"],
                    "avg": float(avg),
                    "current": float(current),
                    "pnl_pct": pnl_pct,
                    "threshold": threshold,
                }
            )

    breaches.sort(key=lambda b: b["pnl_pct"])  # 가장 깊은 손실 우선
    return breaches


def _build_breach_payload(breach: dict[str, Any], date: str) -> dict[str, Any]:
    """손절 이탈 1건 → #brief SELL payload (DecisionCompiler `_publish_brief` 형식).

    price_levels: entry=평단, stop=이탈한 손절가(평단×(1+threshold%)). TP 는
    cut 신호엔 무의미하므로 생략(렌더러가 present 키만 표시).
    """
    avg = breach["avg"]
    threshold = breach["threshold"]
    stop_level = avg * (1 + threshold / 100)
    return {
        "kind": "SELL",
        "ticker": breach["ticker"],
        # note → 렌더러가 표시. 같은 티커가 여러 계좌에 있을 때 어느 계좌인지 구분
        # (계좌별 avg 가 달라 entry/stop 도 다름).
        "note": breach["account"],
        "reason": f"손절선 돌파 ({breach['pnl_pct']:+.1f}% < {threshold}%)",
        "date": date,
        "price_levels": {"entry": round(avg, 2), "stop": round(stop_level, 2)},
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

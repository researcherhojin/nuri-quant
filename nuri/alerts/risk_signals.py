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
from datetime import date as dt_date
from pathlib import Path
from typing import Any, Literal, Optional

from nuri.core.db import query
from nuri.core.rules import (
    BRIEF_BENCHMARK,
    BRIEF_EARNINGS_WINDOW_DAYS,
    BRIEF_SEVERITY_GAP_PCT,
    get_account_strategy_name,
    get_stop_loss_for_account,
)
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
        SELECT p.account, p.ticker, p.avg_price, p.quantity, p.currency, pr.close AS current
        FROM portfolio p
        LEFT JOIN (
            SELECT ticker, close FROM prices
            WHERE (ticker, date) IN (SELECT ticker, MAX(date) FROM prices GROUP BY ticker)
        ) pr ON p.ticker = pr.ticker
        WHERE p.quantity > 0
        """,
        db_path=db_path,
    )
    account_totals = _single_currency_account_totals(rows)

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
                    # 계좌 내 비중 — 같은 -20% 라도 8% 포지션과 1% 포지션은 다른 결정.
                    # 통화가 섞인 계좌는 환율 없이 합산하면 틀린 수가 나오므로 None
                    # (틀린 숫자보다 없는 게 낫다).
                    "weight_pct": (
                        float(current) * float(qty) / account_totals[r["account"]] * 100
                        if account_totals.get(r["account"])
                        else None
                    ),
                    **_price_context(ticker, float(avg), threshold, db_path=db_path),
                }
            )
            breaches[-1].update(_market_context(ticker, breaches[-1].get("ret_20d"), today_kst(), db_path=db_path))

    breaches.sort(key=lambda b: b["pnl_pct"])  # 가장 깊은 손실 우선
    return breaches


def _single_currency_account_totals(rows: list[dict[str, Any]]) -> dict[str, float]:
    """계좌 → 평가금액 합. **단일 통화 계좌만** 반환한다.

    비중은 같은 통화끼리 더해야 의미가 있다. 한 계좌에 KRW 종목과 USD 종목이
    섞여 있으면 환율 없이 합산한 수는 틀린다 — 그런 계좌는 아예 빼서 카드가
    비중을 생략하게 한다(틀린 숫자를 보여주는 것보다 낫다). KR 판정은 `.KS`
    뿐 아니라 `.KQ` 도 포함해야 한다(#764).
    """
    by_account: dict[str, float] = {}
    currencies: dict[str, set[str]] = {}
    for r in rows:
        acct, close, qty = r["account"], r["current"], r["quantity"]
        cur = "KRW" if (r.get("currency") == "KRW" or is_kr_ticker(str(r["ticker"]))) else "USD"
        currencies.setdefault(acct, set()).add(cur)
        if close and qty:
            by_account[acct] = by_account.get(acct, 0.0) + float(close) * float(qty)
    return {a: v for a, v in by_account.items() if v > 0 and len(currencies.get(a, ())) == 1}


def _price_context(
    ticker: str,
    avg: float,
    threshold: float,
    db_path: Optional[Path] = None,
    lookback: int = 260,
) -> dict[str, Any]:
    """가격 이력 1회 조회로 이탈 경과 + 추세 + 52주고 낙폭을 함께 계산.

    **이탈 경과**: 최신 bar 부터 과거로 훑다가 손절가 위로 올라온 첫 bar 에서
    멈춘다(중간에 회복 후 재이탈이면 재이탈 구간만). "며칠째인가"가 없으면 같은
    줄이 8일 연속 와도 새 신호와 구별되지 않는다 — 처분효과 방어가 알림 피로로
    뒤집히는 지점이다. outbox 발송 이력이 아니라 가격으로 세는 이유는 outbox 는
    보존기간에 따라 지워지지만 가격은 남고, 같은 입력이면 같은 답이 나오기 때문.

    **추세**(5일·20일 수익률)와 **52주고 대비 낙폭**: 같은 -20% 라도 반등 중인
    포지션과 계속 흘러내리는 포지션은 다른 결정이다. lookback 260 = 약 52주.

    가격 이력이 없으면 빈 dict (호출자가 omit).
    """
    stop_level = avg * (1 + threshold / 100)
    rows = query(
        "SELECT date, close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT ?",
        (ticker, lookback),
        db_path=db_path,
    )
    closes = [float(r["close"]) for r in rows if r["close"]]
    if not closes:
        return {}

    out: dict[str, Any] = {}
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
    if days:
        out.update({"breach_days": days, "first_breach_date": first_date, "first_breach_pnl_pct": first_pnl})

    latest = closes[0]
    dates = [str(r["date"]) for r in rows if r["close"]]
    for label, span in (("ret_5d", 5), ("ret_20d", 20)):
        r = _span_return(closes, dates, span)
        if r is not None:
            out[label] = r
    high = max(closes)
    if high:
        out["drawdown_52w"] = (latest - high) / high * 100
    return out


def _span_return(closes: list[float], dates: list[str], bars: int) -> Optional[float]:
    """N **거래일** 수익률 — 봉 간격이 실제로 일별일 때만 계산한다.

    `prices` 는 티커마다 밀도가 다르다. 프로덕션은 21행이 29일을 덮어 정상이지만
    dev replica 는 같은 21행이 41~60일을 덮고, 티커마다 그 폭이 다르다. 그 상태로
    "20봉 전" 을 "20일 전" 이라 부르면 종목과 시장이 서로 **다른 기간**을 비교하게
    되고, 실제로 KODEX 200 이 20일에 +38% 오른 것처럼 보이는 값이 나왔다.

    그래서 봉 수가 아니라 그 봉이 실제로 며칠을 덮는지 보고, 일별 간격에서 나올 수
    있는 범위(거래일 N → 달력 최대 2N일)를 벗어나면 **숫자를 만들지 않는다**.
    틀린 기간의 수익률은 없는 것만 못하다.
    """
    if len(closes) <= bars or not closes[bars]:
        return None
    try:
        span_days = (dt_date.fromisoformat(dates[0]) - dt_date.fromisoformat(dates[bars])).days
    except (ValueError, IndexError):  # pragma: no cover — date 컬럼은 항상 ISO
        return None
    if span_days > bars * 2:
        return None
    return (closes[0] - closes[bars]) / closes[bars] * 100


def _market_context(
    ticker: str,
    ret_20d: Optional[float],
    date: str,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """시장 대비 상대 성과 + 임박한 실적 — 손절 판단을 가르는 두 가지.

    **시장 대비**: 같은 -25% 라도 시장이 함께 빠진 것과 종목 혼자 빠진 것은 다른
    결정이다. 벤치마크는 새로 정하지 않고 이미 고정된 것을 쓴다 — US 는 §3.11 의
    SPY, KR 은 postmarket 이 쓰는 KODEX 200(`config/rules.yaml brief.benchmark`).

    **실적 D-day**: 창(기본 14일) 안의 실적만. 그 밖의 실적은 지금 결정과 무관하다.
    보유가 ETF 중심이면 대부분 비어 있다(ETF 는 실적 이벤트가 없다) — 그래서 이건
    상대 성과의 대체가 아니라 개별주에만 붙는 보조 정보다.

    계산 불가한 항목은 키를 만들지 않는다(카드가 알아서 생략).
    """
    out: dict[str, Any] = {}

    bench = BRIEF_BENCHMARK.get("kr" if is_kr_ticker(ticker) else "us")
    if bench and ret_20d is not None:
        rows = query(
            "SELECT date, close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 21",
            (bench,),
            db_path=db_path,
        )
        closes = [float(r["close"]) for r in rows if r["close"]]
        dates = [str(r["date"]) for r in rows if r["close"]]
        bench_ret = _span_return(closes, dates, 20)
        # 벤치마크 최신일이 종목과 크게 어긋나면 서로 다른 끝점을 비교하게 된다.
        # (예: 프로덕션에 `069500.KS` 는 아예 없고, dev 는 두 달 stale 이다.)
        aligned = bool(dates) and abs((dt_date.fromisoformat(dates[0]) - dt_date.fromisoformat(date)).days) <= 5
        if bench_ret is not None and aligned:
            out.update({"benchmark": bench, "benchmark_ret_20d": bench_ret, "excess_20d": ret_20d - bench_ret})

    rows = query(
        "SELECT date FROM events WHERE ticker = ? AND event_type = 'earnings' AND date >= ? ORDER BY date LIMIT 1",
        (ticker, date),
        db_path=db_path,
    )
    if rows:
        days = (dt_date.fromisoformat(str(rows[0]["date"])) - dt_date.fromisoformat(date)).days
        if 0 <= days <= BRIEF_EARNINGS_WINDOW_DAYS:
            out["earnings_in_days"] = days
    return out


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
    gap = pnl - threshold
    first_pnl = breach.get("first_breach_pnl_pct")
    # 이탈 후 더 내려갔나 — 같은 이탈폭이라도 흘러내리는 쪽이 급하다.
    worsening = first_pnl is not None and pnl < first_pnl
    severe = gap <= BRIEF_SEVERITY_GAP_PCT or worsening

    # 계좌를 카드에 남긴다 — 같은 티커를 여러 계좌에 보유하면(계좌별 평단이 달라
    # dedupe_key 도 계좌를 포함한다) "어느 계좌에서 파는가"가 곧 실행 정보다.
    head = f"{'🔴' if severe else '🟠'} {label} · 손절선 이탈 {age} · {breach['account']}"
    if breach.get("weight_pct") is not None:
        head += f" · 계좌비중 {breach['weight_pct']:.1f}%"

    money = (
        f"　현재 {format_money(breach['current'], ticker)} / 평단 {format_money(breach['avg'], ticker)} ({pnl:+.1f}%)"
    )
    if breach.get("loss_amount"):
        money += f" · 평가손실 {format_money(breach['loss_amount'], ticker)}"

    # 추세 — "지금 어느 방향인가". 반등 중인 -8% 와 흘러내리는 -48% 를 가른다.
    trend_bits = []
    for label_txt, key in (("5일", "ret_5d"), ("20일", "ret_20d")):
        if breach.get(key) is not None:
            trend_bits.append(f"{label_txt} {breach[key]:+.1f}%")
    if breach.get("drawdown_52w") is not None:
        trend_bits.append(f"52주고 대비 {breach['drawdown_52w']:.0f}%")
    if breach.get("first_breach_date") and first_pnl is not None:
        trend_bits.append(
            f"최초 이탈 {breach['first_breach_date'][5:]} 이후 {pnl - first_pnl:+.1f}%p"
            f"{' (회복 중)' if not worsening else ''}"
        )
    trend = "　추세 " + " · ".join(trend_bits) if trend_bits else None

    # 시장 대비 — "시장이 빠진 건가, 이 종목이 빠진 건가". 손절 판단이 여기서 갈린다.
    # 실적 D-day 는 개별주에만 붙는다(ETF 는 실적 이벤트가 없어 대부분 비어 있다).
    market_bits = []
    if breach.get("benchmark") and breach.get("excess_20d") is not None:
        market_bits.append(
            f"20일 시장({breach['benchmark']}) {breach['benchmark_ret_20d']:+.1f}%"
            f" · 종목 {breach['ret_20d']:+.1f}% → 종목 요인 {breach['excess_20d']:+.1f}%p"
        )
    if breach.get("earnings_in_days") is not None:
        market_bits.append(f"실적 D-{breach['earnings_in_days']}")
    market = "　" + " · ".join(market_bits) if market_bits else None

    # 룰 귀결 — 지시가 아니라 룰이 이 상태를 뭐라 부르는지. 집행은 사용자다(§7.1).
    # 이탈폭이 크지 않은데 "얕다"고 단정하면 틀린다(폭은 큰데 반등 중인 경우가 있다).
    # 방향은 추세 줄이 이미 말하므로, 여기서는 악화 중일 때만 덧붙인다.
    rule = f"　룰 {threshold}% 손절 → 청산 구간 · 이탈폭 {gap:+.1f}%p"
    if worsening:
        rule += " (이탈 후에도 계속 하락)"

    return {
        "kind": "SELL",
        "ticker": ticker,
        "summary": "\n".join([x for x in (head, money, trend, market, rule) if x]),
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

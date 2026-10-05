"""가격 타겟 + 리밸런스 어드바이저 API. (인증·remediation 라우트는 #1619 로 제거.)"""

from fastapi import APIRouter

router = APIRouter(tags=["targets"])


@router.get("/targets")
def get_portfolio_targets():
    """전 종목 매수가/손절가/익절가 + 익절/트레일링 시그널."""
    from nuri.trading.recommend.price_targets import (
        calculate_portfolio_targets,
        check_leader_trail_signals,
        check_take_profit_signals,
        check_trailing_stop_signals,
    )

    targets = calculate_portfolio_targets()

    # 익절/트레일링/리더-트레일 도달 종목 태깅.
    # 키는 **(ticker, account)** 다 — 티커만으로 잡으면 같은 종목을 두 계좌에
    # 보유할 때 dict 조립에서 마지막 계좌 것만 남고(앞 계좌 신호 소실), 남은 하나가
    # 두 행 모두에 붙는다. 계좌마다 평단이 다르면 손절/익절선도 다르므로 한쪽은
    # 반드시 틀린 신호를 받는다 (#974).
    def _key(row: dict) -> tuple:
        return (row.get("ticker"), row.get("account"))

    try:
        tp_signals = {_key(s): s for s in check_take_profit_signals()}
    except Exception:
        tp_signals = {}
    try:
        ts_signals = {_key(s): s for s in check_trailing_stop_signals()}
    except Exception:
        ts_signals = {}
    try:
        lt_signals = {_key(s): s for s in check_leader_trail_signals()}
    except Exception:
        lt_signals = {}
    for t in targets:
        tp = tp_signals.get(_key(t))
        ts = ts_signals.get(_key(t))
        lt = lt_signals.get(_key(t))
        t["take_profit_triggered"] = tp["level"] if tp else None
        t["take_profit_sell_pct"] = tp["sell_pct"] if tp else None
        t["trailing_stop_triggered"] = ts is not None
        t["leader_trail_triggered"] = lt is not None
        t["leader_trail_ma"] = lt["ma"] if lt else None

    return {"targets": targets, "count": len(targets)}


@router.get("/targets/{ticker}")
def get_ticker_targets(ticker: str):
    """단일 종목 가격 타겟."""
    from nuri.trading.recommend.price_targets import calculate_targets

    target = calculate_targets(ticker.upper())
    return target


@router.get("/rebalance-advisor")
def get_rebalance_advisor():
    """규칙 위반 감지 + 매도 수량 + 회수 금액."""
    from nuri.analysis.rebalance_advisor import generate_advisor_report

    return generate_advisor_report()

"""가격 타겟 + 리밸런스 어드바이저 + SIEGE 인증 + Remediation API."""

import threading

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


_certify_cache: dict = {"data": None, "ts": 0}
# single-flight — TTL 만료 시 동시 요청이 전부 certify() 를 다시 도는 걸 막는다 (#1119)
_certify_lock = threading.Lock()


@router.get("/certify")
def get_certification():
    """SIEGE 인증 상태 (5분 캐시).

    v2 (#248): 11 base gate check × per-asset-class expansion 으로 total_conditions 가변.
    """
    import time
    from dataclasses import asdict

    now = time.time()
    if _certify_cache["data"] and now - _certify_cache["ts"] < 300:
        return _certify_cache["data"]

    from nuri.trading.engine.certification import certify

    with _certify_lock:
        # double-check — 락을 기다리는 동안 다른 요청이 채웠을 수 있다
        now = time.time()
        if _certify_cache["data"] and now - _certify_cache["ts"] < 300:
            return _certify_cache["data"]

        # API path — persist 실패가 HTTP 500 으로 전파되면 안 됨. swallow=True (E4-0a
        # codex R1 P1). Engine/CLI/remediation 은 default loud 유지.
        cert = certify(caller="api:targets", swallow_persist_errors=True)
        result = {
            "certified": cert.certified,
            "score": cert.score,
            "passed": cert.passed,
            "failed": cert.failed,
            "warnings": cert.warnings,
            "total": cert.total_conditions,
            "conditions": [asdict(c) for c in cert.conditions],
            "timestamp": cert.timestamp,
        }
        _certify_cache["data"] = result
        _certify_cache["ts"] = now
        return result


@router.get("/remediate")
def get_remediation():
    """SIEGE remediation 계획 — REJECTED gate → 매도 액션 매핑."""
    from dataclasses import asdict

    from nuri.trading.engine.remediation import generate_remediation

    plan = generate_remediation()
    return {
        "certified": plan.certified,
        "score": plan.score,
        "failed_gates": plan.failed_gates,
        "warning_gates": plan.warning_gates,
        "actions": [asdict(a) for a in plan.actions],
        "unresolvable": plan.unresolvable,
        "post_remediation_score": plan.post_remediation_score,
        "post_remediation_pass": plan.post_remediation_pass,
    }

"""가격 타겟 + 리밸런스 어드바이저 + SIEGE 인증 + Remediation API."""

from fastapi import APIRouter

router = APIRouter(tags=["targets"])


@router.get("/targets")
def get_portfolio_targets():
    """전 종목 매수가/손절가/익절가 + 익절/트레일링 시그널."""
    from nuri.trading.recommend.price_targets import (
        calculate_portfolio_targets,
        check_take_profit_signals,
        check_trailing_stop_signals,
    )

    targets = calculate_portfolio_targets()

    # 익절/트레일링 도달 종목 태깅
    try:
        tp_signals = {s["ticker"]: s for s in check_take_profit_signals()}
    except Exception:
        tp_signals = {}
    try:
        ts_signals = {s["ticker"]: s for s in check_trailing_stop_signals()}
    except Exception:
        ts_signals = {}
    for t in targets:
        tp = tp_signals.get(t["ticker"])
        ts = ts_signals.get(t["ticker"])
        t["take_profit_triggered"] = tp["level"] if tp else None
        t["take_profit_sell_pct"] = tp["sell_pct"] if tp else None
        t["trailing_stop_triggered"] = ts is not None

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

    cert = certify(caller="api:targets")
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

"""가격 타겟 + 리밸런스 어드바이저 + SIEGE 인증 API."""
from fastapi import APIRouter

router = APIRouter(tags=["targets"])


@router.get("/targets")
def get_portfolio_targets():
    """전 종목 매수가/손절가/익절가 계산."""
    from nuri.trading.recommend.price_targets import calculate_portfolio_targets
    targets = calculate_portfolio_targets()
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


@router.get("/certify")
def get_certification():
    """SIEGE 10-condition 인증 상태."""
    from dataclasses import asdict
    from nuri.trading.engine.certification import certify
    cert = certify()
    return {
        "certified": cert.certified,
        "score": cert.score,
        "passed": cert.passed,
        "failed": cert.failed,
        "warnings": cert.warnings,
        "total": cert.total_conditions,
        "conditions": [asdict(c) for c in cert.conditions],
        "timestamp": cert.timestamp,
    }

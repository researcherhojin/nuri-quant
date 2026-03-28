"""가격 타겟 + 리밸런스 어드바이저 API."""
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

"""종목 상세 API — 모든 데이터를 한 번에."""
from dataclasses import asdict
from fastapi import APIRouter

from nuri.core.db import query, query_df

router = APIRouter(tags=["ticker"])


@router.get("/ticker/{symbol}")
def get_ticker_detail(symbol: str):
    """단일 종목의 모든 분석 데이터."""
    ticker = symbol.upper()
    result = {"ticker": ticker}

    # 1. 가격
    price_row = query(
        "SELECT close, date FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1",
        (ticker,),
    )
    result["price"] = {
        "close": price_row[0]["close"] if price_row else None,
        "date": price_row[0]["date"] if price_row else None,
    }

    # 2. 펀더멘탈
    fund = query("SELECT * FROM fundamentals WHERE ticker=? ORDER BY date DESC LIMIT 1", (ticker,))
    result["fundamentals"] = dict(fund[0]) if fund else None

    # 3. 6 에이전트 합의
    try:
        from nuri.trading.agents.consensus import analyze_ticker
        consensus = analyze_ticker(ticker)
        result["consensus"] = {
            "final_action": consensus.final_action,
            "final_confidence": consensus.final_confidence,
            "agreement_rate": consensus.agreement_rate,
            "verdicts": [asdict(v) for v in consensus.verdicts],
            "dissent": consensus.dissent,
        }
    except Exception as e:
        result["consensus"] = {"error": str(e)}

    # 4. Wall Street — 애널리스트 등급 (최근 10건)
    ratings = query(
        "SELECT date, firm, to_grade, action, target_price FROM analyst_ratings "
        "WHERE ticker=? ORDER BY date DESC LIMIT 10",
        (ticker,),
    )
    result["analyst_ratings"] = [dict(r) for r in ratings]

    # 5. Earnings Surprise
    earnings = query(
        "SELECT quarter, eps_actual, eps_estimate, surprise_pct FROM earnings_surprises "
        "WHERE ticker=? ORDER BY quarter DESC LIMIT 8",
        (ticker,),
    )
    result["earnings"] = [dict(e) for e in earnings]

    # 6. Insider 매매 (최근 10건)
    insiders = query(
        "SELECT date, insider_name, position, transaction_type, shares, value "
        "FROM insider_trades WHERE ticker=? ORDER BY date DESC LIMIT 10",
        (ticker,),
    )
    result["insider_trades"] = [dict(i) for i in insiders]

    # 7. 애널리스트 컨센서스 (기존 estimates)
    est = query("SELECT * FROM estimates WHERE ticker=? ORDER BY date DESC LIMIT 1", (ticker,))
    result["estimates"] = dict(est[0]) if est else None

    # 8. 슈퍼투자자 보유
    si = query(
        "SELECT investor, portfolio_pct, filing_date FROM superinvestors "
        "WHERE ticker=? ORDER BY portfolio_pct DESC LIMIT 5",
        (ticker,),
    )
    result["superinvestors"] = [dict(s) for s in si]

    # 9. 최근 시그널
    try:
        from nuri.trading.recommend.candidates import screen_candidates
        candidates = screen_candidates(lookback_days=10)
        ticker_signals = [asdict(c) for c in candidates if c.ticker == ticker]
        result["signals"] = ticker_signals
    except Exception:
        result["signals"] = []

    return result

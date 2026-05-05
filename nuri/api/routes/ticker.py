"""종목 상세 API — 모든 데이터를 한 번에."""

from dataclasses import asdict

from fastapi import APIRouter, Query

from nuri.core.db import query

router = APIRouter(tags=["ticker"])


@router.get("/tickers/search")
def search_tickers(q: str = Query(..., min_length=1, max_length=20)):
    """종목 검색 — ticker code 또는 한국 종목명 부분 매칭. universe + DB 가격 기반."""
    from pathlib import Path

    import yaml

    from nuri.core.ticker_names import get_ticker_name

    term = q.strip().upper()
    results: list[dict] = []
    seen: set[str] = set()

    # 1) universe.yaml에서 ticker code 매칭
    universe_path = Path(__file__).resolve().parents[3] / "config" / "universe.yaml"
    all_tickers: list[str] = []
    if universe_path.exists():
        with open(universe_path) as f:
            uni = yaml.safe_load(f) or {}
        for group in uni.values():
            if isinstance(group, dict) and "tickers" in group:
                all_tickers.extend(group["tickers"])

    # ticker code 매칭 (NVDA, 005930 등)
    for t in all_tickers:
        if term in t.upper() and t not in seen:
            seen.add(t)
            price_row = query("SELECT close, date FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,))
            results.append(
                {
                    "ticker": t,
                    "name": get_ticker_name(t),
                    "price": price_row[0]["close"] if price_row else None,
                    "date": price_row[0]["date"] if price_row else None,
                }
            )
        if len(results) >= 8:
            break

    # 2) 한글 이름 매칭 (KR 종목 — "삼성" → 005930.KS)
    if len(results) < 8:
        term_lower = q.strip().lower()
        for t in all_tickers:
            if t in seen:
                continue
            if t.endswith(".KS") or t.endswith(".KQ"):
                name = get_ticker_name(t)
                if name and term_lower in name.lower():
                    seen.add(t)
                    price_row = query("SELECT close, date FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,))
                    results.append(
                        {
                            "ticker": t,
                            "name": name,
                            "price": price_row[0]["close"] if price_row else None,
                            "date": price_row[0]["date"] if price_row else None,
                        }
                    )
            if len(results) >= 8:
                break

    return {"results": results, "count": len(results)}


@router.get("/tickers/market-context")
def get_market_context():
    """시장 현황 — VIX, Fear&Greed, 매크로 점수를 독립적으로 조회. 레짐 분류 실패해도 작동."""
    vix_row = query("SELECT value, date FROM macro WHERE indicator='vix' ORDER BY date DESC LIMIT 1")
    fg_row = query("SELECT value, date FROM macro WHERE indicator='fear_greed' ORDER BY date DESC LIMIT 1")

    # Macro score
    try:
        from nuri.quant.regime.macro_score import compute_macro_score

        macro = compute_macro_score()
        macro_score = macro.get("total_score") if isinstance(macro, dict) else None
    except Exception:
        macro_score = None

    # Regime (best effort — may fail if SPY stale)
    trend = None
    try:
        from nuri.quant.regime.classifier import classify_regime

        regime = classify_regime()
        if regime:
            trend = regime.trend
    except Exception:
        pass

    return {
        "trend": trend,
        "vix": round(vix_row[0]["value"], 1) if vix_row else None,
        "vix_date": vix_row[0]["date"] if vix_row else None,
        "fear_greed": round(fg_row[0]["value"], 1) if fg_row else None,
        "fg_date": fg_row[0]["date"] if fg_row else None,
        "macro_score": round(macro_score, 1) if macro_score else None,
    }


@router.get("/tickers/latest-prices")
def get_latest_prices(tickers: str = Query(..., description="Comma-separated ticker list")):
    """여러 종목의 최신 가격을 한 번에 조회. quicklink 카드용 batch endpoint."""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if len(ticker_list) > 20:
        ticker_list = ticker_list[:20]

    result: dict[str, dict] = {}
    for t in ticker_list:
        rows = query(
            "SELECT close, date FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 2",
            (t,),
        )
        if rows:
            latest = rows[0]["close"]
            prev = rows[1]["close"] if len(rows) > 1 else None
            result[t] = {"price": latest, "prev": prev, "date": rows[0]["date"]}
        else:
            result[t] = {"price": None, "prev": None, "date": None}

    return {"prices": result}


@router.get("/ticker/{symbol}")
def get_ticker_detail(symbol: str):
    """단일 종목의 모든 분석 데이터."""
    from nuri.core.ticker_names import get_ticker_name

    ticker = symbol.upper()
    result = {"ticker": ticker, "name": get_ticker_name(ticker)}

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

    # 3. 10 에이전트 합의
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


@router.get("/ticker/{symbol}/prices")
def get_ticker_prices(symbol: str, days: int = Query(180, ge=30, le=1825)):
    """종목 가격 히스토리 (차트용)."""
    ticker = symbol.upper()
    rows = query(
        "SELECT date, open, high, low, close, volume FROM prices WHERE ticker=? ORDER BY date DESC LIMIT ?",
        (ticker, days),
    )
    # 오래된 순으로 정렬
    prices = [dict(r) for r in reversed(rows)]
    return {"ticker": ticker, "prices": prices, "count": len(prices)}

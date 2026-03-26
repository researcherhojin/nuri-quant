"""스윙 트레이드 API."""
from dataclasses import asdict
from fastapi import APIRouter, Query

router = APIRouter(tags=["swing"])


@router.get("/scan")
def get_scan(market: str = Query("us", pattern="^(us|kr)$"), top: int = Query(20, ge=1, le=50)):
    """시장 스캔."""
    from nuri.trading.swing.scanner import scan_market
    results = scan_market(market=market, top_n=top)
    return {"results": [asdict(r) for r in results], "count": len(results)}


@router.get("/swing/entries")
def get_swing_entries(market: str = Query("us", pattern="^(us|kr)$")):
    """스윙 진입 후보 (스캔 + 에이전트 합의)."""
    import json
    from nuri.trading.swing.rules import evaluate_entries
    entries = evaluate_entries(market=market)
    # numpy 타입 → Python 네이티브 변환
    raw = [asdict(e) for e in entries]
    cleaned = json.loads(json.dumps(raw, default=lambda x: x.item() if hasattr(x, 'item') else bool(x) if isinstance(x, type(True)) else str(x)))
    return {
        "entries": cleaned,
        "approved": len([e for e in entries if e.approved]),
        "rejected": len([e for e in entries if not e.approved]),
    }


@router.get("/swing/positions")
def get_swing_positions():
    """오픈 포지션 청산 체크."""
    from nuri.trading.swing.rules import check_exits
    exits = check_exits()
    return {"positions": [asdict(e) for e in exits], "count": len(exits)}


@router.get("/backtest")
def get_backtest():
    """L/S strategy backtest results."""
    from nuri.trading.strategy.backtest import classify_historical_regimes, run_backtest, analyze_per_regime, analyze_entry_timing, stress_test, monte_carlo_test
    regimes = classify_historical_regimes()
    if regimes.empty:
        return {"error": "SPY data insufficient"}
    result = run_backtest(regimes)
    perfs = analyze_per_regime(regimes)
    timing = analyze_entry_timing(regimes)
    stress = stress_test(regimes)
    import json
    from dataclasses import asdict
    # numpy 타입 → Python 네이티브 변환
    def _clean(obj):
        return json.loads(json.dumps(obj, default=lambda x: x.item() if hasattr(x, 'item') else (bool(x) if isinstance(x, (type(True),)) else str(x))))
    return _clean({
        "result": asdict(result),
        "regimes": [asdict(p) for p in perfs],
        "timing": asdict(timing) if timing else None,
        "stress": stress,
    })


@router.get("/strategy/status")
def get_strategy_status():
    """Current strategy + positions."""
    from nuri.trading.strategy.longshort import generate_strategy, REGIME_ALLOCATION
    from nuri.trading.strategy.position import get_positions_summary
    from nuri.trading.strategy.monitor import daily_pnl_summary, detect_regime_transition
    from nuri.analysis.regime.classifier import classify_regime
    from dataclasses import asdict

    regime = classify_regime()
    actions = generate_strategy()
    positions = get_positions_summary()
    pnl = daily_pnl_summary()

    regime_name = regime.regime if regime else "unknown"
    alloc = REGIME_ALLOCATION.get(regime_name, {})

    return {
        "regime": asdict(regime) if regime else None,
        "allocation": alloc,
        "actions": [asdict(a) for a in actions],
        "positions": positions,
        "pnl": pnl,
    }

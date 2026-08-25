"""스윙 트레이드 API."""

import threading
from dataclasses import asdict
from time import monotonic

from fastapi import APIRouter, Depends, Query

from nuri.api.limits import heavy_slot

router = APIRouter(tags=["swing"])

_BACKTEST_CACHE_TTL_SECONDS = 300
_interactive_backtest_cache: dict[tuple[int, str, int, int], tuple[float, dict]] = {}
# single-flight — TTL 만료 시 동시 요청이 같은 백테스트를 중복 수행하는 걸 막는다
# (#1119). 키가 달라도 한 락으로 직렬화한다 — 이 경로는 무거워서 병렬 실행 자체가
# 스레드풀을 갉아먹는 쪽이 더 비싸다.
_backtest_lock = threading.Lock()


# `/scan` 은 **매 요청** scan_market() → yf.download(85 tickers, 60d) 라이브 왕복을
# 물었다 (#1119) — read 핸들러 안의 서드파티 네트워크 호출. 이 파일의 backtest 와
# 같은 TTL + single-flight 를 붙인다. 구조적 해법(scanner 가 `prices` 테이블을 읽게)
# 은 스캐너 시맨틱 변경이라 별건.
_SCAN_CACHE_TTL_SECONDS = 300
_scan_cache: dict[tuple[str, int], tuple[float, dict]] = {}
_scan_lock = threading.Lock()


@router.get("/scan", dependencies=[Depends(heavy_slot)])
def get_scan(market: str = Query("us", pattern="^(us|kr)$"), top: int = Query(20, ge=1, le=50)):
    """시장 스캔. 5분 캐시 + single-flight (#1119)."""
    key = (market, top)
    now = monotonic()
    hit = _scan_cache.get(key)
    if hit and (now - hit[0]) < _SCAN_CACHE_TTL_SECONDS:
        return hit[1]

    with _scan_lock:
        # double-check — 락 대기 중 다른 요청이 채웠을 수 있다
        now = monotonic()
        hit = _scan_cache.get(key)
        if hit and (now - hit[0]) < _SCAN_CACHE_TTL_SECONDS:
            return hit[1]

        from nuri.trading.swing.scanner import scan_market

        results = scan_market(market=market, top_n=top)
        payload = {"results": [asdict(r) for r in results], "count": len(results)}
        _scan_cache[key] = (monotonic(), payload)
        return payload


@router.get("/swing/entries", dependencies=[Depends(heavy_slot)])
def get_swing_entries(market: str = Query("us", pattern="^(us|kr)$")):
    """스윙 진입 후보 (스캔 + 에이전트 합의)."""
    import json

    from nuri.trading.swing.rules import evaluate_entries

    entries = evaluate_entries(market=market)
    # numpy 타입 → Python 네이티브 변환
    raw = [asdict(e) for e in entries]
    cleaned = json.loads(
        json.dumps(
            raw, default=lambda x: x.item() if hasattr(x, "item") else bool(x) if isinstance(x, type(True)) else str(x)
        )
    )
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


@router.get("/backtest", dependencies=[Depends(heavy_slot)])
def get_backtest():
    """L/S strategy backtest results."""
    from nuri.trading.strategy.ls_backtest import (
        analyze_entry_timing,
        analyze_per_regime,
        classify_historical_regimes,
        run_backtest,
        stress_test,
    )

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
        return json.loads(
            json.dumps(
                obj,
                default=lambda x: (
                    x.item() if hasattr(x, "item") else (bool(x) if isinstance(x, (type(True),)) else str(x))
                ),
            )
        )

    return _clean(
        {
            "result": asdict(result),
            "regimes": [asdict(p) for p in perfs],
            "timing": asdict(timing) if timing else None,
            "stress": stress,
        }
    )


@router.get("/backtest/equity", dependencies=[Depends(heavy_slot)])
def get_backtest_equity(
    sma: int = Query(50, ge=50, le=200),
    period: str = Query("3Y", pattern="^(1Y|3Y|5Y)$"),
    sl: int = Query(-7, ge=-15, le=-3),
    tp: int = Query(20, ge=10, le=40),
):
    """Equity curve + drawdown for interactive chart (#89).

    Returns lightweight data: equity curve points, drawdown, regime bands,
    SPY benchmark, and key metrics. Designed for Recharts frontend.
    """
    cache_key = (sma, period, sl, tp)
    cached = _interactive_backtest_cache.get(cache_key)
    now = monotonic()
    if cached and now - cached[0] < _BACKTEST_CACHE_TTL_SECONDS:
        return cached[1]

    with _backtest_lock:
        # double-check — 락을 기다리는 동안 다른 요청이 채웠을 수 있다
        cached = _interactive_backtest_cache.get(cache_key)
        now = monotonic()
        if cached and now - cached[0] < _BACKTEST_CACHE_TTL_SECONDS:
            return cached[1]
        return _run_interactive_backtest(sma, period, sl, tp, cache_key, now)


def _run_interactive_backtest(sma, period, sl, tp, cache_key, now):
    """실제 백테스트 — 반드시 `_backtest_lock` 을 쥔 채 부른다."""
    import json

    from nuri.trading.strategy.ls_backtest import (
        classify_historical_regimes,
        run_interactive_backtest,
    )

    regimes = classify_historical_regimes(sma_period=sma)
    if regimes.empty:
        return {"error": "SPY data insufficient"}

    lookback_days = {"1Y": 252, "3Y": 756, "5Y": 1260}[period]
    regimes = regimes.tail(lookback_days).reset_index(drop=True)

    result = run_interactive_backtest(
        regimes,
        stop_loss_pct=sl,
        take_profit_pct=tp,
    )

    # numpy → native
    def _clean(obj):
        return json.loads(json.dumps(obj, default=lambda x: x.item() if hasattr(x, "item") else str(x)))

    # equity curve with regime bands
    equity = result.equity_curve or []

    # drawdown from equity curve
    drawdown = []
    peak = 0
    for pt in equity:
        val = pt.get("equity", pt.get("value", 0))
        peak = max(peak, val)
        dd_pct = ((val - peak) / peak * 100) if peak > 0 else 0
        drawdown.append({"date": pt.get("date"), "drawdown": round(dd_pct, 2)})

    response = _clean(
        {
            "equity": equity,
            "drawdown": drawdown,
            "metrics": {
                "total_return": result.total_return,
                "annual_return": result.annual_return,
                "sharpe": result.sharpe,
                "max_drawdown": result.max_drawdown,
                "win_rate": result.win_rate,
                "spy_total_return": result.spy_total_return,
                "spy_sharpe": result.spy_sharpe,
                "spy_max_drawdown": result.spy_max_drawdown,
                "excess_return": result.excess_return,
            },
        }
    )
    _interactive_backtest_cache[cache_key] = (now, response)
    return response


@router.get("/strategy/status", dependencies=[Depends(heavy_slot)])
def get_strategy_status():
    """Current strategy + positions."""
    from dataclasses import asdict

    from nuri.quant.regime.classifier import classify_regime
    from nuri.trading.strategy.longshort import REGIME_ALLOCATION, generate_strategy
    from nuri.trading.strategy.monitor import daily_pnl_summary
    from nuri.trading.strategy.position import get_positions_summary

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

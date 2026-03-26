"""Dashboard API — 한 번의 호출로 "오늘 뭐하라고?"에 답하는 액션 중심 요약."""
import time
import logging
from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])

# 캐시 (5분 TTL)
_cache = {"data": None, "timestamp": 0}
CACHE_TTL = 300  # 5분


@router.get("/dashboard")
def get_dashboard():
    """오늘의 투자 판단 요약 — 액션 중심."""
    now = time.time()
    if _cache["data"] and (now - _cache["timestamp"]) < CACHE_TTL:
        return _cache["data"]

    result = _build_dashboard()
    _cache["data"] = result
    _cache["timestamp"] = now
    return result


def _build_dashboard() -> dict:
    """모든 분석을 종합하여 액션 중심 요약 생성."""
    from nuri.core.db import query

    # ── 1. 레짐 + 매크로 ──
    regime_data = {"regime": "unknown", "trend": "unknown", "confidence": 0}
    macro_data = {"score": 50, "interpretation": "Neutral"}
    allocation = {"long": 0, "short": 0, "cash": 100}

    try:
        from nuri.analysis.regime.classifier import classify_regime
        from nuri.analysis.regime.macro_score import compute_macro_score
        r = classify_regime()
        if r:
            regime_data = {"regime": r.regime, "trend": r.trend, "volatility": r.volatility,
                          "confidence": round(r.confidence * 100),
                          "vix": r.details.get("vix"), "fear_greed": r.details.get("fear_greed")}
        m = compute_macro_score()
        macro_data = {"score": round(m.total_score), "interpretation": m.interpretation}

        from nuri.trading.strategy.longshort import REGIME_ALLOCATION
        alloc = REGIME_ALLOCATION.get(r.regime if r else "sideways_high_vol", {})
        allocation = {"long": alloc.get("long_pct", 0), "short": alloc.get("short_pct", 0),
                     "cash": alloc.get("cash_pct", 100)}
    except Exception as e:
        logger.debug(f"Regime/macro: {e}")

    # ── 2. 핵심 액션 (BUY / SELL / WATCH) ──
    actions = []
    try:
        from nuri.trading.agents.consensus import analyze_portfolio
        results = analyze_portfolio()
        for cr in sorted(results, key=lambda x: x.final_confidence, reverse=True):
            if cr.final_action == "BUY" and cr.final_confidence >= 50:
                # 에이전트 근거 1줄
                supporters = [v for v in cr.verdicts if v.action == "BUY"]
                why = supporters[0].reasoning[:50] if supporters else ""
                actions.append({"action": "BUY", "ticker": cr.ticker,
                              "confidence": round(cr.final_confidence),
                              "agreement": round(cr.agreement_rate * 100),
                              "reason": why})
            elif cr.final_action == "SELL" and cr.final_confidence >= 70:
                sellers = [v for v in cr.verdicts if v.action == "SELL"]
                why = sellers[0].reasoning[:50] if sellers else ""
                actions.append({"action": "SELL", "ticker": cr.ticker,
                              "confidence": round(cr.final_confidence),
                              "agreement": round(cr.agreement_rate * 100),
                              "reason": why})

        # HOLD 중 주목할 종목 (smart money/wallstreet BUY인데 전체 HOLD)
        for cr in results:
            if cr.final_action == "HOLD" and cr.agreement_rate < 0.8:
                dissenters = [v for v in cr.verdicts if v.action == "BUY" and v.confidence >= 70]
                if dissenters:
                    actions.append({"action": "WATCH", "ticker": cr.ticker,
                                  "confidence": round(cr.final_confidence),
                                  "agreement": round(cr.agreement_rate * 100),
                                  "reason": f"{dissenters[0].agent_name}: {dissenters[0].reasoning[:40]}"})
    except Exception as e:
        logger.debug(f"Actions: {e}")

    # 상위 5개만
    buys = [a for a in actions if a["action"] == "BUY"][:3]
    sells = [a for a in actions if a["action"] == "SELL"][:3]
    watches = [a for a in actions if a["action"] == "WATCH"][:2]
    top_actions = buys + sells + watches

    # ── 3. 리스크 알림 ──
    alerts = []
    try:
        from nuri.analysis.risk import analyze_risk
        risk = analyze_risk()
        if risk.get("portfolio_stop_triggered"):
            alerts.append({"level": "critical", "message": f"포트폴리오 손절선 돌파 (MDD {risk['max_drawdown_pct']:.1f}%)"})
        for a in risk.get("stop_loss_alerts", [])[:3]:
            alerts.append({"level": "warning", "message": f"{a['ticker']} 손절선 ({a['pnl_pct']:+.1f}%)"})
    except Exception:
        pass

    # drift 경고
    try:
        from nuri.engine.memory import detect_drift
        drifts = detect_drift()
        critical = [d for d in drifts if d.status == "critical"]
        if critical:
            names = ", ".join(d.signal_id for d in critical[:3])
            alerts.append({"level": "warning", "message": f"시그널 성과 급락: {names}"})
    except Exception:
        pass

    # 충돌
    try:
        from nuri.engine.conflicts import detect_conflicts
        conflicts = detect_conflicts()
        if conflicts:
            tickers = ", ".join(set(c.ticker for c in conflicts[:5]))
            alerts.append({"level": "info", "message": f"BUY/SELL 충돌 {len(conflicts)}건: {tickers}"})
    except Exception:
        pass

    # ── 4. 한 줄 판단 (verdict) ──
    trend = regime_data.get("trend", "unknown")
    macro_score = macro_data["score"]
    n_buys = len(buys)
    n_sells = len(sells)

    if trend == "bear" or macro_score < 35:
        verdict = "방어 모드. 현금 비중 유지하고 숏 헤지를 검토하세요."
        verdict_level = "defensive"
    elif trend == "bull" and macro_score >= 60:
        verdict = f"공격 가능. {n_buys}개 매수 후보가 에이전트 합의를 통과했습니다."
        verdict_level = "aggressive"
    elif n_sells > n_buys:
        verdict = f"매도 우위. 에이전트 {n_sells}종목 매도, {n_buys}종목 매수 판정."
        verdict_level = "cautious"
    else:
        verdict = f"관망. 횡보 + 고변동 구간. 대기하며 레짐 전환을 주시하세요."
        verdict_level = "neutral"

    # drift 경고가 있으면 verdict에 추가
    try:
        drifts = detect_drift()
        critical_count = sum(1 for d in drifts if d.status == "critical")
        if critical_count >= 2:
            verdict += f" (매수 시그널 {critical_count}개 성과 급락 중 — 신뢰도 하향)"
    except Exception:
        pass

    # ── 5. Gate 상태 ──
    gate_score = 0
    try:
        from nuri.engine.gate import check_gate
        g = check_gate()
        gate_score = round(g.score * 100)
    except Exception:
        pass

    return {
        "verdict": verdict,
        "verdict_level": verdict_level,  # aggressive/neutral/cautious/defensive
        "regime": regime_data,
        "macro": macro_data,
        "allocation": allocation,
        "actions": top_actions,
        "alerts": alerts,
        "gate_score": gate_score,
        "n_positions": len(query("SELECT 1 FROM positions WHERE status='open'")),
    }

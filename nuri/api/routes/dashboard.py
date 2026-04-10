"""Dashboard API — 한 번의 호출로 "오늘 뭐하라고?"에 답하는 액션 중심 요약.

v2: DB 조회 전용 (<500ms). analyze_portfolio() 인라인 호출 제거.
    - 레짐/매크로: 빠른 조회 유지 (3-5s)
    - 액션: recommendations 테이블에서 읽기
    - Gate: 기존 유지 (query-only)
    - 신선도/파이프라인: 새 모듈에서 조회
"""
import logging
import time

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])

# 캐시 (5분 TTL)
_cache: dict = {"data": None, "timestamp": 0}
CACHE_TTL = 300  # 5분


@router.get("/dashboard")
def get_dashboard():
    """오늘의 투자 판단 요약 — DB 조회 전용 (projection 기반)."""
    now = time.time()
    if _cache["data"] and (now - _cache["timestamp"]) < CACHE_TTL:
        return _cache["data"]

    result = _build_dashboard()
    _cache["data"] = result
    _cache["timestamp"] = now
    return result


def _build_dashboard() -> dict:
    """모든 분석을 종합하여 액션 중심 요약 생성 — DB 조회 전용."""
    from nuri.core.db import query

    # ── 1. 레짐 + 매크로 (빠름: 3-5s) ──
    regime_data = _get_cached_regime()
    macro_data = _get_macro()
    allocation = _get_allocation(regime_data.get("regime", "sideways_high_vol"))

    # ── 2. 핵심 액션 — recommendations 테이블에서 조회 (빠름) ──
    actions = _get_latest_actions()

    # ── 3. 리스크 알림 ──
    alerts = _get_active_alerts()

    # ── 4. 한 줄 판단 (verdict) ──
    trend = regime_data.get("trend", "unknown")
    macro_score = macro_data["score"]
    n_buys = len([a for a in actions if a["action"] == "BUY"])
    n_sells = len([a for a in actions if a["action"] == "SELL"])

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
        verdict = "관망. 횡보 + 고변동 구간. 대기하며 레짐 전환을 주시하세요."
        verdict_level = "neutral"

    # ── 5. Gate 상태 ──
    gate_score = _get_gate_score()

    # ── 6. 신선도 + 파이프라인 ──
    freshness = _get_freshness()
    pipeline_status = _get_pipeline_status()

    # ── 7. 환율 ──
    rate_row = query("SELECT value FROM macro WHERE indicator = 'usd_krw' ORDER BY date DESC LIMIT 1")
    exchange_rate = rate_row[0]["value"] if rate_row else None

    # ── 8. 계좌별 평가액 ──
    account_values = _get_account_values(exchange_rate)

    return {
        "verdict": verdict,
        "verdict_level": verdict_level,
        "regime": regime_data,
        "macro": macro_data,
        "allocation": allocation,
        "actions": actions,
        "alerts": alerts,
        "gate_score": gate_score,
        "n_positions": len(query("SELECT 1 FROM positions WHERE status='open'")),
        "freshness": freshness,
        "pipeline_status": pipeline_status,
        "exchange_rate": exchange_rate,
        "account_values": account_values,
    }


def _get_cached_regime() -> dict:
    """레짐 분류 — classify_regime()은 빠름 (3-5s)."""
    try:
        from nuri.quant.regime.classifier import classify_regime
        r = classify_regime()
        if r:
            return {
                "regime": r.regime,
                "trend": r.trend,
                "volatility": r.volatility,
                "confidence": round(r.confidence * 100),
                "vix": r.details.get("vix"),
                "fear_greed": r.details.get("fear_greed"),
            }
    except Exception as e:
        logger.debug(f"Regime: {e}")
    return {"regime": "unknown", "trend": "unknown", "confidence": 0}


def _get_macro() -> dict:
    """매크로 스코어 — compute_macro_score()은 빠름 (1-2s)."""
    try:
        from nuri.quant.regime.macro_score import compute_macro_score
        m = compute_macro_score()
        return {"score": round(m.total_score), "interpretation": m.interpretation}
    except Exception as e:
        logger.debug(f"Macro: {e}")
    return {"score": 50, "interpretation": "Neutral"}


def _get_allocation(regime: str) -> dict:
    """레짐별 자산 배분 비율."""
    try:
        from nuri.trading.strategy.longshort import REGIME_ALLOCATION
        alloc = REGIME_ALLOCATION.get(regime, {})
        return {
            "long": alloc.get("long_pct", 0),
            "short": alloc.get("short_pct", 0),
            "cash": alloc.get("cash_pct", 100),
        }
    except Exception:
        return {"long": 0, "short": 0, "cash": 100}


def _extract_reason(signals_raw: str | None) -> tuple[str, float | None]:
    """signals JSON에서 reasoning 텍스트와 agreement_rate 추출."""
    if not signals_raw:
        return "", None
    import json
    try:
        data = json.loads(signals_raw)
        reasoning = data.get("reasoning", "")
        # 첫 60자만 (UI line-clamp-1)
        reason = reasoning[:60] if reasoning else ""
        agreement = data.get("agreement_rate")
        return reason, agreement
    except (json.JSONDecodeError, TypeError):
        return signals_raw[:60], None


def _get_ticker_account_map() -> dict[str, str]:
    """ticker → account 매핑 (첫 번째 계좌 기준)."""
    from nuri.core.db import query
    rows = query("SELECT ticker, account FROM portfolio ORDER BY account")
    mapping: dict[str, str] = {}
    for r in rows:
        if r["ticker"] not in mapping:
            mapping[r["ticker"]] = r["account"]
    return mapping


def _get_account_labels() -> dict[str, str]:
    """계좌명 → 표시 라벨 매핑. portfolio.yaml strategy 필드 기반 (broker명 노출 금지)."""
    from pathlib import Path  # noqa: E402

    import yaml  # noqa: E402

    _STRATEGY_LABELS = {"core": "Main", "swing": "Sub", "pension": "Pension", "longterm": "Long"}
    portfolio_path = Path(__file__).parent.parent.parent.parent / "config" / "portfolio.yaml"
    try:
        with open(portfolio_path, encoding="utf-8") as f:
            portfolio = yaml.safe_load(f)
        labels: dict[str, str] = {}
        seen: dict[str, int] = {}
        for acc, info in (portfolio.get("accounts") or {}).items():
            strategy_name = (info or {}).get("strategy", "core")
            base_label = _STRATEGY_LABELS.get(strategy_name, strategy_name.title())
            count = seen.get(base_label, 0)
            seen[base_label] = count + 1
            labels[acc] = base_label if count == 0 else f"{base_label} {count + 1}"
        return labels
    except Exception:
        return {}


def _get_latest_actions() -> list[dict]:
    """recommendations 테이블에서 최신 추천 조회 — analyze_portfolio() 대체."""
    from nuri.core.db import query
    from nuri.core.ticker_names import get_ticker_name
    try:
        rows = query("""
            SELECT ticker, action, confidence, regime, signals, date
            FROM recommendations
            WHERE date = (SELECT MAX(date) FROM recommendations)
            ORDER BY confidence DESC
        """)
        if not rows:
            return []

        ticker_account = _get_ticker_account_map()
        account_labels = _get_account_labels()

        actions = []
        for row in rows:
            action = row["action"]
            confidence = round(row["confidence"] * 100) if row["confidence"] and row["confidence"] <= 1 else round(row["confidence"] or 0)
            reason, agreement_rate = _extract_reason(row.get("signals"))
            raw_account = ticker_account.get(row["ticker"], "")
            account_label = account_labels.get(raw_account, raw_account)

            if action == "BUY" and confidence >= 50:
                actions.append({
                    "action": "BUY",
                    "ticker": row["ticker"],
                    "name": get_ticker_name(row["ticker"]),
                    "confidence": confidence,
                    "reason": reason,
                    "agreement": round(agreement_rate * 100) if agreement_rate is not None else None,
                    "account": account_label,
                })
            elif action == "SELL" and confidence >= 70:
                actions.append({
                    "action": "SELL",
                    "ticker": row["ticker"],
                    "name": get_ticker_name(row["ticker"]),
                    "confidence": confidence,
                    "reason": reason,
                    "agreement": round(agreement_rate * 100) if agreement_rate is not None else None,
                    "account": account_label,
                })

        # 상위 5개만
        buys = [a for a in actions if a["action"] == "BUY"][:3]
        sells = [a for a in actions if a["action"] == "SELL"][:3]
        return buys + sells
    except Exception as e:
        logger.debug(f"Actions from DB: {e}")
        return []


def _get_account_values(exchange_rate: float | None) -> list[dict]:
    """계좌별 평가액 계산."""
    from nuri.core.db import query
    rate = exchange_rate or 1400
    rows = query("""
        SELECT p.account, p.ticker, p.quantity,
               pr.close as latest_price
        FROM portfolio p
        LEFT JOIN (
            SELECT ticker, close FROM prices
            WHERE (ticker, date) IN (SELECT ticker, MAX(date) FROM prices GROUP BY ticker)
        ) pr ON p.ticker = pr.ticker
    """)
    totals: dict[str, float] = {}
    for r in rows:
        acc = r["account"]
        price = r["latest_price"] or 0
        qty = r["quantity"] or 0
        is_kr = r["ticker"].endswith(".KS")
        val = price * qty / rate if is_kr else price * qty
        totals[acc] = totals.get(acc, 0) + val

    account_labels = _get_account_labels()
    return [
        {"account": account_labels.get(acc, acc), "value": round(v, 2)}
        for acc, v in sorted(totals.items(), key=lambda x: -x[1])
    ]


def _get_gate_score() -> int:
    """Gate 상태 — check_gate()은 빠름 (query-only)."""
    try:
        from nuri.trading.engine.gate import check_gate
        g = check_gate()
        return round(g.score * 100)
    except Exception:
        return 0


def _get_active_alerts() -> list[dict]:
    """리스크 알림 (violations + drift + conflicts)."""
    alerts = []

    # 리스크 분석
    try:
        from nuri.analysis.risk import analyze_risk
        risk = analyze_risk()
        if risk.get("portfolio_stop_triggered"):
            alerts.append({
                "level": "critical",
                "message": f"포트폴리오 손절선 돌파 (MDD {risk['max_drawdown_pct']:.1f}%)",
            })
        for a in risk.get("stop_loss_alerts", [])[:3]:
            alerts.append({"level": "warning", "message": f"{a['ticker']} 손절선 ({a['pnl_pct']:+.1f}%)"})
    except Exception:
        pass

    # drift 경고
    try:
        from nuri.trading.engine.memory import detect_drift
        drifts = detect_drift()
        critical = [d for d in drifts if d.status == "critical"]
        if critical:
            names = ", ".join(d.signal_id for d in critical[:3])
            alerts.append({"level": "warning", "message": f"시그널 성과 급락: {names}"})
    except Exception:
        pass

    # 충돌
    try:
        from nuri.trading.engine.conflicts import detect_conflicts
        conflicts = detect_conflicts()
        if conflicts:
            tickers = ", ".join(set(c.ticker for c in conflicts[:5]))
            alerts.append({"level": "info", "message": f"BUY/SELL 충돌 {len(conflicts)}건: {tickers}"})
    except Exception:
        pass

    return alerts


def _get_freshness() -> dict:
    """데이터 신선도 요약."""
    try:
        from nuri.core.freshness import check_all_freshness
        details = check_all_freshness()
        return {d["table"]: {"age_hours": d["age_hours"], "status": d["status"]} for d in details}
    except Exception as e:
        logger.debug(f"Freshness: {e}")
        return {}


def _get_pipeline_status() -> dict:
    """파이프라인 6단계 최신 실행 상태."""
    try:
        from nuri.core.events import get_pipeline_status
        return get_pipeline_status()
    except Exception as e:
        logger.debug(f"Pipeline status: {e}")
        return {}

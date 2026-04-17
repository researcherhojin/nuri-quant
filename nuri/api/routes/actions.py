"""Action-First API — 오늘 뭐 해야 하는지 우선순위로 정리.

🔴 즉시 실행: SIEGE 위반, 손절선 돌파, 강한 SELL 시그널
🟡 오늘 확인: 익절 도달, 트레일링 진입, 헤지 검토
✅ 유지: 정상 보유 종목
🔍 기회 탐색: 비보유 이슈 종목 + 매수 판정
"""
import json
import logging
import time
from datetime import timedelta

from fastapi import APIRouter

from nuri.core.db import query
from nuri.core.timezone import kst_now

logger = logging.getLogger(__name__)
router = APIRouter(tags=["actions"])

# 캐시 (5분 TTL) — dashboard.py와 동일 패턴
CACHE_TTL = 300  # 5분
_actions_cache: dict = {"data": None, "timestamp": 0}
_opportunities_cache: dict = {"data": None, "timestamp": 0}
_market_context_cache: dict = {"data": None, "timestamp": 0}


# ─── /api/actions ───


@router.get("/actions")
def get_actions():
    """우선순위 분류된 오늘의 액션 리스트."""
    now = time.time()
    if _actions_cache["data"] and (now - _actions_cache["timestamp"]) < CACHE_TTL:
        return _actions_cache["data"]
    try:
        result = _build_actions()
        _actions_cache["data"] = result
        _actions_cache["timestamp"] = time.time()
        return result
    except Exception:
        logger.exception("actions API error")
        return {"urgent": [], "check": [], "hold": []}


def _build_actions() -> dict:
    """consensus + SIEGE + targets를 종합하여 🔴/🟡/✅ 분류."""
    urgent: list[dict] = []  # 🔴
    check: list[dict] = []   # 🟡
    hold: list[dict] = []    # ✅

    # ── 데이터 수집 ──
    recommendations = _get_recommendations()
    siege_violations = _get_siege_violations()
    targets_status = _get_targets_status()
    portfolio_holdings = _get_portfolio_map()

    violation_tickers = {v["ticker"] for v in siege_violations}

    # 연금 계좌 종목 식별 (월간 리밸런싱 → daily action에서 제외)
    pension_tickers = {
        t for t, h in portfolio_holdings.items()
        if any(kw in (h.get("account") or "").lower() for kw in ("연금", "pension", "irp"))
    }

    from nuri.core.ticker_names import get_ticker_name

    seen_tickers: set[str] = set()  # 중복 방지
    for rec in recommendations:
        ticker = rec["ticker"]
        # 연금 종목 skip (daily action 불필요)
        if ticker in pension_tickers:
            continue
        # 중복 ticker skip (복수 계좌 동일 종목)
        if ticker in seen_tickers:
            continue
        seen_tickers.add(ticker)

        action = rec["action"]
        confidence = rec["confidence"]
        holding = portfolio_holdings.get(ticker, {})
        pnl_pct = holding.get("pnl_pct", 0)
        position_pct = holding.get("position_pct", 0)
        target = targets_status.get(ticker, {})

        item = {
            "ticker": ticker,
            "name": get_ticker_name(ticker),
            "action": action,
            "confidence": confidence,
            "agreement": rec.get("agreement"),
            "pnl_pct": round(pnl_pct, 1),
            "position_pct": round(position_pct, 1),
            "current_price": holding.get("current_price"),
            "avg_price": holding.get("avg_price"),
            "account": holding.get("account", ""),
            "stop_loss": target.get("stop_loss"),
            "target_1": target.get("target_1"),
            "target_2": target.get("target_2"),
            "reasons": [],
            # A-2b: `_get_recommendations` 가 parse 해둔 JSON 을 그대로 노출.
            # Frontend (A-2c) 가 actions card 에서 10-agent breakdown + basis/penalty
            # 표시. codex A-2b Round 1 HIGH — `_build_actions` 이 drop 하던 bug fix.
            "scoring_detail": rec.get("scoring_detail"),
            "agent_verdicts": rec.get("agent_verdicts"),
        }

        # ── 🔴 즉시 실행 조건 ──

        # SIEGE 한도 초과
        if ticker in violation_tickers:
            violation = next(v for v in siege_violations if v["ticker"] == ticker)
            item["reasons"].append(violation["detail"])
            item["priority"] = "urgent"
            urgent.append(item)
            continue

        # 강한 SELL 시그널
        if action == "SELL":
            item["reasons"].append(f"10-Agent SELL (conf {confidence})")
            if pnl_pct < -7:
                item["reasons"].append(f"손실 {pnl_pct:+.1f}% — 손절선 근접")
                item["priority"] = "urgent"
                urgent.append(item)
                continue
            item["priority"] = "check"
            check.append(item)
            continue

        # ── 🟡 오늘 확인 조건 ──

        promoted = False

        # 2차 익절 도달
        if target.get("target_2") and item["current_price"] and item["current_price"] >= target["target_2"]:
            item["reasons"].append("2차 익절 도달 — 트레일링 전환 권장")
            promoted = True

        # 1차 익절 도달
        elif target.get("target_1") and item["current_price"] and item["current_price"] >= target["target_1"]:
            item["reasons"].append(f"1차 익절 도달 (+{pnl_pct:.0f}%) — 50% 매도 고려")
            promoted = True

        # 높은 공매도 비율
        short_pct = _get_short_interest(ticker)
        if short_pct and short_pct > 10:
            item["reasons"].append(f"공매도 {short_pct:.1f}% — squeeze 주의")
            promoted = True

        if promoted:
            item["priority"] = "check"
            check.append(item)
            continue

        # ── ✅ 유지 ──
        item["priority"] = "hold"
        item["reasons"].append(f"BUY (conf {confidence})" if action == "BUY" else f"HOLD (conf {confidence})")
        hold.append(item)

    return {
        "urgent": urgent,
        "check": check,
        "hold": hold,
        "generated_at": kst_now().isoformat(),
    }


# ─── /api/opportunities ───


@router.get("/opportunities")
def get_opportunities():
    """비보유 이슈 종목 탐색 — scan + WSB + macro events 기반 판정."""
    now = time.time()
    if _opportunities_cache["data"] and (now - _opportunities_cache["timestamp"]) < CACHE_TTL:
        return _opportunities_cache["data"]
    try:
        result = {"opportunities": _build_opportunities(), "generated_at": kst_now().isoformat()}
        _opportunities_cache["data"] = result
        _opportunities_cache["timestamp"] = time.time()
        return result
    except Exception:
        logger.exception("opportunities API error")
        return {"opportunities": []}


def _build_opportunities() -> list[dict]:
    """스캔 결과 + 뉴스 이슈에서 비보유 종목을 찾고 찬성/반대/판정 생성."""
    portfolio_tickers = set(_get_portfolio_map().keys())

    # 스캔 결과 (최근 저장된 것)
    scan_results = _get_recent_scan_results()

    # 시그널 드리프트 (현재 유효한 시그널)
    improving_signals = _get_improving_signals()

    opportunities = []
    for s in scan_results:
        ticker = s["ticker"]
        if ticker in portfolio_tickers:
            continue

        pros: list[str] = []
        cons: list[str] = []

        # 찬성 근거
        if s.get("signal") == "breakout" and s.get("score", 0) >= 50:
            pros.append(f"breakout 시그널 (Score {s['score']})")
        if s.get("signal") == "momentum" and s.get("change_5d", 0) > 10:
            pros.append(f"강한 모멘텀 5D +{s['change_5d']:.1f}%")
        if s.get("rsi") and s["rsi"] < 35:
            if "rsi_oversold" in improving_signals:
                pros.append(f"RSI {s['rsi']:.0f} 과매도 (rsi_oversold 승률 상승 중)")
            else:
                pros.append(f"RSI {s['rsi']:.0f} 과매도")
        if s.get("volume_ratio", 0) >= 2.0:
            pros.append(f"거래량 {s['volume_ratio']:.1f}x 폭증")

        # 반대 근거
        if s.get("rsi") and s["rsi"] > 80:
            cons.append(f"RSI {s['rsi']:.0f} 과매수")
        if s.get("change_5d", 0) < -15:
            cons.append(f"5D {s['change_5d']:+.1f}% 급락 — 하락 모멘텀")
        if s.get("change_5d", 0) > 20:
            cons.append(f"5D +{s['change_5d']:.1f}% 이미 급등 — 추격 매수 위험")
        if s.get("signal") == "volume_spike" and s.get("change_5d", 0) < -10:
            cons.append("급락 + volume_spike — 원인 확인 필요")

        # 판정
        verdict, verdict_level = _compute_verdict(pros, cons, s)

        opportunities.append({
            "ticker": ticker,
            "price": s.get("price"),
            "change_1d": s.get("change_1d"),
            "change_5d": s.get("change_5d"),
            "volume_ratio": s.get("volume_ratio"),
            "rsi": s.get("rsi"),
            "signal": s.get("signal"),
            "score": s.get("score"),
            "pros": pros,
            "cons": cons,
            "verdict": verdict,
            "verdict_level": verdict_level,
        })

    # score 높은 순 + volume_spike 우선
    opportunities.sort(key=lambda x: (x["score"] or 0), reverse=True)
    return opportunities[:10]


def _compute_verdict(pros: list[str], cons: list[str], scan: dict) -> tuple[str, str]:
    """찬성/반대 근거를 종합하여 판정."""
    score = scan.get("score", 0)
    rsi = scan.get("rsi", 50)
    change_5d = scan.get("change_5d", 0)

    # 🔴 매수 금지
    if change_5d < -20 and rsi < 20:
        return "매수 금지 — 극단적 하락, 원인 확인 전 진입 위험", "danger"
    if not pros and cons:
        return "매수 금지 — 근거 부족", "danger"

    # 🟢 매수 고려
    if len(pros) >= 2 and not cons and score >= 40:
        return "매수 고려 — 다수 시그널 정렬", "positive"

    # 🟡 관망
    if pros and cons:
        return "관망 — 혼재 시그널, 조건부 진입 대기", "neutral"
    if change_5d > 15:
        return "관망 — 과매수 구간, 눌림목 대기", "neutral"

    return "데이터 부족 — 판단 불가", "muted"


# ─── /api/market-context ───


@router.get("/market-context")
def get_market_context():
    """시장 컨텍스트 — 매크로 이벤트 + 시스템 건강 (#137 UI)."""
    now = time.time()
    if _market_context_cache["data"] and (now - _market_context_cache["timestamp"]) < CACHE_TTL:
        return _market_context_cache["data"]
    try:
        result = {
            "macro_events": _get_macro_events(),
            "system_health": _get_system_health(),
            "generated_at": kst_now().isoformat(),
        }
        _market_context_cache["data"] = result
        _market_context_cache["timestamp"] = time.time()
        return result
    except Exception:
        logger.exception("market-context API error")
        return {"macro_events": [], "system_health": {}, "generated_at": kst_now().isoformat()}


# ─── 내부 헬퍼 ──


def _get_recommendations() -> list[dict]:
    """최신 consensus 결과 조회.

    A-2b: `scoring_detail` + `agent_verdicts` 컬럼도 노출 — frontend (A-2c) 가
    10-agent contribution breakdown 시각화 + basis_action/penalty 표시에 사용.
    """
    rows = query("""
        SELECT ticker, action, confidence, signals, scoring_detail, agent_verdicts
        FROM recommendations
        WHERE date = (SELECT MAX(date) FROM recommendations)
        ORDER BY confidence DESC
    """)
    results = []
    for r in rows:
        agreement = None
        if r["signals"]:
            try:
                data = json.loads(r["signals"])
                agreement = data.get("agreement_rate")
            except (json.JSONDecodeError, TypeError):
                pass
        # Parse 실패 → None. source=consensus/candidate 로 frontend 분기 (PR #364/#366).
        scoring_detail = None
        if r.get("scoring_detail"):
            try:
                scoring_detail = json.loads(r["scoring_detail"])
            except (json.JSONDecodeError, TypeError):
                pass
        agent_verdicts = None
        if r.get("agent_verdicts"):
            try:
                agent_verdicts = json.loads(r["agent_verdicts"])
            except (json.JSONDecodeError, TypeError):
                pass
        results.append({
            "ticker": r["ticker"],
            "action": r["action"],
            "confidence": round(r["confidence"] * 100) if r["confidence"] and r["confidence"] <= 1 else round(r["confidence"] or 0),
            "agreement": round(agreement * 100) if agreement is not None and agreement <= 1 else agreement,
            "scoring_detail": scoring_detail,
            "agent_verdicts": agent_verdicts,
        })
    return results


def _get_siege_violations() -> list[dict]:
    """SIEGE 인증 위반 사항 조회."""
    import re

    violations = []
    try:
        from nuri.trading.engine.certification import certify
        cert = certify()
        for c in cert.conditions:
            if not c.passed and c.severity == "error":
                detail = c.detail or ""
                if c.id == "position_limit":
                    # "위반: TSLA(15.4%>15%)" or "위반: TSLA(15.4%>15%), NBIS(16%>15%)"
                    matches = re.findall(r"(\S+?)\([\d.]+%>[\d.]+%\)", detail)
                    for ticker in matches:
                        violations.append({"ticker": ticker, "detail": f"SIEGE: {c.description} — {detail}", "condition_id": c.id})
                    if not matches:
                        violations.append({"ticker": "", "detail": f"SIEGE: {c.description} — {detail}", "condition_id": c.id})
                else:
                    violations.append({"ticker": "", "detail": f"SIEGE: {c.description} — {detail}", "condition_id": c.id})
    except Exception as e:
        logger.debug(f"SIEGE violations: {e}")
    return violations


def _get_targets_status() -> dict[str, dict]:
    """포트폴리오 가격 타겟 조회."""
    targets = {}
    try:
        from nuri.trading.recommend.price_targets import calculate_portfolio_targets
        for t in calculate_portfolio_targets():
            targets[t["ticker"]] = {
                "stop_loss": t.get("stop_loss"),
                "target_1": t.get("target_1"),
                "target_2": t.get("target_2"),
                "trailing_stop_pct": t.get("trailing_stop_pct"),
                "analyst_target": t.get("analyst_target"),
            }
    except Exception as e:
        logger.debug(f"Targets: {e}")
    return targets


def _get_portfolio_map() -> dict[str, dict]:
    """보유 종목 → 현재 상태 매핑."""
    from nuri.api.routes.dashboard import _get_account_labels

    rows = query("""
        SELECT p.account, p.ticker, p.quantity, p.avg_price, p.currency,
               pr.close as current_price
        FROM portfolio p
        LEFT JOIN (
            SELECT ticker, close FROM prices
            WHERE (ticker, date) IN (SELECT ticker, MAX(date) FROM prices GROUP BY ticker)
        ) pr ON p.ticker = pr.ticker
    """)

    rate_row = query("SELECT value FROM macro WHERE indicator = 'usd_krw' ORDER BY date DESC LIMIT 1")
    rate = rate_row[0]["value"] if rate_row else 1400

    # 총 자산 계산 (비중% 산정용)
    total_value = 0
    items = []
    for r in rows:
        price = r["current_price"] or r["avg_price"] or 0
        qty = r["quantity"] or 0
        is_kr = r["ticker"].endswith(".KS")
        val = price * qty / rate if is_kr else price * qty
        total_value += val
        items.append((r, val, price, is_kr))

    labels = _get_account_labels()
    result: dict[str, dict] = {}
    for r, val, price, is_kr in items:
        ticker = r["ticker"]
        avg = r["avg_price"] or 0
        pnl = ((price - avg) / avg * 100) if avg > 0 else 0
        pos_pct = (val / total_value * 100) if total_value > 0 else 0

        # 동일 티커 복수 계좌: 기존 데이터에 더 큰 비중을 보존
        if ticker in result and result[ticker]["position_pct"] > pos_pct:
            continue

        result[ticker] = {
            "current_price": price,
            "avg_price": avg,
            "quantity": r["quantity"],
            "pnl_pct": pnl,
            "position_pct": pos_pct,
            "account": labels.get(r["account"], r["account"]),
        }
    return result


def _get_short_interest(ticker: str) -> float | None:
    """공매도 비율 조회."""
    rows = query(
        "SELECT numeric_value FROM external_analysis WHERE ticker = ? AND data_type = 'short_pct_float' ORDER BY date DESC LIMIT 1",
        (ticker,),
    )
    return rows[0]["numeric_value"] if rows else None


def _get_recent_scan_results() -> list[dict]:
    """최근 스캔 결과를 swing_trades 또는 직접 실행에서 가져옴."""
    try:
        from nuri.trading.swing.scanner import scan_market
        results = scan_market(extended=False)
        return [
            {
                "ticker": r.ticker,
                "price": r.price,
                "change_1d": r.change_1d,
                "change_5d": r.change_5d,
                "volume_ratio": r.volume_ratio,
                "rsi": r.rsi,
                "signal": r.signal,
                "score": r.score,
            }
            for r in results[:30]
        ]
    except Exception as e:
        logger.debug(f"Scan: {e}")
        return []


def _get_improving_signals() -> set[str]:
    """승률 상승 중인 시그널 목록."""
    improving = set()
    try:
        from nuri.trading.engine.memory import detect_drift
        drifts = detect_drift()
        for d in drifts:
            if d.status == "improving":
                improving.add(d.signal_id)
    except Exception:
        pass
    return improving


_CATEGORY_KO: dict[str, str] = {
    "geopolitical_escalation": "지정학 긴장 고조",
    "geopolitical_de_escalation": "지정학 긴장 완화",
    "oil_supply_shock": "유가 충격",
    "trade_war": "무역 분쟁",
    "fed_dovish": "Fed 완화 시사",
    "fed_hawkish": "Fed 긴축 시사",
    "earnings_beat": "실적 호실적",
    "earnings_miss": "실적 부진",
    "sector_rally": "섹터 랠리",
    "demand_growth": "수요 증가",
    "export_surge": "수출 급증",
}


def _get_macro_events() -> list[dict]:
    """최근 7일 매크로 이벤트 (category != neutral, confidence >= 0.5).

    headline을 카테고리 한국어 + 원문 요약으로 변환.
    """
    cutoff = (kst_now() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = query("""
        SELECT category, headline, sentiment, confidence, published_at, source
        FROM macro_events
        WHERE published_at >= ?
          AND category != 'neutral'
          AND confidence >= 0.5
        ORDER BY ABS(sentiment) DESC
        LIMIT 10
    """, (cutoff,))
    results = []
    seen_categories: dict[str, int] = {}
    for r in rows:
        cat = r["category"] or ""
        # 같은 카테고리 3개 이상이면 skip (중복 TSMC 뉴스 방지)
        seen_categories[cat] = seen_categories.get(cat, 0) + 1
        if seen_categories[cat] > 2:
            continue
        ko_label = _CATEGORY_KO.get(cat, cat)
        results.append({
            **dict(r),
            "category_ko": ko_label,
        })
    return results[:8]


def _get_system_health() -> dict:
    """시스템 건강 요약 — SIEGE / 레짐 / 매크로 / 데이터 신선도."""
    health = {"siege": {}, "regime": {}, "macro": {}, "freshness": {}}

    # SIEGE
    try:
        from nuri.trading.engine.certification import certify
        cert = certify()
        health["siege"] = {
            "score": round(cert.score),
            "certified": cert.certified,
            "passed": cert.passed,
            "failed": cert.failed,
            "warnings": cert.warnings,
            "total": cert.total_conditions,
        }
    except Exception:
        health["siege"] = {"score": 0, "certified": False}

    # 레짐
    try:
        from nuri.quant.regime.classifier import classify_regime
        r = classify_regime()
        if r:
            health["regime"] = {
                "regime": r.regime,
                "trend": r.trend,
                "volatility": r.volatility,
                "confidence": round(r.confidence * 100),
            }
    except Exception:
        pass

    # 매크로
    try:
        from nuri.quant.regime.macro_score import compute_macro_score
        m = compute_macro_score()
        health["macro"] = {"score": round(m.total_score), "interpretation": m.interpretation}
    except Exception:
        pass

    # 신선도
    try:
        from nuri.core.freshness import check_all_freshness
        details = check_all_freshness()
        fail_count = sum(1 for d in details if d["status"] == "FAIL")
        warn_count = sum(1 for d in details if d["status"] == "WARN")
        health["freshness"] = {
            "status": "FAIL" if fail_count > 0 else "WARN" if warn_count > 0 else "PASS",
            "fail_count": fail_count,
            "warn_count": warn_count,
        }
    except Exception:
        pass

    return health

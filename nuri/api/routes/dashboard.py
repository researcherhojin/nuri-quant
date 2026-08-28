"""Dashboard API — 한 번의 호출로 "오늘 뭐하라고?"에 답하는 액션 중심 요약.

v2: DB 조회 전용 (<500ms). analyze_portfolio() 인라인 호출 제거.
    - 레짐/매크로: 빠른 조회 유지 (3-5s)
    - 액션: recommendations 테이블에서 읽기
    - Gate: 기존 유지 (query-only)
    - 신선도/파이프라인: 새 모듈에서 조회
"""

import logging
import threading
import time

from fastapi import APIRouter, Depends

from nuri.api.cache import portfolio_version
from nuri.api.limits import heavy_slot

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])

# 캐시 (5분 TTL)
# `version` — 포트폴리오가 바뀌면 TTL 이 남아 있어도 버린다 (#1279).
# 액션만 고치고 여기를 두면 같은 화면에서 액션은 새 보유, 히어로 합계는 옛 보유가 되어
# **패널 간 모순**이 생긴다 — 균일하게 낡은 것보다 나쁘다.
_cache: dict = {"data": None, "timestamp": 0, "version": None}
CACHE_TTL = 300  # 5분
# single-flight — TTL 만료 시 동시 요청이 전부 재계산하는 걸 막는다 (#1119)
_lock = threading.Lock()


def _fresh(cache: dict, now: float, version: str) -> bool:
    """TTL **과** 포트폴리오 버전을 함께 본다 (#1279). actions.py 와 같은 계약."""
    return bool(cache["data"]) and (now - cache["timestamp"]) < CACHE_TTL and cache["version"] == version


@router.get("/dashboard", dependencies=[Depends(heavy_slot)])
def get_dashboard():
    """오늘의 투자 판단 요약 — DB 조회 전용 (projection 기반)."""
    now = time.time()
    # 버전은 빌드 **전에** 읽는다 — 사유는 `nuri/api/cache.py` 및 actions.py 참조.
    version = portfolio_version()
    if _fresh(_cache, now, version):
        return _cache["data"]

    with _lock:
        # double-check — 락을 기다리는 동안 다른 요청이 채웠을 수 있다
        now = time.time()
        if _fresh(_cache, now, version):
            return _cache["data"]
        result = _build_dashboard()
        _cache["data"] = result
        _cache["timestamp"] = now
        _cache["version"] = version
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
    # stale gate (#1180, Surface rung): 판단 입력(config/freshness.yaml verdict_gate)이
    # FAIL 이면 "공격 가능" 류 판단을 내지 않는다 — 4일 낡은 가격 위의 판단은 판단이 아니다.
    # 데이터(actions/alerts/...)는 그대로 내려보내고 한 줄 판단만 stale 안내로 바꾼다.
    verdict_stale_inputs = _get_stale_verdict_inputs()
    trend = regime_data.get("trend", "unknown")
    macro_score = macro_data["score"]
    n_buys = len([a for a in actions if a["action"] == "BUY"])
    n_sells = len([a for a in actions if a["action"] == "SELL"])

    if verdict_stale_inputs:
        labels = ", ".join(
            f"{s['label']} {s['age_hours']:.0f}h" if s["age_hours"] is not None else s["label"]
            for s in verdict_stale_inputs
        )
        verdict = f"판단 보류. 입력 데이터 낡음 ({labels}) — 재수집 후 판단하세요."
        verdict_level = "stale"
    elif trend == "bear" or macro_score < 35:
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

    # ── 9. 향후 이벤트 ──
    upcoming_events = _get_upcoming_events()

    # ── 10. 계좌 라벨 매핑 (raw broker → 익명화 label) ──
    # account_labels: 모든 raw 계좌명 → 익명 라벨 (중복-ticker per-account 식별용, #199 fix)
    # ticker_accounts: ticker → label (단일 mapping, backward compat)
    account_labels_map = _get_account_labels()
    ticker_accounts = {t: account_labels_map.get(acc, acc) for t, acc in _get_ticker_account_map().items()}

    # ── 11. Cash + 실제 자산 배분 (#213) ──
    # `allocation`은 regime **권장** 비율 (legacy). `actual_allocation`은 현재 portfolio의
    # holdings + cash로 계산한 **실제** 비율. Hero의 총 자산도 cash 포함.
    cash_summary = _get_cash_balances(exchange_rate)
    actual_allocation = _compute_actual_allocation(account_values, cash_summary["total_cash_usd"])

    return {
        "verdict": verdict,
        "verdict_level": verdict_level,
        # stale gate 근거 — 어떤 입력이 얼마나 낡아 판단이 보류됐는지 (빈 리스트 = 게이트 통과)
        "verdict_stale_inputs": verdict_stale_inputs,
        "regime": regime_data,
        "macro": macro_data,
        "allocation": allocation,  # target (regime 권장) — legacy 이름, backward compat
        "target_allocation": allocation,  # explicit 이름 — regime 권장 비율
        "actual_allocation": actual_allocation,  # 현재 portfolio 실제 비율 (holdings + cash)
        "cash_summary": cash_summary,  # 계좌별 cash + 총 cash USD
        "actions": actions,
        "alerts": alerts,
        "gate_score": gate_score,
        "n_positions": len(query("SELECT 1 FROM positions WHERE status='open'")),
        "freshness": freshness,
        "pipeline_status": pipeline_status,
        "exchange_rate": exchange_rate,
        "account_values": account_values,
        "upcoming_events": upcoming_events,
        "ticker_accounts": ticker_accounts,
        "account_labels": account_labels_map,
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
        # coverage 를 같이 내보낸다 — 68% 짜리 점수가 100% 인 척 보이면 안 된다 (#1026).
        return {"score": round(m.total_score), "interpretation": m.interpretation, "coverage": m.coverage}
    except Exception as e:
        logger.warning(f"Macro score 계산 실패 — 미측정으로 표기: {e}")
    # ⚠️ 여기 `score: 50` 은 **측정값이 아니라 스키마 자리표시자**다. 프론트가 숫자 필드를
    # 요구해서 남겨 둘 뿐이고, 판별은 `coverage == 0` / `interpretation` 으로 한다.
    # 예전엔 "Neutral" 이라 적어 실패가 정상 판독으로 둔갑했다.
    return {"score": 50, "interpretation": "Unavailable", "coverage": 0.0}


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


def _parse_json_field(raw: str | None) -> dict | list | None:
    """A-2b: `scoring_detail` / `agent_verdicts` 컬럼 JSON 파싱.

    Parse 실패 또는 NULL → None 반환 (frontend 가 null-check 로 graceful degrade).
    dict (scoring_detail) 또는 list (agent_verdicts) 둘 다 수용.
    """
    if not raw:
        return None
    import json

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


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
    """계좌명 → 표시 라벨 매핑.

    Resolution order (#214 polish):
      1. `label` field in portfolio.yaml (user custom, e.g. "Brokerage Alpha" or "Brokerage Beta")
      2. strategy-based default ("core" → "Main", "swing" → "Sub", ...)
      3. strategy name title-cased if unknown

    Custom labels let the user put whatever they want **in their own gitignored
    portfolio.yaml** — personal names never enter the code or git history.
    """
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
            info = info or {}
            # (1) user custom `label` wins — bypasses duplicate-suffix logic
            custom_label = info.get("label")
            if isinstance(custom_label, str) and custom_label.strip():
                labels[acc] = custom_label.strip()
                continue
            # (2) strategy-based default with duplicate-count suffix
            # Pylance type narrow — info.get()는 Any, 명시적 str coerce 로 dict.get 시그니처 만족.
            strategy_name = str(info.get("strategy") or "core")
            base_label = _STRATEGY_LABELS.get(strategy_name, strategy_name.title())
            count = seen.get(base_label, 0)
            seen[base_label] = count + 1
            labels[acc] = base_label if count == 0 else f"{base_label} {count + 1}"
        return labels
    except Exception:
        return {}


def _get_latest_actions() -> list[dict]:
    """recommendations 테이블에서 최신 추천 조회 — analyze_portfolio() 대체.

    PR B (codex #2): alpha-native read path. SELL 카드는 `alpha_action=="FLAT"`
    명시 또는 pre-migration legacy SELL (back-compat) 만 surface. 이전엔 `action
    == "SELL"` 단독 검사 — concentration-only SELL 이 writer 에서 누출되면 UI
    까지 전파됐음. PR A actions.py 와 동일 semantic 적용 (shared helper).
    """
    from nuri.core.axis import is_alpha_flat_sell, is_alpha_long_buy
    from nuri.core.db import query
    from nuri.core.ticker_names import get_ticker_name

    try:
        rows = query("""
            SELECT r.ticker, r.action, r.confidence, r.regime, r.signals, r.date,
                   r.scoring_detail, r.agent_verdicts, r.alpha_action, r.portfolio_action,
                   r.date AS as_of, d.id AS decision_id
            FROM recommendations r
            -- 증거 체인 연결 (#1182) — actions.py 와 동일 계약 (same-date UNIQUE JOIN)
            LEFT JOIN decisions d ON d.date = r.date AND d.ticker = r.ticker
            -- emitter 행 제외 — 이 카드는 합의 결과다 (#1078).
            WHERE r.source IS NULL
              AND r.date = (SELECT MAX(date) FROM recommendations WHERE source IS NULL)
            ORDER BY r.confidence DESC
        """)
        if not rows:
            return []

        ticker_account = _get_ticker_account_map()
        account_labels = _get_account_labels()

        actions = []
        for row in rows:
            action = row["action"]
            alpha_action = row.get("alpha_action")
            portfolio_action = row.get("portfolio_action")
            confidence = (
                round(row["confidence"] * 100)
                if row["confidence"] and row["confidence"] <= 1
                else round(row["confidence"] or 0)
            )
            reason, agreement_rate = _extract_reason(row.get("signals"))
            raw_account = ticker_account.get(row["ticker"], "")
            account_label = account_labels.get(raw_account, raw_account)
            # A-2b: scoring_detail + agent_verdicts JSON 파싱. source=consensus/candidate
            # 로 discriminate (PR #364/#366 스키마). Parse 실패는 None 로 graceful degrade.
            scoring_detail = _parse_json_field(row.get("scoring_detail"))
            agent_verdicts = _parse_json_field(row.get("agent_verdicts"))

            if is_alpha_long_buy(alpha_action, action) and confidence >= 50:
                actions.append(
                    {
                        "action": "BUY",
                        "alpha_action": alpha_action,
                        "portfolio_action": portfolio_action,
                        "ticker": row["ticker"],
                        "name": get_ticker_name(row["ticker"]),
                        "confidence": confidence,
                        "reason": reason,
                        "agreement": round(agreement_rate * 100) if agreement_rate is not None else None,
                        "account": account_label,
                        "scoring_detail": scoring_detail,
                        "agent_verdicts": agent_verdicts,
                        # #1182: 증거 체인 링크 + 판정 기준일
                        "decision_id": row.get("decision_id"),
                        "as_of": row.get("as_of"),
                    }
                )
            elif is_alpha_flat_sell(alpha_action, action) and confidence >= 70:
                actions.append(
                    {
                        "action": "SELL",
                        "alpha_action": alpha_action,
                        "portfolio_action": portfolio_action,
                        "ticker": row["ticker"],
                        "name": get_ticker_name(row["ticker"]),
                        "confidence": confidence,
                        "reason": reason,
                        "agreement": round(agreement_rate * 100) if agreement_rate is not None else None,
                        "account": account_label,
                        "scoring_detail": scoring_detail,
                        "agent_verdicts": agent_verdicts,
                        # #1182: 증거 체인 링크 + 판정 기준일
                        "decision_id": row.get("decision_id"),
                        "as_of": row.get("as_of"),
                    }
                )

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
    from nuri.core.ticker_names import is_kr_ticker

    totals: dict[str, float] = {}
    for r in rows:
        acc = r["account"]
        price = r["latest_price"] or 0
        qty = r["quantity"] or 0
        is_kr = is_kr_ticker(r["ticker"])
        val = price * qty / rate if is_kr else price * qty
        totals[acc] = totals.get(acc, 0) + val

    account_labels = _get_account_labels()
    return [
        {"account": account_labels.get(acc, acc), "value": round(v, 2)}
        for acc, v in sorted(totals.items(), key=lambda x: -x[1])
    ]


def _get_cash_balances(exchange_rate: float | None = None) -> dict:
    """portfolio.yaml의 계좌별 cash 잔액을 USD로 환산 합산 (#213).

    Returns:
        {
            "accounts": [
                {"account": "<label>", "cash_usd": N, "cash_krw": N, "total_usd": N},
                ...
            ],
            "total_cash_usd": N,
        }

    portfolio.yaml의 각 계좌 레벨 `cash_usd` / `cash_krw` 필드가 있을 때 합산한다.
    환율 누락 시 1400 기본값 (기존 dashboard 로직과 일치).
    broker 이름은 노출하지 않고 `_get_account_labels()`의 익명 라벨로 치환한다.
    """
    from pathlib import Path

    import yaml

    portfolio_path = Path(__file__).parent.parent.parent.parent / "config" / "portfolio.yaml"
    try:
        with open(portfolio_path, encoding="utf-8") as f:
            portfolio = yaml.safe_load(f) or {}
    except Exception as e:
        logger.debug("portfolio.yaml cash read failed: %s", e)
        return {"accounts": [], "total_cash_usd": 0.0}

    rate = exchange_rate or 1400.0
    labels = _get_account_labels()
    accounts_out: list[dict] = []
    total_usd = 0.0

    for raw_acc, info in (portfolio.get("accounts") or {}).items():
        if not isinstance(info, dict):
            continue
        cash_usd = float(info.get("cash_usd") or 0)
        cash_krw = float(info.get("cash_krw") or 0)
        acc_total = cash_usd + (cash_krw / rate if rate > 0 else 0)
        if acc_total <= 0:
            continue
        accounts_out.append(
            {
                "account": labels.get(raw_acc, raw_acc),
                "cash_usd": round(cash_usd, 2),
                "cash_krw": round(cash_krw, 2),
                "total_usd": round(acc_total, 2),
            }
        )
        total_usd += acc_total

    return {"accounts": accounts_out, "total_cash_usd": round(total_usd, 2)}


def _compute_actual_allocation(account_values: list[dict], cash_total_usd: float) -> dict:
    """실제 포트폴리오 구성 비율 — holdings vs cash (USD 기준, #213).

    `_get_allocation()`은 regime이 권장하는 **target** 비율을 반환하는 반면
    이 함수는 현재 portfolio의 **actual** 구성 비율을 계산한다.

    Returns:
        {"long": 46, "short": 0, "cash": 54}  — 백분율, 합 100
    """
    holdings_usd = sum(av.get("value", 0) for av in account_values)
    total = holdings_usd + cash_total_usd
    if total <= 0:
        return {"long": 0, "short": 0, "cash": 100}
    long_pct = round((holdings_usd / total) * 100)
    cash_pct = 100 - long_pct  # 반올림 오차는 cash 쪽으로 흡수
    return {"long": long_pct, "short": 0, "cash": cash_pct}


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
            alerts.append(
                {
                    "level": "critical",
                    "message": f"포트폴리오 손절선 돌파 (MDD {risk['max_drawdown_pct']:.1f}%)",
                }
            )
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


def _get_upcoming_events() -> list[dict]:
    """향후 14일 이내 주요 이벤트 조회."""
    from datetime import timedelta

    from nuri.core.db import query
    from nuri.core.timezone import kst_now

    now = kst_now()
    today_str = now.strftime("%Y-%m-%d")
    end_str = (now + timedelta(days=14)).strftime("%Y-%m-%d")
    try:
        rows = query(
            "SELECT date, event_type, ticker, description, importance "
            "FROM events WHERE date >= ? AND date <= ? "
            "ORDER BY date, importance DESC LIMIT 10",
            (today_str, end_str),
        )
        return [dict(r) for r in rows]
    except Exception:
        return []


def _get_freshness() -> dict:
    """데이터 신선도 요약.

    키는 `d["key"]` 다 — `d["table"]` 로 읽던 시절엔 KeyError 가 except 에 먹혀
    이 함수가 **항상 빈 dict** 를 조용히 반환했다 (#1180). 회귀 잠금:
    tests/api/test_dashboard.py::TestDashboardFreshness.
    """
    try:
        from nuri.core.freshness import check_all_freshness

        details = check_all_freshness()
        return {d["key"]: {"age_hours": d["age_hours"], "status": d["status"]} for d in details}
    except Exception as e:
        logger.debug(f"Freshness: {e}")
        return {}


def _get_stale_verdict_inputs() -> list[dict]:
    """verdict gate 입력 중 FAIL 만 — 실패 시 빈 리스트 (관측이 판단을 죽이면 안 됨, #894)."""
    try:
        from nuri.core.freshness import stale_verdict_inputs

        return [
            {"key": s["key"], "label": s["label"], "age_hours": s["age_hours"], "last_updated": s["last_updated"]}
            for s in stale_verdict_inputs()
        ]
    except Exception as e:
        logger.debug(f"Verdict stale gate: {e}")
        return []


def _get_pipeline_status() -> dict:
    """파이프라인 6단계 최신 실행 상태."""
    try:
        from nuri.core.events import get_pipeline_status

        return get_pipeline_status()
    except Exception as e:
        logger.debug(f"Pipeline status: {e}")
        return {}

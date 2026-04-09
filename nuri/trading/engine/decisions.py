"""Decision Intelligence — 의사결정 기록 + 결과 추적 + 학습 루프.

멱등성(Idempotency):
  - record_decision(): 같은 날 같은 티커 → UPDATE (INSERT OR REPLACE on UNIQUE(date, ticker))
  - track_decision_outcomes(): NULL인 슬롯만 채움, 한번 기록된 PnL은 불변
  - 재실행해도 데이터 무결성 유지

사용:
    from nuri.trading.engine.decisions import record_decision, track_decision_outcomes
"""
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def record_decision(consensus_result, db_path=None) -> int:
    """ConsensusResult를 decisions 테이블에 멱등 기록.

    시장 컨텍스트(regime, macro_score, event_score, VIX, F&G)를
    의사결정 시점에 스냅샷하여 저장. Lineage 역추적의 기반.

    Args:
        consensus_result: ConsensusResult 객체 (ticker, final_action, confidence, verdicts 등)
        db_path: 테스트용 DB 경로

    Returns:
        decision id (int)
    """
    from nuri.core.db import query, upsert_decision, upsert_decision_evidence
    from nuri.core.timezone import today_kst

    today = today_kst()
    ticker = consensus_result.ticker

    # 현재가 조회
    price_row = query(
        "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        (ticker,), db_path,
    )
    entry_price = price_row[0]["close"] if price_row else 0.0

    # 시장 컨텍스트 스냅샷
    context = _snapshot_market_context(db_path)

    # agent_verdicts JSON
    verdicts_json = json.dumps(
        [
            {
                "agent_name": v.agent_name,
                "ticker": v.ticker,
                "action": v.action,
                "confidence": v.confidence,
                "reasoning": v.reasoning,
                "data_points": v.data_points,
            }
            for v in consensus_result.verdicts
        ],
        ensure_ascii=False,
    )

    # 가격 타겟 조회
    targets = _get_price_targets(ticker, entry_price, db_path)

    decision_data = {
        "date": today,
        "ticker": ticker,
        "action": consensus_result.final_action,
        "confidence": consensus_result.final_confidence,
        "regime": context.get("regime"),
        "macro_score": context.get("macro_score"),
        "event_score": context.get("event_score"),
        "vix": context.get("vix"),
        "fear_greed": context.get("fear_greed"),
        "agent_verdicts": verdicts_json,
        "agreement_rate": consensus_result.agreement_rate,
        "dissent": json.dumps(consensus_result.dissent, ensure_ascii=False),
        "reasoning": consensus_result.reasoning,
        "entry_price": entry_price,
        "stop_loss": targets.get("stop_loss"),
        "target_1": targets.get("target_1"),
        "target_2": targets.get("target_2"),
    }

    decision_id = upsert_decision(decision_data, db_path)

    # Evidence chain: 각 에이전트 verdict를 별도 evidence로 기록
    evidence_records = [
        {
            "source_type": "agent",
            "source_key": v.agent_name,
            "action": v.action,
            "confidence": v.confidence,
            "detail": json.dumps(v.data_points, ensure_ascii=False),
        }
        for v in consensus_result.verdicts
    ]

    # 시장 컨텍스트도 evidence로 기록
    if context.get("regime"):
        evidence_records.append({
            "source_type": "regime",
            "source_key": "current",
            "action": None,
            "confidence": None,
            "detail": json.dumps(context, ensure_ascii=False),
        })

    upsert_decision_evidence(decision_id, evidence_records, db_path)

    logger.info(f"Decision recorded: {ticker} {consensus_result.final_action} "
                f"(conf={consensus_result.final_confidence:.0f}, id={decision_id})")
    return decision_id


def record_decisions(results: list, db_path=None) -> int:
    """여러 ConsensusResult를 일괄 기록. 멱등."""
    count = 0
    for r in results:
        record_decision(r, db_path)
        count += 1
    return count


def track_decision_outcomes(db_path=None) -> int:
    """과거 decisions의 7/30/60/90일 P&L 자동 업데이트.

    멱등성: NULL인 슬롯만 채움. 이미 기록된 값은 변경하지 않음.
    """
    from nuri.core.db import get_db, query
    from nuri.core.timezone import kst_now

    now = kst_now().replace(tzinfo=None)
    updated = 0

    pending = query(
        "SELECT id, date, ticker, action, entry_price, pnl_7d, pnl_30d, pnl_60d, pnl_90d "
        "FROM decisions WHERE entry_price > 0 AND outcome = 'pending'",
        db_path=db_path,
    )

    for dec in pending:
        dec_date = datetime.strptime(dec["date"], "%Y-%m-%d")
        elapsed = (now - dec_date).days
        ticker = dec["ticker"]
        entry = dec["entry_price"]

        updates = {}

        for days, col in [(7, "pnl_7d"), (30, "pnl_30d"), (60, "pnl_60d"), (90, "pnl_90d")]:
            if elapsed >= days and dec[col] is None:
                target_date = (dec_date + timedelta(days=days)).strftime("%Y-%m-%d")
                price = query(
                    "SELECT close FROM prices WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT 1",
                    (ticker, target_date), db_path,
                )
                if price and entry > 0:
                    ret = (price[0]["close"] - entry) / entry * 100
                    updates[col] = round(ret, 2)

        # outcome 판정: 90일 경과 시 결정, 아니면 pending 유지
        if "pnl_90d" in updates:
            pnl = updates["pnl_90d"]
            action = dec["action"]
            if action == "BUY":
                updates["outcome"] = "success" if pnl > 0 else "failure"
            elif action == "SELL":
                updates["outcome"] = "success" if pnl < 0 else "failure"
            else:
                updates["outcome"] = "neutral"

        if updates:
            updates["updated_at"] = now.strftime("%Y-%m-%d %H:%M")
            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            updates["id"] = dec["id"]
            with get_db(db_path) as conn:
                conn.execute(f"UPDATE decisions SET {set_clause} WHERE id = :id", updates)
            updated += 1

    return updated


def get_decision_summary(db_path=None) -> dict:
    """의사결정 요약 통계 — 총 건수, 결과별 분포, 에이전트별 적중률."""
    from nuri.core.db import query

    total_rows = query("SELECT COUNT(*) as cnt FROM decisions", db_path=db_path)
    total = total_rows[0]["cnt"] if total_rows else 0

    outcome_rows = query(
        "SELECT outcome, COUNT(*) as cnt FROM decisions GROUP BY outcome",
        db_path=db_path,
    )
    outcomes = {r["outcome"]: r["cnt"] for r in outcome_rows}

    return {
        "total": total,
        "pending": outcomes.get("pending", 0),
        "success": outcomes.get("success", 0),
        "failure": outcomes.get("failure", 0),
        "neutral": outcomes.get("neutral", 0),
    }


def _snapshot_market_context(db_path=None) -> dict:
    """현재 시장 컨텍스트 스냅샷 (regime, macro_score, VIX, F&G 등)."""
    from nuri.core.db import query

    context = {}

    # VIX
    vix_row = query(
        "SELECT value FROM macro WHERE indicator = 'vix' ORDER BY date DESC LIMIT 1",
        db_path=db_path,
    )
    if vix_row:
        context["vix"] = vix_row[0]["value"]

    # Fear & Greed
    fg_row = query(
        "SELECT value FROM macro WHERE indicator = 'fear_greed' ORDER BY date DESC LIMIT 1",
        db_path=db_path,
    )
    if fg_row:
        context["fear_greed"] = fg_row[0]["value"]

    # Regime — pipeline_events에서 최신 regime_changed 이벤트
    regime_row = query(
        "SELECT payload FROM pipeline_events WHERE event_type = 'regime_changed' "
        "ORDER BY timestamp DESC LIMIT 1",
        db_path=db_path,
    )
    if regime_row:
        try:
            payload = json.loads(regime_row[0]["payload"])
            context["regime"] = payload.get("regime", payload.get("new_regime"))
        except (json.JSONDecodeError, TypeError):
            pass

    # Macro score — event_score 포함
    try:
        from nuri.quant.regime.macro_score import compute_macro_score
        ms = compute_macro_score(db_path=db_path)
        context["macro_score"] = ms.total_score
        context["event_score"] = ms.event_score
    except Exception:
        pass

    return context


def _get_price_targets(ticker: str, entry_price: float, db_path=None) -> dict:
    """가격 타겟 조회. price_targets 모듈 사용."""
    if entry_price <= 0:
        return {}
    try:
        from nuri.trading.recommend.price_targets import calculate_targets
        return calculate_targets(ticker, entry_price=entry_price, db_path=db_path)
    except Exception:
        return {}

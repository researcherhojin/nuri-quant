"""Consensus → recommendations table persistence.

`save_to_recommendations` is the only DB-writing function in the consensus
package. Same-day re-runs UPSERT on (date, ticker) to preserve `id` (FKs in
`trades.recommendation_id` would break under DELETE+INSERT).
"""

from __future__ import annotations

import json
import logging

from .models import ConsensusResult

__all__ = ["save_to_recommendations"]

logger = logging.getLogger(__name__)


def save_to_recommendations(results: list[ConsensusResult], db_path=None) -> int:
    """ConsensusResult를 recommendations 테이블에 INSERT.

    이전: `make consensus`는 stdout만 출력하고 DB에 저장하지 않아 frontend
    /decision 페이지가 빈 상태로 표시되었음 (routing failure).
    이제 합의 직후 자동 저장하여 evidence trail 연속성 보장.

    중복 방지: (date, ticker) 같은 날 재실행 시 INSERT OR REPLACE.
    """
    from nuri.core.db import get_db, query
    from nuri.core.timezone import today_kst

    if not results:
        return 0

    today = today_kst()

    # PR A: regime 을 한 번 classify 해 배치 전체에 공유 (codex Q3 권고 — per-ticker
    # classify 는 ~30ms × N 추가 latency). 실패 시 None 으로 폴백 (legacy 동작 유지).
    # #832: canonical ALL_REGIMES 값만 저장 — free-text 유입 시 NULL 로 정규화.
    batch_regime: str | None = None
    try:
        from nuri.quant.regime.classifier import canonical_regime_or_none, classify_regime

        rr = classify_regime(db_path=db_path)
        if rr is not None:
            batch_regime = canonical_regime_or_none(rr.regime)
    except Exception:
        logger.debug("save_to_recommendations: regime classify 실패, NULL 유지", exc_info=True)

    records = []
    for r in results:
        # 모든 final_action (BUY/SELL/HOLD) persist — same-day 재실행 시 UPSERT 로 stale
        # row 방지 (codex A-1 review P1-1). Learning Memory 는 개별 agent verdict 의
        # action 으로 hit 판정하므로 rec.final_action=HOLD 라도 verdicts 배열 내 BUY/SELL
        # 은 학습 대상. _compute_weights 의 action 분기가 HOLD 를 자동 skip.
        # 현재가 조회
        price_row = query(
            "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (r.ticker,),
            db_path=db_path,
        )
        entry_price = price_row[0]["close"] if price_row else 0.0

        verdicts_json = json.dumps(
            [
                {
                    "agent_name": v.agent_name,
                    "ticker": v.ticker,
                    "action": v.action,
                    "confidence": v.confidence,
                    "reasoning": v.reasoning,
                    "data_points": v.data_points,
                    "alpha_action": v.alpha_action,
                    "portfolio_action": v.portfolio_action,
                }
                for v in r.verdicts
            ],
            ensure_ascii=False,
        )

        # Phase 2 A-2a: scoring_detail persist. _build_consensus 가 채웠지만 legacy
        # 호출자가 직접 ConsensusResult 를 만들 수 있어 None 방어. `is not None`
        # 사용해 빈 dict `{}` 는 persist (codex A-2a review P3 — falsy 실수 방지).
        scoring_detail_json = json.dumps(r.scoring_detail, ensure_ascii=False) if r.scoring_detail is not None else None

        # PR A: consensus 결과를 portfolio/alpha axis 로 surface. 현재 consensus
        # 는 BUY/SELL/HOLD 만 emit 하므로 단순 derive — risk_v 가 portfolio_action
        # 을 채웠으면 그대로 노출, 아니면 None. alpha_action 은 final_action 에서
        # derive (LONG/SHORT/FLAT 이 아닌 None 은 "신호 없음" 의미; HOLD 는 alpha
        # axis 중립 = None).
        risk_verdict = next((v for v in r.verdicts if v.agent_name == "risk"), None)
        portfolio_action = risk_verdict.portfolio_action if risk_verdict is not None else None
        if r.final_action == "BUY":
            alpha_action: str | None = "LONG"
        elif r.final_action == "SELL":
            alpha_action = "FLAT"
        else:
            alpha_action = None  # HOLD — alpha 중립

        records.append(
            {
                "date": today,
                "ticker": r.ticker,
                "action": r.final_action,
                "confidence": r.final_confidence,
                "regime": batch_regime,  # PR A: 배치 1회 classify 결과 공유
                "signals": json.dumps(
                    {
                        "agreement_rate": r.agreement_rate,
                        "dissent_count": len(r.dissent),
                        "reasoning": r.reasoning,
                    }
                ),
                "entry_price": entry_price,
                "agent_verdicts": verdicts_json,
                "scoring_detail": scoring_detail_json,
                "alpha_action": alpha_action,
                "portfolio_action": portfolio_action,
            }
        )

    with get_db(db_path) as conn:
        # 같은 날 같은 종목 재실행 시 UPSERT — id 보존 (trades.recommendation_id FK 안전).
        # INSERT OR REPLACE 는 DELETE+INSERT 라 id 바뀌어 FK 참조 끊김 위험.
        conn.executemany(
            """INSERT INTO recommendations
               (date, ticker, action, confidence, regime, signals, entry_price,
                agent_verdicts, scoring_detail, alpha_action, portfolio_action)
               VALUES (:date, :ticker, :action, :confidence, :regime, :signals, :entry_price,
                       :agent_verdicts, :scoring_detail, :alpha_action, :portfolio_action)
               ON CONFLICT(date, ticker) DO UPDATE SET
                   action = excluded.action,
                   confidence = excluded.confidence,
                   regime = excluded.regime,
                   signals = excluded.signals,
                   entry_price = excluded.entry_price,
                   agent_verdicts = excluded.agent_verdicts,
                   scoring_detail = excluded.scoring_detail,
                   alpha_action = excluded.alpha_action,
                   portfolio_action = excluded.portfolio_action,
                   -- 내용을 합의가 덮었으면 라벨도 합의 것이다. emitter 가 먼저 앉은
                   -- `(date, ticker)` 를 덮을 때 `source` 만 남겨두면 그 행이 `source IS
                   -- NULL` 읽기 경로 전체에서 사라진다 — §3.11 판정 표본 포함 (#1078).
                   source = NULL""",
            records,
        )
        return len(records)

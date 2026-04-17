"""
E-3: 추천 추적기 — 추천 저장 + 성과 추적.

E-1 후보 + E-2 리밸런싱 결과를 DB에 저장하고,
30/60/90일 후 실제 수익률과 비교하여 시스템 적중률을 측정한다.

사용법:
    python -m nuri.trading.recommend.tracker --save      # 오늘 추천 저장 + 과거 추적
    python -m nuri.trading.recommend.tracker              # 추적 리포트만
"""
import argparse
import json
import logging
from datetime import datetime, timedelta

from nuri.core.db import get_db, query

logger = logging.getLogger(__name__)


def _serialize_verdicts(consensus_results) -> dict[str, list[dict]]:
    """ConsensusResult 리스트 → {ticker: [verdict_dict, ...]} 변환.

    각 verdict에서 agent_name, action, confidence, reasoning (100자 제한)을 추출.
    """
    verdicts_map: dict[str, list[dict]] = {}
    for result in consensus_results:
        ticker_verdicts = []
        for v in result.verdicts:
            ticker_verdicts.append({
                "agent_name": v.agent_name,
                "action": v.action,
                "confidence": round(v.confidence, 1),
                "reasoning": v.reasoning[:100] if v.reasoning else "",
            })
        verdicts_map[result.ticker] = ticker_verdicts
    return verdicts_map


def save_recommendations(candidates=None, actions=None, verdicts=None, db_path=None) -> int:
    """E-1 후보 + E-2 액션을 recommendations 테이블에 저장.

    Args:
        candidates: E-1 후보 리스트
        actions: E-2 리밸런싱 액션 리스트
        verdicts: 에이전트 verdict 딕셔너리 {ticker: [verdict_dict, ...]}
        db_path: DB 경로 (테스트용)
    """
    from nuri.core.timezone import today_kst
    from nuri.trading.recommend.candidates import TIER_ACTIONABLE

    today = today_kst()
    records = []

    # E-1 후보에서 regime_fit + actionable tier 인 것만.
    # CLI 경로 (__main__) 는 이미 actionable 필터 후 호출하지만 다른 caller (테스트/
    # 내부 script) 가 advisory/avoid 를 섞어 persist 하는 것을 방어 (codex A-1 review).
    if candidates:
        for c in candidates:
            if not c.regime_fit:
                continue
            if getattr(c, "tier", TIER_ACTIONABLE) != TIER_ACTIONABLE:
                continue
            rec = {
                "date": today,
                "ticker": c.ticker,
                "action": c.direction,
                "confidence": c.confidence,
                "regime": "",
                "signals": json.dumps([c.signal_id]),
                "entry_price": c.price,
            }
            # 에이전트 verdict 첨부
            if verdicts and c.ticker in verdicts:
                rec["agent_verdicts"] = json.dumps(verdicts[c.ticker], ensure_ascii=False)
            # scoring_detail 첨부. A-2b-pre: `is not None` 로 guard 해 빈 dict `{}`
            # 도 persist — consensus.py A-2a 수정과 동일 semantic (codex A-2a Round 2
            # P3 연장선, falsy 실수 방지).
            if hasattr(c, "scoring_detail") and c.scoring_detail is not None:
                rec["scoring_detail"] = json.dumps(c.scoring_detail, ensure_ascii=False)
            records.append(rec)

    # E-2 액션에서 BUY/SELL만
    if actions:
        for a in actions:
            if a.action in ("HOLD",):
                continue
            # 이미 같은 ticker+action이 있으면 건너뜀
            existing = [r for r in records if r["ticker"] == a.ticker and r["action"] == a.action]
            if existing:
                # 시그널 정보 병합
                existing[0]["signals"] = json.dumps(
                    json.loads(existing[0]["signals"]) + a.signals
                )
                continue

            # 현재 가격 조회
            price_row = query(
                "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
                (a.ticker,), db_path=db_path,
            )
            price = price_row[0]["close"] if price_row else 0

            rec = {
                "date": today,
                "ticker": a.ticker,
                "action": a.action,
                "confidence": 50.0,  # 리밸런싱 기반은 기본 50
                "regime": a.regime_note,
                "signals": json.dumps(a.signals),
                "entry_price": price,
            }
            # 에이전트 verdict 첨부 (E-2 액션에도)
            if verdicts and a.ticker in verdicts:
                rec["agent_verdicts"] = json.dumps(verdicts[a.ticker], ensure_ascii=False)
            records.append(rec)

    if not records:
        return 0

    with get_db(db_path) as conn:
        conn.executemany(
            """INSERT OR IGNORE INTO recommendations
               (date, ticker, action, confidence, regime, signals, entry_price,
                agent_verdicts, scoring_detail)
               VALUES (:date, :ticker, :action, :confidence, :regime, :signals, :entry_price,
                       :agent_verdicts, :scoring_detail)""",
            # 누락된 키에 대해 기본값 None 보장
            [{**{"agent_verdicts": None, "scoring_detail": None}, **r} for r in records],
        )
        return len(records)


def track_outcomes(db_path=None) -> int:
    """과거 추천의 30/60/90일 수익률을 업데이트."""
    from nuri.core.timezone import kst_now

    # naive datetime으로 통일 (DB 날짜는 naive)
    now = kst_now().replace(tzinfo=None)
    updated = 0

    # 아직 추적 안 된 추천 조회
    recs = query(
        "SELECT id, date, ticker, action, entry_price FROM recommendations "
        "WHERE entry_price > 0 AND (outcome_30d IS NULL OR outcome_60d IS NULL OR outcome_90d IS NULL)",
        db_path=db_path,
    )

    for rec in recs:
        rec_date = datetime.strptime(rec["date"], "%Y-%m-%d")
        elapsed = (now - rec_date).days
        ticker = rec["ticker"]
        entry = rec["entry_price"]

        updates = {}

        # 30일 추적
        if elapsed >= 30 and rec.get("outcome_30d") is None:
            target = (rec_date + timedelta(days=30)).strftime("%Y-%m-%d")
            price = query(
                "SELECT close FROM prices WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT 1",
                (ticker, target), db_path=db_path,
            )
            if price and entry > 0:
                ret = (price[0]["close"] - entry) / entry * 100
                updates["outcome_30d"] = round(ret, 2)

        # 60일 추적
        if elapsed >= 60 and rec.get("outcome_60d") is None:
            target = (rec_date + timedelta(days=60)).strftime("%Y-%m-%d")
            price = query(
                "SELECT close FROM prices WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT 1",
                (ticker, target), db_path=db_path,
            )
            if price and entry > 0:
                ret = (price[0]["close"] - entry) / entry * 100
                updates["outcome_60d"] = round(ret, 2)

        # 90일 추적
        if elapsed >= 90 and rec.get("outcome_90d") is None:
            target = (rec_date + timedelta(days=90)).strftime("%Y-%m-%d")
            price = query(
                "SELECT close FROM prices WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT 1",
                (ticker, target), db_path=db_path,
            )
            if price and entry > 0:
                ret = (price[0]["close"] - entry) / entry * 100
                updates["outcome_90d"] = round(ret, 2)

        # hit 판정 (30일 기준): 의미 있는 수익만 적중으로 인정
        # BUY: +5% 이상 (성장 +20% 목표의 25%), SELL: -2% 이하 (의미 있는 하락 회피)
        if "outcome_30d" in updates:
            action = rec["action"]
            ret30 = updates["outcome_30d"]
            if action == "BUY":
                updates["hit"] = ret30 >= 5.0
                # hit_quality: 목표 수익률(+20%) 대비 달성 비율 (0.0~1.0+)
                updates["hit_quality"] = round(ret30 / 20.0, 3) if ret30 > 0 else 0.0
            else:
                updates["hit"] = ret30 < -2.0
                # SELL hit_quality: 하락폭 대비 회피 효과 (기대 손실 -10% 기준)
                updates["hit_quality"] = round(abs(ret30) / 10.0, 3) if ret30 < 0 else 0.0

        if updates:
            updates["tracked_at"] = now.strftime("%Y-%m-%d %H:%M")
            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            updates["id"] = rec["id"]
            with get_db(db_path) as conn:
                conn.execute(f"UPDATE recommendations SET {set_clause} WHERE id = :id", updates)
            updated += 1

    return updated


def get_tracking_report(db_path=None) -> dict:
    """추적 리포트 데이터 생성."""
    total = query("SELECT COUNT(*) as c FROM recommendations", db_path=db_path)
    total_count = total[0]["c"] if total else 0

    tracked = query(
        "SELECT COUNT(*) as c FROM recommendations WHERE outcome_30d IS NOT NULL",
        db_path=db_path,
    )
    tracked_count = tracked[0]["c"] if tracked else 0

    hits = query(
        "SELECT COUNT(*) as c FROM recommendations WHERE hit = 1",
        db_path=db_path,
    )
    hit_count = hits[0]["c"] if hits else 0

    # 액션별 통계
    by_action = query(
        """SELECT action,
                  COUNT(*) as total,
                  SUM(CASE WHEN hit = 1 THEN 1 ELSE 0 END) as hits,
                  AVG(outcome_30d) as avg_30d
           FROM recommendations
           WHERE outcome_30d IS NOT NULL
           GROUP BY action""",
        db_path=db_path,
    )

    return {
        "total_recommendations": total_count,
        "tracked": tracked_count,
        "hit_count": hit_count,
        "hit_rate": hit_count / tracked_count if tracked_count > 0 else 0,
        "by_action": by_action,
    }


def print_tracking_report(db_path=None) -> None:
    """추적 리포트 출력."""
    report = get_tracking_report(db_path)

    print(f"\n{'=' * 55}")
    print("  Recommendation Tracking Report")
    print(f"{'=' * 55}")
    print(f"  Total recommendations: {report['total_recommendations']}")
    print(f"  Tracked (30d+):        {report['tracked']}")

    if report["tracked"] > 0:
        print(f"  Hit rate:              {report['hit_rate']:.0%} ({report['hit_count']}/{report['tracked']})")

        if report["by_action"]:
            print(f"\n  {'Action':<8} {'Total':>6} {'Hits':>6} {'Rate':>7} {'Avg30d':>8}")
            print(f"  {'-' * 38}")
            for row in report["by_action"]:
                rate = row["hits"] / row["total"] if row["total"] > 0 else 0
                avg = row["avg_30d"] or 0
                print(f"  {row['action']:<8} {row['total']:>6} {row['hits']:>6} "
                      f"{rate:>6.0%} {avg:>+7.1f}%")
    else:
        print("  아직 추적 가능한 데이터 없음 (30일 대기)")

    # 최근 추천 5건
    recent = query(
        "SELECT date, ticker, action, confidence, entry_price, outcome_30d, hit "
        "FROM recommendations ORDER BY date DESC LIMIT 5",
        db_path=db_path,
    )
    if recent:
        print("\n  Recent:")
        for r in recent:
            outcome = f"{r['outcome_30d']:+.1f}%" if r["outcome_30d"] is not None else "pending"
            hit_mark = "O" if r.get("hit") else ("X" if r.get("hit") is not None else "—")
            print(f"    {r['date']} {r['ticker']:<8} {r['action']:<6} "
                  f"conf={r['confidence']:.0f} ${r['entry_price']:,.2f} → {outcome} [{hit_mark}]")

    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Nuri-Quant 추천 추적기")
    parser.add_argument("--save", action="store_true", help="오늘 추천 저장 + 과거 추적")
    args = parser.parse_args()

    if args.save:
        # E-1 + E-2 실행 후 저장
        from nuri.trading.recommend.candidates import TIER_ACTIONABLE, screen_candidates
        all_candidates = screen_candidates(lookback_days=5)
        # B-2-ext codex P1: advisory/avoid tier 는 "disclosure only" 라 persist
        # 하지 않는다. 정식 추천으로 저장되면 stat 없는 시그널이 history 에 섞여
        # 다음 Learning Memory 재계산에 오염 전파. actionable 만 저장.
        candidates = [c for c in all_candidates if getattr(c, "tier", TIER_ACTIONABLE) == TIER_ACTIONABLE]
        dropped = len(all_candidates) - len(candidates)
        if dropped:
            logger.info(f"후보 {len(all_candidates)}건 중 actionable {len(candidates)}건 저장 "
                        f"(advisory/avoid {dropped}건은 disclosure-only, persist 제외)")
        else:
            logger.info(f"후보 {len(candidates)}건 스크리닝")

        try:
            from nuri.trading.recommend.rebalance import regime_aware_rebalance
            actions = regime_aware_rebalance(method="rp")
            logger.info(f"리밸런싱 {len(actions)}건")
        except Exception as e:
            logger.warning(f"리밸런싱 실패 (건너뜀): {e}")
            actions = None

        n = save_recommendations(candidates, actions)
        logger.info(f"추천 {n}건 저장")

        tracked = track_outcomes()
        logger.info(f"추적 {tracked}건 업데이트")

    print_tracking_report()

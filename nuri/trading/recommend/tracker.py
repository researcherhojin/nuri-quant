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
from nuri.quant.regime.classifier import canonical_regime_or_none

logger = logging.getLogger(__name__)


def _serialize_verdicts(consensus_results) -> dict[str, list[dict]]:
    """ConsensusResult 리스트 → {ticker: [verdict_dict, ...]} 변환.

    각 verdict에서 agent_name, action, confidence, reasoning (100자 제한)을 추출.
    """
    verdicts_map: dict[str, list[dict]] = {}
    for result in consensus_results:
        ticker_verdicts = []
        for v in result.verdicts:
            ticker_verdicts.append(
                {
                    "agent_name": v.agent_name,
                    "action": v.action,
                    "confidence": round(v.confidence, 1),
                    "reasoning": v.reasoning[:100] if v.reasoning else "",
                }
            )
        verdicts_map[result.ticker] = ticker_verdicts
    return verdicts_map


#: `recommendations.source` 에 찍는 emit 경로 라벨. NULL 은 합의 파이프라인(기존 행 전부).
#: §3.11 판정 표본은 사전등록된 모집단을 유지해야 하므로 `decision_alpha.fetch_sample`
#: 이 이 값을 **제외**한다 — 사용자 결정 2026-08-18. 포함으로 바꾸려면 그쪽 필터 한 줄과
#: STRATEGY 기록이 같이 필요하다.
BUY_CANDIDATE_SOURCE = "buy_candidate_emitter"


def save_buy_candidates(result, db_path=None) -> int:
    """`buy_candidate_emitter` 의 EmitResult 를 `recommendations` 에 영속화 (#1078).

    **왜**: 이 emitter 의 실행에는 지금까지 아무것도 남지 않았다. 후보를 발행하고 브리핑에
    렌더한 뒤 `EmitResult` 를 통째로 버렸다. 그래서 tracker 백필 · `decision_outcomes` ·
    `/api/alpha` 까지 이어지는 체인이 이 경로에 대해서만 통째로 비어 있었다.

    행 하나당 `source=BUY_CANDIDATE_SOURCE` 를 찍는다. 합의 파이프라인이 같은 테이블을
    쓰기 때문에 출처가 구분되지 않으면 §3.11 표본을 어느 쪽으로도 정의할 수 없다.

    ⚠️ `recommendations` 는 `UNIQUE(date, ticker)` + `INSERT OR IGNORE` 다. 합의가 07:05 에
    쓴 ticker 를 emitter 가 같은 날(브리핑은 09:00 ET) 다시 내면 **조용히 드롭**된다.
    실제 삽입 수를 `rowcount` 로 재서 드롭을 로그로 남긴다 — 안 그러면 "저장했다" 와
    "저장된 척했다" 가 구분되지 않는다 (`market_data.py:92` 가 같은 이유로 rowcount 를 쓴다).

    Returns: 실제 삽입된 행 수 (드롭 제외).
    """
    from nuri.core.axis import derive_alpha_action
    from nuri.core.timezone import today_kst

    candidates = getattr(result, "candidates", None) or []
    if not candidates:
        return 0

    today = today_kst()

    # 원장에는 **그 결정을 실제로 지배한** 레짐을 적는다 (#1082). 여기서 다시 분류하면
    # 게이트가 본 값과 다른 값이 행에 박힌다 — 프로덕션 실측(2026-08-18)에서
    # emit 은 `recovery`, 저장된 행은 `bull_low_vol` 이었다. 둘 다 canonical 이라
    # `canonical_regime_or_none` 도 못 걸렀고, 원장을 되짚으면 틀린 근거가 나왔다.
    #
    # #1138 로 emitter 도 `classify_regime()` 을 쓰게 되어 두 writer 가 같은 **척도**를
    # 공유한다. 다만 같아진 건 척도지 **시점**이 아니다 — 그래서 재측정이 아니라 소비여야
    # 한다. 두 계열이 한 컬럼에서 실제로 관측되는 자리는 `llm/thesis_query.py` 하나뿐이다
    # (`source` 필터 없이 티커 히스토리를 렌더). 나머지 분석 경로는 전부 `source IS NULL`
    # 로 합의 행만 본다. 덤으로 호출당 14-18ms 를 아낀다.
    #
    # `getattr(result, "regime", None)` 이 아니다: `.candidates` 만 있고 `.regime` 이 없는
    # 객체(예: `held_add.HeldAddResult`)를 넘기면 **결측이 조용히 NULL 로 강등**돼,
    # 이 PR 이 구분하려고 만든 "기록 안 됨" 칸으로 들어간다. 그건 데이터 부재가 아니라
    # 배선 오류이므로 AttributeError 로 터지는 게 맞다 (#894 는 관측이 본 작업을
    # 게이트하지 말라는 규칙이지, 호출 계약 위반을 삼키라는 규칙이 아니다).
    emitted_regime = result.regime
    batch_regime = canonical_regime_or_none(emitted_regime)

    # 컬럼은 canonical 10개 아니면 NULL 이다 (#832). 그래서 "분류 불가"(`unknown`)와
    # "아예 기록 안 됨"이 컬럼에서는 똑같이 NULL 로 보인다. 컬럼의 도메인을 넓히는
    # 대신 사실을 `scoring_detail` 에 남겨 둘을 구분한다.
    #
    # `EmitResult.regime` 의 기본값 `""` 도 그대로 흘려보낸다 — 빈 문자열은 falsy 라
    # 아래 부착 조건에서 걸러진다. 여기서 `or None` 으로 한 번 더 정규화하던 코드는
    # 동작이 같은 중복이었고(뮤테이션으로 확인: 지워도 12/12 초록), 커버리지가 세지
    # 않는 삼항 갈래만 하나 늘렸다.
    #
    # ⚠️ 마커는 **내구적이지 않다**: 합의 경로가 나중에 같은 `(date, ticker)` 를 쓰면
    # `ON CONFLICT DO UPDATE` 가 `scoring_detail` 을 통째로 덮고 `source` 를 NULL 로
    # 되돌린다 (`agents/consensus/persistence.py`, 의도된 동작이고 그쪽 테스트가 잠근다).
    unresolved = None if batch_regime else emitted_regime

    records = []
    for c in candidates:
        records.append(
            {
                "date": today,
                "ticker": c.ticker,
                "action": "BUY",
                "alpha_action": derive_alpha_action("BUY"),
                # portfolio_action 은 NULL — 이건 alpha 축 신호지 포트폴리오 룰이 아니다
                # (#429 축 분리). 집중도/섹터는 REBALANCE 경로에서만 나온다.
                "portfolio_action": None,
                "confidence": c.score,
                "regime": batch_regime,
                "signals": json.dumps(c.sources, ensure_ascii=False),
                "entry_price": c.entry,
                "source": BUY_CANDIDATE_SOURCE,
                # 가격 레벨은 recommendations 에 컬럼이 없다 — 사용자 CLAUDE.md 가 요구하는
                # entry/stop/TP 는 브리핑이 렌더하고, 여기엔 사후 재구성을 위해 남긴다.
                "scoring_detail": json.dumps(
                    {
                        "deploy_pct": c.deploy_pct,
                        "stop": c.stop,
                        "tp1": c.tp1,
                        "tp2": c.tp2,
                        "why_now": c.why_now,
                        # canonical 이 아니어서 regime 컬럼이 NULL 이 된 경우에만 존재.
                        # 값은 emitter 가 실제로 쓴 라벨(보통 `unknown`)이다.
                        **({"regime_unresolved": unresolved} if unresolved else {}),
                    },
                    ensure_ascii=False,
                ),
            }
        )

    with get_db(db_path) as conn:
        cur = conn.executemany(
            """INSERT OR IGNORE INTO recommendations
               (date, ticker, action, alpha_action, portfolio_action,
                confidence, regime, signals, entry_price, source, scoring_detail)
               VALUES (:date, :ticker, :action, :alpha_action, :portfolio_action,
                       :confidence, :regime, :signals, :entry_price, :source, :scoring_detail)""",
            records,
        )
        inserted = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0

    dropped = len(records) - inserted
    if dropped > 0:
        logger.warning(
            "buy candidates %d건 중 %d건이 UNIQUE(date,ticker) 로 드롭됐다 "
            "— 같은 날 합의 파이프라인이 먼저 쓴 ticker 다 (%s)",
            len(records),
            dropped,
            today,
        )
    logger.info("buy candidates %d건 저장 (드롭 %d)", inserted, dropped)
    return inserted


def save_recommendations(candidates=None, actions=None, verdicts=None, db_path=None) -> int:
    """E-1 후보 + E-2 액션을 recommendations 테이블에 저장.

    Args:
        candidates: E-1 후보 리스트
        actions: E-2 리밸런싱 액션 리스트
        verdicts: 에이전트 verdict 딕셔너리 {ticker: [verdict_dict, ...]}
        db_path: DB 경로 (테스트용)

    PR B (codex #2): E-1 candidates + E-2 actions 모두 `alpha_action` 를
    `derive_alpha_action(direction / action)` 으로 채운다. `portfolio_action` 은
    E-1/E-2 scope 에서 설정되지 않음 (concentration 같은 portfolio rule 은
    risk_agent + consensus 경로에서만 emit — PR A) — NULL 유지.

    P0 stale-data fix (#507 audit 2026-04-30): SELL/TRIM/REDUCE action 은
    portfolio.quantity > 0 인 ticker 에만 persist. portfolio.yaml live sync
    누락 / broker 매도 미반영으로 인한 "0 주 ticker SELL 권고" 차단.
    BUY 는 universe scan 이므로 qty 무관 (held 면 candidates emitter 가 add 모드
    에서 처리, 여기서는 신호 path 만 책임).
    """
    from nuri.core.axis import derive_alpha_action
    from nuri.core.timezone import today_kst
    from nuri.trading.recommend.candidates import TIER_ACTIONABLE

    today = today_kst()
    records = []

    # #832: regime 라벨 batch 1회 classify (consensus persistence.py 와 동일 패턴).
    # 기존 E-1 "" / E-2 free-text(regime_note) 유입이 라벨 커버리지 3% 의 원인.
    # canonical ALL_REGIMES 값만 저장, 분류 실패 시 NULL 유지 ('unknown' 금지).
    batch_regime: str | None = None
    try:
        from nuri.quant.regime.classifier import canonical_regime_or_none, classify_regime

        rr = classify_regime(db_path=db_path)
        if rr is not None:
            batch_regime = canonical_regime_or_none(rr.regime)
    except Exception:
        logger.debug("save_recommendations: regime classify 실패, NULL 유지", exc_info=True)

    # held set 한 번만 fetch — SELL/TRIM filter 용. set 검사 O(1).
    held_rows = query(
        "SELECT DISTINCT ticker FROM portfolio WHERE quantity > 0",
        db_path=db_path,
    )
    held: set[str] = {r["ticker"] for r in held_rows}
    sell_actions = {"SELL", "TRIM", "REDUCE"}

    # E-1 후보에서 regime_fit + actionable tier 인 것만.
    # CLI 경로 (__main__) 는 이미 actionable 필터 후 호출하지만 다른 caller (테스트/
    # 내부 script) 가 advisory/avoid 를 섞어 persist 하는 것을 방어 (codex A-1 review).
    if candidates:
        for c in candidates:
            if not c.regime_fit:
                continue
            # A-6: dataclass default 이므로 `c.tier` 는 항상 존재.
            if c.tier != TIER_ACTIONABLE:
                continue
            # P0 fix: SELL on 0-qty ticker 차단 (stale broker state guard).
            if c.direction in sell_actions and c.ticker not in held:
                logger.info("skip SELL on non-held %s (broker sync 후 sweeper 가 정리)", c.ticker)
                continue
            rec = {
                "date": today,
                "ticker": c.ticker,
                "action": c.direction,
                "alpha_action": derive_alpha_action(c.direction),
                "portfolio_action": None,  # E-1 signal-driven — portfolio rule 아님
                "confidence": c.confidence,
                "regime": batch_regime,  # #832: "" 대신 canonical 라벨 (분류 실패 시 NULL)
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
            # P0 fix: SELL on 0-qty 차단 (rebalance 가 0주 ticker 권고하면 안 됨).
            if a.action in sell_actions and a.ticker not in held:
                logger.info("skip rebalance SELL on non-held %s", a.ticker)
                continue
            # 이미 같은 ticker+action이 있으면 건너뜀
            existing = [r for r in records if r["ticker"] == a.ticker and r["action"] == a.action]
            if existing:
                # 시그널 정보 병합
                existing[0]["signals"] = json.dumps(json.loads(existing[0]["signals"]) + a.signals)
                continue

            # 현재 가격 조회
            price_row = query(
                "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
                (a.ticker,),
                db_path=db_path,
            )
            price = price_row[0]["close"] if price_row else 0

            rec = {
                "date": today,
                "ticker": a.ticker,
                "action": a.action,
                "alpha_action": derive_alpha_action(a.action),
                "portfolio_action": None,  # E-2 rebalance 는 legacy 경로. PR C 에서 재분류.
                "confidence": 50.0,  # 리밸런싱 기반은 기본 50
                # #832: regime_note 는 free-text ("[recovery] 비중 축소" 등) 라 regime
                # 컬럼 오염 원인 — canonical batch 라벨로 대체 (note 는 컬럼 미persist).
                "regime": batch_regime,
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
               (date, ticker, action, alpha_action, portfolio_action,
                confidence, regime, signals, entry_price,
                agent_verdicts, scoring_detail)
               VALUES (:date, :ticker, :action, :alpha_action, :portfolio_action,
                       :confidence, :regime, :signals, :entry_price,
                       :agent_verdicts, :scoring_detail)""",
            # 누락된 키에 대해 기본값 None 보장
            [{**{"agent_verdicts": None, "scoring_detail": None}, **r} for r in records],
        )
        return len(records)


# 추적 호라이즌 — short (provisional/readiness) + canonical (30) + extended (60/90).
# 21d 만 _compute_weights_provisional 의 weight source. 7/14 는 readiness/monitoring only.
# 30 은 canonical — Learning Memory hit/hit_quality 판정 기준 (변경 금지).
TRACK_HORIZONS = (7, 14, 21, 30, 60, 90)


# forward-close lookup tolerance — target ± HORIZON_TOLERANCE_DAYS 안에 trading day 있어야 valid.
# 주말+공휴일+간헐 gap 흡수용 작은 window. 너무 크면 codex P2 (delisting → day-1 close 가
# day-21 으로 저장) 재발 — 보수적으로 7일 (한 주 휴장 한도).
HORIZON_TOLERANCE_DAYS = 7


def _forward_close_at_horizon(
    ticker: str,
    entry_date: datetime,
    horizon_days: int,
    db_path=None,
) -> float | None:
    """단일 deterministic forward-close 조회 helper (#468 codex Round 1 #5 + Review P2).

    Rule: entry_date + horizon_days (calendar) 의 ±HORIZON_TOLERANCE_DAYS window 안에
    가장 최근 trading day close. window 밖 (e.g., delisting 으로 horizon 이전에 거래 중단)
    → None 반환 → caller 가 NULL 유지 (immutable, 오염 방지).

    codex review P2 lock-in: 기존 `WHERE date <= target` 만으로는 horizon 이전 어느
    시점이든 통과 → delisting 시 day-1 close 를 day-21 outcome 으로 저장하는 silent
    contamination. lower bound (target - tolerance) 추가로 차단.
    """
    target_dt = entry_date + timedelta(days=horizon_days)
    target = target_dt.strftime("%Y-%m-%d")
    lower_bound = (target_dt - timedelta(days=HORIZON_TOLERANCE_DAYS)).strftime("%Y-%m-%d")
    rows = query(
        "SELECT close FROM prices WHERE ticker = ? AND date <= ? AND date >= ? ORDER BY date DESC LIMIT 1",
        (ticker, target, lower_bound),
        db_path=db_path,
    )
    if not rows:
        return None
    return rows[0]["close"]


def track_outcomes(db_path=None, recompute: bool = False) -> int:
    """과거 추천의 7/14/21/30/60/90일 forward return 을 업데이트.

    #468 codex Plan consult Round 1:
    - Multi-horizon: 7/14/21/30/60/90. 7/14/21 = provisional/readiness, 30 = canonical, 60/90 = extended.
    - Outcome immutability: non-null outcome 절대 overwrite 안 함 (recompute=True 명시 시만).
    - Deterministic: `_forward_close_at_horizon` 헬퍼 단일 정의.
    - Hit/hit_quality 는 outcome_30d (canonical) 기준만. 짧은 호라이즌은 monitoring only.

    Args:
        db_path: DB 경로 (테스트용)
        recompute: True 일 때만 기존 non-null outcome overwrite 허용. 기본 False.
    """
    from nuri.core.timezone import kst_now

    # naive datetime으로 통일 (DB 날짜는 naive)
    now = kst_now().replace(tzinfo=None)
    updated = 0

    # 아직 추적 안 된 추천 조회 — 전체 호라이즌 중 하나라도 미채움이면 후보.
    # recompute=True 면 모든 row scan (immutability 무시 후 덮어쓰기).
    if recompute:
        recs = query(
            "SELECT id, date, ticker, action, entry_price, "
            "outcome_7d, outcome_14d, outcome_21d, outcome_30d, outcome_60d, outcome_90d "
            "FROM recommendations WHERE entry_price > 0",
            db_path=db_path,
        )
    else:
        recs = query(
            "SELECT id, date, ticker, action, entry_price, "
            "outcome_7d, outcome_14d, outcome_21d, outcome_30d, outcome_60d, outcome_90d "
            "FROM recommendations "
            "WHERE entry_price > 0 AND ("
            "  outcome_7d IS NULL OR outcome_14d IS NULL OR outcome_21d IS NULL"
            "  OR outcome_30d IS NULL OR outcome_60d IS NULL OR outcome_90d IS NULL"
            ")",
            db_path=db_path,
        )

    for rec in recs:
        rec_date = datetime.strptime(rec["date"], "%Y-%m-%d")
        elapsed = (now - rec_date).days
        ticker = rec["ticker"]
        entry = rec["entry_price"]

        if entry <= 0:
            continue

        updates: dict[str, float | bool | str] = {}
        ret30: float | None = None  # canonical hit 판정용 로컬 캡처 (type narrowing)

        for horizon in TRACK_HORIZONS:
            col = f"outcome_{horizon}d"
            current = rec[col]
            # Outcome immutability — non-null 절대 overwrite 금지 (recompute 시만 예외).
            if current is not None and not recompute:
                continue
            if elapsed < horizon:
                continue
            close = _forward_close_at_horizon(ticker, rec_date, horizon, db_path=db_path)
            if close is None:
                continue
            ret = round((close - entry) / entry * 100, 2)
            updates[col] = ret
            if horizon == 30:
                ret30 = ret

        # hit / hit_quality 는 canonical 30d 만 결정 (의도된 단일 기준).
        # BUY: +5% 이상 (성장 +20% 목표의 25%), SELL: -2% 이하.
        if ret30 is not None:
            action = rec["action"]
            if action == "BUY":
                updates["hit"] = ret30 >= 5.0
                updates["hit_quality"] = round(ret30 / 20.0, 3) if ret30 > 0 else 0.0
            else:
                updates["hit"] = ret30 < -2.0
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
                print(f"  {row['action']:<8} {row['total']:>6} {row['hits']:>6} {rate:>6.0%} {avg:>+7.1f}%")
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
            print(
                f"    {r['date']} {r['ticker']:<8} {r['action']:<6} "
                f"conf={r['confidence']:.0f} ${r['entry_price']:,.2f} → {outcome} [{hit_mark}]"
            )

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
        # A-6: dataclass default 로 tier 항상 존재 — defensive getattr 제거.
        candidates = [c for c in all_candidates if c.tier == TIER_ACTIONABLE]
        dropped = len(all_candidates) - len(candidates)
        if dropped:
            logger.info(
                f"후보 {len(all_candidates)}건 중 actionable {len(candidates)}건 저장 "
                f"(advisory/avoid {dropped}건은 disclosure-only, persist 제외)"
            )
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

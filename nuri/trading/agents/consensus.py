"""
멀티 에이전트 합의 엔진 — SIEGE Swarm Intelligence 패턴.

10개 전문 에이전트의 독립 판정을 가중 투표로 합산.
에이전트별 가중치는 과거 적중률(Learning Memory)에서 동적 계산.
의견 불일치는 명시적으로 기록하여 감사 가능.

사용법:
    python -m nuri.trading.agents.consensus
    python -m nuri.trading.agents.consensus --ticker TSLA
"""

import argparse
import logging
from dataclasses import dataclass

from nuri.core.agent_config import AGENT_CONFIG
from nuri.core.db import get_tickers
from nuri.trading.agents.base import AgentVerdict
from nuri.trading.agents.crypto_agent import CryptoAgent
from nuri.trading.agents.fundamental import FundamentalAgent
from nuri.trading.agents.korean_market import KoreanMarketAgent
from nuri.trading.agents.macro_agent import MacroAgent
from nuri.trading.agents.options_agent import OptionsAgent
from nuri.trading.agents.retail_agent import RetailAgent
from nuri.trading.agents.risk_agent import RiskAgent
from nuri.trading.agents.smart_money import SmartMoneyAgent
from nuri.trading.agents.technical import TechnicalAgent
from nuri.trading.agents.wallstreet import WallStreetAgent

logger = logging.getLogger(__name__)

# 기본 가중치 (과거 데이터 없을 때)
# 7→10 에이전트 확장: 기존 에이전트 비중 소폭 하향, 신규 3개 배분
DEFAULT_WEIGHTS = {
    "technical": 0.152,  # 16→15.2 (×0.95)
    "fundamental": 0.114,  # 12→11.4
    "macro": 0.114,  # 12→11.4
    "risk": 0.19,  # 20→19 (거부권 유지)
    "smart_money": 0.076,  # 8→7.6
    "wallstreet": 0.105,  # 11→10.5
    "korean_market": 0.076,  # 8→7.6 (.KS 종목에서만 실질 영향)
    "options": 0.076,  # 8→7.6
    "crypto": 0.047,  # 5→4.7
    "retail": 0.05,  # 0→5% 활성화: WSB 역발상 시그널
}

ALL_AGENTS = [
    TechnicalAgent(),
    FundamentalAgent(),
    MacroAgent(),
    RiskAgent(),
    SmartMoneyAgent(),
    WallStreetAgent(),
    KoreanMarketAgent(),
    OptionsAgent(),
    CryptoAgent(),
    RetailAgent(),
]


@dataclass
class ConsensusResult:
    """멀티 에이전트 합의 결과."""

    ticker: str
    final_action: str  # "BUY", "SELL", "HOLD"
    final_confidence: float  # 0~100
    agreement_rate: float  # 0~1 (동일 action 비율)
    verdicts: list[AgentVerdict]
    dissent: list[str]  # 반대 의견 에이전트 목록
    reasoning: str  # 합의 근거 요약
    divergence_flag: bool = False  # TechnicalAgent 가 합의 BUY/SELL 에 정면 반대 (#5.10 JKHY 방지)
    divergence_reason: str = ""  # flag 가 True 일 때 사용자에게 노출할 설명
    # Mechanical penalty 감사 필드 — caller 가 `consensus_penalty_applied` 이벤트 emit 시 사용.
    penalty_applied: bool = False  # True 면 divergence penalty 로 action 이 downgrade 됨
    pre_penalty_action: str = ""  # penalty 발동 전 원 action (BUY/SELL). flag=False 이면 빈 문자열.
    # Phase 2 A-2a: per-agent contribution breakdown. `save_to_recommendations` 가
    # JSON 직렬화해 recommendations.scoring_detail 에 persist. 이전에는 None 이라
    # API/frontend 가 "왜 이 판정이 나왔는지" 를 reconstruct 할 수 없었음.
    scoring_detail: dict | None = None


def _compute_weights(db_path=None) -> dict[str, float]:
    """Learning Memory + recommendations 기반 동적 가중치 계산.

    recommendations.agent_verdicts (JSON list of verdict dicts) 를 primary source
    로 읽어 에이전트별 적중률을 계산. 30일 이상 경과한 추천 중 outcome_30d 가
    있는 건만 대상. 데이터 부족 시 (< min_records) DEFAULT_WEIGHTS 반환.

    TODO(#178): decisions 테이블 기반 compute_agent_accuracy()가 30건 이상
    완료되면, recommendations 대신 decisions 테이블을 primary source로 전환.
    decisions는 outcome 판정이 더 엄격하고 (90일 기준), agent_verdicts가
    정규화된 JSON이라 파싱이 안정적. 현재는 additive — 두 소스가 공존.
    See: nuri.trading.engine.decisions.compute_agent_accuracy()
    """
    from nuri.core.db import query

    _lm = AGENT_CONFIG.get("consensus", {}).get("learning_memory", {})
    lookback = _lm.get("lookback_days", 180)
    min_records = _lm.get("min_records", 10)

    rows = query(
        """
        SELECT agent_verdicts, outcome_30d FROM recommendations
        WHERE outcome_30d IS NOT NULL
          AND agent_verdicts IS NOT NULL
          AND agent_verdicts != ''
          AND date >= date('now', ? || ' days')
        """,
        (f"-{lookback}",),
        db_path=db_path,
    )

    import json

    agent_hits: dict[str, list[bool]] = {name: [] for name in DEFAULT_WEIGHTS}
    # Observability counters — silent fallback 방지 (codex A-1 review).
    # 모든 row 가 skip 되면 min_records 문턱을 넘어도 가중치 변화 없이
    # DEFAULT_WEIGHTS 로 귀결되는 silent failure. 카운터로 drill-down 가능.
    rows_seen = len(rows)
    rows_parsed = 0
    rows_skipped_schema = 0
    rows_skipped_json = 0

    for row in rows:
        try:
            verdicts_str = row["agent_verdicts"]
            verdicts = json.loads(verdicts_str) if isinstance(verdicts_str, str) else None
            if not isinstance(verdicts, list):
                rows_skipped_schema += 1
                continue

            # WHERE outcome_30d IS NOT NULL guards the read; `or 0` is defensive only.
            outcome = row["outcome_30d"] or 0
            is_positive = outcome > 0
            rows_parsed += 1

            for v in verdicts:
                if not isinstance(v, dict):
                    continue
                agent_name = v.get("agent_name", "")
                action = v.get("action", "HOLD")
                if agent_name in agent_hits:
                    # BUY가 양수 수익이면 적중, SELL이 음수 수익이면 적중.
                    # outcome_30d == 0 bias 는 의도적 pin (test_hit_rate_outcome_zero_is_buy_miss_sell_hit).
                    # HOLD agent verdict 는 hit 판정 제외 (분기 없음 → 자동 skip).
                    if action == "BUY":
                        agent_hits[agent_name].append(is_positive)
                    elif action == "SELL":
                        agent_hits[agent_name].append(not is_positive)
        except (json.JSONDecodeError, TypeError, KeyError):
            rows_skipped_json += 1
            continue

    # min_records gate — parsed count 기반 (codex A-1 P1-2).
    # 이전: len(rows) < min_records 로 raw SQL 수 검증 → malformed row 가 gate 통과 후
    # 실제 학습 샘플이 문턱 미달로 가중치 shift. parsed 수로 gate 해야 샘플 신뢰성 보장.
    if rows_parsed < min_records:
        # fallback 발생 시 명시적 WARNING — normal path (early return) 과 구분.
        if rows_seen > 0:
            logger.warning(
                "_compute_weights fallback to DEFAULT_WEIGHTS: rows_seen=%d rows_parsed=%d (< min_records=%d) skipped_schema=%d skipped_json=%d",
                rows_seen, rows_parsed, min_records, rows_skipped_schema, rows_skipped_json,
            )
        return dict(DEFAULT_WEIGHTS)

    # Normal path — DEBUG 레벨 (per-ticker 호출 hot path spam 방지).
    # Anomaly (skip 발생) 시 INFO 로 올려 operator 눈에 띄게.
    if rows_skipped_schema > 0 or rows_skipped_json > 0:
        logger.info(
            "_compute_weights anomaly: rows_seen=%d rows_parsed=%d rows_skipped_schema=%d rows_skipped_json=%d",
            rows_seen, rows_parsed, rows_skipped_schema, rows_skipped_json,
        )
    else:
        logger.debug(
            "_compute_weights: rows_seen=%d rows_parsed=%d",
            rows_seen, rows_parsed,
        )

    # 적중률 기반 가중치 계산
    min_agent_records = _lm.get("min_agent_records", 5)
    hit_rates = {}
    for name, hits in agent_hits.items():
        if len(hits) >= min_agent_records:
            hit_rates[name] = sum(hits) / len(hits)

    if not hit_rates:
        return dict(DEFAULT_WEIGHTS)

    # 적중률을 가중치로 변환 (정규화)
    # 기본 가중치의 ±adjustment_range 범위 내에서 조정
    adj_range = _lm.get("adjustment_range", 0.30)
    min_weight = _lm.get("min_weight_floor", 0.03)
    weights = dict(DEFAULT_WEIGHTS)
    for name, rate in hit_rates.items():
        base = DEFAULT_WEIGHTS.get(name, 0.1)
        # 50% 적중률 = 기본값, 70% = +30%, 30% = -30%
        adjustment = (rate - 0.5) * 1.5  # -0.75 ~ +0.75 범위
        adjusted = base * (1 + max(-adj_range, min(adj_range, adjustment)))
        weights[name] = max(min_weight, adjusted)

    # 총합 1.0으로 정규화
    total = sum(weights.values())
    if total > 0:
        weights = {k: v / total for k, v in weights.items()}

    return weights


def _build_consensus(ticker: str, verdicts: list[AgentVerdict], weights: dict) -> ConsensusResult:
    """가중 투표로 합의 결과 산출 (analyze_ticker / stream_analyze_ticker 공용)."""
    action_scores = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
    for v in verdicts:
        w = weights.get(v.agent_name, 0.1)
        action_scores[v.action] += w * (v.confidence / 100)

    # 리스크 에이전트 거부권
    veto_threshold = AGENT_CONFIG.get("consensus", {}).get("risk_veto_threshold", 80)
    risk_v = next((v for v in verdicts if v.agent_name == "risk"), None)
    risk_veto_fired = False
    if risk_v and risk_v.action == "SELL" and risk_v.confidence >= veto_threshold:
        final_action = "SELL"
        final_confidence = risk_v.confidence
        reasoning = f"리스크 에이전트 거부권 발동: {risk_v.reasoning}"
        risk_veto_fired = True
    else:
        final_action = max(action_scores, key=lambda k: action_scores[k])
        total_weight = sum(action_scores.values())
        final_confidence = (action_scores[final_action] / total_weight * 100) if total_weight > 0 else 0
        supporters = [v for v in verdicts if v.action == final_action]
        reasoning = " | ".join(f"{v.agent_name}: {v.reasoning}" for v in supporters)

    # Divergence detection — docs/HARNESS.md §2 (JKHY, 2026-04-14) 재발 방지.
    # 9개 fundamentals-ish 에이전트가 BUY 를 몰아주면 TechnicalAgent 의 SELL
    # 반대가 묻힘. 합의 action 이 BUY/SELL 이고 technical 이 정확히 반대 action
    # 이면 flag + reason 을 surface. HOLD 는 "약한 반대" 로 간주해 flag 하지 않음.
    divergence_flag = False
    divergence_reason = ""
    tech_v = next((v for v in verdicts if v.agent_name == "technical"), None)
    if tech_v and final_action in ("BUY", "SELL"):
        opposite = {"BUY": "SELL", "SELL": "BUY"}[final_action]
        if tech_v.action == opposite:
            divergence_flag = True
            divergence_reason = (
                f"기술지표 반대: TechnicalAgent 가 {tech_v.action} "
                f"(conf {tech_v.confidence:.0f}) — 합의 {final_action} 과 충돌. "
                f"근거: {tech_v.reasoning[:120]}"
            )

    # Divergence mechanical penalty — flag 가 informational 인 P1 A1/A2 한계 보완.
    # tech confidence 가 threshold 이상일 때만 final_action 을 HOLD 로 downgrade.
    # 원래 계산된 final_confidence 는 **그대로 유지** (downstream 이 신뢰도 정보
    # 로 사용할 수 있게). reasoning 에 penalty 근거 prepend. Risk veto 가 이미
    # 발동했다면 precedence 에 따라 penalty skip.
    divergence_threshold = AGENT_CONFIG.get("consensus", {}).get("divergence_technical_threshold", 80)
    penalty_applied = False
    pre_penalty_action_str = ""
    if divergence_flag and not risk_veto_fired and tech_v and tech_v.confidence >= divergence_threshold:
        pre_penalty_action_str = final_action  # BUY 또는 SELL
        final_action = "HOLD"
        reasoning = f"기술지표 반대로 downgrade (tech {tech_v.action} conf {tech_v.confidence:.0f} ≥ {divergence_threshold}) | {reasoning}"
        penalty_applied = True

    # agreement_rate / dissent 는 **penalty 이전** 의 원 verdict 분포 기준으로
    # 계산 — 사용자가 "10 중 몇 개가 HOLD 동의" 가 아니라 "원래 BUY/SELL 쪽은
    # 몇 개 였는지" 를 볼 수 있어야 penalty 맥락을 이해할 수 있다.
    dist_basis = pre_penalty_action_str if penalty_applied else final_action
    agree_count = sum(1 for v in verdicts if v.action == dist_basis)
    agreement_rate = agree_count / len(verdicts) if verdicts else 0
    dissent = [
        f"{v.agent_name}({v.action}, {v.confidence:.0f}): {v.reasoning}" for v in verdicts if v.action != dist_basis
    ]

    # Phase 2 A-2a — scoring breakdown. 사용자가 "왜 이 action 이 나왔는가" 를
    # reconstruct 할 수 있도록 per-agent weight × confidence 기여도를 저장.
    # Risk veto / divergence penalty 도 함께 기록해 audit trail 확보.
    #
    # Schema (codex A-2a review 대응):
    # - `source="consensus"` + `schema_version=1` — candidates.py scoring_detail
    #   (tier/conflict_penalty 기반) 와 같은 column 공유하므로 discriminator 필수.
    # - `basis_action` — contributions 가 참조하는 action 방향. penalty 미발동 시
    #   final_action 과 동일, 발동 시 pre_penalty_action (downgrade 전 원 방향).
    # - `final_action_source` — 어느 메커니즘이 final_action 을 결정했는가.
    #   "weighted_sum" | "risk_veto" | "divergence_penalty".
    final_confidence_rounded = round(final_confidence, 1)
    basis_action = pre_penalty_action_str if penalty_applied else final_action
    if risk_veto_fired:
        final_action_source = "risk_veto"
    elif penalty_applied:
        final_action_source = "divergence_penalty"
    else:
        final_action_source = "weighted_sum"
    contributions = []
    for v in verdicts:
        w = weights.get(v.agent_name, 0.1)
        weighted = round(w * (v.confidence / 100), 4)
        contributions.append(
            {
                "agent_name": v.agent_name,
                "action": v.action,
                "confidence": round(float(v.confidence), 1),
                "weight": round(float(w), 4),
                "weighted": weighted,
                # basis_action 방향 (penalty 발동 시 pre_penalty_action, 아니면
                # final_action) 에 실제 기여한 verdict 를 True 로 마킹. UI 는 이
                # 플래그로 "합의 방향 지지자" 를 강조하되 final_action 과 다를 수
                # 있음을 `basis_action` 별도 노출로 처리.
                "counted_for_basis_action": v.action == basis_action,
            }
        )
    scoring_detail = {
        "source": "consensus",
        "schema_version": 1,
        "weights": {k: round(float(v), 4) for k, v in weights.items()},
        "action_scores": {k: round(float(val), 4) for k, val in action_scores.items()},
        "contributions": contributions,
        "final_action": final_action,
        "final_confidence": final_confidence_rounded,
        "final_action_source": final_action_source,
        "basis_action": basis_action,
        "agreement_rate": round(agreement_rate, 2),
        "risk_veto_fired": risk_veto_fired,
        "divergence_flag": divergence_flag,
        "penalty_applied": penalty_applied,
        "pre_penalty_action": pre_penalty_action_str,
    }

    return ConsensusResult(
        ticker=ticker,
        final_action=final_action,
        final_confidence=final_confidence_rounded,
        agreement_rate=round(agreement_rate, 2),
        verdicts=verdicts,
        dissent=dissent,
        reasoning=reasoning,
        divergence_flag=divergence_flag,
        divergence_reason=divergence_reason,
        penalty_applied=penalty_applied,
        pre_penalty_action=pre_penalty_action_str,
        scoring_detail=scoring_detail,
    )


def analyze_ticker(ticker: str, db_path=None) -> ConsensusResult:
    """단일 종목에 대해 10개 에이전트 분석 + 합의.

    한 에이전트가 외부 API 등으로 느려져도 전체가 죽지 않도록,
    `as_completed` iterator의 TimeoutError를 잡고 미완료 future는
    HOLD/0/타임아웃 verdict로 폴백한다 (#130 회귀 방지).

    Timeout은 `config/agents.yaml` `consensus.agent_timeout_sec` 에서 설정.
    """
    import concurrent.futures

    weights = _compute_weights(db_path)
    verdicts: list[AgentVerdict] = []
    agent_timeout = AGENT_CONFIG.get("consensus", {}).get("agent_timeout_sec", 60)

    def _run_agent(agent):
        try:
            return agent.analyze(ticker, db_path)
        except Exception as e:  # noqa: BLE001 — 에이전트 예외를 verdict로 흡수
            return AgentVerdict(agent.name, ticker, "HOLD", 0, f"에러: {e}")

    # `with` 대신 명시적 shutdown — 미완료 future를 cancel하고 즉시 반환.
    # `with` 블록은 __exit__에서 wait=True로 모든 future 완료를 기다리므로
    # timeout의 의미가 사라짐.
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(ALL_AGENTS))
    try:
        futures = {executor.submit(_run_agent, agent): agent for agent in ALL_AGENTS}
        completed: set[concurrent.futures.Future] = set()
        try:
            for future in concurrent.futures.as_completed(futures, timeout=agent_timeout):
                completed.add(future)
                agent = futures[future]
                try:
                    verdicts.append(future.result())
                except Exception as e:  # noqa: BLE001
                    verdicts.append(AgentVerdict(agent.name, ticker, "HOLD", 0, f"에러: {e}"))
        except concurrent.futures.TimeoutError:
            # 전체 batch timeout — 미완료 future는 폴백 verdict로
            for future, agent in futures.items():
                if future not in completed:
                    verdicts.append(AgentVerdict(agent.name, ticker, "HOLD", 0, "타임아웃"))
    finally:
        # cancel_futures: 큐에 대기중인(아직 시작 안 한) future 취소
        # wait=False: 실행 중인 future가 끝날 때까지 기다리지 않음
        executor.shutdown(wait=False, cancel_futures=True)

    result = _build_consensus(ticker, verdicts, weights)
    _emit_penalty_event_if_fired(result, verdicts, db_path=db_path)
    return result


def _emit_penalty_event_if_fired(result: ConsensusResult, verdicts: list[AgentVerdict], db_path=None) -> None:
    """Mechanical penalty 발동 시 `consensus_penalty_applied` 이벤트 기록.

    STRATEGY §2.6 Escalation Ladder — soft penalty rung 감사 로그. 1-2 달 후
    `pipeline_events` 조회로 "penalty 가 몇 % 발동하고, 몇 % 티커에 영향이며,
    BUY→HOLD swing 은 몇 건인가" 를 답할 수 있어야 한다. Emit 실패해도
    consensus 자체는 정상 반환.
    """
    if not result.penalty_applied:
        return
    tech_v = next((v for v in verdicts if v.agent_name == "technical"), None)
    if tech_v is None:
        return
    threshold = AGENT_CONFIG.get("consensus", {}).get("divergence_technical_threshold", 80)
    try:
        from nuri.core.events import emit_event

        emit_event(
            "consensus_penalty_applied",
            step="recommend",
            payload={
                "ticker": result.ticker,
                "penalty_kind": "divergence_technical",
                "threshold": threshold,
                "technical_action": tech_v.action,
                "technical_confidence": tech_v.confidence,
                "consensus_action_before": result.pre_penalty_action,
                "consensus_confidence_before": result.final_confidence,
                "consensus_action_after": result.final_action,
                "consensus_confidence_after": result.final_confidence,
                "swing": f"{result.pre_penalty_action}_TO_{result.final_action}",
                "divergence_reason": result.divergence_reason,
            },
            db_path=db_path,
        )
    except Exception:
        logger.warning("consensus_penalty_applied 이벤트 emit 실패 — consensus 결과는 정상 반환", exc_info=True)


def stream_analyze_ticker(ticker: str, db_path=None):
    """단일 종목 스트리밍 분석 — 에이전트 완료 순서대로 verdict 생성.

    `analyze_ticker`와 동일한 timeout 폴백 로직 (#130). 미완료 에이전트는
    timeout 도달 시점에 일괄 HOLD/0/타임아웃 verdict로 yield.

    Yields:
        ("verdict", AgentVerdict) — 에이전트 완료 시마다
        ("consensus", ConsensusResult) — 전체 합의 완료 시
    """
    import concurrent.futures

    weights = _compute_weights(db_path)
    verdicts: list[AgentVerdict] = []
    agent_timeout = AGENT_CONFIG.get("consensus", {}).get("agent_timeout_sec", 60)

    def _run_agent(agent):
        try:
            return agent.analyze(ticker, db_path)
        except Exception as e:  # noqa: BLE001
            return AgentVerdict(agent.name, ticker, "HOLD", 0, f"에러: {e}")

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(ALL_AGENTS))
    try:
        futures = {executor.submit(_run_agent, agent): agent for agent in ALL_AGENTS}
        completed: set[concurrent.futures.Future] = set()
        try:
            for future in concurrent.futures.as_completed(futures, timeout=agent_timeout):
                completed.add(future)
                agent = futures[future]
                try:
                    verdict = future.result()
                except Exception as e:  # noqa: BLE001
                    verdict = AgentVerdict(agent.name, ticker, "HOLD", 0, f"에러: {e}")
                verdicts.append(verdict)
                yield ("verdict", verdict)
        except concurrent.futures.TimeoutError:
            for future, agent in futures.items():
                if future not in completed:
                    verdict = AgentVerdict(agent.name, ticker, "HOLD", 0, "타임아웃")
                    verdicts.append(verdict)
                    yield ("verdict", verdict)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    result = _build_consensus(ticker, verdicts, weights)
    _emit_penalty_event_if_fired(result, verdicts, db_path=db_path)
    yield ("consensus", result)


def analyze_portfolio(db_path=None) -> list[ConsensusResult]:
    """전 보유종목에 대해 멀티 에이전트 합의."""
    tickers = get_tickers(db_path=db_path)
    results = []
    for ticker in tickers:
        result = analyze_ticker(ticker, db_path)
        results.append(result)
        logger.info(
            f"{ticker}: {result.final_action} (conf={result.final_confidence:.0f}, agree={result.agreement_rate:.0%})"
        )
    return results


def save_to_recommendations(results: list[ConsensusResult], db_path=None) -> int:
    """ConsensusResult를 recommendations 테이블에 INSERT.

    이전: `make consensus`는 stdout만 출력하고 DB에 저장하지 않아 frontend
    /decision 페이지가 빈 상태로 표시되었음 (routing failure).
    이제 합의 직후 자동 저장하여 evidence trail 연속성 보장.

    중복 방지: (date, ticker) 같은 날 재실행 시 INSERT OR REPLACE.
    """
    import json

    from nuri.core.db import get_db, query
    from nuri.core.timezone import today_kst

    if not results:
        return 0

    today = today_kst()
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
                }
                for v in r.verdicts
            ],
            ensure_ascii=False,
        )

        # Phase 2 A-2a: scoring_detail persist. _build_consensus 가 채웠지만 legacy
        # 호출자가 직접 ConsensusResult 를 만들 수 있어 None 방어. `is not None`
        # 사용해 빈 dict `{}` 는 persist (codex A-2a review P3 — falsy 실수 방지).
        scoring_detail_json = (
            json.dumps(r.scoring_detail, ensure_ascii=False) if r.scoring_detail is not None else None
        )
        records.append(
            {
                "date": today,
                "ticker": r.ticker,
                "action": r.final_action,
                "confidence": r.final_confidence,
                "regime": None,  # consensus는 regime 정보 없음 — tracker.py가 채움
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
            }
        )

    with get_db(db_path) as conn:
        # 같은 날 같은 종목 재실행 시 UPSERT — id 보존 (trades.recommendation_id FK 안전).
        # INSERT OR REPLACE 는 DELETE+INSERT 라 id 바뀌어 FK 참조 끊김 위험.
        conn.executemany(
            """INSERT INTO recommendations
               (date, ticker, action, confidence, regime, signals, entry_price,
                agent_verdicts, scoring_detail)
               VALUES (:date, :ticker, :action, :confidence, :regime, :signals, :entry_price,
                       :agent_verdicts, :scoring_detail)
               ON CONFLICT(date, ticker) DO UPDATE SET
                   action = excluded.action,
                   confidence = excluded.confidence,
                   regime = excluded.regime,
                   signals = excluded.signals,
                   entry_price = excluded.entry_price,
                   agent_verdicts = excluded.agent_verdicts,
                   scoring_detail = excluded.scoring_detail""",
            records,
        )
        return len(records)


def print_consensus(results: list[ConsensusResult], *, verbose: bool = False) -> None:
    """합의 결과 CLI 출력.

    Args:
        results: ConsensusResult 리스트
        verbose: True 시 종목별 supporting verdicts (합의 의견의 reasoning) 함께 출력
    """
    if not results:
        print("합의 결과 없음")
        return

    print(f"\n{'=' * 120}")
    print(f"  Multi-Agent Consensus ({len(results)} tickers, 10 agents)")
    print(f"{'=' * 120}")
    header_agents = ["Tech", "Fund", "Macro", "Risk", "Smart", "Wall", "KR", "Opt", "Crypto", "Ret"]
    print(f"  {'Ticker':<10} {'Action':<6} {'Conf':>5} {'Agree':>6} " + " ".join(f"{h:>5}" for h in header_agents))
    print(f"  {'-' * 110}")

    agent_order = [
        "technical",
        "fundamental",
        "macro",
        "risk",
        "smart_money",
        "wallstreet",
        "korean_market",
        "options",
        "crypto",
        "retail",
    ]

    for r in sorted(results, key=lambda x: x.final_confidence, reverse=True):
        agent_map = {v.agent_name: v for v in r.verdicts}
        cols = []
        for name in agent_order:
            v = agent_map.get(name)
            if v:
                icon = {"BUY": "B", "SELL": "S", "HOLD": "H"}.get(v.action, "?")
                cols.append(f"{icon}{v.confidence:.0f}")
            else:
                cols.append("--")

        print(
            f"  {r.ticker:<10} {r.final_action:<6} {r.final_confidence:>4.0f} {r.agreement_rate:>5.0%} "
            f"{' '.join(f'{c:>5}' for c in cols)}"
        )

    # 합의 supporters reasoning 출력 (verbose 모드 또는 단일 종목)
    show_supporters = verbose or len(results) == 1
    if show_supporters:
        for r in sorted(results, key=lambda x: x.final_confidence, reverse=True):
            supporters = [v for v in r.verdicts if v.action == r.final_action]
            if not supporters:
                continue
            print(
                f"\n  ▸ {r.ticker} {r.final_action} ({r.final_confidence:.0f}, agree={r.agreement_rate:.0%}) — supporters:"
            )
            for v in sorted(supporters, key=lambda x: x.confidence, reverse=True):
                print(f"      {v.agent_name}({v.confidence:.0f}): {v.reasoning}")

    # 반대 의견 요약
    dissents = [(r.ticker, r.dissent) for r in results if r.dissent]
    if dissents:
        print(f"\n  Dissent ({sum(len(d) for _, d in dissents)} opinions):")
        for ticker, ds in dissents[:5]:
            for d in ds:
                print(f"    {ticker}: {d}")

    # 가격 타겟 출력
    try:
        from nuri.trading.recommend.price_targets import calculate_targets, format_target_tree

        buy_hold = [r for r in results if r.final_action in ("BUY", "HOLD")]
        if buy_hold:
            print(f"\n{'=' * 85}")
            print("  Price Targets (BUY/HOLD 종목)")
            print(f"{'=' * 85}")
            for r in sorted(buy_hold, key=lambda x: x.final_confidence, reverse=True)[:10]:
                target = calculate_targets(r.ticker)
                if "error" not in target:
                    print(format_target_tree(target))
                    print(f"  {'─' * 50}")
    except Exception as e:
        logger.debug("가격 타겟 출력 실패: %s", e)

    # 외부 데이터 요약 출력
    try:
        from nuri.collectors.external import get_external

        tickers_with_data = set()
        for r in results:
            ext = get_external(r.ticker)
            if ext:
                tickers_with_data.add(r.ticker)
        if tickers_with_data:
            print(f"\n{'=' * 85}")
            print(f"  External Data ({len(tickers_with_data)} tickers)")
            print(f"{'=' * 85}")
            for r in results:
                if r.ticker not in tickers_with_data:
                    continue
                ext = get_external(r.ticker)
                parts = []
                for d in ext:
                    if d["data_type"] == "consensus":
                        parts.append(f"TipRanks:{d['value']}")
                    elif d["data_type"] == "superinvestor_count":
                        parts.append(f"슈퍼투자자:{d['value']}명")
                    elif d["data_type"] == "target_price" and d["source"] == "tipranks":
                        parts.append(f"목표가:${d['numeric_value']:,.0f}")
                if parts:
                    print(f"  {r.ticker:<10} {' | '.join(parts)}")
    except Exception as e:
        logger.debug("외부 데이터 출력 실패: %s", e)
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Nuri-Quant 멀티 에이전트 합의")
    parser.add_argument("--ticker", help="특정 종목만")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="합의 의견의 supporting verdicts reasoning 함께 출력"
    )
    args = parser.parse_args()

    if args.ticker:
        result = analyze_ticker(args.ticker)
        print_consensus([result], verbose=args.verbose)
        # 단일 종목도 DB 저장 (frontend evidence 연속성)
        saved = save_to_recommendations([result])
        if saved:
            logger.info(f"recommendations 테이블에 {saved}건 저장")
        # Decision Intelligence: 의사결정 저널 기록
        from nuri.trading.engine.decisions import record_decisions

        dec_count = record_decisions([result])
        logger.info(f"decisions 테이블에 {dec_count}건 기록")
    else:
        results = analyze_portfolio()
        print_consensus(results, verbose=args.verbose)
        saved = save_to_recommendations(results)
        if saved:
            logger.info(f"recommendations 테이블에 {saved}건 저장 (frontend /decision 활성화)")
        # Decision Intelligence: 의사결정 저널 기록
        from nuri.trading.engine.decisions import record_decisions

        dec_count = record_decisions(results)
        logger.info(f"decisions 테이블에 {dec_count}건 기록")

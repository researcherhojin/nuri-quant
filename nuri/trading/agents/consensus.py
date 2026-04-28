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


@dataclass
class AgentEligibility:
    """Per-agent state at a single outcome horizon (canonical 30d or provisional 21d).

    #468 codex Plan consult Round 1 — structural separation: canonical vs provisional
    return identical shapes so `select_weight_source` can run per-agent precedence.
    """

    name: str
    sample_count: int  # BUY/SELL verdicts with non-null outcome at this horizon
    weight: float  # adjusted (capped) weight, or DEFAULT_WEIGHTS[name] when not eligible
    eligible: bool  # sample_count >= min_agent_records (per-agent gate)


def _compute_horizon_eligibility(
    *,
    outcome_col: str,
    adjustment_range: float,
    label: str,
    db_path=None,
) -> dict[str, AgentEligibility]:
    """Shared per-horizon eligibility + weight calc.

    canonical_30d 와 provisional_21d 가 같은 shape 으로 결과 emit. 차이는:
    - outcome_col: 'outcome_30d' (canonical) vs 'outcome_21d' (provisional)
    - adjustment_range: 0.30 vs 0.10 (codex Round 1 — provisional 은 conservative cap)

    Observability: rows_seen / rows_parsed / rows_skipped_* 는 label 로 prefix 해
    canonical/provisional 가 같은 hot path 에서 구분 가능.
    """
    from nuri.core.db import query

    _lm = AGENT_CONFIG.get("consensus", {}).get("learning_memory", {})
    lookback = _lm.get("lookback_days", 180)
    min_records = _lm.get("min_records", 10)
    min_agent_records = _lm.get("min_agent_records", 5)
    min_weight = _lm.get("min_weight_floor", 0.03)

    rows = query(
        f"""
        SELECT agent_verdicts, {outcome_col} AS outcome FROM recommendations
        WHERE {outcome_col} IS NOT NULL
          AND agent_verdicts IS NOT NULL
          AND agent_verdicts != ''
          AND date >= date('now', ? || ' days')
        """,
        (f"-{lookback}",),
        db_path=db_path,
    )

    import json

    agent_hits: dict[str, list[bool]] = {name: [] for name in DEFAULT_WEIGHTS}
    rows_seen = len(rows)
    rows_parsed = 0
    rows_skipped_schema = 0
    rows_skipped_json = 0
    rows_skipped_no_usable = 0

    for row in rows:
        try:
            verdicts_str = row["agent_verdicts"]
            verdicts = json.loads(verdicts_str) if isinstance(verdicts_str, str) else None
            if not isinstance(verdicts, list):
                rows_skipped_schema += 1
                continue

            outcome = row["outcome"] or 0
            is_positive = outcome > 0

            row_has_usable_verdict = False
            for v in verdicts:
                if not isinstance(v, dict):
                    continue
                agent_name = v.get("agent_name", "")
                action = v.get("action", "HOLD")
                if agent_name in agent_hits:
                    if action == "BUY":
                        agent_hits[agent_name].append(is_positive)
                        row_has_usable_verdict = True
                    elif action == "SELL":
                        agent_hits[agent_name].append(not is_positive)
                        row_has_usable_verdict = True

            if row_has_usable_verdict:
                rows_parsed += 1
            else:
                rows_skipped_no_usable += 1
        except (json.JSONDecodeError, TypeError, KeyError):
            rows_skipped_json += 1
            continue

    # Total-rows gate — backward compat: 기존 _compute_weights 가 rows_parsed <
    # min_records 일 때 early return DEFAULT_WEIGHTS 였음. 같은 의미를 per-agent
    # 구조에서 보존하려면 이 gate 미통과 시 모든 agent eligible=False 강제.
    total_gate_passed = rows_parsed >= min_records

    eligibility: dict[str, AgentEligibility] = {}
    for name, hits in agent_hits.items():
        sample = len(hits)
        eligible = total_gate_passed and sample >= min_agent_records
        if eligible and sample > 0:
            rate = sum(hits) / sample
            base = DEFAULT_WEIGHTS.get(name, 0.1)
            # 50% 적중률 = 기본값, 70% = +adjustment_range, 30% = -adjustment_range
            adjustment = (rate - 0.5) * 1.5
            adjusted = base * (1 + max(-adjustment_range, min(adjustment_range, adjustment)))
            weight = max(min_weight, adjusted)
        else:
            weight = DEFAULT_WEIGHTS.get(name, 0.1)
        eligibility[name] = AgentEligibility(
            name=name, sample_count=sample, weight=weight, eligible=eligible
        )

    # Observability — 기존 _compute_weights 와 동일 키 이름 보존 (회귀 테스트).
    # WARNING: total gate 미통과 (fallback). INFO: skip 발생. DEBUG: normal path.
    if not total_gate_passed and rows_seen > 0:
        logger.warning(
            "%s fallback to DEFAULT_WEIGHTS: rows_seen=%d rows_parsed=%d (< min_records=%d) "
            "rows_skipped_schema=%d rows_skipped_json=%d rows_skipped_no_usable=%d",
            label, rows_seen, rows_parsed, min_records,
            rows_skipped_schema, rows_skipped_json, rows_skipped_no_usable,
        )
    elif rows_skipped_schema or rows_skipped_json or rows_skipped_no_usable:
        logger.info(
            "%s anomaly: rows_seen=%d rows_parsed=%d "
            "rows_skipped_schema=%d rows_skipped_json=%d rows_skipped_no_usable=%d",
            label, rows_seen, rows_parsed,
            rows_skipped_schema, rows_skipped_json, rows_skipped_no_usable,
        )
    else:
        logger.debug(
            "%s: rows_seen=%d rows_parsed=%d", label, rows_seen, rows_parsed,
        )

    return eligibility


def compute_canonical_weights(db_path=None) -> dict[str, AgentEligibility]:
    """Canonical 30d Learning Memory.

    #468 codex Round 1 — STRUCTURAL separation: 이 함수는 ONLY outcome_30d 만 read.
    Hard veto / amplifier (STRATEGY §2.6) 경로는 이 함수만 호출 — provisional 미접촉.
    adjustment_range = 0.30 (config default).
    """
    return _compute_horizon_eligibility(
        outcome_col="outcome_30d",
        adjustment_range=AGENT_CONFIG.get("consensus", {}).get("learning_memory", {}).get("adjustment_range", 0.30),
        label="canonical_30d",
        db_path=db_path,
    )


def compute_provisional_weights(db_path=None) -> dict[str, AgentEligibility]:
    """Provisional 21d short-horizon (warm-start before 30d outcomes saturate).

    #468 codex Round 1 — STRUCTURAL separation: ONLY outcome_21d read. 0.10 cap
    (canonical 의 1/3, conservative policy — calibration 별도 작업). veto/amplifier
    절대 호출 금지 (mainline `select_weight_source` 만 호출).
    """
    return _compute_horizon_eligibility(
        outcome_col="outcome_21d",
        adjustment_range=AGENT_CONFIG.get("consensus", {}).get("learning_memory", {}).get(
            "provisional_adjustment_range", 0.10
        ),
        label="provisional_21d",
        db_path=db_path,
    )


def select_weight_source(
    canonical: dict[str, AgentEligibility],
    provisional: dict[str, AgentEligibility],
) -> tuple[dict[str, float], dict[str, str]]:
    """Per-agent precedence: canonical_30d > provisional_21d > default.

    #468 codex Round 1 #1 — global label 이 아니라 per-agent. 일부 agent canonical,
    일부 provisional, 일부 default 동시 상태 가능. structurally_unsaturating 은
    BUY+SELL verdict 이력 없이 default fallback 인 agent (retail/crypto HOLD-only).

    Returns:
        (final_weights, source_per_agent)
        source_per_agent[name] ∈ {'canonical_30d', 'provisional_21d', 'default', 'structurally_unsaturating'}
    """
    weights = dict(DEFAULT_WEIGHTS)
    sources: dict[str, str] = {}

    for name in DEFAULT_WEIGHTS:
        c = canonical.get(name)
        p = provisional.get(name)
        if c is not None and c.eligible:
            weights[name] = c.weight
            sources[name] = "canonical_30d"
        elif p is not None and p.eligible:
            weights[name] = p.weight
            sources[name] = "provisional_21d"
        else:
            # Default fallback. structurally_unsaturating: 두 호라이즌 모두 BUY+SELL=0.
            total_samples = (c.sample_count if c else 0) + (p.sample_count if p else 0)
            sources[name] = "structurally_unsaturating" if total_samples == 0 else "default"

    # 정규화
    total = sum(weights.values())
    if total > 0:
        weights = {k: v / total for k, v in weights.items()}

    return weights, sources


def _compute_weights(db_path=None) -> dict[str, float]:
    """Legacy entry — backward compat. mainline (analyze_ticker / stream_analyze_ticker) 만 사용.

    #468 codex Round 1: 내부적으로 select_weight_source 위임. veto/amplifier 절대
    이 함수 직접 호출 금지 — `compute_canonical_weights` 만 사용 (structural separation).

    TODO(#178): decisions 테이블 기반 compute_agent_accuracy() 가 30건 이상 완료되면
    recommendations 대신 decisions 를 primary source 로 전환.
    See: nuri.trading.engine.decisions.compute_agent_accuracy()
    """
    canonical = compute_canonical_weights(db_path=db_path)
    provisional = compute_provisional_weights(db_path=db_path)
    weights, sources = select_weight_source(canonical, provisional)

    # provisional 발동 또는 structurally_unsaturating 시만 INFO surface
    # (조작자에게 low-confidence warm-start 또는 영구 default 상태 알림).
    # Pure canonical-only success 는 DEBUG (기존 _compute_weights normal path 와 동일 톤).
    prov_agents = [n for n, s in sources.items() if s == "provisional_21d"]
    unsaturating = [n for n, s in sources.items() if s == "structurally_unsaturating"]
    canon_agents = [n for n, s in sources.items() if s == "canonical_30d"]
    if prov_agents or unsaturating:
        logger.info(
            "_compute_weights per-agent source: canonical_30d=%s provisional_21d=%s structurally_unsaturating=%s",
            canon_agents, prov_agents, unsaturating,
        )
    elif canon_agents:
        logger.debug(
            "_compute_weights per-agent: all canonical_30d eligible (n=%d)", len(canon_agents)
        )

    return weights


def agent_readiness(db_path=None) -> dict:
    """Per-agent readiness snapshot for /api/learning-memory/readiness.

    #468 codex Round 1 #6/#7 — API 응답 형태 per-agent (global label 금지).
    structurally_unsaturating 표시 (HOLD-only emit pattern).
    """
    canonical = compute_canonical_weights(db_path=db_path)
    provisional = compute_provisional_weights(db_path=db_path)
    final_weights, sources = select_weight_source(canonical, provisional)

    agents = []
    for name in DEFAULT_WEIGHTS:
        c = canonical.get(name)
        p = provisional.get(name)
        agents.append({
            "name": name,
            "default_weight": DEFAULT_WEIGHTS[name],
            "final_weight": round(final_weights[name], 4),
            "source": sources[name],
            "canonical_30d": {
                "sample_count": c.sample_count if c else 0,
                "eligible": c.eligible if c else False,
                "weight": round(c.weight, 4) if c else DEFAULT_WEIGHTS[name],
            },
            "provisional_21d": {
                "sample_count": p.sample_count if p else 0,
                "eligible": p.eligible if p else False,
                "weight": round(p.weight, 4) if p else DEFAULT_WEIGHTS[name],
            },
        })
    return {
        "agents": agents,
        "summary": {
            "canonical_30d": sum(1 for s in sources.values() if s == "canonical_30d"),
            "provisional_21d": sum(1 for s in sources.values() if s == "provisional_21d"),
            "default": sum(1 for s in sources.values() if s == "default"),
            "structurally_unsaturating": sum(1 for s in sources.values() if s == "structurally_unsaturating"),
        },
    }


def _build_consensus(ticker: str, verdicts: list[AgentVerdict], weights: dict) -> ConsensusResult:
    """가중 투표로 합의 결과 산출 (analyze_ticker / stream_analyze_ticker 공용)."""
    action_scores = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
    for v in verdicts:
        w = weights.get(v.agent_name, 0.1)
        action_scores[v.action] += w * (v.confidence / 100)

    # 리스크 에이전트 거부권 — PR A: alpha_action="FLAT" 만 발동 (기존
    # `action=="SELL"` 에서 변경). concentration > 15% 같은 portfolio rule 은
    # alpha=FLAT 을 emit 하지 않으므로 veto 못 건다 → SIEGE REJECT → SELL 경로
    # 구조적 차단 (§ STRATEGY 2.6 Soft penalty vs Hard veto).
    # Back-compat: `alpha_action` 이 None 인 legacy/기타 agent 는 action=="SELL"
    # 로 폴백 판정 (risk agent 만 PR A 범위에서 axis 채움).
    veto_threshold = AGENT_CONFIG.get("consensus", {}).get("risk_veto_threshold", 80)
    risk_v = next((v for v in verdicts if v.agent_name == "risk"), None)
    risk_veto_fired = False
    veto_fired_now = False
    if risk_v is not None and risk_v.confidence >= veto_threshold:
        alpha_flat = risk_v.alpha_action == "FLAT"
        legacy_sell = risk_v.alpha_action is None and risk_v.action == "SELL"
        veto_fired_now = alpha_flat or legacy_sell
    if veto_fired_now:
        assert risk_v is not None  # veto_fired_now => risk_v non-None
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

    # PR A: regime 을 한 번 classify 해 배치 전체에 공유 (codex Q3 권고 — per-ticker
    # classify 는 ~30ms × N 추가 latency). 실패 시 None 으로 폴백 (legacy 동작
    # 유지), tracker.py 가 이후 backfill.
    batch_regime: str | None = None
    try:
        from nuri.quant.regime.classifier import classify_regime
        rr = classify_regime(db_path=db_path)
        if rr is not None:
            batch_regime = rr.regime
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
        scoring_detail_json = (
            json.dumps(r.scoring_detail, ensure_ascii=False) if r.scoring_detail is not None else None
        )

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
                   portfolio_action = excluded.portfolio_action""",
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

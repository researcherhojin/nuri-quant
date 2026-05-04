"""Learning Memory — per-agent weight calc from outcome backtest.

Structural separation (#468 codex Round 1): canonical (outcome_30d) and
provisional (outcome_21d) live in separate functions so static-source assertions
in tests remain meaningful (`compute_canonical_weights` source must NOT contain
"outcome_21d", and vice versa).

select_weight_source is a pure selector — no DB I/O. Tests assert this via
`inspect.getsource` (`test_select_weight_source_does_not_query_db`).
"""

from __future__ import annotations

import logging

from nuri.core.agent_config import AGENT_CONFIG

from .models import AgentEligibility
from .registry import DEFAULT_WEIGHTS

__all__ = [
    "_compute_horizon_eligibility",
    "compute_canonical_weights",
    "compute_provisional_weights",
    "select_weight_source",
]

logger = logging.getLogger(__name__)


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
            if not isinstance(verdicts, list):  # pragma: no cover — schema-violation defensive
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
        eligibility[name] = AgentEligibility(name=name, sample_count=sample, weight=weight, eligible=eligible)

    # Observability — 기존 _compute_weights 와 동일 키 이름 보존 (회귀 테스트).
    # WARNING: total gate 미통과 (fallback). INFO: skip 발생. DEBUG: normal path.
    if not total_gate_passed and rows_seen > 0:
        logger.warning(
            "%s fallback to DEFAULT_WEIGHTS: rows_seen=%d rows_parsed=%d (< min_records=%d) "
            "rows_skipped_schema=%d rows_skipped_json=%d rows_skipped_no_usable=%d",
            label,
            rows_seen,
            rows_parsed,
            min_records,
            rows_skipped_schema,
            rows_skipped_json,
            rows_skipped_no_usable,
        )
    elif rows_skipped_schema or rows_skipped_json or rows_skipped_no_usable:
        logger.info(
            "%s anomaly: rows_seen=%d rows_parsed=%d "
            "rows_skipped_schema=%d rows_skipped_json=%d rows_skipped_no_usable=%d",
            label,
            rows_seen,
            rows_parsed,
            rows_skipped_schema,
            rows_skipped_json,
            rows_skipped_no_usable,
        )
    else:
        logger.debug(
            "%s: rows_seen=%d rows_parsed=%d",
            label,
            rows_seen,
            rows_parsed,
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
        adjustment_range=AGENT_CONFIG.get("consensus", {})
        .get("learning_memory", {})
        .get("provisional_adjustment_range", 0.10),
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

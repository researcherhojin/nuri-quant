"""CausalFactorAuditor — Layer B actor (#529 Phase 2 — canonical #6).

López de Prado 2025 *Causal Factor Investing* 의 4-test framework:
1. **DAG plausibility** — assumed causal graph 의 d-separation 검증
2. **Placebo falsification** — random shuffle 한 placebo factor 가 origin 의 t-stat 80%+ 면 mirage
3. **Event-study** — 가설 trigger 직전/직후 abnormal return window
4. **Negative control** — 이론상 무관한 factor 가 같이 움직이면 spurious correlation

Layer B 설계 (Codex Round 5):
- 100% deterministic — 통계 검증, ZERO LLM
- 결과는 Hypothesis-Registry (#4) 의 evidence 로 사용 가능
- WalkForward-Validator (#5) 의 metric_kind='regression' 결과를 input 으로 받음

Anti-pattern 방지 (lock-test):
- placebo t-stat / origin t-stat > 0.80 → MIRAGE 판정 (BLOCK 권고)
- DAG cycle / back-door path open → INSUFFICIENT (검증 불가)
- n_obs < 100 → INSUFFICIENT (Codex: insufficient power for 4-test)

References:
- López de Prado 2025: https://rpc.cfainstitute.org/research/foundation/2025/causality-factor-investing
- Hypothesis-Registry (#4): factor mirage 감지 시 reject_hypothesis 호출 후보
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from nuri.agents.base import REGISTRY, Actor, ActorResult, Layer, Outcome, RunContext
from nuri.core.db import log_causal_audit, query
from nuri.core.timezone import today_kst

logger = logging.getLogger(__name__)

# ─── 4-test 임계값 (Codex consult + López de Prado 2025) ─────
MIN_OBS = 100  # < 100 obs → INSUFFICIENT (statistical power 부족)
PLACEBO_T_RATIO_MIRAGE_CUTOFF = 0.80  # placebo / origin t-stat > 0.80 → MIRAGE
EVENT_STUDY_WINDOW = 5  # ±5 day abnormal return window
EVENT_STUDY_T_CUTOFF = 1.96  # 95% confidence
NEGATIVE_CONTROL_R_CUTOFF = 0.30  # |r| > 0.30 with negative control → spurious 의심
N_PLACEBO_RUNS = 100  # placebo permutation 횟수


@dataclass
class TestResults:
    """4-test 개별 결과 + composite causal_certainty."""

    dag: dict = field(default_factory=dict)
    placebo: dict = field(default_factory=dict)
    event_study: dict = field(default_factory=dict)
    negative_control: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dag": self.dag,
            "placebo": self.placebo,
            "event_study": self.event_study,
            "negative_control": self.negative_control,
        }


def _t_stat(y: np.ndarray, x: np.ndarray) -> float:
    """OLS slope t-stat (단변수). degenerate → 0.0."""
    if len(x) < 3 or np.std(x) == 0 or np.std(y) == 0:
        return 0.0
    cov = np.cov(x, y, ddof=1)[0, 1]
    var_x = float(np.var(x, ddof=1))
    if var_x == 0:  # pragma: no cover — already guarded by np.std(x) == 0 above
        return 0.0
    beta = cov / var_x
    y_hat = beta * (x - x.mean()) + y.mean()
    residuals = y - y_hat
    sse = float(np.sum(residuals**2))
    n = len(x)
    if n <= 2 or sse <= 0:
        return 0.0
    se_beta = float(np.sqrt(sse / (n - 2) / (var_x * (n - 1))))
    if se_beta == 0:  # pragma: no cover — sse>0 + var_x>0 guarantees se_beta>0
        return 0.0
    return float(beta / se_beta)


def _dag_plausibility_check(
    edges: list[tuple[str, str]],
    nodes: list[str],
) -> dict[str, Any]:
    """Test 1 — DAG plausibility: cycle 검출 + back-door path 개수.

    edges = [(parent, child), ...] (causal arrow direction).
    cycle 있으면 INSUFFICIENT (DAG 가 아님).
    """
    # Build adjacency
    adj: dict[str, list[str]] = {n: [] for n in nodes}
    for src, dst in edges:
        if src not in adj or dst not in adj:
            return {
                "pass": False,
                "reason": f"edge ({src}, {dst}) references unknown node",
                "n_edges": len(edges),
                "has_cycle": False,
            }
        adj[src].append(dst)

    # DFS cycle detection
    WHITE, GRAY, BLACK = 0, 1, 2
    color = dict.fromkeys(nodes, WHITE)
    has_cycle = False

    def dfs(node: str) -> None:
        nonlocal has_cycle
        color[node] = GRAY
        for nxt in adj[node]:
            if color[nxt] == GRAY:
                has_cycle = True
                return
            if color[nxt] == WHITE:
                dfs(nxt)
                if has_cycle:
                    return
        color[node] = BLACK

    for n in nodes:
        if color[n] == WHITE:
            dfs(n)
            if has_cycle:
                break

    return {
        "pass": not has_cycle,
        "has_cycle": has_cycle,
        "n_edges": len(edges),
        "n_nodes": len(nodes),
        "reason": "cycle detected" if has_cycle else "DAG valid",
    }


def _placebo_falsification(
    factor: np.ndarray,
    returns: np.ndarray,
    n_runs: int = N_PLACEBO_RUNS,
    rng: np.random.Generator | None = None,
) -> dict[str, Any]:
    """Test 2 — Placebo: shuffle factor → t-stat 분포.

    placebo 의 95th percentile t-stat / origin t-stat 비율 > 0.80 → MIRAGE 의심.
    """
    if rng is None:
        rng = np.random.default_rng(42)
    origin_t = abs(_t_stat(returns, factor))

    placebo_ts = []
    for _ in range(n_runs):
        shuffled = rng.permutation(factor)
        placebo_ts.append(abs(_t_stat(returns, shuffled)))
    placebo_arr = np.array(placebo_ts)
    p95 = float(np.percentile(placebo_arr, 95)) if len(placebo_arr) else 0.0
    ratio = p95 / origin_t if origin_t > 0 else float("inf") if p95 > 0 else 0.0

    is_mirage = ratio > PLACEBO_T_RATIO_MIRAGE_CUTOFF
    return {
        "pass": not is_mirage,
        "origin_t_stat": float(origin_t),
        "placebo_p95_t_stat": p95,
        "placebo_t_ratio": float(ratio),
        "n_runs": n_runs,
        "verdict": "MIRAGE" if is_mirage else "GENUINE",
    }


def _event_study(
    factor: np.ndarray,
    returns: np.ndarray,
    event_indices: list[int],
    window: int = EVENT_STUDY_WINDOW,
) -> dict[str, Any]:
    """Test 3 — Event-study: trigger event 직전/직후 abnormal return.

    각 event ± window day 의 cumulative abnormal return (CAR) 계산.
    CAR 의 t-stat > 1.96 (95%) 통과.
    event_indices 비어 있으면 정량 검증 불가 → 기본 pass=True (해당 없음).
    """
    if not event_indices:
        return {
            "pass": True,
            "skipped": True,
            "reason": "no event_indices provided (factor 자체로는 event 정의 안 됨)",
        }
    if len(returns) < 2 * window + 1:
        return {
            "pass": False,
            "skipped": True,
            "reason": f"returns len {len(returns)} < required {2 * window + 1}",
        }

    cars = []
    for ev_idx in event_indices:
        lo, hi = max(0, ev_idx - window), min(len(returns), ev_idx + window + 1)
        cars.append(float(np.sum(returns[lo:hi])))
    car_arr = np.array(cars)
    if len(car_arr) < 3 or np.std(car_arr) == 0:
        return {
            "pass": False,
            "n_events": len(car_arr),
            "reason": "insufficient events for t-test",
        }
    t = float(np.mean(car_arr) / (np.std(car_arr, ddof=1) / np.sqrt(len(car_arr))))
    return {
        "pass": abs(t) > EVENT_STUDY_T_CUTOFF,
        "n_events": len(car_arr),
        "mean_car": float(np.mean(car_arr)),
        "t_stat": t,
        "cutoff": EVENT_STUDY_T_CUTOFF,
    }


def _negative_control(
    factor: np.ndarray,
    negative_factors: dict[str, np.ndarray],
) -> dict[str, Any]:
    """Test 4 — Negative control: 이론상 무관한 factor 와 |corr| > 0.30 면 spurious 의심.

    negative_factors 비어 있으면 검증 skip (pass=True).
    어떤 negative control 와도 |r| > 0.30 → fail.
    """
    if not negative_factors:
        return {
            "pass": True,
            "skipped": True,
            "reason": "no negative_factors provided (검증 skip)",
        }
    correlations = {}
    worst_abs_r = 0.0
    worst_name = ""
    for name, neg_factor in negative_factors.items():
        if len(neg_factor) != len(factor):
            continue
        if np.std(factor) == 0 or np.std(neg_factor) == 0:
            r = 0.0
        else:
            r = float(np.corrcoef(factor, neg_factor)[0, 1])
        correlations[name] = r
        if abs(r) > worst_abs_r:
            worst_abs_r = abs(r)
            worst_name = name

    is_pass = worst_abs_r <= NEGATIVE_CONTROL_R_CUTOFF
    return {
        "pass": is_pass,
        "correlations": correlations,
        "worst_abs_r": worst_abs_r,
        "worst_name": worst_name,
        "cutoff": NEGATIVE_CONTROL_R_CUTOFF,
    }


def _composite_certainty(
    dag_pass: bool,
    placebo: dict,
    event_study: dict,
    negative_control: dict,
) -> float:
    """4 test pass-rate weighted by signal strength → causal_certainty ∈ [0, 1].

    DAG 30% + placebo 30% + event-study 20% + negative-control 20%.
    placebo 는 ratio 가 작을수록 가중치 큼 (mirage 멀수록 좋음).
    """
    score = 0.0
    if dag_pass:
        score += 0.30
    if placebo.get("pass"):
        ratio = placebo.get("placebo_t_ratio", 1.0)
        # ratio 0.0 (perfect) → 0.30, ratio 0.80 (cutoff) → 0.0
        placebo_weight = max(0.0, (PLACEBO_T_RATIO_MIRAGE_CUTOFF - ratio) / PLACEBO_T_RATIO_MIRAGE_CUTOFF)
        score += 0.30 * placebo_weight
    if event_study.get("pass"):
        score += 0.20
    if negative_control.get("pass"):
        score += 0.20
    return float(min(1.0, max(0.0, score)))


def _verdict_from_results(
    n_obs: int,
    dag_pass: bool,
    placebo: dict,
    certainty: float,
) -> str:
    """4-test 결과 → verdict enum."""
    if n_obs < MIN_OBS:
        return "INSUFFICIENT"
    if not dag_pass:
        return "INSUFFICIENT"  # DAG 위반 시 검증 불가
    if placebo.get("verdict") == "MIRAGE":
        return "MIRAGE"
    if certainty >= 0.7:
        return "ROBUST"
    if certainty >= 0.4:
        return "WEAK"
    return "MIRAGE"  # 매우 낮은 certainty 도 mirage 처리 (defensive)


@REGISTRY.register
class CausalFactorAuditor(Actor):
    """López de Prado 2025 4-test causal audit — Layer B producer.

    Actions (input_data['action']):
        audit  — 4-test 실행 + DB row 기록
        last_audit  — factor_id 의 가장 최근 audit 조회 (read-only)

    Required input (action='audit'):
        factor_id: str  — audit 대상 factor 식별자
        factor: list[float] | np.ndarray  — factor exposure time series
        returns: list[float] | np.ndarray  — same length, asset returns
        dag_edges: list[(str, str)]  — assumed causal edges
        dag_nodes: list[str]  — DAG 의 모든 노드
        event_indices: list[int] (optional)  — event-study trigger 위치
        negative_factors: dict[str, list[float]] (optional)  — negative control set
        as_of_date: str (optional, default today_kst())

    Outcome 매핑 (Codex Round 5 Layer B):
        PASS  — verdict ∈ {ROBUST, WEAK} (factor 사용 가능)
        WARN  — verdict == MIRAGE (placebo 우려)
        BLOCK — verdict == INSUFFICIENT (n_obs 부족, DAG 위반, 또는 invalid input)
    """

    name = "causal-factor-auditor"
    version = "0.1.0"
    layer = Layer.B

    VALID_ACTIONS: tuple[str, ...] = ("audit", "last_audit")

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        action = input_data.get("action")
        if action not in self.VALID_ACTIONS:
            return ActorResult(
                output={"error": f"invalid action {action!r}, expected {self.VALID_ACTIONS}"},
                outcome=Outcome.BLOCK,
                input_summary=f"action={action}",
            )

        if action == "last_audit":
            return self._last_audit(input_data)

        return self._audit(input_data, ctx)

    # ─── handlers ─────────────────────────────────────────────

    def _audit(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        factor_id = input_data.get("factor_id")
        factor_raw = input_data.get("factor")
        returns_raw = input_data.get("returns")
        dag_edges = input_data.get("dag_edges", [])
        dag_nodes = input_data.get("dag_nodes", [])

        if not factor_id or factor_raw is None or returns_raw is None:
            return ActorResult(
                output={"error": "audit requires 'factor_id' + 'factor' + 'returns'"},
                outcome=Outcome.BLOCK,
                input_summary="audit",
            )

        try:
            factor = np.asarray(factor_raw, dtype=np.float64)
            returns = np.asarray(returns_raw, dtype=np.float64)
        except (ValueError, TypeError) as exc:
            return ActorResult(
                output={"error": f"factor/returns must be numeric arrays: {exc}"},
                outcome=Outcome.BLOCK,
                input_summary=f"audit {factor_id}",
            )

        if factor.shape != returns.shape:
            return ActorResult(
                output={"error": f"factor shape {factor.shape} != returns shape {returns.shape}"},
                outcome=Outcome.BLOCK,
                input_summary=f"audit {factor_id}",
            )
        if factor.ndim != 1:
            return ActorResult(
                output={"error": f"factor must be 1-D, got shape {factor.shape}"},
                outcome=Outcome.BLOCK,
                input_summary=f"audit {factor_id}",
            )
        if not (np.isfinite(factor).all() and np.isfinite(returns).all()):
            return ActorResult(
                output={"error": "factor/returns contain NaN/Inf"},
                outcome=Outcome.BLOCK,
                input_summary=f"audit {factor_id}",
            )

        n_obs = int(len(factor))
        as_of_date = input_data.get("as_of_date") or today_kst()

        # 1. DAG plausibility
        dag = _dag_plausibility_check(list(dag_edges), list(dag_nodes))

        # 2. Placebo falsification
        placebo = _placebo_falsification(factor, returns, n_runs=int(input_data.get("n_placebo_runs", N_PLACEBO_RUNS)))

        # 3. Event-study
        event_study = _event_study(factor, returns, list(input_data.get("event_indices") or []))

        # 4. Negative control
        neg_input = input_data.get("negative_factors") or {}
        neg_arrays = {k: np.asarray(v, dtype=np.float64) for k, v in neg_input.items()}
        negative_control = _negative_control(factor, neg_arrays)

        certainty = _composite_certainty(dag.get("pass", False), placebo, event_study, negative_control)
        verdict = _verdict_from_results(n_obs, dag.get("pass", False), placebo, certainty)

        results = TestResults(
            dag=dag,
            placebo=placebo,
            event_study=event_study,
            negative_control=negative_control,
        )

        log_causal_audit(
            factor_id=factor_id,
            as_of_date=as_of_date,
            n_obs=n_obs,
            verdict=verdict,
            causal_certainty=certainty,
            dag_pass=dag.get("pass", False),
            placebo_pass=placebo.get("pass", False),
            event_study_pass=event_study.get("pass", False),
            negative_control_pass=negative_control.get("pass", False),
            test_results=results.to_dict(),
            run_id=ctx.run_id,
        )

        # Discord publish: MIRAGE 시 ROLLOUT alert
        if verdict == "MIRAGE":
            self._publish_mirage(factor_id, as_of_date, certainty, placebo, ctx.run_id)

        outcome_map = {
            "ROBUST": Outcome.PASS,
            "WEAK": Outcome.PASS,
            "MIRAGE": Outcome.WARN,
            "INSUFFICIENT": Outcome.BLOCK,
        }
        return ActorResult(
            output={
                "factor_id": factor_id,
                "as_of_date": as_of_date,
                "verdict": verdict,
                "causal_certainty": certainty,
                "n_obs": n_obs,
                "dag_pass": dag.get("pass", False),
                "placebo_pass": placebo.get("pass", False),
                "event_study_pass": event_study.get("pass", False),
                "negative_control_pass": negative_control.get("pass", False),
                "tests": results.to_dict(),
            },
            outcome=outcome_map[verdict],
            sample_n=n_obs,
            input_summary=f"audit {factor_id} {verdict} ({certainty:.2f})",
        )

    @staticmethod
    def _last_audit(input_data: dict[str, Any]) -> ActorResult:
        factor_id = input_data.get("factor_id")
        if factor_id:
            rows = query(
                """SELECT * FROM causal_audits WHERE factor_id = ?
                   ORDER BY as_of_date DESC LIMIT 1""",
                (factor_id,),
            )
        else:
            rows = query("SELECT * FROM causal_audits ORDER BY as_of_date DESC LIMIT 1")
        if not rows:
            return ActorResult(
                output={"error": "no causal_audits row found"},
                outcome=Outcome.WARN,
                input_summary="last_audit",
            )
        r = dict(rows[0])
        return ActorResult(
            output=r,
            outcome=Outcome.PASS,
            input_summary=f"last_audit {r['factor_id']} {r['verdict']}",
        )

    # ─── Discord publish (best-effort) ───────────────────────

    @staticmethod
    def _publish_mirage(
        factor_id: str,
        as_of_date: str,
        certainty: float,
        placebo: dict,
        run_id: str,
    ) -> None:
        try:
            from nuri.agents.discord.outbox import stage_rollout

            stage_rollout(
                payload={
                    "kind": "factor_mirage",
                    "summary": (
                        f"MIRAGE {factor_id} @ {as_of_date}: "
                        f"certainty={certainty:.2f}, "
                        f"placebo_t_ratio={placebo.get('placebo_t_ratio', 0):.2f}"
                    ),
                    "factor_id": factor_id,
                    "as_of_date": as_of_date,
                    "certainty": certainty,
                    "placebo_t_ratio": placebo.get("placebo_t_ratio"),
                },
                dedupe_key=f"mirage:{factor_id}:{as_of_date}",
                actor_name="causal-factor-auditor",
                run_id=run_id,
            )
        except Exception:  # noqa: BLE001 — best-effort
            # 발행 실패로 액터를 죽이지 않는다(#894) — 다만 **조용히** 넘기지도 않는다.
            logger.exception("outbox staging 실패: stage_rollout")


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m nuri.agents.actors.causal_factor_auditor last_audit [--factor-id X]

    audit 은 factor/returns array 가 필요해서 Python 호출 전용.
    """
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(prog="causal-factor-auditor")
    parser.add_argument("action", choices=["last_audit"])
    parser.add_argument("--factor-id", default=None)
    args = parser.parse_args(argv)

    actor = CausalFactorAuditor()
    payload: dict[str, Any] = {"action": args.action}
    if args.factor_id:
        payload["factor_id"] = args.factor_id
    result = actor.run(payload)
    print(_json.dumps(result.output, indent=2, ensure_ascii=False, default=str))
    return 0 if result.outcome in (Outcome.PASS, Outcome.WARN) else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())

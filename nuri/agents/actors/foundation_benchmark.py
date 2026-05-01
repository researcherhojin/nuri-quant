"""FoundationBenchmark — Layer B actor (#529 Phase 2 — canonical #7).

Foundation time-series 모델 (TimesFM / Chronos / Moirai 등) 을 우리 sticky-HMM
baseline 과 *동일 protocol* 로 벤치마킹 — "신모델이라 좋아 보이는" 착시 방지.

Layer B 설계 (Codex Round 5):
- 100% deterministic — 통계적 비교만, ZERO LLM
- 모든 결과 foundation_benchmarks 영구 기록 (audit-traceable)
- WalkForwardValidator pit_hash 와 join 가능 (동일 fold spec 보장)
- caller-injected metric value (model inference 는 호출자 책임 — pluggable)

본 PR 범위 (infrastructure only):
- benchmark / compare / list_runs 3 actions
- TimesFM/Chronos 실제 inference X (heavy dep — 별도 PR)
- caller 가 metric_value 계산 → 전달 → 기록 + 비교
- sticky-HMM baseline 과 placeholder foundation 둘 다 비교 가능

Anti-pattern 방지 (lock-test):
- 단일 model 만 등록 → compare 시 WARN (비교 불가)
- benchmark_run 미존재 → BLOCK (오타 catch)
- model_kind / metric_name enum 위반 → BLOCK (helper level)

Discord publish:
- compare 결과 foundation 이 baseline 대비 *유의미* (>10% 개선) → ROLLOUT (GREEN)
- baseline 우수 / 비등 → publish X (정상)
- benchmark / list_runs publish X (read-only / 단일 기록 noise 차단)
"""

from __future__ import annotations

from typing import Any, Optional

from nuri.agents.base import REGISTRY, Actor, ActorResult, Layer, Outcome, RunContext
from nuri.core.db import (
    log_foundation_benchmark,
    query,
)

# higher_is_better 방향 — caller 가 명시 안 하면 metric_name 으로 기본값 산출.
_DEFAULT_HIGHER_IS_BETTER: dict[str, bool] = {
    "brier": False,
    "logloss": False,
    "mse": False,
    "mae": False,
    "sharpe": True,
    "hit_rate": True,
}

# foundation 우수 판정 임계값 — baseline 대비 10% 이상 개선.
SIGNIFICANT_IMPROVEMENT_PCT = 0.10


@REGISTRY.register
class FoundationBenchmark(Actor):
    """Foundation vs baseline cross-model benchmark — Layer B.

    Actions (input_data['action']):
        benchmark   — 단일 model 의 단일 metric 측정 + 기록
        compare     — 동일 benchmark_run 의 model 결과 비교 → winner + delta
        list_runs   — 최근 benchmark_run 목록 (read-only)

    Outcome 매핑 (Codex Round 5 Layer B):
        benchmark  — PASS (기록 자체는 항상 성공)
        compare    — PASS (>=2 model 비교 가능) / WARN (단 1개) / BLOCK (run 미존재)
        list_runs  — PASS
        invalid    — BLOCK
    """

    name = "foundation-benchmark"
    version = "0.1.0"
    layer = Layer.B

    VALID_ACTIONS: tuple[str, ...] = ("benchmark", "compare", "list_runs")
    VALID_KINDS: tuple[str, ...] = ("baseline", "foundation", "traditional")
    VALID_METRICS: tuple[str, ...] = (
        "brier", "logloss", "sharpe", "mse", "mae", "hit_rate",
    )

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        action = input_data.get("action")
        if action not in self.VALID_ACTIONS:
            return ActorResult(
                output={"error": f"invalid action {action!r}, expected {self.VALID_ACTIONS}"},
                outcome=Outcome.BLOCK,
                input_summary=f"action={action}",
            )

        if action == "benchmark":
            return self._benchmark(input_data, ctx)
        if action == "compare":
            return self._compare(input_data, ctx)
        return self._list_runs(input_data)

    # ─── benchmark ────────────────────────────────────────────

    def _benchmark(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        """단일 model 의 단일 metric 측정 결과 기록."""
        # 필수 input 검증
        required = ("benchmark_run", "model_id", "model_kind", "metric_name", "metric_value", "sample_n")
        missing = [k for k in required if k not in input_data]
        if missing:
            return ActorResult(
                output={"error": f"benchmark requires {required}, missing {missing}"},
                outcome=Outcome.BLOCK,
                input_summary="benchmark",
            )

        benchmark_run = str(input_data["benchmark_run"])
        model_id = str(input_data["model_id"])
        model_kind = str(input_data["model_kind"])
        metric_name = str(input_data["metric_name"])

        if model_kind not in self.VALID_KINDS:
            return ActorResult(
                output={"error": f"model_kind {model_kind!r} not in {self.VALID_KINDS}"},
                outcome=Outcome.BLOCK,
                input_summary=f"benchmark {model_id}",
            )
        if metric_name not in self.VALID_METRICS:
            return ActorResult(
                output={"error": f"metric_name {metric_name!r} not in {self.VALID_METRICS}"},
                outcome=Outcome.BLOCK,
                input_summary=f"benchmark {model_id}",
            )

        try:
            metric_value = float(input_data["metric_value"])
            sample_n = int(input_data["sample_n"])
        except (TypeError, ValueError) as exc:
            return ActorResult(
                output={"error": f"metric_value/sample_n cast failed: {exc}"},
                outcome=Outcome.BLOCK,
                input_summary=f"benchmark {model_id}",
            )
        if sample_n < 0:
            return ActorResult(
                output={"error": f"sample_n must be >= 0, got {sample_n}"},
                outcome=Outcome.BLOCK,
                input_summary=f"benchmark {model_id}",
            )

        # higher_is_better 기본값 (caller override 가능)
        higher_is_better = bool(
            input_data.get("higher_is_better", _DEFAULT_HIGHER_IS_BETTER[metric_name])
        )

        try:
            benchmark_id = log_foundation_benchmark(
                benchmark_run=benchmark_run,
                model_id=model_id,
                model_kind=model_kind,
                metric_name=metric_name,
                metric_value=metric_value,
                higher_is_better=higher_is_better,
                sample_n=sample_n,
                pit_hash=input_data.get("pit_hash"),
                walkforward_run_id=input_data.get("walkforward_run_id"),
                notes=input_data.get("notes"),
                actor_run_id=ctx.run_id,
            )
        except ValueError as exc:  # helper enum / sample_n violation
            return ActorResult(
                output={"error": f"helper rejected: {exc}"},
                outcome=Outcome.BLOCK,
                input_summary=f"benchmark {model_id}",
            )

        return ActorResult(
            output={
                "benchmark_id": benchmark_id,
                "benchmark_run": benchmark_run,
                "model_id": model_id,
                "model_kind": model_kind,
                "metric_name": metric_name,
                "metric_value": metric_value,
                "higher_is_better": higher_is_better,
                "sample_n": sample_n,
            },
            outcome=Outcome.PASS,
            sample_n=sample_n,
            input_summary=f"benchmark {model_id} {metric_name}={metric_value:.4f}",
        )

    # ─── compare ──────────────────────────────────────────────

    def _compare(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        """동일 benchmark_run 의 여러 model 결과 비교."""
        benchmark_run = input_data.get("benchmark_run")
        if not benchmark_run:
            return ActorResult(
                output={"error": "compare requires 'benchmark_run'"},
                outcome=Outcome.BLOCK,
                input_summary="compare",
            )

        metric_filter = input_data.get("metric_name")
        model_filter = input_data.get("model_ids")

        sql = "SELECT benchmark_id, model_id, model_kind, metric_name, metric_value, higher_is_better, sample_n FROM foundation_benchmarks WHERE benchmark_run = ?"
        params: list[Any] = [benchmark_run]
        if metric_filter:
            if metric_filter not in self.VALID_METRICS:
                return ActorResult(
                    output={"error": f"metric_name {metric_filter!r} not in {self.VALID_METRICS}"},
                    outcome=Outcome.BLOCK,
                    input_summary=f"compare {benchmark_run}",
                )
            sql += " AND metric_name = ?"
            params.append(metric_filter)
        if model_filter:
            if not isinstance(model_filter, list) or not all(isinstance(m, str) for m in model_filter):
                return ActorResult(
                    output={"error": "model_ids must be list[str]"},
                    outcome=Outcome.BLOCK,
                    input_summary=f"compare {benchmark_run}",
                )
            placeholders = ",".join("?" * len(model_filter))
            sql += f" AND model_id IN ({placeholders})"
            params.extend(model_filter)
        sql += " ORDER BY metric_name, model_id"

        rows = [dict(r) for r in query(sql, tuple(params))]
        if not rows:
            return ActorResult(
                output={
                    "error": f"benchmark_run {benchmark_run!r} not found",
                    "benchmark_run": benchmark_run,
                },
                outcome=Outcome.BLOCK,
                input_summary=f"compare {benchmark_run}",
            )

        # metric 별 그룹핑 → winner + delta 계산
        per_metric: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            per_metric.setdefault(r["metric_name"], []).append(r)

        comparisons: list[dict[str, Any]] = []
        any_significant_foundation_win = False
        for metric_name, group in per_metric.items():
            if len(group) < 2:
                comparisons.append({
                    "metric_name": metric_name,
                    "n_models": len(group),
                    "verdict": "insufficient_models",
                    "models": group,
                })
                continue
            higher_is_better = bool(group[0]["higher_is_better"])
            ranked = sorted(
                group,
                key=lambda x: x["metric_value"],
                reverse=higher_is_better,
            )
            winner = ranked[0]
            runner = ranked[1]
            # baseline vs foundation 비교 — foundation 이 winner 이고 baseline runner 면 delta 산출
            delta = self._relative_improvement(
                winner["metric_value"], runner["metric_value"], higher_is_better
            )
            verdict = self._verdict(winner, runner, delta)
            if verdict == "foundation_wins_significantly":
                any_significant_foundation_win = True
            comparisons.append({
                "metric_name": metric_name,
                "n_models": len(group),
                "winner_model_id": winner["model_id"],
                "winner_kind": winner["model_kind"],
                "winner_value": winner["metric_value"],
                "runner_model_id": runner["model_id"],
                "runner_kind": runner["model_kind"],
                "runner_value": runner["metric_value"],
                "delta_relative": delta,
                "higher_is_better": higher_is_better,
                "verdict": verdict,
                "ranked_models": ranked,
            })

        # 단 1개 model 만 등록된 경우 (모든 metric 그룹이 insufficient_models) → WARN
        all_insufficient = all(c["verdict"] == "insufficient_models" for c in comparisons)
        outcome = Outcome.WARN if all_insufficient else Outcome.PASS

        # Discord publish — foundation 유의미 우수 시만
        if any_significant_foundation_win:
            self._publish_rollout(benchmark_run, comparisons, ctx.run_id)

        return ActorResult(
            output={
                "benchmark_run": benchmark_run,
                "n_rows": len(rows),
                "n_metrics": len(per_metric),
                "comparisons": comparisons,
                "any_foundation_significant_win": any_significant_foundation_win,
            },
            outcome=outcome,
            sample_n=len(rows),
            input_summary=f"compare {benchmark_run} metrics={len(per_metric)} rows={len(rows)}",
        )

    @staticmethod
    def _relative_improvement(
        winner_val: float, runner_val: float, higher_is_better: bool
    ) -> float:
        """winner 가 runner 대비 얼마나 우수한가 — relative pct (0.10 = 10% 개선).

        higher_is_better=True 일 때: (winner - runner) / |runner|
        higher_is_better=False 일 때: (runner - winner) / |runner|
        runner_val == 0 → 0 (degenerate avoid div-by-zero).
        """
        if runner_val == 0:
            return 0.0
        if higher_is_better:
            return (winner_val - runner_val) / abs(runner_val)
        return (runner_val - winner_val) / abs(runner_val)

    @staticmethod
    def _verdict(winner: dict[str, Any], runner: dict[str, Any], delta: float) -> str:
        """human-readable verdict.

        foundation_wins_significantly — foundation kind winner + delta >= 10%
        baseline_robust              — baseline kind winner
        traditional_wins             — traditional kind winner (참고용)
        foundation_wins_marginal     — foundation winner but delta < 10% (실용성 낮음)
        tie                          — delta < 1%
        """
        if abs(delta) < 0.01:
            return "tie"
        winner_kind = winner.get("model_kind", "")
        if winner_kind == "foundation":
            if delta >= SIGNIFICANT_IMPROVEMENT_PCT:
                return "foundation_wins_significantly"
            return "foundation_wins_marginal"
        if winner_kind == "baseline":
            return "baseline_robust"
        return "traditional_wins"

    # ─── list_runs ────────────────────────────────────────────

    @staticmethod
    def _list_runs(input_data: dict[str, Any]) -> ActorResult:
        try:
            limit = int(input_data.get("limit", 10))
        except (TypeError, ValueError):
            return ActorResult(
                output={"error": "limit must be int"},
                outcome=Outcome.BLOCK,
                input_summary="list_runs",
            )
        if limit <= 0:
            return ActorResult(
                output={"error": f"limit must be > 0, got {limit}"},
                outcome=Outcome.BLOCK,
                input_summary="list_runs",
            )

        rows = query(
            """SELECT benchmark_run, MIN(created_at) AS first_seen,
                      COUNT(*) AS n_rows, COUNT(DISTINCT model_id) AS n_models
               FROM foundation_benchmarks
               GROUP BY benchmark_run
               ORDER BY first_seen DESC
               LIMIT ?""",
            (limit,),
        )
        runs = [dict(r) for r in rows]
        return ActorResult(
            output={"runs": runs, "n_runs": len(runs), "limit": limit},
            outcome=Outcome.PASS,
            sample_n=len(runs),
            input_summary=f"list_runs limit={limit} → {len(runs)}",
        )

    # ─── Discord publish (best-effort) ────────────────────────

    @staticmethod
    def _publish_rollout(
        benchmark_run: str,
        comparisons: list[dict[str, Any]],
        run_id: str,
    ) -> None:
        """foundation 우수 시 ROLLOUT 채널에 promotion 권고. 실패해도 actor outcome 영향 X."""
        try:
            from nuri.agents.discord.publisher import Channel, DiscordPublisher

            wins = [c for c in comparisons if c.get("verdict") == "foundation_wins_significantly"]
            lines = []
            for c in wins:
                lines.append(
                    f"- **{c['metric_name']}**: {c['winner_model_id']} "
                    f"({c['winner_value']:.4f}) > {c['runner_model_id']} "
                    f"({c['runner_value']:.4f}) — Δ {c['delta_relative'] * 100:.1f}%"
                )
            embed = {
                "title": f"Foundation model win — {benchmark_run}",
                "description": (
                    "Consider promotion — foundation model significantly outperforms baseline "
                    f"on {len(wins)} metric(s):\n" + "\n".join(lines)
                ),
                "color": 0x2ECC71,
                "footer": {"text": f"nuri-quant • foundation-benchmark • run_id={run_id[:8]}"},
            }
            DiscordPublisher().publish_embed(
                Channel.ROLLOUT,
                embed=embed,
                actor_name="foundation-benchmark",
                run_id=run_id,
            )
        except Exception:  # noqa: BLE001
            pass


def main(argv: Optional[list[str]] = None) -> int:
    """CLI: python -m nuri.agents.actors.foundation_benchmark {benchmark,compare,list_runs}"""
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(prog="foundation-benchmark")
    parser.add_argument("action", choices=["benchmark", "compare", "list_runs"])
    parser.add_argument("--benchmark-run", default=None)
    parser.add_argument("--model-id", default=None)
    parser.add_argument(
        "--model-kind", default="baseline", choices=["baseline", "foundation", "traditional"]
    )
    parser.add_argument(
        "--metric-name",
        default="brier",
        choices=["brier", "logloss", "sharpe", "mse", "mae", "hit_rate"],
    )
    parser.add_argument("--metric-value", type=float, default=None)
    parser.add_argument("--sample-n", type=int, default=0)
    parser.add_argument("--higher-is-better", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)

    actor = FoundationBenchmark()
    payload: dict[str, Any] = {"action": args.action}
    if args.action == "benchmark":
        if not args.benchmark_run or not args.model_id or args.metric_value is None:
            print(_json.dumps({"error": "benchmark needs --benchmark-run --model-id --metric-value"}))
            return 2
        payload.update(
            {
                "benchmark_run": args.benchmark_run,
                "model_id": args.model_id,
                "model_kind": args.model_kind,
                "metric_name": args.metric_name,
                "metric_value": args.metric_value,
                "sample_n": args.sample_n,
                "higher_is_better": args.higher_is_better,
            }
        )
    elif args.action == "compare":
        if not args.benchmark_run:
            print(_json.dumps({"error": "compare needs --benchmark-run"}))
            return 2
        payload["benchmark_run"] = args.benchmark_run
    else:
        payload["limit"] = args.limit

    result = actor.run(payload)
    print(_json.dumps(result.output, indent=2, ensure_ascii=False, default=str))
    return 0 if result.outcome in (Outcome.PASS, Outcome.WARN) else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())

"""FreshnessGatekeeper — Layer A actor (#529 Phase 2 Codex Round 5 inventory #2).

Responsibilities:
- 데이터 freshness policy 검증 (nuri.core.freshness 위임)
- stale data 기반 emit 차단 (PASS / WARN / BLOCK)
- audit trail 영구 기록 (모든 게이트 결정)

Layer A 설계 (Codex Round 5 mandatory #3):
- 100% rule-based — FRESHNESS_POLICIES (config) + age_hours 비교
- ZERO LLM — 차단 결정에 추론 의존 X
- Layer B (collector-orchestrator), Layer C (sre-incident) 와 분리

Anti-pattern 방지:
- Stale data 추천 발행 (#532 KIS token issue 와 짝패) → BLOCK
- WARN 무시 → audit_ledger 영구 기록 + Drift-Sentinel 향후 watch
"""

from __future__ import annotations

from typing import Any

from nuri.agents.base import REGISTRY, Actor, ActorResult, Layer, Outcome, RunContext
from nuri.core.freshness import (
    FRESHNESS_POLICIES,
    check_all_freshness,
    check_freshness,
)


@REGISTRY.register
class FreshnessGatekeeper(Actor):
    """Data freshness enforcement gate.

    Actions (input_data['action']):
        check  — 단일 key freshness 검증 (key 필수)
        check_all  — 모든 FRESHNESS_POLICIES 검증
        list_policies  — 등록된 policy keys 조회 (read-only)

    Outcome 매핑 (Codex Round 5 Layer A enforcement):
        PASS  — 모든 체크 status=PASS
        WARN  — 일부 status=WARN (emit 가능, alert 필요)
        BLOCK — 일부 status=FAIL (emit 차단)
        BLOCK — invalid input
    """

    name = "freshness-gatekeeper"
    version = "0.1.0"
    layer = Layer.A

    VALID_ACTIONS: tuple[str, ...] = ("check", "check_all", "list_policies")

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        action = input_data.get("action")

        if action not in self.VALID_ACTIONS:
            return ActorResult(
                output={"error": f"invalid action {action!r}, expected {self.VALID_ACTIONS}"},
                outcome=Outcome.BLOCK,
                input_summary=f"action={action}",
            )

        if action == "list_policies":
            return ActorResult(
                output={"policies": sorted(FRESHNESS_POLICIES.keys())},
                outcome=Outcome.PASS,
                sample_n=len(FRESHNESS_POLICIES),
                input_summary="list_policies",
            )

        if action == "check":
            key = input_data.get("key")
            if not key or not isinstance(key, str):
                return ActorResult(
                    output={"error": "key (str) required for check"},
                    outcome=Outcome.BLOCK,
                    input_summary="check (no key)",
                )
            if key not in FRESHNESS_POLICIES:
                return ActorResult(
                    output={
                        "error": f"unknown key {key!r}",
                        "available": sorted(FRESHNESS_POLICIES.keys()),
                    },
                    outcome=Outcome.BLOCK,
                    input_summary=f"check {key}",
                )

            result = check_freshness(key)
            return ActorResult(
                output=result,
                outcome=self._status_to_outcome(result["status"]),
                sample_n=1,
                input_summary=f"check {key} → {result['status']} ({result.get('age_hours', '?')}h)",
            )

        # action == "check_all"
        results = check_all_freshness()
        statuses = [r["status"] for r in results]
        # 가장 나쁜 status 가 outcome 결정 (worst-case enforcement)
        if "FAIL" in statuses:
            outcome = Outcome.BLOCK
        elif "WARN" in statuses:
            outcome = Outcome.WARN
        else:
            outcome = Outcome.PASS

        return ActorResult(
            output={
                "results": results,
                "summary": {
                    "pass": statuses.count("PASS"),
                    "warn": statuses.count("WARN"),
                    "fail": statuses.count("FAIL"),
                    "total": len(statuses),
                },
            },
            outcome=outcome,
            sample_n=len(results),
            input_summary=f"check_all → {statuses.count('PASS')}/{len(statuses)} pass",
        )

    @staticmethod
    def _status_to_outcome(status: str) -> Outcome:
        """nuri.core.freshness status 문자열 → Outcome 매핑."""
        return {
            "PASS": Outcome.PASS,
            "WARN": Outcome.WARN,
            "FAIL": Outcome.BLOCK,
        }.get(status, Outcome.ERROR)


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m nuri.agents.actors.freshness_gatekeeper <action> [key]

    Examples:
        python -m nuri.agents.actors.freshness_gatekeeper list_policies
        python -m nuri.agents.actors.freshness_gatekeeper check --key prices
        python -m nuri.agents.actors.freshness_gatekeeper check_all
    """
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(prog="freshness-gatekeeper")
    parser.add_argument("action", choices=FreshnessGatekeeper.VALID_ACTIONS)
    parser.add_argument("--key", help="freshness policy key (required for 'check')")

    args = parser.parse_args(argv)
    input_data: dict[str, Any] = {"action": args.action}
    if args.key:
        input_data["key"] = args.key

    actor = FreshnessGatekeeper()
    try:
        result = actor.run(input_data)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2

    print(json.dumps(result.output, indent=2, ensure_ascii=False, default=str))
    if result.outcome == Outcome.PASS:
        return 0
    if result.outcome == Outcome.WARN:
        return 1
    return 2  # BLOCK or ERROR


if __name__ == "__main__":
    import sys

    sys.exit(main())

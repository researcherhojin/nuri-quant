"""ReleaseRollbackManager — Layer A actor for canary rollout + emergency rollback (#529).

Codex Round 5 Phase 6 → Phase 2 로 promote (사용자 dogfooding 요청).
이 actor 가 PR workflow 자동화의 첫 building block.

Responsibilities (Codex Round 5 inventory #13):
- hypothesis rollout (canary scope: paper → partial → full)
- rollback (즉시 disable + audit + reason 기록)
- schema-compat 체크 (out of scope for v0)

Layer A 설계 (Codex Round 5 mandatory #3):
- 100% rule-based, ZERO LLM
- 모든 결정 audit_ledger + run_ledger 영구 기록
- LLM down 이어도 정상 작동 (graceful degradation 보장)

Anti-pattern 방지:
- Knight Capital 2012-08-01 (배포 실패 4M+ 오류주문) → canary scope 강제
- 양방향 SQLite write (Codex Round 5 mandatory #1) → flag 변경은 single-writer 만
"""

from __future__ import annotations

from typing import Any

from nuri.agents.base import REGISTRY, Actor, ActorResult, Layer, Outcome, RunContext
from nuri.core.db import is_feature_enabled, set_feature_flag


@REGISTRY.register
class ReleaseRollbackManager(Actor):
    """Canary rollout + emergency rollback enforcement.

    Actions (input_data['action']):
        enable    — flag enable (canary_scope 필수: paper/partial/full)
        rollback  — flag immediate disable (reason 필수, audit 영구 기록)
        status    — flag enabled 상태 + canary_scope 조회 (read-only)

    Returns:
        ActorResult with outcome:
            PASS  — action 성공
            BLOCK — invalid input 또는 권한 부족 (state 변경 X)
            ERROR — DB exception (base.run() 가 처리)
    """

    name = "release-rollback-manager"
    version = "0.1.0"
    layer = Layer.A

    VALID_ACTIONS: tuple[str, ...] = ("enable", "rollback", "status")
    VALID_SCOPES: tuple[str, ...] = ("paper", "partial", "full")

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        action = input_data.get("action")
        flag = input_data.get("flag")

        # Layer A enforcement: input validation 먼저
        if action not in self.VALID_ACTIONS:
            return ActorResult(
                output={"error": f"invalid action {action!r}, expected {self.VALID_ACTIONS}"},
                outcome=Outcome.BLOCK,
                input_summary=f"action={action}",
            )
        if not flag or not isinstance(flag, str):
            return ActorResult(
                output={"error": "flag (str) required"},
                outcome=Outcome.BLOCK,
                input_summary=f"action={action}",
            )

        if action == "enable":
            scope = input_data.get("canary_scope")
            if scope not in self.VALID_SCOPES:
                return ActorResult(
                    output={"error": f"canary_scope required for enable, got {scope!r}"},
                    outcome=Outcome.BLOCK,
                    input_summary=f"enable {flag}",
                )
            owner = input_data.get("owner", "release-rollback-manager")
            description = input_data.get("description")
            set_feature_flag(flag, enabled=True, canary_scope=scope, owner=owner, description=description)
            new_state = is_feature_enabled(flag)
            return ActorResult(
                output={
                    "action": "enable",
                    "flag": flag,
                    "canary_scope": scope,
                    "enabled": new_state,
                },
                outcome=Outcome.PASS,
                sample_n=1,
                input_summary=f"enable {flag} scope={scope}",
            )

        if action == "rollback":
            reason = input_data.get("reason")
            if not reason:
                return ActorResult(
                    output={"error": "reason required for rollback (audit trail mandatory)"},
                    outcome=Outcome.BLOCK,
                    input_summary=f"rollback {flag}",
                )
            owner = input_data.get("owner", "release-rollback-manager")
            set_feature_flag(flag, enabled=False, owner=owner, disabled_reason=reason)
            new_state = is_feature_enabled(flag)
            assert new_state is False, "rollback failed — flag still enabled"
            return ActorResult(
                output={
                    "action": "rollback",
                    "flag": flag,
                    "enabled": new_state,
                    "reason": reason,
                },
                outcome=Outcome.PASS,
                sample_n=1,
                input_summary=f"rollback {flag}: {reason[:60]}",
            )

        # action == "status"
        enabled = is_feature_enabled(flag)
        return ActorResult(
            output={"action": "status", "flag": flag, "enabled": enabled},
            outcome=Outcome.PASS,
            sample_n=1,
            input_summary=f"status {flag}",
        )


def main(argv: list[str] | None = None) -> int:
    """CLI entry: python -m nuri.agents.actors.release_rollback_manager <action> ...

    Examples:
        python -m nuri.agents.actors.release_rollback_manager enable cycle_engine_v1 --scope paper
        python -m nuri.agents.actors.release_rollback_manager rollback cycle_engine_v1 \\
            --reason "Sharpe dropped below 0.5"
        python -m nuri.agents.actors.release_rollback_manager status cycle_engine_v1
    """
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(prog="release-rollback-manager")
    parser.add_argument("action", choices=ReleaseRollbackManager.VALID_ACTIONS)
    parser.add_argument("flag", help="feature flag name")
    parser.add_argument(
        "--scope",
        choices=ReleaseRollbackManager.VALID_SCOPES,
        help="canary scope (required for enable)",
    )
    parser.add_argument("--reason", help="rollback reason (required for rollback)")
    parser.add_argument("--owner", default="cli", help="owner for audit trail")
    parser.add_argument("--description", help="optional description")

    args = parser.parse_args(argv)

    input_data: dict[str, Any] = {
        "action": args.action,
        "flag": args.flag,
        "owner": args.owner,
    }
    if args.scope:
        input_data["canary_scope"] = args.scope
    if args.reason:
        input_data["reason"] = args.reason
    if args.description:
        input_data["description"] = args.description

    actor = ReleaseRollbackManager()
    try:
        result = actor.run(input_data)
    except Exception as exc:  # pragma: no cover — base.run() catches all execute() exceptions
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2

    print(json.dumps(result.output, indent=2, ensure_ascii=False))
    return 0 if result.outcome == Outcome.PASS else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())

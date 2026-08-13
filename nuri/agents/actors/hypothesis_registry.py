"""HypothesisRegistry — Layer A actor (#529 Phase 2 — canonical #4).

Responsibilities (Codex Round 5 #128, #130, #347, #350):
- producer actor (RegimePosterior 등) 의 claim 을 hypothesis 로 등록
- lifecycle gate: open → validated|rejected|expired (status machine)
- emit 허가 결정: validated + 만료 X 만 PASS, 그 외 BLOCK
- feature_flag + canary_scope 으로 Release-Rollback-Manager 와 join

Layer A 설계 (ZERO LLM, 100% rule):
- 모든 action 이 outcome 반환 필수 (PASS / BLOCK / WARN)
- status 전이는 helper (db.validate_hypothesis / reject_hypothesis) 가 강제
- expiry 는 deterministic 날짜 비교

Anti-pattern 방지 (lock-test):
- validation_metrics 없이 validated 로 변경 → ValueError (helper 단)
- rejection_reason 없이 rejected 로 변경 → ValueError
- expired/rejected hypothesis emit 시도 → BLOCK
- validated 재validate → ValueError (status machine 위반)
- 동일 (producer + claim) 중복 register → idempotent (기존 id 반환, is_new=False)

Discord publish:
- validated → ROLLOUT embed (validation metrics 포함)
- rejected → ROLLOUT embed (rejection reason 포함)
- best-effort: publish 실패해도 actor outcome 영향 X
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from nuri.agents.base import REGISTRY, Actor, ActorResult, Layer, Outcome, RunContext
from nuri.core.db import (
    expire_hypotheses,
    query,
    register_hypothesis,
    reject_hypothesis,
    validate_hypothesis,
)
from nuri.core.timezone import today_kst

logger = logging.getLogger(__name__)

DEFAULT_EXPIRY_DAYS = 90  # Codex: hypothesis 가 90 일 내 검증 못 받으면 stale


@REGISTRY.register
class HypothesisRegistry(Actor):
    """Hypothesis lifecycle gate — Layer A enforcement.

    Actions (input_data['action']):
        register  — 신규 hypothesis 등록 (idempotent on claim_hash)
        validate  — open → validated (validation_metrics 필수)
        reject    — open → rejected (rejection_reason 필수)
        expire    — 만료 일자 지난 open 일괄 처리 (cron-style)
        check_emit — hypothesis_id 의 emit 허가 여부 결정 (PASS/BLOCK)
        list_open — 현재 open 상태 hypothesis 목록 (read-only)

    Outcome 매핑 (Codex Round 5 Layer A enforcement):
        register → PASS (신규/idempotent 둘 다)
        validate → PASS (성공) / BLOCK (실패 — status machine 위반)
        reject   → PASS / BLOCK
        expire   → PASS (개수 보고)
        check_emit:
          PASS  — validated + expiry_date >= today
          BLOCK — expired / rejected / open / 미존재
        list_open → PASS
    """

    name = "hypothesis-registry"
    version = "0.1.0"
    layer = Layer.A

    VALID_ACTIONS: tuple[str, ...] = (
        "register",
        "validate",
        "reject",
        "expire",
        "check_emit",
        "list_open",
    )

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        action = input_data.get("action")

        if action not in self.VALID_ACTIONS:
            return ActorResult(
                output={"error": f"invalid action {action!r}, expected {self.VALID_ACTIONS}"},
                outcome=Outcome.BLOCK,
                input_summary=f"action={action}",
            )

        if action == "register":
            return self._register(input_data, ctx)
        if action == "validate":
            return self._validate(input_data, ctx)
        if action == "reject":
            return self._reject(input_data, ctx)
        if action == "expire":
            return self._expire()
        if action == "check_emit":
            return self._check_emit(input_data)
        return self._list_open()

    # ─── handlers ─────────────────────────────────────────────

    @staticmethod
    def _register(input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        required = ("hypothesis_id", "name", "version", "producer_actor", "claim_text", "evidence")
        for key in required:
            if input_data.get(key) is None:
                return ActorResult(
                    output={"error": f"register requires {key!r}"},
                    outcome=Outcome.BLOCK,
                    input_summary="register",
                )

        # default expiry = today + 90d (Codex: stale prevention)
        expiry_date = input_data.get("expiry_date")
        if not expiry_date:
            today_str = today_kst()
            from datetime import date

            today_obj = date.fromisoformat(today_str)
            expiry_date = (today_obj + timedelta(days=DEFAULT_EXPIRY_DAYS)).isoformat()

        try:
            hid, is_new = register_hypothesis(
                hypothesis_id=input_data["hypothesis_id"],
                name=input_data["name"],
                version=input_data["version"],
                producer_actor=input_data["producer_actor"],
                producer_run_id=input_data.get("producer_run_id") or ctx.run_id,
                claim_text=input_data["claim_text"],
                evidence=input_data["evidence"],
                expiry_date=expiry_date,
                feature_flag=input_data.get("feature_flag"),
                canary_scope=input_data.get("canary_scope"),
            )
        except ValueError as exc:
            return ActorResult(
                output={"error": str(exc)},
                outcome=Outcome.BLOCK,
                input_summary="register",
            )

        return ActorResult(
            output={"hypothesis_id": hid, "is_new": is_new, "expiry_date": expiry_date},
            outcome=Outcome.PASS,
            input_summary=f"register {hid} (new={is_new})",
        )

    def _validate(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        hid = input_data.get("hypothesis_id")
        metrics = input_data.get("validation_metrics")
        if not hid or not metrics:
            return ActorResult(
                output={"error": "validate requires 'hypothesis_id' + 'validation_metrics'"},
                outcome=Outcome.BLOCK,
                input_summary="validate",
            )
        try:
            validate_hypothesis(hid, metrics)
        except ValueError as exc:
            return ActorResult(
                output={"error": str(exc), "hypothesis_id": hid},
                outcome=Outcome.BLOCK,
                input_summary=f"validate {hid}",
            )

        self._publish_lifecycle("validated", hid, ctx.run_id, extra={"metrics": metrics})
        return ActorResult(
            output={"hypothesis_id": hid, "status": "validated"},
            outcome=Outcome.PASS,
            input_summary=f"validate {hid}",
        )

    def _reject(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        hid = input_data.get("hypothesis_id")
        reason = input_data.get("rejection_reason")
        if not hid or not reason:
            return ActorResult(
                output={"error": "reject requires 'hypothesis_id' + 'rejection_reason'"},
                outcome=Outcome.BLOCK,
                input_summary="reject",
            )
        try:
            reject_hypothesis(hid, reason)
        except ValueError as exc:
            return ActorResult(
                output={"error": str(exc), "hypothesis_id": hid},
                outcome=Outcome.BLOCK,
                input_summary=f"reject {hid}",
            )

        self._publish_lifecycle("rejected", hid, ctx.run_id, extra={"reason": reason})
        return ActorResult(
            output={"hypothesis_id": hid, "status": "rejected"},
            outcome=Outcome.PASS,
            input_summary=f"reject {hid}",
        )

    @staticmethod
    def _expire() -> ActorResult:
        n = expire_hypotheses()
        return ActorResult(
            output={"expired_count": n},
            outcome=Outcome.PASS,
            sample_n=n,
            input_summary=f"expire (n={n})",
        )

    @staticmethod
    def _check_emit(input_data: dict[str, Any]) -> ActorResult:
        hid = input_data.get("hypothesis_id")
        if not hid:
            return ActorResult(
                output={"error": "check_emit requires 'hypothesis_id'"},
                outcome=Outcome.BLOCK,
                input_summary="check_emit",
            )
        rows = query(
            "SELECT status, expiry_date FROM hypotheses WHERE hypothesis_id = ?",
            (hid,),
        )
        if not rows:
            return ActorResult(
                output={"error": f"hypothesis {hid!r} not found", "hypothesis_id": hid},
                outcome=Outcome.BLOCK,
                input_summary=f"check_emit {hid}",
            )
        r = dict(rows[0])
        # 만료 자동 감지 (expire 호출 안 했어도 emit 시점에 차단)
        if r["status"] == "open" and r["expiry_date"] < today_kst():
            return ActorResult(
                output={
                    "hypothesis_id": hid,
                    "status": "open",
                    "reason": f"expiry_date {r['expiry_date']} passed (auto-detected)",
                },
                outcome=Outcome.BLOCK,
                input_summary=f"check_emit {hid} expired",
            )
        if r["status"] != "validated":
            return ActorResult(
                output={
                    "hypothesis_id": hid,
                    "status": r["status"],
                    "reason": f"emit requires status=validated, got {r['status']!r}",
                },
                outcome=Outcome.BLOCK,
                input_summary=f"check_emit {hid} {r['status']}",
            )
        return ActorResult(
            output={"hypothesis_id": hid, "status": "validated"},
            outcome=Outcome.PASS,
            input_summary=f"check_emit {hid} validated",
        )

    @staticmethod
    def _list_open() -> ActorResult:
        rows = query(
            """SELECT hypothesis_id, name, version, producer_actor, expiry_date,
                      canary_scope, feature_flag
               FROM hypotheses WHERE status='open' ORDER BY created_at DESC"""
        )
        items = [dict(r) for r in rows]
        return ActorResult(
            output={"count": len(items), "hypotheses": items},
            outcome=Outcome.PASS,
            sample_n=len(items),
            input_summary=f"list_open (n={len(items)})",
        )

    # ─── Discord publish (best-effort) ───────────────────────

    @staticmethod
    def _publish_lifecycle(
        new_status: str,
        hypothesis_id: str,
        run_id: str,
        extra: dict[str, Any],
    ) -> None:
        """validated/rejected 전이 시 ROLLOUT 채널 publish.

        publish 실패해도 actor outcome 영향 X (best-effort).
        """
        try:
            from nuri.agents.discord.outbox import stage_rollout

            metrics_str = ""
            if "metrics" in extra:
                metrics_str = ", ".join(
                    f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}"
                    for k, v in list(extra["metrics"].items())[:5]
                )
            stage_rollout(
                payload={
                    "kind": f"hypothesis_{new_status}",
                    "summary": (
                        f"{hypothesis_id} → {new_status}"
                        + (f" [{metrics_str}]" if metrics_str else "")
                        + (f" reason={extra['reason']}" if extra.get("reason") else "")
                    ),
                    "hypothesis_id": hypothesis_id,
                    "new_status": new_status,
                    "metrics": extra.get("metrics"),
                    "reason": extra.get("reason"),
                },
                dedupe_key=f"hyp_status:{hypothesis_id}:{new_status}",
                actor_name="hypothesis-registry",
                run_id=run_id,
            )
        except Exception:  # noqa: BLE001 — best-effort
            # 발행 실패로 액터를 죽이지 않는다(#894) — 다만 **조용히** 넘기지도 않는다.
            logger.exception("outbox staging 실패: stage_rollout")


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m nuri.agents.actors.hypothesis_registry <action> [...]

    노출 action: list_open / expire / check_emit / register.
    validate/reject 는 Python 호출 (metrics dict 입력 필요).
    """
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(prog="hypothesis-registry")
    parser.add_argument("action", choices=["list_open", "expire", "check_emit", "register"])
    parser.add_argument("--hypothesis-id", default=None)
    parser.add_argument("--name", default=None)
    parser.add_argument("--version", default=None)
    parser.add_argument("--producer-actor", default=None)
    parser.add_argument("--claim-text", default=None)
    parser.add_argument("--evidence-json", default="{}", help="JSON string")
    parser.add_argument("--expiry-date", default=None)
    args = parser.parse_args(argv)

    actor = HypothesisRegistry()
    payload: dict[str, Any] = {"action": args.action}
    if args.hypothesis_id:
        payload["hypothesis_id"] = args.hypothesis_id
    if args.action == "register":
        payload.update(
            {
                "name": args.name,
                "version": args.version,
                "producer_actor": args.producer_actor,
                "claim_text": args.claim_text,
                "evidence": _json.loads(args.evidence_json),
                "expiry_date": args.expiry_date,
            }
        )
    result = actor.run(payload)
    print(_json.dumps(result.output, indent=2, ensure_ascii=False, default=str))
    return 0 if result.outcome == Outcome.PASS else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())

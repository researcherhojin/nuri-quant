"""AuditLedger — Layer A actor (#529 Phase 2 — canonical #10).

Read-only query interface + retention policy on top of the existing
`agent_audit_ledger` table (created in migration #25).

Layer A 설계 (Codex Round 5):
- 100% rule-based — ZERO LLM
- Schema 변동 없음 — 기존 audit ledger 의 consumer
- 4 actions: query / summarize_by_outcome / summarize_by_actor / retention_check
- retention_check 만 enforcement 결정 (PASS / WARN / BLOCK)

Anti-pattern 방지:
- Layer A 는 LLM 의존 절대 금지
- 모든 row 추가는 Actor.base.run() 이 자동 — 이 actor 는 read-only
- archive 로직은 직접 구현 X (다음 phase) — 측정 + 권고만

Discord publish:
- retention_check BLOCK → INCIDENTS (DB bloat 위험, RED)
- retention_check WARN → OPS (cleanup 권고, AMBER)
- query / summarize 결과는 publish X (조회 noise 방지)
"""

from __future__ import annotations

from typing import Any, Optional

from nuri.agents.base import REGISTRY, Actor, ActorResult, Layer, Outcome, RunContext
from nuri.core.db import query

# ─── retention 임계값 (config 화 Phase 3+ 예정) ───────────────
DEFAULT_MAX_ROWS = 1_000_000
DEFAULT_RETENTION_DAYS = 90
BLOCK_MULTIPLIER = 1.5  # max_rows * 1.5 → 즉시 archive (BLOCK)


@REGISTRY.register
class AuditLedger(Actor):
    """Read-only consumer of `agent_audit_ledger` + retention policy.

    Actions (input_data['action']):
        query                  — filter rows (actor / layer / outcome / since)
        summarize_by_outcome   — GROUP BY outcome
        summarize_by_actor     — GROUP BY actor_name
        retention_check        — row count vs threshold → PASS/WARN/BLOCK

    Outcome 매핑 (Codex Round 5 Layer A):
        PASS  — 모든 정상 path (query/summarize 항상 PASS)
        WARN  — retention_check: total_rows > max_rows
        BLOCK — retention_check: total_rows > max_rows * 1.5 (즉시 archive 필요)
    """

    name = "audit-ledger"
    version = "0.1.0"
    layer = Layer.A

    VALID_ACTIONS: tuple[str, ...] = (
        "query",
        "summarize_by_outcome",
        "summarize_by_actor",
        "retention_check",
    )

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        action = input_data.get("action")
        if action not in self.VALID_ACTIONS:
            return ActorResult(
                output={"error": f"invalid action {action!r}, expected {self.VALID_ACTIONS}"},
                outcome=Outcome.BLOCK,
                input_summary=f"action={action}",
            )

        if action == "query":
            return self._query(input_data)
        if action == "summarize_by_outcome":
            return self._summarize_by_outcome(input_data)
        if action == "summarize_by_actor":
            return self._summarize_by_actor(input_data)
        # retention_check
        return self._retention_check(input_data, ctx)

    # ─── query ────────────────────────────────────────────────

    @staticmethod
    def _query(input_data: dict[str, Any]) -> ActorResult:
        # filter parameter — 모두 optional
        actor_name = input_data.get("actor_name")
        layer = input_data.get("layer")
        outcome = input_data.get("outcome")
        since_iso = input_data.get("since_iso")
        try:
            limit = int(input_data.get("limit", 100))
        except (TypeError, ValueError):
            return ActorResult(
                output={"error": "limit must be integer"},
                outcome=Outcome.BLOCK,
                input_summary="query invalid limit",
            )

        if layer is not None and layer not in ("A", "B", "C"):
            return ActorResult(
                output={"error": f"layer must be A/B/C, got {layer!r}"},
                outcome=Outcome.BLOCK,
                input_summary="query invalid layer",
            )
        if outcome is not None and outcome not in ("pass", "block", "warn", "error"):
            return ActorResult(
                output={"error": f"outcome must be pass/block/warn/error, got {outcome!r}"},
                outcome=Outcome.BLOCK,
                input_summary="query invalid outcome",
            )

        sql = "SELECT * FROM agent_audit_ledger"
        clauses: list[str] = []
        params: list[Any] = []
        if actor_name:
            clauses.append("actor_name = ?")
            params.append(actor_name)
        if layer:
            clauses.append("layer = ?")
            params.append(layer)
        if outcome:
            clauses.append("outcome = ?")
            params.append(outcome)
        if since_iso:
            clauses.append("timestamp >= ?")
            params.append(since_iso)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY timestamp DESC, id DESC LIMIT ?"
        params.append(limit)

        rows = query(sql, tuple(params))
        items = [dict(r) for r in rows]
        return ActorResult(
            output={"count": len(items), "rows": items},
            outcome=Outcome.PASS,
            sample_n=len(items),
            input_summary=f"query (n={len(items)})",
        )

    # ─── summarize_by_outcome ─────────────────────────────────

    @staticmethod
    def _summarize_by_outcome(input_data: dict[str, Any]) -> ActorResult:
        actor_name = input_data.get("actor_name")
        since_iso = input_data.get("since_iso")

        sql = "SELECT outcome, COUNT(*) as cnt FROM agent_audit_ledger"
        clauses: list[str] = []
        params: list[Any] = []
        if actor_name:
            clauses.append("actor_name = ?")
            params.append(actor_name)
        if since_iso:
            clauses.append("timestamp >= ?")
            params.append(since_iso)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " GROUP BY outcome"

        rows = query(sql, tuple(params))
        # outcome 4종 + None (unset) — None 은 'unset' key 로 surface
        totals: dict[str, int] = {"pass": 0, "block": 0, "warn": 0, "error": 0}
        unset = 0
        for r in rows:
            key = r["outcome"]
            cnt = int(r["cnt"])
            if key is None:
                unset += cnt
            elif key in totals:
                totals[key] = cnt
        total_count = sum(totals.values()) + unset
        output: dict[str, Any] = {"totals": totals, "total_count": total_count}
        if unset:
            output["unset"] = unset
        return ActorResult(
            output=output,
            outcome=Outcome.PASS,
            sample_n=total_count,
            input_summary=f"summarize_by_outcome (total={total_count})",
        )

    # ─── summarize_by_actor ───────────────────────────────────

    @staticmethod
    def _summarize_by_actor(input_data: dict[str, Any]) -> ActorResult:
        layer = input_data.get("layer")
        since_iso = input_data.get("since_iso")

        if layer is not None and layer not in ("A", "B", "C"):
            return ActorResult(
                output={"error": f"layer must be A/B/C, got {layer!r}"},
                outcome=Outcome.BLOCK,
                input_summary="summarize_by_actor invalid layer",
            )

        sql = "SELECT actor_name, outcome, COUNT(*) as cnt FROM agent_audit_ledger"
        clauses: list[str] = []
        params: list[Any] = []
        if layer:
            clauses.append("layer = ?")
            params.append(layer)
        if since_iso:
            clauses.append("timestamp >= ?")
            params.append(since_iso)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " GROUP BY actor_name, outcome"

        rows = query(sql, tuple(params))
        actors: dict[str, dict[str, int]] = {}
        for r in rows:
            name = r["actor_name"]
            slot = actors.setdefault(name, {"pass": 0, "block": 0, "warn": 0, "error": 0, "total": 0})
            outcome_key = r["outcome"] or "unset"
            cnt = int(r["cnt"])
            if outcome_key in slot:
                slot[outcome_key] = cnt
            slot["total"] += cnt
        return ActorResult(
            output={"actors": actors, "total_actors": len(actors)},
            outcome=Outcome.PASS,
            sample_n=len(actors),
            input_summary=f"summarize_by_actor (n={len(actors)})",
        )

    # ─── retention_check ──────────────────────────────────────

    def _retention_check(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        try:
            max_rows = int(input_data.get("max_rows", DEFAULT_MAX_ROWS))
            since_days = int(input_data.get("since_days", DEFAULT_RETENTION_DAYS))
        except (TypeError, ValueError):
            return ActorResult(
                output={"error": "max_rows / since_days must be integer"},
                outcome=Outcome.BLOCK,
                input_summary="retention_check invalid args",
            )

        if max_rows <= 0 or since_days <= 0:
            return ActorResult(
                output={"error": "max_rows / since_days must be positive"},
                outcome=Outcome.BLOCK,
                input_summary="retention_check invalid args",
            )

        # 총 row 개수 — sqlite COUNT(*) 는 full scan but ledger 1M 까지 OK
        total_rows_result = query("SELECT COUNT(*) AS n FROM agent_audit_ledger")
        total_rows = int(total_rows_result[0]["n"]) if total_rows_result else 0

        # since_days 보다 오래된 row — sqlite julianday 기반 (datetime('now') 와 동일 격)
        old_rows_result = query(
            "SELECT COUNT(*) AS n FROM agent_audit_ledger WHERE julianday('now') - julianday(timestamp) > ?",
            (since_days,),
        )
        old_rows = int(old_rows_result[0]["n"]) if old_rows_result else 0

        block_threshold = int(max_rows * BLOCK_MULTIPLIER)
        if total_rows > block_threshold:
            recommendation = (
                f"BLOCK: total_rows {total_rows:,} > block threshold {block_threshold:,} "
                f"(max_rows {max_rows:,} × {BLOCK_MULTIPLIER}). 즉시 archive 필요."
            )
            outcome = Outcome.BLOCK
        elif total_rows > max_rows:
            recommendation = (
                f"WARN: total_rows {total_rows:,} > max_rows {max_rows:,}. "
                f"cleanup (>{since_days}d {old_rows:,} rows) 권고."
            )
            outcome = Outcome.WARN
        else:
            recommendation = (
                f"PASS: total_rows {total_rows:,} ≤ max_rows {max_rows:,} (>{since_days}d: {old_rows:,} rows)."
            )
            outcome = Outcome.PASS

        output = {
            "total_rows": total_rows,
            "rows_older_than_n_days": old_rows,
            "since_days": since_days,
            "max_rows": max_rows,
            "block_threshold": block_threshold,
            "recommendation": recommendation,
        }

        # ─── Discord publish (BLOCK → INCIDENTS, WARN → OPS) ───
        if outcome == Outcome.BLOCK:
            self._publish_incidents(output, ctx.run_id)
        elif outcome == Outcome.WARN:
            self._publish_ops(output, ctx.run_id)

        return ActorResult(
            output=output,
            outcome=outcome,
            sample_n=total_rows,
            input_summary=f"retention_check {outcome.value} (rows={total_rows:,})",
        )

    # ─── Discord publish (best-effort) ───────────────────────

    @staticmethod
    def _publish_incidents(output: dict[str, Any], run_id: str) -> None:
        """retention_check BLOCK → #incidents outbox stage (PR3 Codex Round 6)."""
        try:
            from nuri.agents.discord.outbox import stage_incident

            stage_incident(
                payload={
                    "kind": "audit_ledger_block",
                    "summary": (
                        f"DB bloat BLOCK: total={output['total_rows']:,} > "
                        f"threshold={output['block_threshold']:,}, immediate archive required"
                    ),
                    "total_rows": output["total_rows"],
                    "block_threshold": output["block_threshold"],
                    "max_rows": output["max_rows"],
                    "recommendation": output["recommendation"],
                },
                priority="high",  # bloat block 은 즉시 surface
                dedupe_key="audit_ledger_block",  # 1건만 (반복 alert 방지)
                actor_name="audit-ledger",
                run_id=run_id,
            )
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _publish_ops(output: dict[str, Any], run_id: str) -> None:
        """retention_check WARN → #ops outbox stage (PR3 Codex Round 6)."""
        try:
            from nuri.agents.discord.outbox import stage_ops

            stage_ops(
                payload={
                    "kind": "audit_ledger_warn",
                    "summary": (
                        f"cleanup recommended: total={output['total_rows']:,}, "
                        f"older than {output['since_days']}d = {output['rows_older_than_n_days']:,}"
                    ),
                    "total_rows": output["total_rows"],
                    "max_rows": output["max_rows"],
                    "since_days": output["since_days"],
                    "rows_older_than_n_days": output["rows_older_than_n_days"],
                    "recommendation": output["recommendation"],
                },
                dedupe_key="audit_ledger_warn",
                actor_name="audit-ledger",
                run_id=run_id,
            )
        except Exception:  # noqa: BLE001
            pass


def main(argv: Optional[list[str]] = None) -> int:
    """CLI: python -m nuri.agents.actors.audit_ledger <action> [options]."""
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(prog="audit-ledger")
    parser.add_argument(
        "action",
        choices=["query", "summarize_by_outcome", "summarize_by_actor", "retention_check"],
    )
    parser.add_argument("--actor-name", default=None)
    parser.add_argument("--layer", default=None, choices=[None, "A", "B", "C"])
    parser.add_argument("--outcome", default=None, choices=[None, "pass", "block", "warn", "error"])
    parser.add_argument("--since-iso", default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--max-rows", type=int, default=DEFAULT_MAX_ROWS)
    parser.add_argument("--since-days", type=int, default=DEFAULT_RETENTION_DAYS)
    args = parser.parse_args(argv)

    payload: dict[str, Any] = {"action": args.action}
    if args.actor_name:
        payload["actor_name"] = args.actor_name
    if args.layer:
        payload["layer"] = args.layer
    if args.outcome:
        payload["outcome"] = args.outcome
    if args.since_iso:
        payload["since_iso"] = args.since_iso
    if args.action == "query":
        payload["limit"] = args.limit
    if args.action == "retention_check":
        payload["max_rows"] = args.max_rows
        payload["since_days"] = args.since_days

    result = AuditLedger().run(payload)
    print(_json.dumps(result.output, indent=2, ensure_ascii=False, default=str))
    return 0 if result.outcome == Outcome.PASS else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())

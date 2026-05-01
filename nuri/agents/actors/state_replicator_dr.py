"""StateReplicatorDR — Layer A actor (#529 Phase 2 Codex Round 5 inventory #15).

Responsibilities:
- MBP ↔ Mac mini DR (Disaster Recovery) state 추적
- 실제 sync 는 launchd autopull (5분 간격) 이 처리, 본 actor 는 readiness 기록 + 검증
- "DR replica 가 N분 이상 stale 인가?" 검출
- "primary writer 가 어디인가?" 추적 + 검증
- replica 의 schema_version 이 primary 와 동일한가?

Layer A 설계 (Codex Round 5 mandatory #3):
- 100% rule-based, ZERO LLM
- 모든 결정 audit_ledger + run_ledger 영구 기록
- LLM down 이어도 정상 작동 (graceful degradation 보장)

Anti-pattern 방지:
- Single-writer prod invariant (Round 5 mandatory #1) — primary != replica 강제
- Stale replica → 사후 사고 시 복구 불가능 → BLOCK + Discord INCIDENTS alert
- schema mismatch → migration drift → BLOCK (out_of_sync 로 status 자동 update)

Docker 이전 까지는 *기록 + 룰 검증* 만, 실제 file copy 는 다음 phase.
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any, Optional

from nuri.agents.base import REGISTRY, Actor, ActorResult, Layer, Outcome, RunContext
from nuri.core.db import (
    get_schema_version,
    query,
    upsert_dr_replica,
)
from nuri.core.timezone import kst_now

# launchd autopull heartbeat 파일 — Mac mini 가 5분 간격 git fetch 성공 시 mtime 갱신.
# Docker 이전 까지는 placeholder (없으면 unreachable 로 표시).
HEARTBEAT_PATH = Path("data/.autopull_heartbeat")

# status 임계값 (사용자 룰 명세)
HEALTHY_LAG_SECONDS = 600  # 10분 이내 = healthy
STALE_LAG_SECONDS = 3600  # 10분 ~ 1시간 = stale, 그 이상 = unreachable


@REGISTRY.register
class StateReplicatorDR(Actor):
    """DR replica readiness enforcement gate.

    Actions (input_data['action']):
        snapshot       — 현재 머신의 DR state 기록 (replica_id + role 필수)
        verify         — 모든 replica 가 healthy 인지 검증 (max_lag_seconds 옵션)
        list_replicas  — 모든 replica 조회 (read-only)

    Outcome 매핑 (Codex Round 5 Layer A enforcement):
        snapshot       — PASS (기록 자체는 항상 성공)
        verify         — PASS (전부 healthy) / WARN (stale 만) / BLOCK (unreachable/out_of_sync)
        list_replicas  — PASS
        BLOCK          — invalid input
    """

    name = "state-replicator-dr"
    version = "0.1.0"
    layer = Layer.A

    VALID_ACTIONS: tuple[str, ...] = ("snapshot", "verify", "list_replicas")
    VALID_ROLES: tuple[str, ...] = ("primary", "replica")

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        action = input_data.get("action")

        # Layer A enforcement: input validation 먼저
        if action not in self.VALID_ACTIONS:
            return ActorResult(
                output={"error": f"invalid action {action!r}, expected {self.VALID_ACTIONS}"},
                outcome=Outcome.BLOCK,
                input_summary=f"action={action}",
            )

        if action == "snapshot":
            return self._snapshot(input_data, ctx)
        if action == "verify":
            return self._verify(input_data, ctx)
        # action == "list_replicas"
        return self._list_replicas()

    # ─── snapshot ────────────────────────────────────────────

    def _snapshot(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        replica_id = input_data.get("replica_id")
        role = input_data.get("role")

        if not replica_id or not isinstance(replica_id, str):
            return ActorResult(
                output={"error": "replica_id (str) required for snapshot"},
                outcome=Outcome.BLOCK,
                input_summary="snapshot (no replica_id)",
            )
        if role not in self.VALID_ROLES:
            return ActorResult(
                output={"error": f"role required (primary/replica), got {role!r}"},
                outcome=Outcome.BLOCK,
                input_summary=f"snapshot {replica_id} (bad role)",
            )

        hostname = socket.gethostname()
        schema_version = get_schema_version()
        now_kst = kst_now()

        # primary: 항상 now 기록, lag=0, status=healthy
        # replica: launchd autopull heartbeat 기반 lag 산출
        if role == "primary":
            last_sync_at = now_kst.strftime("%Y-%m-%d %H:%M:%S")
            sync_lag_seconds = 0
            status = "healthy"
            notes = "primary writer — last_sync_at=now"
        else:
            last_sync_at, sync_lag_seconds, status, notes = self._probe_replica_heartbeat(now_kst)

        upsert_dr_replica(
            replica_id=replica_id,
            role=role,
            hostname=hostname,
            last_sync_at=last_sync_at,
            last_sync_schema_version=schema_version,
            sync_lag_seconds=sync_lag_seconds,
            status=status,
            notes=notes,
            run_id=ctx.run_id,
        )

        return ActorResult(
            output={
                "action": "snapshot",
                "replica_id": replica_id,
                "role": role,
                "hostname": hostname,
                "last_sync_at": last_sync_at,
                "last_sync_schema_version": schema_version,
                "sync_lag_seconds": sync_lag_seconds,
                "status": status,
            },
            outcome=Outcome.PASS,
            sample_n=1,
            input_summary=f"snapshot {replica_id} role={role} status={status}",
        )

    @staticmethod
    def _probe_replica_heartbeat(
        now_kst,
    ) -> tuple[Optional[str], Optional[int], str, str]:
        """launchd autopull heartbeat 파일 mtime 으로 lag/status 산출.

        Docker 이전 까지는 heartbeat 파일이 없을 수 있음 → unreachable 처리.
        """
        if not HEARTBEAT_PATH.exists():
            return (
                None,
                None,
                "unreachable",
                f"heartbeat missing ({HEARTBEAT_PATH}) — launchd autopull placeholder",
            )

        mtime = HEARTBEAT_PATH.stat().st_mtime
        # KST naive datetime 으로 일관성 유지 (DB 저장용)
        from datetime import datetime as _dt

        from nuri.core.timezone import KST

        last_sync_dt = _dt.fromtimestamp(mtime, tz=KST)
        last_sync_at = last_sync_dt.strftime("%Y-%m-%d %H:%M:%S")
        sync_lag_seconds = int((now_kst - last_sync_dt).total_seconds())

        if sync_lag_seconds < HEALTHY_LAG_SECONDS:
            status = "healthy"
            notes = f"autopull heartbeat fresh ({sync_lag_seconds}s)"
        elif sync_lag_seconds < STALE_LAG_SECONDS:
            status = "stale"
            notes = f"autopull lagging ({sync_lag_seconds}s) — within tolerance"
        else:
            status = "unreachable"
            notes = f"autopull stalled ({sync_lag_seconds}s ≥ {STALE_LAG_SECONDS}s)"

        return last_sync_at, sync_lag_seconds, status, notes

    # ─── verify ─────────────────────────────────────────────

    def _verify(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        max_lag = input_data.get("max_lag_seconds", HEALTHY_LAG_SECONDS)
        if not isinstance(max_lag, int) or max_lag <= 0:
            return ActorResult(
                output={"error": f"max_lag_seconds must be positive int, got {max_lag!r}"},
                outcome=Outcome.BLOCK,
                input_summary="verify (bad max_lag)",
            )

        rows = query("SELECT * FROM dr_replicas")
        replicas = [dict(r) for r in rows]
        if not replicas:
            # replica 등록 X → 검증 대상 없음. surface only (no action change).
            return ActorResult(
                output={
                    "action": "verify",
                    "summary": {"healthy": 0, "stale": 0, "unreachable": 0, "out_of_sync": 0, "total": 0},
                    "replicas": [],
                    "message": "no replicas registered (snapshot 먼저 실행)",
                },
                outcome=Outcome.WARN,
                sample_n=0,
                input_summary="verify (empty)",
            )

        # primary schema_version 기준으로 replica 의 mismatch 감지
        primaries = [r for r in replicas if r["role"] == "primary"]
        primary_schema = primaries[0]["last_sync_schema_version"] if primaries else None

        unhealthy_blocks: list[dict[str, Any]] = []
        stale_warns: list[dict[str, Any]] = []

        for r in replicas:
            replica_id = r["replica_id"]
            role = r["role"]
            status = r["status"]
            schema_v = r["last_sync_schema_version"]
            lag = r["sync_lag_seconds"]

            # schema mismatch 검증: replica 만 (primary 는 자기 자신 기준)
            schema_mismatch = (
                role == "replica" and primary_schema is not None and schema_v is not None and schema_v != primary_schema
            )
            if schema_mismatch:
                # status 를 out_of_sync 로 update (idempotent)
                upsert_dr_replica(
                    replica_id=replica_id,
                    role=role,
                    hostname=r["hostname"],
                    last_sync_at=r["last_sync_at"],
                    last_sync_schema_version=schema_v,
                    sync_lag_seconds=lag,
                    status="out_of_sync",
                    notes=f"schema mismatch: replica={schema_v} vs primary={primary_schema}",
                    run_id=ctx.run_id,
                )
                unhealthy_blocks.append(
                    {
                        "replica_id": replica_id,
                        "role": role,
                        "status": "out_of_sync",
                        "reason": f"schema mismatch: replica={schema_v} vs primary={primary_schema}",
                    }
                )
                continue

            # lag 기반 분류
            if status in ("unreachable", "out_of_sync"):
                unhealthy_blocks.append(
                    {
                        "replica_id": replica_id,
                        "role": role,
                        "status": status,
                        "reason": f"status={status}, lag={lag}s",
                    }
                )
            elif status == "stale" or (lag is not None and lag > max_lag):
                stale_warns.append(
                    {
                        "replica_id": replica_id,
                        "role": role,
                        "status": status,
                        "reason": f"lag {lag}s exceeds max_lag {max_lag}s",
                    }
                )

        # outcome 결정 — worst-case enforcement
        if unhealthy_blocks:
            outcome = Outcome.BLOCK
        elif stale_warns:
            outcome = Outcome.WARN
        else:
            outcome = Outcome.PASS

        # status 분포 요약
        all_statuses = [r["status"] for r in replicas]
        # out_of_sync 로 update 한 row 반영 위해 다시 read
        if unhealthy_blocks:
            rows2 = query("SELECT status FROM dr_replicas")
            all_statuses = [r["status"] for r in rows2]

        summary = {
            "healthy": all_statuses.count("healthy"),
            "stale": all_statuses.count("stale"),
            "unreachable": all_statuses.count("unreachable"),
            "out_of_sync": all_statuses.count("out_of_sync"),
            "total": len(all_statuses),
        }

        result = ActorResult(
            output={
                "action": "verify",
                "summary": summary,
                "blocks": unhealthy_blocks,
                "warns": stale_warns,
                "max_lag_seconds": max_lag,
            },
            outcome=outcome,
            sample_n=len(replicas),
            input_summary=f"verify → {summary['healthy']}/{summary['total']} healthy",
        )

        # Discord publish (BLOCK 시만, best-effort)
        if outcome == Outcome.BLOCK:
            self._publish_incidents(unhealthy_blocks, ctx.run_id)

        return result

    # ─── list_replicas ──────────────────────────────────────

    @staticmethod
    def _list_replicas() -> ActorResult:
        rows = query("SELECT * FROM dr_replicas ORDER BY role, replica_id")
        items = [dict(r) for r in rows]
        return ActorResult(
            output={"count": len(items), "replicas": items},
            outcome=Outcome.PASS,
            sample_n=len(items),
            input_summary=f"list_replicas (n={len(items)})",
        )

    # ─── Discord publish (best-effort) ───────────────────────

    @staticmethod
    def _publish_incidents(blocks: list[dict[str, Any]], run_id: str) -> None:
        """DR replica BLOCK → #incidents outbox stage (PR3 Codex Round 6)."""
        try:
            from nuri.agents.discord.outbox import stage_incident

            replica_ids = ",".join(b["replica_id"] for b in blocks[:5])
            stage_incident(
                payload={
                    "kind": "dr_replica_block",
                    "summary": f"DR readiness compromised: {len(blocks)} unhealthy [{replica_ids}]",
                    "n_unhealthy": len(blocks),
                    "blocks": blocks[:5],
                },
                priority="high",  # DR readiness 위반 = 즉시 surface
                dedupe_key="dr_replica_block",
                actor_name="state-replicator-dr",
                run_id=run_id,
            )
        except Exception:  # noqa: BLE001
            pass


def main(argv: list[str] | None = None) -> int:
    """CLI entry: python -m nuri.agents.actors.state_replicator_dr <action> ...

    Examples:
        python -m nuri.agents.actors.state_replicator_dr snapshot \\
            --replica-id macmini-primary --role primary
        python -m nuri.agents.actors.state_replicator_dr snapshot \\
            --replica-id mbp-replica --role replica
        python -m nuri.agents.actors.state_replicator_dr verify --max-lag 600
        python -m nuri.agents.actors.state_replicator_dr list_replicas
    """
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(prog="state-replicator-dr")
    parser.add_argument("action", choices=StateReplicatorDR.VALID_ACTIONS)
    parser.add_argument("--replica-id", help="replica identifier (required for snapshot)")
    parser.add_argument(
        "--role",
        choices=StateReplicatorDR.VALID_ROLES,
        help="primary or replica (required for snapshot)",
    )
    parser.add_argument(
        "--max-lag",
        type=int,
        default=HEALTHY_LAG_SECONDS,
        help=f"max acceptable lag in seconds (default {HEALTHY_LAG_SECONDS})",
    )

    args = parser.parse_args(argv)
    input_data: dict[str, Any] = {"action": args.action}
    if args.replica_id:
        input_data["replica_id"] = args.replica_id
    if args.role:
        input_data["role"] = args.role
    if args.action == "verify":
        input_data["max_lag_seconds"] = args.max_lag

    actor = StateReplicatorDR()
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

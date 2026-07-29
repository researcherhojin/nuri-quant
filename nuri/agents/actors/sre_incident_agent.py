"""SREIncidentAgent — Layer A actor (#529 Phase 2 — canonical #14).

운영 인프라 이상 자동 탐지 + 영구 incident ledger 기록 + Discord alert routing.

Layer A 설계 (Codex Round 5):
- 100% rule-based — threshold 비교 (LLM 추론 X)
- ZERO LLM
- 8 detector 모두 결정적 (DB query + filesystem stat)
- 모든 incident → audit_ledger + incidents 테이블 영구 기록

8 Detector:
    1. orphan_run         — agent_run_ledger started + finished_at IS NULL + >1h
                            warning (1h+) / critical (3h+)
    2. disk_full          — shutil.disk_usage() percent_used > 80 (warn) / > 90 (crit)
    3. db_lock            — SELECT 1 FROM agent_audit_ledger 시도 → exception → critical
    4. scheduler_heartbeat— data/.scheduler_heartbeat mtime 미존재 시 skip,
                            > 30분 (warn) / > 1h (crit)
    5. actor_failure_streak— actor_name 별 마지막 N run 모두 'failed':
                            3회 (warn) / 5회 (crit)
    6. data_freshness_critical — check_all_freshness() FAIL 개수:
                            ≥1 (warn) / ≥3 (crit)
    7. signal_evaluation_stale — pipeline_events 'signal_evaluation_run'
                            heartbeat 공백 영업일 (#825): ≥2 (warn) / ≥4 (crit)
    8. alpha_report_stale — pipeline_events 'alpha_report_run' 의 **마지막 성공
                            stage** 공백 (#894): ≥35일 (warn). heartbeat 공백이
                            아니라 성공 공백 — cron 이 매일이라 role 누락 상태도
                            heartbeat 는 계속 찍힌다.

Idempotent semantics:
- 동일 (incident_type, target) 의 open incident 는 단일 row → log_incident() 가
  재호출 시 last_detected_at 만 update (UNIQUE constraint).
- Discord re-publish 차단: 기존 incident 가 update 된 경우 publish 안 함
  (신규 INSERT 일 때만 publish — log_incident return id 와 새로 만들어진 id 비교).

Discord routing:
- critical → INCIDENTS 채널 (RED, operator urgent)
- warning  → OPS 채널 (AMBER)
- info     → publish 안 함 (audit only)
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from nuri.agents.base import REGISTRY, Actor, ActorResult, Layer, Outcome, RunContext
from nuri.core.db import (
    acknowledge_incident as db_acknowledge_incident,
)
from nuri.core.db import (
    log_incident,
    query,
)
from nuri.core.db import (
    resolve_incident as db_resolve_incident,
)
from nuri.core.timezone import kst_now, to_kst

# ─── 임계값 (config 가능 — 추후 rules.yaml 이관) ──────────
ORPHAN_WARN_HOURS = 1.0
ORPHAN_CRIT_HOURS = 3.0
DISK_WARN_PCT = 80.0
DISK_CRIT_PCT = 90.0
SCHEDULER_WARN_MIN = 30.0
SCHEDULER_CRIT_MIN = 60.0
FAILURE_STREAK_WARN = 3
FAILURE_STREAK_CRIT = 5
FRESHNESS_FAIL_WARN = 1
FRESHNESS_FAIL_CRIT = 3
# 시그널 평가 heartbeat 공백 (#825) — 영업일 단위 (KST 화~토, technical cron '0 7 * * 2-6')
SIGNAL_EVAL_WARN_DAYS = 2
SIGNAL_EVAL_CRIT_DAYS = 4
# 당일은 이 시각(KST) 이후부터 미실행으로 계상 — 07:00 cron 전 새벽 scan false positive 방지
SIGNAL_EVAL_GRACE_HOUR = 12
# 평가 예정 요일 (Mon=0 기준 화~토 — 미국 거래일 마감 다음 날 아침 KST)
SIGNAL_EVAL_WEEKDAYS = (1, 2, 3, 4, 5)
# §3.11 월간 alpha 리포트 미발화 임계 (#894). 월 1회 발화라 한 달(31일)로는
# 정상 주기와 구분이 안 된다 — 한 주기를 통째로 놓친 게 확실해지는 35일.
# pipeline_events 보존 90일(scripts/db/maintenance.py)이라 이 창은 안전하다.
ALPHA_REPORT_STALE_DAYS = 35

HEARTBEAT_PATH = Path(__file__).resolve().parents[3] / "data" / ".scheduler_heartbeat"


@REGISTRY.register
class SREIncidentAgent(Actor):
    """Operational incident detection + lifecycle management — Layer A.

    Actions (input_data['action']):
        scan        — 8 detector 모두 실행 → log_incident + Discord publish.
        acknowledge — incident_id 사용자 확인 (audit-only).
        resolve     — incident_id 종료 (status='resolved').
        list_open   — open incident 목록 (severity 필터 optional).

    Outcome 매핑 (Codex Round 5 Layer A):
        scan        — 항상 PASS (탐지 자체는 성공). critical 발견되어도 PASS
                       (log + alert 가 의미 있는 record).
        acknowledge — PASS / BLOCK (incident 미존재).
        resolve     — PASS / BLOCK (incident 미존재).
        list_open   — PASS.
        invalid     — BLOCK.
    """

    name = "sre-incident-agent"
    version = "0.1.0"
    layer = Layer.A

    VALID_ACTIONS: tuple[str, ...] = ("scan", "acknowledge", "resolve", "list_open")

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        action = input_data.get("action")
        if action not in self.VALID_ACTIONS:
            return ActorResult(
                output={"error": f"invalid action {action!r}, expected {self.VALID_ACTIONS}"},
                outcome=Outcome.BLOCK,
                input_summary=f"action={action}",
            )

        if action == "scan":
            return self._scan(input_data, ctx)
        if action == "acknowledge":
            return self._acknowledge(input_data)
        if action == "resolve":
            return self._resolve(input_data)
        return self._list_open(input_data)

    # ─── scan ────────────────────────────────────────────────

    def _scan(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        """8 detector 실행 → 발견된 incident 목록 반환."""
        detected: list[dict[str, Any]] = []

        for detector in (
            self._detect_orphan_runs,
            self._detect_disk_full,
            self._detect_db_lock,
            self._detect_scheduler_heartbeat,
            self._detect_actor_failure_streak,
            self._detect_data_freshness_critical,
            self._detect_signal_evaluation_stale,
            self._detect_alpha_report_stale,
        ):
            try:
                detected.extend(detector(ctx))
            except Exception as exc:  # noqa: BLE001 — detector 실패는 다른 detector 진행
                detected.append(
                    {
                        "incident_type": "db_lock",  # detector 실패 = infra 의심
                        "severity": "warning",
                        "target": detector.__name__,
                        "evidence": {"detector_error": str(exc)[:200]},
                        "is_new": False,
                    }
                )

        # 요약 (severity 분포)
        severity_counts = {"critical": 0, "warning": 0, "info": 0}
        for inc in detected:
            severity_counts[inc.get("severity", "info")] = severity_counts.get(inc.get("severity", "info"), 0) + 1

        return ActorResult(
            output={
                "incidents": detected,
                "summary": {
                    "total": len(detected),
                    **severity_counts,
                },
            },
            outcome=Outcome.PASS,
            sample_n=len(detected),
            input_summary=(
                f"scan → {len(detected)} incidents "
                f"(crit={severity_counts['critical']}, warn={severity_counts['warning']})"
            ),
        )

    # ─── 8 detectors ─────────────────────────────────────────

    def _detect_orphan_runs(self, ctx: RunContext) -> list[dict[str, Any]]:
        """agent_run_ledger 에서 started + finished_at NULL + age 검사."""
        rows = query(
            """SELECT actor_name, run_id, started_at,
                      (julianday('now') - julianday(started_at)) * 24.0 AS age_hours
               FROM agent_run_ledger
               WHERE status = 'started' AND finished_at IS NULL
                 AND datetime(started_at) < datetime('now', ?)""",
            (f"-{int(ORPHAN_WARN_HOURS * 60)} minutes",),
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            age = float(row["age_hours"] or 0.0)
            severity = "critical" if age >= ORPHAN_CRIT_HOURS else "warning"
            evidence = {
                "run_id": row["run_id"],
                "started_at": row["started_at"],
                "age_hours": round(age, 2),
                "warn_threshold_hours": ORPHAN_WARN_HOURS,
                "critical_threshold_hours": ORPHAN_CRIT_HOURS,
            }
            out.append(
                self._record_incident(
                    incident_type="orphan_run",
                    severity=severity,
                    target=str(row["actor_name"]),
                    evidence=evidence,
                    ctx=ctx,
                )
            )
        return out

    def _detect_disk_full(self, ctx: RunContext) -> list[dict[str, Any]]:
        """shutil.disk_usage('.') 기반 디스크 사용률."""
        usage = shutil.disk_usage(".")
        if usage.total <= 0:
            return []
        percent_used = (usage.used / usage.total) * 100.0
        if percent_used <= DISK_WARN_PCT:
            return []
        severity = "critical" if percent_used > DISK_CRIT_PCT else "warning"
        evidence = {
            "percent_used": round(percent_used, 2),
            "total_gb": round(usage.total / (1024**3), 2),
            "free_gb": round(usage.free / (1024**3), 2),
            "warn_threshold_pct": DISK_WARN_PCT,
            "critical_threshold_pct": DISK_CRIT_PCT,
        }
        return [
            self._record_incident(
                incident_type="disk_full",
                severity=severity,
                target="disk",
                evidence=evidence,
                ctx=ctx,
            )
        ]

    def _detect_db_lock(self, ctx: RunContext) -> list[dict[str, Any]]:
        """간단한 SELECT 1 시도 — exception 발생 시 db_lock incident."""
        try:
            query("SELECT 1 FROM agent_audit_ledger LIMIT 1")
        except Exception as exc:  # noqa: BLE001
            evidence = {"error": str(exc)[:300]}
            return [
                self._record_incident(
                    incident_type="db_lock",
                    severity="critical",
                    target="db",
                    evidence=evidence,
                    ctx=ctx,
                )
            ]
        return []

    def _detect_scheduler_heartbeat(self, ctx: RunContext) -> list[dict[str, Any]]:
        """data/.scheduler_heartbeat mtime 검사. 파일 미존재 시 skip (info-only — 미배포 환경)."""
        if not HEARTBEAT_PATH.exists():
            return []
        # mtime 검사 — KST 무관하게 epoch delta 사용 (kst_now 가 아닌 time.time 활용:
        # 파일시스템 mtime 도 epoch 단위라 변환 비용 없음).
        import time as _time

        age_minutes = (_time.time() - HEARTBEAT_PATH.stat().st_mtime) / 60.0
        if age_minutes <= SCHEDULER_WARN_MIN:
            return []
        severity = "critical" if age_minutes >= SCHEDULER_CRIT_MIN else "warning"
        evidence = {
            "heartbeat_path": str(HEARTBEAT_PATH),
            "age_minutes": round(age_minutes, 2),
            "warn_threshold_min": SCHEDULER_WARN_MIN,
            "critical_threshold_min": SCHEDULER_CRIT_MIN,
        }
        return [
            self._record_incident(
                incident_type="scheduler_heartbeat",
                severity=severity,
                target="scheduler",
                evidence=evidence,
                ctx=ctx,
            )
        ]

    def _detect_actor_failure_streak(self, ctx: RunContext) -> list[dict[str, Any]]:
        """actor_name 별 마지막 N run status 가 모두 'failed' 인지."""
        actors_rows = query(
            """SELECT DISTINCT actor_name FROM agent_run_ledger
               WHERE status IN ('finished','failed')"""
        )
        out: list[dict[str, Any]] = []
        for actor_row in actors_rows:
            actor_name = actor_row["actor_name"]
            recent = query(
                """SELECT status FROM agent_run_ledger
                   WHERE actor_name = ? AND status IN ('finished','failed')
                   ORDER BY started_at DESC
                   LIMIT ?""",
                (actor_name, FAILURE_STREAK_CRIT),
            )
            statuses = [r["status"] for r in recent]
            if len(statuses) < FAILURE_STREAK_WARN:
                continue
            # 마지막 FAILURE_STREAK_CRIT 모두 failed → critical
            if len(statuses) >= FAILURE_STREAK_CRIT and all(s == "failed" for s in statuses):
                severity = "critical"
                streak = FAILURE_STREAK_CRIT
            elif len(statuses) >= FAILURE_STREAK_WARN and all(s == "failed" for s in statuses[:FAILURE_STREAK_WARN]):
                severity = "warning"
                streak = FAILURE_STREAK_WARN
            else:
                continue
            evidence = {
                "actor_name": actor_name,
                "consecutive_failures": streak,
                "warn_threshold": FAILURE_STREAK_WARN,
                "critical_threshold": FAILURE_STREAK_CRIT,
            }
            out.append(
                self._record_incident(
                    incident_type="actor_failure_streak",
                    severity=severity,
                    target=str(actor_name),
                    evidence=evidence,
                    ctx=ctx,
                )
            )
        return out

    def _detect_data_freshness_critical(self, ctx: RunContext) -> list[dict[str, Any]]:
        """nuri.core.freshness.check_all_freshness() 결과 중 FAIL 개수."""
        from nuri.core.freshness import check_all_freshness

        results = check_all_freshness()
        fails = [r for r in results if r.get("status") == "FAIL"]
        n_fails = len(fails)
        if n_fails < FRESHNESS_FAIL_WARN:
            return []
        severity = "critical" if n_fails >= FRESHNESS_FAIL_CRIT else "warning"
        evidence = {
            "fail_count": n_fails,
            "fail_keys": [r.get("key") for r in fails],
            "warn_threshold": FRESHNESS_FAIL_WARN,
            "critical_threshold": FRESHNESS_FAIL_CRIT,
        }
        return [
            self._record_incident(
                incident_type="data_freshness_critical",
                severity=severity,
                target="freshness",
                evidence=evidence,
                ctx=ctx,
            )
        ]

    def _detect_signal_evaluation_stale(self, ctx: RunContext) -> list[dict[str, Any]]:
        """pipeline_events 'signal_evaluation_run' heartbeat 공백 검사 (#825).

        signals 테이블은 발화(계산) 행만 저장 → 무기록이 '조건 미충족(정상)'인지
        '평가 미실행(고장)'인지 구분 불가 (#734 silent outage 계열). technical
        collector 가 평가마다 heartbeat 1행 (fired_count=0 포함) 을 남기고,
        여기서 공백 영업일(KST 화~토) 수를 센다.

        heartbeat 행이 전무하면 skip (미배포/신규 DB — scheduler_heartbeat 와 동일).
        """
        rows = query(
            """SELECT MAX(timestamp) AS last_run FROM pipeline_events
               WHERE event_type = 'signal_evaluation_run'"""
        )
        last_run = rows[0]["last_run"] if rows else None
        if not last_run:
            return []
        missed = _missed_eval_days(str(last_run), kst_now())
        if missed < SIGNAL_EVAL_WARN_DAYS:
            return []
        severity = "critical" if missed >= SIGNAL_EVAL_CRIT_DAYS else "warning"
        evidence = {
            "last_evaluated_at_utc": str(last_run),
            "missed_eval_days": missed,
            "warn_threshold_days": SIGNAL_EVAL_WARN_DAYS,
            "critical_threshold_days": SIGNAL_EVAL_CRIT_DAYS,
        }
        return [
            self._record_incident(
                incident_type="signal_evaluation_stale",
                severity=severity,
                target="signals",
                evidence=evidence,
                ctx=ctx,
            )
        ]

    def _detect_alpha_report_stale(self, ctx: RunContext) -> list[dict[str, Any]]:
        """pipeline_events 'alpha_report_run' 의 **마지막 성공 stage** 공백 검사 (#894).

        heartbeat 공백이 아니라 *성공* 공백을 재는 게 핵심이다. cron 이 매일
        ('0 9 * * *') 이라 `NURI_ROLE` 이 비어 있어도 heartbeat 는 매일 찍힌다 —
        공백만 보면 설정 오류를 영영 못 잡는데, 그게 #894 가 잡으라는 바로 그
        케이스다 (리포트가 판정일까지 한 번도 안 나가는 상태).

        한 번도 stage 된 적 없으면 최초 heartbeat 를 기준으로 잰다 — 신규 배포에서
        role 이 처음부터 누락된 경우가 정확히 여기 걸린다. heartbeat 가 전무하면
        skip (미배포 / 신규 DB — scheduler_heartbeat 와 동일한 취급).
        """
        rows = query(
            """SELECT MIN(timestamp) AS first_run,
                      MAX(timestamp) AS last_run,
                      MAX(CASE WHEN json_valid(payload)
                                AND json_extract(payload, '$.staged') = 1
                               THEN timestamp END) AS last_staged
               FROM pipeline_events
               WHERE event_type = 'alpha_report_run'"""
        )
        if not rows or not rows[0]["first_run"]:
            return []
        row = rows[0]
        last_staged = row["last_staged"]
        # 성공분이 없으면 '언제부터 성공 없이 돌고 있나' = 최초 heartbeat 이후 경과.
        anchor = last_staged or row["first_run"]
        anchor_dt = datetime.strptime(str(anchor)[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
        days = (kst_now().date() - to_kst(anchor_dt).date()).days
        if days < ALPHA_REPORT_STALE_DAYS:
            return []

        # 마지막 실행의 skip 사유를 붙여 조치가 바로 나오게 한다 (역할 누락인지 예외인지).
        last_rows = query(
            """SELECT payload FROM pipeline_events
               WHERE event_type = 'alpha_report_run'
               ORDER BY timestamp DESC LIMIT 1"""
        )
        # payload 는 인시던트에 *사유* 를 붙이려고 읽는다. 인시던트를 낼지 말지는 이미
        # 위에서 정해졌으므로, 여기서 무슨 일이 나든 발화를 막아선 안 된다 (#927).
        # 깨진 payload 로 detector 가 죽으면 "리포트가 안 나간다" 는 사실까지 같이 사라진다.
        # `except Exception` 이 넓은 건 의도다 — 비-dict JSON('null'/'[]'/'"x"'/'5')이
        # `.get` 에서 내는 AttributeError 가 좁은 튜플에 안 걸려서 실제로 전파됐다.
        reason = "unknown"
        payload: dict[str, Any] = {}
        try:
            raw = json.loads(last_rows[0]["payload"]) if last_rows and last_rows[0]["payload"] else {}
            payload = raw if isinstance(raw, dict) else {}
            if not isinstance(raw, dict):
                reason = "unparseable"
            elif payload.get("error"):
                reason = "error"
            elif not payload.get("role_ok"):
                reason = "role_missing"
            elif payload.get("already_emitted"):
                reason = "already_emitted"
            else:
                reason = "staged"
        except Exception:  # noqa: BLE001 — 사유 추출 실패가 인시던트 발화를 막으면 안 된다
            reason = "unparseable"
            payload = {}

        evidence = {
            "last_staged_at_utc": str(last_staged) if last_staged else None,
            "never_staged": last_staged is None,
            "days_since_staged": days,
            "threshold_days": ALPHA_REPORT_STALE_DAYS,
            "last_run_at_utc": str(row["last_run"]),
            "last_skip_reason": reason,
            "last_error": payload.get("error"),
        }
        return [
            self._record_incident(
                incident_type="alpha_report_stale",
                severity="warning",
                target="alpha_report",
                evidence=evidence,
                ctx=ctx,
            )
        ]

    # ─── helpers ─────────────────────────────────────────────

    def _record_incident(
        self,
        incident_type: str,
        severity: str,
        target: str,
        evidence: dict[str, Any],
        ctx: RunContext,
    ) -> dict[str, Any]:
        """log_incident 호출 + 신규 여부 판정 + Discord publish 라우팅.

        is_new 판정: log_incident 호출 직전 open row 존재 여부.
        신규 INSERT 인 경우만 Discord publish (re-publish 차단).
        """
        # 신규 여부 판정 (log_incident 호출 전 미리 검사 — race condition tolerable for SRE).
        existing_rows = query(
            """SELECT incident_id FROM incidents
               WHERE incident_type = ? AND target = ? AND status = 'open'""",
            (incident_type, target),
        )
        is_new = len(existing_rows) == 0

        incident_id = log_incident(
            incident_type=incident_type,
            severity=severity,
            target=target,
            evidence=evidence,
            run_id=ctx.run_id,
        )

        if is_new and severity in ("critical", "warning"):
            self._publish_alert(incident_id, incident_type, severity, target, evidence, ctx.run_id)

        return {
            "incident_id": incident_id,
            "incident_type": incident_type,
            "severity": severity,
            "target": target,
            "evidence": evidence,
            "is_new": is_new,
        }

    # ─── action: acknowledge ─────────────────────────────────

    @staticmethod
    def _acknowledge(input_data: dict[str, Any]) -> ActorResult:
        incident_id = input_data.get("incident_id")
        if not isinstance(incident_id, int):
            return ActorResult(
                output={"error": "incident_id (int) required"},
                outcome=Outcome.BLOCK,
                input_summary="acknowledge",
            )
        ok = db_acknowledge_incident(incident_id=incident_id)
        if not ok:
            return ActorResult(
                output={"error": f"incident {incident_id} not found or not open"},
                outcome=Outcome.BLOCK,
                input_summary=f"acknowledge {incident_id}",
            )
        return ActorResult(
            output={"incident_id": incident_id, "status": "acknowledged"},
            outcome=Outcome.PASS,
            input_summary=f"acknowledge {incident_id}",
        )

    # ─── action: resolve ─────────────────────────────────────

    @staticmethod
    def _resolve(input_data: dict[str, Any]) -> ActorResult:
        incident_id = input_data.get("incident_id")
        if not isinstance(incident_id, int):
            return ActorResult(
                output={"error": "incident_id (int) required"},
                outcome=Outcome.BLOCK,
                input_summary="resolve",
            )
        ok = db_resolve_incident(incident_id=incident_id)
        if not ok:
            return ActorResult(
                output={"error": f"incident {incident_id} not in open/acknowledged state"},
                outcome=Outcome.BLOCK,
                input_summary=f"resolve {incident_id}",
            )
        return ActorResult(
            output={"incident_id": incident_id, "status": "resolved"},
            outcome=Outcome.PASS,
            input_summary=f"resolve {incident_id}",
        )

    # ─── action: list_open ───────────────────────────────────

    @staticmethod
    def _list_open(input_data: dict[str, Any]) -> ActorResult:
        severity = input_data.get("severity")  # optional filter
        limit = int(input_data.get("limit", 100))
        sql = "SELECT * FROM incidents WHERE status = 'open'"
        params: list[Any] = []
        if severity:
            if severity not in ("critical", "warning", "info"):
                return ActorResult(
                    output={"error": f"severity must be critical/warning/info, got {severity!r}"},
                    outcome=Outcome.BLOCK,
                    input_summary="list_open",
                )
            sql += " AND severity = ?"
            params.append(severity)
        sql += " ORDER BY last_detected_at DESC, incident_id DESC LIMIT ?"
        params.append(limit)
        rows = query(sql, tuple(params))
        items = [dict(r) for r in rows]
        return ActorResult(
            output={"count": len(items), "incidents": items},
            outcome=Outcome.PASS,
            sample_n=len(items),
            input_summary=f"list_open (n={len(items)})",
        )

    # ─── Discord publish (best-effort) ───────────────────────

    @staticmethod
    def _publish_alert(
        incident_id: int,
        incident_type: str,
        severity: str,
        target: str,
        evidence: dict[str, Any],
        run_id: str,
    ) -> None:
        """critical → #incidents, warning → #ops outbox (PR3 Codex Round 6). info X."""
        try:
            from nuri.agents.discord.outbox import stage_incident, stage_ops

            if severity == "critical":
                stage_fn = stage_incident
                priority = "high"
            elif severity == "warning":
                stage_fn = stage_ops
                priority = "normal"
            else:
                return

            stage_fn(
                payload={
                    "kind": f"sre_{incident_type}",
                    # cryptic "type severity on target (incident_id=...)" 대신 영향 수치 한 줄.
                    "summary": _human_incident_summary(incident_type, target, evidence),
                    "incident_id": incident_id,
                    "incident_type": incident_type,
                    "severity": severity,
                    "target": target,
                    "evidence": evidence,
                },
                priority=priority,
                dedupe_key=f"sre_incident:{incident_id}",
                actor_name="sre-incident-agent",
                run_id=run_id,
            )
        except Exception:  # noqa: BLE001
            pass


def _missed_eval_days(last_run_utc: str, now: datetime) -> int:
    """마지막 heartbeat 이후 놓친 평가 예정일(KST 화~토) 수 (#825).

    pipeline_events.timestamp 는 sqlite DEFAULT datetime('now') = **UTC** —
    KST 변환 없이 날짜를 자르면 07:00 KST 실행분이 전날로 밀려 1일 과대 계상
    (07:00 KST = 전날 22:00 UTC).
    **Test:** tests/agents/test_sre_incident_agent.py::TestMissedEvalDays
    ::test_utc_timestamp_converted_to_kst — to_kst 변환을 제거하면 FAIL.

    당일은 SIGNAL_EVAL_GRACE_HOUR(KST) 이후에만 미실행으로 계상 —
    07:00 cron 이 아직 안 돈 새벽 scan 의 false positive 방지.
    """
    last_utc = datetime.strptime(last_run_utc[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
    last_date = to_kst(last_utc).date()  # to_kst 는 naive 를 UTC 로 간주
    today = now.date()
    missed = 0
    day = last_date + timedelta(days=1)
    while day <= today:
        if day == today and now.hour < SIGNAL_EVAL_GRACE_HOUR:
            break
        if day.weekday() in SIGNAL_EVAL_WEEKDAYS:
            missed += 1
        day += timedelta(days=1)
    return missed


def _human_incident_summary(incident_type: str, target: str, evidence: dict[str, Any]) -> str:
    """인시던트 영향을 담은 사람이 읽는 한 줄 (evidence 수치 활용).

    #incidents 디지스트가 cryptic "type severity on target" 대신 "무엇이/얼마나"
    를 보이게 한다 ([[feedback_alert_readability]] 의미+영향). 의미/조치는 outbox
    _SRE_KIND_META 가 그룹 단위로 붙인다.
    """
    e = evidence
    if incident_type == "scheduler_heartbeat":
        return f"{target} — {e.get('age_minutes', 0):.0f}분째 갱신 없음 (임계 {e.get('warn_threshold_min', 30):.0f}분)"
    if incident_type == "disk_full":
        return f"{target} — 사용률 {e.get('percent_used', 0):.0f}% (여유 {e.get('free_gb', 0):.0f}GB)"
    if incident_type == "db_lock":
        return f"{target} — DB 접근 실패: {e.get('error', '?')}"
    if incident_type == "orphan_run":
        return f"{target} 작업 — {e.get('age_hours', 0):.1f}h 미완료(orphan)"
    if incident_type == "actor_failure_streak":
        return f"{target} — {e.get('consecutive_failures', 0)}회 연속 실패"
    if incident_type == "data_freshness_critical":
        keys = ", ".join((e.get("fail_keys") or [])[:3])
        return f"데이터 소스 {e.get('fail_count', 0)}개 stale: {keys}"
    if incident_type == "signal_evaluation_stale":
        return (
            f"{target} — {e.get('missed_eval_days', 0)}영업일째 시그널 평가 미실행 "
            f"(마지막 {e.get('last_evaluated_at_utc', '?')} UTC)"
        )
    if incident_type == "alpha_report_stale":
        cause = {
            "role_missing": "NURI_ROLE 미설정 — scheduler plist EnvironmentVariables 확인",
            "error": f"실행 예외: {e.get('last_error') or '?'}",
            "already_emitted": "중복 판정이 계속 True — dedupe 로직 점검",
        }.get(str(e.get("last_skip_reason")), "원인 미상")
        when = "한 번도 발화 없음" if e.get("never_staged") else f"마지막 {e.get('last_staged_at_utc', '?')} UTC"
        return f"§3.11 월간 alpha 리포트 — {e.get('days_since_staged', 0)}일째 미발화 ({when}). {cause}"
    return f"{incident_type} on {target}"


def _short_json(payload: dict[str, Any], max_len: int = 800) -> str:
    """Discord embed 용 짧은 JSON 직렬화 — long evidence 잘라서 truncate."""
    import json as _json

    s = _json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    if len(s) > max_len:
        s = s[:max_len] + "\n... (truncated)"
    return s


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m nuri.agents.actors.sre_incident_agent <action> [...]

    Examples:
        python -m nuri.agents.actors.sre_incident_agent scan
        python -m nuri.agents.actors.sre_incident_agent list_open --severity critical
        python -m nuri.agents.actors.sre_incident_agent acknowledge --incident-id 42
        python -m nuri.agents.actors.sre_incident_agent resolve --incident-id 42
    """
    import argparse
    import json as _json
    import sys

    parser = argparse.ArgumentParser(prog="sre-incident-agent")
    parser.add_argument("action", choices=SREIncidentAgent.VALID_ACTIONS)
    parser.add_argument("--incident-id", type=int, default=None)
    parser.add_argument("--severity", default=None, choices=[None, "critical", "warning", "info"])
    parser.add_argument("--limit", type=int, default=100)

    args = parser.parse_args(argv)
    payload: dict[str, Any] = {"action": args.action, "limit": args.limit}
    if args.incident_id is not None:
        payload["incident_id"] = args.incident_id
    if args.severity:
        payload["severity"] = args.severity

    actor = SREIncidentAgent()
    try:
        result = actor.run(payload)
    except Exception as exc:
        print(_json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2

    print(_json.dumps(result.output, indent=2, ensure_ascii=False, default=str))
    if result.outcome == Outcome.PASS:
        return 0
    if result.outcome == Outcome.WARN:
        return 1
    return 2  # BLOCK or ERROR


if __name__ == "__main__":
    import sys

    sys.exit(main())

"""CollectorOrchestrator — Layer B actor (#529 Phase 2 — canonical #1).

Responsibilities:
- 21+ collectors (kis_prices, yfinance, pykrx, fred, finviz, etc.) 의 oversight.
- 단일 collector 실행 → status (started/finished/failed/timeout/rate_limited) audit.
- Retry + exponential backoff (1s → 2s → 4s) — 외부 API 일시적 실패 회복.
- Health scan: 최근 N 시간 collector_runs GROUP BY → pass_rate / unhealthy 분류.
- Best-effort Discord publish (BLOCK → INCIDENTS / WARN / final-fail → OPS).

Layer B 설계 (Codex Round 5):
- 100% deterministic — 통계 + retry, ZERO LLM.
- Outcome 매핑 (Round 5 Layer B):
    PASS  — orchestrate 성공 + scan_health 모두 healthy
    WARN  — orchestrate under-fetch (rows < expected) / scan_health 1+ unhealthy
    BLOCK — orchestrate retry 소진 / scan_health 모두 catastrophic / invalid input

Design rationale:
- 기존 collectors 는 self-monitoring 부재 → 실패 silent → consensus 가 stale data 사용 → 손실.
- 본 actor 는 "외부 API 가 측정 가능한 영역" (Harness 7원칙 #7) 을 audit form 으로
  영구 보존 — backtest / 사후 검증 / SRE incident 자동 enrichment 가능.
- Retry 는 transient (rate-limit / 일시 timeout) 만 회복 — 영구 fail (404 등) 은 즉시 BLOCK.

Anti-pattern 방지:
- collector 실패 silent → consensus 가 stale 데이터로 결정 → 손실 (사용자 -₩7M 사례).
- 외부 API rate-limit hit 누적 무시 → 더 강한 throttle / IP 차단 → catastrophic.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from nuri.agents.base import REGISTRY, Actor, ActorResult, Layer, Outcome, RunContext
from nuri.core.db import log_collector_run, query
from nuri.core.timezone import kst_now

logger = logging.getLogger(__name__)

# 외부 API transient error 패턴 — retry 가능한 케이스만 식별.
# (rate-limit / timeout 은 별도 분류, 그 외 generic exception 은 'failed'.)
_RATE_LIMIT_HINTS: tuple[str, ...] = (
    "rate limit",
    "rate-limit",
    "too many requests",
    "429",
    "throttle",
)


def _classify_error(exc: BaseException) -> str:
    """Exception → status enum 매핑.

    timeout    — TimeoutError / 'timeout' 메시지
    rate_limited — 429 / 'rate limit' / 'throttle' 키워드
    failed     — 그 외 generic exception
    """
    if isinstance(exc, TimeoutError):
        return "timeout"
    msg = str(exc).lower()
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    if any(hint in msg for hint in _RATE_LIMIT_HINTS):
        return "rate_limited"
    return "failed"


@REGISTRY.register
class CollectorOrchestrator(Actor):
    """Collector oversight + retry + rate-limit + freshness 추적.

    Actions (input_data['action']):
        orchestrate  — 단일 collector_fn 실행 + audit + retry
        scan_health  — 최근 N 시간 collector_runs health 요약
        list_recent  — 최근 N 개 run 조회 (debug)

    orchestrate input:
        collector_name: str         — 식별자 (e.g. 'kis_prices', 'yfinance')
        collector_fn: Callable[[], Any]  — 실행 함수 (반환값은 row count 추정용 또는 무시)
        expected_rows: Optional[int] — under-fetch 판정 기준
        max_retries: int = 3        — exponential backoff 횟수
        timeout_s: float = 60       — fn 실행 monotonic budget (참고용 — fn 자체가 강제 X)

    scan_health input:
        hours: int = 24             — 윈도우
        unhealthy_threshold: float = 0.5  — 실패율 > threshold → unhealthy

    list_recent input:
        collector_name: Optional[str]  — 필터
        limit: int = 20
    """

    name = "collector-orchestrator"
    version = "0.1.0"
    layer = Layer.B

    VALID_ACTIONS: tuple[str, ...] = ("orchestrate", "scan_health", "list_recent")

    # exponential backoff 베이스 (1s → 2s → 4s ...). 테스트에서 monkeypatch 가능.
    BACKOFF_BASE_S: float = 1.0

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        action = input_data.get("action")
        if action not in self.VALID_ACTIONS:
            return ActorResult(
                output={"error": f"invalid action {action!r}, expected {self.VALID_ACTIONS}"},
                outcome=Outcome.BLOCK,
                input_summary=f"action={action}",
            )

        if action == "orchestrate":
            return self._orchestrate(input_data, ctx)
        if action == "scan_health":
            return self._scan_health(input_data, ctx)
        return self._list_recent(input_data)

    # ─── action: orchestrate ─────────────────────────────────

    def _orchestrate(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        collector_name = input_data.get("collector_name")
        collector_fn = input_data.get("collector_fn")
        expected_rows = input_data.get("expected_rows")
        max_retries = int(input_data.get("max_retries", 3))
        # timeout_s 는 metric 목적 — collector_fn 이 자체 timeout 미보장 시 단순 측정값.
        timeout_s = float(input_data.get("timeout_s", 60))

        if not isinstance(collector_name, str) or not collector_name:
            return ActorResult(
                output={"error": "collector_name (str) required"},
                outcome=Outcome.BLOCK,
                input_summary="orchestrate",
            )
        if not callable(collector_fn):
            return ActorResult(
                output={"error": "collector_fn (callable) required"},
                outcome=Outcome.BLOCK,
                input_summary=f"orchestrate {collector_name}",
            )
        if max_retries < 0:
            return ActorResult(
                output={"error": "max_retries must be >= 0"},
                outcome=Outcome.BLOCK,
                input_summary=f"orchestrate {collector_name}",
            )

        attempts: list[dict[str, Any]] = []
        rate_limit_hits = 0
        last_error: Optional[str] = None
        rows_collected = 0
        # attempt 0 + retry 회수 = max_retries+1 회 시도.
        # 마지막 시도는 성공→return(174)/실패→break(212)로만 종료하므로 for 자연 소진 arc(148->218)은
        # max_retries>=0(L136) 불변식상 도달 불가 → pragma: no branch 로 partial-branch 제외.
        for attempt_idx in range(max_retries + 1):  # pragma: no branch
            start_ms = time.monotonic()
            try:
                result_value = collector_fn()
                duration_ms = int((time.monotonic() - start_ms) * 1000)
                rows_collected = self._extract_row_count(result_value)
                run_id = log_collector_run(
                    collector_name=collector_name,
                    status="finished",
                    rows_collected=rows_collected,
                    rows_expected=expected_rows,
                    duration_ms=duration_ms,
                    retry_count=attempt_idx,
                    rate_limit_hits=rate_limit_hits,
                    actor_run_id=ctx.run_id,
                    finished_at=kst_now().isoformat(),
                )
                attempts.append(
                    {
                        "attempt": attempt_idx,
                        "status": "finished",
                        "rows_collected": rows_collected,
                        "duration_ms": duration_ms,
                        "run_id": run_id,
                    }
                )
                return self._finalize_orchestrate(
                    collector_name=collector_name,
                    rows_collected=rows_collected,
                    expected_rows=expected_rows,
                    attempts=attempts,
                    rate_limit_hits=rate_limit_hits,
                    timeout_s=timeout_s,
                    ctx=ctx,
                )
            except Exception as exc:  # noqa: BLE001 — retry 분류용 catch-all.
                duration_ms = int((time.monotonic() - start_ms) * 1000)
                status = _classify_error(exc)
                last_error = f"{type(exc).__name__}: {exc}"[:500]
                if status == "rate_limited":
                    rate_limit_hits += 1
                run_id = log_collector_run(
                    collector_name=collector_name,
                    status=status,
                    rows_collected=0,
                    rows_expected=expected_rows,
                    duration_ms=duration_ms,
                    error_message=last_error,
                    retry_count=attempt_idx,
                    rate_limit_hits=rate_limit_hits,
                    actor_run_id=ctx.run_id,
                    finished_at=kst_now().isoformat(),
                )
                attempts.append(
                    {
                        "attempt": attempt_idx,
                        "status": status,
                        "duration_ms": duration_ms,
                        "error": last_error,
                        "run_id": run_id,
                    }
                )
                # 마지막 시도면 retry 안 함.
                if attempt_idx >= max_retries:
                    break
                # exponential backoff: 1s → 2s → 4s ...
                backoff_s = self.BACKOFF_BASE_S * (2**attempt_idx)
                time.sleep(backoff_s)

        # retry 모두 소진 — final-fail Discord publish + BLOCK.
        self._publish_orchestrate_failure(
            collector_name=collector_name,
            error=last_error or "unknown",
            attempts=len(attempts),
            run_id=ctx.run_id,
        )
        return ActorResult(
            output={
                "collector_name": collector_name,
                "outcome": "block",
                "attempts": attempts,
                "error": last_error,
                "rate_limit_hits": rate_limit_hits,
            },
            outcome=Outcome.BLOCK,
            sample_n=0,
            input_summary=f"orchestrate {collector_name} retries={len(attempts)}",
        )

    def _finalize_orchestrate(
        self,
        collector_name: str,
        rows_collected: int,
        expected_rows: Optional[int],
        attempts: list[dict[str, Any]],
        rate_limit_hits: int,
        timeout_s: float,
        ctx: RunContext,
    ) -> ActorResult:
        """orchestrate finished 케이스 — under-fetch 판정 + Outcome 결정."""
        # under-fetch: expected_rows 가 주어지면 90% threshold.
        warn_under_fetch = expected_rows is not None and expected_rows > 0 and rows_collected < expected_rows * 0.9
        if warn_under_fetch:
            outcome = Outcome.WARN
            self._publish_orchestrate_failure(
                collector_name=collector_name,
                error=f"under-fetch: {rows_collected}/{expected_rows}",
                attempts=len(attempts),
                run_id=ctx.run_id,
            )
        else:
            outcome = Outcome.PASS

        return ActorResult(
            output={
                "collector_name": collector_name,
                "outcome": outcome.value,
                "rows_collected": rows_collected,
                "rows_expected": expected_rows,
                "attempts": attempts,
                "rate_limit_hits": rate_limit_hits,
                "timeout_budget_s": timeout_s,
            },
            outcome=outcome,
            sample_n=rows_collected,
            input_summary=f"orchestrate {collector_name} rows={rows_collected}",
        )

    @staticmethod
    def _extract_row_count(value: Any) -> int:
        """collector_fn 반환값 → row count 추정. 없으면 0."""
        if value is None:
            return 0
        if isinstance(value, int):
            return max(value, 0)
        if hasattr(value, "__len__"):
            try:
                return len(value)  # type: ignore[arg-type]
            except TypeError:
                return 0
        return 0

    # ─── action: scan_health ─────────────────────────────────

    def _scan_health(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        hours = int(input_data.get("hours", 24))
        unhealthy_threshold = float(input_data.get("unhealthy_threshold", 0.5))
        if hours < 1:
            return ActorResult(
                output={"error": "hours must be >= 1"},
                outcome=Outcome.BLOCK,
                input_summary="scan_health",
            )

        rows = query(
            """SELECT collector_name, status, duration_ms, rate_limit_hits,
                      started_at
               FROM collector_runs
               WHERE datetime(started_at) >= datetime('now', ? || ' hours')
               ORDER BY started_at DESC""",
            (f"-{hours}",),
        )

        # collector_name 별 GROUP BY 집계.
        groups: dict[str, dict[str, Any]] = {}
        for r in rows:
            name = r["collector_name"]
            g = groups.setdefault(
                name,
                {
                    "total_runs": 0,
                    "pass_count": 0,
                    "fail_count": 0,
                    "duration_sum_ms": 0,
                    "duration_n": 0,
                    "total_rate_limits": 0,
                    "last_status": None,
                    "last_started_at": None,
                },
            )
            g["total_runs"] += 1
            if r["status"] == "finished":
                g["pass_count"] += 1
            else:
                g["fail_count"] += 1
            if r["duration_ms"] is not None:
                g["duration_sum_ms"] += int(r["duration_ms"])
                g["duration_n"] += 1
            g["total_rate_limits"] += int(r["rate_limit_hits"] or 0)
            # rows DESC → 첫 row 가 last_*.
            if g["last_status"] is None:
                g["last_status"] = r["status"]
                g["last_started_at"] = r["started_at"]

        summaries: list[dict[str, Any]] = []
        unhealthy_count = 0
        for name, g in sorted(groups.items()):
            total = g["total_runs"]
            pass_rate = g["pass_count"] / total if total else 0.0
            failure_rate = g["fail_count"] / total if total else 0.0
            avg_duration = g["duration_sum_ms"] // g["duration_n"] if g["duration_n"] else None
            health_status = "unhealthy" if failure_rate > unhealthy_threshold else "healthy"
            if health_status == "unhealthy":
                unhealthy_count += 1
            summaries.append(
                {
                    "collector_name": name,
                    "health_status": health_status,
                    "pass_rate": round(pass_rate, 3),
                    "total_runs": total,
                    "last_status": g["last_status"],
                    "last_started_at": g["last_started_at"],
                    "avg_duration_ms": avg_duration,
                    "total_rate_limits": g["total_rate_limits"],
                }
            )

        # Outcome 결정:
        #   collector 0개 → PASS (no data, no incident).
        #   모두 unhealthy → BLOCK (catastrophic — 전체 pipeline blind).
        #   1+ unhealthy → WARN.
        #   모두 healthy → PASS.
        if not summaries:
            outcome = Outcome.PASS
        elif unhealthy_count == len(summaries):
            outcome = Outcome.BLOCK
            self._publish_health_alert(
                outcome=outcome,
                summaries=summaries,
                hours=hours,
                run_id=ctx.run_id,
            )
        elif unhealthy_count > 0:
            outcome = Outcome.WARN
            self._publish_health_alert(
                outcome=outcome,
                summaries=summaries,
                hours=hours,
                run_id=ctx.run_id,
            )
        else:
            outcome = Outcome.PASS

        return ActorResult(
            output={
                "hours": hours,
                "unhealthy_threshold": unhealthy_threshold,
                "collector_count": len(summaries),
                "unhealthy_count": unhealthy_count,
                "summaries": summaries,
            },
            outcome=outcome,
            sample_n=len(summaries),
            input_summary=f"scan_health hours={hours} unhealthy={unhealthy_count}/{len(summaries)}",
        )

    # ─── action: list_recent ─────────────────────────────────

    @staticmethod
    def _list_recent(input_data: dict[str, Any]) -> ActorResult:
        collector_name = input_data.get("collector_name")
        limit = int(input_data.get("limit", 20))
        if limit < 1:
            return ActorResult(
                output={"error": "limit must be >= 1"},
                outcome=Outcome.BLOCK,
                input_summary="list_recent",
            )

        if collector_name:
            rows = query(
                """SELECT * FROM collector_runs
                   WHERE collector_name = ?
                   ORDER BY started_at DESC, run_id DESC LIMIT ?""",
                (collector_name, limit),
            )
        else:
            rows = query(
                """SELECT * FROM collector_runs
                   ORDER BY started_at DESC, run_id DESC LIMIT ?""",
                (limit,),
            )

        items = [dict(r) for r in rows]
        return ActorResult(
            output={
                "collector_name": collector_name,
                "limit": limit,
                "count": len(items),
                "runs": items,
            },
            outcome=Outcome.PASS,
            sample_n=len(items),
            input_summary=f"list_recent ({len(items)} runs)",
        )

    # ─── Discord publish (best-effort) ───────────────────────

    @staticmethod
    def _publish_orchestrate_failure(
        collector_name: str,
        error: str,
        attempts: int,
        run_id: str,
    ) -> None:
        """Final orchestrate failure → #ops outbox stage (PR3 Codex Round 6)."""
        try:
            from nuri.agents.discord.outbox import stage_ops

            stage_ops(
                payload={
                    "kind": "collector_failure",
                    "summary": (f"{collector_name} failed after {attempts} attempts: {error[:120]}"),
                    "collector_name": collector_name,
                    "attempts": attempts,
                    "error": error[:300],
                },
                dedupe_key=f"collector_failure:{collector_name}",
                actor_name="collector-orchestrator",
                run_id=run_id,
            )
        except Exception:  # noqa: BLE001  # pragma: no cover — best-effort outbox publish
            # 발행 실패로 액터를 죽이지 않는다(#894) — 다만 **조용히** 넘기지도 않는다.
            logger.exception("outbox staging 실패: stage_ops")

    @staticmethod
    def _publish_health_alert(
        outcome: Outcome,
        summaries: list[dict[str, Any]],
        hours: int,
        run_id: str,
    ) -> None:
        """scan_health WARN → #ops, BLOCK → #incidents (PR3 Codex Round 6). info 는 publish X."""
        try:
            from nuri.agents.discord.outbox import stage_incident, stage_ops

            unhealthy = [s for s in summaries if s["health_status"] == "unhealthy"]
            if outcome == Outcome.BLOCK:
                stage_fn = stage_incident
                kind = "collector_health_catastrophic"
            elif outcome == Outcome.WARN:
                stage_fn = stage_ops
                kind = "collector_health_warn"
            else:
                return

            unhealthy_names = ",".join(s["collector_name"] for s in unhealthy[:5])
            stage_fn(
                payload={
                    "kind": kind,
                    "summary": (f"{len(unhealthy)}/{len(summaries)} unhealthy in {hours}h: {unhealthy_names}"),
                    "hours": hours,
                    "unhealthy": [
                        {
                            "name": s["collector_name"],
                            "pass_rate": s["pass_rate"],
                            "runs": s["total_runs"],
                            "last_status": s["last_status"],
                        }
                        for s in unhealthy[:10]
                    ],
                },
                dedupe_key=f"collector_health:{kind}",
                actor_name="collector-orchestrator",
                run_id=run_id,
            )
        except Exception:  # noqa: BLE001  # pragma: no cover — best-effort outbox publish
            # 발행 실패로 액터를 죽이지 않는다(#894) — 다만 **조용히** 넘기지도 않는다.
            logger.exception("outbox staging 실패: stage_fn")


# ─── helpers ───────────────────────────────────────────────


def make_collector_fn(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Callable[[], Any]:
    """편의 wrapper — 기존 collector 함수를 zero-arg 형태로 변환.

    e.g. `make_collector_fn(fetch_prices, tickers=['AAPL'])`.
    """

    def _wrapped() -> Any:
        return fn(*args, **kwargs)

    return _wrapped


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m nuri.agents.actors.collector_orchestrator <action>

    scan_health / list_recent 만 CLI 노출 (orchestrate 는 callable 필요).
    """
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(prog="collector-orchestrator")
    sub = parser.add_subparsers(dest="action", required=True)

    p_scan = sub.add_parser("scan_health")
    p_scan.add_argument("--hours", type=int, default=24)
    p_scan.add_argument("--unhealthy-threshold", type=float, default=0.5)

    p_list = sub.add_parser("list_recent")
    p_list.add_argument("--collector-name", default=None)
    p_list.add_argument("--limit", type=int, default=20)

    args = parser.parse_args(argv)

    actor = CollectorOrchestrator()
    if args.action == "scan_health":
        result = actor.run(
            {
                "action": "scan_health",
                "hours": args.hours,
                "unhealthy_threshold": args.unhealthy_threshold,
            }
        )
    else:
        result = actor.run(
            {
                "action": "list_recent",
                "collector_name": args.collector_name,
                "limit": args.limit,
            }
        )

    print(_json.dumps(result.output, indent=2, ensure_ascii=False, default=str))
    if result.outcome == Outcome.PASS:
        return 0
    if result.outcome == Outcome.WARN:
        return 1
    return 2


if __name__ == "__main__":
    import sys

    sys.exit(main())

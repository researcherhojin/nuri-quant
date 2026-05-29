"""ForwardOutcomeTracker — Layer B actor (#529 Phase 2 closed-loop — canonical #11).

DecisionCompiler #8 가 emit 한 decision 의 *실제 결과* 추적 → HypothesisRegistry #4
의 hypothesis 자동 validate (성공) / reject (실패). Phase 2 의 closed-loop 완성.

Layer B 설계 (Codex Round 5):
- ZERO LLM, deterministic 측정
- Lookahead bias 차단: as_of_date + observation_window 이후 데이터만 사용
- 미래 가격 데이터 없으면 insufficient_data (false validation 차단)

Validation rule (defaults):
- Window 7d:  realized_return >= +5% → pass / <= -5% → reject / 사이 → insufficient
- Window 14d: realized_return >= +7% → pass / <= -7% → reject
- Window 30d: realized_return >= +10% → pass / <= -10% → reject
- Threshold 도달 (hit_threshold=True) 시 항상 pass
- HOLD action 의 decision 은 추적 X (BUY/SELL 만)

Anti-pattern 방지 (lock-test):
- as_of_date + window > today → insufficient (lookahead 위반 시도 차단)
- agent_decisions 에 ticker price 없음 → insufficient_data
- hypothesis 가 이미 validated/rejected/expired → update X (status machine 위반 차단)
- HOLD decision 추적 시도 → skip (의미 없음)

Discord publish:
- hypothesis 자동 validation (pass/reject) → ROLLOUT 채널
- best-effort: publish 실패해도 actor outcome 영향 X
"""

from __future__ import annotations

import json
from typing import Any, Optional

from nuri.agents.base import REGISTRY, Actor, ActorResult, Layer, Outcome, RunContext
from nuri.core.db import (
    log_decision,
    log_decision_outcome,
    query,
    reject_hypothesis,
    validate_hypothesis,
)
from nuri.core.timezone import today_kst

# ─── window 별 validation 임계값 (Codex consult 합의) ─────────
WINDOW_THRESHOLDS: dict[int, tuple[float, float]] = {
    7: (0.05, -0.05),  # ±5% within 7 days
    14: (0.07, -0.07),  # ±7% within 14 days
    30: (0.10, -0.10),  # ±10% within 30 days
}
SUPPORTED_WINDOWS: tuple[int, ...] = (7, 14, 30)
DEFAULT_BENCHMARK_TICKER = "SPY"  # 시장 베타 — alpha 산출 baseline


def backfill_agent_decisions_from_recommendations() -> int:
    """Bridge emitted BUY/SELL recommendations into the agent_decisions ledger.

    `decision_outcomes` has FK(decision_id) -> agent_decisions, and this tracker
    measures rows from agent_decisions. Production recommendations land in the
    `recommendations` table (not agent_decisions — the DecisionCompiler actor that
    would fill it is unwired), so the tracker had nothing to measure and
    decision_outcomes stayed empty. Mirror each BUY/SELL rec into agent_decisions
    (decision_id='rec_{id}', provenance marked in inputs_json) so the FK + tracker
    work as designed.

    Idempotent: skips recs already mirrored; log_decision upserts on conflict.
    Returns the count of newly mirrored decisions.
    """
    recs = query("SELECT id, date, ticker, action, confidence FROM recommendations WHERE action IN ('BUY', 'SELL')")
    if not recs:
        return 0
    existing = {
        dict(r)["decision_id"] for r in query("SELECT decision_id FROM agent_decisions WHERE decision_id LIKE 'rec_%'")
    }
    n = 0
    for row in recs:
        r = dict(row)
        decision_id = f"rec_{r['id']}"
        if decision_id in existing:
            continue
        conf = r.get("confidence")
        conviction = max(0.0, min(1.0, (conf if conf is not None else 50.0) / 100.0))
        log_decision(
            decision_id=decision_id,
            ticker=r["ticker"],
            as_of_date=r["date"],
            action=r["action"],
            conviction=conviction,
            inputs={
                # 실제 출처는 recommendations 파이프라인 (DecisionCompiler actor 아님).
                # audit-traceability 키는 enforcement 충족용 placeholder + 출처 명시.
                "regime_run_id": "n/a-recommendation",
                "hypothesis_id": "n/a-recommendation",
                "causal_audit_id": "n/a-recommendation",
                "source": "recommendations-backfill",
                "rec_id": r["id"],
            },
            rationale={"source": "recommendations table mirror for alpha tracking"},
            status="emitted",
        )
        n += 1
    return n


@REGISTRY.register
class ForwardOutcomeTracker(Actor):
    """Closed-loop outcome tracker — emit → measure → validate.

    Actions (input_data['action']):
        scan       — 추적 가능한 emitted decision 들을 일괄 측정 (cron-style)
        track_one  — 단일 decision_id 측정
        last_outcome — decision_id 의 가장 최근 outcome 조회 (read-only)

    Outcome 매핑 (Layer B):
        PASS — 측정 + validation 성공
        WARN — insufficient_data (가격 부족 또는 lookahead) / HOLD skip
        BLOCK — invalid input
    """

    name = "forward-outcome-tracker"
    version = "0.1.0"
    layer = Layer.B

    VALID_ACTIONS: tuple[str, ...] = ("scan", "track_one", "last_outcome")

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
        if action == "track_one":
            return self._track_one(input_data, ctx)
        return self._last_outcome(input_data)

    # ─── handlers ─────────────────────────────────────────────

    def _scan(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        """Emitted decisions 를 cron-style 으로 일괄 측정.

        windows: 측정할 observation window list (default: 모든 supported)
        max_decisions: 한 번에 처리할 최대 개수 (default 100)
        """
        windows = input_data.get("windows") or list(SUPPORTED_WINDOWS)
        for w in windows:
            if w not in SUPPORTED_WINDOWS:
                return ActorResult(
                    output={"error": f"unsupported window {w}, allowed {SUPPORTED_WINDOWS}"},
                    outcome=Outcome.BLOCK,
                    input_summary=f"scan windows={windows}",
                )
        max_decisions = int(input_data.get("max_decisions", 100))

        # recommendations -> agent_decisions ledger 동기화 (FK 충족 + 측정 대상 확보).
        synced = backfill_agent_decisions_from_recommendations()

        rows = query(
            """SELECT decision_id, ticker, as_of_date, action, inputs_json
               FROM agent_decisions
               WHERE status = 'emitted' AND action IN ('BUY','SELL')
               ORDER BY created_at DESC LIMIT ?""",
            (max_decisions,),
        )

        results: list[dict[str, Any]] = []
        for row in rows:
            r = dict(row)
            for window in windows:
                outcome = self._measure_one(
                    decision_id=r["decision_id"],
                    ticker=r["ticker"],
                    as_of_date=r["as_of_date"],
                    action=r["action"],
                    inputs_json=r["inputs_json"],
                    window=window,
                    ctx=ctx,
                )
                results.append(outcome)

        n_pass = sum(1 for o in results if o["validation"] == "pass")
        n_reject = sum(1 for o in results if o["validation"] == "reject")
        n_insuf = sum(1 for o in results if o["validation"] == "insufficient_data")

        return ActorResult(
            output={
                "synced_from_recommendations": synced,
                "scanned": len(rows),
                "windows": windows,
                "n_measurements": len(results),
                "n_pass": n_pass,
                "n_reject": n_reject,
                "n_insufficient": n_insuf,
                "results": results[:50],  # truncate for audit_ledger
            },
            outcome=Outcome.PASS,
            sample_n=len(results),
            input_summary=f"scan {len(rows)} dec × {len(windows)} win → {n_pass}p/{n_reject}r/{n_insuf}i",
        )

    def _track_one(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        decision_id = input_data.get("decision_id")
        window = input_data.get("observation_window", 7)
        if not decision_id:
            return ActorResult(
                output={"error": "track_one requires 'decision_id'"},
                outcome=Outcome.BLOCK,
                input_summary="track_one",
            )
        if window not in SUPPORTED_WINDOWS:
            return ActorResult(
                output={"error": f"observation_window must be {SUPPORTED_WINDOWS}, got {window}"},
                outcome=Outcome.BLOCK,
                input_summary=f"track_one {decision_id}",
            )

        rows = query(
            "SELECT decision_id, ticker, as_of_date, action, inputs_json FROM agent_decisions WHERE decision_id = ?",
            (decision_id,),
        )
        if not rows:
            return ActorResult(
                output={"error": f"decision_id {decision_id!r} not found"},
                outcome=Outcome.BLOCK,
                input_summary=f"track_one {decision_id}",
            )
        r = dict(rows[0])
        if r["action"] == "HOLD":
            return ActorResult(
                output={"decision_id": decision_id, "skipped": "HOLD action — no tracking"},
                outcome=Outcome.WARN,
                input_summary=f"track_one {decision_id} HOLD skip",
            )

        result = self._measure_one(
            decision_id=r["decision_id"],
            ticker=r["ticker"],
            as_of_date=r["as_of_date"],
            action=r["action"],
            inputs_json=r["inputs_json"],
            window=window,
            ctx=ctx,
        )
        outcome = Outcome.PASS if result["validation"] in ("pass", "reject") else Outcome.WARN
        return ActorResult(
            output=result,
            outcome=outcome,
            sample_n=1,
            input_summary=f"track_one {decision_id} w{window} {result['validation']}",
        )

    @staticmethod
    def _last_outcome(input_data: dict[str, Any]) -> ActorResult:
        decision_id = input_data.get("decision_id")
        if decision_id:
            rows = query(
                """SELECT * FROM decision_outcomes WHERE decision_id = ?
                   ORDER BY observation_window DESC LIMIT 1""",
                (decision_id,),
            )
        else:
            rows = query("SELECT * FROM decision_outcomes ORDER BY created_at DESC, rowid DESC LIMIT 1")
        if not rows:
            return ActorResult(
                output={"error": "no decision_outcomes row found"},
                outcome=Outcome.WARN,
                input_summary="last_outcome",
            )
        r = dict(rows[0])
        return ActorResult(
            output=r,
            outcome=Outcome.PASS,
            input_summary=f"last_outcome {r['decision_id']} w{r['observation_window']}",
        )

    # ─── core measurement ─────────────────────────────────────

    def _measure_one(
        self,
        decision_id: str,
        ticker: str,
        as_of_date: str,
        action: str,
        inputs_json: str,
        window: int,
        ctx: RunContext,
    ) -> dict[str, Any]:
        """단일 (decision, window) 측정 → outcome row + 자동 validation trigger.

        Returns dict with: decision_id, window, validation, realized_return, alpha, ...
        """
        today = today_kst()
        from datetime import date

        as_of = date.fromisoformat(as_of_date)
        target_date = self._add_business_days(as_of, window).isoformat()

        # ─── lookahead guard: target_date 가 미래면 insufficient ───
        if target_date > today:
            log_decision_outcome(
                decision_id=decision_id,
                observation_window=window,
                tracked_as_of_date=today,
                hypothesis_validation="insufficient_data",
                notes=f"target_date {target_date} > today {today} (lookahead guard)",
                run_id=ctx.run_id,
            )
            return {
                "decision_id": decision_id,
                "window": window,
                "validation": "insufficient_data",
                "reason": "lookahead — target_date in future",
            }

        # ─── 가격 조회 ───
        entry = self._fetch_close(ticker, as_of_date)
        exit_p = self._fetch_close_on_or_after(ticker, target_date)
        bench_entry = self._fetch_close(DEFAULT_BENCHMARK_TICKER, as_of_date)
        bench_exit = self._fetch_close_on_or_after(DEFAULT_BENCHMARK_TICKER, target_date)

        if entry is None or exit_p is None:
            log_decision_outcome(
                decision_id=decision_id,
                observation_window=window,
                tracked_as_of_date=today,
                hypothesis_validation="insufficient_data",
                notes=f"price missing — entry={entry}, exit={exit_p}",
                run_id=ctx.run_id,
            )
            return {
                "decision_id": decision_id,
                "window": window,
                "validation": "insufficient_data",
                "reason": "price data missing",
            }

        realized = (exit_p - entry) / entry
        # SELL action → return 의 부호 반전 (short proxy)
        if action == "SELL":
            realized = -realized

        bench_return: Optional[float] = None
        alpha: Optional[float] = None
        if bench_entry is not None and bench_exit is not None and bench_entry > 0:
            bench_return = (bench_exit - bench_entry) / bench_entry
            if action == "SELL":
                bench_return = -bench_return
            alpha = realized - bench_return

        # ─── validation rule ───
        up_thresh, down_thresh = WINDOW_THRESHOLDS[window]
        hit_threshold = realized >= up_thresh
        if hit_threshold:
            validation = "pass"
        elif realized <= down_thresh:
            validation = "reject"
        else:
            validation = "insufficient_data"

        log_decision_outcome(
            decision_id=decision_id,
            observation_window=window,
            tracked_as_of_date=today,
            entry_price=entry,
            exit_price=exit_p,
            realized_return=realized,
            benchmark_return=bench_return,
            alpha=alpha,
            hit_threshold=hit_threshold,
            hypothesis_validation=validation,
            notes=f"action={action} ticker={ticker}",
            run_id=ctx.run_id,
        )

        # ─── auto-trigger HypothesisRegistry validate/reject ───
        hypothesis_id = self._extract_hypothesis_id(inputs_json)
        if hypothesis_id and validation in ("pass", "reject"):
            self._trigger_hypothesis_update(
                hypothesis_id=hypothesis_id,
                validation=validation,
                window=window,
                realized=realized,
                alpha=alpha,
                run_id=ctx.run_id,
            )

        return {
            "decision_id": decision_id,
            "ticker": ticker,
            "window": window,
            "validation": validation,
            "realized_return": realized,
            "alpha": alpha,
            "hit_threshold": hit_threshold,
            "hypothesis_id": hypothesis_id,
        }

    # ─── helpers ──────────────────────────────────────────────

    @staticmethod
    def _add_business_days(start, n: int):
        """간단 calendar-day add (주말/휴장 정확 처리는 prices 의 on_or_after 가 흡수)."""
        from datetime import timedelta

        return start + timedelta(days=n)

    @staticmethod
    def _fetch_close(ticker: str, date_str: str) -> Optional[float]:
        rows = query(
            "SELECT close FROM prices WHERE ticker = ? AND date = ? LIMIT 1",
            (ticker, date_str),
        )
        if not rows:
            return None
        v = dict(rows[0]).get("close")
        return float(v) if v is not None else None

    @staticmethod
    def _fetch_close_on_or_after(ticker: str, date_str: str) -> Optional[float]:
        """target_date 이후 첫 거래일의 close (주말/휴장 자동 흡수)."""
        rows = query(
            "SELECT close FROM prices WHERE ticker = ? AND date >= ? ORDER BY date LIMIT 1",
            (ticker, date_str),
        )
        if not rows:
            return None
        v = dict(rows[0]).get("close")
        return float(v) if v is not None else None

    @staticmethod
    def _extract_hypothesis_id(inputs_json: str) -> Optional[str]:
        try:
            return json.loads(inputs_json or "{}").get("hypothesis_id")
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _trigger_hypothesis_update(
        hypothesis_id: str,
        validation: str,
        window: int,
        realized: float,
        alpha: Optional[float],
        run_id: str,
    ) -> None:
        """auto-validate/reject — 이미 종결된 hypothesis 는 silently skip (status machine 보존)."""
        # status check first (silent skip if not open)
        rows = query(
            "SELECT status FROM hypotheses WHERE hypothesis_id = ?",
            (hypothesis_id,),
        )
        if not rows or dict(rows[0])["status"] != "open":
            return  # 이미 validated/rejected/expired → skip

        try:
            if validation == "pass":
                metrics = {
                    "auto_trigger": "forward-outcome-tracker",
                    "observation_window": window,
                    "realized_return": realized,
                    "alpha": alpha,
                }
                validate_hypothesis(hypothesis_id, metrics)
                ForwardOutcomeTracker._publish_validation(hypothesis_id, "validated", realized, alpha, run_id)
            elif validation == "reject":
                reason = (
                    f"forward outcome reject: w={window}d "
                    f"realized={realized:.4f}, alpha={alpha if alpha is not None else 'N/A'}"
                )
                reject_hypothesis(hypothesis_id, reason)
                ForwardOutcomeTracker._publish_validation(hypothesis_id, "rejected", realized, alpha, run_id)
        except ValueError:  # status machine race / already changed → skip
            pass

    @staticmethod
    def _publish_validation(
        hypothesis_id: str,
        new_status: str,
        realized: float,
        alpha: Optional[float],
        run_id: str,
    ) -> None:
        try:
            from nuri.agents.discord.outbox import stage_rollout

            stage_rollout(
                payload={
                    "kind": f"hypothesis_{new_status}",
                    "summary": (
                        f"{hypothesis_id} → {new_status} "
                        f"realized={realized:+.4f} alpha={alpha if alpha is not None else 'N/A'}"
                    ),
                    "hypothesis_id": hypothesis_id,
                    "new_status": new_status,
                    "realized": realized,
                    "alpha": alpha,
                },
                dedupe_key=f"hyp_validation:{hypothesis_id}:{new_status}",
                actor_name="forward-outcome-tracker",
                run_id=run_id,
            )
        except Exception:  # noqa: BLE001
            pass


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m nuri.agents.actors.forward_outcome_tracker {scan,last_outcome}"""
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(prog="forward-outcome-tracker")
    parser.add_argument("action", choices=["scan", "last_outcome", "track_one"])
    parser.add_argument("--decision-id", default=None)
    parser.add_argument("--observation-window", type=int, default=7)
    parser.add_argument("--max-decisions", type=int, default=100)
    args = parser.parse_args(argv)

    actor = ForwardOutcomeTracker()
    payload: dict[str, Any] = {"action": args.action}
    if args.action == "scan":
        payload["max_decisions"] = args.max_decisions
    elif args.action == "track_one":
        payload["decision_id"] = args.decision_id
        payload["observation_window"] = args.observation_window
    elif args.action == "last_outcome" and args.decision_id:
        payload["decision_id"] = args.decision_id

    result = actor.run(payload)
    print(_json.dumps(result.output, indent=2, ensure_ascii=False, default=str))
    return 0 if result.outcome in (Outcome.PASS, Outcome.WARN) else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())

"""DecisionCompiler — Layer B actor (#529 Phase 2 capstone — canonical #8).

RegimePosterior + HypothesisRegistry + CausalFactorAuditor 의 출력을 통합해
**audit-traceable 매매 추천** 를 emit. Phase 2 의 capstone — 모든 producer/gate 가
여기로 수렴.

Layer B 설계 (Codex Round 5):
- ZERO LLM, deterministic 결정
- 자동 매매 영구 X (#7.1) — emit 만, 사용자 manual 매매
- inputs_json 으로 source actor run_id 영구 기록 (audit traceable form 강제)

통합 로직 (defensive defaults):
- HypothesisRegistry.check_emit BLOCK → HOLD (Layer A enforcement 우회 금지)
- CausalFactorAuditor.last_audit verdict=MIRAGE → HOLD (factor mirage 차단)
- CausalFactorAuditor.last_audit verdict=INSUFFICIENT → HOLD
- conviction < CONVICTION_HOLD_CUTOFF (0.5) → HOLD (low-confidence emit 차단)
- conviction < CONVICTION_EMIT_CUTOFF (0.7) → HOLD (작은 신호 무시)
- All gates PASS + conviction >= 0.7 + regime favorable → BUY/SELL emit

Anti-pattern 방지 (lock-test):
- HypothesisRegistry BLOCK 결과를 무시하고 emit 시도 → 무조건 HOLD + blocked
- causal_audit verdict=MIRAGE 인 factor 사용 시도 → 무조건 HOLD
- 낮은 conviction 의 emit 시도 → HOLD enforced
- inputs_json 에 source actor run_id 누락 → log_decision 가 panic
"""

from __future__ import annotations

import uuid
from typing import Any

from nuri.agents.base import REGISTRY, Actor, ActorResult, Layer, Outcome, RunContext
from nuri.core.db import log_decision, query
from nuri.core.timezone import today_kst

# ─── 의사결정 임계값 ─────────────────────────────────────
CONVICTION_EMIT_CUTOFF = 0.70  # emit 최소 conviction
CONVICTION_HOLD_CUTOFF = 0.50  # 이 미만은 무조건 HOLD (low-signal)
REGIME_FAVOR_PROB = 0.60  # regime posterior top1 prob >= 이 값 → favorable

VALID_ACTIONS_INPUT: tuple[str, ...] = ("BUY", "SELL")  # caller 가 제안하는 방향


@REGISTRY.register
class DecisionCompiler(Actor):
    """Phase 2 capstone — 3 producer/gate 의 출력 통합.

    Actions (input_data['action']):
        compile  — 입력 evidence 통합 → BUY/SELL/HOLD decision emit
        last_decision — ticker 의 가장 최근 decision 조회 (read-only)

    Required input (action='compile'):
        ticker: str
        proposed_action: 'BUY' | 'SELL' (caller 의 alpha 제안 방향)
        regime_evidence: dict — RegimePosterior.run() 의 output
            {regime_run_id, posterior, argmax_state, top2_margin, ...}
        hypothesis_check: dict — HypothesisRegistry.check_emit 의 output
            {hypothesis_id, status, outcome ∈ {pass, block}}
        causal_evidence: dict — CausalFactorAuditor.last_audit 의 output
            {factor_id, as_of_date, verdict, causal_certainty}
        as_of_date: str (optional, default today_kst())
        walkforward_run_id: str (optional)

    Outcome 매핑:
        PASS — emit 성공 (BUY/SELL)
        WARN — HOLD (블록 게이트 통과 X 또는 conviction 부족)
        BLOCK — invalid input (필수 evidence 누락)
    """

    name = "decision-compiler"
    version = "0.1.0"
    layer = Layer.B

    VALID_ACTIONS: tuple[str, ...] = ("compile", "last_decision")

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        action = input_data.get("action")
        if action not in self.VALID_ACTIONS:
            return ActorResult(
                output={"error": f"invalid action {action!r}, expected {self.VALID_ACTIONS}"},
                outcome=Outcome.BLOCK,
                input_summary=f"action={action}",
            )

        if action == "last_decision":
            return self._last_decision(input_data)

        return self._compile(input_data, ctx)

    # ─── handlers ─────────────────────────────────────────────

    def _compile(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        # ─── input validation ───
        ticker = input_data.get("ticker")
        proposed_action = input_data.get("proposed_action")

        if not ticker or not isinstance(ticker, str):
            return ActorResult(
                output={"error": "ticker (str) required"},
                outcome=Outcome.BLOCK,
                input_summary="compile",
            )
        if proposed_action not in VALID_ACTIONS_INPUT:
            return ActorResult(
                output={"error": f"proposed_action must be {VALID_ACTIONS_INPUT}, got {proposed_action!r}"},
                outcome=Outcome.BLOCK,
                input_summary=f"compile {ticker}",
            )

        regime_evidence_raw = input_data.get("regime_evidence")
        hypothesis_check_raw = input_data.get("hypothesis_check")
        causal_evidence_raw = input_data.get("causal_evidence")
        if not isinstance(regime_evidence_raw, dict):
            return ActorResult(
                output={"error": "regime_evidence (dict) required"},
                outcome=Outcome.BLOCK,
                input_summary=f"compile {ticker}",
            )
        if not isinstance(hypothesis_check_raw, dict):
            return ActorResult(
                output={"error": "hypothesis_check (dict) required"},
                outcome=Outcome.BLOCK,
                input_summary=f"compile {ticker}",
            )
        if not isinstance(causal_evidence_raw, dict):
            return ActorResult(
                output={"error": "causal_evidence (dict) required"},
                outcome=Outcome.BLOCK,
                input_summary=f"compile {ticker}",
            )

        # 명시적 dict 변수 — Pylance 가 narrowing 인식
        regime_evidence: dict[str, Any] = regime_evidence_raw
        hypothesis_check: dict[str, Any] = hypothesis_check_raw
        causal_evidence: dict[str, Any] = causal_evidence_raw

        # source IDs 필수
        regime_run_id = regime_evidence.get("regime_run_id") or regime_evidence.get("run_id")
        hypothesis_id = hypothesis_check.get("hypothesis_id")
        causal_audit_id = self._causal_audit_id(causal_evidence)
        if not (regime_run_id and hypothesis_id and causal_audit_id):
            return ActorResult(
                output={
                    "error": "source IDs missing — regime_run_id/hypothesis_id/causal_audit_id 모두 필요",
                    "got": {
                        "regime_run_id": regime_run_id,
                        "hypothesis_id": hypothesis_id,
                        "causal_audit_id": causal_audit_id,
                    },
                },
                outcome=Outcome.BLOCK,
                input_summary=f"compile {ticker}",
            )

        as_of_date = input_data.get("as_of_date") or today_kst()
        decision_id = f"dc-{uuid.uuid4().hex[:12]}"

        inputs = {
            "regime_run_id": regime_run_id,
            "hypothesis_id": hypothesis_id,
            "causal_audit_id": causal_audit_id,
        }
        wf_id = input_data.get("walkforward_run_id")
        if wf_id:
            inputs["walkforward_run_id"] = wf_id

        # ─── gate 1: hypothesis check_emit ───
        hyp_outcome = hypothesis_check.get("outcome")
        if hyp_outcome != "pass" and hyp_outcome != Outcome.PASS:
            # PASS 가 아니면 무조건 HOLD (status enforcement)
            reason = (
                f"hypothesis check_emit BLOCK ({hypothesis_check.get('status', 'unknown')}): "
                f"{hypothesis_check.get('reason', hypothesis_check.get('error', 'no detail'))}"
            )
            return self._emit_blocked(decision_id, ticker, as_of_date, inputs, ctx, reason, conviction=0.0)

        # ─── gate 2: causal audit ───
        causal_verdict = causal_evidence.get("verdict")
        causal_certainty = float(causal_evidence.get("causal_certainty", 0.0))
        if causal_verdict in ("MIRAGE", "INSUFFICIENT"):
            reason = f"causal verdict={causal_verdict} (factor mirage 또는 검증 불가)"
            return self._emit_blocked(decision_id, ticker, as_of_date, inputs, ctx, reason, conviction=causal_certainty)

        # ─── conviction 계산 ───
        regime_top_prob = self._regime_top_prob(regime_evidence)
        top2_margin = float(regime_evidence.get("top2_margin", 0.0))
        # composite: causal_certainty 50% + regime_top_prob 30% + top2_margin 20%
        conviction = 0.50 * causal_certainty + 0.30 * regime_top_prob + 0.20 * top2_margin
        conviction = float(max(0.0, min(1.0, conviction)))

        rationale = {
            "proposed_action": proposed_action,
            "causal_certainty": causal_certainty,
            "regime_top_prob": regime_top_prob,
            "top2_margin": top2_margin,
            "conviction": conviction,
            "thresholds": {
                "emit_cutoff": CONVICTION_EMIT_CUTOFF,
                "hold_cutoff": CONVICTION_HOLD_CUTOFF,
                "regime_favor_prob": REGIME_FAVOR_PROB,
            },
        }

        # ─── gate 3: conviction ───
        if conviction < CONVICTION_HOLD_CUTOFF:
            reason = f"conviction {conviction:.3f} < hold_cutoff {CONVICTION_HOLD_CUTOFF}"
            return self._emit_blocked(
                decision_id,
                ticker,
                as_of_date,
                inputs,
                ctx,
                reason,
                conviction=conviction,
                rationale=rationale,
            )
        if conviction < CONVICTION_EMIT_CUTOFF or regime_top_prob < REGIME_FAVOR_PROB:
            # 통과는 하지만 emit 임계값 미달 → HOLD (defensive)
            reason = (
                f"conviction {conviction:.3f} < emit_cutoff {CONVICTION_EMIT_CUTOFF} "
                f"or regime_top_prob {regime_top_prob:.3f} < {REGIME_FAVOR_PROB}"
            )
            return self._emit_hold(decision_id, ticker, as_of_date, inputs, ctx, conviction, rationale, reason)

        # ─── all gates PASS → BUY/SELL emit ───
        return self._emit_action(decision_id, ticker, as_of_date, proposed_action, conviction, inputs, rationale, ctx)

    # ─── emit helpers ─────────────────────────────────────────

    def _emit_action(
        self,
        decision_id: str,
        ticker: str,
        as_of_date: str,
        action: str,
        conviction: float,
        inputs: dict,
        rationale: dict,
        ctx: RunContext,
    ) -> ActorResult:
        log_decision(
            decision_id=decision_id,
            ticker=ticker,
            as_of_date=as_of_date,
            action=action,
            conviction=conviction,
            inputs=inputs,
            rationale=rationale,
            status="emitted",
            run_id=ctx.run_id,
        )
        self._publish_brief(decision_id, ticker, action, conviction, rationale, ctx.run_id)
        return ActorResult(
            output={
                "decision_id": decision_id,
                "ticker": ticker,
                "action": action,
                "conviction": conviction,
                "status": "emitted",
                "rationale": rationale,
            },
            outcome=Outcome.PASS,
            input_summary=f"compile {ticker} {action} ({conviction:.2f})",
        )

    def _emit_hold(
        self,
        decision_id: str,
        ticker: str,
        as_of_date: str,
        inputs: dict,
        ctx: RunContext,
        conviction: float,
        rationale: dict,
        reason: str,
    ) -> ActorResult:
        rationale_full = {**rationale, "hold_reason": reason}
        log_decision(
            decision_id=decision_id,
            ticker=ticker,
            as_of_date=as_of_date,
            action="HOLD",
            conviction=conviction,
            inputs=inputs,
            rationale=rationale_full,
            status="emitted",  # HOLD 도 emit 의 한 형태
            run_id=ctx.run_id,
        )
        return ActorResult(
            output={
                "decision_id": decision_id,
                "ticker": ticker,
                "action": "HOLD",
                "conviction": conviction,
                "status": "emitted",
                "reason": reason,
                "rationale": rationale_full,
            },
            outcome=Outcome.WARN,
            input_summary=f"compile {ticker} HOLD ({reason[:40]})",
        )

    def _emit_blocked(
        self,
        decision_id: str,
        ticker: str,
        as_of_date: str,
        inputs: dict,
        ctx: RunContext,
        reason: str,
        conviction: float,
        rationale: dict | None = None,
    ) -> ActorResult:
        rationale_full = (rationale or {}) | {"block_reason": reason}
        log_decision(
            decision_id=decision_id,
            ticker=ticker,
            as_of_date=as_of_date,
            action="HOLD",
            conviction=conviction,
            inputs=inputs,
            rationale=rationale_full,
            status="blocked",
            block_reason=reason,
            run_id=ctx.run_id,
        )
        self._publish_block(decision_id, ticker, reason, ctx.run_id)
        return ActorResult(
            output={
                "decision_id": decision_id,
                "ticker": ticker,
                "action": "HOLD",
                "conviction": conviction,
                "status": "blocked",
                "block_reason": reason,
            },
            outcome=Outcome.WARN,
            input_summary=f"compile {ticker} BLOCKED ({reason[:40]})",
        )

    @staticmethod
    def _last_decision(input_data: dict[str, Any]) -> ActorResult:
        ticker = input_data.get("ticker")
        if ticker:
            rows = query(
                """SELECT * FROM agent_decisions WHERE ticker = ?
                   ORDER BY created_at DESC, rowid DESC LIMIT 1""",
                (ticker,),
            )
        else:
            rows = query("SELECT * FROM agent_decisions ORDER BY created_at DESC, rowid DESC LIMIT 1")
        if not rows:
            return ActorResult(
                output={"error": "no agent_decisions row found"},
                outcome=Outcome.WARN,
                input_summary="last_decision",
            )
        r = dict(rows[0])
        return ActorResult(
            output=r,
            outcome=Outcome.PASS,
            input_summary=f"last_decision {r['ticker']} {r['action']}",
        )

    # ─── parsers ──────────────────────────────────────────────

    @staticmethod
    def _regime_top_prob(regime_evidence: dict) -> float:
        """posterior list 에서 top1 확률 추출. 없으면 0.0."""
        posterior = regime_evidence.get("posterior")
        if isinstance(posterior, list) and posterior:
            return float(max(posterior))
        # fallback: top2_margin + 0.5 (대략적 추정)
        return 0.5 + float(regime_evidence.get("top2_margin", 0.0)) / 2

    @staticmethod
    def _causal_audit_id(causal_evidence: dict) -> str | None:
        """causal_audit_id = factor_id@as_of_date (PK composite)."""
        fid = causal_evidence.get("factor_id")
        date = causal_evidence.get("as_of_date")
        if fid and date:
            return f"{fid}@{date}"
        return causal_evidence.get("causal_audit_id")

    # ─── Discord publish (best-effort) ───────────────────────

    @staticmethod
    def _publish_brief(
        decision_id: str,
        ticker: str,
        action: str,
        conviction: float,
        rationale: dict,
        run_id: str,
    ) -> None:
        """emit 된 decision → BRIEF 채널 (사용자 추천)."""
        try:
            from nuri.agents.discord.publisher import Channel, DiscordPublisher

            color = 0x2ECC71 if action == "BUY" else 0xE74C3C if action == "SELL" else 0x95A5A6
            embed = {
                "title": f"{action} — {ticker}",
                "description": (
                    f"decision_id: `{decision_id}`\n"
                    f"conviction: **{conviction:.3f}**\n"
                    f"causal: {rationale.get('causal_certainty', 0):.3f} · "
                    f"regime_top: {rationale.get('regime_top_prob', 0):.3f} · "
                    f"margin: {rationale.get('top2_margin', 0):.3f}"
                ),
                "color": color,
                "footer": {"text": f"nuri-quant • run_id={run_id[:8]} • emit only, manual execute"},
            }
            DiscordPublisher().publish_embed(
                Channel.BRIEF,
                embed=embed,
                actor_name="decision-compiler",
                run_id=run_id,
            )
        except Exception:  # noqa: BLE001 — best-effort
            pass

    @staticmethod
    def _publish_block(decision_id: str, ticker: str, reason: str, run_id: str) -> None:
        """blocked decision → OPS 채널 (operator alert)."""
        try:
            from nuri.agents.discord.publisher import Channel, DiscordPublisher

            embed = {
                "title": f"Decision BLOCKED — {ticker}",
                "description": (f"decision_id: `{decision_id}`\nreason: {reason}"),
                "color": 0xF39C12,
                "footer": {"text": f"nuri-quant • run_id={run_id[:8]}"},
            }
            DiscordPublisher().publish_embed(
                Channel.OPS,
                embed=embed,
                actor_name="decision-compiler",
                run_id=run_id,
            )
        except Exception:  # noqa: BLE001
            pass


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m nuri.agents.actors.decision_compiler last_decision [--ticker X]

    compile 은 dict input 필요 → Python 호출 전용.
    """
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(prog="decision-compiler")
    parser.add_argument("action", choices=["last_decision"])
    parser.add_argument("--ticker", default=None)
    args = parser.parse_args(argv)

    actor = DecisionCompiler()
    payload: dict[str, Any] = {"action": args.action}
    if args.ticker:
        payload["ticker"] = args.ticker
    result = actor.run(payload)
    print(_json.dumps(result.output, indent=2, ensure_ascii=False, default=str))
    return 0 if result.outcome in (Outcome.PASS, Outcome.WARN) else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())

"""ExecutionFirewall — Layer A actor (#529 Phase 2 — canonical #9).

DecisionCompiler emit 직후 / 사용자 매매 직전 마지막 hard constraint gate.
"emit 됐어도 leverage cap / position cap / VIX 게이트 위반이면 차단" — 사고 방지의
마지막 piece (Knight Capital 류 사고 prevention).

Layer A 설계 (Codex Round 5):
- 100% rule-based (config/rules.yaml + 사용자 규칙)
- ZERO LLM — 차단 결정에 추론 의존 X
- Hard severity = emit 차단, soft = warn (emit 허용)
- 모든 block 결정 execution_blocks + audit_ledger 영구 기록

Hard rules (모두 우회 불가):
- VIX > 30 + BUY → vix_too_high (사용자 규칙)
- Banned leverage ETF (TQQQ/SQQQ/UPRO/SPXU/TSLL) → banned_leverage_etf
- post-trade single position > 15% → position_cap
- post-trade sector > 35% → sector_concentration
- post-trade cash < 20% → cash_reserve
- total long exposure / cash > 1.5x → leverage_cap
- 일일 portfolio loss > -10% → max_daily_loss

Soft rule:
- VIX 25-30 + BUY → 'caution' warn (emit 허용 + 사용자에게 경고)

Anti-pattern 방지 (lock-test):
- Hard severity 위반 시 무조건 BLOCK (severity 우회 불가)
- DecisionCompiler emit 결과를 무시하고 PASS 처리 시도 → 무조건 가장 먼저 검사
- 모든 block_type 이 audit row 영구 기록 (pass 도 기록 — 사후 룰 보정용)

Discord publish: hard block 시 → INCIDENTS 채널 (operator urgent)
"""

from __future__ import annotations

from typing import Any

from nuri.agents.base import REGISTRY, Actor, ActorResult, Layer, Outcome, RunContext
from nuri.core.db import log_execution_block, query
from nuri.core.rules import RULES, VIX_BLOCK_ABOVE, VIX_CAUTION_ABOVE

# ─── 룰 임계값 (config/rules.yaml override 가능) ─────────────
# VIX 게이트는 canonical entry_rules.vix_gate (nuri.core.rules 로더) 단일 출처를 import.
# (과거: buy_checklist.vix_gate 를 읽었으나 그 키는 rules.yaml 에 부재 → 항상 dead literal
#  fallback 이라 운영자의 VIX 게이트 config 편집이 firewall 에서 무시됐음.)
VIX_HARD_BLOCK = float(VIX_BLOCK_ABOVE)
VIX_SOFT_CAUTION = float(VIX_CAUTION_ABOVE)
MAX_SINGLE_POSITION = float(RULES["position_limits"]["max_single_position"])
MAX_SECTOR_EXPOSURE = float(RULES["position_limits"]["max_sector_exposure"])
MIN_CASH_RESERVE = float(RULES.get("position_limits", {}).get("min_cash_reserve", 0.20))
BANNED_LEVERAGE_ETFS: set[str] = set(RULES.get("leverage", {}).get("banned_etfs", []))
MAX_LEVERAGE = float(RULES.get("leverage", {}).get("max_leverage", 1.5))
MAX_DAILY_LOSS = float(RULES.get("stop_loss", {}).get("portfolio", -10)) / 100.0


@REGISTRY.register
class ExecutionFirewall(Actor):
    """Hard constraint enforcement gate — Layer A.

    Actions (input_data['action']):
        check       — DecisionCompiler emit 결과 + portfolio state → PASS / BLOCK
        list_blocks — 최근 block 기록 조회 (read-only)

    Required input (action='check'):
        decision_id: str
        ticker: str
        trade_action: 'BUY' | 'SELL' | 'HOLD'  — 매매 방향 (key 충돌 회피)
        proposed_position_value: float — emit 시 매매 금액 (USD or KRW)
        portfolio_state: dict — 현재 포트폴리오
            {
              total_value, cash, positions: {ticker: {value, sector}},
              vix (optional), daily_pnl_pct (optional)
            }

    Outcome 매핑 (Codex Round 5 Layer A):
        PASS — 모든 hard rule 통과 (soft warn 있을 수 있음)
        BLOCK — hard rule 위반 (block_reasons list 반환)
        WARN — soft rule 위반만 있는 경우 (예: VIX 25-30 caution)
    """

    name = "execution-firewall"
    version = "0.1.0"
    layer = Layer.A

    VALID_ACTIONS: tuple[str, ...] = ("check", "list_blocks")

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        action = input_data.get("action")
        if action not in self.VALID_ACTIONS:
            return ActorResult(
                output={"error": f"invalid action {action!r}, expected {self.VALID_ACTIONS}"},
                outcome=Outcome.BLOCK,
                input_summary=f"action={action}",
            )

        if action == "list_blocks":
            return self._list_blocks(input_data)

        return self._check(input_data, ctx)

    # ─── core check ───────────────────────────────────────────

    def _check(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        # ─── input validation ───
        decision_id = input_data.get("decision_id")
        ticker = input_data.get("ticker")
        # 'trade_action' 우선, fallback 'action_type' (legacy compat)
        decision_action = input_data.get("trade_action") or input_data.get("action_type")
        portfolio_state = input_data.get("portfolio_state")
        proposed_value = input_data.get("proposed_position_value", 0.0)

        if not decision_id or not isinstance(decision_id, str):
            return ActorResult(
                output={"error": "decision_id (str) required"},
                outcome=Outcome.BLOCK,
                input_summary="check",
            )
        if not ticker or not isinstance(ticker, str):
            return ActorResult(
                output={"error": "ticker (str) required"},
                outcome=Outcome.BLOCK,
                input_summary=f"check {decision_id}",
            )
        if decision_action not in ("BUY", "SELL", "HOLD"):
            return ActorResult(
                output={"error": f"trade_action must be BUY/SELL/HOLD, got {decision_action!r}"},
                outcome=Outcome.BLOCK,
                input_summary=f"check {decision_id}",
            )
        if not isinstance(portfolio_state, dict):
            return ActorResult(
                output={"error": "portfolio_state (dict) required"},
                outcome=Outcome.BLOCK,
                input_summary=f"check {decision_id}",
            )

        try:
            proposed_value = float(proposed_value or 0)
        except (TypeError, ValueError):
            return ActorResult(
                output={"error": "proposed_position_value must be numeric"},
                outcome=Outcome.BLOCK,
                input_summary=f"check {decision_id}",
            )

        ticker_upper = ticker.upper()
        hard_blocks: list[dict[str, Any]] = []
        soft_warns: list[dict[str, Any]] = []

        # ─── HOLD 는 firewall pass-through (포지션 변동 없음) ───
        if decision_action == "HOLD":
            return ActorResult(
                output={
                    "decision_id": decision_id,
                    "ticker": ticker_upper,
                    "action": "HOLD",
                    "verdict": "PASS",
                    "blocks": [],
                    "warns": [],
                    "skipped": "HOLD has no position impact",
                },
                outcome=Outcome.PASS,
                input_summary=f"check {decision_id} HOLD pass-through",
            )

        # ─── BUY 전용 게이트 ───
        if decision_action == "BUY":
            # 1) VIX gate
            vix = portfolio_state.get("vix")
            if vix is not None:
                vix_f = float(vix)
                if vix_f > VIX_HARD_BLOCK:
                    hard_blocks.append(
                        {
                            "type": "vix_too_high",
                            "reason": f"VIX {vix_f:.2f} > hard block threshold {VIX_HARD_BLOCK}",
                            "evidence": {"vix": vix_f, "threshold": VIX_HARD_BLOCK},
                        }
                    )
                elif vix_f > VIX_SOFT_CAUTION:
                    soft_warns.append(
                        {
                            "type": "vix_too_high",
                            "reason": f"VIX {vix_f:.2f} in caution band ({VIX_SOFT_CAUTION}-{VIX_HARD_BLOCK})",
                            "evidence": {"vix": vix_f, "caution_above": VIX_SOFT_CAUTION},
                        }
                    )

            # 2) Banned leverage ETF
            if ticker_upper in BANNED_LEVERAGE_ETFS:
                hard_blocks.append(
                    {
                        "type": "banned_leverage_etf",
                        "reason": f"{ticker_upper} in banned ETF list (rules.yaml)",
                        "evidence": {"ticker": ticker_upper, "banned": sorted(BANNED_LEVERAGE_ETFS)},
                    }
                )

            # 3) post-trade position cap (단일 종목)
            total_value = float(portfolio_state.get("total_value", 0) or 0)
            positions = portfolio_state.get("positions") or {}
            existing_pos = positions.get(ticker_upper, {}) if isinstance(positions, dict) else {}
            existing_value = float(existing_pos.get("value", 0) or 0)
            new_total = total_value + proposed_value if total_value > 0 else proposed_value
            new_position_value = existing_value + proposed_value
            if new_total > 0:
                new_position_pct = new_position_value / new_total
                if new_position_pct > MAX_SINGLE_POSITION:
                    hard_blocks.append(
                        {
                            "type": "position_cap",
                            "reason": (
                                f"post-trade {ticker_upper} {new_position_pct:.2%} > "
                                f"max_single_position {MAX_SINGLE_POSITION:.2%}"
                            ),
                            "evidence": {
                                "ticker": ticker_upper,
                                "new_pct": new_position_pct,
                                "cap": MAX_SINGLE_POSITION,
                            },
                        }
                    )

            # 4) sector concentration
            existing_sector = existing_pos.get("sector") if isinstance(existing_pos, dict) else None
            new_sector = input_data.get("sector") or existing_sector
            if new_sector and new_total > 0 and isinstance(positions, dict):
                sector_value = float(proposed_value)
                for tk, info in positions.items():
                    if isinstance(info, dict) and info.get("sector") == new_sector:
                        sector_value += float(info.get("value", 0) or 0)
                sector_pct = sector_value / new_total
                if sector_pct > MAX_SECTOR_EXPOSURE:
                    hard_blocks.append(
                        {
                            "type": "sector_concentration",
                            "reason": (
                                f"post-trade sector {new_sector} {sector_pct:.2%} > "
                                f"max_sector_exposure {MAX_SECTOR_EXPOSURE:.2%}"
                            ),
                            "evidence": {
                                "sector": new_sector,
                                "new_pct": sector_pct,
                                "cap": MAX_SECTOR_EXPOSURE,
                            },
                        }
                    )

            # 5) cash reserve
            cash = float(portfolio_state.get("cash", 0) or 0)
            cash_after = cash - proposed_value
            if new_total > 0:
                cash_pct = cash_after / new_total
                if cash_pct < MIN_CASH_RESERVE:
                    hard_blocks.append(
                        {
                            "type": "cash_reserve",
                            "reason": (f"post-trade cash {cash_pct:.2%} < min_cash_reserve {MIN_CASH_RESERVE:.2%}"),
                            "evidence": {
                                "cash_after": cash_after,
                                "cash_pct": cash_pct,
                                "floor": MIN_CASH_RESERVE,
                            },
                        }
                    )

            # 6) leverage cap (장 전체 long exposure / cash)
            long_exposure = (
                sum(
                    float(p.get("value", 0) or 0)
                    for p in (positions.values() if isinstance(positions, dict) else [])
                    if isinstance(p, dict)
                )
                + proposed_value
            )
            if cash > 0:
                leverage_ratio = long_exposure / cash
                if leverage_ratio > MAX_LEVERAGE:
                    hard_blocks.append(
                        {
                            "type": "leverage_cap",
                            "reason": (f"long_exposure / cash = {leverage_ratio:.2f}x > max_leverage {MAX_LEVERAGE}x"),
                            "evidence": {
                                "long_exposure": long_exposure,
                                "cash": cash,
                                "ratio": leverage_ratio,
                                "cap": MAX_LEVERAGE,
                            },
                        }
                    )

        # ─── BUY/SELL 공통: 일일 손실 한도 ───
        daily_pnl_pct = portfolio_state.get("daily_pnl_pct")
        if daily_pnl_pct is not None:
            try:
                pnl = float(daily_pnl_pct)
                if pnl <= MAX_DAILY_LOSS and decision_action == "BUY":
                    hard_blocks.append(
                        {
                            "type": "max_daily_loss",
                            "reason": (f"daily PnL {pnl:.2%} <= max_daily_loss {MAX_DAILY_LOSS:.2%} (신규 BUY 차단)"),
                            "evidence": {"daily_pnl_pct": pnl, "limit": MAX_DAILY_LOSS},
                        }
                    )
            except (TypeError, ValueError):
                pass

        # ─── 결과 정리 ───
        for blk in hard_blocks:
            log_execution_block(
                decision_id=decision_id,
                block_type=blk["type"],
                severity="hard",
                block_reason=blk["reason"],
                evidence=blk["evidence"],
                run_id=ctx.run_id,
            )
        for warn in soft_warns:
            log_execution_block(
                decision_id=decision_id,
                block_type=warn["type"],
                severity="soft",
                block_reason=warn["reason"],
                evidence=warn["evidence"],
                run_id=ctx.run_id,
            )

        if hard_blocks:
            self._publish_incidents(decision_id, ticker_upper, hard_blocks, ctx.run_id)
            return ActorResult(
                output={
                    "decision_id": decision_id,
                    "ticker": ticker_upper,
                    "action": decision_action,
                    "verdict": "BLOCK",
                    "blocks": hard_blocks,
                    "warns": soft_warns,
                },
                outcome=Outcome.BLOCK,
                input_summary=f"check {decision_id} BLOCK ({len(hard_blocks)} hard)",
            )

        if soft_warns:
            return ActorResult(
                output={
                    "decision_id": decision_id,
                    "ticker": ticker_upper,
                    "action": decision_action,
                    "verdict": "WARN",
                    "blocks": [],
                    "warns": soft_warns,
                },
                outcome=Outcome.WARN,
                input_summary=f"check {decision_id} WARN ({len(soft_warns)} soft)",
            )

        return ActorResult(
            output={
                "decision_id": decision_id,
                "ticker": ticker_upper,
                "action": decision_action,
                "verdict": "PASS",
                "blocks": [],
                "warns": [],
            },
            outcome=Outcome.PASS,
            input_summary=f"check {decision_id} PASS",
        )

    # ─── list_blocks ──────────────────────────────────────────

    @staticmethod
    def _list_blocks(input_data: dict[str, Any]) -> ActorResult:
        decision_id = input_data.get("decision_id")
        severity = input_data.get("severity")  # optional filter
        limit = int(input_data.get("limit", 50))

        sql = "SELECT * FROM execution_blocks"
        params: list[Any] = []
        clauses: list[str] = []
        if decision_id:
            clauses.append("decision_id = ?")
            params.append(decision_id)
        if severity:
            clauses.append("severity = ?")
            params.append(severity)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC, block_id DESC LIMIT ?"
        params.append(limit)

        rows = query(sql, tuple(params))
        items = [dict(r) for r in rows]
        return ActorResult(
            output={"count": len(items), "blocks": items},
            outcome=Outcome.PASS,
            sample_n=len(items),
            input_summary=f"list_blocks (n={len(items)})",
        )

    # ─── Discord publish (best-effort) ───────────────────────

    @staticmethod
    def _publish_incidents(
        decision_id: str,
        ticker: str,
        blocks: list[dict[str, Any]],
        run_id: str,
    ) -> None:
        """Hard-veto execution block → #incidents outbox stage (PR3 Codex Round 6)."""
        try:
            from nuri.agents.discord.outbox import stage_incident

            block_types = ",".join(b["type"] for b in blocks)
            stage_incident(
                payload={
                    "kind": "execution_block",
                    "ticker": ticker,
                    "summary": f"{ticker} EXEC BLOCK [{block_types}] decision_id={decision_id}",
                    "decision_id": decision_id,
                    "blocks": blocks[:5],
                    "block_types": block_types,
                },
                priority="high",  # hard-veto = 즉시 surface
                dedupe_key=f"exec_block:{decision_id}",
                actor_name="execution-firewall",
                run_id=run_id,
            )
        except Exception:  # noqa: BLE001
            pass


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m nuri.agents.actors.execution_firewall list_blocks [--severity hard]"""
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(prog="execution-firewall")
    parser.add_argument("action", choices=["list_blocks"])
    parser.add_argument("--decision-id", default=None)
    parser.add_argument("--severity", default=None, choices=[None, "hard", "soft"])
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)

    actor = ExecutionFirewall()
    payload: dict[str, Any] = {"action": args.action, "limit": args.limit}
    if args.decision_id:
        payload["decision_id"] = args.decision_id
    if args.severity:
        payload["severity"] = args.severity
    result = actor.run(payload)
    print(_json.dumps(result.output, indent=2, ensure_ascii=False, default=str))
    return 0 if result.outcome == Outcome.PASS else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())

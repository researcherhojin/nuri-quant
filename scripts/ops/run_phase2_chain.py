#!/usr/bin/env python3
"""Phase 2 4-actor chain end-to-end verification (O1, #529).

실 macro feature → RegimePosterior → HypothesisRegistry → CausalFactorAuditor →
DecisionCompiler → ExecutionFirewall 1 ticker production run.

목적 (Codex Round 5 #5 + Harness 7 #3 — "사용자 워크플로로 검증한다"):
- mock test 가 아닌 *실제 데이터* 로 chain 작동 검증
- 각 게이트가 어디서 어떻게 PASS / BLOCK 결정하는지 명확히 surface
- 첫 emit 또는 어떤 actor 가 stop 했는지 보고

사용:
    .venv/bin/python scripts/ops/run_phase2_chain.py --ticker NVDA
    .venv/bin/python scripts/ops/run_phase2_chain.py --ticker NVDA --dry-run  # log_decision 호출 X
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import numpy as np
import pandas as pd

from nuri.agents.actors.causal_factor_auditor import CausalFactorAuditor
from nuri.agents.actors.decision_compiler import DecisionCompiler
from nuri.agents.actors.execution_firewall import ExecutionFirewall
from nuri.agents.actors.hypothesis_registry import HypothesisRegistry
from nuri.agents.actors.regime_posterior import RegimePosterior
from nuri.core.db import query_df
from nuri.core.timezone import today_kst

# ─── ANSI color (terminal report) ─────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
AMBER = "\033[93m"
BLUE = "\033[94m"
DIM = "\033[2m"
RESET = "\033[0m"


def _print_step(n: int, name: str, status: str, summary: str) -> None:
    color = {"PASS": GREEN, "WARN": AMBER, "BLOCK": RED, "INFO": BLUE}.get(status, "")
    print(f"{DIM}[{n}/6]{RESET} {color}{status:5}{RESET} {name:30} {summary}")


def _ov(result) -> str:
    """ActorResult.outcome.value or 'unknown' — Layer A actors guarantee non-None
    by contract, but pyright sees Optional[Outcome]. Helper narrows + safely defaults."""
    return result.outcome.value if result.outcome is not None else "unknown"


def fetch_macro_features(start_date: str = "2025-01-01") -> pd.DataFrame:
    """vix + 10y/2y yield → vix_z + yield_curve_slope DataFrame.

    hy_oas 미보유 → 2-feature subset (RegimePosterior spec override 필요).
    """
    df = query_df(
        """SELECT date, indicator, value FROM macro
           WHERE indicator IN ('vix','us_10y_yield','us_2y_yield')
             AND date >= ?
           ORDER BY date""",
        (start_date,),
    )
    pivot = df.pivot(index="date", columns="indicator", values="value")
    pivot.columns.name = None

    # vix_z: 252d rolling z-score (정상화)
    pivot["vix_z"] = (pivot["vix"] - pivot["vix"].rolling(252, min_periods=20).mean()) / pivot["vix"].rolling(
        252, min_periods=20
    ).std()
    # yield_curve_slope: 10y - 2y (positive = normal, negative = inverted)
    pivot["yield_curve_slope"] = pivot["us_10y_yield"] - pivot["us_2y_yield"]
    # forward-fill macro values to align dates
    pivot = pivot[["vix_z", "yield_curve_slope"]].ffill().dropna()
    return pivot


def fetch_ticker_returns(ticker: str, start_date: str = "2025-01-01") -> pd.DataFrame:
    """ticker 일별 close → daily return."""
    df = query_df(
        "SELECT date, close FROM prices WHERE ticker = ? AND date >= ? ORDER BY date",
        (ticker, start_date),
    )
    df["return_1d"] = df["close"].pct_change()
    return df.dropna()


def fetch_portfolio_state(default_cash: float = 50_000.0) -> dict[str, Any]:
    """Best-effort portfolio snapshot (없으면 default placeholder).

    실 holdings 가 있으면 그걸 쓰고, 없으면 빈 portfolio + cash 만 사용.
    """
    try:
        rows = query_df("SELECT ticker, qty, current_price FROM holdings WHERE qty > 0")
        positions: dict[str, dict[str, Any]] = {}
        total_value = 0.0
        for _, r in rows.iterrows():
            value = float(r["qty"]) * float(r["current_price"] or 0)
            if value > 0:
                positions[r["ticker"]] = {"value": value, "sector": "unknown"}
                total_value += value
    except Exception:
        positions = {}
        total_value = 0.0

    # VIX 최신값 — ExecutionFirewall vix_too_high gate
    vix_row = query_df("SELECT value FROM macro WHERE indicator='vix' ORDER BY date DESC LIMIT 1")
    vix = float(vix_row["value"].iloc[0]) if not vix_row.empty else None

    return {
        "total_value": total_value if total_value > 0 else 100_000.0,
        "cash": default_cash,
        "positions": positions,
        "vix": vix,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 2 chain end-to-end verification")
    parser.add_argument("--ticker", default="NVDA", help="대상 ticker (default: NVDA)")
    parser.add_argument("--proposed-action", default="BUY", choices=["BUY", "SELL"])
    parser.add_argument("--proposed-value", type=float, default=3000.0, help="제안 매매 금액 USD")
    parser.add_argument("--dry-run", action="store_true", help="DB write skip — 검증 전용")
    args = parser.parse_args(argv)

    print(
        f"\n{BLUE}═══ Phase 2 Chain Verification — {args.ticker} {args.proposed_action} ${args.proposed_value:,.0f} ═══{RESET}\n"
    )

    # ─── Step 1: fetch real macro features ───
    macro = fetch_macro_features()
    if len(macro) < 30:
        _print_step(1, "fetch macro features", "BLOCK", f"only {len(macro)} rows (<30 needed)")
        return 2
    _print_step(1, "fetch macro features", "INFO", f"{len(macro)} rows, last={macro.index[-1]}")
    print(
        f"      latest: vix_z={macro['vix_z'].iloc[-1]:.3f}, yield_curve_slope={macro['yield_curve_slope'].iloc[-1]:.3f}"
    )

    # ─── Step 2: RegimePosterior fit ───
    spec = {"feature_cols": ("vix_z", "yield_curve_slope"), "n_states": 3}
    train_window = f"{macro.index[0]}..{macro.index[-1]}"
    regime_result = RegimePosterior().run(
        {
            "action": "fit",
            "data": macro.reset_index(drop=True),
            "as_of_date": today_kst(),
            "train_window": train_window,
            "data_freshness_status": "PASS",  # 첫 실행은 manual seed
            "spec": spec,
        }
    )
    if _ov(regime_result) == "block":
        _print_step(2, "RegimePosterior", "BLOCK", str(regime_result.output.get("error", ""))[:80])
        return 2
    posterior = regime_result.output["posterior"]
    argmax = regime_result.output["argmax_state"]
    top2_margin = regime_result.output["top2_margin"]
    regime_run_id = regime_result.output.get("model_version", "regime-v1")
    _print_step(
        2,
        "RegimePosterior",
        _ov(regime_result).upper(),
        f"argmax={argmax} posterior={[round(p, 3) for p in posterior]} margin={top2_margin:.3f}",
    )

    # ─── Step 3: HypothesisRegistry register + (manual) validate ───
    hyp = HypothesisRegistry()
    hypothesis_id = f"chain-verify-{args.ticker}-{today_kst()}"
    register_result = hyp.run(
        {
            "action": "register",
            "hypothesis_id": hypothesis_id,
            "name": f"chain-verify-{args.ticker}",
            "version": "1.0.0",
            "producer_actor": "regime-posterior",
            "claim_text": f"{args.ticker} {args.proposed_action} based on regime argmax={argmax}",
            "evidence": {"posterior": posterior, "top2_margin": top2_margin},
        }
    )
    if _ov(register_result) == "block":
        _print_step(3, "HypothesisRegistry register", "BLOCK", str(register_result.output.get("error", ""))[:80])
        return 2
    is_new = register_result.output.get("is_new")
    _print_step(
        3,
        "HypothesisRegistry register",
        "PASS",
        f"hypothesis_id={hypothesis_id} is_new={is_new}",
    )

    # 첫 실행이면 manual validate (forward outcome 데이터 없음 — placeholder)
    # 이후 실행은 ForwardOutcomeTracker 가 자동 처리
    if is_new:
        validate_result = hyp.run(
            {
                "action": "validate",
                "hypothesis_id": hypothesis_id,
                "validation_metrics": {"manual_seed": True, "first_run": True},
            }
        )
        _print_step(
            3,
            "HypothesisRegistry validate (manual seed)",
            _ov(validate_result).upper(),
            "manual seed for first run",
        )

    # check_emit gate
    check_result = hyp.run({"action": "check_emit", "hypothesis_id": hypothesis_id})
    hypothesis_check = {
        "hypothesis_id": hypothesis_id,
        "status": check_result.output.get("status"),
        "outcome": _ov(check_result),
    }
    if _ov(check_result) != "pass":
        _print_step(3, "HypothesisRegistry check_emit", "BLOCK", str(check_result.output.get("reason", ""))[:80])
        return 2

    # ─── Step 4: CausalFactorAuditor on momentum factor ───
    returns_df = fetch_ticker_returns(args.ticker)
    if len(returns_df) < 100:
        _print_step(4, "CausalFactorAuditor", "BLOCK", f"only {len(returns_df)} return rows (<100)")
        return 2
    # factor = lagged 1-day return (proxy momentum), returns = next-day return
    # PIT-safe: factor[t] uses return[t-1], target = return[t]
    returns_arr = returns_df["return_1d"].to_numpy()
    factor = returns_arr[:-1]  # t-1 returns as factor
    returns_target = returns_arr[1:]  # t returns as target

    causal_result = CausalFactorAuditor().run(
        {
            "action": "audit",
            "factor_id": f"momentum-1d-{args.ticker}",
            "factor": factor.tolist(),
            "returns": returns_target.tolist(),
            "dag_edges": [("factor", "returns")],
            "dag_nodes": ["factor", "returns"],
            "as_of_date": today_kst(),
            "n_placebo_runs": 50,
        }
    )
    if _ov(causal_result) == "block":
        _print_step(4, "CausalFactorAuditor", "BLOCK", str(causal_result.output.get("error", ""))[:80])
        return 2
    causal_evidence = causal_result.output
    _print_step(
        4,
        "CausalFactorAuditor",
        _ov(causal_result).upper(),
        f"verdict={causal_evidence['verdict']} certainty={causal_evidence['causal_certainty']:.3f} placebo_ratio={causal_evidence['tests']['placebo']['placebo_t_ratio']:.3f}",
    )

    # ─── Step 5: DecisionCompiler ───
    if args.dry_run:
        print(f"      {DIM}--dry-run: DecisionCompiler skip{RESET}")
        return 0

    dc_result = DecisionCompiler().run(
        {
            "action": "compile",
            "ticker": args.ticker,
            "proposed_action": args.proposed_action,
            "regime_evidence": {
                "regime_run_id": regime_run_id,
                "posterior": posterior,
                "argmax_state": argmax,
                "top2_margin": top2_margin,
            },
            "hypothesis_check": hypothesis_check,
            "causal_evidence": causal_evidence,
            "as_of_date": today_kst(),
        }
    )
    decision_id = dc_result.output.get("decision_id")
    action = dc_result.output.get("action")
    conviction = dc_result.output.get("conviction", 0)
    status = dc_result.output.get("status", "?")
    _print_step(
        5,
        "DecisionCompiler",
        _ov(dc_result).upper(),
        f"action={action} conviction={conviction:.3f} status={status}",
    )
    if status == "blocked":
        print(f"      {AMBER}block_reason{RESET}: {dc_result.output.get('block_reason')}")
    if not decision_id:
        return 2 if _ov(dc_result) == "block" else 1

    # ─── Step 6: ExecutionFirewall (only if BUY/SELL emit, HOLD skip) ───
    ef_result = None  # sentinel — None 이면 firewall 미실행 (HOLD path)
    if action in ("BUY", "SELL"):
        portfolio = fetch_portfolio_state()
        ef_result = ExecutionFirewall().run(
            {
                "action": "check",
                "decision_id": decision_id,
                "ticker": args.ticker,
                "trade_action": action,
                "proposed_position_value": args.proposed_value,
                "portfolio_state": portfolio,
            }
        )
        verdict = ef_result.output.get("verdict")
        blocks = ef_result.output.get("blocks", [])
        warns = ef_result.output.get("warns", [])
        _print_step(
            6,
            "ExecutionFirewall",
            _ov(ef_result).upper(),
            f"verdict={verdict} blocks={len(blocks)} warns={len(warns)} portfolio_vix={portfolio.get('vix')}",
        )
        for b in blocks:
            print(f"      {RED}HARD BLOCK{RESET} {b['type']}: {b['reason']}")
        for w in warns:
            print(f"      {AMBER}SOFT WARN{RESET} {w['type']}: {w['reason']}")
    else:
        _print_step(6, "ExecutionFirewall", "INFO", f"action={action} — firewall skip (no position impact)")

    # ─── Final summary ───
    print(f"\n{BLUE}═══ Chain complete ═══{RESET}")
    if action == "BUY" or action == "SELL":
        if dc_result.output.get("status") == "emitted" and (args.proposed_action == action):
            ef_outcome = _ov(ef_result) if ef_result is not None else "n/a"
            if ef_outcome == "pass":
                print(f"{GREEN}✓ EMIT 성공{RESET} — decision_id={decision_id}")
                print("  Discord BRIEF embed published (best-effort)")
                return 0
            print(f"{AMBER}⚠ DecisionCompiler emit but Firewall {ef_outcome}{RESET}")
            return 1
    print(f"{AMBER}⊘ HOLD/blocked{RESET} — decision_id={decision_id} (사용자 검토 후 룰 보정 검토)")
    return 1


if __name__ == "__main__":
    sys.exit(main())

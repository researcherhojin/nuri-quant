"""Strategic Asset Allocation drift advisor (STRATEGY §3.10, Phase 2).

현재 portfolio 의 asset_class 비중 vs `config/rules.yaml strategic_allocation_targets`
비교 → drift 계산 + REBALANCE 권고 emit.

**axis 분리 룰 준수** (STRATEGY §3.7, PR #429): 본 module 은 portfolio_action=REBALANCE
만 emit. alpha_action=FLAT 절대 X — 자산 배분 drift 는 종목 매도 트리거가 아님.

근거: STRATEGY §3.10 — Brinson-HBB (1986/Ibbotson-Kaplan 2000 보정), Vanguard 2024,
Ilmanen 2022. discipline (정기 rebalance) 가 alpha 보다 큼 (DALBAR/Morningstar 2024).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from nuri.core.db import query
from nuri.core.rules import RULES
from nuri.trading.engine.certification import _classify_asset_class

# severity: |drift| >= emergency 면 즉시, >= threshold 면 정기 rebalance 권고.
_DEFAULT_DRIFT_THRESHOLD_PCT = 5.0
_DEFAULT_DRIFT_EMERGENCY_PCT = 10.0


def compute_current_allocation(db_path: Optional[Path] = None) -> dict[str, float]:
    """Portfolio 의 현재 asset_class 별 비중 (%) 반환.

    holdings value = quantity × avg_price (현재가 unavailable 시 진입가 proxy — STRATEGY
    §3.10 의 strategic 비중은 진입 cost basis 기준으로 충분히 robust).

    Returns: {asset_class: pct} (합 ≈ 100, 빈 portfolio 면 {}).
    """
    rows = query(
        "SELECT ticker, sector, quantity, avg_price FROM portfolio WHERE ticker != ''",
        db_path=db_path,
    )
    if not rows:
        return {}

    rules_cfg = RULES.get("siege_gates", {}).get("asset_class_rules", [])
    if not rules_cfg:
        return {}

    by_class: dict[str, float] = {}
    total_value = 0.0
    for row in rows:
        try:
            value = float(row["quantity"]) * float(row["avg_price"])
        except (TypeError, ValueError):
            continue  # 비숫자 row skip
        if value <= 0:
            continue
        ac = _classify_asset_class(row["ticker"], row["sector"] or "", rules_cfg)
        by_class[ac] = by_class.get(ac, 0.0) + value
        total_value += value

    if total_value <= 0:
        return {}
    return {k: round(v / total_value * 100, 2) for k, v in by_class.items()}


def compute_drift(account_strategy: str, db_path: Optional[Path] = None) -> dict[str, Any]:
    """Account strategy 별 SAA target 대비 drift 계산.

    Returns dict 구조:
        strategy        — account_strategy 이름
        targets         — config/rules.yaml strategic_allocation_targets[strategy]
        current         — 현재 asset_class 비중
        drift           — {asset_class: current - target} (음수=under, 양수=over)
        violations      — [{asset_class, drift, severity}] (severity: warning|emergency)
        action          — "REBALANCE" 또는 "OK"
        cadence         — config rebalance_policy.cadence (default 'quarterly')

    cash_min 은 별도 처리 — drift 계산에 포함 X (현금은 잔여 buffer, equity/bond 비중과
    별도 axis).
    """
    targets = RULES.get("strategic_allocation_targets", {}).get(account_strategy)
    if not targets:
        return {
            "strategy": account_strategy,
            "error": f"no SAA targets defined for '{account_strategy}' (config/rules.yaml)",
            "action": "OK",
            "violations": [],
        }

    policy = RULES.get("rebalance_policy", {})
    threshold = float(policy.get("drift_threshold_pct", _DEFAULT_DRIFT_THRESHOLD_PCT))
    emergency = float(policy.get("drift_emergency_pct", _DEFAULT_DRIFT_EMERGENCY_PCT))
    cadence = policy.get("cadence", "quarterly")

    current = compute_current_allocation(db_path=db_path)
    drift: dict[str, float] = {}
    violations: list[dict[str, Any]] = []

    for ac, target_pct in targets.items():
        if ac == "cash_min":
            continue
        cur_pct = current.get(ac, 0.0)
        d = round(cur_pct - float(target_pct), 2)
        drift[ac] = d
        if abs(d) >= emergency:
            violations.append({"asset_class": ac, "drift": d, "severity": "emergency"})
        elif abs(d) >= threshold:
            violations.append({"asset_class": ac, "drift": d, "severity": "warning"})

    return {
        "strategy": account_strategy,
        "targets": dict(targets),
        "current": current,
        "drift": drift,
        "violations": violations,
        "action": "REBALANCE" if violations else "OK",
        "cadence": cadence,
        "behavior_gap_warning": policy.get("behavior_gap_warning", True),
    }


def format_report(result: dict[str, Any]) -> str:
    """Human-readable 1-screen report — CLI 출력용."""
    if "error" in result:
        return f"❌ SAA drift skip: {result['error']}"

    lines = [
        f"## Strategic Allocation Drift — {result['strategy']} ({result['cadence']} rebalance)",
        "",
        "| asset_class | target | current | drift | severity |",
        "|---|---|---|---|---|",
    ]
    severities = {v["asset_class"]: v["severity"] for v in result["violations"]}
    for ac, target_pct in result["targets"].items():
        if ac == "cash_min":
            continue
        cur = result["current"].get(ac, 0.0)
        d = result["drift"].get(ac, 0.0)
        sev = severities.get(ac, "—")
        lines.append(f"| {ac} | {target_pct}% | {cur}% | {d:+.2f}% | {sev} |")

    action = result["action"]
    icon = "🔴" if action == "REBALANCE" else "✅"
    lines += ["", f"{icon} **action: {action}**"]

    if action == "REBALANCE":
        lines += [
            "",
            "권고: 위반 asset_class 의 비중을 target 으로 회귀시키도록 매수/매도 (portfolio_action=REBALANCE).",
            "**alpha_action=FLAT 절대 X** — 종목 매도 트리거 아님 (STRATEGY §3.7).",
        ]
        if result.get("behavior_gap_warning"):
            lines.append("⚠ behavior gap 주의: 시장 timing 시도 X (DALBAR/Morningstar 2024 — 격차 ~1-3%/yr).")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m nuri.trading.strategy.strategic_allocation --strategy <name>"""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--strategy",
        default="core",
        choices=["core", "active", "swing", "long_term", "pension"],
        help="account_strategy 이름 (config/rules.yaml strategic_allocation_targets key)",
    )
    args = parser.parse_args(argv)

    result = compute_drift(args.strategy)
    print(format_report(result))
    return 0 if result.get("action") == "OK" else 1


if __name__ == "__main__":  # pragma: no cover  # invariant: 표준 entry idiom — main() 이 testable
    import sys

    sys.exit(main())

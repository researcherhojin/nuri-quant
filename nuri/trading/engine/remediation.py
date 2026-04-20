"""
SIEGE Remediation Engine — REJECTED 인증서를 행동 가능한 리밸런싱 계획으로 변환.

certify() 결과의 실패 gate와 rebalance_advisor의 매도 액션을 매핑하고,
액션 실행 후 gate 재통과 가능 여부를 시뮬레이션한다.

사용법:
    python -m nuri.trading.engine.remediation
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# SIEGE gate → rebalance 위반 유형 매핑
# 매매로 해결 가능한 gate만 포함. 나머지(vix_gate, data_fresh 등)는 unresolvable.
_GATE_TO_VIOLATION: dict[str, list[str]] = {
    "position_limit": ["position_limit_exceeded"],
    "sector_limit": ["sector_limit_exceeded"],
    "stop_loss": ["stop_loss_exceeded"],
    "leverage_ban": ["leverage_etf"],
}

# 매매로 해결할 수 없는 gate (정보성 표시만)
_UNRESOLVABLE_GATES: set[str] = {
    "vix_gate", "data_fresh", "external_data", "conflict_free",
    "drift_safe", "rules_loaded",
}


@dataclass
class RemediationAction:
    """단일 remediation 액션."""
    gate_id: str
    ticker: str
    action: str          # "SELL_ALL" | "REDUCE"
    sell_shares: int
    sell_value_usd: float
    reason: str
    severity: str        # "critical" | "high" | "medium"


@dataclass
class RemediationPlan:
    """SIEGE remediation 계획."""
    certified: bool
    score: float
    failed_gates: list[str]
    warning_gates: list[str]
    actions: list[RemediationAction]
    unresolvable: list[dict]     # gate_id + detail (매매로 해결 불가)
    post_remediation_score: float
    post_remediation_pass: bool  # 액션 실행 후 error gate 통과 예측


def generate_remediation(db_path: Optional[Path] = None) -> RemediationPlan:
    """certify() + rebalance_advisor를 결합하여 remediation 계획 생성."""
    from nuri.analysis.rebalance_advisor import generate_advisor_report
    from nuri.trading.engine.certification import certify

    cert = certify(db_path=db_path, caller="remediation")
    report = generate_advisor_report(db_path=db_path)

    # 실패/경고 gate 분류
    failed_gates = [c.id for c in cert.conditions if not c.passed and c.severity == "error"]
    warning_gates = [c.id for c in cert.conditions if not c.passed and c.severity == "warning"]

    # 이미 CERTIFIED면 액션 없음
    if cert.certified:
        return RemediationPlan(
            certified=True,
            score=cert.score,
            failed_gates=[],
            warning_gates=warning_gates,
            actions=[],
            unresolvable=[],
            post_remediation_score=cert.score,
            post_remediation_pass=True,
        )

    # 실패 gate에 매핑되는 advisor action 추출
    actions: list[RemediationAction] = []
    resolvable_gate_ids: set[str] = set()

    for gate_id in failed_gates:
        violation_types = _GATE_TO_VIOLATION.get(gate_id, [])
        if not violation_types:
            continue

        resolvable_gate_ids.add(gate_id)

        for advisor_action in report["actions"]:
            if advisor_action["violation_type"] in violation_types:
                actions.append(RemediationAction(
                    gate_id=gate_id,
                    ticker=advisor_action["ticker"],
                    action=advisor_action["action"],
                    sell_shares=advisor_action["sell_shares"],
                    sell_value_usd=advisor_action["sell_value_usd"],
                    reason=advisor_action["reason"],
                    severity=advisor_action["severity"],
                ))

    # 해결 불가능한 gate (failed error 중 매핑 없는 것)
    unresolvable: list[dict] = []
    for c in cert.conditions:
        if not c.passed and c.id not in resolvable_gate_ids:
            if c.id in _UNRESOLVABLE_GATES:
                unresolvable.append({"gate_id": c.id, "detail": c.detail, "severity": c.severity})

    # post-remediation 시뮬레이션
    # resolvable error gate를 모두 해결한다고 가정
    unresolved_error_count = len(failed_gates) - len(resolvable_gate_ids)
    post_pass = unresolved_error_count == 0

    # 점수 시뮬: resolvable error gate가 pass로 변하면 passed += len(resolvable)
    total = cert.total_conditions
    simulated_passed = cert.passed + len(resolvable_gate_ids)
    simulated_passed = min(simulated_passed, total)
    post_score = round(simulated_passed / total * 100, 1) if total > 0 else 0.0

    return RemediationPlan(
        certified=cert.certified,
        score=cert.score,
        failed_gates=failed_gates,
        warning_gates=warning_gates,
        actions=actions,
        unresolvable=unresolvable,
        post_remediation_score=post_score,
        post_remediation_pass=post_pass,
    )


def print_remediation(plan: RemediationPlan) -> None:
    """Remediation 계획 CLI 출력."""
    print(f"\n{'═' * 60}")
    status = "CERTIFIED" if plan.certified else "REJECTED"
    print(f"  SIEGE Remediation — {status} ({plan.score:.0f}%)")
    print(f"{'═' * 60}")

    if plan.certified:
        print("  ✅ 모든 필수 조건 통과. Remediation 불필요.")
        if plan.warning_gates:
            print(f"  ⚠ 경고: {', '.join(plan.warning_gates)}")
        print()
        return

    # 진단
    print("\n  ── 진단 ──")
    print(f"  ❌ 실패 gate: {', '.join(plan.failed_gates)}")
    if plan.warning_gates:
        print(f"  ⚠ 경고 gate: {', '.join(plan.warning_gates)}")

    # 처방
    if plan.actions:
        print(f"\n  ── 처방 ({len(plan.actions)}건) ──")
        for idx, a in enumerate(plan.actions, 1):
            severity_marker = ""
            if a.severity == "critical":
                severity_marker = "[!!] "
            elif a.severity == "high":
                severity_marker = "[!] "

            qty_text = f"{a.sell_shares}주 전량" if a.action == "SELL_ALL" else f"{a.sell_shares}주 일부"
            print(f"  {severity_marker}[{idx}] SELL {a.ticker} {qty_text} → {a.reason} (회수 ~${a.sell_value_usd:,.0f})")
            print(f"       gate: {a.gate_id}")
    else:
        print("\n  처방 없음 — 매매로 해결 가능한 위반 없음")

    # 해결 불가
    if plan.unresolvable:
        print(f"\n  ── 해결 불가 ({len(plan.unresolvable)}건) ──")
        for u in plan.unresolvable:
            print(f"  ℹ {u['gate_id']}: {u['detail']}")

    # 예상 post-remediation
    print("\n  ── 예상 결과 ──")
    post_status = "PASS" if plan.post_remediation_pass else "FAIL"
    print(f"  처방 실행 후: {post_status} ({plan.post_remediation_score:.0f}%)")
    if not plan.post_remediation_pass:
        print("  ⚠ 매매 불가능 error gate 잔존 — 수동 조치 필요")

    total_recovery = sum(a.sell_value_usd for a in plan.actions)
    if total_recovery > 0:
        print(f"  총 회수: ~${total_recovery:,.0f}")

    print(f"{'═' * 60}\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    plan = generate_remediation()
    print_remediation(plan)

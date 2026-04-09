"""Tests for nuri.trading.engine.remediation."""
from dataclasses import dataclass
from unittest.mock import patch

from nuri.trading.engine.remediation import (
    _GATE_TO_VIOLATION,
    _UNRESOLVABLE_GATES,
    RemediationAction,
    RemediationPlan,
    generate_remediation,
    print_remediation,
)

# ── Dataclass tests ──────────────────────────────────────────

class TestRemediationAction:
    def test_create(self):
        a = RemediationAction(
            gate_id="position_limit",
            ticker="AAPL",
            action="REDUCE",
            sell_shares=5,
            sell_value_usd=800.0,
            reason="비중 20.0% > 한도 15%",
            severity="medium",
        )
        assert a.gate_id == "position_limit"
        assert a.action == "REDUCE"
        assert a.sell_value_usd == 800.0


class TestRemediationPlan:
    def test_certified_plan(self):
        plan = RemediationPlan(
            certified=True, score=100.0,
            failed_gates=[], warning_gates=[],
            actions=[], unresolvable=[],
            post_remediation_score=100.0, post_remediation_pass=True,
        )
        assert plan.certified is True
        assert plan.actions == []

    def test_rejected_plan(self):
        plan = RemediationPlan(
            certified=False, score=70.0,
            failed_gates=["position_limit"], warning_gates=["vix_gate"],
            actions=[RemediationAction("position_limit", "AAPL", "REDUCE", 5, 800.0, "test", "medium")],
            unresolvable=[],
            post_remediation_score=80.0, post_remediation_pass=True,
        )
        assert not plan.certified
        assert len(plan.actions) == 1
        assert plan.post_remediation_pass is True


# ── Constants tests ──────────────────────────────────────────

class TestConstants:
    def test_gate_to_violation_keys(self):
        """Resolvable gates map to known violation types."""
        assert "position_limit" in _GATE_TO_VIOLATION
        assert "sector_limit" in _GATE_TO_VIOLATION
        assert "stop_loss" in _GATE_TO_VIOLATION
        assert "leverage_ban" in _GATE_TO_VIOLATION

    def test_unresolvable_gates(self):
        """Unresolvable gates are correct set."""
        assert "vix_gate" in _UNRESOLVABLE_GATES
        assert "data_fresh" in _UNRESOLVABLE_GATES
        assert "position_limit" not in _UNRESOLVABLE_GATES


# ── generate_remediation tests ───────────────────────────────

@dataclass
class _MockCondition:
    id: str
    passed: bool
    severity: str = "error"
    detail: str = ""
    description: str = ""


@dataclass
class _MockCertificate:
    certified: bool
    score: float
    total_conditions: int
    passed: int
    failed: int
    warnings: int
    conditions: list
    timestamp: str = "2026-04-09"


class TestGenerateRemediation:
    def test_certified_returns_empty_plan(self, db_path):
        """CERTIFIED → no actions."""
        cert = _MockCertificate(
            certified=True, score=100.0, total_conditions=10,
            passed=10, failed=0, warnings=0,
            conditions=[_MockCondition(f"c{i}", True) for i in range(10)],
        )
        with patch("nuri.trading.engine.certification.certify", return_value=cert), \
             patch("nuri.analysis.rebalance_advisor.generate_advisor_report", return_value={"actions": []}):
            plan = generate_remediation(db_path=db_path)

        assert plan.certified is True
        assert plan.actions == []
        assert plan.post_remediation_pass is True

    def test_rejected_with_resolvable_actions(self, db_path):
        """REJECTED with position_limit → maps advisor actions to remediation."""
        conditions = [
            _MockCondition("position_limit", False, "error", "위반: AAPL(20.0%)"),
            *[_MockCondition(f"c{i}", True) for i in range(9)],
        ]
        cert = _MockCertificate(
            certified=False, score=90.0, total_conditions=10,
            passed=9, failed=1, warnings=0, conditions=conditions,
        )
        advisor_report = {
            "actions": [
                {
                    "ticker": "AAPL",
                    "violation_type": "position_limit_exceeded",
                    "action": "REDUCE",
                    "sell_shares": 5,
                    "sell_value_usd": 800.0,
                    "reason": "비중 20.0% > 한도 15%",
                    "severity": "medium",
                },
            ],
            "total_violations": 1,
            "total_recovery_usd": 800.0,
            "violations_by_type": {"position_limit_exceeded": 1},
            "violations_by_severity": {"medium": 1},
            "has_critical": False,
        }

        with patch("nuri.trading.engine.certification.certify", return_value=cert), \
             patch("nuri.analysis.rebalance_advisor.generate_advisor_report", return_value=advisor_report):
            plan = generate_remediation(db_path=db_path)

        assert not plan.certified
        assert len(plan.actions) == 1
        assert plan.actions[0].gate_id == "position_limit"
        assert plan.actions[0].ticker == "AAPL"
        assert plan.post_remediation_pass is True
        assert plan.post_remediation_score == 100.0

    def test_rejected_with_unresolvable_gate(self, db_path):
        """REJECTED + unresolvable warning gates."""
        conditions = [
            _MockCondition("position_limit", False, "error", "위반"),
            _MockCondition("vix_gate", False, "warning", "VIX 35.0"),
            *[_MockCondition(f"c{i}", True) for i in range(8)],
        ]
        cert = _MockCertificate(
            certified=False, score=80.0, total_conditions=10,
            passed=8, failed=1, warnings=1, conditions=conditions,
        )
        advisor_report = {
            "actions": [{
                "ticker": "AAPL", "violation_type": "position_limit_exceeded",
                "action": "REDUCE", "sell_shares": 3, "sell_value_usd": 500.0,
                "reason": "비중 초과", "severity": "medium",
            }],
            "total_violations": 1, "total_recovery_usd": 500.0,
            "violations_by_type": {}, "violations_by_severity": {}, "has_critical": False,
        }

        with patch("nuri.trading.engine.certification.certify", return_value=cert), \
             patch("nuri.analysis.rebalance_advisor.generate_advisor_report", return_value=advisor_report):
            plan = generate_remediation(db_path=db_path)

        assert len(plan.unresolvable) == 1
        assert plan.unresolvable[0]["gate_id"] == "vix_gate"
        assert plan.post_remediation_pass is True  # error gate는 해결 가능

    def test_no_advisor_actions_for_failed_gate(self, db_path):
        """REJECTED but advisor has no matching actions → empty actions, fail predicted."""
        conditions = [
            _MockCondition("position_limit", False, "error", "위반"),
            *[_MockCondition(f"c{i}", True) for i in range(9)],
        ]
        cert = _MockCertificate(
            certified=False, score=90.0, total_conditions=10,
            passed=9, failed=1, warnings=0, conditions=conditions,
        )
        advisor_report = {
            "actions": [], "total_violations": 0, "total_recovery_usd": 0.0,
            "violations_by_type": {}, "violations_by_severity": {}, "has_critical": False,
        }

        with patch("nuri.trading.engine.certification.certify", return_value=cert), \
             patch("nuri.analysis.rebalance_advisor.generate_advisor_report", return_value=advisor_report):
            plan = generate_remediation(db_path=db_path)

        assert plan.actions == []
        # gate is resolvable type but no actions found → still counted as resolvable
        assert plan.post_remediation_pass is True

    def test_multiple_failed_gates(self, db_path):
        """Multiple error gates fail → maps each to correct violation type."""
        conditions = [
            _MockCondition("position_limit", False, "error", "위반"),
            _MockCondition("leverage_ban", False, "error", "TSLL 보유"),
            *[_MockCondition(f"c{i}", True) for i in range(8)],
        ]
        cert = _MockCertificate(
            certified=False, score=80.0, total_conditions=10,
            passed=8, failed=2, warnings=0, conditions=conditions,
        )
        advisor_report = {
            "actions": [
                {"ticker": "AAPL", "violation_type": "position_limit_exceeded",
                 "action": "REDUCE", "sell_shares": 3, "sell_value_usd": 500.0,
                 "reason": "비중 초과", "severity": "medium"},
                {"ticker": "TSLL", "violation_type": "leverage_etf",
                 "action": "SELL_ALL", "sell_shares": 100, "sell_value_usd": 1500.0,
                 "reason": "레버리지 ETF 금지", "severity": "critical"},
            ],
            "total_violations": 2, "total_recovery_usd": 2000.0,
            "violations_by_type": {}, "violations_by_severity": {}, "has_critical": True,
        }

        with patch("nuri.trading.engine.certification.certify", return_value=cert), \
             patch("nuri.analysis.rebalance_advisor.generate_advisor_report", return_value=advisor_report):
            plan = generate_remediation(db_path=db_path)

        assert len(plan.actions) == 2
        gate_ids = {a.gate_id for a in plan.actions}
        assert gate_ids == {"position_limit", "leverage_ban"}
        assert plan.post_remediation_pass is True
        assert plan.post_remediation_score == 100.0

    def test_stop_loss_gate_maps_to_stop_loss_exceeded(self, db_path):
        """stop_loss gate maps to stop_loss_exceeded violation."""
        conditions = [
            _MockCondition("stop_loss", False, "error", "위반 2건"),
            *[_MockCondition(f"c{i}", True) for i in range(9)],
        ]
        cert = _MockCertificate(
            certified=False, score=90.0, total_conditions=10,
            passed=9, failed=1, warnings=0, conditions=conditions,
        )
        advisor_report = {
            "actions": [
                {"ticker": "MSFT", "violation_type": "stop_loss_exceeded",
                 "action": "SELL_ALL", "sell_shares": 10, "sell_value_usd": 3000.0,
                 "reason": "손절 -15.0% 초과", "severity": "critical"},
            ],
            "total_violations": 1, "total_recovery_usd": 3000.0,
            "violations_by_type": {}, "violations_by_severity": {}, "has_critical": True,
        }

        with patch("nuri.trading.engine.certification.certify", return_value=cert), \
             patch("nuri.analysis.rebalance_advisor.generate_advisor_report", return_value=advisor_report):
            plan = generate_remediation(db_path=db_path)

        assert len(plan.actions) == 1
        assert plan.actions[0].gate_id == "stop_loss"
        assert plan.actions[0].action == "SELL_ALL"

    def test_certified_with_warnings(self, db_path):
        """CERTIFIED but warnings exist → still no actions."""
        conditions = [
            *[_MockCondition(f"c{i}", True) for i in range(8)],
            _MockCondition("vix_gate", False, "warning", "VIX 32.0"),
            _MockCondition("data_fresh", False, "warning", "80시간 전"),
        ]
        cert = _MockCertificate(
            certified=True, score=80.0, total_conditions=10,
            passed=8, failed=0, warnings=2, conditions=conditions,
        )

        with patch("nuri.trading.engine.certification.certify", return_value=cert), \
             patch("nuri.analysis.rebalance_advisor.generate_advisor_report", return_value={"actions": []}):
            plan = generate_remediation(db_path=db_path)

        assert plan.certified is True
        assert plan.actions == []
        assert plan.warning_gates == ["vix_gate", "data_fresh"]


# ── print_remediation tests ──────────────────────────────────

class TestPrintRemediation:
    def test_print_certified(self, capsys):
        plan = RemediationPlan(
            certified=True, score=100.0,
            failed_gates=[], warning_gates=[],
            actions=[], unresolvable=[],
            post_remediation_score=100.0, post_remediation_pass=True,
        )
        print_remediation(plan)
        output = capsys.readouterr().out
        assert "CERTIFIED" in output
        assert "불필요" in output

    def test_print_certified_with_warnings(self, capsys):
        plan = RemediationPlan(
            certified=True, score=80.0,
            failed_gates=[], warning_gates=["vix_gate"],
            actions=[], unresolvable=[],
            post_remediation_score=80.0, post_remediation_pass=True,
        )
        print_remediation(plan)
        output = capsys.readouterr().out
        assert "CERTIFIED" in output
        assert "vix_gate" in output

    def test_print_rejected_with_actions(self, capsys):
        plan = RemediationPlan(
            certified=False, score=70.0,
            failed_gates=["position_limit", "leverage_ban"],
            warning_gates=["vix_gate"],
            actions=[
                RemediationAction("leverage_ban", "TSLL", "SELL_ALL", 100, 1500.0, "레버리지 금지", "critical"),
                RemediationAction("position_limit", "AAPL", "REDUCE", 5, 800.0, "비중 초과", "medium"),
            ],
            unresolvable=[{"gate_id": "vix_gate", "detail": "VIX 35.0", "severity": "warning"}],
            post_remediation_score=90.0, post_remediation_pass=True,
        )
        print_remediation(plan)
        output = capsys.readouterr().out
        assert "REJECTED" in output
        assert "진단" in output
        assert "처방" in output
        assert "TSLL" in output
        assert "[!!]" in output  # critical marker
        assert "해결 불가" in output
        assert "vix_gate" in output
        assert "PASS" in output
        assert "$2,300" in output  # total recovery 1500 + 800

    def test_print_rejected_no_actions(self, capsys):
        plan = RemediationPlan(
            certified=False, score=80.0,
            failed_gates=["position_limit"],
            warning_gates=[],
            actions=[],
            unresolvable=[],
            post_remediation_score=90.0, post_remediation_pass=True,
        )
        print_remediation(plan)
        output = capsys.readouterr().out
        assert "REJECTED" in output
        assert "처방 없음" in output

    def test_print_rejected_post_fail(self, capsys):
        """Post-remediation still fails → warning message."""
        plan = RemediationPlan(
            certified=False, score=70.0,
            failed_gates=["position_limit"],
            warning_gates=[],
            actions=[],
            unresolvable=[],
            post_remediation_score=80.0, post_remediation_pass=False,
        )
        print_remediation(plan)
        output = capsys.readouterr().out
        assert "FAIL" in output
        assert "수동 조치" in output

    def test_print_high_severity_marker(self, capsys):
        plan = RemediationPlan(
            certified=False, score=80.0,
            failed_gates=["stop_loss"],
            warning_gates=[],
            actions=[
                RemediationAction("stop_loss", "MSFT", "SELL_ALL", 10, 3000.0, "손절 초과", "high"),
            ],
            unresolvable=[],
            post_remediation_score=90.0, post_remediation_pass=True,
        )
        print_remediation(plan)
        output = capsys.readouterr().out
        assert "[!]" in output
        assert "[!!]" not in output  # high, not critical

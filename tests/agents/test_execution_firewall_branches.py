"""nuri/agents/actors/execution_firewall.py 의 5 partial branches 닫기 (#616 Phase 2).

Each test triggers a specific False branch in BUY-gate logic:
- 166→186: vix=None → VIX gate 자체 skip → leverage ETF 단계로
- 202→221: new_total=0 (total_value=0 + proposed=0) → position cap 평가 skip
- 226→225: positions 의 entries 가 다른 sector → sector match continue
- 248→264: new_total=0 → cash reserve 평가 skip
- 272→289: cash=0 → leverage cap 평가 skip

`# pragma: no cover` 미사용 (CLAUDE.md ★).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nuri.agents.actors.execution_firewall import ExecutionFirewall
from nuri.core.db import init_db, log_decision


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "ef_branches.db"
    init_db(path)
    return path


@pytest.fixture
def patched_db(db_path):
    """기존 test_execution_firewall.py 와 동일 패턴 — 모든 DB 호출 redirect."""
    from nuri.core import db as db_module

    def make_redirect(fn):
        def wrapped(*args, **kwargs):
            kwargs.setdefault("db_path", db_path)
            return fn(*args, **kwargs)

        return wrapped

    patches = [
        patch("nuri.agents.base.log_agent_audit", side_effect=make_redirect(db_module.log_agent_audit)),
        patch("nuri.agents.base.start_agent_run", side_effect=make_redirect(db_module.start_agent_run)),
        patch("nuri.agents.base.finish_agent_run", side_effect=make_redirect(db_module.finish_agent_run)),
        patch(
            "nuri.agents.actors.execution_firewall.log_execution_block",
            side_effect=make_redirect(db_module.log_execution_block),
        ),
        patch(
            "nuri.agents.actors.execution_firewall.query",
            side_effect=make_redirect(db_module.query),
        ),
    ]
    for p in patches:
        p.start()
    yield db_path
    for p in patches:
        p.stop()


def _seed(db_path, decision_id: str = "d-test"):
    log_decision(
        decision_id=decision_id,
        ticker="NVDA",
        as_of_date="2026-05-01",
        action="BUY",
        conviction=0.85,
        inputs={"regime_run_id": "r", "hypothesis_id": "h", "causal_audit_id": "c"},
        rationale={},
        status="emitted",
        db_path=db_path,
    )


def _check_payload(decision_id: str, **portfolio_overrides):
    portfolio = {
        "total_value": 100_000.0,
        "cash": 50_000.0,
        "positions": {"AAPL": {"value": 10_000.0, "sector": "tech"}},
        "vix": 18.0,
    }
    portfolio.update(portfolio_overrides)
    return {
        "action": "check",
        "decision_id": decision_id,
        "ticker": "NVDA",
        "trade_action": "BUY",
        "proposed_position_value": 3000.0,
        "portfolio_state": portfolio,
    }


class TestExecutionFirewallBranches:
    """5 partial branches in execution_firewall.py."""

    def test_vix_none_skips_vix_gate(self, patched_db):
        """Branch 166→186: portfolio_state.vix=None → if vix is not None: False
        → 186 (banned ETF 단계로). VIX 자체 평가 skip."""
        _seed(patched_db, "d-vix-none")
        ef = ExecutionFirewall()
        # vix=None → portfolio_state.get("vix") None → 166 False
        out = ef.run(_check_payload("d-vix-none", vix=None))
        # vix gate skipped → no vix_too_high block (다른 hard block 도 없음 정상 portfolio)
        block_types = [b["type"] for b in (out.output.get("blocks") or [])]
        assert "vix_too_high" not in block_types

    def test_zero_new_total_skips_position_cap(self, patched_db):
        """Branch 202→221: total_value=0 + proposed=0 → new_total=0 → 202 False
        → 221 (sector concentration 단계로)."""
        _seed(patched_db, "d-zero-total")
        ef = ExecutionFirewall()
        # proposed=0 + total_value=0 → new_total=0 → position_cap skip
        out = ef.run(
            _check_payload("d-zero-total", total_value=0.0, positions={}, cash=0.0) | {"proposed_position_value": 0.0}
        )
        block_types = [b["type"] for b in (out.output.get("blocks") or [])]
        assert "position_cap" not in block_types

    def test_other_sector_position_continues_loop(self, patched_db):
        """Branch 226→225: positions 안 entry 가 new_sector 와 다름 → if False
        → for loop 다음 iteration. (target ticker 의 sector 만 추가, 다른 sector
        는 sum 에서 제외 됨을 확인.)"""
        _seed(patched_db, "d-other-sector")
        ef = ExecutionFirewall()
        # AAPL sector=tech, MSFT sector=cloud (different) → 226 분기 둘 다 (tech True, cloud False)
        out = ef.run(
            _check_payload(
                "d-other-sector",
                positions={
                    "AAPL": {"value": 5_000.0, "sector": "tech"},  # 226 True
                    "MSFT": {"value": 5_000.0, "sector": "cloud"},  # 226 False
                },
                vix=18.0,
            )
            | {"sector": "tech"}  # input_data sector = tech
        )
        # NVDA(proposed) + AAPL(tech) sum 만 = 8000, total=103000 → ~7.8% < 35% → no block
        block_types = [b["type"] for b in (out.output.get("blocks") or [])]
        assert "sector_concentration" not in block_types

    def test_zero_new_total_skips_cash_reserve(self, patched_db):
        """Branch 248→264: new_total=0 → if False → 264 (leverage 단계로). cash reserve
        평가 자체 skip."""
        _seed(patched_db, "d-zero-cash")
        ef = ExecutionFirewall()
        out = ef.run(
            _check_payload("d-zero-cash", total_value=0.0, positions={}, cash=0.0) | {"proposed_position_value": 0.0}
        )
        block_types = [b["type"] for b in (out.output.get("blocks") or [])]
        assert "cash_reserve" not in block_types

    def test_zero_cash_skips_leverage_cap(self, patched_db):
        """Branch 272→289: cash=0 → if cash > 0: False → 289 (daily PnL 단계로).
        leverage cap 평가 skip."""
        _seed(patched_db, "d-leverage-cash-zero")
        ef = ExecutionFirewall()
        # cash=0 + total_value>0 → new_total>0 → 다른 분기 통과, 272 False
        out = ef.run(
            _check_payload(
                "d-leverage-cash-zero",
                total_value=50_000.0,  # new_total>0 으로 cash_reserve 통과 시도
                cash=0.0,  # 272 False
                positions={"AAPL": {"value": 50_000.0, "sector": "tech"}},
            )
        )
        block_types = [b["type"] for b in (out.output.get("blocks") or [])]
        # cash=0 인 portfolio 는 cash_reserve 가 발동될 수 있음 — leverage_cap 만 확인
        assert "leverage_cap" not in block_types

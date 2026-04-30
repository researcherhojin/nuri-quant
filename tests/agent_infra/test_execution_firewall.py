"""ExecutionFirewall tests (#529 Phase 2 — actor #9, canonical Layer A).

검증 (Codex Round 5 Layer A):
- Layer A enforcement (outcome 필수, ZERO LLM)
- 2 actions: check / list_blocks
- Hard rules (모두 우회 불가):
    1. VIX > 30 + BUY → vix_too_high
    2. Banned leverage ETF (TQQQ/SQQQ/...) → banned_leverage_etf
    3. Post-trade single position > 15% → position_cap
    4. Post-trade sector > 35% → sector_concentration
    5. Post-trade cash < 20% → cash_reserve
    6. long_exposure / cash > 1.5x → leverage_cap
    7. daily PnL <= -10% + BUY → max_daily_loss
- Soft rule:
    - VIX 25-30 + BUY → caution warn (PASS + warn list)
- Anti-pattern lock-tests:
    1. Hard rule 우회 불가 — 어떤 input 으로도 BLOCK 결정 변경 X
    2. HOLD action → pass-through (포지션 영향 없음)
    3. SELL action → 대부분 게이트 skip
    4. 모든 block decision_id audit 영구 기록 (execution_blocks)
- Discord publish: hard block → INCIDENTS (mock)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nuri.agents.actors.execution_firewall import (
    BANNED_LEVERAGE_ETFS,
    MAX_LEVERAGE,
    MAX_SECTOR_EXPOSURE,
    MAX_SINGLE_POSITION,
    MIN_CASH_RESERVE,
    VIX_HARD_BLOCK,
    VIX_SOFT_CAUTION,
    ExecutionFirewall,
)
from nuri.agents.base import Layer, Outcome
from nuri.core.db import init_db, log_decision, log_execution_block, query

# ═══════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "ef.db"
    init_db(path)
    return path


@pytest.fixture
def patched_db(db_path):
    """모든 DB 호출 redirect."""
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


def _seed_decision(db_path, decision_id: str, ticker: str = "NVDA", action: str = "BUY"):
    log_decision(
        decision_id=decision_id,
        ticker=ticker,
        as_of_date="2026-05-01",
        action=action,
        conviction=0.85,
        inputs={"regime_run_id": "r", "hypothesis_id": "h", "causal_audit_id": "c"},
        rationale={},
        status="emitted",
        db_path=db_path,
    )


def _portfolio(**overrides):
    base = {
        "total_value": 100_000.0,
        "cash": 50_000.0,
        "positions": {"NVDA": {"value": 10_000.0, "sector": "tech"}},
        "vix": 18.0,
    }
    base.update(overrides)
    return base


def _check_payload(decision_id: str, ticker: str, **overrides):
    payload = {
        "action": "check",
        "decision_id": decision_id,
        "ticker": ticker,
        "trade_action": "BUY",
        "proposed_position_value": 3000.0,
        "portfolio_state": _portfolio(),
    }
    payload.update(overrides)
    return payload


# ═══════════════════════════════════════════════════════
# Layer A invariants
# ═══════════════════════════════════════════════════════


class TestActorRegistration:
    def test_layer_is_a(self):
        assert ExecutionFirewall.layer == Layer.A

    def test_no_llm_dependency(self):
        assert getattr(ExecutionFirewall, "_uses_llm", False) is False

    def test_registered_in_canonical_15(self):
        from nuri.agents.base import REGISTRY

        assert REGISTRY.get("execution-firewall") is ExecutionFirewall


# ═══════════════════════════════════════════════════════
# Input validation
# ═══════════════════════════════════════════════════════


class TestInputValidation:
    def test_invalid_action_blocked(self, patched_db):
        result = ExecutionFirewall().run({"action": "weird"})
        assert result.outcome == Outcome.BLOCK

    def test_missing_decision_id_blocked(self, patched_db):
        payload = _check_payload("dc-x", "NVDA")
        del payload["decision_id"]
        result = ExecutionFirewall().run(payload)
        assert result.outcome == Outcome.BLOCK

    def test_missing_ticker_blocked(self, patched_db):
        payload = _check_payload("dc-x", "NVDA")
        del payload["ticker"]
        result = ExecutionFirewall().run(payload)
        assert result.outcome == Outcome.BLOCK

    def test_invalid_trade_action_blocked(self, patched_db):
        _seed_decision(patched_db, "dc-x")
        result = ExecutionFirewall().run(_check_payload("dc-x", "NVDA", trade_action="YOLO"))
        assert result.outcome == Outcome.BLOCK
        assert "trade_action" in result.output["error"]

    def test_missing_portfolio_state_blocked(self, patched_db):
        _seed_decision(patched_db, "dc-x")
        payload = _check_payload("dc-x", "NVDA")
        del payload["portfolio_state"]
        result = ExecutionFirewall().run(payload)
        assert result.outcome == Outcome.BLOCK

    def test_non_numeric_value_blocked(self, patched_db):
        _seed_decision(patched_db, "dc-x")
        result = ExecutionFirewall().run(_check_payload("dc-x", "NVDA", proposed_position_value="lots"))
        assert result.outcome == Outcome.BLOCK


# ═══════════════════════════════════════════════════════
# Happy path — PASS
# ═══════════════════════════════════════════════════════


class TestHappyPath:
    def test_small_buy_passes(self, patched_db):
        _seed_decision(patched_db, "dc-pass")
        result = ExecutionFirewall().run(_check_payload("dc-pass", "NVDA", sector="tech"))
        assert result.outcome == Outcome.PASS
        assert result.output["verdict"] == "PASS"
        assert result.output["blocks"] == []

    def test_hold_pass_through(self, patched_db):
        _seed_decision(patched_db, "dc-hold", action="HOLD")
        result = ExecutionFirewall().run(_check_payload("dc-hold", "ANY", trade_action="HOLD"))
        assert result.outcome == Outcome.PASS
        assert (
            "pass-through" in result.output.get("skipped", "").lower()
            or "no position" in result.output.get("skipped", "").lower()
        )

    def test_sell_skips_buy_gates(self, patched_db):
        """SELL → VIX gate, banned ETF gate skip (BUY 전용)."""
        _seed_decision(patched_db, "dc-sell")
        result = ExecutionFirewall().run(
            _check_payload(
                "dc-sell",
                "TQQQ",  # banned ETF
                trade_action="SELL",
                portfolio_state=_portfolio(vix=40),  # VIX too high
                proposed_position_value=5000,
            )
        )
        # SELL: BUY 전용 gate 모두 skip → PASS (max_daily_loss 도 BUY 전용)
        assert result.outcome == Outcome.PASS


# ═══════════════════════════════════════════════════════
# Hard rules — anti-pattern lock-tests
# ═══════════════════════════════════════════════════════


class TestVixGateLockTest:
    """LOCK-TEST: VIX > 30 + BUY → 무조건 BLOCK (사용자 규칙 + rules.yaml)."""

    def test_vix_above_30_blocks_buy(self, patched_db):
        _seed_decision(patched_db, "dc-vix")
        result = ExecutionFirewall().run(
            _check_payload(
                "dc-vix",
                "NVDA",
                portfolio_state=_portfolio(vix=35),
            )
        )
        assert result.outcome == Outcome.BLOCK
        assert any(b["type"] == "vix_too_high" for b in result.output["blocks"])

    def test_vix_at_threshold_passes(self, patched_db):
        """VIX == threshold → strictly > 만 block."""
        _seed_decision(patched_db, "dc-vix-edge")
        result = ExecutionFirewall().run(
            _check_payload(
                "dc-vix-edge",
                "NVDA",
                portfolio_state=_portfolio(vix=VIX_HARD_BLOCK),
                sector="tech",
            )
        )
        # exactly threshold: not > so pass
        assert all(b["type"] != "vix_too_high" for b in result.output["blocks"])

    def test_vix_caution_band_soft_warn(self, patched_db):
        """VIX 25-30 → soft warn (PASS + warn list)."""
        _seed_decision(patched_db, "dc-vix-soft")
        result = ExecutionFirewall().run(
            _check_payload(
                "dc-vix-soft",
                "MSFT",
                portfolio_state=_portfolio(vix=27),
            )
        )
        assert result.outcome == Outcome.WARN
        assert any(w["type"] == "vix_too_high" for w in result.output["warns"])
        assert result.output["blocks"] == []


class TestBannedEtfLockTest:
    """LOCK-TEST: banned leverage ETF → 무조건 BLOCK (어떤 portfolio 상태든)."""

    @pytest.mark.parametrize("ticker", ["TQQQ", "SQQQ", "UPRO", "SPXU", "TSLL"])
    def test_each_banned_etf_blocked(self, patched_db, ticker):
        _seed_decision(patched_db, f"dc-{ticker}", ticker=ticker)
        result = ExecutionFirewall().run(_check_payload(f"dc-{ticker}", ticker))
        assert result.outcome == Outcome.BLOCK
        assert any(b["type"] == "banned_leverage_etf" for b in result.output["blocks"])

    def test_lowercase_ticker_normalized(self, patched_db):
        """소문자 입력도 동일하게 차단."""
        _seed_decision(patched_db, "dc-low", ticker="TQQQ")
        result = ExecutionFirewall().run(_check_payload("dc-low", "tqqq"))
        assert result.outcome == Outcome.BLOCK


class TestPositionCapLockTest:
    """LOCK-TEST: post-trade single position > 15% → BLOCK."""

    def test_oversized_buy_blocks(self, patched_db):
        _seed_decision(patched_db, "dc-pos")
        # 기존 NVDA 10k + 추가 20k = 30k / (100k+20k=120k) = 25% > 15%
        result = ExecutionFirewall().run(
            _check_payload(
                "dc-pos",
                "NVDA",
                proposed_position_value=20_000,
                sector="tech",
            )
        )
        assert result.outcome == Outcome.BLOCK
        assert any(b["type"] == "position_cap" for b in result.output["blocks"])

    def test_within_position_cap_passes(self, patched_db):
        _seed_decision(patched_db, "dc-pos-ok")
        # 기존 0 + 5k / 105k = 4.76% < 15%
        result = ExecutionFirewall().run(
            _check_payload(
                "dc-pos-ok",
                "AMD",
                proposed_position_value=5_000,
                sector="tech",
            )
        )
        # may have other blocks but position_cap not triggered
        assert all(b["type"] != "position_cap" for b in result.output["blocks"])


class TestSectorConcentrationLockTest:
    """LOCK-TEST: post-trade sector > 35% → BLOCK."""

    def test_sector_overload_blocks(self, patched_db):
        _seed_decision(patched_db, "dc-sec")
        # tech sector: NVDA 10k + AAPL 30k 추가 = 40k / 130k = 30.7%
        # 더 늘려야 35% 초과
        result = ExecutionFirewall().run(
            _check_payload(
                "dc-sec",
                "AAPL",
                proposed_position_value=40_000,  # 가능한 한 큰 비중
                portfolio_state={
                    "total_value": 100_000.0,
                    "cash": 60_000.0,
                    "positions": {
                        "NVDA": {"value": 20_000, "sector": "tech"},
                        "MSFT": {"value": 15_000, "sector": "tech"},
                    },
                    "vix": 18,
                },
                sector="tech",
            )
        )
        # 위반들 중 sector_concentration 포함 (다른 cap 도 같이 hit 가능)
        assert any(b["type"] == "sector_concentration" for b in result.output["blocks"])


class TestCashReserveLockTest:
    """LOCK-TEST: post-trade cash < 20% → BLOCK."""

    def test_low_cash_blocks(self, patched_db):
        _seed_decision(patched_db, "dc-cash")
        # cash 50k → -45k = 5k cash 후, total 105k → 5/105 = 4.76% < 20%
        result = ExecutionFirewall().run(
            _check_payload(
                "dc-cash",
                "AMD",
                proposed_position_value=45_000,
                sector="tech",
            )
        )
        assert any(b["type"] == "cash_reserve" for b in result.output["blocks"])


class TestLeverageCapLockTest:
    """LOCK-TEST: long_exposure / cash > 1.5x → BLOCK."""

    def test_high_leverage_blocks(self, patched_db):
        _seed_decision(patched_db, "dc-lev")
        result = ExecutionFirewall().run(
            _check_payload(
                "dc-lev",
                "AMD",
                proposed_position_value=5_000,
                portfolio_state={
                    "total_value": 100_000.0,
                    "cash": 10_000.0,  # very low cash
                    "positions": {
                        "NVDA": {"value": 50_000, "sector": "tech"},
                    },
                    "vix": 18,
                },
                sector="tech",
            )
        )
        # long = 50k + 5k = 55k / 10k = 5.5x > 1.5x
        assert any(b["type"] == "leverage_cap" for b in result.output["blocks"])


class TestMaxDailyLossLockTest:
    """LOCK-TEST: daily PnL <= -10% + BUY → BLOCK."""

    def test_daily_loss_blocks_buy(self, patched_db):
        _seed_decision(patched_db, "dc-loss")
        result = ExecutionFirewall().run(
            _check_payload(
                "dc-loss",
                "NVDA",
                portfolio_state=_portfolio(daily_pnl_pct=-0.12),
            )
        )
        assert any(b["type"] == "max_daily_loss" for b in result.output["blocks"])

    def test_daily_loss_does_not_block_sell(self, patched_db):
        _seed_decision(patched_db, "dc-loss-sell")
        result = ExecutionFirewall().run(
            _check_payload(
                "dc-loss-sell",
                "NVDA",
                trade_action="SELL",
                portfolio_state=_portfolio(daily_pnl_pct=-0.12),
            )
        )
        # SELL 은 max_daily_loss 적용 안 됨 (포지션 정리는 허용)
        assert all(b["type"] != "max_daily_loss" for b in result.output["blocks"])


# ═══════════════════════════════════════════════════════
# Persistence
# ═══════════════════════════════════════════════════════


class TestPersistence:
    def test_blocks_persisted_to_execution_blocks(self, patched_db):
        _seed_decision(patched_db, "dc-persist", ticker="TQQQ")
        ExecutionFirewall().run(_check_payload("dc-persist", "TQQQ"))
        rows = query(
            "SELECT block_type, severity, evidence_json FROM execution_blocks WHERE decision_id=?",
            ("dc-persist",),
            db_path=patched_db,
        )
        assert len(rows) >= 1
        assert any(dict(r)["block_type"] == "banned_leverage_etf" for r in rows)
        assert all(dict(r)["severity"] == "hard" for r in rows)

    def test_audit_ledger_layer_a(self, patched_db):
        _seed_decision(patched_db, "dc-aud")
        ExecutionFirewall().run(_check_payload("dc-aud", "NVDA", sector="tech"))
        rows = query(
            "SELECT layer, outcome FROM agent_audit_ledger WHERE actor_name='execution-firewall'",
            db_path=patched_db,
        )
        assert rows[0]["layer"] == "A"
        assert rows[0]["outcome"] in ("pass", "warn", "block")

    def test_soft_warn_persisted(self, patched_db):
        _seed_decision(patched_db, "dc-soft")
        ExecutionFirewall().run(
            _check_payload(
                "dc-soft",
                "MSFT",
                portfolio_state=_portfolio(vix=27),
            )
        )
        rows = query(
            "SELECT severity FROM execution_blocks WHERE decision_id=?",
            ("dc-soft",),
            db_path=patched_db,
        )
        assert any(dict(r)["severity"] == "soft" for r in rows)


# ═══════════════════════════════════════════════════════
# list_blocks
# ═══════════════════════════════════════════════════════


class TestListBlocks:
    def test_empty_db_zero(self, patched_db):
        result = ExecutionFirewall().run({"action": "list_blocks"})
        assert result.outcome == Outcome.PASS
        assert result.output["count"] == 0

    def test_filter_by_severity(self, patched_db):
        _seed_decision(patched_db, "dc-h")
        _seed_decision(patched_db, "dc-s")
        log_execution_block(
            decision_id="dc-h",
            block_type="vix_too_high",
            severity="hard",
            block_reason="x",
            evidence={},
            db_path=patched_db,
        )
        log_execution_block(
            decision_id="dc-s",
            block_type="vix_too_high",
            severity="soft",
            block_reason="x",
            evidence={},
            db_path=patched_db,
        )
        result = ExecutionFirewall().run({"action": "list_blocks", "severity": "hard"})
        assert result.output["count"] == 1
        assert dict(result.output["blocks"][0])["severity"] == "hard"

    def test_filter_by_decision_id(self, patched_db):
        _seed_decision(patched_db, "dc-d1")
        _seed_decision(patched_db, "dc-d2")
        log_execution_block(
            decision_id="dc-d1",
            block_type="vix_too_high",
            severity="hard",
            block_reason="x",
            evidence={},
            db_path=patched_db,
        )
        log_execution_block(
            decision_id="dc-d2",
            block_type="vix_too_high",
            severity="hard",
            block_reason="y",
            evidence={},
            db_path=patched_db,
        )
        result = ExecutionFirewall().run({"action": "list_blocks", "decision_id": "dc-d1"})
        assert result.output["count"] == 1


# ═══════════════════════════════════════════════════════
# Discord publish
# ═══════════════════════════════════════════════════════


class TestDiscordPublish:
    def test_hard_block_publishes_to_incidents(self, patched_db):
        _seed_decision(patched_db, "dc-pub", ticker="TQQQ")
        with patch("nuri.agents.discord.publisher.DiscordPublisher.publish_embed") as mock_publish:
            ExecutionFirewall().run(_check_payload("dc-pub", "TQQQ"))
            mock_publish.assert_called_once()
            kw = mock_publish.call_args.kwargs
            assert kw["actor_name"] == "execution-firewall"
            assert "BLOCK" in kw["embed"]["title"]

    def test_pass_does_not_publish(self, patched_db):
        _seed_decision(patched_db, "dc-pubp")
        with patch("nuri.agents.discord.publisher.DiscordPublisher.publish_embed") as mock_publish:
            ExecutionFirewall().run(_check_payload("dc-pubp", "AMD", sector="tech"))
            mock_publish.assert_not_called()

    def test_publish_failure_does_not_block_actor(self, patched_db):
        _seed_decision(patched_db, "dc-pubf", ticker="TQQQ")
        with patch(
            "nuri.agents.discord.publisher.DiscordPublisher.publish_embed",
            side_effect=RuntimeError("network"),
        ):
            result = ExecutionFirewall().run(_check_payload("dc-pubf", "TQQQ"))
            # publish 실패해도 BLOCK outcome 유지
            assert result.outcome == Outcome.BLOCK


# ═══════════════════════════════════════════════════════
# Helper direct lock-tests
# ═══════════════════════════════════════════════════════


class TestHelperLockTests:
    def test_invalid_block_type_rejected(self, db_path):
        _seed_decision(db_path, "dc-x")
        with pytest.raises(ValueError, match="block_type must be"):
            log_execution_block(
                decision_id="dc-x",
                block_type="bogus",
                severity="hard",
                block_reason="x",
                evidence={},
                db_path=db_path,
            )

    def test_invalid_severity_rejected(self, db_path):
        _seed_decision(db_path, "dc-y")
        with pytest.raises(ValueError, match="severity must be"):
            log_execution_block(
                decision_id="dc-y",
                block_type="vix_too_high",
                severity="medium",
                block_reason="x",
                evidence={},
                db_path=db_path,
            )

    def test_empty_reason_rejected(self, db_path):
        _seed_decision(db_path, "dc-z")
        with pytest.raises(ValueError, match="block_reason required"):
            log_execution_block(
                decision_id="dc-z",
                block_type="vix_too_high",
                severity="hard",
                block_reason="   ",
                evidence={},
                db_path=db_path,
            )


# ═══════════════════════════════════════════════════════
# Constants smoke
# ═══════════════════════════════════════════════════════


class TestConstants:
    def test_vix_thresholds_sane(self):
        assert 0 < VIX_SOFT_CAUTION < VIX_HARD_BLOCK

    def test_position_thresholds_sane(self):
        assert 0 < MAX_SINGLE_POSITION < MAX_SECTOR_EXPOSURE
        assert 0 < MIN_CASH_RESERVE < 1
        assert MAX_LEVERAGE >= 1.0

    def test_banned_etfs_non_empty(self):
        assert len(BANNED_LEVERAGE_ETFS) >= 3


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════


class TestCli:
    def test_cli_list_blocks_empty(self, patched_db, capsys):
        from nuri.agents.actors.execution_firewall import main

        rc = main(["list_blocks"])
        assert rc == 0
        out = capsys.readouterr().out
        assert '"count": 0' in out

    def test_cli_list_blocks_severity_filter(self, patched_db, capsys):
        from nuri.agents.actors.execution_firewall import main

        rc = main(["list_blocks", "--severity", "hard"])
        assert rc == 0

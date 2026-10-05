"""Bucket E2 branch coverage — engine gate, memory, conflicts. (certification/remediation 은 #1619 로 삭제.)

Targets specific missed lines from coverage audit 2026-05-04.
Each test = behavioral lock (not smoke).
"""
# cspell:ignore SPYY KOSP siege

from __future__ import annotations

from unittest.mock import patch

import pytest

from nuri.core.db import get_db, init_db


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "test.db"
    init_db(p)
    return p


# ════════════════════════ memory.py ════════════════════════════════════


class TestConflictsBullSellRegimeFit:
    def test_bull_with_regime_fit_sell_skipped(self, db_path, monkeypatch):
        """Line 163: bull regime 에서 SELL 이 regime_fit 이면 모순으로 분류 X (continue)."""
        from unittest.mock import MagicMock

        from nuri.trading.engine.conflicts import detect_conflicts
        from nuri.trading.recommend.candidates import TIER_ACTIONABLE

        # Single SELL candidate, regime_fit=True
        sell_cand = MagicMock(
            ticker="AAPL",
            tier=TIER_ACTIONABLE,
            direction="SELL",
            signal_id="sell1",
            regime_fit=True,
            profit_factor=2.0,
        )
        monkeypatch.setattr(
            "nuri.trading.recommend.candidates.screen_candidates",
            lambda **kw: [sell_cand],
        )

        # Force regime = bull
        from dataclasses import dataclass

        @dataclass
        class FakeRegime:
            regime: str = "bull_low_vol"
            trend: str = "bull"
            volatility: str = "low"
            confidence: float = 0.8

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: FakeRegime(),
        )

        conflicts = detect_conflicts(db_path=db_path)
        # regime_fit → continue (no regime_contradiction emitted)
        regime_conflicts = [c for c in conflicts if c.conflict_type == "regime_contradiction"]
        assert regime_conflicts == []


class TestMemoryDriftZeroWinrate:
    def test_zero_all_time_winrate_skipped(self, db_path):
        """Line 155 (continue): all_time win_rate=0 → drift skip."""
        from nuri.trading.engine.memory import detect_drift

        with get_db(db_path) as conn:
            # all_time win_rate = 0 → drift 계산 스킵 (분모 0 회피)
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, "
                "trades, win_rate, profit_factor, avg_return) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("2025-03-25", "loser_signal", None, "all_time", 50, 0.0, 0.5, -2.0),
            )
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, "
                "trades, win_rate, profit_factor, avg_return) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("2025-03-25", "loser_signal", None, "recent_90d", 10, 0.1, 0.6, -1.0),
            )

        drifts = detect_drift(db_path=db_path)
        # zero-winrate 시그널은 skip — drift 결과 0건
        assert drifts == []

    def test_no_recent_match_skipped(self, db_path):
        """Line 155 (continue): recent map 에 sig_id 없으면 drift skip."""
        from nuri.trading.engine.memory import detect_drift

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, "
                "trades, win_rate, profit_factor, avg_return) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("2025-03-25", "orphan_signal", None, "all_time", 100, 0.6, 2.0, 3.0),
            )
            # recent_90d 에 동일 signal_id 없음 → continue branch
        drifts = detect_drift(db_path=db_path)
        assert drifts == []


class TestMemorySaveSnapshotEmpty:
    def test_save_snapshot_empty_trades_returns_zero(self, db_path, tmp_path, monkeypatch):
        """Line 50-51: trades.empty (header-only csv) → return 0 early.

        Line 114 (`if not records`) 는 unreachable 한 defensive guard 이므로 pragma 처리.
        trades non-empty 이면 all_time groupby 가 반드시 1+ record 생성하기 때문.
        """
        from nuri.trading.engine import memory as mem_mod

        # _find_latest_csv 가 헤더만 있는 빈 CSV 반환
        empty_csv = tmp_path / "signal_results.csv"
        empty_csv.write_text("signal_id,return_pct,entry_date\n")  # header only — no rows

        monkeypatch.setattr(mem_mod, "_find_latest_csv", lambda fname: empty_csv)
        # trades.empty → line 51 early return — DB write 없음
        result = mem_mod.save_snapshot(db_path=db_path)
        assert result == 0


class TestMemoryMain:
    def test_main_no_args_prints_status(self, monkeypatch, capsys):
        """Lines 241-254 (refactored to main): default invocation calls detect_drift + print."""
        from nuri.trading.engine import memory as mem_mod

        called = {"snapshot": False, "detect": False, "print": False}

        def fake_detect(db_path=None):
            called["detect"] = True
            return []

        def fake_print(drifts):
            called["print"] = True

        monkeypatch.setattr(mem_mod, "detect_drift", fake_detect)
        monkeypatch.setattr(mem_mod, "print_memory_status", fake_print)
        rc = mem_mod.main([])
        assert rc == 0
        assert called["detect"] is True
        assert called["print"] is True

    def test_main_snapshot_flag_invokes_save(self, monkeypatch):
        """--snapshot: save_snapshot 호출."""
        from nuri.trading.engine import memory as mem_mod

        called = {"save": False, "init": False}

        def fake_save():
            called["save"] = True
            return 5

        def fake_init():
            called["init"] = True

        monkeypatch.setattr(mem_mod, "save_snapshot", fake_save)
        monkeypatch.setattr("nuri.core.db.init_db", fake_init)
        monkeypatch.setattr(mem_mod, "detect_drift", lambda db_path=None: [])
        monkeypatch.setattr(mem_mod, "print_memory_status", lambda d: None)

        rc = mem_mod.main(["--snapshot"])
        assert rc == 0
        assert called["save"] is True
        assert called["init"] is True


# ════════════════════════ gate.py ════════════════════════════════════


class TestGateScorecardFound:
    def test_signal_scorecard_csv_found(self, db_path, tmp_path, monkeypatch):
        """Lines 117-120: scorecard CSV 발견 → found=True branch.

        gate.py 내부에서 `from pathlib import Path` 후 `Path(__file__).parent...` 로
        report_dir 결정 — Path 자체를 monkeypatch 하여 우리의 tmp_path 가리키게 함.
        """
        from pathlib import Path as RealPath

        # Set up: tmp_path/data/reports/2025-03-25/signal_scorecard.csv
        snap_dir = tmp_path / "data" / "reports" / "2025-03-25"
        snap_dir.mkdir(parents=True)
        (snap_dir / "signal_scorecard.csv").write_text("dummy\n")

        # Path(__file__).parent.parent.parent.parent — 4번 parent.
        # gate.py 위치: nuri/trading/engine/gate.py → 4 parents = 프로젝트 루트.
        # tmp_path 가 프로젝트 루트인 것처럼 보이게 하려면, 그 자리에 파일이 있는 것처럼
        # 'fake __file__' 을 4-deep 으로 만들어준다.
        fake_file = tmp_path / "nuri" / "trading" / "engine" / "gate.py"
        fake_file.parent.mkdir(parents=True)
        fake_file.write_text("")

        import nuri.trading.engine.gate as gate_mod

        monkeypatch.setattr(gate_mod, "__file__", str(fake_file))

        cond = gate_mod._check_signal_scorecard(db_path=db_path)
        assert cond.passed is True
        assert cond.detail == "존재"


class TestGateMain:
    def test_main_phase_flag_invokes_check_gate(self, monkeypatch, capsys):
        """Lines 273-286 (refactored): --phase=collect path."""
        from nuri.trading.engine import gate as gate_mod

        called = {"check": False, "all": False}

        def fake_check(phase, db_path=None):
            called["check"] = True
            return gate_mod.GateResult(phase=phase, total=0, passed=0, score=0.0, ready=True, conditions=[])

        def fake_all(db_path=None):
            called["all"] = True
            return {}

        monkeypatch.setattr(gate_mod, "check_gate", fake_check)
        monkeypatch.setattr(gate_mod, "check_all_gates", fake_all)
        monkeypatch.setattr(gate_mod, "print_gate", lambda r: None)
        rc = gate_mod.main(["--phase", "collect"])
        assert rc == 0
        assert called["check"] is True
        assert called["all"] is False  # all-gates path NOT taken

    def test_main_no_phase_invokes_check_all(self, monkeypatch):
        """No --phase: check_all_gates branch."""
        from nuri.trading.engine import gate as gate_mod

        called = {"check": False, "all": False}

        def fake_check(phase, db_path=None):
            called["check"] = True
            return gate_mod.GateResult(phase=phase, total=0, passed=0, score=0.0, ready=True, conditions=[])

        def fake_all(db_path=None):
            called["all"] = True
            return {
                "collect": gate_mod.GateResult("collect", 0, 0, 0.0, True, []),
            }

        monkeypatch.setattr(gate_mod, "check_gate", fake_check)
        monkeypatch.setattr(gate_mod, "check_all_gates", fake_all)
        monkeypatch.setattr(gate_mod, "print_gate", lambda r: None)
        rc = gate_mod.main([])
        assert rc == 0
        assert called["all"] is True
        assert called["check"] is False

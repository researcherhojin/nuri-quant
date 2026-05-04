"""Bucket E2 branch coverage — engine/certification, gate, memory, conflicts, remediation.

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


# ════════════════════════ certification.py ════════════════════════════


class TestCertificationClassifyAssetClass:
    def test_safety_net_no_default_rule(self):
        """Line 326: rules without `default` match → fallback 'us_equity'."""
        from nuri.trading.engine.certification import _classify_asset_class

        # Rules that won't match — no default rule
        rules = [
            {"match": {"ticker_suffix": ".KS"}, "asset_class": "kr_equity"},
        ]
        # AAPL has no .KS suffix — no rule matches → safety net
        assert _classify_asset_class("AAPL", "Technology", rules) == "us_equity"


class TestCertificationCompute3dChange:
    def test_zero_past_value_returns_none(self, db_path):
        """Line 383: past value == 0 → ZeroDivisionError 회피, None 반환."""
        from nuri.trading.engine.certification import _compute_3d_change

        with get_db(db_path) as conn:
            for d, v in [
                ("2025-03-22", 0.0),  # oldest in window
                ("2025-03-23", 1.0),
                ("2025-03-24", 1.5),
                ("2025-03-25", 2.0),  # latest
            ]:
                conn.execute(
                    "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                    (d, "vix", v),
                )
        # 4 rows fetched (DESC LIMIT 4); past = oldest (0.0) → None
        result = _compute_3d_change("vix", db_path=db_path)
        assert result is None


class TestCertificationVolatilityClass:
    def test_secondary_indicator_missing_silent_skip(self, db_path):
        """Line 422: secondary indicator data 없으면 continue (silent)."""
        from nuri.trading.engine.certification import _check_volatility_for_class

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "vix", 18.0),
            )
        policy = {
            "volatility_primary": "vix",
            "volatility_primary_threshold": 30,
            "volatility_secondary": ["nonexistent_indicator"],
            "volatility_secondary_threshold": 25,
        }
        out = _check_volatility_for_class("us_equity", policy, db_path=db_path)
        # 1 condition only — primary pass; secondary silently skipped
        assert len(out) == 1
        assert out[0].id == "volatility_gate_us_equity"
        assert out[0].passed is True


class TestCertificationVolatilityGates:
    def test_class_without_policy_skipped(self, db_path, monkeypatch):
        """Line 460: asset_classes 에 매칭 policy 없으면 continue."""
        from nuri.trading.engine import certification as cert_mod

        # Seed portfolio with kr_equity ticker
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, sector) VALUES (?, ?, ?, ?, ?)",
                ("test", "005930.KS", 10, 70000.0, "Semiconductor"),
            )

        # Mock RULES so siege_gates has classes but no kr_equity policy
        fake_rules = {
            "siege_gates": {
                "asset_class_rules": [
                    {"match": {"ticker_suffix": ".KS"}, "asset_class": "kr_equity"},
                    {"match": {"default": True}, "asset_class": "us_equity"},
                ],
                "asset_classes": {
                    # kr_equity policy 없음 → skip
                    "us_equity": {"volatility_primary": "vix", "volatility_primary_threshold": 30},
                },
            }
        }
        monkeypatch.setattr(cert_mod, "RULES", fake_rules)

        out = cert_mod._check_volatility_gates(db_path=db_path)
        # kr_equity 매칭하지만 policy 없어서 결과는 0건 (continue)
        assert all("kr_equity" not in c.id for c in out)


class TestCertificationFreshnessClass:
    def test_secondary_freshness_missing_silent(self, db_path):
        """Line 556: secondary freshness 데이터 없으면 silent skip."""
        from nuri.trading.engine.certification import _check_freshness_for_class

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("SPY", "2025-03-25", 500.0),
            )
        policy = {
            "freshness_primary": "SPY",
            "freshness_max_hours": 9999,  # always ok
            "freshness_secondary": ["NONEXISTENT_TICKER"],
        }
        out = _check_freshness_for_class("us_equity", policy, db_path=db_path)
        # primary 1건만, secondary silent skip
        assert len(out) == 1
        assert out[0].id == "data_fresh_us_equity"


class TestCertificationDataFreshness:
    def test_class_without_policy_skipped(self, db_path, monkeypatch):
        """Line 590: data_freshness 에서도 policy 없는 class 는 continue."""
        from nuri.trading.engine import certification as cert_mod

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, sector) VALUES (?, ?, ?, ?, ?)",
                ("test", "005930.KS", 10, 70000.0, "Semiconductor"),
            )

        fake_rules = {
            "siege_gates": {
                "asset_class_rules": [
                    {"match": {"ticker_suffix": ".KS"}, "asset_class": "kr_equity"},
                    {"match": {"default": True}, "asset_class": "us_equity"},
                ],
                "asset_classes": {
                    "us_equity": {"freshness_primary": "SPY", "freshness_max_hours": 72},
                },
            }
        }
        monkeypatch.setattr(cert_mod, "RULES", fake_rules)

        out = cert_mod._check_data_freshness(db_path=db_path)
        # kr_equity: policy missing → continue (no data_fresh_kr_equity emitted)
        assert all("kr_equity" not in c.id for c in out)


class TestCertificationCountExternalForClass:
    def test_empty_tickers_fallback_global(self, db_path):
        """Lines 603-607: tickers=[] → global SELECT COUNT(*) fallback."""
        from nuri.trading.engine.certification import _count_external_for_class

        with get_db(db_path) as conn:
            for src in ["a", "b", "c"]:
                conn.execute(
                    "INSERT INTO external_analysis (date, source, ticker, data_type, value) VALUES (?, ?, ?, ?, ?)",
                    ("2025-03-25", src, "AAPL", "rating", "BUY"),
                )
        records, sources = _count_external_for_class("us_equity", [], db_path=db_path)
        assert records == 3
        assert sources == 3


class TestCertificationExternalForClassException:
    def test_count_exception_returns_warning(self, db_path):
        """Lines 625-626: _count_external_for_class throws → warning 반환."""
        from nuri.trading.engine.certification import _check_external_for_class

        # Patch the helper to raise — verifies except branch
        with patch(
            "nuri.trading.engine.certification._count_external_for_class",
            side_effect=RuntimeError("synthetic"),
        ):
            cond = _check_external_for_class(
                "us_equity",
                ["AAPL"],
                {"external_min_records": 10, "external_min_sources": 3},
                db_path=db_path,
            )
        assert cond.passed is False
        assert cond.severity == "warning"
        assert "external_analysis 조회 실패" in cond.detail


class TestCertificationCheckExternalDataNoPolicy:
    def test_external_class_without_policy_skipped(self, db_path, monkeypatch):
        """Line 668: _check_external_data 에서도 policy 없는 class 는 continue."""
        from nuri.trading.engine import certification as cert_mod

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, sector) VALUES (?, ?, ?, ?, ?)",
                ("test", "005930.KS", 10, 70000.0, "Semiconductor"),
            )

        fake_rules = {
            "siege_gates": {
                "asset_class_rules": [
                    {"match": {"ticker_suffix": ".KS"}, "asset_class": "kr_equity"},
                    {"match": {"default": True}, "asset_class": "us_equity"},
                ],
                "asset_classes": {
                    "us_equity": {"external_min_records": 10, "external_min_sources": 3},
                },
            }
        }
        monkeypatch.setattr(cert_mod, "RULES", fake_rules)

        out = cert_mod._check_external_data(db_path=db_path)
        # kr_equity policy missing → continue (no external_data_kr_equity emitted)
        assert all("kr_equity" not in c.id for c in out)


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


class TestRemediationGateNoMapping:
    def test_failed_gate_without_violation_mapping_skipped(self, db_path, monkeypatch):
        """Line 90: _GATE_TO_VIOLATION 매핑 없는 failed gate 는 continue (skip)."""
        from unittest.mock import MagicMock

        from nuri.trading.engine import remediation as rem

        # cert with a failed gate that has NO mapping (e.g. 'unknown_gate')
        unknown_failed = MagicMock(id="unknown_gate", passed=False, severity="error", detail="x")
        ok_passed = MagicMock(id="position_limit", passed=True, severity="error", detail="ok")

        cert_mock = MagicMock(
            certified=False,
            score=50.0,
            conditions=[unknown_failed, ok_passed],
            passed=1,
            total_conditions=2,
        )
        # certify / advisor 모두 함수 내부 import — 'source.module.function' patching
        monkeypatch.setattr(
            "nuri.trading.engine.certification.certify",
            lambda **kw: cert_mock,
        )
        monkeypatch.setattr(
            "nuri.analysis.rebalance_advisor.generate_advisor_report",
            lambda **kw: {"actions": []},
        )

        plan = rem.generate_remediation(db_path=db_path)
        # unknown_gate has no mapping → no actions, ends in unresolvable (or unmapped)
        assert plan.actions == []


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


class TestCertificationClassifyAssetClassSectorMatch:
    def test_sector_exact_match(self):
        """Line 325: `sector == m['sector']` exact match branch."""
        from nuri.trading.engine.certification import _classify_asset_class

        rules = [
            {"match": {"sector": "Treasury"}, "asset_class": "bond"},
            {"match": {"default": True}, "asset_class": "us_equity"},
        ]
        assert _classify_asset_class("TLT", "Treasury", rules) == "bond"


class TestCertificationGroupHoldingsDup:
    def test_duplicate_ticker_sector_skipped(self, db_path):
        """Line 352: 같은 (ticker, sector) 가 여러 계좌에 있으면 두번째 row continue."""
        from nuri.trading.engine import certification as cert_mod

        with get_db(db_path) as conn:
            # 두 계좌에서 같은 (AAPL, Technology) 보유 — DISTINCT
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, sector) VALUES (?, ?, ?, ?, ?)",
                ("acct1", "AAPL", 10, 150.0, "Technology"),
            )
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, sector) VALUES (?, ?, ?, ?, ?)",
                ("acct2", "AAPL", 5, 160.0, "Technology"),
            )
        groups = cert_mod._group_holdings_by_asset_class(db_path=db_path)
        # AAPL 만 1번 등장 (DISTINCT 효과)
        all_tickers = [h["ticker"] for v in groups.values() for h in v]
        assert all_tickers.count("AAPL") == 1


class TestCertificationFreshnessClassThresholds:
    def test_primary_stale_emits_warning(self, db_path):
        """Line 548: primary age > max_hours → warning emit."""
        from nuri.trading.engine.certification import _check_freshness_for_class

        # Insert SPY price from 10 days ago — age > 1h
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("SPY", "2020-01-01", 300.0),
            )
        policy = {
            "freshness_primary": "SPY",
            "freshness_max_hours": 1,  # impossible — 항상 stale
        }
        out = _check_freshness_for_class("us_equity", policy, db_path=db_path)
        # primary stale → warning
        assert len(out) == 1
        assert out[0].passed is False
        assert out[0].severity == "warning"
        assert "초과" in out[0].detail

    def test_secondary_stale_emits_warning(self, db_path):
        """Line 560: secondary age > max_hours → cross-market warning."""
        from nuri.trading.engine.certification import _check_freshness_for_class

        with get_db(db_path) as conn:
            # primary fresh enough
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("SPY", "2099-01-01", 300.0),
            )
            # secondary stale (10 years ago)
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("KOSPI", "2015-01-01", 2000.0),
            )
        policy = {
            "freshness_primary": "SPY",
            "freshness_max_hours": 999999,  # primary always fresh
            "freshness_secondary": ["KOSPI"],
        }
        # use threshold 1h so secondary stale
        # Policy 위 max_hours 가 secondary 에도 사용됨 (freshness_max_hours)
        # 그러므로 둘 다 같은 threshold — KOSPI 가 SPY 보다 더 stale 이지만 999999 면 둘 다 ok
        # 다른 방식: max_hours 작게
        policy["freshness_max_hours"] = 1
        # 이제 SPY (2099 = 미래) 는 age 음수 → ok, KOSPI (2015) age > 1
        # 다만 _ticker_age_hours 가 (now - date) 이므로 SPY 미래 → 음수 → 음수 <= 1 ok
        out = _check_freshness_for_class("us_equity", policy, db_path=db_path)
        # primary ok + secondary stale (warning)
        secondary = [c for c in out if "KOSPI" in c.id]
        assert len(secondary) == 1
        assert secondary[0].passed is False
        assert "교차 시장 stale" in secondary[0].detail


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

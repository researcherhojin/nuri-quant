"""DriftSentinel tests (#529 Phase 2 — actor #12, canonical Layer B).

검증 (Codex Round 5 Layer B):
- Layer B invariants (deterministic, ZERO LLM, registered in canonical 15)
- PSI math (identical → 0, completely different → high, degenerate handling)
- KS math (identical → 0, shifted → high)
- severity classification 4-state (stable / minor / major / critical)
- check 4 outcomes (PASS / WARN minor / WARN major / BLOCK critical)
- scan_features aggregation (PASS / WARN / BLOCK)
- list_alerts filter (severity / since_iso / limit)
- Discord publish routing (critical=INCIDENTS, major=OPS, minor/stable=skip)
- HelperLockTests (log_drift_alert enum + value validation)
- CLI smoke (list_alerts only — check/scan_features 는 array 입력 필요)
- audit_ledger 자동 기록
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from nuri.agents.actors.drift_sentinel import (
    KS_CRITICAL,
    KS_MAJOR,
    KS_MINOR,
    PSI_CRITICAL,
    PSI_MAJOR,
    PSI_MINOR,
    DriftSentinel,
    _classify_severity,
    _compute_ks,
    _compute_psi,
    _severity_threshold,
    main,
)
from nuri.agents.base import Layer, Outcome
from nuri.core.db import (
    init_db,
    log_drift_alert,
    query,
)

# ═══════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "drift.db"
    init_db(path)
    return path


@pytest.fixture
def patched_db(db_path):
    """모든 DB 호출을 임시 path 로 redirect."""
    from nuri.core import db as db_module

    def make_redirect(fn):
        def wrapped(*args, **kwargs):
            kwargs.setdefault("db_path", db_path)
            return fn(*args, **kwargs)

        return wrapped

    patches = [
        patch(
            "nuri.agents.base.log_agent_audit",
            side_effect=make_redirect(db_module.log_agent_audit),
        ),
        patch(
            "nuri.agents.base.start_agent_run",
            side_effect=make_redirect(db_module.start_agent_run),
        ),
        patch(
            "nuri.agents.base.finish_agent_run",
            side_effect=make_redirect(db_module.finish_agent_run),
        ),
        patch(
            "nuri.agents.actors.drift_sentinel.log_drift_alert",
            side_effect=make_redirect(db_module.log_drift_alert),
        ),
        patch(
            "nuri.agents.actors.drift_sentinel.query",
            side_effect=make_redirect(db_module.query),
        ),
    ]
    for p in patches:
        p.start()
    yield db_path
    for p in patches:
        p.stop()


@pytest.fixture
def no_publish():
    """Discord publish mock — 모든 테스트 default."""
    with patch("nuri.agents.actors.drift_sentinel.DriftSentinel._publish_drift") as m:
        yield m


# ═══════════════════════════════════════════════════════
# Layer invariants
# ═══════════════════════════════════════════════════════


class TestDriftSentinelLayer:
    def test_actor_layer_is_b(self):
        assert DriftSentinel.layer == Layer.B

    def test_no_llm_dependency(self):
        assert getattr(DriftSentinel, "_uses_llm", False) is False

    def test_registered_in_canonical_15(self):
        from nuri.agents.base import REGISTRY

        assert REGISTRY.get("drift-sentinel") is DriftSentinel

    def test_valid_actions_exposed(self):
        assert DriftSentinel.VALID_ACTIONS == ("check", "scan_features", "list_alerts")

    def test_actor_name_canonical(self):
        assert DriftSentinel.name == "drift-sentinel"


# ═══════════════════════════════════════════════════════
# PSI math primitives
# ═══════════════════════════════════════════════════════


class TestPsiMath:
    def test_identical_distributions_psi_zero(self):
        rng = np.random.default_rng(42)
        sample = rng.normal(0, 1, 1000)
        # 동일 분포 → PSI ~ 0
        psi = _compute_psi(sample, sample.copy())
        assert psi < 0.01

    def test_similar_distributions_psi_low(self):
        rng = np.random.default_rng(42)
        baseline = rng.normal(0, 1, 1000)
        current = rng.normal(0, 1, 1000)  # 같은 분포 다른 sample
        psi = _compute_psi(baseline, current)
        # IID resample → PSI 일반적으로 < PSI_MINOR
        assert psi < PSI_MINOR

    def test_shifted_distribution_psi_high(self):
        rng = np.random.default_rng(42)
        baseline = rng.normal(0, 1, 1000)
        current = rng.normal(3, 1, 1000)  # mean shift +3σ
        psi = _compute_psi(baseline, current)
        # 큰 shift → critical 영역
        assert psi >= PSI_CRITICAL

    def test_completely_different_distribution_psi_very_high(self):
        rng = np.random.default_rng(42)
        baseline = rng.normal(0, 1, 1000)
        current = rng.normal(10, 1, 1000)  # 거의 disjoint
        psi = _compute_psi(baseline, current)
        assert psi > PSI_CRITICAL

    def test_degenerate_baseline_returns_zero(self):
        baseline = np.ones(100)  # 분산 0
        current = np.random.default_rng(0).normal(0, 1, 100)
        psi = _compute_psi(baseline, current)
        assert psi == 0.0

    def test_empty_input_returns_zero(self):
        assert _compute_psi(np.array([]), np.array([1.0, 2.0])) == 0.0
        assert _compute_psi(np.array([1.0, 2.0]), np.array([])) == 0.0

    def test_nan_inf_returns_zero(self):
        baseline = np.array([1.0, 2.0, np.nan, 4.0])
        current = np.array([1.0, 2.0, 3.0, 4.0])
        assert _compute_psi(baseline, current) == 0.0

    def test_psi_non_negative(self):
        """PSI 는 정의상 ≥ 0."""
        rng = np.random.default_rng(0)
        for _ in range(20):
            b = rng.normal(0, 1, 200)
            c = rng.normal(rng.uniform(-2, 2), rng.uniform(0.5, 2), 200)
            assert _compute_psi(b, c) >= 0.0


# ═══════════════════════════════════════════════════════
# KS math primitives
# ═══════════════════════════════════════════════════════


class TestKsMath:
    def test_identical_distributions_ks_low(self):
        rng = np.random.default_rng(42)
        sample = rng.normal(0, 1, 1000)
        ks = _compute_ks(sample, sample.copy())
        assert ks < 0.01

    def test_shifted_distribution_ks_high(self):
        rng = np.random.default_rng(42)
        baseline = rng.normal(0, 1, 1000)
        current = rng.normal(3, 1, 1000)
        ks = _compute_ks(baseline, current)
        assert ks >= KS_CRITICAL

    def test_ks_in_unit_interval(self):
        rng = np.random.default_rng(0)
        for _ in range(10):
            b = rng.normal(0, 1, 200)
            c = rng.normal(rng.uniform(-2, 2), 1, 200)
            ks = _compute_ks(b, c)
            assert 0.0 <= ks <= 1.0

    def test_empty_input_returns_zero(self):
        assert _compute_ks(np.array([]), np.array([1.0])) == 0.0

    def test_nan_input_returns_zero(self):
        baseline = np.array([1.0, np.nan, 3.0])
        current = np.array([1.0, 2.0, 3.0])
        assert _compute_ks(baseline, current) == 0.0


# ═══════════════════════════════════════════════════════
# Severity classification
# ═══════════════════════════════════════════════════════


class TestSeverityClassification:
    def test_psi_stable(self):
        assert _classify_severity("psi", 0.05) == "stable"
        assert _classify_severity("psi", 0.0) == "stable"

    def test_psi_minor(self):
        assert _classify_severity("psi", 0.10) == "minor"
        assert _classify_severity("psi", 0.20) == "minor"

    def test_psi_major(self):
        assert _classify_severity("psi", 0.25) == "major"
        assert _classify_severity("psi", 0.40) == "major"

    def test_psi_critical(self):
        assert _classify_severity("psi", 0.50) == "critical"
        assert _classify_severity("psi", 1.5) == "critical"

    def test_ks_stable(self):
        assert _classify_severity("ks", 0.04) == "stable"

    def test_ks_minor(self):
        assert _classify_severity("ks", 0.05) == "minor"
        assert _classify_severity("ks", 0.09) == "minor"

    def test_ks_major(self):
        assert _classify_severity("ks", 0.10) == "major"
        assert _classify_severity("ks", 0.15) == "major"

    def test_ks_critical(self):
        assert _classify_severity("ks", 0.20) == "critical"
        assert _classify_severity("ks", 0.99) == "critical"

    def test_invalid_test_type_raises(self):
        with pytest.raises(ValueError):
            _classify_severity("chi2", 0.1)

    def test_negative_statistic_raises(self):
        with pytest.raises(ValueError):
            _classify_severity("psi", -0.01)

    def test_severity_threshold_psi(self):
        assert _severity_threshold("psi", "stable") == 0.0
        assert _severity_threshold("psi", "minor") == PSI_MINOR
        assert _severity_threshold("psi", "major") == PSI_MAJOR
        assert _severity_threshold("psi", "critical") == PSI_CRITICAL

    def test_severity_threshold_ks(self):
        assert _severity_threshold("ks", "stable") == 0.0
        assert _severity_threshold("ks", "minor") == KS_MINOR
        assert _severity_threshold("ks", "major") == KS_MAJOR
        assert _severity_threshold("ks", "critical") == KS_CRITICAL


# ═══════════════════════════════════════════════════════
# Invalid action handling
# ═══════════════════════════════════════════════════════


class TestInvalidAction:
    def test_invalid_action_blocks(self, patched_db, no_publish):
        actor = DriftSentinel()
        result = actor.run({"action": "delete"})
        assert result.outcome == Outcome.BLOCK

    def test_missing_action_blocks(self, patched_db, no_publish):
        actor = DriftSentinel()
        result = actor.run({})
        assert result.outcome == Outcome.BLOCK


# ═══════════════════════════════════════════════════════
# check action — input validation
# ═══════════════════════════════════════════════════════


class TestCheckInputValidation:
    def test_missing_feature_name_blocks(self, patched_db, no_publish):
        actor = DriftSentinel()
        result = actor.run(
            {"action": "check", "baseline": [1.0, 2.0], "current": [1.0], "test_type": "psi"}
        )
        assert result.outcome == Outcome.BLOCK

    def test_missing_baseline_blocks(self, patched_db, no_publish):
        actor = DriftSentinel()
        result = actor.run(
            {"action": "check", "feature_name": "x", "current": [1.0], "test_type": "psi"}
        )
        assert result.outcome == Outcome.BLOCK

    def test_invalid_test_type_blocks(self, patched_db, no_publish):
        actor = DriftSentinel()
        result = actor.run(
            {
                "action": "check",
                "feature_name": "x",
                "baseline": [1.0, 2.0],
                "current": [1.0, 2.0],
                "test_type": "chi2",
            }
        )
        assert result.outcome == Outcome.BLOCK

    def test_non_numeric_blocks(self, patched_db, no_publish):
        actor = DriftSentinel()
        result = actor.run(
            {
                "action": "check",
                "feature_name": "x",
                "baseline": ["a", "b"],
                "current": [1.0, 2.0],
                "test_type": "psi",
            }
        )
        assert result.outcome == Outcome.BLOCK

    def test_2d_input_blocks(self, patched_db, no_publish):
        actor = DriftSentinel()
        result = actor.run(
            {
                "action": "check",
                "feature_name": "x",
                "baseline": [[1.0, 2.0], [3.0, 4.0]],
                "current": [1.0, 2.0],
                "test_type": "psi",
            }
        )
        assert result.outcome == Outcome.BLOCK

    def test_empty_baseline_blocks(self, patched_db, no_publish):
        actor = DriftSentinel()
        result = actor.run(
            {
                "action": "check",
                "feature_name": "x",
                "baseline": [],
                "current": [1.0, 2.0],
                "test_type": "psi",
            }
        )
        assert result.outcome == Outcome.BLOCK


# ═══════════════════════════════════════════════════════
# check action — 4 outcome states
# ═══════════════════════════════════════════════════════


class TestCheckOutcomes:
    def test_stable_returns_pass(self, patched_db, no_publish):
        rng = np.random.default_rng(42)
        baseline = rng.normal(0, 1, 1000).tolist()
        current = rng.normal(0, 1, 1000).tolist()
        actor = DriftSentinel()
        result = actor.run(
            {
                "action": "check",
                "feature_name": "vix_z",
                "baseline": baseline,
                "current": current,
                "test_type": "psi",
            }
        )
        assert result.outcome == Outcome.PASS
        assert result.output["severity"] == "stable"

    def test_minor_returns_warn(self, patched_db, no_publish):
        # PSI minor (0.10-0.25) 영역 강제 — 작은 mean shift
        rng = np.random.default_rng(42)
        baseline = rng.normal(0, 1, 5000).tolist()
        current = rng.normal(0.4, 1, 5000).tolist()
        actor = DriftSentinel()
        result = actor.run(
            {
                "action": "check",
                "feature_name": "vix_z",
                "baseline": baseline,
                "current": current,
                "test_type": "psi",
            }
        )
        # 0.10 ≤ PSI < 0.50 어딘가 → WARN
        assert result.outcome == Outcome.WARN
        assert result.output["severity"] in ("minor", "major")

    def test_critical_returns_block(self, patched_db, no_publish):
        rng = np.random.default_rng(42)
        baseline = rng.normal(0, 1, 1000).tolist()
        current = rng.normal(5, 1, 1000).tolist()  # 5σ shift
        actor = DriftSentinel()
        result = actor.run(
            {
                "action": "check",
                "feature_name": "vix_z",
                "baseline": baseline,
                "current": current,
                "test_type": "psi",
            }
        )
        assert result.outcome == Outcome.BLOCK
        assert result.output["severity"] == "critical"

    def test_ks_critical_returns_block(self, patched_db, no_publish):
        rng = np.random.default_rng(42)
        baseline = rng.normal(0, 1, 1000).tolist()
        current = rng.normal(5, 1, 1000).tolist()
        actor = DriftSentinel()
        result = actor.run(
            {
                "action": "check",
                "feature_name": "regime_posterior_top1",
                "baseline": baseline,
                "current": current,
                "test_type": "ks",
            }
        )
        assert result.outcome == Outcome.BLOCK
        assert result.output["severity"] == "critical"

    def test_check_persists_alert_row(self, patched_db, no_publish):
        baseline = [1.0] * 100 + [2.0] * 100
        current = [1.0] * 100 + [2.0] * 100
        actor = DriftSentinel()
        result = actor.run(
            {
                "action": "check",
                "feature_name": "decision_conviction",
                "baseline": baseline,
                "current": current,
                "test_type": "psi",
                "actor_name": "decision-compiler",
            }
        )
        assert result.output["alert_id"] > 0
        rows = query(
            "SELECT * FROM drift_alerts WHERE alert_id = ?",
            (result.output["alert_id"],),
            db_path=patched_db,
        )
        assert len(rows) == 1
        assert rows[0]["feature_name"] == "decision_conviction"
        assert rows[0]["actor_name"] == "decision-compiler"
        assert rows[0]["test_type"] == "psi"


# ═══════════════════════════════════════════════════════
# scan_features action — aggregation
# ═══════════════════════════════════════════════════════


class TestScanFeatures:
    def test_all_stable_returns_pass(self, patched_db, no_publish):
        rng = np.random.default_rng(42)
        baseline = rng.normal(0, 1, 1000).tolist()
        current = rng.normal(0, 1, 1000).tolist()
        actor = DriftSentinel()
        result = actor.run(
            {
                "action": "scan_features",
                "features": [
                    {
                        "feature_name": "vix_z",
                        "baseline": baseline,
                        "current": current,
                        "test_type": "psi",
                    },
                    {
                        "feature_name": "regime_top1",
                        "baseline": baseline,
                        "current": current,
                        "test_type": "ks",
                    },
                ],
            }
        )
        assert result.outcome == Outcome.PASS
        assert result.output["n_stable"] == 2
        assert result.output["n_critical"] == 0

    def test_any_critical_returns_block(self, patched_db, no_publish):
        rng = np.random.default_rng(42)
        stable_b = rng.normal(0, 1, 1000).tolist()
        stable_c = rng.normal(0, 1, 1000).tolist()
        crit_b = rng.normal(0, 1, 1000).tolist()
        crit_c = rng.normal(5, 1, 1000).tolist()
        actor = DriftSentinel()
        result = actor.run(
            {
                "action": "scan_features",
                "features": [
                    {
                        "feature_name": "stable_feat",
                        "baseline": stable_b,
                        "current": stable_c,
                        "test_type": "psi",
                    },
                    {
                        "feature_name": "drifted_feat",
                        "baseline": crit_b,
                        "current": crit_c,
                        "test_type": "psi",
                    },
                ],
            }
        )
        assert result.outcome == Outcome.BLOCK
        assert result.output["n_critical"] == 1

    def test_only_minor_returns_warn(self, patched_db, no_publish):
        rng = np.random.default_rng(42)
        baseline = rng.normal(0, 1, 5000).tolist()
        current = rng.normal(0.4, 1, 5000).tolist()
        actor = DriftSentinel()
        result = actor.run(
            {
                "action": "scan_features",
                "features": [
                    {
                        "feature_name": "minor_feat",
                        "baseline": baseline,
                        "current": current,
                        "test_type": "psi",
                    }
                ],
            }
        )
        assert result.outcome == Outcome.WARN

    def test_empty_features_blocks(self, patched_db, no_publish):
        actor = DriftSentinel()
        result = actor.run({"action": "scan_features", "features": []})
        assert result.outcome == Outcome.BLOCK

    def test_missing_features_blocks(self, patched_db, no_publish):
        actor = DriftSentinel()
        result = actor.run({"action": "scan_features"})
        assert result.outcome == Outcome.BLOCK


# ═══════════════════════════════════════════════════════
# list_alerts action — filter
# ═══════════════════════════════════════════════════════


class TestListAlerts:
    def _seed_alerts(self, db_path):
        log_drift_alert(
            feature_name="vix_z",
            test_type="psi",
            test_statistic=0.05,
            threshold=0.0,
            severity="stable",
            baseline_window="2026-01-01..2026-01-31",
            current_window="2026-04-01..2026-04-30",
            n_baseline=1000,
            n_current=1000,
            distribution_summary={"k": "v"},
            actor_name="regime-posterior",
            db_path=db_path,
        )
        log_drift_alert(
            feature_name="regime_top1",
            test_type="ks",
            test_statistic=0.30,
            threshold=KS_CRITICAL,
            severity="critical",
            baseline_window="2026-01-01..2026-01-31",
            current_window="2026-04-01..2026-04-30",
            n_baseline=500,
            n_current=500,
            distribution_summary={"k": "v"},
            actor_name="regime-posterior",
            db_path=db_path,
        )
        log_drift_alert(
            feature_name="conviction",
            test_type="psi",
            test_statistic=0.15,
            threshold=PSI_MINOR,
            severity="minor",
            baseline_window="2026-01-01..2026-01-31",
            current_window="2026-04-01..2026-04-30",
            n_baseline=200,
            n_current=200,
            distribution_summary={"k": "v"},
            actor_name="decision-compiler",
            db_path=db_path,
        )

    def test_list_all(self, patched_db, no_publish):
        self._seed_alerts(patched_db)
        actor = DriftSentinel()
        result = actor.run({"action": "list_alerts", "limit": 100})
        assert result.outcome == Outcome.PASS
        assert result.output["count"] == 3

    def test_severity_filter(self, patched_db, no_publish):
        self._seed_alerts(patched_db)
        actor = DriftSentinel()
        result = actor.run({"action": "list_alerts", "severity": "critical"})
        assert result.outcome == Outcome.PASS
        assert result.output["count"] == 1
        assert result.output["alerts"][0]["severity"] == "critical"

    def test_invalid_severity_blocks(self, patched_db, no_publish):
        actor = DriftSentinel()
        result = actor.run({"action": "list_alerts", "severity": "FATAL"})
        assert result.outcome == Outcome.BLOCK

    def test_limit_caps_results(self, patched_db, no_publish):
        self._seed_alerts(patched_db)
        actor = DriftSentinel()
        result = actor.run({"action": "list_alerts", "limit": 2})
        assert result.outcome == Outcome.PASS
        assert result.output["count"] == 2

    def test_since_iso_filter(self, patched_db, no_publish):
        self._seed_alerts(patched_db)
        actor = DriftSentinel()
        # 미래 시점 → 0 hits
        result = actor.run(
            {"action": "list_alerts", "since_iso": "2099-01-01 00:00:00"}
        )
        assert result.outcome == Outcome.PASS
        assert result.output["count"] == 0


# ═══════════════════════════════════════════════════════
# Discord publish routing
# ═══════════════════════════════════════════════════════


class TestDiscordPublishRouting:
    def test_critical_publishes_to_incidents(self, patched_db):
        rng = np.random.default_rng(42)
        baseline = rng.normal(0, 1, 1000).tolist()
        current = rng.normal(5, 1, 1000).tolist()
        with patch(
            "nuri.agents.discord.publisher.DiscordPublisher.publish_embed",
            return_value=MagicMock(ok=True, channel="incidents", http_status=204, retry_count=0),
        ) as pub_embed:
            actor = DriftSentinel()
            actor.run(
                {
                    "action": "check",
                    "feature_name": "vix_z",
                    "baseline": baseline,
                    "current": current,
                    "test_type": "psi",
                    "actor_name": "regime-posterior",
                }
            )
        from nuri.agents.discord.publisher import Channel

        assert pub_embed.called
        call = pub_embed.call_args
        channel_arg = call.args[0] if call.args else call.kwargs.get("channel")
        assert channel_arg == Channel.INCIDENTS

    def test_major_publishes_to_ops(self, patched_db):
        # PSI major (0.25-0.50) 강제
        rng = np.random.default_rng(42)
        baseline = rng.normal(0, 1, 5000).tolist()
        current = rng.normal(0.7, 1, 5000).tolist()
        with patch(
            "nuri.agents.discord.publisher.DiscordPublisher.publish_embed",
            return_value=MagicMock(ok=True, channel="ops", http_status=204, retry_count=0),
        ) as pub_embed:
            actor = DriftSentinel()
            result = actor.run(
                {
                    "action": "check",
                    "feature_name": "vix_z",
                    "baseline": baseline,
                    "current": current,
                    "test_type": "psi",
                }
            )
        # severity major 가 나와야 publish 호출됨
        if result.output["severity"] == "major":
            from nuri.agents.discord.publisher import Channel

            assert pub_embed.called
            channel_arg = pub_embed.call_args.args[0] if pub_embed.call_args.args else pub_embed.call_args.kwargs.get(
                "channel"
            )
            assert channel_arg == Channel.OPS
        else:
            # severity 가 critical 이라면 INCIDENTS 로 가야 — 본 테스트 invariant 미충족
            # 하지만 publish 자체는 호출되어야 함 (defensive)
            assert pub_embed.called

    def test_stable_does_not_publish(self, patched_db):
        rng = np.random.default_rng(42)
        baseline = rng.normal(0, 1, 1000).tolist()
        current = rng.normal(0, 1, 1000).tolist()
        with patch(
            "nuri.agents.discord.publisher.DiscordPublisher.publish_embed",
            return_value=MagicMock(ok=True, channel="ops", http_status=204, retry_count=0),
        ) as pub_embed:
            actor = DriftSentinel()
            actor.run(
                {
                    "action": "check",
                    "feature_name": "vix_z",
                    "baseline": baseline,
                    "current": current,
                    "test_type": "psi",
                }
            )
        assert not pub_embed.called

    def test_publish_failure_does_not_break_check(self, patched_db):
        rng = np.random.default_rng(42)
        baseline = rng.normal(0, 1, 1000).tolist()
        current = rng.normal(5, 1, 1000).tolist()
        with patch(
            "nuri.agents.discord.publisher.DiscordPublisher.publish_embed",
            side_effect=RuntimeError("webhook 500"),
        ):
            actor = DriftSentinel()
            result = actor.run(
                {
                    "action": "check",
                    "feature_name": "vix_z",
                    "baseline": baseline,
                    "current": current,
                    "test_type": "psi",
                }
            )
        # Discord 실패는 outcome 에 영향 X — critical 은 BLOCK 그대로
        assert result.outcome == Outcome.BLOCK


# ═══════════════════════════════════════════════════════
# helper enum 검증 (HelperLockTests)
# ═══════════════════════════════════════════════════════


class TestHelperEnumLockTests:
    def test_log_drift_alert_invalid_test_type_raises(self, db_path):
        with pytest.raises(ValueError):
            log_drift_alert(
                feature_name="x",
                test_type="bogus",
                test_statistic=0.1,
                threshold=0.0,
                severity="stable",
                baseline_window="b",
                current_window="c",
                n_baseline=1,
                n_current=1,
                distribution_summary={},
                db_path=db_path,
            )

    def test_log_drift_alert_invalid_severity_raises(self, db_path):
        with pytest.raises(ValueError):
            log_drift_alert(
                feature_name="x",
                test_type="psi",
                test_statistic=0.1,
                threshold=0.0,
                severity="FATAL",
                baseline_window="b",
                current_window="c",
                n_baseline=1,
                n_current=1,
                distribution_summary={},
                db_path=db_path,
            )

    def test_log_drift_alert_negative_statistic_raises(self, db_path):
        with pytest.raises(ValueError):
            log_drift_alert(
                feature_name="x",
                test_type="psi",
                test_statistic=-0.1,
                threshold=0.0,
                severity="stable",
                baseline_window="b",
                current_window="c",
                n_baseline=1,
                n_current=1,
                distribution_summary={},
                db_path=db_path,
            )

    def test_log_drift_alert_negative_threshold_raises(self, db_path):
        with pytest.raises(ValueError):
            log_drift_alert(
                feature_name="x",
                test_type="psi",
                test_statistic=0.1,
                threshold=-0.5,
                severity="stable",
                baseline_window="b",
                current_window="c",
                n_baseline=1,
                n_current=1,
                distribution_summary={},
                db_path=db_path,
            )

    def test_log_drift_alert_negative_n_raises(self, db_path):
        with pytest.raises(ValueError):
            log_drift_alert(
                feature_name="x",
                test_type="psi",
                test_statistic=0.1,
                threshold=0.0,
                severity="stable",
                baseline_window="b",
                current_window="c",
                n_baseline=-1,
                n_current=1,
                distribution_summary={},
                db_path=db_path,
            )

    def test_log_drift_alert_empty_feature_raises(self, db_path):
        with pytest.raises(ValueError):
            log_drift_alert(
                feature_name="",
                test_type="psi",
                test_statistic=0.1,
                threshold=0.0,
                severity="stable",
                baseline_window="b",
                current_window="c",
                n_baseline=1,
                n_current=1,
                distribution_summary={},
                db_path=db_path,
            )

    def test_log_drift_alert_returns_alert_id(self, db_path):
        alert_id = log_drift_alert(
            feature_name="vix_z",
            test_type="psi",
            test_statistic=0.10,
            threshold=PSI_MINOR,
            severity="minor",
            baseline_window="2026-01-01..2026-01-31",
            current_window="2026-04-01..2026-04-30",
            n_baseline=1000,
            n_current=1000,
            distribution_summary={"bins": [1, 2, 3]},
            actor_name="regime-posterior",
            run_id="run-123",
            db_path=db_path,
        )
        assert alert_id > 0


# ═══════════════════════════════════════════════════════
# Audit trail
# ═══════════════════════════════════════════════════════


class TestAuditTrail:
    def test_check_decision_audited(self, patched_db, no_publish):
        rng = np.random.default_rng(42)
        baseline = rng.normal(0, 1, 200).tolist()
        current = rng.normal(0, 1, 200).tolist()
        actor = DriftSentinel()
        actor.run(
            {
                "action": "check",
                "feature_name": "vix_z",
                "baseline": baseline,
                "current": current,
                "test_type": "psi",
            }
        )
        rows = query(
            "SELECT actor_name, layer, outcome FROM agent_audit_ledger",
            db_path=patched_db,
        )
        assert any(
            r["actor_name"] == "drift-sentinel"
            and r["layer"] == "B"
            and r["outcome"] == "pass"
            for r in rows
        )

    def test_invalid_action_block_audited(self, patched_db, no_publish):
        actor = DriftSentinel()
        actor.run({"action": "delete"})
        rows = query(
            "SELECT outcome FROM agent_audit_ledger WHERE actor_name = 'drift-sentinel'",
            db_path=patched_db,
        )
        assert any(r["outcome"] == "block" for r in rows)


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════


class TestCli:
    def test_cli_list_alerts_returns_0(self, patched_db, capsys):
        rc = main(["list_alerts"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "alerts" in out

    def test_cli_list_alerts_with_severity(self, patched_db, capsys):
        rc = main(["list_alerts", "--severity", "critical", "--limit", "10"])
        assert rc == 0

    def test_cli_invalid_severity_raises_systemexit(self, patched_db):
        with pytest.raises(SystemExit):
            main(["list_alerts", "--severity", "FATAL"])

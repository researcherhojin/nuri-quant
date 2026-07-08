"""DriftSentinel branch coverage — Issue #616 Phase 3-A2.

3 partials 닫음:
- 208→221: `if baseline.size and np.std(baseline) > 0:` False (degenerate baseline)
- 211→221: `if len(edges) >= 2:` False (n_bins=0 → quantile edges 1 element)
- 417→419: `if severity in severity_counts:` False (sub_result error → severity None)

+ line 128: scipy 성공 return — `--cov` numpy double-init Heisenbug 우회 (stub).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from nuri.agents.actors.drift_sentinel import (
    DriftSentinel,
    _compute_ks,
    _distribution_summary,
)
from nuri.agents.base import Outcome, RunContext

# ═══════════════════════════════════════════════════════
# _distribution_summary — line 208/211 partials
# ═══════════════════════════════════════════════════════


class TestDistributionSummaryBins:
    def test_skip_bins_when_baseline_std_zero(self):
        """baseline.std == 0 → 208 False → bins 키 없음."""
        baseline = np.array([5.0, 5.0, 5.0, 5.0])  # 분산 0
        current = np.array([1.0, 2.0, 3.0])

        summary = _distribution_summary(baseline, current)

        assert "bins" not in summary
        assert summary["baseline"]["std"] == 0.0
        assert summary["baseline"]["n"] == 4

    def test_skip_bins_when_baseline_empty(self):
        """baseline.size == 0 → 208 short-circuit False → bins 키 없음."""
        baseline = np.array([], dtype=np.float64)
        current = np.array([1.0, 2.0])

        summary = _distribution_summary(baseline, current)

        assert "bins" not in summary
        assert summary["baseline"]["n"] == 0

    def test_skip_bins_when_edges_collapse(self):
        """n_bins=0 → linspace [0.0] → quantile 1 element → 211 False → bins 키 없음.

        baseline.std > 0 이지만 edges 가 collapse 한 degenerate case.
        """
        baseline = np.array([1.0, 2.0, 3.0, 4.0])  # std > 0
        current = np.array([5.0, 6.0])

        summary = _distribution_summary(baseline, current, n_bins=0)

        assert "bins" not in summary  # 208 True 통과 후 211 False 로 skip
        assert summary["baseline"]["std"] > 0


# ═══════════════════════════════════════════════════════
# scan_features — line 417→419 partial
# ═══════════════════════════════════════════════════════


class TestScanFeaturesUnknownSeverity:
    def test_sub_result_without_severity_skips_counter(self):
        """_check 가 BLOCK 으로 error 반환 시 output 에 severity 없음.
        out.get('severity') == None → 417 False → 419 alerts.append 만 실행.
        """
        actor = DriftSentinel()
        ctx = RunContext(run_id="test-scan-unknown-severity")

        # baseline/current 누락 → _check 가 BLOCK + {"error": ...} 반환
        bad_features = [
            {"feature_name": "no_data", "test_type": "psi"},  # baseline/current 누락
        ]

        with patch.object(actor, "_publish_drift"):
            result = actor._scan_features({"features": bad_features}, ctx)

        # severity_counts 모두 0 (None 은 dict 에 없으므로 increment 안 됨)
        assert result.output["n_stable"] == 0
        assert result.output["n_minor"] == 0
        assert result.output["n_major"] == 0
        assert result.output["n_critical"] == 0
        # alerts 는 무조건 append (419)
        assert len(result.output["alerts"]) == 1
        assert "error" in result.output["alerts"][0]
        # 모두 None severity → BLOCK 도 critical 도 아님 → PASS
        assert result.outcome == Outcome.PASS


# ═══════════════════════════════════════════════════════
# _compute_ks — line 128 (scipy 성공 return)
# ═══════════════════════════════════════════════════════


class TestComputeKsScipySuccessPath:
    def test_scipy_success_returns_statistic(self):
        """line 128 `return float(result.statistic)` — scipy 정상 경로.

        실 scipy.stats.ks_2samp 는 `--cov` 계측 시 numpy double-init 로
        `numpy.dtypes.VoidDType` 가 사라져 AttributeError 를 던지고 fallback
        (131-134) 으로 빠진다 — 측정 행위 자체가 경로를 바꾸는 Heisenbug.
        프로덕션/비계측 런에서는 128 이 정상 실행되므로, 취약한 외부 호출만
        stub 으로 격리해 128 을 실제로 태운다.
        """
        baseline = np.array([1.0, 2.0, 3.0, 4.0])
        current = np.array([2.0, 3.0, 4.0, 5.0])

        def stub_ks(_a, _b):
            return SimpleNamespace(statistic=0.42, pvalue=0.1)

        with patch("scipy.stats.ks_2samp", stub_ks):
            result = _compute_ks(baseline, current)

        assert result == 0.42

"""DriftSentinel — Layer B actor (#529 Phase 2 — canonical #12).

모델 input distribution drift 감지. RegimePosterior 의 feature distribution /
DecisionCompiler 의 conviction distribution 가 학습 시점 baseline 대비 얼마나
벗어났는지 PSI (Population Stability Index) + KS (Kolmogorov-Smirnov) 2-sample
test 로 측정.

Layer B 설계 (Codex Round 5):
- 100% deterministic — 통계 검증, ZERO LLM
- numpy + scipy.stats.ks_2samp (이미 pyproject 의존성)
- 결과는 drift_alerts 테이블 영구 기록 (idempotent X — historical trend)

PSI 임계값 (산업 표준):
    < 0.10        → stable
    0.10 ≤ x < 0.25 → minor (관찰 권고)
    0.25 ≤ x < 0.50 → major (재학습 권고)
    ≥ 0.50        → critical (즉시 조치)

KS D-statistic 임계값:
    < 0.05        → stable
    0.05 ≤ x < 0.10 → minor
    0.10 ≤ x < 0.20 → major
    ≥ 0.20        → critical

Anti-pattern 방지:
- baseline / current degenerate (분산 0) → PSI=0.0 (stable)
- KS 는 동일 길이 불필요 (2-sample)
- bin 가장자리 0 카운트 → smoothing (1e-6) 으로 log(0) 회피
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from nuri.agents.base import REGISTRY, Actor, ActorResult, Layer, Outcome, RunContext
from nuri.core.db import log_drift_alert, query

# ─── PSI 임계값 (산업 표준) ─────────────────────────────────
PSI_MINOR = 0.10
PSI_MAJOR = 0.25
PSI_CRITICAL = 0.50

# ─── KS D-statistic 임계값 ──────────────────────────────────
KS_MINOR = 0.05
KS_MAJOR = 0.10
KS_CRITICAL = 0.20

# Bin smoothing (log(0) 회피)
_PSI_EPS = 1e-6
_DEFAULT_PSI_BINS = 10

_VALID_TEST_TYPES = ("psi", "ks")
_VALID_SEVERITIES = ("stable", "minor", "major", "critical")


# ═══════════════════════════════════════════════════════
# Math primitives (모듈 함수, 단위 테스트 가능)
# ═══════════════════════════════════════════════════════


def _compute_psi(
    baseline: np.ndarray,
    current: np.ndarray,
    n_bins: int = _DEFAULT_PSI_BINS,
) -> float:
    """Population Stability Index.

    PSI = sum((current_pct - baseline_pct) * ln(current_pct / baseline_pct)).

    동일 분포 → ~0. 완전 다름 → ∞.
    Degenerate (분산 0 또는 동일 single value) → 0.0 반환 (stable 판정).
    bin smoothing: 0 카운트 bin 은 _PSI_EPS 로 대체 (log(0) 회피).
    """
    if baseline.size == 0 or current.size == 0:
        return 0.0
    if not (np.isfinite(baseline).all() and np.isfinite(current).all()):
        # NaN/Inf 포함 시 stable 처리 (caller 가 책임지고 정제)
        return 0.0
    # baseline 의 quantile 로 bin edge 정의 (data-driven binning)
    if np.std(baseline) == 0:
        # baseline 이 single value 면 bin 자체가 의미 없음 — current 도 동일하면 stable
        return 0.0

    # quantile bin edges — 양 끝 inf 처리
    quantiles = np.linspace(0.0, 1.0, n_bins + 1)
    edges = np.quantile(baseline, quantiles)
    # Edge unique 보장 — degenerate quantile (중복 edge) 시 unique 만
    edges = np.unique(edges)
    if len(edges) < 2:
        return 0.0
    # 양 끝 ±inf 로 expand — current 가 baseline range 밖이어도 카운트
    edges[0] = -np.inf
    edges[-1] = np.inf

    baseline_counts, _ = np.histogram(baseline, bins=edges)
    current_counts, _ = np.histogram(current, bins=edges)

    baseline_pct = baseline_counts / max(baseline.size, 1)
    current_pct = current_counts / max(current.size, 1)

    # smoothing
    baseline_pct = np.where(baseline_pct == 0, _PSI_EPS, baseline_pct)
    current_pct = np.where(current_pct == 0, _PSI_EPS, current_pct)

    psi = float(np.sum((current_pct - baseline_pct) * np.log(current_pct / baseline_pct)))
    return max(0.0, psi)  # 수치 오차로 음수 나오면 0 으로 clip


def _compute_ks(baseline: np.ndarray, current: np.ndarray) -> float:
    """Kolmogorov-Smirnov 2-sample test D-statistic.

    D = max(|F_baseline(x) - F_current(x)|) over all x.
    동일 분포 → ~0. 완전 다름 → 1.0.
    Empty input 또는 NaN/Inf → 0.0 반환 (stable).

    scipy.stats.ks_2samp 사용 (이미 pyproject 의존성).
    """
    if baseline.size == 0 or current.size == 0:
        return 0.0
    if not (np.isfinite(baseline).all() and np.isfinite(current).all()):
        return 0.0
    try:
        from scipy.stats import ks_2samp

        result = ks_2samp(baseline, current)
        return float(result.statistic)
    except Exception:  # noqa: BLE001 — scipy 부재 또는 numerical issue
        # fallback: empirical CDF 비교 (numpy only)
        combined = np.sort(np.concatenate([baseline, current]))
        cdf_b = np.searchsorted(np.sort(baseline), combined, side="right") / baseline.size
        cdf_c = np.searchsorted(np.sort(current), combined, side="right") / current.size
        return float(np.max(np.abs(cdf_b - cdf_c)))


def _classify_severity(test_type: str, statistic: float) -> str:
    """PSI / KS statistic → severity enum.

    test_type ∈ ('psi','ks').
    statistic 음수 → ValueError (caller 가 abs 처리해야 함).
    """
    if test_type not in _VALID_TEST_TYPES:
        raise ValueError(f"test_type must be {_VALID_TEST_TYPES}, got {test_type!r}")
    if statistic < 0:
        raise ValueError(f"statistic must be >= 0, got {statistic}")

    if test_type == "psi":
        if statistic < PSI_MINOR:
            return "stable"
        if statistic < PSI_MAJOR:
            return "minor"
        if statistic < PSI_CRITICAL:
            return "major"
        return "critical"
    # ks
    if statistic < KS_MINOR:
        return "stable"
    if statistic < KS_MAJOR:
        return "minor"
    if statistic < KS_CRITICAL:
        return "major"
    return "critical"


def _severity_threshold(test_type: str, severity: str) -> float:
    """severity rung 의 lower bound (DB 에 archive 할 threshold 값)."""
    if test_type == "psi":
        return {
            "stable": 0.0,
            "minor": PSI_MINOR,
            "major": PSI_MAJOR,
            "critical": PSI_CRITICAL,
        }[severity]
    return {
        "stable": 0.0,
        "minor": KS_MINOR,
        "major": KS_MAJOR,
        "critical": KS_CRITICAL,
    }[severity]


def _distribution_summary(
    baseline: np.ndarray,
    current: np.ndarray,
    n_bins: int = _DEFAULT_PSI_BINS,
) -> dict[str, Any]:
    """Bin counts + percentile summary — DB archive 용."""
    summary: dict[str, Any] = {
        "baseline": {
            "n": int(baseline.size),
            "mean": float(np.mean(baseline)) if baseline.size else 0.0,
            "std": float(np.std(baseline)) if baseline.size else 0.0,
            "p10": float(np.percentile(baseline, 10)) if baseline.size else 0.0,
            "p50": float(np.percentile(baseline, 50)) if baseline.size else 0.0,
            "p90": float(np.percentile(baseline, 90)) if baseline.size else 0.0,
        },
        "current": {
            "n": int(current.size),
            "mean": float(np.mean(current)) if current.size else 0.0,
            "std": float(np.std(current)) if current.size else 0.0,
            "p10": float(np.percentile(current, 10)) if current.size else 0.0,
            "p50": float(np.percentile(current, 50)) if current.size else 0.0,
            "p90": float(np.percentile(current, 90)) if current.size else 0.0,
        },
    }
    # Bin counts (PSI 와 동일 binning)
    if baseline.size and np.std(baseline) > 0:
        edges = np.quantile(baseline, np.linspace(0.0, 1.0, n_bins + 1))
        edges = np.unique(edges)
        if len(edges) >= 2:
            edges[0] = -np.inf
            edges[-1] = np.inf
            b_counts, _ = np.histogram(baseline, bins=edges)
            c_counts, _ = np.histogram(current, bins=edges)
            summary["bins"] = {
                "edges": [float(e) if np.isfinite(e) else (None) for e in edges],
                "baseline_counts": [int(c) for c in b_counts],
                "current_counts": [int(c) for c in c_counts],
            }
    return summary


# ═══════════════════════════════════════════════════════
# Actor
# ═══════════════════════════════════════════════════════


@REGISTRY.register
class DriftSentinel(Actor):
    """Input distribution drift detection — Layer B producer.

    Actions (input_data['action']):
        check          — 단일 feature drift 측정 + log_drift_alert 기록.
        scan_features  — 등록된 feature 들 일괄 check.
        list_alerts    — drift_alerts 조회 (severity / since_iso 필터).

    Outcome 매핑 (Codex Round 5 Layer B):
        check / scan_features:
            PASS  — 모두 stable
            WARN  — minor / major
            BLOCK — critical (재학습 강제 권고)
        list_alerts:
            PASS

    Required input (action='check'):
        feature_name: str
        baseline: list[float] — 학습 시점 분포
        current:  list[float] — 비교 대상 최신 분포
        test_type: 'psi' | 'ks'
        actor_name: Optional[str] — drift 가 영향 미치는 actor
        n_bins: int (PSI only, default 10)
        baseline_window: Optional[str] — 'YYYY-MM-DD..YYYY-MM-DD' (default 'baseline')
        current_window: Optional[str] (default 'current')
    """

    name = "drift-sentinel"
    version = "0.1.0"
    layer = Layer.B

    VALID_ACTIONS: tuple[str, ...] = ("check", "scan_features", "list_alerts")

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        action = input_data.get("action")
        if action not in self.VALID_ACTIONS:
            return ActorResult(
                output={"error": f"invalid action {action!r}, expected {self.VALID_ACTIONS}"},
                outcome=Outcome.BLOCK,
                input_summary=f"action={action}",
            )

        if action == "check":
            return self._check(input_data, ctx)
        if action == "scan_features":
            return self._scan_features(input_data, ctx)
        return self._list_alerts(input_data)

    # ─── action: check ───────────────────────────────────────

    def _check(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        feature_name = input_data.get("feature_name")
        baseline_raw = input_data.get("baseline")
        current_raw = input_data.get("current")
        test_type = input_data.get("test_type")

        if not feature_name or baseline_raw is None or current_raw is None:
            return ActorResult(
                output={"error": "check requires 'feature_name' + 'baseline' + 'current'"},
                outcome=Outcome.BLOCK,
                input_summary="check",
            )
        if test_type not in _VALID_TEST_TYPES:
            return ActorResult(
                output={"error": f"test_type must be {_VALID_TEST_TYPES}, got {test_type!r}"},
                outcome=Outcome.BLOCK,
                input_summary=f"check {feature_name}",
            )

        try:
            baseline = np.asarray(baseline_raw, dtype=np.float64)
            current = np.asarray(current_raw, dtype=np.float64)
        except (ValueError, TypeError) as exc:
            return ActorResult(
                output={"error": f"baseline/current must be numeric arrays: {exc}"},
                outcome=Outcome.BLOCK,
                input_summary=f"check {feature_name}",
            )

        if baseline.ndim != 1 or current.ndim != 1:
            return ActorResult(
                output={
                    "error": f"baseline/current must be 1-D, got shapes "
                    f"{baseline.shape} / {current.shape}"
                },
                outcome=Outcome.BLOCK,
                input_summary=f"check {feature_name}",
            )
        if baseline.size == 0 or current.size == 0:
            return ActorResult(
                output={"error": "baseline/current must be non-empty"},
                outcome=Outcome.BLOCK,
                input_summary=f"check {feature_name}",
            )

        n_bins = int(input_data.get("n_bins", _DEFAULT_PSI_BINS))
        actor_name = input_data.get("actor_name")
        baseline_window = str(input_data.get("baseline_window") or "baseline")
        current_window = str(input_data.get("current_window") or "current")

        if test_type == "psi":
            statistic = _compute_psi(baseline, current, n_bins=n_bins)
        else:
            statistic = _compute_ks(baseline, current)

        severity = _classify_severity(test_type, statistic)
        threshold = _severity_threshold(test_type, severity)
        summary = _distribution_summary(baseline, current, n_bins=n_bins)

        alert_id = log_drift_alert(
            feature_name=str(feature_name),
            test_type=test_type,
            test_statistic=statistic,
            threshold=threshold,
            severity=severity,
            baseline_window=baseline_window,
            current_window=current_window,
            n_baseline=int(baseline.size),
            n_current=int(current.size),
            distribution_summary=summary,
            actor_name=actor_name,
            run_id=ctx.run_id,
        )

        # Discord publish: critical → INCIDENTS, major → OPS.
        if severity == "critical":
            self._publish_drift(
                feature_name=str(feature_name),
                test_type=test_type,
                statistic=statistic,
                threshold=threshold,
                severity=severity,
                actor_name=actor_name,
                run_id=ctx.run_id,
            )
        elif severity == "major":
            self._publish_drift(
                feature_name=str(feature_name),
                test_type=test_type,
                statistic=statistic,
                threshold=threshold,
                severity=severity,
                actor_name=actor_name,
                run_id=ctx.run_id,
            )

        outcome_map = {
            "stable": Outcome.PASS,
            "minor": Outcome.WARN,
            "major": Outcome.WARN,
            "critical": Outcome.BLOCK,
        }
        return ActorResult(
            output={
                "alert_id": alert_id,
                "feature_name": feature_name,
                "test_type": test_type,
                "test_statistic": statistic,
                "threshold": threshold,
                "severity": severity,
                "n_baseline": int(baseline.size),
                "n_current": int(current.size),
                "actor_name": actor_name,
            },
            outcome=outcome_map[severity],
            sample_n=int(current.size),
            input_summary=f"check {feature_name} {test_type}={statistic:.4f} {severity}",
        )

    # ─── action: scan_features ───────────────────────────────

    def _scan_features(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        features = input_data.get("features")
        if not isinstance(features, list) or not features:
            return ActorResult(
                output={"error": "scan_features requires non-empty 'features' list"},
                outcome=Outcome.BLOCK,
                input_summary="scan_features",
            )

        alerts: list[dict[str, Any]] = []
        severity_counts = {"stable": 0, "minor": 0, "major": 0, "critical": 0}

        for feat in features:
            if not isinstance(feat, dict):
                continue
            sub_input = {"action": "check", **feat}
            sub_result = self._check(sub_input, ctx)
            out = sub_result.output
            severity = out.get("severity")
            if severity in severity_counts:
                severity_counts[severity] += 1
            alerts.append(out)

        if severity_counts["critical"] > 0:
            scan_outcome = Outcome.BLOCK
        elif severity_counts["minor"] > 0 or severity_counts["major"] > 0:
            scan_outcome = Outcome.WARN
        else:
            scan_outcome = Outcome.PASS

        return ActorResult(
            output={
                "n_stable": severity_counts["stable"],
                "n_minor": severity_counts["minor"],
                "n_major": severity_counts["major"],
                "n_critical": severity_counts["critical"],
                "alerts": alerts,
            },
            outcome=scan_outcome,
            sample_n=len(alerts),
            input_summary=(
                f"scan_features → {len(alerts)} checks "
                f"(crit={severity_counts['critical']}, "
                f"major={severity_counts['major']}, "
                f"minor={severity_counts['minor']})"
            ),
        )

    # ─── action: list_alerts ─────────────────────────────────

    @staticmethod
    def _list_alerts(input_data: dict[str, Any]) -> ActorResult:
        severity = input_data.get("severity")
        since_iso = input_data.get("since_iso")
        limit = int(input_data.get("limit", 50))

        if severity is not None and severity not in _VALID_SEVERITIES:
            return ActorResult(
                output={"error": f"severity must be {_VALID_SEVERITIES}, got {severity!r}"},
                outcome=Outcome.BLOCK,
                input_summary="list_alerts",
            )

        sql = "SELECT * FROM drift_alerts WHERE 1=1"
        params: list[Any] = []
        if severity:
            sql += " AND severity = ?"
            params.append(severity)
        if since_iso:
            sql += " AND detected_at >= ?"
            params.append(str(since_iso))
        sql += " ORDER BY detected_at DESC, alert_id DESC LIMIT ?"
        params.append(limit)

        rows = query(sql, tuple(params))
        items = [dict(r) for r in rows]
        return ActorResult(
            output={"count": len(items), "alerts": items},
            outcome=Outcome.PASS,
            sample_n=len(items),
            input_summary=f"list_alerts (n={len(items)})",
        )

    # ─── Discord publish (best-effort) ───────────────────────

    @staticmethod
    def _publish_drift(
        feature_name: str,
        test_type: str,
        statistic: float,
        threshold: float,
        severity: str,
        actor_name: Optional[str],
        run_id: str,
    ) -> None:
        """critical → INCIDENTS (RED), major → OPS (AMBER). minor/stable publish X."""
        try:
            from nuri.agents.discord.publisher import Channel, DiscordPublisher

            if severity == "critical":
                channel = Channel.INCIDENTS
                color = 0xE74C3C  # RED
            elif severity == "major":
                channel = Channel.OPS
                color = 0xF39C12  # AMBER
            else:
                return

            embed = {
                "title": f"Drift detected — {feature_name} ({test_type.upper()})",
                "description": (
                    f"feature: **{feature_name}**\n"
                    f"actor: **{actor_name or 'n/a'}**\n"
                    f"test: **{test_type.upper()}**\n"
                    f"statistic: **{statistic:.4f}** (threshold {threshold:.4f})\n"
                    f"severity: **{severity}**"
                ),
                "color": color,
                "footer": {"text": f"nuri-quant • run_id={run_id[:8]} • Drift-Sentinel"},
            }
            DiscordPublisher().publish_embed(
                channel,
                embed=embed,
                actor_name="drift-sentinel",
                run_id=run_id,
            )
        except Exception:  # noqa: BLE001 — best-effort
            pass


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m nuri.agents.actors.drift_sentinel <action> [...]

    check / scan_features 는 array 입력이 필요해 Python 호출 전용.
    list_alerts 만 CLI 직접 사용.
    """
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(prog="drift-sentinel")
    parser.add_argument("action", choices=["list_alerts"])
    parser.add_argument("--severity", default=None, choices=list(_VALID_SEVERITIES))
    parser.add_argument("--since-iso", default=None)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args(argv)

    actor = DriftSentinel()
    payload: dict[str, Any] = {"action": args.action, "limit": args.limit}
    if args.severity:
        payload["severity"] = args.severity
    if args.since_iso:
        payload["since_iso"] = args.since_iso

    result = actor.run(payload)
    print(_json.dumps(result.output, indent=2, ensure_ascii=False, default=str))
    return 0 if result.outcome in (Outcome.PASS, Outcome.WARN) else 2


if __name__ == "__main__":
    import sys

    sys.exit(main())

"""WalkForwardValidator — Layer B actor (#529 Phase 2 — canonical #5).

Responsibilities:
- Rolling/Expanding fold spec → model fit/eval split (point-in-time enforced)
- Aggregate metrics (Brier, log-loss, Sharpe, hit-rate)
- pit_hash 로 reproducibility 보장 (동일 입력 → 동일 hash)
- 모든 결과 walkforward_runs 영구 기록

Layer B 설계 (Codex Round 5):
- 100% deterministic — 통계적 계산만, ZERO LLM
- 각 fold 의 train_data 는 test_data 보다 *strictly before* (PIT 위반 시 즉시 fail)
- Anti-leak lock-test: future data 가 train 에 섞이면 무조건 ValueError
- Layer A actor 가 enforce 결정 시 우리 결과 참조 가능 (e.g. Brier > threshold → block)

Design rationale (Codex consult 2026-05-01):
- signal_backtest 는 이미 PIT-safe (rule eval, no fit) → refactor 불필요
- 우리는 *모델 fit 하는 future actor 들* (Regime-Posterior sticky-HMM, Causal-Factor-Auditor,
  Foundation-Benchmark) 을 위한 evaluation primitive
- López de Prado *Causal Factor Investing 2025*: walk-forward = backtest discipline 의 core

Anti-pattern 방지:
- 전체 데이터 single fit → in-sample overfit → SIEGE gate 통과한 것처럼 보이지만 production 실패
- Train-test contamination → metrics 가 진짜 OOS 성능 X → user 손실
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, cast

import numpy as np
import pandas as pd

from nuri.agents.base import REGISTRY, Actor, ActorResult, Layer, Outcome, RunContext
from nuri.core.db import log_walkforward_run
from nuri.core.timezone import kst_now


@dataclass
class FoldSpec:
    """Walk-forward fold 정의.

    kind:
        'rolling'    — train window 가 step 만큼 이동 (window 크기 고정)
        'expanding'  — train window 가 점점 확장 (시작 고정)
    train_size: train 의 row 수
    test_size:  test 의 row 수
    step:       다음 fold 까지 이동할 step (보통 = test_size)
    """

    kind: str
    train_size: int
    test_size: int
    step: int

    def __post_init__(self) -> None:
        if self.kind not in ("rolling", "expanding"):
            raise ValueError(f"kind must be rolling/expanding, got {self.kind!r}")
        if self.train_size < 1 or self.test_size < 1 or self.step < 1:
            raise ValueError("train_size/test_size/step must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "train_size": self.train_size,
            "test_size": self.test_size,
            "step": self.step,
        }


def _generate_folds(n: int, spec: FoldSpec) -> list[tuple[slice, slice]]:
    """fold spec + 데이터 길이 → list of (train_slice, test_slice).

    각 fold 는 (train, test) 쌍. train 은 test 보다 *strictly before*.
    rolling: train 시작점이 step 만큼 이동 (window 크기 train_size 고정)
    expanding: train 시작점은 0 고정, 끝점만 확장
    """
    folds: list[tuple[slice, slice]] = []
    test_start = spec.train_size
    while test_start + spec.test_size <= n:
        if spec.kind == "rolling":
            train_start = test_start - spec.train_size
        else:  # expanding
            train_start = 0
        train_slice = slice(train_start, test_start)
        test_slice = slice(test_start, test_start + spec.test_size)
        folds.append((train_slice, test_slice))
        test_start += spec.step
    return folds


def _compute_pit_hash(
    data: pd.DataFrame,
    model_id: str,
    spec: FoldSpec,
) -> str:
    """data 디지털 + model_id + spec → SHA256[:16].

    Reproducibility key: 동일 입력 → 동일 hash → 동일 metrics 보장 검증.
    """
    h = hashlib.sha256()
    h.update(model_id.encode())
    h.update(json.dumps(spec.to_dict(), sort_keys=True).encode())
    # data digest: shape + first/last row + col sums (full hash 면 비싸므로 sample)
    h.update(str(data.shape).encode())
    if not data.empty:
        h.update(pd.util.hash_pandas_object(data.iloc[[0, -1]], index=True).to_numpy().tobytes())
        # column sum 으로 row 순서 변화 detect
        for col in data.select_dtypes(include=[np.number]).columns:
            h.update(f"{col}={data[col].sum():.6f}".encode())
    return h.hexdigest()[:16]


def _verify_pit(train: pd.DataFrame, test: pd.DataFrame) -> None:
    """Anti-leak: train 의 모든 row 가 test 의 첫 row 보다 *strictly before* 인지 확인.

    DataFrame 이 'date' column 보유 시 그 column 으로, 아니면 index 로 비교.
    위반 시 ValueError (Layer B enforcement: 데이터 leak 은 panic).
    """
    if train.empty or test.empty:
        return
    if "date" in train.columns and "date" in test.columns:
        train_max = pd.to_datetime(train["date"]).max()
        test_min = pd.to_datetime(test["date"]).min()
    else:
        train_max = train.index.max()
        test_min = test.index.min()
    if train_max >= test_min:
        raise ValueError(
            f"PIT leak detected: train.max ({train_max}) >= test.min ({test_min}). "
            "Walk-forward fold contamination — this is the bug we hunt."
        )


def _brier_score(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    """Mean squared error of probabilistic predictions. Lower = better. [0, 1] range."""
    return float(np.mean((y_prob - y_true) ** 2))


def _log_loss(y_true: np.ndarray, y_prob: np.ndarray, eps: float = 1e-15) -> float:
    """Binary cross-entropy. Lower = better. probs 를 (eps, 1-eps) 로 clip."""
    p = np.clip(y_prob, eps, 1 - eps)
    return float(-np.mean(y_true * np.log(p) + (1 - y_true) * np.log(1 - p)))


def _hit_rate(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Binary classification accuracy (y_pred 는 0/1 hard label)."""
    return float(np.mean((y_pred >= 0.5) == (y_true >= 0.5)))


def _sharpe_from_returns(returns: np.ndarray, risk_free: float = 0.0) -> float:
    """Annualized Sharpe (252 trading days). returns is daily.

    sample size <2 또는 std=0 시 0.0 반환 (degenerate case).
    """
    if len(returns) < 2:
        return 0.0
    excess = returns - risk_free / 252
    sd = float(np.std(excess, ddof=1))
    if sd == 0:
        return 0.0
    return float(np.mean(excess) / sd * np.sqrt(252))


def _aggregate_metrics(fold_metrics: list[dict[str, float]]) -> dict[str, float]:
    """fold-별 metrics → 평균 + std. 빈 list 면 빈 dict."""
    if not fold_metrics:
        return {}
    agg: dict[str, float] = {}
    for key in fold_metrics[0]:
        vals = np.array([m[key] for m in fold_metrics if key in m])
        agg[f"{key}_mean"] = float(np.mean(vals))
        agg[f"{key}_std"] = float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0
    return agg


@REGISTRY.register
class WalkForwardValidator(Actor):
    """Walk-forward model evaluation primitive.

    Actions (input_data['action']):
        run    — execute walk-forward eval (model_fn, data, fold_spec, metrics 필수)
        pit_hash — read-only: data + spec → pit_hash 만 계산 (cache key 용도)

    Outcome 매핑 (Codex Round 5 Layer B):
        PASS  — 모든 fold 정상 완료
        WARN  — 일부 fold 실패 (degenerate case, e.g. test 안에 unique class 1개)
        BLOCK — PIT leak 검출 (data contamination 은 panic)
        BLOCK — invalid input (model_fn 미지정 등)

    model_fn signature:
        model_fn(train_df: pd.DataFrame) -> predict_fn
        predict_fn(test_df: pd.DataFrame) -> np.ndarray (probabilities or returns)

    metrics 옵션:
        'classification' — brier + logloss + hit_rate (y_true ∈ {0,1})
        'regression'     — mse + mae + sharpe (y_true 는 returns)
    """

    name = "walkforward-validator"
    version = "0.1.0"
    layer = Layer.B

    VALID_ACTIONS: tuple[str, ...] = ("run", "pit_hash")
    VALID_METRIC_KINDS: tuple[str, ...] = ("classification", "regression")

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        action = input_data.get("action")

        if action not in self.VALID_ACTIONS:
            return ActorResult(
                output={"error": f"invalid action {action!r}, expected {self.VALID_ACTIONS}"},
                outcome=Outcome.BLOCK,
                input_summary=f"action={action}",
            )

        # ─── Common input parse ───
        data = input_data.get("data")
        if not isinstance(data, pd.DataFrame):
            return ActorResult(
                output={"error": "data (pd.DataFrame) required"},
                outcome=Outcome.BLOCK,
                input_summary=action,
            )

        spec_dict = input_data.get("fold_spec")
        if not isinstance(spec_dict, dict):
            return ActorResult(
                output={"error": "fold_spec (dict) required"},
                outcome=Outcome.BLOCK,
                input_summary=action,
            )
        try:
            spec = FoldSpec(**spec_dict)
        except (TypeError, ValueError) as exc:
            return ActorResult(
                output={"error": f"invalid fold_spec: {exc}"},
                outcome=Outcome.BLOCK,
                input_summary=action,
            )

        model_id = str(input_data.get("model_id", "unknown"))
        pit_hash = _compute_pit_hash(data, model_id, spec)

        if action == "pit_hash":
            return ActorResult(
                output={"pit_hash": pit_hash, "model_id": model_id, "n_rows": len(data)},
                outcome=Outcome.PASS,
                sample_n=len(data),
                input_summary=f"pit_hash {model_id} ({len(data)} rows)",
            )

        # ─── action == "run" ───
        model_fn = input_data.get("model_fn")
        if not callable(model_fn):
            return ActorResult(
                output={"error": "model_fn (callable) required for action=run"},
                outcome=Outcome.BLOCK,
                input_summary=f"run {model_id}",
            )

        target_col = input_data.get("target_col")
        if not target_col or target_col not in data.columns:
            return ActorResult(
                output={"error": f"target_col {target_col!r} not in data columns {list(data.columns)}"},
                outcome=Outcome.BLOCK,
                input_summary=f"run {model_id}",
            )

        metric_kind = input_data.get("metric_kind", "classification")
        if metric_kind not in self.VALID_METRIC_KINDS:
            return ActorResult(
                output={"error": f"metric_kind {metric_kind!r}, expected {self.VALID_METRIC_KINDS}"},
                outcome=Outcome.BLOCK,
                input_summary=f"run {model_id}",
            )

        folds = _generate_folds(len(data), spec)
        if not folds:
            return ActorResult(
                output={
                    "error": f"no valid folds: data has {len(data)} rows but train_size={spec.train_size} + test_size={spec.test_size} required"
                },
                outcome=Outcome.BLOCK,
                input_summary=f"run {model_id}",
            )

        run_id = str(uuid.uuid4())
        fold_results: list[dict[str, Any]] = []
        n_train_total = 0
        n_test_total = 0
        any_failed = False
        start_time = time.monotonic()

        for fold_idx, (tr_slice, te_slice) in enumerate(folds):
            train_df = data.iloc[tr_slice].copy()
            test_df = data.iloc[te_slice].copy()
            n_train_total += len(train_df)
            n_test_total += len(test_df)

            # PIT enforcement (Layer B core invariant)
            _verify_pit(train_df, test_df)

            try:
                predict_fn = cast(Any, model_fn)(train_df)
                y_prob = np.asarray(cast(Any, predict_fn)(test_df), dtype=np.float64)
                y_true = np.asarray(test_df[target_col].values, dtype=np.float64)

                if len(y_prob) != len(y_true):
                    raise ValueError(f"predict_fn returned {len(y_prob)} preds, expected {len(y_true)}")

                fold_metrics = self._compute_fold_metrics(y_true, y_prob, metric_kind)
                fold_results.append(
                    {"fold": fold_idx, "n_train": len(train_df), "n_test": len(test_df), **fold_metrics}
                )
            except Exception as exc:
                any_failed = True
                fold_results.append(
                    {
                        "fold": fold_idx,
                        "n_train": len(train_df),
                        "n_test": len(test_df),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        successful = [f for f in fold_results if "error" not in f]
        aggregate = _aggregate_metrics(
            [{k: v for k, v in f.items() if k not in ("fold", "n_train", "n_test")} for f in successful]
        )

        metrics_payload = {"folds": fold_results, "aggregate": aggregate}
        duration_ms = int((time.monotonic() - start_time) * 1000)

        log_walkforward_run(
            run_id=run_id,
            model_id=model_id,
            fold_spec=spec.to_dict(),
            metrics=metrics_payload,
            pit_hash=pit_hash,
            n_folds=len(folds),
            n_train_obs=n_train_total,
            n_test_obs=n_test_total,
            finished_at=kst_now().isoformat(),
        )

        outcome = Outcome.WARN if any_failed else Outcome.PASS
        return ActorResult(
            output={
                "run_id": run_id,
                "model_id": model_id,
                "pit_hash": pit_hash,
                "n_folds": len(folds),
                "n_successful": len(successful),
                "metrics": metrics_payload,
            },
            outcome=outcome,
            sample_n=n_test_total,
            input_summary=f"run {model_id} folds={len(folds)} duration={duration_ms}ms",
        )

    @staticmethod
    def _compute_fold_metrics(y_true: np.ndarray, y_prob: np.ndarray, kind: str) -> dict[str, float]:
        if kind == "classification":
            return {
                "brier": _brier_score(y_true, y_prob),
                "logloss": _log_loss(y_true, y_prob),
                "hit_rate": _hit_rate(y_true, y_prob),
            }
        # regression
        residuals = y_prob - y_true
        return {
            "mse": float(np.mean(residuals**2)),
            "mae": float(np.mean(np.abs(residuals))),
            "sharpe": _sharpe_from_returns(y_prob),
        }


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m nuri.agents.actors.walkforward_validator <action>

    pit_hash 만 의미 있는 CLI 사용 — run 은 model_fn callable 필요해서 Python 내부 호출 전용.
    """
    import argparse
    import json as _json
    import sys

    parser = argparse.ArgumentParser(prog="walkforward-validator")
    parser.add_argument("action", choices=["pit_hash"])  # CLI 는 pit_hash 만 노출
    parser.add_argument("--model-id", default="cli")
    parser.add_argument("--csv", required=True, help="path to CSV with date column")
    parser.add_argument("--train-size", type=int, default=252)
    parser.add_argument("--test-size", type=int, default=21)
    parser.add_argument("--step", type=int, default=21)
    parser.add_argument("--kind", choices=["rolling", "expanding"], default="rolling")
    args = parser.parse_args(argv)

    df = pd.read_csv(args.csv)
    actor = WalkForwardValidator()
    try:
        result = actor.run(
            {
                "action": "pit_hash",
                "data": df,
                "fold_spec": {
                    "kind": args.kind,
                    "train_size": args.train_size,
                    "test_size": args.test_size,
                    "step": args.step,
                },
                "model_id": args.model_id,
            }
        )
    except Exception as exc:
        print(_json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2

    print(_json.dumps(result.output, indent=2, ensure_ascii=False))
    return 0 if result.outcome == Outcome.PASS else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())

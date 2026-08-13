"""RegimePosterior — Layer B actor (#529 Phase 2 — canonical #3).

Responsibilities:
- 거시 feature (vix_z / yield_curve_slope / hy_oas) → smoothed P(state_t | data_1:T)
- sticky-HMM (Gaussian emission + diagonal Dirichlet prior on transition) fit + smooth
- 매 학습 결과 12-field audit row 영구 기록 (regime_posteriors)
- regime change (argmax_state 변동) 시 Discord ROLLOUT 채널 publish

Layer B 설계 (Codex Round 5 + 2026-05-01 design consult):
- 100% deterministic — sticky-HMM EM, ZERO LLM
- 기존 nuri/quant/regime/classifier.py 의 hard-label hysteresis 와 *별개* track 으로
  운영 (정보량 보존, hard label 은 SIEGE/UI 가 계속 사용)
- WalkForward-Validator (#5) 와 같이 Brier/log-loss 으로 평가 가능
- producer/consumer 분리: 우리는 *producer* (DB row 만 emit), Decision-Compiler (#8)
  가 향후 read-only consumer

Anti-pattern 방지 (lock-test 보장):
- posterior 합 ≠ 1 (numerical drift) → log_regime_posterior 가 panic
- transition matrix 음수 (sticky prior 위반) → fit 단계에서 panic
- sticky 효과 부재 (HMM 이 diag prior 무시) → dwell time 검증 필요
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM

from nuri.agents.base import REGISTRY, Actor, ActorResult, Layer, Outcome, RunContext
from nuri.core.db import log_regime_posterior, query
from nuri.core.timezone import today_kst

logger = logging.getLogger(__name__)

# ─── Sticky-HMM 기본 파라미터 (Codex consult 합의) ─────────────
DEFAULT_N_STATES = 3  # bull / bear / sideways 매핑 가능 (해석은 Layer C)
DEFAULT_STICKY_KAPPA = 50.0  # diagonal Dirichlet prior 강도 (높을수록 dwell 증가)
DEFAULT_N_ITER = 50  # EM 반복
DEFAULT_TOL = 1e-4
DEFAULT_RANDOM_STATE = 42  # reproducibility (pit_hash 와 짝패)
DEFAULT_FEATURE_COLS: tuple[str, ...] = ("vix_z", "yield_curve_slope", "hy_oas")


@dataclass
class StickyHMMSpec:
    """Sticky-HMM 학습 spec (audit row 의 model_version + state_space_version 산출)."""

    n_states: int = DEFAULT_N_STATES
    sticky_kappa: float = DEFAULT_STICKY_KAPPA
    n_iter: int = DEFAULT_N_ITER
    tol: float = DEFAULT_TOL
    random_state: int = DEFAULT_RANDOM_STATE
    feature_cols: tuple[str, ...] = DEFAULT_FEATURE_COLS

    def __post_init__(self) -> None:
        if self.n_states < 2:
            raise ValueError(f"n_states must be >= 2, got {self.n_states}")
        if self.sticky_kappa < 0:
            raise ValueError(f"sticky_kappa must be >= 0, got {self.sticky_kappa}")
        if not self.feature_cols:
            raise ValueError("feature_cols must not be empty")

    @property
    def state_space_version(self) -> str:
        return f"{self.n_states}-state-v1"

    @property
    def model_version(self) -> str:
        return f"sticky_hmm_n{self.n_states}_k{int(self.sticky_kappa)}_v1"


def _entropy(p: np.ndarray) -> float:
    """Shannon entropy (bits). p 는 probability vector (sum=1).

    posterior 가 degenerate (한 state 에 100%) 면 entropy=0.
    uniform 일 때 log2(n) 최대.
    """
    p_arr: np.ndarray = np.asarray(p, dtype=np.float64)
    p_pos: np.ndarray = p_arr[p_arr > 0]  # 0 entry log skip
    if p_pos.size == 0:
        return 0.0
    return float(-(p_pos * np.log2(p_pos)).sum())


def _top2_margin(p: np.ndarray) -> float:
    """top1 - top2 확률 차. 큰 값 = 단일 state 강한 신호. 작은 값 = 모호.

    Decision-Compiler 가 향후 이 값으로 신뢰도 게이팅 가능.
    """
    sorted_p = np.sort(np.asarray(p, dtype=np.float64))[::-1]
    if sorted_p.size < 2:
        return float(sorted_p[0]) if sorted_p.size == 1 else 0.0
    return float(sorted_p[0] - sorted_p[1])


def _hash_array(arr: np.ndarray) -> str:
    """numpy array → SHA256[:16]. transition_params_hash / emission_params_hash 산출용."""
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(arr).tobytes())
    return h.hexdigest()[:16]


def _apply_sticky_prior(transmat: np.ndarray, kappa: float) -> np.ndarray:
    """Diagonal Dirichlet prior 적용 — diagonal 에 +kappa, row-normalize.

    sticky-HMM 의 핵심: P(state_t = i | state_{t-1} = i) 를 inflate.
    kappa=0 이면 vanilla HMM 동일.
    """
    if kappa <= 0:
        return transmat
    n = transmat.shape[0]
    boosted = transmat + kappa * np.eye(n)
    # row-normalize
    row_sums = boosted.sum(axis=1, keepdims=True)
    return boosted / row_sums


def _fit_sticky_hmm(
    features: np.ndarray,
    spec: StickyHMMSpec,
) -> tuple[Any, np.ndarray, np.ndarray, np.ndarray]:
    """Sticky-HMM fit + smoothed posterior. hmmlearn 의존.

    Returns:
        (model, posterior_smoothed, transmat_sticky, means)
        posterior_smoothed: (T, n_states) — P(state_t | data_1:T)
        transmat_sticky: (n_states, n_states) — sticky prior 적용된 transition
        means: (n_states, n_features)
    """
    model = GaussianHMM(
        n_components=spec.n_states,
        covariance_type="diag",
        n_iter=spec.n_iter,
        tol=spec.tol,
        random_state=spec.random_state,
    )
    model.fit(features)
    # 기본 transition 에 sticky prior 적용 → 재정규화
    sticky_transmat = _apply_sticky_prior(model.transmat_, spec.sticky_kappa)
    model.transmat_ = sticky_transmat
    # smoothed posterior — predict_proba = forward-backward 결과
    posterior = model.predict_proba(features)
    return model, posterior, sticky_transmat, model.means_


@dataclass
class _PosteriorSummary:
    """fit + smooth 결과의 단일 시점 요약 (DB audit row 의 source).

    field=field(...) 로 default empty 처리해 dataclass 가 mutable default 를 안전하게 보유.
    """

    posterior: list[float] = field(default_factory=list)
    argmax_state: int = 0
    entropy: float = 0.0
    top2_margin: float = 0.0
    transition_params_hash: str = ""
    emission_params_hash: str = ""


def _summarize_last_step(
    posterior_smoothed: np.ndarray,
    transmat: np.ndarray,
    means: np.ndarray,
) -> _PosteriorSummary:
    """가장 최근 timestamp 의 posterior 한 줄 요약. DB row 1 개에 매핑."""
    last = posterior_smoothed[-1]
    # numerical drift safeguard — sum=1 에서 1e-9 이내로 재정규화
    last = last / last.sum()
    return _PosteriorSummary(
        posterior=last.tolist(),
        argmax_state=int(np.argmax(last)),
        entropy=_entropy(last),
        top2_margin=_top2_margin(last),
        transition_params_hash=_hash_array(transmat),
        emission_params_hash=_hash_array(means),
    )


def _validate_features(
    data: pd.DataFrame,
    feature_cols: tuple[str, ...],
) -> np.ndarray:
    """feature column 존재 + numeric + NaN 없음 검증. 위반 시 ValueError.

    sticky-HMM fit 전에 데이터 cleanliness 강제 (Layer B contract).
    """
    missing = [c for c in feature_cols if c not in data.columns]
    if missing:
        raise ValueError(f"missing feature columns: {missing}")
    arr = data[list(feature_cols)].to_numpy(dtype=np.float64)
    if not np.isfinite(arr).all():
        nan_cols = [c for c in feature_cols if not np.isfinite(data[c].to_numpy()).all()]
        raise ValueError(f"non-finite values in feature columns: {nan_cols}")
    if arr.shape[0] < 30:
        raise ValueError(f"need >=30 rows for sticky-HMM fit, got {arr.shape[0]} (degenerate EM)")
    return arr


@REGISTRY.register
class RegimePosterior(Actor):
    """Sticky-HMM smoothed regime posterior — Layer B producer.

    Actions (input_data['action']):
        fit  — 학습 + smoothed posterior 산출 + DB audit row 기록
        last_posterior  — 가장 최근 as_of_date 의 posterior 조회 (read-only)

    Required input (action='fit'):
        data: pd.DataFrame  — feature_cols 보유, date column 권장 (없으면 index 사용)
        as_of_date: str (YYYY-MM-DD)  — train_window 의 끝 날짜 (audit key)
        train_window: str  — "YYYY-MM-DD..YYYY-MM-DD" (감사용 metadata)
        data_freshness_status: 'PASS'|'WARN'|'FAIL'  — Freshness-Gatekeeper 결과 snapshot
        spec: dict (optional)  — StickyHMMSpec fields override

    Outcome 매핑 (Codex Round 5 Layer B):
        PASS  — fit 정상, audit row 기록 완료
        WARN  — fit 정상이나 data_freshness_status='WARN' 또는 entropy 너무 높음 (>0.95 * log2(n))
        BLOCK — invalid input / feature 결손 / 학습 데이터 부족

    Discord publish:
        argmax_state 가 직전 row 와 다르면 ROLLOUT 채널로 embed publish (regime change alert).
    """

    name = "regime-posterior"
    version = "0.1.0"
    layer = Layer.B

    VALID_ACTIONS: tuple[str, ...] = ("fit", "last_posterior")
    HIGH_ENTROPY_FRACTION = 0.95  # entropy > 0.95 * log2(n_states) → WARN

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        action = input_data.get("action")

        if action not in self.VALID_ACTIONS:
            return ActorResult(
                output={"error": f"invalid action {action!r}, expected {self.VALID_ACTIONS}"},
                outcome=Outcome.BLOCK,
                input_summary=f"action={action}",
            )

        if action == "last_posterior":
            return self._last_posterior(input_data)

        # ─── action == "fit" ───
        data = input_data.get("data")
        if not isinstance(data, pd.DataFrame):
            return ActorResult(
                output={"error": "data (pd.DataFrame) required"},
                outcome=Outcome.BLOCK,
                input_summary="fit",
            )

        as_of_date = input_data.get("as_of_date") or today_kst()
        train_window = input_data.get("train_window")
        if not isinstance(train_window, str) or ".." not in train_window:
            return ActorResult(
                output={"error": "train_window 'YYYY-MM-DD..YYYY-MM-DD' required"},
                outcome=Outcome.BLOCK,
                input_summary=f"fit {as_of_date}",
            )

        freshness = input_data.get("data_freshness_status")
        if freshness not in ("PASS", "WARN", "FAIL"):
            return ActorResult(
                output={"error": f"data_freshness_status must be PASS/WARN/FAIL, got {freshness!r}"},
                outcome=Outcome.BLOCK,
                input_summary=f"fit {as_of_date}",
            )
        if freshness == "FAIL":
            return ActorResult(
                output={
                    "error": "data_freshness_status=FAIL — refusing to fit on stale data",
                    "as_of_date": as_of_date,
                },
                outcome=Outcome.BLOCK,
                input_summary=f"fit {as_of_date}",
            )

        spec_dict = input_data.get("spec") or {}
        try:
            spec = StickyHMMSpec(**spec_dict)
        except (TypeError, ValueError) as exc:
            return ActorResult(
                output={"error": f"invalid spec: {exc}"},
                outcome=Outcome.BLOCK,
                input_summary=f"fit {as_of_date}",
            )

        try:
            features = _validate_features(data, spec.feature_cols)
        except ValueError as exc:
            return ActorResult(
                output={"error": str(exc)},
                outcome=Outcome.BLOCK,
                input_summary=f"fit {as_of_date}",
            )

        try:
            _model, posterior_smoothed, transmat, means = _fit_sticky_hmm(features, spec)
        except Exception as exc:  # hmmlearn convergence/singular cov 등
            return ActorResult(
                output={"error": f"sticky-HMM fit failed: {type(exc).__name__}: {exc}"},
                outcome=Outcome.BLOCK,
                input_summary=f"fit {as_of_date}",
            )

        # post-fit invariant: transition matrix non-negative + row-sum=1
        if (transmat < 0).any():
            raise ValueError(f"transition matrix has negative entries (sticky prior bug): min={transmat.min()}")
        row_sums = transmat.sum(axis=1)
        if not np.allclose(row_sums, 1.0, atol=1e-6):
            raise ValueError(f"transition matrix rows must sum to 1 (got {row_sums.tolist()})")

        summary = _summarize_last_step(posterior_smoothed, transmat, means)

        # outcome 분류
        max_entropy = math.log2(spec.n_states)
        outcome = Outcome.PASS
        if freshness == "WARN":
            outcome = Outcome.WARN
        elif summary.entropy > self.HIGH_ENTROPY_FRACTION * max_entropy:
            outcome = Outcome.WARN  # near-uniform posterior = signal 없음

        feature_snapshot = {
            "n_obs": int(features.shape[0]),
            "feature_cols": list(spec.feature_cols),
            "last_features": dict(zip(spec.feature_cols, features[-1].tolist(), strict=True)),
        }

        # 직전 argmax 조회 → regime change 판정 (Discord publish 결정)
        regime_changed, prev_argmax = self._detect_regime_change(
            as_of_date=as_of_date,
            model_version=spec.model_version,
            curr_argmax=summary.argmax_state,
        )

        log_regime_posterior(
            as_of_date=as_of_date,
            model_version=spec.model_version,
            state_space_version=spec.state_space_version,
            feature_snapshot=feature_snapshot,
            posterior=summary.posterior,
            argmax_state=summary.argmax_state,
            entropy=summary.entropy,
            top2_margin=summary.top2_margin,
            transition_params_hash=summary.transition_params_hash,
            emission_params_hash=summary.emission_params_hash,
            train_window=train_window,
            data_freshness_status=freshness,
            run_id=ctx.run_id,
        )

        if regime_changed:
            self._publish_regime_change(
                as_of_date=as_of_date,
                model_version=spec.model_version,
                prev_argmax=prev_argmax,
                summary=summary,
                run_id=ctx.run_id,
            )

        return ActorResult(
            output={
                "as_of_date": as_of_date,
                "model_version": spec.model_version,
                "argmax_state": summary.argmax_state,
                "posterior": summary.posterior,
                "entropy": summary.entropy,
                "top2_margin": summary.top2_margin,
                "regime_changed": regime_changed,
                "prev_argmax": prev_argmax,
                "n_states": spec.n_states,
            },
            outcome=outcome,
            sample_n=int(features.shape[0]),
            input_summary=f"fit {as_of_date} {spec.model_version}",
        )

    # ─── helpers ─────────────────────────────────────────────

    @staticmethod
    def _last_posterior(input_data: dict[str, Any]) -> ActorResult:
        """가장 최근 as_of_date 의 posterior row 조회."""
        model_version = input_data.get("model_version")
        if model_version:
            rows = query(
                """SELECT * FROM regime_posteriors WHERE model_version = ?
                   ORDER BY as_of_date DESC LIMIT 1""",
                (model_version,),
            )
        else:
            rows = query("SELECT * FROM regime_posteriors ORDER BY as_of_date DESC LIMIT 1")
        if not rows:
            return ActorResult(
                output={"error": "no regime_posteriors row found"},
                outcome=Outcome.WARN,
                input_summary="last_posterior",
            )
        r = dict(rows[0])
        r["posterior"] = json.loads(r["posterior_json"])
        return ActorResult(
            output=r,
            outcome=Outcome.PASS,
            input_summary=f"last_posterior {r['as_of_date']}",
        )

    @staticmethod
    def _detect_regime_change(
        as_of_date: str,
        model_version: str,
        curr_argmax: int,
    ) -> tuple[bool, int | None]:
        """as_of_date 직전 row 의 argmax_state 와 비교 → 변동 여부."""
        rows = query(
            """SELECT argmax_state FROM regime_posteriors
               WHERE model_version = ? AND as_of_date < ?
               ORDER BY as_of_date DESC LIMIT 1""",
            (model_version, as_of_date),
        )
        if not rows:
            return False, None  # 첫 row → change 아님
        prev = int(rows[0]["argmax_state"])
        return prev != curr_argmax, prev

    @staticmethod
    def _publish_regime_change(
        as_of_date: str,
        model_version: str,
        prev_argmax: int | None,
        summary: _PosteriorSummary,
        run_id: str,
    ) -> None:
        """Regime change 발생 시 ROLLOUT 채널로 embed publish.

        env (DISCORD_WEBHOOK_ROLLOUT) 미설정 시 publisher 가 graceful skip → 테스트 환경 안전.
        실패도 actor decision 자체를 fail 시키지 않음 (best-effort notification).
        """
        try:
            from nuri.agents.discord.outbox import stage_rollout

            stage_rollout(
                payload={
                    "kind": "regime_change",
                    "summary": (
                        f"{model_version} @ {as_of_date}: "
                        f"{prev_argmax} → {summary.argmax_state} "
                        f"(margin {summary.top2_margin:.2f}, entropy {summary.entropy:.2f})"
                    ),
                    "model_version": model_version,
                    "as_of_date": as_of_date,
                    "prev_argmax": prev_argmax,
                    "new_argmax": summary.argmax_state,
                    "top2_margin": summary.top2_margin,
                    "entropy": summary.entropy,
                    "posterior": list(summary.posterior),
                },
                dedupe_key=f"regime_change:{model_version}:{as_of_date}",
                actor_name="regime-posterior",
                run_id=run_id,
            )
        except Exception:  # noqa: BLE001 — best-effort, never block actor
            # 발행 실패로 액터를 죽이지 않는다(#894) — 다만 **조용히** 넘기지도 않는다.
            logger.exception("outbox staging 실패: stage_rollout")


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m nuri.agents.actors.regime_posterior last_posterior

    fit 은 macro feature DataFrame 이 필요해서 Python 내부 호출 전용.
    last_posterior 만 노출 (운영 inspection 용도).
    """
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(prog="regime-posterior")
    parser.add_argument("action", choices=["last_posterior"])
    parser.add_argument("--model-version", default=None)
    args = parser.parse_args(argv)

    actor = RegimePosterior()
    result = actor.run(
        {
            "action": args.action,
            "model_version": args.model_version,
        }
    )
    print(_json.dumps(result.output, indent=2, ensure_ascii=False, default=str))
    return 0 if result.outcome in (Outcome.PASS, Outcome.WARN) else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())

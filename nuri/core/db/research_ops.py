"""Phase 2 research/registry/benchmark writes (#529).

Walk-forward validator results, regime posterior snapshots, hypothesis
lifecycle (register/validate/reject/expire), causal audits, foundation model
benchmarks. All append-only ledgers.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from ..timezone import kst_now
from .connection import get_db

_HYPOTHESIS_STATUSES = ("open", "validated", "rejected", "expired")
_CANARY_SCOPES = ("paper", "partial", "full")
_FBENCH_VALID_KINDS: tuple[str, ...] = ("baseline", "foundation", "traditional")
_FBENCH_VALID_METRICS: tuple[str, ...] = ("brier", "logloss", "sharpe", "mse", "mae", "hit_rate")
_CAUSAL_VERDICTS = ("ROBUST", "WEAK", "MIRAGE", "INSUFFICIENT")


def log_walkforward_run(
    run_id: str,
    model_id: str,
    fold_spec: dict,
    metrics: dict,
    pit_hash: str,
    n_folds: int,
    n_train_obs: Optional[int] = None,
    n_test_obs: Optional[int] = None,
    finished_at: Optional[str] = None,
    error_message: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Walk-forward evaluation result audit (#529 Phase 2 — WalkForward-Validator).

    fold_spec: {"kind": "rolling"|"expanding", "train_size": N, "test_size": M, "step": K}
    metrics: {"aggregate": {"brier": .., "logloss": ..}, "folds": [{"fold": 0, ..}, ...]}
    pit_hash: data digest + fold spec + model_id → reproducibility key.
    finished_at None → run still in progress (started_at default).
    """
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT INTO walkforward_runs
               (run_id, model_id, fold_spec_json, metrics_json, pit_hash,
                n_folds, n_train_obs, n_test_obs, finished_at, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(run_id) DO UPDATE SET
                 metrics_json = excluded.metrics_json,
                 finished_at = COALESCE(excluded.finished_at, finished_at),
                 error_message = excluded.error_message""",
            (
                run_id,
                model_id,
                json.dumps(fold_spec, sort_keys=True),
                json.dumps(metrics, default=str),
                pit_hash,
                n_folds,
                n_train_obs,
                n_test_obs,
                finished_at,
                error_message,
            ),
        )


def log_regime_posterior(
    as_of_date: str,
    model_version: str,
    state_space_version: str,
    feature_snapshot: dict,
    posterior: list[float],
    argmax_state: int,
    entropy: float,
    top2_margin: float,
    transition_params_hash: str,
    emission_params_hash: str,
    train_window: str,
    data_freshness_status: str,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Sticky-HMM smoothed posterior audit (#529 Phase 2 — Regime-Posterior actor #3).

    Codex Round 5 Layer B. (as_of_date, model_version) 가 PK 로 동일 학습 재실행 시 idempotent
    upsert. posterior_json = list[float] (state 별 P(state_t | data_1:T), sum=1).
    data_freshness_status: PASS/WARN/FAIL — Freshness-Gatekeeper 의 결정 snapshot.

    Layer A 가 이 row 를 read 하여 enforce 가능 (e.g. argmax 변경 시 SIEGE re-run trigger).
    """
    if data_freshness_status not in ("PASS", "WARN", "FAIL"):
        raise ValueError(f"data_freshness_status must be PASS/WARN/FAIL, got {data_freshness_status!r}")
    if abs(sum(posterior) - 1.0) > 1e-6:
        raise ValueError(f"posterior must sum to 1 (got {sum(posterior):.6f}) — sticky-HMM smoothed P violation")
    if not (0 <= argmax_state < len(posterior)):
        raise ValueError(f"argmax_state {argmax_state} out of range [0, {len(posterior)})")
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT INTO regime_posteriors
               (as_of_date, model_version, state_space_version, feature_snapshot_json,
                posterior_json, argmax_state, entropy, top2_margin,
                transition_params_hash, emission_params_hash, train_window,
                data_freshness_status, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(as_of_date, model_version) DO UPDATE SET
                 state_space_version = excluded.state_space_version,
                 feature_snapshot_json = excluded.feature_snapshot_json,
                 posterior_json = excluded.posterior_json,
                 argmax_state = excluded.argmax_state,
                 entropy = excluded.entropy,
                 top2_margin = excluded.top2_margin,
                 transition_params_hash = excluded.transition_params_hash,
                 emission_params_hash = excluded.emission_params_hash,
                 train_window = excluded.train_window,
                 data_freshness_status = excluded.data_freshness_status,
                 run_id = excluded.run_id""",
            (
                as_of_date,
                model_version,
                state_space_version,
                json.dumps(feature_snapshot, sort_keys=True, default=str),
                json.dumps(posterior),
                argmax_state,
                entropy,
                top2_margin,
                transition_params_hash,
                emission_params_hash,
                train_window,
                data_freshness_status,
                run_id,
            ),
        )


def register_hypothesis(
    hypothesis_id: str,
    name: str,
    version: str,
    producer_actor: str,
    claim_text: str,
    evidence: dict,
    expiry_date: str,
    producer_run_id: Optional[str] = None,
    feature_flag: Optional[str] = None,
    canary_scope: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> tuple[str, bool]:
    """Hypothesis 등록 — claim_hash idempotent (동일 producer + claim 재등록 시 기존 id 반환).

    Returns (hypothesis_id, is_new) — is_new=False 시 기존 row 그대로.
    Initial status = 'open'. 명시적 validate/reject/expire 호출로만 전이.

    Codex Round 5 Layer A: open→validated 는 validation_metrics_json 필수.
    """

    if canary_scope is not None and canary_scope not in _CANARY_SCOPES:
        raise ValueError(f"canary_scope must be {_CANARY_SCOPES}, got {canary_scope!r}")
    claim_hash = hashlib.sha256(f"{producer_actor}|{claim_text}".encode()).hexdigest()[:32]

    with get_db(db_path) as conn:
        existing = conn.execute(
            "SELECT hypothesis_id FROM hypotheses WHERE claim_hash = ?",
            (claim_hash,),
        ).fetchone()
        if existing:
            return existing["hypothesis_id"], False
        conn.execute(
            """INSERT INTO hypotheses
               (hypothesis_id, name, version, producer_actor, producer_run_id,
                claim_text, claim_hash, evidence_json, status,
                feature_flag, canary_scope, expiry_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)""",
            (
                hypothesis_id,
                name,
                version,
                producer_actor,
                producer_run_id,
                claim_text,
                claim_hash,
                json.dumps(evidence, sort_keys=True, default=str),
                feature_flag,
                canary_scope,
                expiry_date,
            ),
        )
        return hypothesis_id, True


def validate_hypothesis(
    hypothesis_id: str,
    validation_metrics: dict,
    db_path: Optional[Path] = None,
) -> None:
    """open → validated 전이. validation_metrics 필수 (Layer A enforcement).

    Codex Round 5 mandatory: 검증 metrics 없이 validated 로 변경 불가.
    이미 validated/rejected/expired 면 ValueError (status machine 위반).
    """
    if not validation_metrics:
        raise ValueError("validation_metrics dict required to validate (Layer A enforcement)")
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM hypotheses WHERE hypothesis_id = ?",
            (hypothesis_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"hypothesis {hypothesis_id!r} not found")
        if row["status"] != "open":
            raise ValueError(
                f"cannot validate hypothesis {hypothesis_id!r}: status={row['status']!r} "
                "(only open → validated allowed)"
            )
        conn.execute(
            """UPDATE hypotheses SET status='validated',
               validated_at=datetime('now'),
               validation_metrics_json=?
               WHERE hypothesis_id=?""",
            (json.dumps(validation_metrics, sort_keys=True, default=str), hypothesis_id),
        )


def reject_hypothesis(
    hypothesis_id: str,
    rejection_reason: str,
    db_path: Optional[Path] = None,
) -> None:
    """open → rejected. rejection_reason 필수."""
    if not rejection_reason or not rejection_reason.strip():
        raise ValueError("rejection_reason required to reject (Layer A enforcement)")
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM hypotheses WHERE hypothesis_id = ?",
            (hypothesis_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"hypothesis {hypothesis_id!r} not found")
        if row["status"] != "open":
            raise ValueError(
                f"cannot reject hypothesis {hypothesis_id!r}: status={row['status']!r} (only open → rejected allowed)"
            )
        conn.execute(
            "UPDATE hypotheses SET status='rejected', rejection_reason=? WHERE hypothesis_id=?",
            (rejection_reason, hypothesis_id),
        )


def expire_hypotheses(db_path: Optional[Path] = None) -> int:
    """open + expiry_date < today → expired. 반환: 만료 처리된 row 수.

    SRE-Incident-Agent / scheduler 가 cron 으로 주기 호출. idempotent.
    """
    with get_db(db_path) as conn:
        cursor = conn.execute(
            """UPDATE hypotheses SET status='expired'
               WHERE status='open' AND date(expiry_date) < date('now')"""
        )
        return cursor.rowcount


def log_causal_audit(
    factor_id: str,
    as_of_date: str,
    n_obs: int,
    verdict: str,
    causal_certainty: float,
    dag_pass: bool,
    placebo_pass: bool,
    event_study_pass: bool,
    negative_control_pass: bool,
    test_results: dict,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Causal-Factor-Auditor 4-test verdict audit (#529 Phase 2 actor #6).

    López de Prado 2025: 4 tests = DAG plausibility / placebo / event-study / negative control.
    causal_certainty ∈ [0,1] composite = 4 test pass-rate weighted by t-stat strength.
    (factor_id, as_of_date) PK → 동일 factor 재audit 시 idempotent upsert.

    Layer B contract: ZERO LLM, deterministic. 결과는 Hypothesis-Registry (#4) consumer.
    """
    if verdict not in _CAUSAL_VERDICTS:
        raise ValueError(f"verdict must be {_CAUSAL_VERDICTS}, got {verdict!r}")
    if not (0.0 <= causal_certainty <= 1.0):
        raise ValueError(f"causal_certainty must be in [0,1], got {causal_certainty}")
    if n_obs < 0:
        raise ValueError(f"n_obs must be >= 0, got {n_obs}")
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT INTO causal_audits
               (factor_id, as_of_date, n_obs, verdict, causal_certainty,
                dag_pass, placebo_pass, event_study_pass, negative_control_pass,
                test_results_json, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(factor_id, as_of_date) DO UPDATE SET
                 n_obs = excluded.n_obs,
                 verdict = excluded.verdict,
                 causal_certainty = excluded.causal_certainty,
                 dag_pass = excluded.dag_pass,
                 placebo_pass = excluded.placebo_pass,
                 event_study_pass = excluded.event_study_pass,
                 negative_control_pass = excluded.negative_control_pass,
                 test_results_json = excluded.test_results_json,
                 run_id = excluded.run_id""",
            (
                factor_id,
                as_of_date,
                n_obs,
                verdict,
                causal_certainty,
                int(dag_pass),
                int(placebo_pass),
                int(event_study_pass),
                int(negative_control_pass),
                json.dumps(test_results, sort_keys=True, default=str),
                run_id,
            ),
        )


def log_foundation_benchmark(
    benchmark_run: str,
    model_id: str,
    model_kind: str,
    metric_name: str,
    metric_value: float,
    higher_is_better: bool,
    sample_n: int,
    pit_hash: Optional[str] = None,
    walkforward_run_id: Optional[str] = None,
    notes: Optional[str] = None,
    actor_run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Foundation-Benchmark 단일 metric 기록 (#529 Phase 2 actor #7).

    benchmark_run: 'YYYY-MM-DD-<slug>' 그루핑 키 (같은 protocol 의 비교군).
    model_kind ∈ ('baseline','foundation','traditional') 검증.
    metric_name ∈ ('brier','logloss','sharpe','mse','mae','hit_rate') 검증.
    sample_n >= 0 검증 (음수 panic).
    pit_hash / walkforward_run_id: WalkForwardValidator audit join 용.

    Returns: lastrowid (benchmark_id).
    """
    if model_kind not in _FBENCH_VALID_KINDS:
        raise ValueError(f"model_kind must be one of {_FBENCH_VALID_KINDS}, got {model_kind!r}")
    if metric_name not in _FBENCH_VALID_METRICS:
        raise ValueError(f"metric_name must be one of {_FBENCH_VALID_METRICS}, got {metric_name!r}")
    if sample_n < 0:
        raise ValueError(f"sample_n must be >= 0, got {sample_n}")
    with get_db(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO foundation_benchmarks
               (benchmark_run, model_id, model_kind, metric_name, metric_value,
                higher_is_better, sample_n, pit_hash, walkforward_run_id,
                notes, actor_run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                benchmark_run,
                model_id,
                model_kind,
                metric_name,
                float(metric_value),
                1 if higher_is_better else 0,
                int(sample_n),
                pit_hash,
                walkforward_run_id,
                notes,
                actor_run_id,
            ),
        )
        return cursor.lastrowid or 0


def save_backtest(
    strategy_id: str,
    start_date: str,
    end_date: str,
    total_return: float,
    sharpe: float,
    max_drawdown: float,
    win_rate: float,
    params: Optional[dict] = None,
    created_at: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """백테스트 결과 1행 기록 (backtests 테이블 — 그동안 writer 부재, Phase 3 placeholder 활성화).

    엔진(run_momentum_backtest)이 반환한 메트릭을 영속화한다. start_date/end_date 는
    실제 백테스트된 가격 구간(영업일 window)이며, period 문자열이 아닌 실측 날짜다.
    params 는 재현용 설정 dict(JSON 저장). created_at None → kst_now() (KST invariant,
    backtests 테이블엔 created_at DEFAULT 가 없어 명시 기록).

    Returns: lastrowid (backtest id).
    """
    stamp = created_at or kst_now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO backtests
               (strategy_id, start_date, end_date, total_return, sharpe,
                max_drawdown, win_rate, params, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                strategy_id,
                start_date,
                end_date,
                float(total_return),
                float(sharpe),
                float(max_drawdown),
                float(win_rate),
                json.dumps(params or {}, default=str),
                stamp,
            ),
        )
        return cursor.lastrowid or 0

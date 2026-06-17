"""WalkForwardValidator tests (#529 Phase 2 — actor #5, canonical).

검증:
- Layer B (deterministic, ZERO LLM)
- 4 actions: run / pit_hash, classification + regression metrics
- Anti-leak lock-test: future data injection 시 PIT 위반 panic
- Rolling vs Expanding fold 정확성
- Reproducibility: 동일 입력 → 동일 pit_hash + 동일 metrics
- 모든 결정 walkforward_runs + agent_audit_ledger 자동 기록
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from nuri.agents.actors.walkforward_validator import (
    FoldSpec,
    WalkForwardValidator,
    _aggregate_metrics,
    _brier_score,
    _generate_folds,
    _hit_rate,
    _log_loss,
    _sharpe_from_returns,
    _verify_pit,
)
from nuri.agents.base import Layer, Outcome
from nuri.core.db import init_db, query


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "wf.db"
    init_db(path)
    return path


@pytest.fixture
def patched_db(db_path):
    """base + actor 의 db 호출을 임시 path 로 redirect."""
    from nuri.core import db as db_module

    def make_redirect(fn):
        def wrapped(*args, **kwargs):
            # actor 가 db_path=None 을 명시 전달(#711)해도 tmp DB 로 라우팅되도록
            # setdefault 대신 None 도 덮어쓴다.
            if kwargs.get("db_path") is None:
                kwargs["db_path"] = db_path
            return fn(*args, **kwargs)

        return wrapped

    patches = [
        patch("nuri.agents.base.log_agent_audit", side_effect=make_redirect(db_module.log_agent_audit)),
        patch("nuri.agents.base.start_agent_run", side_effect=make_redirect(db_module.start_agent_run)),
        patch("nuri.agents.base.finish_agent_run", side_effect=make_redirect(db_module.finish_agent_run)),
        patch(
            "nuri.agents.actors.walkforward_validator.log_walkforward_run",
            side_effect=make_redirect(db_module.log_walkforward_run),
        ),
    ]
    for p in patches:
        p.start()
    yield db_path
    for p in patches:
        p.stop()


@pytest.fixture
def synthetic_data():
    """100 rows, date column, target binary, feature numeric."""
    n = 100
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "date": dates,
            "feature": rng.normal(0, 1, n),
            "target": rng.integers(0, 2, n).astype(float),
        }
    )


# ═══════════════════════════════════════════════════════
# Layer A/B/C invariants
# ═══════════════════════════════════════════════════════


class TestActorRegistration:
    def test_layer_is_b(self):
        assert WalkForwardValidator.layer == Layer.B

    def test_no_llm_dependency(self):
        assert getattr(WalkForwardValidator, "_uses_llm", False) is False

    def test_registered_in_canonical_15(self):
        from nuri.agents.base import REGISTRY

        assert REGISTRY.get("walkforward-validator") is WalkForwardValidator


# ═══════════════════════════════════════════════════════
# FoldSpec validation
# ═══════════════════════════════════════════════════════


class TestFoldSpec:
    def test_valid_rolling(self):
        s = FoldSpec(kind="rolling", train_size=10, test_size=5, step=5)
        assert s.kind == "rolling"

    def test_valid_expanding(self):
        s = FoldSpec(kind="expanding", train_size=10, test_size=5, step=5)
        assert s.kind == "expanding"

    def test_invalid_kind_raises(self):
        with pytest.raises(ValueError, match="rolling/expanding"):
            FoldSpec(kind="weird", train_size=10, test_size=5, step=5)

    def test_zero_size_raises(self):
        with pytest.raises(ValueError, match=">= 1"):
            FoldSpec(kind="rolling", train_size=0, test_size=5, step=5)


# ═══════════════════════════════════════════════════════
# _generate_folds correctness
# ═══════════════════════════════════════════════════════


class TestGenerateFolds:
    def test_rolling_fold_count(self):
        # n=100, train=20, test=10, step=10 → test_start ∈ {20, 30, 40, 50, 60, 70, 80, 90}
        # while test_start + test_size <= 100 → 90 + 10 = 100 ✓ → 8 folds
        folds = _generate_folds(100, FoldSpec("rolling", 20, 10, 10))
        assert len(folds) == 8

    def test_rolling_train_window_fixed(self):
        folds = _generate_folds(100, FoldSpec("rolling", 20, 10, 10))
        for tr, te in folds:
            assert tr.stop - tr.start == 20  # train window fixed
            assert te.stop - te.start == 10
            assert tr.stop == te.start  # train ends right before test

    def test_expanding_train_window_grows(self):
        folds = _generate_folds(100, FoldSpec("expanding", 20, 10, 10))
        prev_size = 0
        for tr, te in folds:
            assert tr.start == 0  # expanding always starts at 0
            curr_size = tr.stop - tr.start
            assert curr_size > prev_size
            prev_size = curr_size
            assert tr.stop == te.start  # PIT boundary

    def test_no_folds_when_data_too_small(self):
        folds = _generate_folds(10, FoldSpec("rolling", 20, 10, 10))
        assert folds == []


# ═══════════════════════════════════════════════════════
# _verify_pit — Anti-leak Lock-Test
# ═══════════════════════════════════════════════════════


class TestAntiLeakLockTest:
    """LOCK-TEST (Gotcha-Test Pair §5.3.1): future data injection MUST panic.

    이 테스트가 fail 하면 fix 가 reverted 된 것 — Walk-forward primitive 의 PIT
    enforcement 가 무력화된 상태. 모든 future actor 의 metric 신뢰성 박살.
    """

    def test_future_data_in_train_panics(self):
        """train 에 test 보다 늦은 row 가 섞이면 ValueError."""
        train = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-01", "2026-12-31"]),  # 12-31 이 미래
                "x": [1.0, 2.0],
            }
        )
        test = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-01", "2026-06-02"]),
                "x": [3.0, 4.0],
            }
        )
        with pytest.raises(ValueError, match="PIT leak"):
            _verify_pit(train, test)

    def test_train_strictly_before_test_passes(self):
        train = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
                "x": [1.0, 2.0],
            }
        )
        test = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-03", "2026-01-04"]),
                "x": [3.0, 4.0],
            }
        )
        _verify_pit(train, test)  # no raise

    def test_overlap_panics(self):
        """train.max == test.min 도 leak (PIT 는 strict less-than)."""
        d = pd.to_datetime(["2026-01-01", "2026-01-02"])
        train = pd.DataFrame({"date": d, "x": [1.0, 2.0]})
        test = pd.DataFrame({"date": d[1:], "x": [2.5]})
        with pytest.raises(ValueError, match="PIT leak"):
            _verify_pit(train, test)

    def test_index_based_pit_when_no_date_col(self):
        """date column 없으면 index 비교 — DatetimeIndex 등."""
        train = pd.DataFrame({"x": [1, 2]}, index=pd.date_range("2026-01-01", periods=2))
        test = pd.DataFrame({"x": [3, 4]}, index=pd.date_range("2026-01-03", periods=2))
        _verify_pit(train, test)
        # leak case
        bad_test = pd.DataFrame({"x": [3]}, index=pd.date_range("2026-01-02", periods=1))
        with pytest.raises(ValueError, match="PIT leak"):
            _verify_pit(train, bad_test)


# ═══════════════════════════════════════════════════════
# Metrics primitives
# ═══════════════════════════════════════════════════════


class TestMetrics:
    def test_brier_perfect_pred(self):
        assert _brier_score(np.array([0, 1, 1, 0]), np.array([0, 1, 1, 0])) == 0.0

    def test_brier_worst_pred(self):
        assert _brier_score(np.array([0, 1]), np.array([1, 0])) == 1.0

    def test_log_loss_perfect_clipped(self):
        # exact 0 / 1 prob → eps clip → small but nonzero
        loss = _log_loss(np.array([0, 1]), np.array([0.0, 1.0]))
        assert loss < 1e-10

    def test_hit_rate_50_50(self):
        assert _hit_rate(np.array([0, 1, 0, 1]), np.array([0.6, 0.4, 0.6, 0.4])) == 0.0

    def test_sharpe_zero_std(self):
        assert _sharpe_from_returns(np.array([0.01, 0.01, 0.01])) == 0.0

    def test_sharpe_positive(self):
        # consistent positive returns → high Sharpe
        s = _sharpe_from_returns(np.array([0.01, 0.012, 0.008, 0.011, 0.009]))
        assert s > 5.0


class TestAggregate:
    def test_empty_returns_empty(self):
        assert _aggregate_metrics([]) == {}

    def test_mean_and_std(self):
        agg = _aggregate_metrics([{"brier": 0.2}, {"brier": 0.4}])
        assert agg["brier_mean"] == pytest.approx(0.3)
        assert agg["brier_std"] == pytest.approx(0.14142, rel=1e-3)


# ═══════════════════════════════════════════════════════
# Action: pit_hash (read-only reproducibility key)
# ═══════════════════════════════════════════════════════


class TestActionPitHash:
    def test_pit_hash_deterministic(self, patched_db, synthetic_data):
        actor = WalkForwardValidator()
        r1 = actor.run(
            {
                "action": "pit_hash",
                "data": synthetic_data,
                "fold_spec": {"kind": "rolling", "train_size": 50, "test_size": 10, "step": 10},
                "model_id": "test_v1",
            }
        )
        r2 = actor.run(
            {
                "action": "pit_hash",
                "data": synthetic_data,
                "fold_spec": {"kind": "rolling", "train_size": 50, "test_size": 10, "step": 10},
                "model_id": "test_v1",
            }
        )
        assert r1.outcome == Outcome.PASS
        assert r1.output["pit_hash"] == r2.output["pit_hash"]

    def test_pit_hash_changes_with_model_id(self, patched_db, synthetic_data):
        actor = WalkForwardValidator()
        r1 = actor.run(
            {
                "action": "pit_hash",
                "data": synthetic_data,
                "fold_spec": {"kind": "rolling", "train_size": 50, "test_size": 10, "step": 10},
                "model_id": "v1",
            }
        )
        r2 = actor.run(
            {
                "action": "pit_hash",
                "data": synthetic_data,
                "fold_spec": {"kind": "rolling", "train_size": 50, "test_size": 10, "step": 10},
                "model_id": "v2",
            }
        )
        assert r1.output["pit_hash"] != r2.output["pit_hash"]

    def test_pit_hash_changes_with_data(self, patched_db, synthetic_data):
        actor = WalkForwardValidator()
        r1 = actor.run(
            {
                "action": "pit_hash",
                "data": synthetic_data,
                "fold_spec": {"kind": "rolling", "train_size": 50, "test_size": 10, "step": 10},
                "model_id": "v1",
            }
        )
        modified = synthetic_data.copy()
        modified.loc[0, "feature"] = 999.0
        r2 = actor.run(
            {
                "action": "pit_hash",
                "data": modified,
                "fold_spec": {"kind": "rolling", "train_size": 50, "test_size": 10, "step": 10},
                "model_id": "v1",
            }
        )
        assert r1.output["pit_hash"] != r2.output["pit_hash"]


# ═══════════════════════════════════════════════════════
# Action: run (full walk-forward)
# ═══════════════════════════════════════════════════════


def _dummy_classifier(train_df: pd.DataFrame):
    """Returns a predict_fn that outputs constant 0.5 (uninformed prior)."""

    def predict(test_df):
        return np.full(len(test_df), 0.5)

    return predict


def _smart_classifier(train_df: pd.DataFrame):
    """Predicts target using feature mean of train (deterministic, learns from train only)."""
    target_mean = float(train_df["target"].mean())

    def predict(test_df):
        return np.full(len(test_df), target_mean)

    return predict


class TestActionRun:
    def test_classification_run_pass(self, patched_db, synthetic_data):
        actor = WalkForwardValidator()
        result = actor.run(
            {
                "action": "run",
                "data": synthetic_data,
                "fold_spec": {"kind": "rolling", "train_size": 50, "test_size": 10, "step": 10},
                "model_id": "dummy_clf",
                "model_fn": _dummy_classifier,
                "target_col": "target",
                "metric_kind": "classification",
            }
        )
        assert result.outcome == Outcome.PASS
        assert result.output["n_folds"] >= 1
        assert "brier_mean" in result.output["metrics"]["aggregate"]
        assert "logloss_mean" in result.output["metrics"]["aggregate"]
        assert "hit_rate_mean" in result.output["metrics"]["aggregate"]

    def test_regression_run_pass(self, patched_db, synthetic_data):
        actor = WalkForwardValidator()
        result = actor.run(
            {
                "action": "run",
                "data": synthetic_data,
                "fold_spec": {"kind": "rolling", "train_size": 50, "test_size": 10, "step": 10},
                "model_id": "dummy_reg",
                "model_fn": _smart_classifier,
                "target_col": "target",
                "metric_kind": "regression",
            }
        )
        assert result.outcome == Outcome.PASS
        assert "mse_mean" in result.output["metrics"]["aggregate"]
        assert "mae_mean" in result.output["metrics"]["aggregate"]

    def test_persisted_to_walkforward_runs(self, patched_db, synthetic_data):
        actor = WalkForwardValidator()
        result = actor.run(
            {
                "action": "run",
                "data": synthetic_data,
                "fold_spec": {"kind": "rolling", "train_size": 50, "test_size": 10, "step": 10},
                "model_id": "persist_test",
                "model_fn": _dummy_classifier,
                "target_col": "target",
                "metric_kind": "classification",
            }
        )
        rows = query(
            "SELECT model_id, n_folds, pit_hash, finished_at FROM walkforward_runs WHERE run_id = ?",
            (result.output["run_id"],),
            db_path=patched_db,
        )
        assert len(rows) == 1
        assert rows[0]["model_id"] == "persist_test"
        assert rows[0]["finished_at"] is not None

    def test_db_path_routes_walkforward_run_to_caller_db(self, tmp_path, monkeypatch, synthetic_data):
        """#711 lock-test: input_data['db_path'] 가 walkforward_runs 를 caller DB 로 보내고
        기본 DB 는 건드리지 않는다. db_path passthrough 를 되돌리면(기본 DB 기록) FAIL —
        explicit-db caller 의 backtests/walkforward_runs split-write 회귀를 잡는다."""
        from nuri.core import db as db_module

        default_db = tmp_path / "default.db"
        caller_db = tmp_path / "caller.db"
        init_db(default_db)
        init_db(caller_db)
        # 기본 DB resolution(=db_path None) 을 tmp default 로 가둬 실제 DB 오염 방지.
        monkeypatch.setattr(db_module, "DB_PATH", default_db)

        actor = WalkForwardValidator()
        result = actor.run(
            {
                "action": "run",
                "data": synthetic_data,
                "fold_spec": {"kind": "rolling", "train_size": 50, "test_size": 10, "step": 10},
                "model_id": "db_path_route",
                "model_fn": _dummy_classifier,
                "target_col": "target",
                "metric_kind": "classification",
                "db_path": caller_db,
            }
        )
        run_id = result.output["run_id"]
        caller_rows = query("SELECT 1 FROM walkforward_runs WHERE run_id = ?", (run_id,), db_path=caller_db)
        default_rows = query("SELECT 1 FROM walkforward_runs WHERE run_id = ?", (run_id,), db_path=default_db)
        assert len(caller_rows) == 1, "walkforward_run 이 caller DB 에 기록돼야 함"
        assert len(default_rows) == 0, "walkforward_run 이 기본 DB 로 새면 안 됨 (split-write)"

    def test_failed_fold_returns_warn(self, patched_db, synthetic_data):
        """일부 fold 의 model_fn 이 raise 하면 outcome=WARN (전체 panic 아님)."""
        call_count = {"n": 0}

        def flaky_model(train_df):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("simulated train failure")
            return _dummy_classifier(train_df)

        actor = WalkForwardValidator()
        result = actor.run(
            {
                "action": "run",
                "data": synthetic_data,
                "fold_spec": {"kind": "rolling", "train_size": 50, "test_size": 10, "step": 10},
                "model_id": "flaky",
                "model_fn": flaky_model,
                "target_col": "target",
                "metric_kind": "classification",
            }
        )
        assert result.outcome == Outcome.WARN
        assert result.output["n_successful"] < result.output["n_folds"]
        # error 가 metrics 에 기록되어 있어야 함
        errored = [f for f in result.output["metrics"]["folds"] if "error" in f]
        assert len(errored) >= 1

    def test_predict_length_mismatch_marks_fold_failed(self, patched_db, synthetic_data):
        """predict_fn 이 잘못된 길이 반환 → 해당 fold error 처리."""

        def broken_model(train_df):
            return lambda test_df: np.array([0.5])  # length 1, expected len(test)

        actor = WalkForwardValidator()
        result = actor.run(
            {
                "action": "run",
                "data": synthetic_data,
                "fold_spec": {"kind": "rolling", "train_size": 50, "test_size": 10, "step": 10},
                "model_id": "len_mismatch",
                "model_fn": broken_model,
                "target_col": "target",
                "metric_kind": "classification",
            }
        )
        assert result.outcome == Outcome.WARN
        assert result.output["n_successful"] == 0


# ═══════════════════════════════════════════════════════
# Input validation
# ═══════════════════════════════════════════════════════


class TestInputValidation:
    def test_invalid_action_blocks(self, patched_db):
        actor = WalkForwardValidator()
        result = actor.run({"action": "weird"})
        assert result.outcome == Outcome.BLOCK

    def test_missing_data_blocks(self, patched_db):
        actor = WalkForwardValidator()
        result = actor.run(
            {
                "action": "run",
                "fold_spec": {"kind": "rolling", "train_size": 10, "test_size": 5, "step": 5},
            }
        )
        assert result.outcome == Outcome.BLOCK

    def test_missing_fold_spec_blocks(self, patched_db, synthetic_data):
        actor = WalkForwardValidator()
        result = actor.run({"action": "run", "data": synthetic_data})
        assert result.outcome == Outcome.BLOCK

    def test_invalid_fold_spec_blocks(self, patched_db, synthetic_data):
        actor = WalkForwardValidator()
        result = actor.run(
            {
                "action": "run",
                "data": synthetic_data,
                "fold_spec": {"kind": "weird", "train_size": 10, "test_size": 5, "step": 5},
            }
        )
        assert result.outcome == Outcome.BLOCK

    def test_missing_model_fn_blocks(self, patched_db, synthetic_data):
        actor = WalkForwardValidator()
        result = actor.run(
            {
                "action": "run",
                "data": synthetic_data,
                "fold_spec": {"kind": "rolling", "train_size": 50, "test_size": 10, "step": 10},
                "target_col": "target",
            }
        )
        assert result.outcome == Outcome.BLOCK

    def test_invalid_target_col_blocks(self, patched_db, synthetic_data):
        actor = WalkForwardValidator()
        result = actor.run(
            {
                "action": "run",
                "data": synthetic_data,
                "fold_spec": {"kind": "rolling", "train_size": 50, "test_size": 10, "step": 10},
                "model_fn": _dummy_classifier,
                "target_col": "nonexistent",
            }
        )
        assert result.outcome == Outcome.BLOCK

    def test_invalid_metric_kind_blocks(self, patched_db, synthetic_data):
        actor = WalkForwardValidator()
        result = actor.run(
            {
                "action": "run",
                "data": synthetic_data,
                "fold_spec": {"kind": "rolling", "train_size": 50, "test_size": 10, "step": 10},
                "model_fn": _dummy_classifier,
                "target_col": "target",
                "metric_kind": "weird",
            }
        )
        assert result.outcome == Outcome.BLOCK

    def test_data_too_small_blocks(self, patched_db):
        actor = WalkForwardValidator()
        small = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=5),
                "target": [0, 1, 0, 1, 0],
            }
        )
        result = actor.run(
            {
                "action": "run",
                "data": small,
                "fold_spec": {"kind": "rolling", "train_size": 50, "test_size": 10, "step": 10},
                "model_fn": _dummy_classifier,
                "target_col": "target",
            }
        )
        assert result.outcome == Outcome.BLOCK
        assert "no valid folds" in result.output["error"]


# ═══════════════════════════════════════════════════════
# Audit trail integration
# ═══════════════════════════════════════════════════════


class TestAuditTrail:
    def test_run_logged_to_audit_ledger(self, patched_db, synthetic_data):
        actor = WalkForwardValidator()
        actor.run(
            {
                "action": "run",
                "data": synthetic_data,
                "fold_spec": {"kind": "rolling", "train_size": 50, "test_size": 10, "step": 10},
                "model_id": "audit_test",
                "model_fn": _dummy_classifier,
                "target_col": "target",
                "metric_kind": "classification",
            }
        )
        rows = query(
            "SELECT actor_name, layer, outcome FROM agent_audit_ledger WHERE actor_name = 'walkforward-validator'",
            db_path=patched_db,
        )
        assert len(rows) >= 1
        assert rows[0]["layer"] == "B"
        assert rows[0]["outcome"] == "pass"

    def test_pit_hash_action_logged(self, patched_db, synthetic_data):
        actor = WalkForwardValidator()
        actor.run(
            {
                "action": "pit_hash",
                "data": synthetic_data,
                "fold_spec": {"kind": "rolling", "train_size": 50, "test_size": 10, "step": 10},
                "model_id": "hash_test",
            }
        )
        rows = query(
            "SELECT outcome FROM agent_audit_ledger WHERE actor_name = 'walkforward-validator'",
            db_path=patched_db,
        )
        assert any(r["outcome"] == "pass" for r in rows)


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════


class TestCli:
    def test_cli_pit_hash(self, tmp_path, patched_db, capsys):
        from nuri.agents.actors.walkforward_validator import main

        csv_path = tmp_path / "data.csv"
        df = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=100),
                "feature": np.random.default_rng(0).normal(0, 1, 100),
                "target": np.random.default_rng(0).integers(0, 2, 100),
            }
        )
        df.to_csv(csv_path, index=False)
        rc = main(["pit_hash", "--csv", str(csv_path), "--model-id", "cli_test"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "pit_hash" in out

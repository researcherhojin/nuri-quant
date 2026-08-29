"""Evidence 바인딩 컬럼 잠금 (#1305) — Gotcha-Test Pair.

세 원장(backtests · walkforward_runs · decision_outcomes)의 writer 가
`code_rev` / `execution_config_sha_v1` 을 self-measured 로 채우는지 **행을 읽어서**
잠근다. writer 에서 채움 한 줄을 지우면 FAIL. backtests 쪽은
`tests/core/test_research_ops.py::TestTheRevisionIsRecordedButNeverInvented` 가 잠근다.

`execution_config_sha_v1()` 자체의 계약(closure 동결·None 규칙)도 여기서 잠근다 —
mixed-sample 규칙은 `tests/quant/test_evidence_binding.py`.
"""

from __future__ import annotations

import pytest

from nuri.core.db import init_db, log_decision, log_decision_outcome, log_walkforward_run, provenance, query


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "evidence.db"
    init_db(p)
    return p


def _log_wf(db_path, **overrides):
    kwargs = dict(
        run_id="wf-1",
        model_id="hmm-v1",
        fold_spec={"kind": "rolling", "train_size": 100, "test_size": 20, "step": 20},
        metrics={"aggregate": {"brier": 0.2}},
        pit_hash="pit-abc",
        n_folds=5,
        db_path=db_path,
    )
    kwargs.update(overrides)
    return log_walkforward_run(**kwargs)


def _log_outcome(db_path, **overrides):
    # decision_outcomes 는 agent_decisions FK (PRAGMA foreign_keys=ON) — 부모 행 선행.
    log_decision(
        decision_id="d-1",
        ticker="TEST",
        as_of_date="2026-08-29",
        action="BUY",
        conviction=0.5,
        inputs={"regime_run_id": "r1", "hypothesis_id": "h1", "causal_audit_id": "c1"},
        rationale={"why": "test"},
        status="emitted",
        db_path=db_path,
    )
    kwargs = dict(
        decision_id="d-1",
        observation_window=7,
        tracked_as_of_date="2026-09-05",
        hypothesis_validation="pass",
        db_path=db_path,
    )
    kwargs.update(overrides)
    return log_decision_outcome(**kwargs)


class TestWalkforwardRunCarriesBinding:
    def test_insert_fills_both_columns(self, db_path):
        _log_wf(db_path)
        row = query("SELECT code_rev, execution_config_sha_v1 FROM walkforward_runs", db_path=db_path)[0]
        assert row["code_rev"], "walk-forward 행이 산출 코드를 특정하지 못한다"
        assert row["execution_config_sha_v1"], "walk-forward 행이 산출 설정을 특정하지 못한다"

    def test_rerun_upsert_refreshes_binding(self, db_path, monkeypatch):
        """재실행(upsert)은 새 코드의 산출이다 — 바인딩이 첫 실행 값에 얼어붙으면
        정정 run 이 낡은 코드에 귀속되어 #1115 가 막으려던 상황이 재현된다."""
        _log_wf(db_path)
        monkeypatch.setattr(provenance, "_CODE_REV_CACHE", "newrev-1305")
        _log_wf(db_path, metrics={"aggregate": {"brier": 0.1}})
        rows = query("SELECT code_rev FROM walkforward_runs", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["code_rev"] == "newrev-1305"


class TestDecisionOutcomeCarriesBinding:
    def test_insert_fills_both_columns(self, db_path):
        _log_outcome(db_path)
        row = query("SELECT code_rev, execution_config_sha_v1 FROM decision_outcomes", db_path=db_path)[0]
        assert row["code_rev"], "outcome 행이 산출 코드를 특정하지 못한다"
        assert row["execution_config_sha_v1"], "outcome 행이 산출 설정을 특정하지 못한다"

    def test_recompute_upsert_refreshes_binding(self, db_path, monkeypatch):
        _log_outcome(db_path)
        monkeypatch.setattr(provenance, "_CODE_REV_CACHE", "newrev-1305")
        _log_outcome(db_path, hypothesis_validation="reject")
        rows = query("SELECT code_rev, hypothesis_validation FROM decision_outcomes", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["code_rev"] == "newrev-1305"
        assert rows[0]["hypothesis_validation"] == "reject"


class TestExecutionConfigShaV1:
    """closure 는 rules+agents+signals 로 **동결** — 바꾸려면 _v2 (#1305 Codex P1).

    같은 컬럼명 아래에서 closure 가 바뀌면 행 간 비교가 불능이 되고 cherry-pick
    소재가 된다.
    """

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        provenance._CONFIG_SHA_CACHE = provenance._CONFIG_SHA_UNSET
        yield
        provenance._CONFIG_SHA_CACHE = provenance._CONFIG_SHA_UNSET

    @pytest.fixture
    def fake_root(self, tmp_path, monkeypatch):
        for rel in provenance._CONFIG_CLOSURE_V1:
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"# {rel}\nkey: value\n")
        monkeypatch.setattr(provenance, "_REPO_ROOT", tmp_path)
        return tmp_path

    def test_the_closure_is_frozen_to_v1(self):
        assert provenance._CONFIG_CLOSURE_V1 == (
            "config/rules.yaml",
            "config/agents.yaml",
            "config/signals.yaml",
            "config/walkforward.yaml",
            "config/walkforward_variants.yaml",
            "config/walkforward_exits.yaml",
            "config/walkforward_exits_growth.yaml",
        ), "closure 를 바꿨다 — _v1 컬럼의 의미가 깨진다. execution_config_sha_v2 로 갈 것"

    def test_the_closure_files_exist_in_the_real_repo(self):
        """closure 에 등재된 파일이 레포에서 사라지면 모든 신규 행이 조용히 None 이 된다.

        rename/삭제 PR 이 이 테스트로 잡혀야 _v2 승계를 논의할 수 있다.
        """
        for rel in provenance._CONFIG_CLOSURE_V1:
            assert (provenance._REPO_ROOT / rel).is_file(), f"{rel} 이 없다 — closure 가 죽었다"

    def test_same_content_same_sha(self, fake_root):
        first = provenance.execution_config_sha_v1()
        provenance._CONFIG_SHA_CACHE = provenance._CONFIG_SHA_UNSET
        assert first == provenance.execution_config_sha_v1()
        assert first and len(first) == 32

    def test_changed_rule_changes_the_sha(self, fake_root):
        before = provenance.execution_config_sha_v1()
        provenance._CONFIG_SHA_CACHE = provenance._CONFIG_SHA_UNSET
        (fake_root / "config/rules.yaml").write_text("stop_loss: -0.07\n")
        assert provenance.execution_config_sha_v1() != before

    def test_content_moving_across_a_file_boundary_changes_the_sha(self, fake_root):
        """내용만 이어붙이면 A 끝↔B 앞 이동이 같은 해시를 낸다 — 파일명 구분자 잠금."""
        (fake_root / "config/rules.yaml").write_text("ab")
        (fake_root / "config/agents.yaml").write_text("c")
        before = provenance.execution_config_sha_v1()
        provenance._CONFIG_SHA_CACHE = provenance._CONFIG_SHA_UNSET
        (fake_root / "config/rules.yaml").write_text("a")
        (fake_root / "config/agents.yaml").write_text("bc")
        assert provenance.execution_config_sha_v1() != before

    def test_a_missing_closure_file_yields_none_not_a_partial_hash(self, fake_root):
        """부분 해시는 다른 closure 의 해시와 구분이 안 되는 제3의 값 — 지어내지 않는다."""
        (fake_root / "config/signals.yaml").unlink()
        assert provenance.execution_config_sha_v1() is None

    def test_the_sha_is_read_once_per_process(self, fake_root, monkeypatch):
        """walk-forward 루프가 행마다 부른다 — 파일 3개 재독을 행 수만큼 반복하지 않는다."""
        first = provenance.execution_config_sha_v1()
        (fake_root / "config/rules.yaml").write_text("changed: true\n")
        assert provenance.execution_config_sha_v1() == first, "캐시가 안 먹는다"

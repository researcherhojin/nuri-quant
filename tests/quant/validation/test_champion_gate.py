"""Champion-challenger 게이트 잠금 (#1307) — Gotcha-Test Pair.

순차 통제 3축을 각각 잠근다: 반감 alpha-spending / attempt ledger 누적 /
holdout retirement. 그리고 핵심 계약 — **기계는 기각만 자동, 승격은 제안까지** —
이 캠페인 내 통과(runner)와 캠페인 간 임계(sequential)의 AND 로 구현돼 있음을 잠근다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import init_db, log_challenger_attempt, query
from nuri.quant.validation.champion_gate import (
    adjudicate,
    campaign_alpha,
    holdout_uses,
    next_campaign_seq,
)

GATE_CFG = {"alpha_total": 0.05, "holdout_max_uses": 3, "holdout_version": "h1"}


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "gate.db"
    init_db(p)
    return p


def _variant(name, *, baseline=False, p_value=0.001, eligible=True, holdout=0.8):
    return {
        "name": name,
        "baseline": baseline,
        "p_value": None if baseline else p_value,
        "oos_sharpe_pooled": 1.0,
        "holdout_sharpe": holdout,
        "promotion_eligible": eligible,
        "discovery_passed": eligible,
        "holdout_passed": eligible,
        "alpha_effective": 0.05,
        "walkforward_run_id": f"wf-{name}",
    }


def _run_result(variants):
    return {"n_test_variants": sum(1 for v in variants if not v.get("baseline")), "variants": variants}


class TestCampaignAlpha:
    def test_halving_never_exhausts_the_budget(self):
        """sum_{j>=1} alpha/2^j = alpha — 캠페인을 무한 반복해도 평생 예산 불변."""
        assert campaign_alpha(0.05, 1) == pytest.approx(0.025)
        assert campaign_alpha(0.05, 2) == pytest.approx(0.0125)
        total = sum(campaign_alpha(0.05, j) for j in range(1, 60))
        # 수학적으로는 엄격히 미만이나 60항이면 float 이 0.05 로 반올림된다 — 초과만 금지
        assert total <= 0.05 + 1e-12

    def test_seq_below_one_raises(self):
        with pytest.raises(ValueError):
            campaign_alpha(0.05, 0)


class TestAdjudicate:
    def test_eligible_and_sequentially_significant_is_a_candidate_not_a_promotion(self, db_path):
        """promotion_candidate 는 제안이다 — 원장 verdict 문자열 자체가 계약이고,
        승격 상태는 이 시스템 어디에도 기계가 쓸 수 없다 (§2.6 운용 원칙 5)."""
        res = adjudicate(
            _run_result([_variant("v0", baseline=True), _variant("v2", p_value=0.001)]),
            gate_config=GATE_CFG,
            db_path=db_path,
        )
        assert res["promotion_candidates"] == ["v2"]
        row = query("SELECT * FROM challenger_attempts", db_path=db_path)[0]
        assert row["verdict"] == "promotion_candidate"
        assert row["champion"] == "v0"
        # #1305 evidence 바인딩 소비 — attempt 행이 산출 코드·설정을 특정한다
        assert row["code_rev"] and row["execution_config_sha_v1"]

    def test_runner_pass_alone_is_not_enough_the_sequential_threshold_also_binds(self, db_path):
        """runner 의 정적 alpha(0.05/k) 통과가 순차 임계(0.025/k)를 못 넘으면 기각.

        이 AND 를 지우면 게이트는 기존 runner 의 재포장일 뿐이고 시간축 통제가
        사라진다 — #1307 의 존재 이유.
        """
        res = adjudicate(
            _run_result([_variant("v0", baseline=True), _variant("v2", p_value=0.03, eligible=True)]),
            gate_config=GATE_CFG,
            db_path=db_path,
        )
        # 캠페인 1: 0.05/2 = 0.025, n_test=1 → 임계 0.025. p=0.03 은 탈락.
        assert res["promotion_candidates"] == []
        assert query("SELECT verdict FROM challenger_attempts", db_path=db_path)[0]["verdict"] == "rejected"

    def test_rejections_accumulate_and_tighten_the_next_campaign(self, db_path):
        """기각 이력이 다음 캠페인의 임계를 반감시킨다 — 이력이 사라지면 spending 붕괴."""
        first = adjudicate(
            _run_result([_variant("v0", baseline=True), _variant("v2", p_value=0.9, eligible=False)]),
            gate_config=GATE_CFG,
            db_path=db_path,
        )
        second = adjudicate(
            _run_result([_variant("v0", baseline=True), _variant("v2", p_value=0.9, eligible=False)]),
            gate_config=GATE_CFG,
            db_path=db_path,
        )
        assert (first["campaign_seq"], second["campaign_seq"]) == (1, 2)
        assert second["sequential_alpha_effective"] == pytest.approx(first["sequential_alpha_effective"] / 2.0)
        assert next_campaign_seq("variant", db_path=db_path) == 3

    def test_holdout_retires_after_max_uses(self, db_path):
        """봉인 구간은 max_uses 회 열람 후 은퇴 — 이후는 eligible 이어도 승격 제안 불가."""
        for _ in range(3):
            adjudicate(
                _run_result([_variant("v0", baseline=True), _variant("v2", p_value=0.001)]),
                gate_config=GATE_CFG,
                db_path=db_path,
            )
        res = adjudicate(
            _run_result([_variant("v0", baseline=True), _variant("v2", p_value=0.001)]),
            gate_config=GATE_CFG,
            db_path=db_path,
        )
        assert res["holdout_retired"] is True
        assert res["promotion_candidates"] == []
        rows = query("SELECT verdict FROM challenger_attempts WHERE campaign_seq = 4", db_path=db_path)
        assert [r["verdict"] for r in rows] == ["holdout_retired"]

    def test_sealed_holdout_does_not_consume_a_use(self, db_path):
        """discovery 미통과로 봉인을 안 열었으면(holdout_sharpe None) 소비가 아니다."""
        adjudicate(
            _run_result(
                [_variant("v0", baseline=True, holdout=None), _variant("v2", p_value=0.9, eligible=False, holdout=None)]
            ),
            gate_config=GATE_CFG,
            db_path=db_path,
        )
        assert holdout_uses("variant", "h1:variant", db_path=db_path) == 0

    def test_baseline_gets_no_ledger_row(self, db_path):
        adjudicate(
            _run_result([_variant("v0", baseline=True), _variant("v2")]),
            gate_config=GATE_CFG,
            db_path=db_path,
        )
        rows = query("SELECT challenger FROM challenger_attempts", db_path=db_path)
        assert [r["challenger"] for r in rows] == ["v2"]


class TestLedgerWriter:
    def test_invalid_verdict_and_axis_rejected(self, db_path):
        with pytest.raises(ValueError):
            log_challenger_attempt("variant", 1, "v2", "promoted", 0.01, db_path=db_path)
        with pytest.raises(ValueError):
            log_challenger_attempt("variant", 1, "v2", "rejected", 0.01, evidence_axis="vibes", db_path=db_path)
        with pytest.raises(ValueError):
            log_challenger_attempt("variant", 0, "v2", "rejected", 0.01, db_path=db_path)


class TestCli:
    """CLI 는 원장/설정의 읽기 표면 — 전역 격리 DB(conftest) 위에서 실행."""

    def test_status_reports_next_campaign_and_holdout(self, capsys):
        import json as _json

        from nuri.quant.validation.champion_gate import main

        assert main(["status", "--family", "variant"]) == 0
        out = _json.loads(capsys.readouterr().out)
        assert out["next_campaign_seq"] == 1
        assert out["holdout_retired"] is False

    def test_history_lists_recorded_attempts(self, capsys):
        import json as _json

        from nuri.quant.validation.champion_gate import main

        log_challenger_attempt("variant", 1, "v2", "rejected", 0.0125)
        assert main(["history", "--family", "variant"]) == 0
        rows = _json.loads(capsys.readouterr().out)
        assert [r["challenger"] for r in rows] == ["v2"]

    def test_module_entrypoint_runs(self, monkeypatch):
        """`python -m nuri.quant.validation.champion_gate status` — pragma 대신 runpy 잠금
        (tests/quant/test_main_runpy.py 관례: no-cover 로 가리지 않는다)."""
        import io
        import runpy
        import sys

        captured = io.StringIO()
        monkeypatch.setattr(sys, "argv", ["champion_gate", "status"])
        monkeypatch.setattr(sys, "stdout", captured)
        try:
            runpy.run_module("nuri.quant.validation.champion_gate", run_name="__main__")
        except SystemExit as exc:
            assert exc.code in (0, None)
        assert "next_campaign_seq" in captured.getvalue()

    def test_missing_gate_section_is_a_preregistration_error(self, tmp_path):
        from nuri.quant.validation.champion_gate import _load_gate_config

        bare = tmp_path / "wf.yaml"
        bare.write_text("gate: {}\n")
        with pytest.raises(ValueError, match="champion_gate"):
            _load_gate_config(bare)


class TestRunnerWiring:
    def test_gate_true_adjudicates_and_writes_the_ledger(self, db_path):
        """runner → 게이트 배선 e2e — `gate=True` 가 attempt 원장까지 닿는다.

        이 배선을 지우면 runner 는 측정만 하고 캠페인이 원장에 안 남는다 —
        adjudicate 단위 테스트만으로는 안 잡힌다 (Mutation Axes + Wiring).
        """
        from nuri.quant.validation.variant_walkforward import run_variant_search

        cfg = {
            "portfolio": {"top_n": 2, "rebalance_days": 2},
            "fold": {"kind": "rolling", "train_size": 10, "test_size": 5, "step": 5},
            "holdout": {"frac": 0.2},
            "costs": {"survivorship_haircut_bps_annual": 200},
            "gate": {
                "min_oos_sharpe": 0.5,
                "min_holdout_sharpe": 0.0,
                "permutation": {"n": 10, "alpha": 0.05, "seed": 0},
                "multiple_comparison": "bonferroni",
            },
            "variants": [
                {
                    "name": "v0",
                    "select": "momentum",
                    "baseline": True,
                    "theory": "control",
                    "params": [{"lookback": 2}],
                },
                {"name": "v2", "select": "vol_scaled", "theory": "vol-scaled", "params": [{"lookback": 3}]},
            ],
        }
        idx = pd.date_range("2024-01-01", periods=40, freq="B")
        rng = {"AAA": 0.001, "BBB": 0.002, "CCC": 0.003, "DDD": 0.004}
        close = pd.DataFrame(
            {t: 100.0 * np.cumprod(1.0 + s + 0.002 * np.sin(np.arange(40))) for t, s in rng.items()},
            index=idx,
        )
        vol = pd.DataFrame(1e6, index=idx, columns=close.columns)

        r = run_variant_search(
            cost_bps=10.0,
            fx_series=pd.Series(1300.0, index=idx),
            close=close,
            vol=vol,
            config=cfg,
            persist=True,
            gate=True,
            db_path=db_path,
        )

        assert r["gate"]["campaign_seq"] == 1
        rows = query("SELECT challenger, verdict, code_rev FROM challenger_attempts", db_path=db_path)
        assert [row["challenger"] for row in rows] == ["v2"]
        assert rows[0]["code_rev"]

    def test_gate_requires_persist(self):
        """원장에 없는 근거로는 승격 제안이 성립하지 않는다."""
        from nuri.quant.validation.variant_walkforward import run_variant_search

        idx = pd.date_range("2024-01-01", periods=10, freq="B")
        close = pd.DataFrame({"AAA": np.linspace(100, 110, 10)}, index=idx)
        with pytest.raises(ValueError, match="persist"):
            run_variant_search(
                cost_bps=10.0,
                fx_series=pd.Series(1300.0, index=idx),
                close=close,
                gate=True,
                persist=False,
            )

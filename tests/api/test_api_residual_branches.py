"""API 라우트의 나머지 분기 — 레짐 미상 스냅샷 · 리포트 없는 최신 디렉터리 · alpha 미측정 완료행."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from nuri.api.routes import alpha, evidence, stream
from nuri.core.db import get_db, init_db


@pytest.fixture
def default_db(tmp_path, monkeypatch):
    import nuri.core.db as dbmod

    path = tmp_path / "api.db"
    init_db(path)
    monkeypatch.setattr(dbmod, "DB_PATH", path)
    return path


def test_a_snapshot_without_a_regime_reading_carries_no_regime_fields(default_db, monkeypatch):
    monkeypatch.setattr(stream, "_cache", {})
    monkeypatch.setattr(stream, "_cache_time", 0)
    monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda *a, **k: None)

    snap = stream._get_snapshot()

    assert not {"regime", "confidence", "vix", "fear_greed"} & set(snap)
    assert snap["open_positions"] == 0


def test_a_dated_dir_without_either_report_is_a_404(tmp_path, monkeypatch):
    (tmp_path / "2020-01-02" / "evidence").mkdir(parents=True)  # 차트 디렉터리만 있고 md 는 없다
    monkeypatch.setattr(evidence, "REPORT_DIR", tmp_path)

    with pytest.raises(HTTPException) as exc:
        evidence.get_evidence_report()

    assert exc.value.status_code == 404


def test_a_completed_window_without_alpha_is_not_an_effective_bet(default_db):
    """수익률은 측정됐지만 벤치마크가 없어 alpha 가 비면 완료로는 세되 표본(effective bet)은 아니다."""
    with get_db(default_db) as conn:
        conn.execute(
            """INSERT INTO agent_decisions (decision_id, ticker, as_of_date, action, conviction,
                   inputs_json, rationale_json, status) VALUES ('d-1', 'TST_A', '2026-09-01', 'BUY', 0.8, '{}', '{}', 'emitted')"""
        )
        conn.execute(
            """INSERT INTO decision_outcomes (decision_id, observation_window, tracked_as_of_date, realized_return,
                   benchmark_return, alpha, hit_threshold, hypothesis_validation)
               VALUES ('d-1', 7, '2026-09-08', 0.02, NULL, NULL, 0, 'insufficient_data')"""
        )

    out = alpha.alpha_summary()

    seven = next(w for w in out["windows"] if w["window"] == 7)
    assert (seven["n_completed"], seven["n_clean"]) == (1, 0)
    assert out["effective_bets"] == 0

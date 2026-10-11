"""recommend 계층의 나머지 분기 — 리더 가격 트리 · rank_floor 없는 그리드 · tracker `-m` 보고 전용 실행."""

from __future__ import annotations

import io
import runpy
import sys

import pytest

from nuri.trading.recommend.held_add_would_fire import compute_grid_thresholds
from nuri.trading.recommend.price_targets import format_target_tree


def test_a_leader_tree_has_no_fixed_take_profit_ladder():
    """리더(성장주)는 고정 익절 대신 이동평균 이탈로 청산한다 — 1·2차 익절과 트레일링 줄이 없다."""
    tree = format_target_tree(
        {
            "ticker": "TST_LEAD",
            "stock_type": "growth",
            "current_price": 168.0,
            "entry_price": 165.0,
            "stop_loss": 153.45,
            "stop_loss_pct": -7.0,
            "target_1": None,
            "is_leader": True,
            "leader_ma": 150.0,
            "leader_ma_period": 50,
            "analyst_target": None,
        }
    )

    assert "1차 익절" not in tree and "2차 익절" not in tree and "트레일링" not in tree
    assert "⭐ 리더 (성장주): 고정 익절 미적용 — 50일선" in tree
    assert tree.splitlines()[-1].startswith("└──")


def test_a_grid_without_rank_floor_has_no_rank_floor_variant():
    current = {"tp1_residual_add": 75.0, "ride_winner": 75.0, "average_down": 80.0}

    grid = compute_grid_thresholds([60.0, 70.0, 80.0], current, {"absolute": [55], "percentiles": [70]})

    assert set(grid) == {"current", "abs_55", "p70"}


def test_the_tracker_entry_point_without_save_only_reports(monkeypatch):
    """`--save` 가 없으면 후보 선별·저장·추적을 건드리지 않고 보고만 한다. runpy 는 모듈을 다시 실행하므로
    경계는 다른 모듈(candidates)에 둔다 — 불리면 테스트가 실패한다."""
    monkeypatch.setattr(
        "nuri.trading.recommend.candidates.screen_candidates",
        lambda *a, **k: pytest.fail("보고 전용 실행이 후보 선별을 돌렸다"),
    )
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "argv", ["tracker"])
    monkeypatch.setattr(sys, "stdout", stdout)

    runpy.run_module("nuri.trading.recommend.tracker", run_name="__main__")

    out = stdout.getvalue()
    assert "Recommendation Tracking Report" in out and "Total recommendations: 0" in out

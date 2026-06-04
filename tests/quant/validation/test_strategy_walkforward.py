"""Lock-tests for strategy walk-forward adapter (P1b 검증 창고).

- known-answer: _sharpe_from_returns 손계산 일치 + _max_drawdown 손계산
- mandatory gate: cost_bps / fx_series None → ValueError (gross/통화-naive 차단)
- cost·FX 가 실제로 net return 에 반영됨 (cargo-cult 아님) — monotonicity lock
- frozen universe: .KS 제외 (통화 혼합 방지)
- WalkForwardValidator 무수정 구동 + walkforward_runs 1행 기록 (P1a 엔드포인트로 surface)
- FROZEN holdout 은 walk-forward fold 가 보지 않음
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from nuri.agents.actors.walkforward_validator import _sharpe_from_returns
from nuri.quant.validation.strategy_walkforward import (
    _build_us_panel,
    _max_drawdown,
    _strategy_net_returns,
    run_strategy_walkforward,
)

SQRT252 = math.sqrt(252)

# 작은 pre-registered config — 빠른 fold 구성 (train 10 / test 5 / holdout 20%)
SMALL_CFG = {
    "strategy": {"lookback_grid": [2, 3], "top_n": 2, "rebalance_days": 2},
    "fold": {"kind": "rolling", "train_size": 10, "test_size": 5, "step": 5},
    "holdout": {"frac": 0.2},
    "costs": {"survivorship_haircut_bps_annual": 200},
    "gate": {"min_oos_sharpe": 0.5, "min_holdout_sharpe": 0.0},
}


def _panel(n: int = 30, tickers=("AAA", "BBB", "CCC", "DDD")) -> pd.DataFrame:
    """결정론적 US close 패널 — 종목별 상이한 추세 + sin 변동(std>0 보장)."""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    data = {}
    for k, t in enumerate(tickers):
        steps = 0.001 * (k + 1) + 0.002 * np.sin(np.arange(n))
        data[t] = 100.0 * np.cumprod(1.0 + steps)
    return pd.DataFrame(data, index=dates)


def _flat_fx(idx: pd.Index, rate: float = 1300.0) -> pd.Series:
    return pd.Series(rate, index=idx, dtype=float)


# ── known-answer ──────────────────────────────────────────────


class TestKnownAnswer:
    def test_sharpe_hand_computed(self):
        # returns=[0.01,0.02,0.03]: mean=0.02, std(ddof=1)=0.01 → Sharpe = 2*sqrt(252)
        r = np.array([0.01, 0.02, 0.03])
        assert _sharpe_from_returns(r) == pytest.approx(2.0 * SQRT252, rel=1e-9)

    def test_max_drawdown_hand_computed(self):
        # cum=[1.1, 0.55, 0.55], peak=1.1 → trough dd = 0.55/1.1 - 1 = -0.5
        assert _max_drawdown(np.array([0.1, -0.5, 0.0])) == pytest.approx(-0.5)

    def test_max_drawdown_monotonic_up_is_zero(self):
        assert _max_drawdown(np.array([0.01, 0.02, 0.01])) == pytest.approx(0.0)

    def test_max_drawdown_empty(self):
        assert _max_drawdown(np.array([])) == 0.0


# ── mandatory cost / FX gate ──────────────────────────────────


class TestMandatoryInputs:
    def test_refuses_without_cost(self):
        with pytest.raises(ValueError, match="cost_bps"):
            run_strategy_walkforward(cost_bps=None, fx_series=_flat_fx(_panel().index), prices=_panel())

    def test_refuses_without_fx(self):
        with pytest.raises(ValueError, match="fx_series"):
            run_strategy_walkforward(cost_bps=10.0, fx_series=None, prices=_panel())

    def test_refuses_too_few_rows(self):
        # < 2 row → 즉시 거부 (empty/단일 row guard)
        one = _panel(n=1)
        with pytest.raises(ValueError, match="insufficient price history"):
            run_strategy_walkforward(cost_bps=10.0, fx_series=_flat_fx(one.index), prices=one, config=SMALL_CFG)

    def test_refuses_insufficient_after_warmup(self):
        # row 는 있지만 warmup(max lookback) 이후 fold 구성 불가 → 거부
        tiny = _panel(n=5)
        with pytest.raises(ValueError):
            run_strategy_walkforward(cost_bps=10.0, fx_series=_flat_fx(tiny.index), prices=tiny, config=SMALL_CFG)


# ── cost / FX genuinely applied (not cargo-cult) ──────────────


class TestCostFxApplied:
    def test_higher_cost_lowers_net(self):
        p = _panel()
        fx_ret = _flat_fx(p.index).pct_change().reindex(p.index).fillna(0.0)
        lo = _strategy_net_returns(p, fx_ret, 3, 2, 2, cost_bps=0.0, haircut_daily=0.0)
        hi = _strategy_net_returns(p, fx_ret, 3, 2, 2, cost_bps=100.0, haircut_daily=0.0)
        # 거래비용이 클수록 누적 net 이 낮다 (turnover 발생 구간에서만 차감 → strictly lower)
        assert hi.sum() < lo.sum()

    def test_fx_drift_changes_net(self):
        p = _panel()
        flat = _flat_fx(p.index).pct_change().reindex(p.index).fillna(0.0)  # 변화 0
        rising = pd.Series(1300.0 * (1.001 ** np.arange(len(p))), index=p.index)
        rising_ret = rising.pct_change().reindex(p.index).fillna(0.0)
        base = _strategy_net_returns(p, flat, 3, 2, 2, cost_bps=0.0, haircut_daily=0.0)
        fxd = _strategy_net_returns(p, rising_ret, 3, 2, 2, cost_bps=0.0, haircut_daily=0.0)
        # FX 상승(원화 약세)은 US 보유분의 KRW net 을 끌어올린다 → 다름
        assert not np.allclose(base.to_numpy(), fxd.to_numpy())
        assert fxd.sum() > base.sum()

    def test_haircut_lowers_net(self):
        p = _panel()
        fx_ret = _flat_fx(p.index).pct_change().reindex(p.index).fillna(0.0)
        no_hc = _strategy_net_returns(p, fx_ret, 3, 2, 2, cost_bps=0.0, haircut_daily=0.0)
        hc = _strategy_net_returns(p, fx_ret, 3, 2, 2, cost_bps=0.0, haircut_daily=0.001)
        assert hc.sum() < no_hc.sum()

    def test_warmup_is_zero(self):
        p = _panel()
        fx_ret = _flat_fx(p.index).pct_change().reindex(p.index).fillna(0.0)
        net = _strategy_net_returns(p, fx_ret, 5, 2, 2, cost_bps=10.0, haircut_daily=0.001)
        assert (net.iloc[:5] == 0.0).all()  # 보유 전 구간은 net=0 (FX 노출 없음)


# ── integration: drives validator + logs walkforward_runs ─────


class TestIntegration:
    def test_run_returns_summary_and_logs(self, db_path_mp):
        from nuri.core.db import query

        p = _panel(n=30)
        result = run_strategy_walkforward(cost_bps=10.0, fx_series=_flat_fx(p.index), prices=p, config=SMALL_CFG)
        # 요약 dict 구조
        assert result["model_id"] == "momentum-topN-walkforward"
        assert result["walkforward_run_id"]
        assert result["n_folds"] >= 1
        assert result["frozen_universe_n"] == 4
        assert result["cost_bps"] == 10.0
        assert result["selected_lookback_holdout"] in (2, 3)
        assert isinstance(result["holdout_max_drawdown"], float)
        assert result["holdout_max_drawdown"] <= 0.0
        assert isinstance(result["gate"]["passed"], bool)

        # WalkForwardValidator 가 walkforward_runs 에 기록 → P1a 엔드포인트로 surface
        rows = query(
            "SELECT run_id, model_id FROM walkforward_runs WHERE run_id = ?",
            (result["walkforward_run_id"],),
            db_path=db_path_mp,
        )
        assert len(rows) == 1
        assert rows[0]["model_id"] == "momentum-topN-walkforward"

    def test_end_to_end_from_db_with_real_config(self, db_path_mp):
        # config/prices 모두 미지정 → 실제 config/walkforward.yaml 로드 + _build_us_panel(DB) 경로.
        # 실제 config 는 train 252 + holdout 0.2 → warmup 120 후 충분한 row 시드 (520).
        from nuri.core.db import get_db, query

        p = _panel(n=520)
        with get_db(db_path_mp) as conn:
            conn.executemany(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                [(t, d.strftime("%Y-%m-%d"), float(p.loc[d, t])) for t in p.columns for d in p.index],
            )
        result = run_strategy_walkforward(cost_bps=10.0, fx_series=_flat_fx(p.index))
        assert result["n_folds"] >= 1
        assert result["frozen_universe_n"] == 4
        assert result["holdout_n"] > 0
        # 실제 config 라도 walkforward_runs 기록은 동일
        rows = query(
            "SELECT run_id FROM walkforward_runs WHERE run_id = ?",
            (result["walkforward_run_id"],),
            db_path=db_path_mp,
        )
        assert len(rows) == 1

    def test_holdout_reserved(self, db_path_mp):
        # warmup 3 → 27 rows, holdout frac 0.2 → holdout_n=5, walkforward_n=22? 봉인 검증.
        p = _panel(n=30)
        result = run_strategy_walkforward(cost_bps=10.0, fx_series=_flat_fx(p.index), prices=p, config=SMALL_CFG)
        # holdout 은 walk-forward 가 보지 않는 별도 구간 (둘의 합 = warmup 이후 전체)
        assert result["holdout_n"] > 0
        assert result["walkforward_n"] + result["holdout_n"] == 30 - max(SMALL_CFG["strategy"]["lookback_grid"])
        # holdout 평가가 실제로 돌았다 (maxDD 산출됨)
        assert result["holdout_max_drawdown"] <= 0.0


# ── frozen survivor universe ──────────────────────────────────


class TestFrozenUniverse:
    def test_build_panel_excludes_kr(self, db_path):
        from nuri.core.db import get_db

        with get_db(db_path) as conn:
            for t in ("AAA", "005930.KS"):
                for d in pd.date_range("2024-01-01", periods=5, freq="B"):
                    conn.execute(
                        "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                        (t, d.strftime("%Y-%m-%d"), 100.0),
                    )
        panel = _build_us_panel(db_path=db_path)
        assert "AAA" in panel.columns
        assert "005930.KS" not in panel.columns  # 통화 혼합 방지

    def test_build_panel_empty_db(self, db_path):
        assert _build_us_panel(db_path=db_path).empty

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
    _load_wf_config,
    _max_drawdown,
    _portfolio_usd_returns,
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
    "gate": {
        "min_oos_sharpe": 0.5,
        "min_holdout_sharpe": 0.0,
        "permutation": {"n": 10, "alpha": 0.05, "seed": 0},  # 테스트는 소표본 (속도)
    },
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

    def test_loads_real_config(self):
        # config=None 경로의 _load_wf_config (fast unit — 전체 파이프라인 불필요)
        cfg = _load_wf_config()
        assert "strategy" in cfg and "fold" in cfg
        assert "permutation" in cfg["gate"]  # #701 순열 블록 존재

    def test_run_builds_panel_from_db(self, db_path_mp):
        # prices=None → _build_us_panel(DB) 경로 (fast — SMALL_CFG, 소표본 순열)
        from nuri.core.db import get_db

        p = _panel(n=30)
        with get_db(db_path_mp) as conn:
            conn.executemany(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                [(t, d.strftime("%Y-%m-%d"), float(p.loc[d, t])) for t in p.columns for d in p.index],
            )
        r = run_strategy_walkforward(
            cost_bps=10.0, fx_series=_flat_fx(p.index), config=SMALL_CFG
        )  # prices 미지정 → DB 패널
        assert r["frozen_universe_n"] == 4
        assert "oos_sharpe_pooled" in r

    @pytest.mark.slow  # 실제 config = 200 순열 × 520-row 패널 (heavy integration smoke)
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


# ── same-bar lookahead 회귀 (결정론적 micro-case) ──────────────


class TestNoSameBarLookahead:
    """리밸런싱일 점프가 그날 수익으로 적립되면 안 된다 (§5.3.1 Gotcha-Test Pair).

    SPIKE 이 리밸런싱일 i=4 에 +100% 점프 → 그날 모멘텀 1위로 '선택'되지만, day-4 수익은
    *이전* 보유분(STEADY)으로 번다. 누설(선택일 수익을 그날 보유분에 적립)이 되살아나면
    daily[4]=1.0(점프) 가 되어 이 테스트가 깨진다. 확률적 Sharpe 경계와 달리 seed-drift
    에 면역인 결정론적 메커니즘 lock (codex 권고).
    """

    def test_rebalance_day_spike_not_credited_same_bar(self):
        idx = pd.date_range("2024-01-01", periods=8, freq="B")
        prices = pd.DataFrame(
            {
                "STEADY": [100, 101, 102, 103, 104, 105, 106, 107],
                "SPIKE": [100, 100, 100, 100, 200, 200, 200, 200],  # i=4 에 +100% 점프
            },
            index=idx,
            dtype=float,
        )
        daily, _turnover = _portfolio_usd_returns(prices, lookback=2, top_n=1, rebalance_days=2)
        # i=2 첫 리밸런싱: mom(STEADY)=0.02 > mom(SPIKE)=0 → STEADY 보유
        # i=4 리밸런싱: SPIKE 가 모멘텀 1위로 선택되지만, day-4 수익은 STEADY(104/103-1)로 번다.
        assert daily.iloc[4] == pytest.approx(104 / 103 - 1, rel=1e-9)
        assert daily.iloc[4] < 0.02  # 점프(1.0) 미반영 — 누설이면 1.0 → 실패
        # i=5: 이제 SPIKE 보유 → 그 다음 수익(200/200-1=0) 반영
        assert daily.iloc[5] == pytest.approx(0.0)

    def test_first_return_not_dropped(self):
        # 첫 리밸런싱(i=lookback) 다음 bar 부터 정상 적립 (off-by-one 반대 방향 점검)
        idx = pd.date_range("2024-01-01", periods=6, freq="B")
        prices = pd.DataFrame(
            {"A": [100, 110, 121, 133.1, 146.41, 161.051]},  # 매일 +10%
            index=idx,
            dtype=float,
        )
        daily, _ = _portfolio_usd_returns(prices, lookback=2, top_n=1, rebalance_days=2)
        assert daily.iloc[2] == pytest.approx(0.0)  # 첫 선택일 = 보유 전 → 0
        assert daily.iloc[3] == pytest.approx(0.1, rel=1e-9)  # 다음 bar 부터 +10% 적립


# ── #701 null-safe gate (permutation 검정) ────────────────────


class TestNullSafeGate:
    """#701: 순열 검정으로 noise 가 gate 를 통과하지 못한다.

    독립 random-walk 의 주기적 리밸런싱은 양의 Sharpe(변동성 하베스팅) + lookback 선택
    편향을 만들지만, 동일 파이프라인을 시간셔플 null 에도 적용하므로 real ≈ null → p≥alpha
    → 통과 실패. 기존 절대-Sharpe gate(min 0.5)는 noise 를 ~27% 통과시켰다.
    """

    CFG = {
        "strategy": {"lookback_grid": [10, 20], "top_n": 3, "rebalance_days": 10},
        "fold": {"kind": "rolling", "train_size": 60, "test_size": 20, "step": 20},
        "holdout": {"frac": 0.2},
        "costs": {"survivorship_haircut_bps_annual": 0},
        "gate": {
            "min_oos_sharpe": 0.5,
            "min_holdout_sharpe": 0.0,
            "permutation": {"n": 30, "alpha": 0.05, "seed": 0},
        },
    }

    @staticmethod
    def _rw(seed, n=260, n_tick=12):
        rng = np.random.default_rng(seed)
        dates = pd.date_range("2020-01-01", periods=n, freq="B")
        prices = pd.DataFrame(
            {f"T{j}": 100 * np.exp(np.cumsum(rng.normal(0.0, 0.02, n))) for j in range(n_tick)},
            index=dates,
        )
        return prices, dates

    def _run(self, seed):
        prices, dates = self._rw(seed)
        return run_strategy_walkforward(
            cost_bps=0.0, fx_series=pd.Series(1300.0, index=dates), prices=prices, config=self.CFG
        )

    def test_random_walk_does_not_pass_gate(self, db_path_mp):
        r = self._run(7)  # 결정론적 — noise → p≈0.84
        assert r["permutation"]["p_value"] >= self.CFG["gate"]["permutation"]["alpha"]
        assert r["gate"]["passed"] is False

    def test_high_noise_sharpe_still_rejected(self, db_path_mp):
        # seed 11: pooled OOS = +2.84 (구 절대-gate min 0.5 통과했을 값) 이지만 동일 절차가
        # noise 에서도 그만큼 만들어내므로 p≈0.10 → 통과 실패. 이게 #701 핵심.
        r = self._run(11)
        assert r["oos_sharpe_pooled"] > 0.5  # 구 절대 floor 는 통과
        assert r["gate"]["passed"] is False  # 순열 gate 는 거부
        assert r["permutation"]["p_value"] >= self.CFG["gate"]["permutation"]["alpha"]

    def test_p_value_deterministic(self, db_path_mp):
        a = self._run(7)["permutation"]["p_value"]
        b = self._run(7)["permutation"]["p_value"]
        assert a == b  # seed 고정 → 재현 (gate 판정 안정)

    def test_result_reports_pooled_and_p_value(self, db_path_mp):
        r = self._run(1)
        assert "oos_sharpe_pooled" in r
        assert 0.0 < r["permutation"]["p_value"] <= 1.0
        assert "null_p95" in r["permutation"]
        assert r["gate"]["alpha"] == 0.05
        assert r["gate"]["p_value"] == r["permutation"]["p_value"]


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


# ── persist + CLI (단일 검증 경로 — #702 엔진 폐기 대체) ────────


class TestPersistAndValidation:
    def test_persist_writes_backtest_summary(self, db_path_mp):
        import json as _json

        from nuri.core.db import query

        p = _panel(n=30)
        run_strategy_walkforward(cost_bps=10.0, fx_series=_flat_fx(p.index), prices=p, config=SMALL_CFG, persist=True)
        rows = query("SELECT strategy_id, sharpe, total_return, win_rate, params FROM backtests", db_path=db_path_mp)
        assert len(rows) == 1
        assert rows[0]["strategy_id"] == "momentum-topN-walkforward"
        # walk-forward 는 total_return/win_rate 미산출 → NULL (Sharpe/gate 기반)
        assert rows[0]["total_return"] is None
        assert rows[0]["win_rate"] is None
        assert "gate_passed" in _json.loads(rows[0]["params"])

    def test_load_fx_series(self, db_path):
        from nuri.core.db import get_db
        from nuri.quant.validation.strategy_walkforward import _load_fx_series

        with get_db(db_path) as conn:
            for i, d in enumerate(pd.date_range("2024-01-01", periods=5, freq="B")):
                conn.execute(
                    "INSERT INTO macro (indicator, date, value) VALUES (?, ?, ?)",
                    ("usd_krw", d.strftime("%Y-%m-%d"), 1300.0 + i),
                )
        fx = _load_fx_series(db_path=db_path)
        assert len(fx) == 5
        assert fx.iloc[0] == 1300.0

    def test_load_fx_series_missing_raises(self, db_path):
        from nuri.quant.validation.strategy_walkforward import _load_fx_series

        with pytest.raises(ValueError, match="usd_krw"):
            _load_fx_series(db_path=db_path)

    def test_run_strategy_validation_end_to_end(self, db_path_mp):
        from nuri.core.db import get_db, query
        from nuri.quant.validation.strategy_walkforward import run_strategy_validation

        p = _panel(n=30)
        with get_db(db_path_mp) as conn:
            conn.executemany(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                [(t, d.strftime("%Y-%m-%d"), float(p.loc[d, t])) for t in p.columns for d in p.index],
            )
            for d in p.index:
                conn.execute(
                    "INSERT INTO macro (indicator, date, value) VALUES (?, ?, ?)",
                    ("usd_krw", d.strftime("%Y-%m-%d"), 1300.0),
                )
        r = run_strategy_validation(cost_bps=10.0, config=SMALL_CFG)  # db_path=None → DB_PATH(monkeypatched)
        assert r["frozen_universe_n"] == 4
        assert len(query("SELECT id FROM backtests", db_path=db_path_mp)) == 1  # persist 됨


class TestCLI:
    def test_main_success_prints_summary(self, monkeypatch, capsys):
        import nuri.quant.validation.strategy_walkforward as S

        fake = {
            "frozen_universe_n": 100,
            "n_folds": 5,
            "oos_sharpe_pooled": 0.3,
            "permutation": {"p_value": 0.4, "null_p95": 0.8},
            "holdout_sharpe": 0.5,
            "holdout_max_drawdown": -0.1,
            "gate": {"passed": False},
        }
        monkeypatch.setattr(S, "run_strategy_validation", lambda **k: fake)
        assert S.main([]) == 0
        assert "GATE PASSED" in capsys.readouterr().out

    def test_main_fx_error_returns_2(self, monkeypatch):
        import nuri.quant.validation.strategy_walkforward as S

        def boom(**k):
            raise ValueError("usd_krw not in macro")

        monkeypatch.setattr(S, "run_strategy_validation", boom)
        assert S.main([]) == 2

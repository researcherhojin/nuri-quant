"""Lock-tests for pre-registered variant edge search (#706).

- select_fn known-answer: 각 변형이 의도한 신호로 선택하는지 결정론적 micro-case
- 패널 품질 필터: exclude_tickers / min_history / min_breadth (사전등록 필터 lock)
- Bonferroni: alpha_effective = alpha / n_test_variants (baseline 분모 제외)
- mandatory gate: cost_bps / fx_series None → ValueError (gross/통화-naive 차단)
- same-bar lookahead: 리밸런싱일 점프 미적립 (baseline 과 동일 규율, §5.3.1)
- 승격 자격 = discovery AND holdout AND not baseline
- persist: 변형별 backtests 1행 + walkforward_runs 기록
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nuri.quant.validation.variant_walkforward import (
    _build_panels,
    _evaluate_variant,
    _load_variants_config,
    _param_warmup,
    _sel_momentum,
    _sel_regime_momentum,
    _sel_skip_momentum,
    _sel_vol_scaled,
    _sel_volume_confirmed,
    _variant_daily_returns,
    run_variant_search,
)

# 작은 pre-registered config — 빠른 fold (테스트 전용; 실 config 와 구조 동일)
SMALL_CFG = {
    "panel": {"exclude_tickers": ["KOSDAQ"], "min_history": 5, "min_breadth": 2},
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
        {"name": "v0", "select": "momentum", "baseline": True, "theory": "control", "params": [{"lookback": 2}]},
        {"name": "v2", "select": "vol_scaled", "theory": "vol-scaled", "params": [{"lookback": 3}]},
    ],
}


def _panel(n: int = 40, tickers=("AAA", "BBB", "CCC", "DDD")) -> pd.DataFrame:
    """결정론적 close 패널 — 종목별 상이한 추세 + sin 변동."""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    data = {}
    for k, t in enumerate(tickers):
        steps = 0.001 * (k + 1) + 0.002 * np.sin(np.arange(n))
        data[t] = 100.0 * np.cumprod(1.0 + steps)
    return pd.DataFrame(data, index=dates)


def _vol_panel(close: pd.DataFrame, base: float = 1e6) -> pd.DataFrame:
    return pd.DataFrame(base, index=close.index, columns=close.columns)


def _flat_fx(idx: pd.Index) -> pd.Series:
    return pd.Series(1300.0, index=idx, dtype=float)


# ── select_fn known-answer (결정론적 micro-case) ───────────────


class TestSelectFns:
    def test_momentum_picks_highest_trailing_return(self):
        p = _panel()
        # DDD(가장 큰 drift) > CCC > BBB > AAA — top 2 = DDD, CCC
        held = _sel_momentum(p, None, 20, {"lookback": 10}, 2, {})
        assert held == ["DDD", "CCC"]

    def test_skip_momentum_excludes_recent_window(self):
        # JUMPY 는 최근 2일에만 급등 — skip=2 면 그 급등이 신호에서 빠져 STEADY 가 이긴다
        idx = pd.date_range("2024-01-01", periods=12, freq="B")
        steady = 100 * np.cumprod(1.0 + np.full(12, 0.01))
        jumpy = np.full(12, 100.0)
        jumpy[10:] = 130.0  # i-2 이후 급등
        p = pd.DataFrame({"STEADY": steady, "JUMPY": jumpy}, index=idx)
        held_skip = _sel_skip_momentum(p, None, 11, {"lookback": 8, "skip": 2}, 1, {})
        held_plain = _sel_momentum(p, None, 11, {"lookback": 8}, 1, {})
        assert held_skip == ["STEADY"]  # 최근 점프 제외 → 꾸준한 추세 승
        assert held_plain == ["JUMPY"]  # 일반 모멘텀은 점프 포함

    def test_vol_scaled_prefers_low_vol_trend(self):
        # 같은 누적수익이라도 변동성 낮은 쪽이 ret/vol 랭킹 승
        idx = pd.date_range("2024-01-01", periods=20, freq="B")
        smooth = 100 * np.cumprod(1.0 + np.full(20, 0.01))
        wild_steps = np.full(20, 0.01)
        wild_steps[::2] = 0.06
        wild_steps[1::2] = -0.035
        wild = 100 * np.cumprod(1.0 + wild_steps)
        p = pd.DataFrame({"SMOOTH": smooth, "WILD": wild}, index=idx)
        held = _sel_vol_scaled(p, None, 19, {"lookback": 10}, 1, {})
        assert held == ["SMOOTH"]

    def test_volume_confirmed_filters_by_dollar_volume_surge(self):
        # 모멘텀 top-2N 후보 중 거래대금 surge 큰 쪽이 선택된다
        p = _panel()
        vol = _vol_panel(p)
        vol.loc[p.index[26:31], "CCC"] = 5e6  # CCC surge — 선택 시점 i=30 의 surge_window(26..30)
        held = _sel_volume_confirmed(p, vol, 30, {"lookback": 10, "surge_window": 5}, 1, {})
        assert held == ["CCC"]  # 모멘텀 1위 DDD 보다 surge 우위 CCC

    def test_regime_momentum_goes_cash_below_ma(self):
        idx = pd.date_range("2024-01-01", periods=30, freq="B")
        spy = np.linspace(100, 80, 30)  # 하락 추세 → 가격 < MA
        stock = np.linspace(100, 120, 30)
        p = pd.DataFrame({"SPY": spy, "AAA": stock}, index=idx)
        cfg = {"regime": {"ticker": "SPY", "ma": 10}}
        assert _sel_regime_momentum(p, None, 29, {"lookback": 5}, 1, cfg) == []  # cash

    def test_regime_momentum_holds_above_ma(self):
        idx = pd.date_range("2024-01-01", periods=30, freq="B")
        spy = np.linspace(100, 130, 30)  # 상승 추세 → 가격 > MA
        stock = np.linspace(100, 120, 30)
        p = pd.DataFrame({"SPY": spy, "AAA": stock}, index=idx)
        cfg = {"regime": {"ticker": "SPY", "ma": 10}}
        held = _sel_regime_momentum(p, None, 29, {"lookback": 5}, 1, cfg)
        assert held == ["SPY"]  # 모멘텀 1위 (SPY 도 패널 멤버 — 후보 포함)

    def test_volume_confirmed_empty_when_no_momentum_candidates(self):
        # lookback 시점이 전부 NaN(상장 전) → 모멘텀 후보 0 → cash
        idx = pd.date_range("2024-01-01", periods=10, freq="B")
        late = np.full(10, np.nan)
        late[8:] = 100.0
        p = pd.DataFrame({"AAA": late, "BBB": late}, index=idx)
        held = _sel_volume_confirmed(p, _vol_panel(p), 9, {"lookback": 8, "surge_window": 2}, 1, {})
        assert held == []

    def test_param_warmup_includes_regime_ma(self):
        assert _param_warmup({"regime": {"ticker": "SPY", "ma": 200}}, {"lookback": 60}) == 200
        assert _param_warmup({}, {"lookback": 60}) == 60


# ── 패널 품질 필터 (사전등록 lock) ─────────────────────────────


class TestPanelFilter:
    @staticmethod
    def _seed(db_path, rows):
        from nuri.core.db import get_db

        with get_db(db_path) as conn:
            conn.executemany("INSERT INTO prices (ticker, date, close, volume) VALUES (?, ?, ?, ?)", rows)

    def test_excludes_pseudo_tickers_and_kr(self, db_path):
        rows = []
        for i, d in enumerate(pd.date_range("2024-01-01", periods=10, freq="B")):
            ds = d.strftime("%Y-%m-%d")
            for t in ("AAA", "BBB", "KOSDAQ", "005930.KS"):
                rows.append((t, ds, 100.0 + i, 1e6))
        self._seed(db_path, rows)
        close, vol = _build_panels(SMALL_CFG, db_path=db_path)
        assert set(close.columns) == {"AAA", "BBB"}  # KOSDAQ(denylist) + .KS 제외
        assert list(vol.columns) == list(close.columns)

    def test_min_history_drops_shallow_tickers(self, db_path):
        rows = []
        dates = pd.date_range("2024-01-01", periods=10, freq="B")
        for i, d in enumerate(dates):
            ds = d.strftime("%Y-%m-%d")
            rows.append(("DEEP", ds, 100.0 + i, 1e6))
            rows.append(("DEEP2", ds, 100.0 + i, 1e6))
            if i >= 8:  # SHALLOW 는 2일치만 (< min_history 5)
                rows.append(("SHALLOW", ds, 50.0, 1e6))
        self._seed(db_path, rows)
        close, _ = _build_panels(SMALL_CFG, db_path=db_path)
        assert "SHALLOW" not in close.columns
        assert {"DEEP", "DEEP2"} <= set(close.columns)

    def test_min_breadth_trims_degenerate_lead(self, db_path):
        # 처음 5일은 LONE 1종목뿐 (< min_breadth 2) → trim, 폭 2 이상부터 시작
        rows = []
        dates = pd.date_range("2024-01-01", periods=12, freq="B")
        for i, d in enumerate(dates):
            ds = d.strftime("%Y-%m-%d")
            rows.append(("LONE", ds, 100.0 + i, 1e6))
            if i >= 5:
                rows.append(("LATER", ds, 100.0 + i, 1e6))
        self._seed(db_path, rows)
        close, _ = _build_panels(SMALL_CFG, db_path=db_path)
        assert close.index[0] == dates[5]  # degenerate 선두 trim

    def test_empty_db_returns_empty(self, db_path):
        close, vol = _build_panels(SMALL_CFG, db_path=db_path)
        assert close.empty and vol.empty

    def test_breadth_never_reached_returns_empty(self, db_path):
        # 종목들이 min_history 는 넘지만 동시 존재 폭이 min_breadth 미달 → 빈 패널
        rows = []
        for i, d in enumerate(pd.date_range("2024-01-01", periods=14, freq="B")):
            ds = d.strftime("%Y-%m-%d")
            if i < 7:
                rows.append(("EARLY", ds, 100.0 + i, 1e6))
            else:
                rows.append(("LATE", ds, 100.0 + i, 1e6))
        self._seed(db_path, rows)
        close, vol = _build_panels(SMALL_CFG, db_path=db_path)
        assert close.empty and vol.empty

    def test_all_filtered_returns_empty(self, db_path):
        # min_history 미달만 존재 → 빈 패널
        rows = [("X", "2024-01-02", 100.0, 1e6)]
        self._seed(db_path, rows)
        close, vol = _build_panels(SMALL_CFG, db_path=db_path)
        assert close.empty and vol.empty


# ── same-bar lookahead (baseline 과 동일 규율) ─────────────────


class TestNoSameBarLookahead:
    def test_rebalance_day_spike_not_credited_same_bar(self):
        # SPIKE 가 리밸런싱일 i=4 에 +100% 점프 — 그날 수익은 이전 보유분(STEADY)으로 번다
        idx = pd.date_range("2024-01-01", periods=8, freq="B")
        prices = pd.DataFrame(
            {
                "STEADY": [100, 101, 102, 103, 104, 105, 106, 107],
                "SPIKE": [100, 100, 100, 100, 200, 200, 200, 200],
            },
            index=idx,
            dtype=float,
        )
        daily, _ = _variant_daily_returns(
            prices, None, _sel_momentum, {"lookback": 2}, {}, top_n=1, rebalance_days=2, warmup=2
        )
        assert daily.iloc[4] == pytest.approx(104 / 103 - 1, rel=1e-9)  # 점프(1.0) 미적립
        assert daily.iloc[5] == pytest.approx(0.0)  # 다음 bar 부터 SPIKE 보유


# ── gate / Bonferroni / runner ─────────────────────────────────


class TestRunner:
    def test_refuses_without_cost_or_fx(self):
        p = _panel()
        with pytest.raises(ValueError, match="cost_bps"):
            run_variant_search(cost_bps=None, fx_series=_flat_fx(p.index), close=p, vol=_vol_panel(p))
        with pytest.raises(ValueError, match="fx_series"):
            run_variant_search(cost_bps=10.0, fx_series=None, close=p, vol=_vol_panel(p))

    def test_bonferroni_alpha_excludes_baseline(self):
        p = _panel()
        r = run_variant_search(cost_bps=10.0, fx_series=_flat_fx(p.index), close=p, vol=_vol_panel(p), config=SMALL_CFG)
        assert r["n_test_variants"] == 1  # v0 은 baseline — 분모 제외
        assert r["alpha_effective"] == pytest.approx(0.05 / 1)

    def test_result_table_shape(self):
        p = _panel()
        r = run_variant_search(cost_bps=10.0, fx_series=_flat_fx(p.index), close=p, vol=_vol_panel(p), config=SMALL_CFG)
        assert [v["name"] for v in r["variants"]] == ["v0", "v2"]
        for v in r["variants"]:
            assert 0.0 < v["p_value"] <= 1.0
            assert isinstance(v["promotion_eligible"], bool)
            assert v["holdout_max_drawdown"] <= 0.0
        assert r["universe_n"] == 4

    def test_baseline_never_promotion_eligible(self):
        p = _panel()
        r = run_variant_search(cost_bps=10.0, fx_series=_flat_fx(p.index), close=p, vol=_vol_panel(p), config=SMALL_CFG)
        v0 = next(v for v in r["variants"] if v["name"] == "v0")
        assert v0["baseline"] is True
        assert v0["promotion_eligible"] is False  # 대조군은 정의상 승격 불가

    def test_unknown_select_fn_rejected(self):
        cfg = {**SMALL_CFG, "variants": [{"name": "x", "select": "nope", "theory": "t", "params": [{"lookback": 2}]}]}
        p = _panel()
        with pytest.raises(ValueError, match="unknown select_fn"):
            run_variant_search(cost_bps=10.0, fx_series=_flat_fx(p.index), close=p, vol=_vol_panel(p), config=cfg)

    def test_missing_regime_ticker_rejected(self):
        cfg = {
            **SMALL_CFG,
            "variants": [
                {
                    "name": "v4",
                    "select": "regime_momentum",
                    "theory": "t",
                    "regime": {"ticker": "SPY", "ma": 5},
                    "params": [{"lookback": 2}],
                }
            ],
        }
        p = _panel()  # SPY 없음
        with pytest.raises(ValueError, match="regime ticker"):
            run_variant_search(cost_bps=10.0, fx_series=_flat_fx(p.index), close=p, vol=_vol_panel(p), config=cfg)

    def test_empty_db_panel_rejected(self, db_path_mp):
        # close 미지정 → DB 패널 빌드 → 빈 패널이면 거부 (품질 필터 후 부족 메시지)
        with pytest.raises(ValueError, match="panel quality filter"):
            run_variant_search(
                cost_bps=10.0, fx_series=_flat_fx(pd.date_range("2024-01-01", periods=5)), config=SMALL_CFG
            )

    def test_insufficient_rows_rejected(self):
        p = _panel(n=3)
        with pytest.raises(ValueError):
            run_variant_search(cost_bps=10.0, fx_series=_flat_fx(p.index), close=p, vol=_vol_panel(p), config=SMALL_CFG)

    def test_random_walk_not_promotion_eligible(self):
        # noise 에서 승격 자격이 나오면 안 된다 (#701 null-safe 원칙 상속)
        rng = np.random.default_rng(7)
        idx = pd.date_range("2022-01-01", periods=120, freq="B")
        p = pd.DataFrame({f"T{j}": 100 * np.exp(np.cumsum(rng.normal(0.0, 0.02, 120))) for j in range(8)}, index=idx)
        cfg = {
            **SMALL_CFG,
            "fold": {"kind": "rolling", "train_size": 40, "test_size": 15, "step": 15},
            "variants": [
                {"name": "v0", "select": "momentum", "baseline": True, "theory": "c", "params": [{"lookback": 5}]},
                {"name": "v2", "select": "vol_scaled", "theory": "t", "params": [{"lookback": 5}, {"lookback": 10}]},
            ],
        }
        r = run_variant_search(cost_bps=0.0, fx_series=_flat_fx(idx), close=p, vol=_vol_panel(p), config=cfg)
        assert r["promotion_eligible"] == []

    def test_persist_writes_backtests_and_walkforward_runs(self, db_path_mp):
        from nuri.core.db import query

        p = _panel()
        r = run_variant_search(
            cost_bps=10.0,
            fx_series=_flat_fx(p.index),
            close=p,
            vol=_vol_panel(p),
            config=SMALL_CFG,
            persist=True,
        )
        rows = query("SELECT strategy_id, sharpe, params FROM backtests ORDER BY strategy_id", db_path=db_path_mp)
        assert [row["strategy_id"] for row in rows] == ["wf-variant:v0", "wf-variant:v2"]
        runs = query("SELECT model_id FROM walkforward_runs", db_path=db_path_mp)
        assert {row["model_id"] for row in runs} == {"wf-variant:v0", "wf-variant:v2"}
        assert all(v["walkforward_run_id"] for v in r["variants"])

    def test_loads_real_config_and_registry_complete(self):
        cfg = _load_variants_config()
        assert cfg["gate"]["multiple_comparison"] == "bonferroni"
        names = [v["name"] for v in cfg["variants"]]
        assert names == [
            "v0_momentum",
            "v1_skip_momentum",
            "v2_vol_scaled",
            "v3_volume_confirmed",
            "v4_regime_momentum",
        ]
        # 사전등록 규율: 검정 변형 4개, 각 param grid ≤ 3, baseline 은 v0 만
        assert sum(1 for v in cfg["variants"] if not v.get("baseline", False)) == 4
        assert all(len(v["params"]) <= 3 for v in cfg["variants"])
        from nuri.quant.validation.variant_walkforward import _SELECT_REGISTRY

        assert all(v["select"] in _SELECT_REGISTRY for v in cfg["variants"])


# ── 변형 단건 평가 (holdout 봉인) ──────────────────────────────


class TestEvaluateVariant:
    def test_holdout_reserved_and_reported(self):
        p = _panel()
        fx_ret = _flat_fx(p.index).pct_change().reindex(p.index).fillna(0.0)
        v = SMALL_CFG["variants"][0]
        r = _evaluate_variant(p, _vol_panel(p), fx_ret, v, SMALL_CFG, cost_bps=10.0, alpha_eff=0.05)
        warmup = 2
        assert r["walkforward_n"] + r["holdout_n"] == len(p) - warmup
        assert r["holdout_n"] > 0
        assert r["selected_param"] in v["params"]

    def test_too_short_panel_raises(self):
        p = _panel(n=4)
        fx_ret = _flat_fx(p.index).pct_change().reindex(p.index).fillna(0.0)
        v = SMALL_CFG["variants"][0]
        with pytest.raises(ValueError, match="need >"):
            _evaluate_variant(p, _vol_panel(p), fx_ret, v, SMALL_CFG, cost_bps=10.0, alpha_eff=0.05)


# ── CLI ────────────────────────────────────────────────────────


class TestCLI:
    def test_main_success_prints_table(self, monkeypatch, capsys):
        import nuri.quant.validation.variant_walkforward as V

        fake = {
            "universe_n": 90,
            "panel_rows": 1200,
            "panel_start": "2021-04-09",
            "panel_end": "2026-06-04",
            "cost_bps": 10.0,
            "n_test_variants": 4,
            "alpha": 0.05,
            "alpha_effective": 0.0125,
            "promotion_eligible": [],
            "variants": [
                {
                    "name": "v0_momentum",
                    "baseline": True,
                    "oos_sharpe_pooled": 0.3,
                    "p_value": 0.5,
                    "null_p95": 1.2,
                    "holdout_sharpe": 0.1,
                    "holdout_max_drawdown": -0.2,
                    "promotion_eligible": False,
                }
            ],
        }
        monkeypatch.setattr(V, "run_variant_validation", lambda **k: fake)
        assert V.main([]) == 0
        out = capsys.readouterr().out
        assert "Bonferroni" in out
        assert "노이즈 초과 엣지 없음" in out

    def test_main_error_returns_2(self, monkeypatch):
        import nuri.quant.validation.variant_walkforward as V

        def boom(**k):
            raise ValueError("usd_krw not in macro")

        monkeypatch.setattr(V, "run_variant_validation", boom)
        assert V.main([]) == 2

    def test_run_variant_validation_loads_fx(self, db_path_mp):
        from nuri.core.db import get_db
        from nuri.quant.validation.variant_walkforward import run_variant_validation

        p = _panel()
        with get_db(db_path_mp) as conn:
            conn.executemany(
                "INSERT INTO prices (ticker, date, close, volume) VALUES (?, ?, ?, ?)",
                [(t, d.strftime("%Y-%m-%d"), float(p.loc[d, t]), 1e6) for t in p.columns for d in p.index],
            )
            for d in p.index:
                conn.execute(
                    "INSERT INTO macro (indicator, date, value) VALUES (?, ?, ?)",
                    ("usd_krw", d.strftime("%Y-%m-%d"), 1300.0),
                )
        r = run_variant_validation(cost_bps=10.0, config=SMALL_CFG, persist=False)
        assert r["universe_n"] == 4
        assert "promotion_eligible" in r

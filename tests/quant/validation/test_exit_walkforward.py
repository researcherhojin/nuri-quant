"""Lock-tests for P4 exit-rule walk-forward (#713).

- _resolve_exit known-answer: stop / TP ladder partial / trailing(HWM) / MA 이탈 /
  buy-hold horizon / 같은 날 full-exit > TP 우선 (체결 규약 동결)
- _simulate_rule: 매도 다음날부터 fraction 축소 (same-bar 규약) + 비용 부과
- paired: 동일 룰 vs 자기 자신 → Δ=0 (paired 비교의 sanity)
- mandatory gate: cost/fx 필수, baseline 정확히 1개
- discovery/holdout 분할: buffer (경계 걸침 진입 제외)
- holdout 봉인: 발견 미통과 룰은 holdout_delta=None
- 랜덤워크: promotion 자격 없음 (#701 원칙 상속)
- persist + CLI
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nuri.quant.validation.exit_walkforward import (
    _load_exits_config,
    _partition_entries,
    _resolve_exit,
    _sample_entries,
    _simulate_rule,
    run_exit_search,
)

SMALL_CFG = {
    "panel": {"exclude_tickers": ["KOSDAQ"], "min_history": 5, "min_breadth": 2},
    "entries": {"n": 40, "seed": 0, "max_horizon": 10, "warmup": 3},
    "holdout": {"frac": 0.2},
    "costs": {"survivorship_haircut_bps_annual": 200},
    "gate": {
        "permutation": {"n": 10, "alpha": 0.05, "seed": 0},
        "multiple_comparison": "bonferroni",
        "min_delta_sharpe": 0.0,
        "min_holdout_delta": 0.0,
    },
    "rules": [
        {
            "name": "e0",
            "baseline": True,
            "theory": "control",
            "stop_pct": -7,
            "tp1": {"pct": 20, "sell": 0.5},
            "tp2": {"pct": 40, "sell": 0.25},
            "trailing_pct": -15,
        },
        {"name": "e4", "theory": "stop only", "stop_pct": -7},
    ],
}


def _panel(n: int = 60, tickers=("AAA", "BBB", "CCC", "DDD")) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    data = {}
    for k, t in enumerate(tickers):
        steps = 0.001 * (k + 1) + 0.002 * np.sin(np.arange(n))
        data[t] = 100.0 * np.cumprod(1.0 + steps)
    return pd.DataFrame(data, index=dates)


def _flat_fx(idx: pd.Index) -> pd.Series:
    return pd.Series(1300.0, index=idx, dtype=float)


# ── _resolve_exit known-answer (결정론) ────────────────────────


class TestResolveExit:
    def test_stop_first_crossing(self):
        c = np.array([100.0, 98.0, 92.0, 90.0])  # day2 에 -8% (≤ -7%)
        liq, events = _resolve_exit(c, None, {"stop_pct": -7}, horizon=10)
        assert liq == 2
        assert events == [(2, 1.0)]

    def test_tp_ladder_partials_then_trailing(self):
        # day1 +20%(TP1 50%), day2 +40%(TP2 25%), day4 고점대비 -15%(트레일 잔여 청산)
        c = np.array([100.0, 120.0, 140.0, 141.0, 119.0])
        rule = {"stop_pct": -7, "tp1": {"pct": 20, "sell": 0.5}, "tp2": {"pct": 40, "sell": 0.25}, "trailing_pct": -15}
        liq, events = _resolve_exit(c, None, rule, horizon=10)
        assert liq == 4  # 119 ≤ 141 × 0.85 = 119.85
        assert (1, 0.5) in events and (2, 0.25) in events
        assert events[-1] == (4, pytest.approx(0.25))

    def test_trailing_uses_high_water_mark(self):
        # 고점 130 후 110 = -15.4% → 트레일 발동 (진입가 대비는 +10% 인데도)
        c = np.array([100.0, 130.0, 125.0, 110.0])
        liq, events = _resolve_exit(c, None, {"trailing_pct": -15}, horizon=10)
        assert liq == 3
        assert events == [(3, 1.0)]

    def test_ma_exit_and_nan_ma_holds(self):
        c = np.array([100.0, 101.0, 102.0, 95.0])
        ma = np.array([np.nan, np.nan, 100.0, 100.0])  # MA 미계산 구간은 보유
        liq, _ = _resolve_exit(c, ma, {"trail_ma": 3}, horizon=10)
        assert liq == 3  # day3: 95 < MA 100 (day1-2 는 NaN → 무시)

    def test_buy_hold_runs_to_horizon(self):
        c = np.array([100.0, 50.0, 40.0, 30.0, 20.0])  # 어떤 폭락에도 무반응
        liq, events = _resolve_exit(c, None, {}, horizon=3)
        assert liq == 3
        assert events == [(3, 1.0)]

    def test_same_day_full_exit_beats_tp(self):
        # day1 에 +20%(TP1) 와 고점대비 트레일이 동시 발생할 수 없으므로 stop 동시 케이스:
        # 진입 후 day1 에 TP1 도달가 = stop 도달가가 양립 불가 → trailing 동시 케이스로 검증.
        # c: day1 +25% (TP1 충족) 이면서 고점(125) 대비 0% — 트레일 미발동. day2 폭락으로
        # 같은 날 TP2(미충족)·트레일 발동 → full-exit 이 잔여 전량.
        c = np.array([100.0, 125.0, 106.0])  # day2: 106 ≤ 125×0.85=106.25 → 트레일
        rule = {"tp1": {"pct": 20, "sell": 0.5}, "tp2": {"pct": 40, "sell": 0.25}, "trailing_pct": -15}
        liq, events = _resolve_exit(c, None, rule, horizon=10)
        assert liq == 2
        assert events == [(1, 0.5), (2, pytest.approx(0.5))]  # TP2 는 liq 이후 → 무효

    def test_horizon_caps_window(self):
        c = np.full(12, 100.0)
        liq, _ = _resolve_exit(c, None, {"stop_pct": -7}, horizon=5)
        assert liq == 5


# ── _simulate_rule: fraction 타이밍 + 비용 ─────────────────────


class TestSimulateRule:
    def test_sell_reduces_fraction_next_day(self):
        # 단일 포지션: day1 +20% → TP1 50% 매도 → day2 수익은 fraction 0.5 로만 적립
        idx = pd.date_range("2024-01-01", periods=4, freq="B")
        close = pd.DataFrame({"X": [100.0, 120.0, 132.0, 132.0]}, index=idx)
        rule = {"tp1": {"pct": 20, "sell": 0.5}}
        s, c = _simulate_rule(close, [(0, 0)], rule, cost_bps=0.0, max_horizon=10)
        assert s[1] == pytest.approx(0.20)  # day1: 전량 보유 +20%
        assert s[2] == pytest.approx(0.5 * 0.10)  # day2: 잔여 0.5 × +10%
        assert c[1] == 1.0 and c[2] == 1.0

    def test_cost_charged_on_trades(self):
        idx = pd.date_range("2024-01-01", periods=3, freq="B")
        close = pd.DataFrame({"X": [100.0, 100.0, 100.0]}, index=idx)
        free, _ = _simulate_rule(close, [(0, 0)], {}, cost_bps=0.0, max_horizon=2)
        paid, _ = _simulate_rule(close, [(0, 0)], {}, cost_bps=100.0, max_horizon=2)
        assert paid.sum() < free.sum()  # 진입 1.0 + 청산 1.0 비용 부과

    def test_trail_ma_rule_in_simulation(self):
        # trail_ma 룰이 MA 패널 계산 경로를 타는지 (MA 이탈 → 청산 후 비활성)
        idx = pd.date_range("2024-01-01", periods=10, freq="B")
        px = np.array([100.0, 101, 102, 103, 104, 105, 90, 89, 88, 87])
        close = pd.DataFrame({"X": px}, index=idx)
        s, c = _simulate_rule(close, [(0, 0)], {"trail_ma": 3}, cost_bps=0.0, max_horizon=9)
        # day6(90) 에서 MA3 이탈 → 청산 → day7+ 비활성
        assert c[6] == 1.0 and c[7] == 0.0

    def test_inactive_days_zero(self):
        idx = pd.date_range("2024-01-01", periods=6, freq="B")
        close = pd.DataFrame({"X": np.linspace(100, 105, 6)}, index=idx)
        s, c = _simulate_rule(close, [(0, 2)], {}, cost_bps=0.0, max_horizon=2)
        assert c[1] == 0.0 and c[3] == 1.0 and c[5] == 0.0  # 진입 전/청산 후 비활성


# ── 진입 샘플링 / 분할 ─────────────────────────────────────────


class TestEntries:
    def test_sample_deterministic_and_valid(self):
        p = _panel()
        e1 = _sample_entries(p, {"n": 20, "seed": 0, "warmup": 3, "max_horizon": 10})
        e2 = _sample_entries(p, {"n": 20, "seed": 0, "warmup": 3, "max_horizon": 10})
        assert e1 == e2  # seed 고정 → 재현 (paired 전제)
        assert all(t0 >= 3 for _, t0 in e1)

    def test_partition_buffer_excludes_straddlers(self):
        # n_days=100, frac 0.2 → split=80. horizon 10 → discovery 는 t0+10<80 (t0≤69),
        # holdout 은 t0≥80, 70..79 진입은 buffer 로 제외.
        entries = [(0, 50), (0, 69), (0, 75), (0, 80), (0, 90)]
        disc, hold, split = _partition_entries(entries, 100, 0.2, 10)
        assert split == 80
        assert (0, 50) in disc and (0, 69) in disc
        assert (0, 75) not in disc and (0, 75) not in hold  # buffer
        assert (0, 80) in hold and (0, 90) in hold

    def test_too_short_panel_raises(self):
        p = _panel(n=4)
        with pytest.raises(ValueError, match="panel too short"):
            _sample_entries(p, {"n": 5, "seed": 0, "warmup": 3, "max_horizon": 10})

    def test_per_ticker_warmup_history_required(self):
        # codex P2: late-start ticker 는 자기 시작 후 warmup 일이 지나야 진입 가능
        # (아니면 E1 의 MA 미계산 → stop-only 로 퇴화한 다른 룰을 평가)
        idx = pd.date_range("2024-01-01", periods=30, freq="B")
        late = np.full(30, np.nan)
        late[20:] = 100.0  # index 20 부터 상장
        p = pd.DataFrame({"OK": np.linspace(100, 110, 30), "LATE": late}, index=idx)
        entries = _sample_entries(p, {"n": 100, "seed": 0, "warmup": 5, "max_horizon": 5})
        arr = p.to_numpy()
        for j, t0 in entries:
            assert not np.isnan(arr[t0 - 5, j])  # t0-warmup 시점에도 히스토리 존재
        late_j = list(p.columns).index("LATE")
        assert all(t0 >= 25 for j, t0 in entries if j == late_j)  # 20+5 이후만

    def test_exposure_mask_windows_sharpe(self):
        # codex P1: 평가 창 밖(예: holdout 의 0-수익 꼬리)이 Δ/Sharpe 에 안 섞인다 —
        # 동일 진입·동일 활동인데 패널 뒤에 무활동 구간을 늘려도 Δ 불변
        from nuri.quant.validation.exit_walkforward import _delta_sharpe

        short = _panel(n=40)
        long = _panel(n=120)  # 동일 생성식 — 앞 40일 가격 동일, 뒤는 무진입 구간
        entries = [(0, 5), (1, 10), (2, 15)]  # 활동 전부 index<30
        fx_s, fx_l = np.zeros(40), np.zeros(120)
        rule, base = {"stop_pct": -7}, {"trailing_pct": -15}
        d_short, s_short, _ = _delta_sharpe(short, entries, rule, base, fx_s, 10.0, 0.0, 10)
        d_long, s_long, _ = _delta_sharpe(long, entries, rule, base, fx_l, 10.0, 0.0, 10)
        assert d_long == pytest.approx(d_short, rel=1e-12)
        assert s_long == pytest.approx(s_short, rel=1e-12)

    def test_sparse_panel_skips_nan_and_warns(self, caplog):
        # 유효 진입 구간이 전부 NaN → NaN 진입 스킵 + 목표 미달 warning
        import logging as _logging

        idx = pd.date_range("2024-01-01", periods=10, freq="B")
        col = np.full(10, np.nan)
        col[0] = 100.0  # warmup(3) 이전에만 유효 → 진입 가능 조합 0
        p = pd.DataFrame({"A": col, "B": col}, index=idx)
        with caplog.at_level(_logging.WARNING):
            entries = _sample_entries(p, {"n": 5, "seed": 0, "warmup": 3, "max_horizon": 5})
        assert entries == []  # NaN 진입은 전부 스킵
        assert "sampled" in caplog.text  # 목표 미달 → warning


# ── runner / gate ──────────────────────────────────────────────


class TestRunner:
    def test_refuses_without_cost_or_fx(self):
        p = _panel()
        with pytest.raises(ValueError, match="cost_bps"):
            run_exit_search(cost_bps=None, fx_series=_flat_fx(p.index), close=p, config=SMALL_CFG)
        with pytest.raises(ValueError, match="fx_series"):
            run_exit_search(cost_bps=10.0, fx_series=None, close=p, config=SMALL_CFG)

    def test_warmup_must_cover_trail_ma(self):
        # warmup < trail_ma 면 진입 시 MA 미계산 → 사전등록과 다른 룰 평가 → 거부 (codex R2)
        p = _panel()
        cfg = {
            **SMALL_CFG,
            "rules": [
                {"name": "e0", "baseline": True, "theory": "c", "stop_pct": -7},
                {"name": "e1", "theory": "t", "trail_ma": 50},  # warmup 3 < 50
            ],
        }
        with pytest.raises(ValueError, match="warmup must be >= trail_ma"):
            run_exit_search(cost_bps=10.0, fx_series=_flat_fx(p.index), close=p, config=cfg)

    def test_requires_exactly_one_baseline(self):
        p = _panel()
        cfg = {**SMALL_CFG, "rules": [{"name": "a", "theory": "t", "stop_pct": -7}]}
        with pytest.raises(ValueError, match="baseline"):
            run_exit_search(cost_bps=10.0, fx_series=_flat_fx(p.index), close=p, config=cfg)

    def test_result_shape_and_bonferroni(self):
        p = _panel()
        r = run_exit_search(cost_bps=10.0, fx_series=_flat_fx(p.index), close=p, config=SMALL_CFG)
        assert r["n_test_rules"] == 1
        assert r["alpha_effective"] == pytest.approx(0.05)
        names = [v["name"] for v in r["rules"]]
        assert names == ["e0", "e4"]
        e0 = r["rules"][0]
        assert e0["baseline"] is True
        assert e0["delta_sharpe"] is None and e0["p_value"] is None  # 대조군은 Δ/p 없음
        assert e0["promotion_eligible"] is False

    def test_identical_rule_paired_delta_zero(self):
        # 자기 자신과의 paired Δ = 정확히 0 (순열 불요 — _delta_sharpe 직접)
        from nuri.quant.validation.exit_walkforward import _delta_sharpe

        p = _panel()
        fx_ret = np.zeros(len(p))
        rule = {"name": "x", "stop_pct": -7}
        d, _, _ = _delta_sharpe(p, [(0, 5), (1, 10)], rule, rule, fx_ret, 10.0, 0.0, 10)
        assert d == pytest.approx(0.0)

    def test_holdout_sealed_on_discovery_fail(self):
        p = _panel()
        r = run_exit_search(cost_bps=10.0, fx_series=_flat_fx(p.index), close=p, config=SMALL_CFG)
        e4 = r["rules"][1]
        # n_perm=10 → 최소 p=1/11>0.05 → discovery 불가능 → holdout 봉인
        assert e4["discovery_passed"] is False
        assert e4["holdout_delta"] is None
        assert e4["promotion_eligible"] is False

    def test_random_walk_no_promotion(self):
        rng = np.random.default_rng(11)
        idx = pd.date_range("2022-01-01", periods=100, freq="B")
        p = pd.DataFrame({f"T{j}": 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 100))) for j in range(6)}, index=idx)
        r = run_exit_search(cost_bps=0.0, fx_series=_flat_fx(idx), close=p, config=SMALL_CFG)
        assert r["promotion_eligible"] == []

    def test_holdout_opened_when_discovery_forced(self):
        # gate 를 결정론적으로 통과시켜(alpha 0.99 + Δ floor 바닥) holdout 개봉 경로 lock
        p = _panel(n=80)
        cfg = {
            **SMALL_CFG,
            "entries": {"n": 30, "seed": 0, "max_horizon": 5, "warmup": 3},
            "gate": {
                # alpha>1 → p≤1.0 이 항상 통과 (결정론적 강제 — 봉인 해제 경로 lock 전용)
                "permutation": {"n": 10, "alpha": 1.5, "seed": 0},
                "multiple_comparison": "bonferroni",
                "min_delta_sharpe": -100.0,
                "min_holdout_delta": -100.0,
            },
        }
        r = run_exit_search(cost_bps=10.0, fx_series=_flat_fx(p.index), close=p, config=cfg)
        e4 = r["rules"][1]
        assert e4["discovery_passed"] is True
        assert e4["holdout_delta"] is not None  # 개봉됨
        assert e4["holdout_passed"] is True
        assert e4["promotion_eligible"] is True

    def test_no_discovery_entries_raises(self):
        # max_horizon 이 panel 을 초과 → 모든 진입이 buffer/holdout → discovery 0
        p = _panel(n=30)
        cfg = {**SMALL_CFG, "entries": {"n": 10, "seed": 0, "max_horizon": 28, "warmup": 3}}
        with pytest.raises(ValueError, match="no discovery entries"):
            run_exit_search(cost_bps=10.0, fx_series=_flat_fx(p.index), close=p, config=cfg)

    def test_persist_writes_backtests(self, db_path_mp):
        from nuri.core.db import query

        p = _panel()
        run_exit_search(cost_bps=10.0, fx_series=_flat_fx(p.index), close=p, config=SMALL_CFG, persist=True)
        rows = query("SELECT strategy_id, params FROM backtests ORDER BY strategy_id", db_path=db_path_mp)
        assert [row["strategy_id"] for row in rows] == ["wf-exit:e0", "wf-exit:e4"]

    def test_empty_db_panel_rejected(self, db_path_mp):
        with pytest.raises(ValueError, match="panel quality filter"):
            run_exit_search(cost_bps=10.0, fx_series=_flat_fx(pd.date_range("2024-01-01", periods=5)), config=SMALL_CFG)

    def test_loads_real_config_preregistered_shape(self):
        cfg = _load_exits_config()
        names = [r["name"] for r in cfg["rules"]]
        assert names == ["e0_ladder", "e1_leader_ma", "e2_trail25", "e3_buy_hold", "e4_stop_only"]
        assert sum(1 for r in cfg["rules"] if r.get("baseline")) == 1
        assert cfg["gate"]["multiple_comparison"] == "bonferroni"
        # E0 은 rules.yaml 현행 값의 동결 복사 (drift 시 의도 확인 필요)
        e0 = cfg["rules"][0]
        assert e0["stop_pct"] == -7 and e0["tp1"]["pct"] == 20 and e0["tp2"]["pct"] == 40
        assert e0["trailing_pct"] == -15
        assert cfg["rules"][1]["trail_ma"] == 50


# ── CLI ────────────────────────────────────────────────────────


class TestCLI:
    def test_main_success_prints_table(self, monkeypatch, capsys):
        import nuri.quant.validation.exit_walkforward as E

        fake = {
            "universe_n": 90,
            "panel_start": "2021-04-20",
            "panel_end": "2026-06-04",
            "cost_bps": 10.0,
            "n_entries": 2000,
            "n_discovery": 1300,
            "n_holdout": 400,
            "split_idx": 1000,
            "n_test_rules": 4,
            "alpha": 0.05,
            "alpha_effective": 0.0125,
            "promotion_eligible": [],
            "rules": [
                {
                    "name": "e0_ladder",
                    "baseline": True,
                    "sharpe": 0.5,
                    "delta_sharpe": None,
                    "p_value": None,
                    "null_p95": None,
                    "max_drawdown": -0.3,
                    "holdout_delta": None,
                    "promotion_eligible": False,
                },
                {
                    "name": "e1_leader_ma",
                    "baseline": False,
                    "sharpe": 0.7,
                    "delta_sharpe": 0.2,
                    "p_value": 0.2,
                    "null_p95": 0.5,
                    "max_drawdown": -0.25,
                    "holdout_delta": None,
                    "promotion_eligible": False,
                },
            ],
        }
        monkeypatch.setattr(E, "run_exit_validation", lambda **k: fake)
        assert E.main([]) == 0
        out = capsys.readouterr().out
        assert "Bonferroni" in out
        assert "sealed" in out
        assert "E0 ladder 유지" in out

    def test_main_error_returns_2(self, monkeypatch):
        import nuri.quant.validation.exit_walkforward as E

        def boom(**k):
            raise ValueError("usd_krw not in macro")

        monkeypatch.setattr(E, "run_exit_validation", boom)
        assert E.main([]) == 2

    def test_run_exit_validation_loads_fx(self, db_path_mp):
        from nuri.core.db import get_db
        from nuri.quant.validation.exit_walkforward import run_exit_validation

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
        r = run_exit_validation(cost_bps=10.0, config=SMALL_CFG, persist=False)
        assert r["universe_n"] == 4
        assert "promotion_eligible" in r

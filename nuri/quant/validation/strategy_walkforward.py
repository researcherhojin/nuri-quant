"""전략 walk-forward 검증 어댑터 (P1b) — WalkForwardValidator 의 첫 caller.

미국 모멘텀 top-N 전략을 walk-forward 로 검증한다. 각 train fold 에서 lookback 을
선택(= model 'fit')하고 다음 test fold 에서 OOS 평가한다. 수익률은 **거래비용 +
KRW→USD FX + 생존자 haircut 차감 후**의 KRW home-currency net return 이다
(원화 계좌 기준; US 보유분의 실현 P&L 은 FX drift 를 포함).

설계 (user 선택 = '전략 수익률', Option A):
- WalkForwardValidator(28-test, Codex Round 5 hardened) 는 **무수정** — 일반 eval
  primitive 로 유지. cost/FX/생존자/holdout 등 strategy 책임은 전부 이 어댑터에 산다.
- 거래비용(cost_bps) + FX(fx_series) 는 **필수 입력** — 없으면 run 거부. gross 이거나
  통화-naive 한 검증이 승격 근거로 새는 것을 writer 경계에서 차단한다.
- FROZEN holdout: 최근 frac 구간은 walk-forward 가 보지 않는다. non-holdout 에서 고른
  lookback 으로 holdout 을 **1회만** 최종 평가 (P2-P6 가 튜닝에 쓸 수 없는 봉인 구간).
- 생존자 universe: 현재 prices 에 존재하는 ticker 만. survivorship 상승편향은 haircut 으로
  보정 (제거 불가 — 실측 사실로 명시).
- model 'fit' = train fold 에서 OOS net Sharpe 를 최대화하는 lookback 선택. 단순 plumbing
  이 아니라 in-sample 파라미터 선택 → strictly-OOS 평가 (López de Prado walk-forward 규율).
- **null-safe gate (#701)**: 독립 자산의 주기적 리밸런싱은 noise 에서도 양의 Sharpe(변동성
  하베스팅)를 만들고 lookback argmax 는 선택 편향을 더한다. 따라서 절대 Sharpe 임계만으론
  random-walk 도 통과한다. 대신 **순열 검정** — 수익률을 시간셔플해 동일 파이프라인을 N회
  돌린 null 분포를 만들고, pooled OOS Sharpe 가 그 분포를 p<alpha 로 이겨야 통과한다.
  리밸런싱 artifact + 선택 편향 모두 null 에 포함 → 깨끗한 비교 (Monte-Carlo permutation test).
- 승격(weight>0)은 이 gate 통과 + max-drawdown 후 **별도 STRATEGY PR**. 이 모듈은 측정만 한다.

WalkForwardValidator 가 결과를 walkforward_runs 에 기록하므로 /api/research/walkforward
(P1a) 로 자동 surface 된다.

known-answer gate: buy-and-hold 상수수익 → annualized Sharpe 손계산 일치 (Sharpe 식 lock).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import yaml

from nuri.agents.actors.walkforward_validator import (
    FoldSpec,
    WalkForwardValidator,
    _generate_folds,
    _sharpe_from_returns,
)
from nuri.core.db import query_df, save_backtest

_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config" / "walkforward.yaml"


def _load_wf_config(path: Optional[Path] = None) -> dict:
    """config/walkforward.yaml 로드 (pre-registered 파라미터)."""
    p = path or _CONFIG_PATH
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _max_drawdown(returns: np.ndarray) -> float:
    """일별 수익률 시계열의 최대 낙폭 (peak-to-trough, <= 0)."""
    r = np.asarray(returns, dtype=np.float64)
    if r.size == 0:
        return 0.0
    cum = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(cum)
    return float((cum / peak - 1.0).min())


def _portfolio_usd_returns(
    prices: pd.DataFrame, lookback: int, top_n: int, rebalance_days: int
) -> tuple[pd.Series, pd.Series]:
    """모멘텀 top-N 동일가중 포트폴리오의 일별 USD 수익률 + 리밸런싱 turnover.

    turnover ∈ [0,1]: 첫 진입 = 1.0(전량 배치), 이후 = 교체 비중(symmetric diff / 2N).
    """
    rets = prices.pct_change(fill_method=None)
    mom = prices.pct_change(lookback, fill_method=None)
    idx = prices.index
    daily = pd.Series(0.0, index=idx)
    turnover = pd.Series(0.0, index=idx)
    held: list[str] = []
    for i in range(len(idx)):
        if i < lookback:
            continue
        # ① day-i 수익률은 *day-i 이전*에 결정된 보유분으로만 번다 (same-bar lookahead 차단).
        #    momentum 선택(mom.iloc[i], price[i] 포함)과 그날 수익률(price[i]/price[i-1])을
        #    같은 날 보유분에 동시 적용하면 이미 본 움직임으로 보상받는 누설이 된다.
        if held:
            daily.iloc[i] = rets.iloc[i][held].mean()
        # ② 리밸런싱은 day-i 종가 신호로 결정 → day i+1 부터 유효 (거래비용은 거래일 i 에 부과).
        if (i - lookback) % rebalance_days == 0:
            row = mom.iloc[i].dropna()
            new = row.nlargest(min(top_n, len(row))).index.tolist()
            prev = set(held)
            new_set = set(new)
            if not prev:
                turnover.iloc[i] = 1.0 if new_set else 0.0
            else:
                turnover.iloc[i] = len(prev.symmetric_difference(new_set)) / (2 * top_n)
            held = new
    return daily, turnover


def _strategy_net_returns(
    prices: pd.DataFrame,
    fx_ret: pd.Series,
    lookback: int,
    top_n: int,
    rebalance_days: int,
    cost_bps: float,
    haircut_daily: float,
) -> pd.Series:
    """거래비용 + FX + 생존자 haircut 차감 후의 KRW home-currency 일별 net return.

    KRW net = (1+USD수익률)(1+FX변화) - 1 - 거래비용 - haircut.
    warmup(< lookback) 구간은 0 (보유 없음 → FX 노출도 없음).
    """
    usd, turnover = _portfolio_usd_returns(prices, lookback, top_n, rebalance_days)
    krw = (1.0 + usd) * (1.0 + fx_ret) - 1.0
    cost = turnover * (cost_bps / 10000.0)
    net = krw - cost - haircut_daily
    net.iloc[:lookback] = 0.0
    return net


def _build_us_panel(db_path: Optional[Path] = None) -> pd.DataFrame:
    """prices 에서 미국 생존자 universe 의 date-indexed USD close 패널.

    .KS(한국) 제외 — 통화 혼합 방지 (engine.py 와 동일 규율). 현재 prices 에 존재하는
    ticker = 생존자 (survivorship bias 는 haircut 으로 보정).
    """
    df = query_df("SELECT ticker, date, close FROM prices ORDER BY date", db_path=db_path)
    if df.empty:
        return pd.DataFrame()
    pivot = df.pivot_table(index="date", columns="ticker", values="close")
    pivot.index = pd.to_datetime(pivot.index)
    pivot = pivot[[t for t in pivot.columns if not str(t).endswith(".KS")]]
    return pivot.dropna(axis=1, how="all").ffill()


def _aligned_net_returns(
    prices: pd.DataFrame,
    fx_ret: pd.Series,
    grid: list[int],
    top_n: int,
    rebalance_days: int,
    cost_bps: float,
    haircut_daily: float,
    warmup: int,
) -> dict[int, np.ndarray]:
    """lookback 별 net return 시계열(warmup 이후, 동일 시작) → {L: np.ndarray}."""
    return {
        L: _strategy_net_returns(prices, fx_ret, L, top_n, rebalance_days, cost_bps, haircut_daily)
        .iloc[warmup:]
        .reset_index(drop=True)
        .to_numpy()
        for L in grid
    }


def _pooled_oos_sharpe(aligned: dict[int, np.ndarray], grid: list[int], fold_spec: dict, split: int) -> float:
    """모든 OOS test-fold 수익률을 모아 단일 Sharpe (per-fold 평균보다 저분산).

    각 fold: train 에서 lookback 선택 → 해당 test 수익률을 pool 에 누적. pool 전체로 Sharpe.
    """
    pooled: list[float] = []
    for tr, te in _generate_folds(split, FoldSpec(**fold_spec)):
        best_l = max(grid, key=lambda L: _sharpe_from_returns(aligned[L][tr]))
        pooled.extend(aligned[best_l][te].tolist())
    return _sharpe_from_returns(np.asarray(pooled)) if len(pooled) > 1 else 0.0


def _permute_prices(prices: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """각 종목 일별 수익률을 시간축 셔플 → 시계열 예측성(모멘텀) 파괴, 수익률 분포·t0 가격 보존.

    permutation null 의 핵심: 동일 파이프라인을 '예측성 없는' 데이터에 적용해 리밸런싱
    artifact + lookback 선택 편향을 null 분포로 포착한다.
    """
    rets = prices.pct_change(fill_method=None)
    out: dict[str, np.ndarray] = {}
    for t in prices.columns:
        r = rets[t].to_numpy()
        idx = np.where(~np.isnan(r))[0]
        shuffled = r.copy()
        shuffled[idx] = r[rng.permutation(idx)]
        out[str(t)] = prices[t].to_numpy()[0] * np.cumprod(1.0 + np.nan_to_num(shuffled))
    return pd.DataFrame(out, index=prices.index)


def run_strategy_walkforward(
    *,
    cost_bps: float,
    fx_series: pd.Series,
    prices: Optional[pd.DataFrame] = None,
    db_path: Optional[Path] = None,
    config: Optional[dict] = None,
    persist: bool = False,
) -> dict[str, Any]:
    """전략 walk-forward 실행 → OOS net Sharpe + FROZEN holdout Sharpe/maxDD.

    cost_bps / fx_series 는 필수 — None 이면 ValueError (gross/통화-naive 검증 차단).
    WalkForwardValidator 가 결과를 walkforward_runs 에 기록한다.

    Returns: 요약 dict (oos_sharpe_mean, holdout_sharpe, holdout_max_drawdown,
             selected_lookback_holdout, frozen_universe_n, gate.passed, ...).
    """
    if cost_bps is None:
        raise ValueError("cost_bps required — gross(거래비용 미반영) 검증은 승격 근거로 금지")
    if fx_series is None:
        raise ValueError("fx_series (KRW/USD) required — 통화-naive 검증은 승격 근거로 금지")

    cfg = config or _load_wf_config()
    if prices is None:
        prices = _build_us_panel(db_path)
    if prices.empty or len(prices) < 2:
        raise ValueError("insufficient price history for walk-forward")

    grid: list[int] = cfg["strategy"]["lookback_grid"]
    top_n: int = cfg["strategy"]["top_n"]
    reb: int = cfg["strategy"]["rebalance_days"]
    haircut_daily = cfg["costs"]["survivorship_haircut_bps_annual"] / 10000.0 / 252.0
    gate = cfg["gate"]

    frozen = list(prices.columns)
    fx_ret = fx_series.pct_change(fill_method=None).reindex(prices.index).fillna(0.0)

    # lookback 별 net return 시계열 → 공통 warmup(=max lookback) 이후만 사용 (warmup 편향 제거)
    series = {L: _strategy_net_returns(prices, fx_ret, L, top_n, reb, cost_bps, haircut_daily) for L in grid}
    warmup = max(grid)
    if len(prices) <= warmup + 2:
        raise ValueError(f"need > {warmup + 2} rows after warmup={warmup}, got {len(prices)}")

    aligned = {L: series[L].iloc[warmup:].reset_index(drop=True) for L in grid}
    dates = prices.index[warmup:]
    n = len(dates)
    holdout_n = int(n * cfg["holdout"]["frac"])
    split = n - holdout_n  # walk-forward 는 [0, split), holdout 은 [split, n)

    # validator data (non-holdout 만)
    data = pd.DataFrame({"date": pd.DatetimeIndex(dates).strftime("%Y-%m-%d")})
    for L in grid:
        data[f"r_lb{L}"] = aligned[L].to_numpy()
    data_wf = data.iloc[:split].reset_index(drop=True)

    def model_fn(train_df: pd.DataFrame):
        # 'fit' = train fold 에서 OOS Sharpe 최대 lookback 선택
        best_l = max(grid, key=lambda L: _sharpe_from_returns(train_df[f"r_lb{L}"].to_numpy()))

        def predict_fn(test_df: pd.DataFrame) -> np.ndarray:
            return test_df[f"r_lb{best_l}"].to_numpy()

        return predict_fn

    actor = WalkForwardValidator()
    result = actor.run(
        {
            "action": "run",
            "data": data_wf,
            "fold_spec": cfg["fold"],
            "model_fn": model_fn,
            # target_col 은 형식 요건 — 평가 지표는 predict 의 Sharpe(net return) 만 소비.
            "target_col": f"r_lb{grid[0]}",
            "metric_kind": "regression",
            "model_id": "momentum-topN-walkforward",
        }
    )
    oos_sharpe = result.output.get("metrics", {}).get("aggregate", {}).get("sharpe_mean")

    # ── null-safe gate (#701): pooled OOS Sharpe + permutation null ──
    # per-fold Sharpe 평균은 분산이 커 절대 임계만으론 noise 도 통과. pooled(전 OOS 수익률
    # 단일 Sharpe) + 시간셔플 순열 null 로 리밸런싱 artifact + lookback 선택 편향을 동시 차감.
    aligned_arr = {L: aligned[L].to_numpy() for L in grid}
    real_pooled = _pooled_oos_sharpe(aligned_arr, grid, cfg["fold"], split)

    perm_cfg = gate.get("permutation", {})
    n_perm = int(perm_cfg.get("n", 200))
    alpha = float(perm_cfg.get("alpha", 0.05))
    rng = np.random.default_rng(int(perm_cfg.get("seed", 0)))
    null_pooled = np.empty(n_perm)
    for i in range(n_perm):
        pa = _aligned_net_returns(
            _permute_prices(prices, rng), fx_ret, grid, top_n, reb, cost_bps, haircut_daily, warmup
        )
        null_pooled[i] = _pooled_oos_sharpe(pa, grid, cfg["fold"], split)
    # 무편향 Monte-Carlo p-value (+1 smoothing → p>0). real 이 null 분포를 이길수록 작다.
    p_value = float((np.sum(null_pooled >= real_pooled) + 1) / (n_perm + 1)) if n_perm else 1.0
    null_p95 = float(np.percentile(null_pooled, 95)) if n_perm else float("nan")

    # FROZEN holdout: non-holdout 전체에서 고른 lookback 으로 holdout 1회 평가.
    # 비대칭 의도: 순열 검정(통계 유의)은 walk-forward leg 가 binding gate 이고, holdout 은
    # 절대 floor(>= min_holdout_sharpe)만 적용하는 sanity 확인. (holdout 순열은 단일 window
    # 라 고분산 → 별도 STRATEGY PR 에서 필요 시 추가.)
    best_l_full = max(grid, key=lambda L: _sharpe_from_returns(aligned[L].iloc[:split].to_numpy()))
    holdout_ret = aligned[best_l_full].iloc[split:].to_numpy()
    holdout_sharpe = _sharpe_from_returns(holdout_ret)
    holdout_drawdown = _max_drawdown(holdout_ret)

    # 통과 = 통계 유의(noise 초과) + 경제적 유의(최소 Sharpe) + holdout 비음수. 셋 다 (defense in depth).
    passed = p_value < alpha and real_pooled >= gate["min_oos_sharpe"] and holdout_sharpe >= gate["min_holdout_sharpe"]

    if persist:
        # 검증된 walk-forward 요약을 backtests 테이블에 1행 기록 (단일 소스 → /api/research/backtests).
        # total_return/win_rate 은 walk-forward 가 산출 안 함 → NULL. 상세는 walkforward_runs.
        save_backtest(
            strategy_id="momentum-topN-walkforward",
            start_date=pd.Timestamp(dates[0]).strftime("%Y-%m-%d"),
            end_date=pd.Timestamp(dates[-1]).strftime("%Y-%m-%d"),
            total_return=None,
            sharpe=real_pooled,
            max_drawdown=holdout_drawdown,
            win_rate=None,
            params={
                "gate_passed": bool(passed),
                "p_value": p_value,
                "alpha": alpha,
                "oos_sharpe_pooled": real_pooled,
                "holdout_sharpe": holdout_sharpe,
                "selected_lookback": best_l_full,
                "n_folds": result.output.get("n_folds"),
                "frozen_universe_n": len(frozen),
                "cost_bps": cost_bps,
            },
            db_path=db_path,
        )

    return {
        "model_id": "momentum-topN-walkforward",
        "walkforward_run_id": result.output.get("run_id"),
        "n_folds": result.output.get("n_folds"),
        # outcome 은 Optional[Outcome] 타입이나 action=run 은 항상 PASS/WARN 설정
        "outcome": result.outcome.name if result.outcome is not None else "UNKNOWN",
        "oos_sharpe_mean": oos_sharpe,  # validator per-fold 평균 (audit 연속성)
        "oos_sharpe_pooled": real_pooled,  # gate 입력 (저분산)
        "holdout_sharpe": holdout_sharpe,
        "holdout_max_drawdown": holdout_drawdown,
        "selected_lookback_holdout": best_l_full,
        "walkforward_n": split,  # walk-forward 가 본 row 수 (holdout 제외)
        "holdout_n": holdout_n,  # FROZEN holdout row 수 (봉인)
        "frozen_universe_n": len(frozen),
        "cost_bps": cost_bps,
        "survivorship_haircut_bps_annual": cfg["costs"]["survivorship_haircut_bps_annual"],
        "holdout_frac": cfg["holdout"]["frac"],
        # 순열 검정: real pooled OOS Sharpe 가 시간셔플 null 분포를 p<alpha 로 이겨야 통과
        "permutation": {"n": n_perm, "p_value": p_value, "null_p95": null_p95},
        "gate": {
            "passed": bool(passed),
            "min_oos_sharpe": gate["min_oos_sharpe"],
            "min_holdout_sharpe": gate["min_holdout_sharpe"],
            "alpha": alpha,
            "p_value": p_value,
        },
    }


def _load_fx_series(db_path: Optional[Path] = None) -> pd.Series:
    """macro 의 usd_krw 일별 시계열 (KRW/USD). FX 필수 입력 — 없으면 ValueError."""
    df = query_df("SELECT date, value FROM macro WHERE indicator='usd_krw' ORDER BY date", db_path=db_path)
    if df.empty:
        raise ValueError("usd_krw not in macro — FX 필수 (make collect 후 재시도)")
    return pd.Series(df["value"].to_numpy(), index=pd.to_datetime(df["date"]))


def run_strategy_validation(
    cost_bps: float = 10.0,
    db_path: Optional[Path] = None,
    config: Optional[dict] = None,
    persist: bool = True,
) -> dict[str, Any]:
    """CLI/verify 진입점: prices(DB) + usd_krw(macro) 로드 → walk-forward → (persist 시) backtests 기록.

    엔진(run_momentum_backtest)의 0-trade 깨진 백테스트를 대체하는 단일 검증 경로. cost_bps
    기본 10bps. fx 는 macro 에서 로드(필수). persist=True(make backtest) 면 backtests +
    walkforward_runs 양쪽 기록, persist=False(verify check) 면 backtests 미기록.
    """
    fx = _load_fx_series(db_path)
    return run_strategy_walkforward(cost_bps=cost_bps, fx_series=fx, db_path=db_path, config=config, persist=persist)


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m nuri.quant.validation.strategy_walkforward [--cost-bps 10]"""
    import argparse
    import json as _json
    import logging
    import sys

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(prog="strategy-walkforward")
    parser.add_argument("--cost-bps", type=float, default=10.0, help="거래비용 (bps, 필수 가정)")
    args = parser.parse_args(argv)

    try:
        r = run_strategy_validation(cost_bps=args.cost_bps)
    except ValueError as exc:
        print(_json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    print(f"\n{'=' * 52}")
    print("  Strategy Walk-Forward 검증 (momentum top-N)")
    print(f"{'=' * 52}")
    print(f"  Universe:           {r['frozen_universe_n']} US tickers | folds {r['n_folds']}")
    print(f"  OOS pooled Sharpe:  {r['oos_sharpe_pooled']:>+8.3f}")
    print(f"  순열 p-value:        {r['permutation']['p_value']:>8.3f}  (null p95 {r['permutation']['null_p95']:+.2f})")
    print(f"  Holdout Sharpe:     {r['holdout_sharpe']:>+8.3f}  (maxDD {r['holdout_max_drawdown']:+.2f})")
    print(f"  >>> GATE PASSED:    {r['gate']['passed']}")
    print()
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())

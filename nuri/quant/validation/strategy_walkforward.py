"""전략 walk-forward 검증 어댑터 (P1b) — WalkForwardValidator 의 첫 caller.

미국 모멘텀 top-N 전략을 walk-forward 로 검증한다. 각 train fold 에서 lookback 을
선택(= model 'fit')하고 다음 test fold 에서 OOS 평가한다. 수익률은 **거래비용 +
KRW→USD FX + 생존자 haircut 차감 후**의 KRW home-currency net return 이다
(KakaoPay 계좌 통화 = KRW; US 보유분의 실현 P&L 은 FX drift 를 포함).

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
- 승격(weight>0)은 이 결과 + max-drawdown 통과 후 **별도 STRATEGY PR**. 이 모듈은 측정만 한다.

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

from nuri.agents.actors.walkforward_validator import WalkForwardValidator, _sharpe_from_returns
from nuri.core.db import query_df

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
    rets = prices.pct_change()
    mom = prices.pct_change(lookback)
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


def run_strategy_walkforward(
    *,
    cost_bps: float,
    fx_series: pd.Series,
    prices: Optional[pd.DataFrame] = None,
    db_path: Optional[Path] = None,
    config: Optional[dict] = None,
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
    fx_ret = fx_series.pct_change().reindex(prices.index).fillna(0.0)

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

    # FROZEN holdout: non-holdout 전체에서 고른 lookback 으로 holdout 1회 평가
    best_l_full = max(grid, key=lambda L: _sharpe_from_returns(aligned[L].iloc[:split].to_numpy()))
    holdout_ret = aligned[best_l_full].iloc[split:].to_numpy()
    holdout_sharpe = _sharpe_from_returns(holdout_ret)
    holdout_drawdown = _max_drawdown(holdout_ret)

    passed = (
        oos_sharpe is not None and oos_sharpe >= gate["min_oos_sharpe"] and holdout_sharpe >= gate["min_holdout_sharpe"]
    )

    return {
        "model_id": "momentum-topN-walkforward",
        "walkforward_run_id": result.output.get("run_id"),
        "n_folds": result.output.get("n_folds"),
        # outcome 은 Optional[Outcome] 타입이나 action=run 은 항상 PASS/WARN 설정
        "outcome": result.outcome.name if result.outcome is not None else "UNKNOWN",
        "oos_sharpe_mean": oos_sharpe,
        "holdout_sharpe": holdout_sharpe,
        "holdout_max_drawdown": holdout_drawdown,
        "selected_lookback_holdout": best_l_full,
        "walkforward_n": split,  # walk-forward 가 본 row 수 (holdout 제외)
        "holdout_n": holdout_n,  # FROZEN holdout row 수 (봉인)
        "frozen_universe_n": len(frozen),
        "cost_bps": cost_bps,
        "survivorship_haircut_bps_annual": cfg["costs"]["survivorship_haircut_bps_annual"],
        "holdout_frac": cfg["holdout"]["frac"],
        "gate": {
            "passed": bool(passed),
            "min_oos_sharpe": gate["min_oos_sharpe"],
            "min_holdout_sharpe": gate["min_holdout_sharpe"],
        },
    }

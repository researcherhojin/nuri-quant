"""Pre-registered 변형 edge search 하니스 (#706) — 여러 신호함수를 동일 #701 gate 로.

config/walkforward_variants.yaml 에 *결과를 보기 전에* 동결된 변형 set(이론 동기 ≤5개)을
단일 측정 절차로 돌린다. 각 변형 = price/volume 패널 위의 select_fn (registry 매핑).

p-hacking 차단 규율 (둘 다 통과해야 승격 자격):
- **Bonferroni 발견단계**: 검정 변형(baseline 제외) k개 → 순열 p < alpha/k AND
  pooled OOS Sharpe ≥ min. 변형을 여럿 시도하는 것 자체가 다중비교이므로 가족 오류율 통제.
- **FROZEN holdout 재확인**: 발견단계 통과 변형만 최근 frac 봉인 구간에서 1회 재평가
  (holdout Sharpe ≥ min floor). walk-forward 가 한 번도 보지 않은 구간.

패널 품질 필터(사전등록, 모든 변형 + permutation null 에 동일 적용):
- exclude_tickers: KRW 지수/선물/테스트 pseudo-ticker 제거 (통화 오염 — 실측 KOSDAQ 적발)
- min_history: 종목별 최소 non-NaN close 일수 (얕은 신규 backfill 제외)
- min_breadth: cross-section 폭 미달 선두 날짜 trim (1~2종목 degenerate fold 제거)

baseline(strategy_walkforward)과 동일 규율 유지: 거래비용+FX 필수 입력, same-bar
lookahead 차단(선택일 수익은 이전 보유분), 생존자 haircut, first-valid-anchor 순열(#707).
승격(weight>0)은 이 runner 통과 + 별도 STRATEGY PR. 이 모듈은 측정만 한다.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

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
from nuri.quant.validation.strategy_walkforward import (
    _max_drawdown,
    _permute_prices,
    _pooled_oos_sharpe,
)

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config" / "walkforward_variants.yaml"

# select_fn(close, vol, i, param, top_n, variant_cfg) -> 보유 ticker 리스트.
# bar i 까지의 데이터(close[i] 포함)로 선택하며, 수익 적립은 i+1 부터 (same-bar 차단은
# _variant_daily_returns 의 루프 순서가 보장 — baseline _portfolio_usd_returns 와 동일).
SelectFn = Callable[[pd.DataFrame, Optional[pd.DataFrame], int, dict, int, dict], list[str]]


def _load_variants_config(path: Optional[Path] = None) -> dict:
    """config/walkforward_variants.yaml 로드 (pre-registered 파라미터)."""
    with open(path or _CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── select_fn registry (V0-V4) ─────────────────────────────────


def _top_n(scores: pd.Series, top_n: int) -> list[str]:
    """NaN 제외 상위 top_n ticker (후보 부족 시 가능한 만큼)."""
    s = scores.dropna()
    return s.nlargest(min(top_n, len(s))).index.tolist()


def _sel_momentum(close, vol, i, param, top_n, variant_cfg) -> list[str]:
    """V0 대조군: trailing-return top-N (baseline 과 동일 신호)."""
    lb = param["lookback"]
    return _top_n(close.iloc[i] / close.iloc[i - lb] - 1.0, top_n)


def _sel_skip_momentum(close, vol, i, param, top_n, variant_cfg) -> list[str]:
    """V1: 12-1 skip-month 모멘텀 — t-lookback → t-skip 수익률 (최근 skip 일 반전 제외)."""
    lb, skip = param["lookback"], param["skip"]
    return _top_n(close.iloc[i - skip] / close.iloc[i - lb] - 1.0, top_n)


def _sel_vol_scaled(close, vol, i, param, top_n, variant_cfg) -> list[str]:
    """V2: 변동성-스케일 모멘텀 — 일평균수익/일변동성 (Sharpe-류 랭킹)."""
    lb = param["lookback"]
    window = close.iloc[i - lb + 1 : i + 1].pct_change(fill_method=None)
    sd = window.std()
    score = window.mean() / sd.replace(0.0, np.nan)
    return _top_n(score, top_n)


def _sel_volume_confirmed(close, vol, i, param, top_n, variant_cfg) -> list[str]:
    """V3: 거래대금-확인 리더 — 모멘텀 top-2N 중 거래대금 surge 상위 N."""
    lb, sw = param["lookback"], param["surge_window"]
    cand = _top_n(close.iloc[i] / close.iloc[i - lb] - 1.0, 2 * top_n)
    if not cand:
        return []
    dv = close[cand].iloc[i - lb + 1 : i + 1] * vol[cand].iloc[i - lb + 1 : i + 1]
    surge = dv.iloc[-sw:].mean() / dv.mean().replace(0.0, np.nan)
    return _top_n(surge, top_n)


def _sel_regime_momentum(close, vol, i, param, top_n, variant_cfg) -> list[str]:
    """V4: regime-조건부 모멘텀 — 지표 ticker < MA(고정) 면 cash (Momentum Crashes 좌측꼬리 제거)."""
    regime = variant_cfg["regime"]
    spy = close[regime["ticker"]]
    ma = regime["ma"]
    if spy.iloc[i] < spy.iloc[i - ma + 1 : i + 1].mean():
        return []
    return _sel_momentum(close, vol, i, param, top_n, variant_cfg)


_SELECT_REGISTRY: dict[str, SelectFn] = {
    "momentum": _sel_momentum,
    "skip_momentum": _sel_skip_momentum,
    "vol_scaled": _sel_vol_scaled,
    "volume_confirmed": _sel_volume_confirmed,
    "regime_momentum": _sel_regime_momentum,
}


def _param_warmup(variant: dict, param: dict) -> int:
    """param 이 읽는 최대 과거 bar 수 (regime MA 포함)."""
    w = param["lookback"]
    if "regime" in variant:
        w = max(w, variant["regime"]["ma"])
    return w


# ── 패널 (close + volume, 품질 필터) ───────────────────────────


def _build_panels(cfg: dict, db_path: Optional[Path] = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """prices 에서 (close, volume) US 패널 — 사전등록 품질 필터 적용.

    .KS 제외(통화 혼합 방지) + exclude_tickers(지수/선물/테스트) + min_history +
    min_breadth 선두 trim. 필터는 모든 변형과 permutation null 에 동일하게 적용된다.
    """
    pc = cfg["panel"]
    df = query_df("SELECT ticker, date, close, volume FROM prices ORDER BY date", db_path=db_path)
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
    excl = set(pc["exclude_tickers"])
    df = df[~df["ticker"].str.endswith(".KS") & ~df["ticker"].isin(excl)]
    close = df.pivot_table(index="date", columns="ticker", values="close")
    close.index = pd.to_datetime(close.index)
    # min_history: 종목별 충분한 실데이터 (ffill 전 기준)
    counts = close.notna().sum()
    keep = [t for t in close.columns if counts[t] >= pc["min_history"]]
    if not keep:
        return pd.DataFrame(), pd.DataFrame()
    close = close[keep]
    # min_breadth: cross-section 폭 미달 선두 구간 trim (degenerate fold 제거)
    width = close.notna().sum(axis=1)
    ok = width[width >= pc["min_breadth"]]
    if ok.empty:
        return pd.DataFrame(), pd.DataFrame()
    close = close.loc[ok.index[0] :]
    vol = df.pivot_table(index="date", columns="ticker", values="volume")
    vol.index = pd.to_datetime(vol.index)
    vol = vol.reindex(index=close.index, columns=close.columns)
    return close.ffill(), vol.ffill()


# ── 일별 net return (변형 일반화) ──────────────────────────────


def _variant_daily_returns(
    close: pd.DataFrame,
    vol: Optional[pd.DataFrame],
    select_fn: SelectFn,
    param: dict,
    variant: dict,
    top_n: int,
    rebalance_days: int,
    warmup: int,
) -> tuple[pd.Series, pd.Series]:
    """select_fn 보유 set 의 일별 USD 수익률 + turnover (same-bar lookahead 차단).

    baseline _portfolio_usd_returns 와 동일 규율: day-i 수익은 *이전* 보유분으로 벌고,
    리밸런싱(bar i 신호)은 i+1 부터 유효. 일별 적립은 numpy (순열 200회 × 변형 비용 절감).
    """
    n = len(close.index)
    rets_np = close.pct_change(fill_method=None).to_numpy()
    col_idx = {t: j for j, t in enumerate(close.columns)}
    daily = np.zeros(n)
    turnover = np.zeros(n)
    held: list[str] = []
    held_idx: list[int] = []
    for i in range(n):
        if i < warmup:
            continue
        if held_idx:
            daily[i] = float(np.nanmean(rets_np[i, held_idx]))
        if (i - warmup) % rebalance_days == 0:
            new = select_fn(close, vol, i, param, top_n, variant)
            prev, new_set = set(held), set(new)
            if not prev:
                turnover[i] = 1.0 if new_set else 0.0
            else:
                turnover[i] = len(prev.symmetric_difference(new_set)) / (2 * top_n)
            held = new
            held_idx = [col_idx[t] for t in new]
    return pd.Series(daily, index=close.index), pd.Series(turnover, index=close.index)


def _variant_net_returns(
    close: pd.DataFrame,
    vol: Optional[pd.DataFrame],
    fx_ret: pd.Series,
    select_fn: SelectFn,
    param: dict,
    variant: dict,
    top_n: int,
    rebalance_days: int,
    cost_bps: float,
    haircut_daily: float,
    warmup: int,
) -> pd.Series:
    """거래비용 + FX + 생존자 haircut 차감 후 KRW net return (baseline 과 동일 공식)."""
    usd, turnover = _variant_daily_returns(close, vol, select_fn, param, variant, top_n, rebalance_days, warmup)
    krw = (1.0 + usd) * (1.0 + fx_ret) - 1.0
    net = krw - turnover * (cost_bps / 10000.0) - haircut_daily
    net.iloc[:warmup] = 0.0
    return net


def _aligned_variant_returns(
    close: pd.DataFrame,
    vol: Optional[pd.DataFrame],
    fx_ret: pd.Series,
    variant: dict,
    cfg: dict,
    cost_bps: float,
    common_warmup: int,
) -> dict[int, np.ndarray]:
    """변형의 param-index 별 net return (공통 warmup 이후 정렬) → {k: np.ndarray}."""
    top_n = cfg["portfolio"]["top_n"]
    reb = cfg["portfolio"]["rebalance_days"]
    haircut = cfg["costs"]["survivorship_haircut_bps_annual"] / 10000.0 / 252.0
    select_fn = _SELECT_REGISTRY[variant["select"]]
    out: dict[int, np.ndarray] = {}
    for k, param in enumerate(variant["params"]):
        w = _param_warmup(variant, param)
        net = _variant_net_returns(close, vol, fx_ret, select_fn, param, variant, top_n, reb, cost_bps, haircut, w)
        out[k] = net.iloc[common_warmup:].reset_index(drop=True).to_numpy()
    return out


# ── 변형 1개 평가 (gate 공통 절차) ─────────────────────────────


def _evaluate_variant(
    close: pd.DataFrame,
    vol: Optional[pd.DataFrame],
    fx_ret: pd.Series,
    variant: dict,
    cfg: dict,
    cost_bps: float,
    alpha_eff: float,
) -> dict[str, Any]:
    """단일 변형: pooled OOS Sharpe + 순열 p + FROZEN holdout (baseline 과 동일 절차)."""
    gate = cfg["gate"]
    keys = list(range(len(variant["params"])))
    warmup = max(_param_warmup(variant, p) for p in variant["params"])
    if len(close) <= warmup + 2:
        raise ValueError(f"{variant['name']}: need > {warmup + 2} rows after warmup={warmup}, got {len(close)}")

    aligned = _aligned_variant_returns(close, vol, fx_ret, variant, cfg, cost_bps, warmup)
    n = len(close.index) - warmup
    holdout_n = int(n * cfg["holdout"]["frac"])
    split = n - holdout_n

    real_pooled = _pooled_oos_sharpe(aligned, keys, cfg["fold"], split)
    n_folds = len(_generate_folds(split, FoldSpec(**cfg["fold"])))

    # permutation null: close 만 셔플 (#707 first-valid anchor), volume 은 원본 유지 —
    # 가격 예측성만 파괴해 "거래대금이 (셔플된) 미래 수익을 맞추는가" 를 검정.
    perm = gate["permutation"]
    rng = np.random.default_rng(int(perm["seed"]))
    n_perm = int(perm["n"])
    null_pooled = np.empty(n_perm)
    for j in range(n_perm):
        pa = _aligned_variant_returns(_permute_prices(close, rng), vol, fx_ret, variant, cfg, cost_bps, warmup)
        null_pooled[j] = _pooled_oos_sharpe(pa, keys, cfg["fold"], split)
    p_value = float((np.sum(null_pooled >= real_pooled) + 1) / (n_perm + 1)) if n_perm else 1.0

    # FROZEN holdout: non-holdout 전체에서 고른 param 으로 1회 평가 (발견단계 통과 시만 의미)
    best_k = max(keys, key=lambda k: _sharpe_from_returns(aligned[k][:split]))
    holdout_ret = aligned[best_k][split:]
    holdout_sharpe = _sharpe_from_returns(holdout_ret)

    discovery = p_value < alpha_eff and real_pooled >= gate["min_oos_sharpe"]
    holdout_ok = holdout_sharpe >= gate["min_holdout_sharpe"]
    return {
        "name": variant["name"],
        "baseline": bool(variant.get("baseline", False)),
        "theory": variant["theory"],
        "oos_sharpe_pooled": real_pooled,
        "p_value": p_value,
        "null_p95": float(np.percentile(null_pooled, 95)) if n_perm else float("nan"),
        "alpha_effective": alpha_eff,
        "n_folds": n_folds,
        "selected_param": variant["params"][best_k],
        "holdout_sharpe": holdout_sharpe,
        "holdout_max_drawdown": _max_drawdown(holdout_ret),
        "discovery_passed": bool(discovery),
        "holdout_passed": bool(holdout_ok),
        # 승격 자격 = Bonferroni 발견 AND holdout 재확인 (baseline 은 대조군 — 항상 False)
        "promotion_eligible": bool(discovery and holdout_ok and not variant.get("baseline", False)),
        "walkforward_n": split,
        "holdout_n": holdout_n,
    }


# ── runner ─────────────────────────────────────────────────────


def run_variant_search(
    *,
    cost_bps: float,
    fx_series: pd.Series,
    close: Optional[pd.DataFrame] = None,
    vol: Optional[pd.DataFrame] = None,
    db_path: Optional[Path] = None,
    config: Optional[dict] = None,
    persist: bool = False,
) -> dict[str, Any]:
    """pre-registered 변형 전체를 동일 gate 로 측정 → 결과 표 + 승격 자격 판정.

    cost_bps / fx_series 필수 (gross/통화-naive 검증 차단 — baseline 과 동일).
    persist=True 면 변형별 1행을 backtests 에 기록 (/api/research/backtests surface).
    """
    if cost_bps is None:
        raise ValueError("cost_bps required — gross(거래비용 미반영) 검증은 승격 근거로 금지")
    if fx_series is None:
        raise ValueError("fx_series (KRW/USD) required — 통화-naive 검증은 승격 근거로 금지")

    cfg = config or _load_variants_config()
    if close is None:
        close, vol = _build_panels(cfg, db_path=db_path)
    if close.empty or len(close) < 2:
        raise ValueError("insufficient price history after panel quality filter")

    variants = cfg["variants"]
    unknown = [v["select"] for v in variants if v["select"] not in _SELECT_REGISTRY]
    if unknown:
        raise ValueError(f"unknown select_fn in config: {unknown}")
    for v in variants:
        if "regime" in v and v["regime"]["ticker"] not in close.columns:
            raise ValueError(f"{v['name']}: regime ticker {v['regime']['ticker']} not in panel")

    # Bonferroni: 검정 변형(baseline 제외) 수로 alpha 분할 (가족 오류율 통제)
    n_test = sum(1 for v in variants if not v.get("baseline", False))
    alpha = float(cfg["gate"]["permutation"]["alpha"])
    alpha_eff = alpha / max(n_test, 1)

    fx_ret = fx_series.pct_change(fill_method=None).reindex(close.index).fillna(0.0)
    results = []
    for v in variants:
        logger.info("evaluating variant %s ...", v["name"])
        r = _evaluate_variant(close, vol, fx_ret, v, cfg, cost_bps, alpha_eff)
        results.append(r)
        if persist:
            save_backtest(
                strategy_id=f"wf-variant:{r['name']}",
                start_date=pd.Timestamp(close.index[0]).strftime("%Y-%m-%d"),
                end_date=pd.Timestamp(close.index[-1]).strftime("%Y-%m-%d"),
                total_return=None,
                sharpe=r["oos_sharpe_pooled"],
                max_drawdown=r["holdout_max_drawdown"],
                win_rate=None,
                params={
                    k: r[k]
                    for k in (
                        "baseline",
                        "theory",
                        "p_value",
                        "alpha_effective",
                        "holdout_sharpe",
                        "selected_param",
                        "discovery_passed",
                        "holdout_passed",
                        "promotion_eligible",
                        "n_folds",
                    )
                }
                | {"cost_bps": cost_bps, "universe_n": close.shape[1]},
                db_path=db_path,
            )

    # WalkForwardValidator 로 변형별 per-fold 기록 (walkforward_runs → /api/research/walkforward)
    run_ids = _log_walkforward_runs(close, vol, fx_ret, variants, cfg, cost_bps) if persist else {}
    for r in results:
        r["walkforward_run_id"] = run_ids.get(r["name"])

    return {
        "universe_n": close.shape[1],
        "panel_rows": len(close),
        "panel_start": pd.Timestamp(close.index[0]).strftime("%Y-%m-%d"),
        "panel_end": pd.Timestamp(close.index[-1]).strftime("%Y-%m-%d"),
        "cost_bps": cost_bps,
        "n_test_variants": n_test,
        "alpha": alpha,
        "alpha_effective": alpha_eff,
        "variants": results,
        "promotion_eligible": [r["name"] for r in results if r["promotion_eligible"]],
    }


def _log_walkforward_runs(
    close: pd.DataFrame,
    vol: Optional[pd.DataFrame],
    fx_ret: pd.Series,
    variants: list[dict],
    cfg: dict,
    cost_bps: float,
) -> dict[str, Optional[str]]:
    """변형별 WalkForwardValidator run (per-fold 메트릭 → walkforward_runs 기록)."""
    actor = WalkForwardValidator()
    run_ids: dict[str, Optional[str]] = {}
    for v in variants:
        keys = list(range(len(v["params"])))
        warmup = max(_param_warmup(v, p) for p in v["params"])
        aligned = _aligned_variant_returns(close, vol, fx_ret, v, cfg, cost_bps, warmup)
        n = len(close.index) - warmup
        split = n - int(n * cfg["holdout"]["frac"])
        data = pd.DataFrame({f"r_k{k}": aligned[k] for k in keys}).iloc[:split].reset_index(drop=True)

        def model_fn(train_df: pd.DataFrame, _keys=keys):
            best = max(_keys, key=lambda k: _sharpe_from_returns(train_df[f"r_k{k}"].to_numpy()))
            return lambda test_df: test_df[f"r_k{best}"].to_numpy()

        result = actor.run(
            {
                "action": "run",
                "data": data,
                "fold_spec": cfg["fold"],
                "model_fn": model_fn,
                "target_col": f"r_k{keys[0]}",  # 형식 요건 — 평가는 predict 수익률만 소비
                "metric_kind": "regression",
                "model_id": f"wf-variant:{v['name']}",
            }
        )
        run_ids[v["name"]] = result.output.get("run_id")
    return run_ids


def run_variant_validation(
    cost_bps: float = 10.0,
    db_path: Optional[Path] = None,
    config: Optional[dict] = None,
    persist: bool = True,
) -> dict[str, Any]:
    """CLI 진입점: prices(DB) + usd_krw(macro) 로드 → 변형 search → (persist 시) 기록."""
    from nuri.quant.validation.strategy_walkforward import _load_fx_series

    fx = _load_fx_series(db_path)
    return run_variant_search(cost_bps=cost_bps, fx_series=fx, db_path=db_path, config=config, persist=persist)


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m nuri.quant.validation.variant_walkforward [--cost-bps 10] [--no-persist]"""
    import argparse
    import json as _json
    import sys

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(prog="variant-walkforward")
    parser.add_argument("--cost-bps", type=float, default=10.0, help="거래비용 (bps, 필수 가정)")
    parser.add_argument("--no-persist", action="store_true", help="backtests/walkforward_runs 기록 생략")
    args = parser.parse_args(argv)

    try:
        r = run_variant_validation(cost_bps=args.cost_bps, persist=not args.no_persist)
    except ValueError as exc:
        print(_json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    print(f"\n{'=' * 78}")
    print("  Pre-registered Variant Edge Search (#706)")
    print(f"  Universe {r['universe_n']} | {r['panel_start']}..{r['panel_end']} | cost {r['cost_bps']}bps", end="")
    print(f" | Bonferroni alpha {r['alpha']}/{r['n_test_variants']} = {r['alpha_effective']:.4f}")
    print(f"{'=' * 78}")
    print(f"  {'variant':<22}{'pooled':>8}{'p':>8}{'null95':>8}{'holdout':>9}{'maxDD':>8}  verdict")
    for v in r["variants"]:
        verdict = "PROMOTE-ELIGIBLE" if v["promotion_eligible"] else ("baseline" if v["baseline"] else "FAIL")
        print(
            f"  {v['name']:<22}{v['oos_sharpe_pooled']:>+8.3f}{v['p_value']:>8.3f}{v['null_p95']:>+8.2f}"
            f"{v['holdout_sharpe']:>+9.3f}{v['holdout_max_drawdown']:>+8.2f}  {verdict}"
        )
    print(f"\n  >>> promotion-eligible: {r['promotion_eligible'] or 'NONE — 노이즈 초과 엣지 없음'}")
    print()
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())

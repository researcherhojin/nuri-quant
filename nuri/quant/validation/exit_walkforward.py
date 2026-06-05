"""P4 exit-룰 사후검증 하니스 (#713) — pre-registered E0-E4 를 동일 순열 gate 로.

config/walkforward_exits.yaml 에 *결과를 보기 전에* 동결된 exit 룰 5개(E0 현행 ladder
대조 + E1-E4 검정)를 **랜덤 진입 Monte Carlo** testbed 에서 paired 비교한다.

설계 (#706 규율 상속 + exit 특화):
- **랜덤 진입**: 무작위 (ticker, 진입일) 쌍 N개를 모든 룰이 공유 → 진입 신호와 분리된
  순수 exit 기여 측정 (paired). momentum 진입은 #706 에서 엣지 없음 확정.
- **주 지표 = ΔSharpe(룰 − E0)**: 동일 진입 집합에서 룰별 일별 net 포트폴리오 수익률
  (활성 포지션 평균, 비용+FX+haircut 차감) 의 Sharpe 차이.
- **순열 null**: exit 룰은 가격 *경로*(추세 지속·드로다운)를 착취한다. 시간셔플(#707
  first-valid anchor)은 분포는 보존하고 경로 구조만 파괴 → 셔플 경로에서도 나오는
  ΔSharpe 는 룰의 가치가 아닌 mechanical artifact. 발견 = Δp < alpha/k (Bonferroni).
- **FROZEN holdout**: 패널 마지막 frac 구간에 진입하는 포지션은 봉인. 발견 통과 룰만
  1회 개봉 (Δ ≥ floor). discovery 진입은 만기가 holdout 시작 전에 끝나는 것만
  (경계 누설 차단 buffer — 사이 진입은 제외).
- 체결 규약(동결): 진입 = 진입일 종가, 이벤트 판정 = 일별 종가, 같은 날 중복 시
  full-exit(stop/trailing/MA) 이 partial(TP) 에 우선. 거래비용은 거래 fraction 에 부과.
- 통과 룰의 rules.yaml 반영은 **별도 STRATEGY PR** — 이 모듈은 측정만 한다.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import yaml

from nuri.agents.actors.walkforward_validator import _sharpe_from_returns
from nuri.core.db import save_backtest
from nuri.quant.validation.strategy_walkforward import _max_drawdown, _permute_prices
from nuri.quant.validation.variant_walkforward import _build_panels

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config" / "walkforward_exits.yaml"


def _load_exits_config(path: Optional[Path] = None) -> dict:
    """config/walkforward_exits.yaml 로드 (pre-registered 파라미터)."""
    with open(path or _CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── 진입 샘플링 (모든 룰 공유 — paired) ────────────────────────


def _sample_entries(close: pd.DataFrame, ecfg: dict) -> list[tuple[int, int]]:
    """무작위 (col_idx, t0) 진입 쌍 — 진입일 종가가 유효한 조합만.

    seed 고정 → 모든 룰·모든 순열 패널이 동일 진입 set 사용 (paired 비교의 전제).
    """
    rng = np.random.default_rng(int(ecfg["seed"]))
    arr = close.to_numpy()
    n_days, n_cols = arr.shape
    lo, hi = int(ecfg["warmup"]), n_days - 2  # 최소 1일은 보유 가능해야
    if hi <= lo:
        raise ValueError(f"panel too short for entries: warmup={lo}, days={n_days}")
    out: list[tuple[int, int]] = []
    target = int(ecfg["n"])
    # 유효 진입(종가 존재)만 수집 — 무한루프 방지 상한
    for _ in range(target * 10):
        if len(out) >= target:
            break
        j = int(rng.integers(0, n_cols))
        t0 = int(rng.integers(lo, hi + 1))
        if not np.isnan(arr[t0, j]):
            out.append((j, t0))
    if len(out) < target:
        logger.warning("entries: %d/%d sampled (sparse panel)", len(out), target)
    return out


# ── 단일 포지션 exit 해석 (first-crossing, 결정론) ─────────────


def _first_at_or_after(mask: np.ndarray) -> int:
    """mask[1:] 중 첫 True 의 index (없으면 큰 수). index 는 윈도 내 day(1..H)."""
    idx = np.flatnonzero(mask[1:])
    return int(idx[0]) + 1 if idx.size else 10**9


def _resolve_exit(
    c: np.ndarray, ma: Optional[np.ndarray], rule: dict, horizon: int
) -> tuple[int, list[tuple[int, float]]]:
    """포지션 가격 윈도 c[0..H](c[0]=진입 종가)에 rule 적용 → (청산 day, [(day, 매도 fraction)]).

    full-exit 후보 = stop / trailing / MA-이탈 / horizon 중 최선착. partial(TP) 은
    full-exit 이전에 발생한 것만 유효. 같은 날 충돌 시 full-exit 우선 (동결 규약).
    """
    H = len(c) - 1
    entry = c[0]
    liq_candidates = [min(H, horizon)]

    if "stop_pct" in rule:
        liq_candidates.append(_first_at_or_after(c <= entry * (1.0 + rule["stop_pct"] / 100.0)))
    if "trailing_pct" in rule:
        hwm = np.maximum.accumulate(c)
        liq_candidates.append(_first_at_or_after(c <= hwm * (1.0 + rule["trailing_pct"] / 100.0)))
    if "trail_ma" in rule and ma is not None:
        below = np.where(np.isnan(ma), False, c < ma)  # MA 미계산 구간은 보유 (#679 와 동일)
        liq_candidates.append(_first_at_or_after(below))

    liq = min(liq_candidates)
    events: list[tuple[int, float]] = []
    remaining = 1.0
    for key in ("tp1", "tp2"):
        if key in rule:
            d = _first_at_or_after(c >= entry * (1.0 + rule[key]["pct"] / 100.0))
            if d < liq:  # full-exit 과 같은 날이면 full-exit 우선
                frac = rule[key]["sell"]
                events.append((d, frac))
                remaining -= frac
    events.append((liq, remaining))  # 청산일에 잔여 전량
    return liq, events


# ── 룰별 일별 USD 수익률 (포지션 집계) ─────────────────────────


def _simulate_rule(
    close: pd.DataFrame,
    entries: list[tuple[int, int]],
    rule: dict,
    cost_bps: float,
    max_horizon: int,
) -> tuple[np.ndarray, np.ndarray]:
    """전 진입 포지션에 rule 적용 → (일별 수익 합, 일별 활성 수) 배열.

    포지션 day-k 수익 = (직전 보유 fraction) × 종목 수익률 − 그날 거래비용.
    진입 매수 비용은 첫 보유일에 부과. 활성 = 진입 다음날부터 청산일까지.
    """
    arr = close.to_numpy()
    n_days = arr.shape[0]
    ma_arr: Optional[np.ndarray] = None
    if "trail_ma" in rule:
        ma_arr = close.rolling(int(rule["trail_ma"])).mean().to_numpy()

    cost = cost_bps / 10000.0
    daily_sum = np.zeros(n_days)
    daily_cnt = np.zeros(n_days)
    for j, t0 in entries:
        end = min(t0 + max_horizon, n_days - 1)
        c = arr[t0 : end + 1, j]
        ma = ma_arr[t0 : end + 1, j] if ma_arr is not None else None
        liq, events = _resolve_exit(c, ma, rule, max_horizon)
        # 보유 fraction f[k] = day k(1..liq) 동안 보유분 — 이벤트 day d 매도는 d+1 부터 반영
        f = np.ones(liq + 1)  # index 1..liq 사용
        trade_cost = np.zeros(liq + 1)
        trade_cost[1] += cost  # 진입 매수 비용 (첫 보유일 부과)
        for d, frac in events:
            if d < liq:
                f[d + 1 :] -= frac
            trade_cost[d if d >= 1 else 1] += cost * frac
        r = c[1 : liq + 1] / c[:liq] - 1.0
        contrib = f[1:] * r - trade_cost[1:]
        daily_sum[t0 + 1 : t0 + 1 + liq] += contrib
        daily_cnt[t0 + 1 : t0 + 1 + liq] += 1.0
    return daily_sum, daily_cnt


def _rule_daily_krw(
    daily_sum: np.ndarray, daily_cnt: np.ndarray, fx_ret: np.ndarray, haircut_daily: float
) -> np.ndarray:
    """활성 포지션 평균 USD 수익률 → KRW net (FX + haircut). 활성 0 인 날은 0."""
    usd = np.divide(daily_sum, daily_cnt, out=np.zeros_like(daily_sum), where=daily_cnt > 0)
    krw = (1.0 + usd) * (1.0 + fx_ret) - 1.0 - haircut_daily
    return np.where(daily_cnt > 0, krw, 0.0)


# ── discovery / holdout 분할 (진입일 기준, buffer 동결) ────────


def _partition_entries(
    entries: list[tuple[int, int]], n_days: int, holdout_frac: float, max_horizon: int
) -> tuple[list[tuple[int, int]], list[tuple[int, int]], int]:
    """진입을 (discovery, holdout) 로 분할 — 경계 누설 차단.

    split = 패널 마지막 frac 시작점. discovery = 만기(진입+max_horizon)가 split 이전에
    끝나는 진입만, holdout = split 이후 진입만. 사이(경계 걸침) 진입은 제외 (buffer).
    """
    split = n_days - int(n_days * holdout_frac)
    disc = [(j, t0) for j, t0 in entries if t0 + max_horizon < split]
    hold = [(j, t0) for j, t0 in entries if t0 >= split]
    return disc, hold, split


# ── 룰 1개 평가 (paired ΔSharpe + 순열 gate) ──────────────────


def _delta_sharpe(
    close: pd.DataFrame,
    entries: list[tuple[int, int]],
    rule: dict,
    base_rule: dict,
    fx_ret: np.ndarray,
    cost_bps: float,
    haircut_daily: float,
    max_horizon: int,
) -> tuple[float, float, np.ndarray]:
    """ΔSharpe(rule − base) + rule Sharpe + rule 일별 KRW 시계열."""
    s_r, c_r = _simulate_rule(close, entries, rule, cost_bps, max_horizon)
    s_b, c_b = _simulate_rule(close, entries, base_rule, cost_bps, max_horizon)
    kr = _rule_daily_krw(s_r, c_r, fx_ret, haircut_daily)
    kb = _rule_daily_krw(s_b, c_b, fx_ret, haircut_daily)
    sr, sb = _sharpe_from_returns(kr), _sharpe_from_returns(kb)
    return sr - sb, sr, kr


def run_exit_search(
    *,
    cost_bps: float,
    fx_series: pd.Series,
    close: Optional[pd.DataFrame] = None,
    db_path: Optional[Path] = None,
    config: Optional[dict] = None,
    persist: bool = False,
) -> dict[str, Any]:
    """pre-registered exit 룰 전체를 paired 순열 gate 로 측정 → 결과 표 + 승격 자격.

    cost_bps / fx_series 필수 (gross/통화-naive 검증 차단). persist=True 면 룰별 1행을
    backtests(`wf-exit:*`) 에 기록.
    """
    if cost_bps is None:
        raise ValueError("cost_bps required — gross(거래비용 미반영) 검증은 승격 근거로 금지")
    if fx_series is None:
        raise ValueError("fx_series (KRW/USD) required — 통화-naive 검증은 승격 근거로 금지")

    cfg = config or _load_exits_config()
    if close is None:
        close, _vol = _build_panels(cfg, db_path=db_path)
    if close.empty or len(close) < 2:
        raise ValueError("insufficient price history after panel quality filter")

    rules: list[dict] = cfg["rules"]
    bases = [r for r in rules if r.get("baseline")]
    if len(bases) != 1:
        raise ValueError("exactly one baseline rule (E0) required")
    base_rule = bases[0]
    n_test = len(rules) - 1
    alpha = float(cfg["gate"]["permutation"]["alpha"])
    alpha_eff = alpha / max(n_test, 1)

    ecfg = cfg["entries"]
    max_horizon = int(ecfg["max_horizon"])
    haircut_daily = cfg["costs"]["survivorship_haircut_bps_annual"] / 10000.0 / 252.0
    fx_ret = fx_series.pct_change(fill_method=None).reindex(close.index).fillna(0.0).to_numpy()

    entries = _sample_entries(close, ecfg)
    disc, hold, split = _partition_entries(entries, len(close), cfg["holdout"]["frac"], max_horizon)
    if not disc:
        raise ValueError("no discovery entries — panel too short for max_horizon + holdout")

    perm = cfg["gate"]["permutation"]
    n_perm = int(perm["n"])
    min_delta = float(cfg["gate"]["min_delta_sharpe"])

    results: list[dict[str, Any]] = []
    for rule in rules:
        name = rule["name"]
        logger.info("evaluating exit rule %s ...", name)
        is_base = bool(rule.get("baseline", False))
        delta, sharpe, kr = _delta_sharpe(close, disc, rule, base_rule, fx_ret, cost_bps, haircut_daily, max_horizon)

        # 순열 null: 셔플 경로에서 같은 paired Δ 를 만들면 mechanical artifact.
        # seed 리셋 → 순열 j 가 룰 간 공유 (#706 과 동일한 공정 비교).
        p_value = 1.0
        null_p95 = float("nan")
        if not is_base:
            rng = np.random.default_rng(int(perm["seed"]))
            null_delta = np.empty(n_perm)
            for i in range(n_perm):
                pc = _permute_prices(close, rng)
                null_delta[i], _, _ = _delta_sharpe(
                    pc, disc, rule, base_rule, fx_ret, cost_bps, haircut_daily, max_horizon
                )
            p_value = float((np.sum(null_delta >= delta) + 1) / (n_perm + 1)) if n_perm else 1.0
            null_p95 = float(np.percentile(null_delta, 95)) if n_perm else float("nan")

        discovery = (not is_base) and p_value < alpha_eff and delta > min_delta

        # FROZEN holdout: 발견 통과 룰만 1회 개봉 (#706 codex P1 봉인 규약 상속)
        holdout_delta: Optional[float] = None
        holdout_ok = False
        if discovery and hold:
            holdout_delta, _, _ = _delta_sharpe(
                close, hold, rule, base_rule, fx_ret, cost_bps, haircut_daily, max_horizon
            )
            holdout_ok = holdout_delta >= float(cfg["gate"]["min_holdout_delta"])

        results.append(
            {
                "name": name,
                "baseline": is_base,
                "theory": rule["theory"],
                "sharpe": sharpe,
                "delta_sharpe": None if is_base else delta,
                "p_value": None if is_base else p_value,
                "null_p95": None if is_base else null_p95,
                "max_drawdown": _max_drawdown(kr),
                "discovery_passed": bool(discovery),
                "holdout_delta": holdout_delta,  # None = 봉인
                "holdout_passed": bool(holdout_ok),
                "promotion_eligible": bool(discovery and holdout_ok),
            }
        )
        if persist:
            save_backtest(
                strategy_id=f"wf-exit:{name}",
                start_date=pd.Timestamp(close.index[0]).strftime("%Y-%m-%d"),
                end_date=pd.Timestamp(close.index[-1]).strftime("%Y-%m-%d"),
                total_return=None,
                sharpe=sharpe,
                max_drawdown=results[-1]["max_drawdown"],
                win_rate=None,
                params={
                    k: results[-1][k]
                    for k in (
                        "baseline",
                        "theory",
                        "delta_sharpe",
                        "p_value",
                        "discovery_passed",
                        "holdout_delta",
                        "holdout_passed",
                        "promotion_eligible",
                    )
                }
                | {"cost_bps": cost_bps, "n_entries_discovery": len(disc), "alpha_effective": alpha_eff},
                db_path=db_path,
            )

    return {
        "universe_n": close.shape[1],
        "panel_start": pd.Timestamp(close.index[0]).strftime("%Y-%m-%d"),
        "panel_end": pd.Timestamp(close.index[-1]).strftime("%Y-%m-%d"),
        "cost_bps": cost_bps,
        "n_entries": len(entries),
        "n_discovery": len(disc),
        "n_holdout": len(hold),
        "split_idx": split,
        "n_test_rules": n_test,
        "alpha": alpha,
        "alpha_effective": alpha_eff,
        "rules": results,
        "promotion_eligible": [r["name"] for r in results if r["promotion_eligible"]],
    }


def run_exit_validation(
    cost_bps: float = 10.0,
    db_path: Optional[Path] = None,
    config: Optional[dict] = None,
    persist: bool = True,
) -> dict[str, Any]:
    """CLI 진입점: prices(DB) + usd_krw(macro) 로드 → exit search → (persist 시) 기록."""
    from nuri.quant.validation.strategy_walkforward import _load_fx_series

    fx = _load_fx_series(db_path)
    return run_exit_search(cost_bps=cost_bps, fx_series=fx, db_path=db_path, config=config, persist=persist)


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m nuri.quant.validation.exit_walkforward [--cost-bps 10] [--no-persist]"""
    import argparse
    import json as _json
    import sys

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(prog="exit-walkforward")
    parser.add_argument("--cost-bps", type=float, default=10.0, help="거래비용 (bps, 필수 가정)")
    parser.add_argument("--no-persist", action="store_true", help="backtests 기록 생략")
    args = parser.parse_args(argv)

    try:
        r = run_exit_validation(cost_bps=args.cost_bps, persist=not args.no_persist)
    except ValueError as exc:
        print(_json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    print(f"\n{'=' * 80}")
    print("  P4 Exit-Rule Walk-Forward (#713) — paired vs e0_ladder")
    print(
        f"  Universe {r['universe_n']} | {r['panel_start']}..{r['panel_end']} | cost {r['cost_bps']}bps"
        f" | entries {r['n_discovery']}d/{r['n_holdout']}h | Bonferroni {r['alpha']}/{r['n_test_rules']}"
        f" = {r['alpha_effective']:.4f}"
    )
    print(f"{'=' * 80}")
    print(f"  {'rule':<16}{'Sharpe':>8}{'ΔvsE0':>8}{'p':>8}{'null95':>8}{'maxDD':>8}{'holdoutΔ':>10}  verdict")
    for v in r["rules"]:
        verdict = "PROMOTE-ELIGIBLE" if v["promotion_eligible"] else ("baseline" if v["baseline"] else "FAIL")
        ds = f"{v['delta_sharpe']:>+8.3f}" if v["delta_sharpe"] is not None else f"{'—':>8}"
        pv = f"{v['p_value']:>8.3f}" if v["p_value"] is not None else f"{'—':>8}"
        np95 = f"{v['null_p95']:>+8.2f}" if v["null_p95"] is not None else f"{'—':>8}"
        hd = f"{v['holdout_delta']:>+10.3f}" if v["holdout_delta"] is not None else f"{'sealed':>10}"
        print(f"  {v['name']:<16}{v['sharpe']:>+8.3f}{ds}{pv}{np95}{v['max_drawdown']:>+8.2f}{hd}  {verdict}")
    print(f"\n  >>> promotion-eligible: {r['promotion_eligible'] or 'NONE — 현행 E0 ladder 유지가 데이터 기반 디폴트'}")
    print()
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())

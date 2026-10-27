"""확증 단계(E)에 필요한 날짜 수 — 파일럿 분산에서 (#1991).

E 는 확증 날짜 수를 파일럿(#1964)에서 잰 분산으로 정해야 한다. iid 공식은 여기서 틀린다.

- **일별 ΔIC 는 서로 기댄다** — 하루 코호트들이 5세션 보유 창과 같은 시장을 공유한다. 그래서 평균의 표준오차를
  이동 블록 부트스트랩(Künsch 1989)으로 재고 장기 표준편차 σ_LR = SE·√n 로 바꾼다.
- **블록 길이는 하나로 고르지 않는다** — 길이 b 의 블록은 lag h 공분산을 대략 (1 − h/b) 로 깎는다(Bartlett 가중,
  Künsch 1989). b = 보유 세션 수 H 면 겹친 보유 창의 lag 1…H−1 이 덜 잡혀 σ_LR 이 아래로 치우친다. 그래서
  b = H … min(n/2, 4H) 를 모두 재고 가장 큰 값을 쓴다(노이즈 중 최댓값이라 위로 치우치지만 덜 잡는 쪽보다 낫다).
- **파일럿 길이에서는 데이터만으로 의존을 못 잰다** — H = 5 이동합 모의(이론 σ_LR 0.1, 400 seed): 20일에서 블록
  최댓값 0.063 · Hansen–Hodrick(lag 4) 0.068, 유한 표본 참값 0.095. 표본 평균을 빼는 것 자체가 장기 분산을 깎는다.
  그래서 **겹침 모델** σ_LR = √(H · γ̂₀) 을 함께 낸다 — 보유 창이 H 세션 겹치면(ρ_h = 1 − h/H) 정확히 성립하고,
  주변 분산만 쓰므로 20일에서도 참값의 0.93배다. 계획 값은 **두 값 중 큰 쪽**이다: 겹침보다 긴 공통 시장 의존은
  블록 쪽이(긴 표본에서) 잡고, 짧은 표본의 하향 편향은 모델 쪽이 막는다. 의존이 없는 자료에는 모델이 √H 배 크게
  잡는다 — 날짜를 더 잡는 쪽이다. 어느 쪽이 정했는지 `sigma_source` 로 낸다.
- **보수적 상한이 아니다 — 가정이 있다** — 4H 세션을 넘는 강한 지속(예: AR(1) ρ = .95)은 어느 쪽도 못 잡아 날짜를
  덜 잡는다(Codex 리뷰: 1만 일에서 필요 날짜의 약 39%). 파일럿 길이로는 그런 의존을 잴 방법이 없으므로 고치지 않고
  가정으로 출력에 적는다(`assumption`). E 가 이 가정을 받아들일지 정한다.
- **정의되지 않는 날** — 공통 종목이 k 개 미만이거나 alpha 또는 어느 팔의 등급이 모두 같으면 Spearman IC 가 없다.
  건너뛰고 이유별로 센다. 그 비율로 달력 날짜 수도 낸다(E 가 덜 잡지 않게).
- **파일럿 20일의 분산은 시끄럽다** — 점 하나가 아니라 중첩 부트스트랩(바깥 블록 표본마다 σ_LR 을 다시 잰다)의
  백분위 범위로 날짜 수를 범위로 낸다. **보정된 95% 신뢰구간이 아니다** — 바깥 재표본의 블록 경계가 의존을 한 번 더
  깎아 범위가 아래로 치우칠 수 있다(공분산 구조에 달림). 그래서 `range` 라 부르고 `calibrated: false` 를 같이 낸다.
- **팔끼리는 같은 종목 위에서** — ΔIC_d = IC(팔1) − IC(팔2), 그날 두 팔 모두 실행 · 정산된 종목만. 팔마다 다른
  집합이면 차이가 정보가 아니라 범위를 잰다. 두 팔의 cutoff(=정산 창)가 다르면 거부한다.
- **정의가 섞이면 거부** — 한 팔에 `arm_hash` 가 둘 이상이거나 (팔, 날짜, 종목) 실행이 둘 이상이면 계산하지 않는다
  (#1990 의 분석 쪽 짝).
- **관측된 평균 ΔIC 는 내지 않는다** — 목표 효과 크기를 파일럿 효과에 맞춰 고르면 확증이 아니다. 분산만 쓴다.

원장은 읽기만(`readonly=True`), 기존 판독기와 같은 필터: 채점 · 늦지 않음 · 배치 ok · 정산 ok · 실험 태그.
출력은 집계만 — 종목별 등급 · 수익은 내지 않는다.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import NormalDist
from typing import Any, Optional

import numpy as np
from scipy.stats import rankdata

from nuri.core.db import query
from nuri.llm import local_client as lc
from nuri.llm.tradingagents.rating import RATING_REVIEW, PortfolioRating

SCORE = {
    PortfolioRating.BUY.value: 2,
    PortfolioRating.OVERWEIGHT.value: 1,
    PortfolioRating.HOLD.value: 0,
    PortfolioRating.UNDERWEIGHT.value: -1,
    PortfolioRating.SELL.value: -2,
    RATING_REVIEW: 0,  # 읽을 수 없는 판정은 중립으로 두되 따로 센다
}
MAX_BLOCK_FACTOR = 4  # 블록 상한 = 4 × 보유 세션 — 그 너머의 의존은 파일럿 길이로는 어차피 못 잰다
MIN_BOOT = 200  # 이보다 적은 반복의 표준편차 · 백분위는 숫자처럼 보이지만 재현되지 않는다
MIN_OUTER = 50
# ΔIC 는 [−4, 4] 의 값 — 표준편차가 이보다 작으면 의견 차이가 아니라 부동소수 오차다(언더플로 · 상쇄로 0 일이나
# 평행이동에 따라 다른 답이 나온다, Codex 리뷰). 계획할 분산이 없다고 거부한다.
MIN_SD = 1e-6


def ledger_rows(*, experiment: str, arms: tuple[str, str], db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """그 실험의 두 팔 실행 — 정산 전 · 누락 행도 가져와 센다(분모에서 조용히 빠지지 않게)."""
    return query(
        "SELECT r.cohort_date, r.arm, r.arm_hash, r.ticker, r.cutoff, r.rating, t.status AS ret_status, t.alpha "
        "FROM thesis_runs r JOIN thesis_batches b ON b.batch_id = r.batch_id AND b.status = 'ok' "
        "LEFT JOIN thesis_returns t ON t.ticker = r.ticker AND t.cutoff = r.cutoff "
        "WHERE r.scored = 1 AND r.late = 0 AND r.experiment = ? AND r.arm IN (?, ?) "
        "ORDER BY r.cohort_date, r.ticker, r.arm",
        (experiment, *arms),
        db_path=db_path,
        readonly=True,
    )


def spearman(x: Any, y: Any) -> float:
    """평균 순위의 Pearson 상관 — 동순위는 평균 순위(scipy `spearmanr` 와 같은 정의)."""
    return float(np.corrcoef(rankdata(x), rankdata(y))[0, 1])


def daily_delta(
    rows: list[dict[str, Any]], arms: tuple[str, str], *, min_tickers: int
) -> tuple[list[str], np.ndarray, dict[str, Any]]:
    """(정의된 날짜, 그날의 ΔIC, 집계) — 날짜순."""
    hashes: dict[str, set[str]] = defaultdict(set)
    seen: set[tuple[str, str, str]] = set()
    by_day: dict[str, dict[str, dict[str, dict[str, Any]]]] = defaultdict(lambda: defaultdict(dict))
    review: Counter[str] = Counter()
    for r in rows:
        key = (r["arm"], r["cohort_date"], r["ticker"])
        if key in seen:
            raise ValueError(f"more than one run for arm {key[0]} on {key[1]}")
        seen.add(key)
        if r["rating"] not in SCORE:
            raise ValueError(f"unknown rating {r['rating']!r}")
        hashes[r["arm"]].add(r["arm_hash"])
        review[r["arm"]] += r["rating"] == RATING_REVIEW
        by_day[r["cohort_date"]][r["ticker"]][r["arm"]] = r
    for a in arms:
        if len(hashes[a]) != 1:
            raise ValueError(f"arm {a} has {len(hashes[a])} definitions in this experiment; expected exactly one")
    undefined: Counter[str] = Counter()
    returns: Counter[str] = Counter()
    dates: list[str] = []
    deltas: list[float] = []
    for day in sorted(by_day):
        scores: dict[str, list[int]] = {a: [] for a in arms}
        alphas: list[float] = []
        for runs in by_day[day].values():
            if not all(a in runs for a in arms):
                continue
            if len({runs[a]["cutoff"] for a in arms}) != 1:
                # 정산은 (종목, cutoff) 단위 — 다르면 서로 다른 수익 창의 등급을 한 IC 에 섞는다
                raise ValueError(f"arms ran on different cutoffs on {day}")
            status = runs[arms[0]]["ret_status"]
            returns[status or "pending"] += 1
            if status != "ok" or runs[arms[0]]["alpha"] is None:
                continue
            if not math.isfinite(float(runs[arms[0]]["alpha"])):
                # 무한대도 순위는 매겨진다 — 손상된 정산이 정상 날로 들어가지 않게 거부한다 (Codex 리뷰)
                raise ValueError(f"a settled alpha on {day} is not finite")
            alphas.append(float(runs[arms[0]]["alpha"]))
            for a in arms:
                scores[a].append(SCORE[runs[a]["rating"]])
        # 이유는 각각 센다(한 날에 둘 이상일 수 있다). 정의되지 않은 날 수 자체는 `days − defined_days`.
        reasons = {
            "few_tickers": len(alphas) < min_tickers,
            "constant_alpha": len(set(alphas)) <= 1,
            "constant_rating": any(len(set(s)) <= 1 for s in scores.values()),
        }
        undefined.update(k for k, v in reasons.items() if v)
        if not any(reasons.values()):
            dates.append(day)
            deltas.append(spearman(scores[arms[0]], alphas) - spearman(scores[arms[1]], alphas))
    counts = {
        "days": len(by_day),
        "defined_days": len(dates),
        "undefined_reasons": dict(sorted(undefined.items())),
        "review_runs": {a: review[a] for a in arms},
        "paired_returns": dict(sorted(returns.items())),
    }
    return dates, np.asarray(deltas, dtype=float), counts


def block_indices(n: int, block: int, size: int, rng: np.random.Generator) -> np.ndarray:
    """이동 블록 부트스트랩 표본 `size` 개의 인덱스 (size, n) — 길이 block 의 연속 구간을 이어 붙여 n 에서 자른다."""
    starts = rng.integers(0, n - block + 1, size=(size, math.ceil(n / block)))
    return (starts[..., None] + np.arange(block)).reshape(size, -1)[:, :n]


def long_run_sd(x: np.ndarray, block: int, n_boot: int, rng: np.random.Generator) -> float:
    """σ_LR = 평균의 블록 부트스트랩 표준오차 × √n."""
    means = x[block_indices(len(x), block, n_boot, rng)].mean(axis=1)
    return float(means.std(ddof=1) * math.sqrt(len(x)))


def planning_sd(x: np.ndarray, holding: int, n_boot: int, rng: np.random.Generator) -> dict[str, Any]:
    """계획용 σ_LR — 블록 부트스트랩(블록 H … min(n/2, 4H) 중 최대)과 겹침 모델 √(H·γ̂₀) 중 큰 쪽."""
    top = min(len(x) // 2, MAX_BLOCK_FACTOR * holding)
    by_block = {b: long_run_sd(x, b, n_boot, rng) for b in range(holding, top + 1)}
    boot = max(by_block.values())
    overlap = float(math.sqrt(holding * np.var(x, ddof=1)))
    return {
        "sigma": max(boot, overlap),
        "source": "bootstrap" if boot > overlap else "overlap_model",
        "bootstrap": boot,
        "overlap_model": overlap,
        "by_block": by_block,
    }


def required_dates(
    deltas: np.ndarray,
    *,
    targets: list[float],
    alpha: float,
    power: float,
    holding: int,
    n_boot: int,
    n_outer: int,
    seed: int,
    level: float = 0.95,
) -> dict[str, Any]:
    """목표 ΔIC 마다 필요한 정의된 날짜 수 — 양측 검정, n = ⌈((z₁₋α/₂ + z_power)·σ/δ)²⌉, σ = `planning_sd`.

    범위는 바깥 블록 표본마다 같은 `planning_sd` 를 다시 잰 백분위다 — 보정된 신뢰구간이 아니다."""
    if holding < 1:
        raise ValueError("holding sessions must be at least 1")
    if n_boot < MIN_BOOT or n_outer < MIN_OUTER:
        raise ValueError(f"at least {MIN_BOOT} bootstrap and {MIN_OUTER} outer replicates are required")
    if not (0 < alpha < 1 and 0.5 <= power < 1 and 0 < level < 1):
        raise ValueError("alpha and level must lie in (0, 1) and power in [0.5, 1)")
    if not targets or not all(math.isfinite(t) and t > 0 for t in targets):
        raise ValueError("targets must be finite and positive")
    if np.ndim(deltas) != 1:
        raise ValueError("the daily differences must be one series")
    n = len(deltas)
    if n < 2 * holding:
        raise ValueError(f"{n} defined days; at least {2 * holding} are needed for {holding}-session holds")
    if not np.all(np.isfinite(deltas)) or float(np.std(deltas, ddof=1)) < MIN_SD:
        raise ValueError("the daily differences have no variance to plan from")
    rng = np.random.default_rng(seed)
    point = planning_sd(deltas, holding, n_boot, rng)
    b = max(point["by_block"], key=lambda k: point["by_block"][k])
    outer = [planning_sd(deltas[i], holding, n_boot, rng)["sigma"] for i in block_indices(n, b, n_outer, rng)]
    lo, hi = np.percentile(outer, [100 * (1 - level) / 2, 100 * (1 + level) / 2])
    # 점 추정이 범위 밖으로 나가지 않게 넓힌다(백분위만으로는 보장되지 않는다)
    lo, hi = min(float(lo), point["sigma"]), max(float(hi), point["sigma"])
    z = NormalDist().inv_cdf(1 - alpha / 2) + NormalDist().inv_cdf(power)

    def need(sd: float, d: float) -> int:
        return max(1, math.ceil((z * sd / d) ** 2))  # 바깥 재표본이 모두 같은 값이면 σ = 0 — 검정은 하루라도 필요

    return {
        "sigma_lr": point["sigma"],
        "sigma_source": point["source"],
        "sigma_bootstrap": point["bootstrap"],
        "sigma_overlap_model": point["overlap_model"],
        "sigma_bootstrap_by_block": {str(k): v for k, v in point["by_block"].items()},
        "sigma_lr_range": [lo, hi],
        "range_level": level,
        "range_calibrated": False,
        # 분산이 없는 바깥 재표본 수 — 많으면 파일럿이 너무 성겨 범위 하한이 뜻을 잃는다
        "degenerate_outer_replicates": sum(v == 0 for v in outer),
        "assumption": f"serial dependence beyond {MAX_BLOCK_FACTOR * holding} sessions is not captured",
        "required": {str(d): {"dates": need(point["sigma"], d), "range": [need(lo, d), need(hi, d)]} for d in targets},
    }


def analyze(
    *,
    experiment: str,
    arms: tuple[str, str],
    targets: list[float],
    alpha: float,
    power: float,
    holding: int,
    n_boot: int,
    n_outer: int,
    seed: int,
    min_tickers: int,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    rows = ledger_rows(experiment=experiment, arms=arms, db_path=db_path)
    _, deltas, counts = daily_delta(rows, arms, min_tickers=min_tickers)
    out = required_dates(
        deltas, targets=targets, alpha=alpha, power=power, holding=holding, n_boot=n_boot, n_outer=n_outer, seed=seed
    )
    rate = counts["defined_days"] / counts["days"]
    for r in out["required"].values():
        r["calendar_dates"] = math.ceil(r["dates"] / rate)
        r["calendar_range"] = [math.ceil(v / rate) for v in r["range"]]
    params = {
        "experiment": experiment,
        "arms": list(arms),
        "alpha": alpha,
        "power": power,
        "holding_sessions": holding,
        "n_boot": n_boot,
        "n_outer": n_outer,
        "seed": seed,
        "min_tickers": min_tickers,
    }
    return {"params": params, **counts, **out}


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Required confirmatory dates from pilot ΔIC variance (aggregates only).")
    p.add_argument("--experiment", required=True)
    p.add_argument("--arms", default="B,A", help="two arms: ΔIC = IC(first) − IC(second)")
    p.add_argument("--targets", default="0.02,0.05,0.1", help="comma-separated target ΔIC values")
    p.add_argument("--alpha", type=float, default=0.05)
    p.add_argument("--power", type=float, default=0.8)
    p.add_argument("--boot", type=int, default=2000)
    p.add_argument("--outer", type=int, default=200)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--min-tickers", type=int, default=5)
    p.add_argument("--db", type=Path, default=None)
    args = p.parse_args(argv)
    arms = tuple(args.arms.split(","))
    if len(arms) != 2 or arms[0] == arms[1]:
        p.error("--arms takes two different arms")
    try:
        out = analyze(
            experiment=args.experiment,
            arms=(arms[0], arms[1]),
            targets=[float(t) for t in args.targets.split(",")],
            alpha=args.alpha,
            power=args.power,
            # 보유 세션 수는 메모리 정산과 같은 값 — 바뀌면 계획도 따라온다
            holding=int(lc.load_config()["memory"]["holding_sessions"]),
            n_boot=args.boot,
            n_outer=args.outer,
            seed=args.seed,
            min_tickers=args.min_tickers,
            db_path=args.db,
        )
    except ValueError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

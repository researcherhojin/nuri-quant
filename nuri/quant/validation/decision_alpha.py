"""Decision-level alpha 판정 도구 — STRATEGY §3.11 사전 고정 기준의 구현 (#831).

3조건 통합 판정 리포트:
  1. mean 30d alpha > 0
  2. ticker-block placebo 순열 p < permutation_p_max (one-sided)
  3. median-decision-date 등분 2분할 모두 mean alpha > 0
+ missing-outcome 비율 공시 (missing_outcome_max_pct 초과 시 판정 무효).

판정 파라미터는 전부 `config/rules.yaml measurement_mode` (사전 고정, lock test
`tests/core/test_rules.py::TestMeasurementMode`) 에서 로드 — 하드코딩 금지.

순열 설계 (ticker_block_placebo, §3.11 표에 사전 고정):
  실 표본의 (ticker → emit 일자 집합) 블록 구조를 유지한 채, 블록의 ticker 만
  동일 시장 (US) eligible universe 에서 치환해 mean alpha null 분포를 생성한다.
  같은 ticker 의 반복 emit 은 null 에서도 같은 치환 ticker 를 공유하므로,
  중첩 관측창·동일일 배치·반복 종목의 의존 구조를 null 이 그대로 상속한다 —
  naive iid 순열은 이 클러스터링을 무시해 anti-conservative (§3.11 근거란).

가격/창 의미론은 ForwardOutcomeTracker 와 동일 (미러 — drift 시 판정 무효):
  entry = close(ticker, emit_date) [정확 일치],
  exit  = close_on_or_after(ticker, emit_date + window **calendar days**)
  (forward_outcome_tracker.py `_add_business_days` 는 이름과 달리 calendar-day
  덧셈이고 주말/휴장은 on_or_after 가 흡수 — 동일 규칙 적용).
  단, 실 표본의 observed alpha 는 재계산하지 않고 원장 `decision_outcomes.alpha`
  를 그대로 쓴다 (§3.11: 판정은 원장 쿼리만 인용).

Usage:
    python -m nuri.quant.validation.decision_alpha            # 진행 리포트 (JSON)
    python -m nuri.quant.validation.decision_alpha --seed 828 --n-perm 1000
"""

from __future__ import annotations

import argparse
import bisect
import json
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np

from nuri.core.db import query
from nuri.core.rules import RULES
from nuri.core.ticker_names import is_kr_ticker
from nuri.core.timezone import today_kst

# 순열 null 오염 방지 — 지수/선물 pseudo-ticker 는 universe 에서 제외.
# (#710 실측: KOSDAQ 이 .KS 필터를 빠져나가 degenerate fold 유발.
#  canonical 목록: config/walkforward_variants.yaml exclude_tickers)
PSEUDO_TICKERS = frozenset({"KOSDAQ", "KOSPI", "GC=F", "TESTAA"})

# 기본 순열 seed — 사전 고정 (reseed-shopping 방지). CLI --seed 로 명시 변경 시
# 리포트에 seed 가 그대로 찍혀 재현 경로가 남는다.
DEFAULT_SEED = 828


def _criteria() -> dict:
    """rules.yaml measurement_mode 블록 (사전 고정 판정 파라미터)."""
    mm = RULES.get("measurement_mode")
    if not mm:
        raise RuntimeError("config/rules.yaml 에 measurement_mode 블록 없음 (§3.11)")
    return mm


class PriceBook:
    """ticker 별 close 시계열 lazy 캐시 — 순열 1,000회의 가격 조회를 메모리에서.

    tracker 와 동일 SQL 의미론: 정확일 close / on-or-after 첫 close.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path
        self._series: dict[str, tuple[list[str], list[float]]] = {}

    def _load(self, ticker: str) -> tuple[list[str], list[float]]:
        if ticker not in self._series:
            rows = query(
                "SELECT date, close FROM prices WHERE ticker = ? AND close IS NOT NULL ORDER BY date",
                (ticker,),
                db_path=self._db_path,
            )
            dates = [r["date"] for r in rows]
            closes = [float(r["close"]) for r in rows]
            self._series[ticker] = (dates, closes)
        return self._series[ticker]

    def close(self, ticker: str, date_str: str) -> Optional[float]:
        dates, closes = self._load(ticker)
        i = bisect.bisect_left(dates, date_str)
        if i < len(dates) and dates[i] == date_str:
            return closes[i]
        return None

    def close_on_or_after(self, ticker: str, date_str: str) -> Optional[float]:
        dates, closes = self._load(ticker)
        i = bisect.bisect_left(dates, date_str)
        if i < len(dates):
            return closes[i]
        return None


@dataclass
class Sample:
    """판정 표본 (US BUY, primary window, alpha 확정분) + 결측 집계."""

    decisions: list[dict] = field(default_factory=list)  # {decision_id, ticker, emit_date, alpha}
    n_missing_closed: int = 0  # 창이 닫혔는데 alpha 미기록 (결측 편향 공시 대상)

    @property
    def n(self) -> int:
        return len(self.decisions)

    @property
    def missing_rate_pct(self) -> float:
        total = self.n + self.n_missing_closed
        return (self.n_missing_closed / total * 100.0) if total else 0.0


def fetch_sample(db_path: Optional[Path] = None, as_of: Optional[str] = None) -> Sample:
    """§3.11 표본 규약 구현 — declared_date~emit_cutoff 의 US BUY, distinct decision.

    결측 정의: 창 (emit + window calendar days) 이 as_of 이전에 닫혔는데
    primary window 의 alpha 가 원장에 없는 결정 (추적 실패/가격 결측).
    """
    mm = _criteria()
    window = int(mm["primary_window_days"])
    today = as_of or today_kst()

    rows = query(
        """
        SELECT r.id AS rec_id, r.ticker AS ticker, r.date AS emit_date, o.alpha AS alpha
        FROM recommendations r
        JOIN agent_decisions ad ON ad.decision_id = 'rec_' || r.id
        LEFT JOIN decision_outcomes o
               ON o.decision_id = 'rec_' || r.id AND o.observation_window = ?
        WHERE ad.action = 'BUY'
          AND r.date >= ? AND r.date <= ?
        ORDER BY r.date, r.id
        """,
        (window, mm["declared_date"], mm["emit_cutoff_date"]),
        db_path=db_path,
    )

    sample = Sample()
    for raw in rows:
        r = dict(raw)
        # §3.11 판정은 US-only 고정 — KR(.KS + .KQ) 은 별도 사전등록 전까지 진단 전용.
        # SQL `NOT LIKE '%.KS'` 는 .KQ 를 통과시켰다 (#925). 판별은 canonical helper 로만.
        if is_kr_ticker(r["ticker"]):
            continue
        if r["alpha"] is not None:
            sample.decisions.append(
                {
                    "decision_id": f"rec_{r['rec_id']}",
                    "ticker": r["ticker"],
                    "emit_date": r["emit_date"],
                    "alpha": float(r["alpha"]),
                }
            )
            continue
        # 창이 닫혔는데 미기록 → 결측 (lookahead 미도래분은 결측 아님)
        target = (date.fromisoformat(r["emit_date"]) + timedelta(days=window)).isoformat()
        if target <= today:
            sample.n_missing_closed += 1
    return sample


def _blocks(decisions: list[dict]) -> dict[str, list[str]]:
    """ticker → emit 일자 리스트 (실 표본의 반복 구조)."""
    blocks: dict[str, list[str]] = {}
    for d in decisions:
        blocks.setdefault(d["ticker"], []).append(d["emit_date"])
    return blocks


def _placebo_alpha(book: PriceBook, ticker: str, emit_date: str, window: int, benchmark: str) -> Optional[float]:
    """치환 ticker 의 (emit, window) alpha — tracker 공식 미러 (BUY 전용)."""
    entry = book.close(ticker, emit_date)
    target = (date.fromisoformat(emit_date) + timedelta(days=window)).isoformat()
    exit_p = book.close_on_or_after(ticker, target)
    b_entry = book.close(benchmark, emit_date)
    b_exit = book.close_on_or_after(benchmark, target)
    if None in (entry, exit_p, b_entry, b_exit) or entry <= 0 or b_entry <= 0:
        return None
    return (exit_p - entry) / entry - (b_exit - b_entry) / b_entry


def _eligible_substitutes(
    book: PriceBook,
    blocks: dict[str, list[str]],
    window: int,
    benchmark: str,
    db_path: Optional[Path] = None,
) -> dict[str, list[str]]:
    """블록별 치환 후보 — 해당 블록의 모든 emit 일자에서 placebo alpha 계산 가능한
    US ticker (원 ticker·benchmark·pseudo 제외). 결정론 보장 위해 정렬 유지."""
    rows = query(
        "SELECT DISTINCT ticker FROM prices ORDER BY ticker",
        db_path=db_path,
    )
    universe = [dict(r)["ticker"] for r in rows]
    # 치환 universe 도 표본과 같은 시장이어야 null 이 유효 — KR(.KS + .KQ) 제외 (#925).
    universe = [t for t in universe if not is_kr_ticker(t) and t not in PSEUDO_TICKERS and t != benchmark]

    eligible: dict[str, list[str]] = {}
    for ticker, dates in blocks.items():
        cands = []
        for t in universe:
            if t == ticker:
                continue
            if all(_placebo_alpha(book, t, d, window, benchmark) is not None for d in dates):
                cands.append(t)
        eligible[ticker] = cands
    return eligible


@dataclass
class PermutationResult:
    p_value: float
    n_permutations: int
    observed_mean: float
    null_means: list[float]
    seed: int
    skipped_blocks: list[str]  # 치환 후보 없어 null 에서 실측 alpha 유지된 블록 (공시)


def ticker_block_placebo(
    sample: Sample,
    n_perm: int,
    seed: int,
    db_path: Optional[Path] = None,
) -> PermutationResult:
    """§3.11 사전 고정 순열 — one-sided p = (1 + #{null ≥ obs}) / (N + 1)."""
    mm = _criteria()
    window = int(mm["primary_window_days"])
    benchmark = str(mm["benchmark"])

    observed = float(np.mean([d["alpha"] for d in sample.decisions]))
    blocks = _blocks(sample.decisions)
    book = PriceBook(db_path=db_path)
    eligible = _eligible_substitutes(book, blocks, window, benchmark, db_path=db_path)
    skipped = sorted([t for t, c in eligible.items() if not c])

    rng = np.random.default_rng(seed)
    tickers = sorted(blocks.keys())  # 결정론 — dict 순회 아닌 정렬 순서
    null_means: list[float] = []
    for _ in range(n_perm):
        total, count = 0.0, 0
        for t in tickers:
            dates = blocks[t]
            cands = eligible[t]
            if not cands:
                # 치환 불가 블록 — 실측 alpha 유지 (null 을 실측 쪽으로 끌어
                # p 를 보수적으로 만든다; skipped_blocks 로 공시)
                for d in sample.decisions:
                    if d["ticker"] == t:
                        total += d["alpha"]
                        count += 1
                continue
            sub = cands[int(rng.integers(len(cands)))]
            for dt in dates:
                a = _placebo_alpha(book, sub, dt, window, benchmark)
                total += a  # eligible 검증으로 None 불가
                count += 1
        null_means.append(total / count)

    ge = sum(1 for m in null_means if m >= observed)
    p = (1 + ge) / (n_perm + 1)
    return PermutationResult(
        p_value=p,
        n_permutations=n_perm,
        observed_mean=observed,
        null_means=null_means,
        seed=seed,
        skipped_blocks=skipped,
    )


def median_split_means(sample: Sample) -> dict:
    """median-decision-date 등분 2분할 (n 균형 보장 — §3.11)."""
    ordered = sorted(sample.decisions, key=lambda d: (d["emit_date"], d["decision_id"]))
    half = len(ordered) // 2
    h1, h2 = ordered[:half], ordered[half:]
    return {
        "h1_n": len(h1),
        "h1_mean": float(np.mean([d["alpha"] for d in h1])) if h1 else None,
        "h2_n": len(h2),
        "h2_mean": float(np.mean([d["alpha"] for d in h2])) if h2 else None,
    }


def adjudicate(
    db_path: Optional[Path] = None,
    n_perm: Optional[int] = None,
    seed: int = DEFAULT_SEED,
    as_of: Optional[str] = None,
) -> dict:
    """3조건 통합 판정 리포트 (JSON-직렬화 가능 dict).

    evaluation_date 이전 실행은 verdict='PROGRESS_REPORT' — §3.11 조기 승격 금지.
    """
    mm = _criteria()
    today = as_of or today_kst()
    n_perm = int(n_perm if n_perm is not None else mm["permutation_n"])

    sample = fetch_sample(db_path=db_path, as_of=today)
    report: dict = {
        "as_of": today,
        "criteria_source": "config/rules.yaml measurement_mode (§3.11 사전 고정)",
        "window_days": int(mm["primary_window_days"]),
        "benchmark": mm["benchmark"],
        "n": sample.n,
        "min_n_required": int(mm["min_n_us_buy_decisions"]),
        "missing_rate_pct": round(sample.missing_rate_pct, 1),
        "missing_max_pct": int(mm["missing_outcome_max_pct"]),
        "pre_evaluation": today < str(mm["evaluation_date"]),
        "evaluation_date": mm["evaluation_date"],
    }

    if sample.n == 0:
        report.update({"verdict": "NO_SAMPLE", "reason": "표본 0건 (declared_date 이후 확정 alpha 없음)"})
        return report

    perm = ticker_block_placebo(sample, n_perm=n_perm, seed=seed, db_path=db_path)
    halves = median_split_means(sample)
    cond = {
        "mean_alpha_positive": perm.observed_mean > 0,
        "permutation_significant": perm.p_value < float(mm["permutation_p_max"]),
        "both_halves_positive": bool(
            halves["h1_mean"] is not None
            and halves["h2_mean"] is not None
            and halves["h1_mean"] > 0
            and halves["h2_mean"] > 0
        ),
    }
    report.update(
        {
            "mean_alpha": round(perm.observed_mean, 6),
            "p_value": round(perm.p_value, 6),
            "p_max": float(mm["permutation_p_max"]),
            "permutation": {
                "scheme": mm["permutation_scheme"],
                "n": perm.n_permutations,
                "seed": perm.seed,
                "one_sided": True,
                "skipped_blocks": perm.skipped_blocks,
            },
            "halves": halves,
            "conditions": cond,
        }
    )

    # 판정 우선순위: 결측 무효 > 표본 미달 > 3조건
    if sample.missing_rate_pct > float(mm["missing_outcome_max_pct"]):
        verdict = "INVALID_MISSING"  # 판정 무효 — 측정 연장 (§3.11 오염 방지 행)
    elif sample.n < int(mm["min_n_us_buy_decisions"]):
        verdict = "INSUFFICIENT_N"
    elif all(cond.values()):
        verdict = "CRITERIA_MET"
    else:
        verdict = "CRITERIA_NOT_MET"
    # 조기 승격 금지 — 판정일 이전엔 어떤 결과도 progress report 로만.
    report["verdict"] = "PROGRESS_REPORT" if report["pre_evaluation"] else verdict
    report["criteria_verdict_if_final"] = verdict
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="§3.11 decision-level alpha 판정 리포트 (#831)")
    parser.add_argument("--db", type=Path, default=None, help="DB 경로 (기본: production 원장 규약 — §3.11)")
    parser.add_argument("--n-perm", type=int, default=None, help="순열 수 override (기본: config permutation_n)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"순열 seed (기본 {DEFAULT_SEED}, 사전 고정)")
    args = parser.parse_args(argv)

    report = adjudicate(db_path=args.db, n_perm=args.n_perm, seed=args.seed)
    report.pop("null_means", None)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

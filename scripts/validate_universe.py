"""Universe + agent data coverage gate — CLI wrapper.

#272 Phase 2c. Spec: docs/SPEC_phase2c_validate.md.

Exit codes:
- 0: 모든 check PASS
- 1: ≥1 check FAIL

사용법:
    python scripts/validate_universe.py                  # 전체 (network fetch)
    python scripts/validate_universe.py --no-fetch       # universe ↔ upstream skip (DB만)
    python scripts/validate_universe.py --format json    # CI-parseable
"""

from __future__ import annotations

import argparse
import json
import sys

from nuri.core.coverage import (
    UNIVERSE_THRESHOLD,
    CoverageCheck,
    _load_universe,
    compute_all_data_coverage,
    compute_universe_match,
    summary,
)


def fetch_upstream_universes() -> tuple[set[str], set[str]]:
    """Wikipedia + FDR에서 upstream universe fetch.

    Returns:
        (us_sp500_set, kr_kospi200_set)
    """
    from nuri.collectors.universe_sync import _fetch_kospi200, _fetch_sp500_from_wikipedia

    us: set[str] = set()
    kr: set[str] = set()
    try:
        us = set(_fetch_sp500_from_wikipedia())
    except Exception as e:
        print(f"⚠️  S&P 500 fetch 실패: {e}", file=sys.stderr)

    try:
        kr = set(_fetch_kospi200())
    except Exception as e:
        print(f"⚠️  KOSPI 200 fetch 실패: {e}", file=sys.stderr)

    return us, kr


def print_table(checks: list[CoverageCheck]) -> None:
    """결과 표 출력."""
    print()
    print("=" * 75)
    print("  Universe + Agent Coverage Validation (#272 Phase 2c)")
    print("=" * 75)
    print()
    print(f"  {'Check':30} {'Actual':>10} {'Threshold':>12} {'Status':>10}")
    print(f"  {'-' * 70}")
    for c in checks:
        flag = "✅ PASS" if c.passed else "🔴 FAIL"
        actual_str = f"{c.actual_pct:.0%}"
        thresh_str = f"≥{c.threshold:.0%}"
        print(f"  {c.name:30} {actual_str:>10} {thresh_str:>12} {flag:>10}")

    summ = summary(checks)
    print()
    print(f"  Result: {summ['pass']}/{len(checks)} PASS → exit {summ['exit_code']}")
    if summ["fail"] > 0:
        print(f"  Failed checks ({summ['fail']}):")
        for c in checks:
            if not c.passed:
                print(f"    • {c.name}: {c.detail}")
    print()


def run_validation(*, fetch: bool = True) -> tuple[list[CoverageCheck], int]:
    """전체 validation 실행.

    Returns:
        (checks_list, exit_code)
    """
    universe = _load_universe()
    checks: list[CoverageCheck] = []

    # 1. universe.yaml ↔ upstream (network)
    if fetch:
        us_upstream, kr_upstream = fetch_upstream_universes()
        if us_upstream:
            checks.append(
                compute_universe_match("us_sp500", us_upstream, universe, market="us", threshold=UNIVERSE_THRESHOLD)
            )
        if kr_upstream:
            checks.append(
                compute_universe_match("kr_kospi200", kr_upstream, universe, market="kr", threshold=UNIVERSE_THRESHOLD)
            )

    # 2. Data tables coverage
    checks.extend(compute_all_data_coverage(universe=universe))

    summ = summary(checks)
    return checks, summ["exit_code"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Nuri-Quant Universe + Coverage Validation Gate")
    parser.add_argument("--no-fetch", action="store_true", help="upstream fetch 건너뜀 (DB만 검사)")
    parser.add_argument("--format", choices=["table", "json"], default="table", help="출력 형식")
    args = parser.parse_args()

    checks, exit_code = run_validation(fetch=not args.no_fetch)

    if args.format == "json":
        print(json.dumps(summary(checks), indent=2, ensure_ascii=False))
    else:
        print_table(checks)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())

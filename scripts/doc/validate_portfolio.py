#!/usr/bin/env python3
"""scripts/validate_portfolio.py — verify every portfolio ticker is alive.

#131의 회귀 방지: `config/portfolio.yaml`에 상장폐지/오타 ticker가 들어가도
파이프라인은 아무 경고 없이 매일 yfinance 404 로그만 반복 출력. 이 스크립트는
사용자가 portfolio를 수정한 직후 (또는 `make setup` 직후) 수동으로 한 번
돌려서, 죽어 있는 ticker를 콘솔에 명확히 보여준다.

판정 기준
---------
yfinance.download(ticker, period="5d") 결과가 비어 있으면 invalid 후보로 분류.
주말/공휴일/네트워크 일시 장애도 같은 결과를 낼 수 있으므로 결과는
"의심"으로 표시 — 사용자가 ticker 코드를 직접 확인 후 yaml에서 제거한다.

Exit code
---------
- 0: 모든 ticker가 데이터 있음
- 1: 1개 이상 invalid 후보 → 사용자 조치 필요

사용법
------
    python scripts/validate_portfolio.py
    python scripts/validate_portfolio.py --config config/portfolio.example.yaml
    python scripts/validate_portfolio.py --quiet      # invalid만 출력
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from scripts.ops.import_portfolio import load_holdings_by_account

ROOT = Path(__file__).parent.parent
DEFAULT_CONFIG = ROOT / "config" / "portfolio.yaml"

GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[0;33m"
CYAN = "\033[0;36m"
DIM = "\033[2m"
NC = "\033[0m"


@dataclass
class TickerCheckResult:
    ticker: str
    account: str
    is_valid: bool
    rows: int  # 0 if invalid, else number of price rows fetched
    error: str | None = None


def check_ticker(ticker: str) -> tuple[bool, int, str | None]:
    """Return (is_valid, num_rows, error_msg)."""
    try:
        import yfinance as yf
    except ImportError:
        return False, 0, "yfinance not installed"

    try:
        df = yf.download(
            ticker,
            period="5d",
            progress=False,
            auto_adjust=False,
            threads=False,
        )
        rows = 0 if df is None else len(df)
        return rows > 0, rows, None
    except Exception as e:  # noqa: BLE001 — 사용자에게 메시지로 보여주기
        return False, 0, f"{type(e).__name__}: {e}"


def validate_portfolio(config_path: Path) -> list[TickerCheckResult]:
    """Load portfolio yaml and check every ticker."""
    by_account = load_holdings_by_account(config_path)

    results: list[TickerCheckResult] = []
    for account, records in by_account.items():
        for record in records:
            ticker = record["ticker"]
            is_valid, rows, error = check_ticker(ticker)
            results.append(
                TickerCheckResult(
                    ticker=ticker,
                    account=account,
                    is_valid=is_valid,
                    rows=rows,
                    error=error,
                )
            )
    return results


def print_report(results: list[TickerCheckResult], *, quiet: bool = False) -> None:
    invalid = [r for r in results if not r.is_valid]
    valid = [r for r in results if r.is_valid]

    if not quiet:
        print(f"{CYAN}=== Nuri-Quant Portfolio Validation ==={NC}")
        print(f"  Checked: {len(results)} tickers across "
              f"{len({r.account for r in results})} accounts")
        print()

        if valid:
            print(f"{GREEN}✓ Valid ({len(valid)}){NC}")
            for r in valid:
                print(f"  {DIM}{r.account:20s} {r.ticker:15s} "
                      f"{r.rows} rows{NC}")
            print()

    if invalid:
        print(f"{RED}✗ Invalid / suspect ({len(invalid)}){NC}")
        for r in invalid:
            tail = r.error or "no recent data — possibly delisted, mistyped, or non-trading day"
            print(f"  {YELLOW}{r.account:20s} {r.ticker:15s}{NC}  → {tail}")
        print()
        print(f"{YELLOW}Action: verify each ticker manually and remove from "
              f"config/portfolio.yaml if delisted.{NC}")
    elif not quiet:
        print(f"{GREEN}All tickers valid.{NC}")


def main() -> int:
    doc = __doc__ or ""
    parser = argparse.ArgumentParser(description=doc.split("\n")[0])
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Portfolio yaml path (default: config/portfolio.yaml)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print invalid tickers",
    )
    args = parser.parse_args()

    if not args.config.exists():
        print(f"{RED}Portfolio file not found: {args.config}{NC}", file=sys.stderr)
        return 2

    results = validate_portfolio(args.config)
    print_report(results, quiet=args.quiet)

    invalid_count = sum(1 for r in results if not r.is_valid)
    return 1 if invalid_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())

"""Universe + agent data coverage 빠른 확인 — Phase 2c gate 전 sanity check.

사용법:
    .venv/bin/python scripts/check_universe_coverage.py
    또는
    make check-coverage  (Makefile 추가 시)
"""

from __future__ import annotations

from pathlib import Path

import yaml

from nuri.core.coverage import US_ONLY_TABLES
from nuri.core.db import query


def main() -> None:
    # 1. universe.yaml 로드
    path = Path("config/universe.yaml")
    if not path.exists():
        print("❌ config/universe.yaml 없음")
        return

    with path.open() as f:
        u = yaml.safe_load(f) or {}

    us_uni = set((u.get("us_core") or {}).get("tickers") or [])
    us_uni |= set((u.get("us_sp500_extended") or {}).get("tickers") or [])
    kr_uni = set((u.get("kr_kospi200") or {}).get("tickers") or [])

    print(f"\n{'=' * 75}")
    print(f"  Universe Coverage 확인 (US={len(us_uni)}, KR={len(kr_uni)})")
    print(f"{'=' * 75}\n")

    # 2. raw count
    print("[1/2] DB 테이블별 raw count")
    print(f"  {'Table':25} {'Tickers':>8} {'Latest date':>15} {'Rows':>10}")
    print(f"  {'-' * 65}")
    # 테이블별 date 컬럼명 (mismatch 방지)
    DATE_COLUMNS = {
        "prices": "date",
        "fundamentals": "date",
        "analyst_ratings": "date",
        "insider_trades": "date",
        "earnings_surprises": "quarter",  # date 아님
        "superinvestors": "filing_date",  # date 아님
        "estimates": "date",
    }
    for table in DATE_COLUMNS:
        try:
            date_col = DATE_COLUMNS[table]
            r = query(f"SELECT COUNT(DISTINCT ticker) AS c, MAX({date_col}) AS latest, COUNT(*) AS n FROM {table}")[0]
            print(f"  {table:25} {r['c']:>8} {(r['latest'] or 'N/A'):>15} {r['n']:>10}")
        except Exception as e:
            print(f"  {table:25} ⚠️  err: {str(e)[:40]}")

    # 3. universe coverage %
    print("\n[2/2] Universe 대비 coverage (Phase 2c spec §2.2)")
    print(f"  {'Source':22} {'US match':>15} {'KR match':>15} {'Threshold':>12} {'Status':>8}")
    print(f"  {'-' * 75}")

    thresholds = {
        "prices": 0.95,
        "fundamentals": 0.80,
        "analyst_ratings": 0.70,
        "insider_trades": 0.50,
        "superinvestors": 0.80,
    }

    for table, threshold in thresholds.items():
        try:
            rows = query(f"SELECT DISTINCT ticker FROM {table}")
            tickers_db = {r["ticker"] for r in rows}
            us_match = len(tickers_db & us_uni)
            us_pct = us_match / max(len(us_uni), 1)
            # status: US 기준 (대부분 데이터가 US 위주)
            flag = "✅ PASS" if us_pct >= threshold else "🔴 FAIL"
            us_str = f"{us_match}/{len(us_uni)} ({us_pct:.0%})"
            # KR 표시: 데이터 소스가 KR 미지원이면 "n/a (소스 미제공)" — 0%로 표시하면
            # 수집 실패처럼 보임. 실제로는 yfinance .KS / SEC EDGAR 한계.
            if table in US_ONLY_TABLES:
                kr_str = "n/a (US-only)"
            else:
                kr_match = len(tickers_db & kr_uni)
                kr_pct = kr_match / max(len(kr_uni), 1)
                kr_str = f"{kr_match}/{len(kr_uni)} ({kr_pct:.0%})"
            print(f"  {table:22} {us_str:>15} {kr_str:>15} {f'≥{threshold:.0%}':>12} {flag:>8}")
        except Exception as e:
            print(f"  {table:22} ⚠️  err: {str(e)[:50]}")

    print()
    print("  주: KR 'n/a (US-only)' = 데이터 소스(yfinance .KS / SEC EDGAR)가")
    print("      KR 종목을 지원하지 않음. 수집 실패가 아닌 소스 한계.")
    print()


if __name__ == "__main__":
    main()

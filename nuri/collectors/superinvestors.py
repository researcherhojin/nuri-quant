"""
슈퍼투자자 포트폴리오 수집기 — SEC EDGAR 13F 기반.

edgartools를 사용하여 SEC EDGAR에서 직접 13F 공시를 파싱.
API 키 불필요. 분기별 갱신.

사용법:
    python -m nuri.collectors.superinvestors
"""
import logging
from datetime import datetime
from typing import Any

import pandas as pd

from nuri.collectors.base import BaseCollector
from nuri.db import get_db, query

logger = logging.getLogger(__name__)

# 추적 대상 슈퍼투자자 (이름, SEC CIK)
SUPERINVESTORS = {
    "Warren Buffett": "0001067983",      # Berkshire Hathaway
    "Bill Gates": "0001166559",           # Bill & Melinda Gates Foundation
    "Ray Dalio": "0001350694",            # Bridgewater Associates
    "Bill Ackman": "0001336528",          # Pershing Square
    "David Tepper": "0001656456",         # Appaloosa Management
}

# edgartools User-Agent (SEC 정책 준수)
EDGAR_IDENTITY = "Nuri-Quant research@nuri-quant.dev"


class SuperinvestorCollector(BaseCollector):
    """SEC EDGAR 13F로 슈퍼투자자 포트폴리오 수집."""

    def __init__(self):
        super().__init__("superinvestors")

    def collect(self, **kwargs) -> list[dict]:
        """전체 슈퍼투자자의 최신 13F 수집."""
        from edgar import Company, set_identity
        set_identity(EDGAR_IDENTITY)

        results = []

        for investor_name, cik in SUPERINVESTORS.items():
            try:
                self.logger.info(f"{investor_name} ({cik}) 13F 수집 중...")
                company = Company(cik)
                filings = company.get_filings(form="13F-HR")

                if not filings or len(filings) == 0:
                    self.logger.warning(f"{investor_name}: 13F 공시 없음")
                    continue

                latest = filings[0]
                filing_date = str(latest.filing_date)
                filing_obj = latest.obj()
                infotable = filing_obj.infotable

                if infotable is None or infotable.empty:
                    self.logger.warning(f"{investor_name}: 보유종목 데이터 없음")
                    continue

                # 티커별 합산 (같은 종목이 여러 줄로 나옴)
                grouped = infotable.groupby("Ticker").agg({
                    "Value": "sum",
                    "SharesPrnAmount": "sum",
                    "Issuer": "first",
                }).reset_index()

                total_value = grouped["Value"].sum()
                if total_value == 0:
                    continue

                for _, row in grouped.iterrows():
                    ticker = row["Ticker"]
                    if not ticker or pd.isna(ticker):
                        continue

                    pct = row["Value"] / total_value * 100

                    results.append({
                        "investor": investor_name,
                        "filing_date": filing_date,
                        "ticker": ticker,
                        "shares": float(row["SharesPrnAmount"]),
                        "market_value": float(row["Value"]),
                        "portfolio_pct": round(pct, 4),
                        "issuer_name": row["Issuer"],
                    })

                self.logger.info(
                    f"{investor_name}: {len(grouped)}종목, "
                    f"공시일 {filing_date}, 총 ${total_value:,.0f}"
                )

            except Exception as e:
                self.logger.error(f"{investor_name}: 수집 실패 — {e}")
                continue

        return results

    def save(self, data: Any) -> int:
        """슈퍼투자자 데이터 DB 저장."""
        if not data:
            return 0
        return _upsert_superinvestors(data)


def _upsert_superinvestors(records: list[dict]) -> int:
    """superinvestors 테이블에 upsert."""
    if not records:
        return 0
    with get_db() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO superinvestors
               (investor, filing_date, ticker, shares, market_value,
                portfolio_pct, issuer_name)
               VALUES (:investor, :filing_date, :ticker, :shares, :market_value,
                       :portfolio_pct, :issuer_name)""",
            records,
        )
        return len(records)


def print_summary():
    """슈퍼투자자 보유 현황 출력."""
    investors = query(
        "SELECT DISTINCT investor FROM superinvestors ORDER BY investor"
    )
    if not investors:
        print("슈퍼투자자 데이터가 없습니다.")
        return

    # 내 보유종목
    my_tickers = set(r["ticker"] for r in query("SELECT DISTINCT ticker FROM portfolio"))

    print(f"\n{'=' * 70}")
    print(f"  슈퍼투자자 포트폴리오 (SEC 13F)")
    print(f"{'=' * 70}")

    for inv in investors:
        name = inv["investor"]
        rows = query(
            """SELECT ticker, issuer_name, portfolio_pct, market_value, filing_date
               FROM superinvestors
               WHERE investor = ?
               ORDER BY portfolio_pct DESC LIMIT 10""",
            (name,),
        )
        if not rows:
            continue

        filing_date = rows[0]["filing_date"]
        total = sum(r["market_value"] for r in query(
            "SELECT market_value FROM superinvestors WHERE investor = ?", (name,)
        ))

        print(f"\n  {name} (공시일: {filing_date}, 총 ${total:,.0f})")
        print(f"  {'Ticker':<10} {'종목명':<25} {'비중%':>8} {'내보유':>6}")
        print(f"  {'-' * 52}")

        for r in rows:
            mine = " *" if r["ticker"] in my_tickers else ""
            print(f"  {r['ticker']:<10} {r['issuer_name'][:24]:<25} "
                  f"{r['portfolio_pct']:>7.1f}%{mine}")

    # 내 보유종목 중 슈퍼투자자도 보유한 종목
    overlap = query(
        """SELECT s.ticker, GROUP_CONCAT(DISTINCT s.investor) as investors
           FROM superinvestors s
           WHERE s.ticker IN (SELECT DISTINCT ticker FROM portfolio)
           GROUP BY s.ticker
           ORDER BY s.ticker"""
    )
    if overlap:
        print(f"\n  {'=' * 50}")
        print(f"  내 보유종목 중 슈퍼투자자도 보유:")
        for r in overlap:
            print(f"    {r['ticker']}: {r['investors']}")

    print()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    collector = SuperinvestorCollector()
    collector.run()
    print_summary()

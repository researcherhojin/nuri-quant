"""
Wall Street 데이터 수집기 — 애널리스트 등급 + 실적 + 내부자 매매.

yfinance에서 직접 수집. API 키 불필요.

사용법:
    python -m nuri.collectors.wallstreet
"""

import logging
from typing import Any

import pandas as pd

from nuri.collectors.base import BaseCollector
from nuri.core.db import get_db, get_tickers

logger = logging.getLogger(__name__)


class WallStreetCollector(BaseCollector):
    """Wall Street 데이터 수집 (yfinance)."""

    def __init__(self):
        super().__init__("wallstreet")

    def collect(self, source: str = "portfolio", **kwargs) -> dict:
        """Wall Street 데이터 수집 (#272 Phase 2b: source 파라미터 지원).

        Args:
            source: 'portfolio' (default, 기존 동작 + 하드코딩 14개 extra) |
                    'universe' (config/universe.yaml 전체) |
                    'all' (portfolio ∪ universe)
        """
        import yfinance as yf

        if source == "portfolio":
            tickers = get_tickers()
            # 기존 하드코딩 extra — backwards compat
            extra = [
                "AAPL",
                "MSFT",
                "GOOG",
                "AMZN",
                "NVDA",
                "META",
                "NFLX",
                "JPM",
                "V",
                "MA",
                "UNH",
                "BA",
                "CRM",
                "ADBE",
            ]
            all_tickers = list(set(tickers + extra))
        else:
            # universe / all: _get_tickers로 위임
            all_tickers = self._get_tickers(source=source)

        ratings = []
        earnings = []
        insiders = []
        short_data = []

        for ticker in all_tickers:
            try:
                t = yf.Ticker(ticker)

                # 0. Short Interest (공매도 비율)
                try:
                    info = t.info or {}
                    short_pct = info.get("shortPercentOfFloat")
                    short_ratio = info.get("shortRatio")  # days to cover
                    if short_pct is not None:
                        short_data.append(
                            {
                                "ticker": ticker,
                                "short_pct_float": round(float(short_pct) * 100, 2),
                                "days_to_cover": float(short_ratio) if short_ratio else None,
                            }
                        )
                except Exception:
                    pass

                # 1. Analyst Ratings (최근 20건)
                ud = t.upgrades_downgrades
                if ud is not None and not ud.empty:
                    for idx, row in ud.head(20).iterrows():
                        date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
                        ratings.append(
                            {
                                "ticker": ticker,
                                "date": date_str,
                                "firm": row.get("Firm", ""),
                                "to_grade": row.get("ToGrade", ""),
                                "from_grade": row.get("FromGrade", ""),
                                "action": row.get("Action", ""),
                                "target_price": float(row["currentPriceTarget"])
                                if pd.notna(row.get("currentPriceTarget"))
                                else None,
                            }
                        )

                # 2. Earnings Surprise
                eh = t.earnings_history
                if eh is not None and not eh.empty:
                    for idx, row in eh.iterrows():
                        quarter = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
                        earnings.append(
                            {
                                "ticker": ticker,
                                "quarter": quarter,
                                "eps_actual": float(row["epsActual"]) if pd.notna(row.get("epsActual")) else None,
                                "eps_estimate": float(row["epsEstimate"]) if pd.notna(row.get("epsEstimate")) else None,
                                "surprise_pct": float(row["surprisePercent"])
                                if pd.notna(row.get("surprisePercent"))
                                else None,
                            }
                        )

                # 3. Insider Trades (최근 20건)
                ins = t.insider_transactions
                if ins is not None and not ins.empty:
                    for _, row in ins.head(20).iterrows():
                        date_str = str(row.get("Start Date", ""))[:10]
                        text = str(row.get("Text", ""))
                        tx_type = (
                            "sale" if "sale" in text.lower() else "purchase" if "purchase" in text.lower() else "other"
                        )
                        insiders.append(
                            {
                                "ticker": ticker,
                                "date": date_str,
                                "insider_name": row.get("Insider", ""),
                                "position": row.get("Position", ""),
                                "transaction_type": tx_type,
                                "shares": float(row["Shares"]) if pd.notna(row.get("Shares")) else None,
                                "value": float(row["Value"]) if pd.notna(row.get("Value")) else None,
                            }
                        )

                self.logger.info(
                    f"  {ticker}: {len([r for r in ratings if r['ticker'] == ticker])}ratings, "
                    f"{len([e for e in earnings if e['ticker'] == ticker])}earnings, "
                    f"{len([i for i in insiders if i['ticker'] == ticker])}insider"
                )

            except Exception as e:
                self.logger.debug(f"{ticker}: {e}")
                continue

        if short_data:
            self.logger.info(f"  Short interest: {len(short_data)}종목 수집")

        return {"ratings": ratings, "earnings": earnings, "insiders": insiders, "short_interest": short_data}

    def save(self, data: Any) -> int:
        count = 0
        if data.get("ratings"):
            count += _upsert_ratings(data["ratings"])
        if data.get("earnings"):
            count += _upsert_earnings(data["earnings"])
        if data.get("insiders"):
            count += _upsert_insiders(data["insiders"])
        if data.get("short_interest"):
            count += _save_short_interest(data["short_interest"])
        return count


def _upsert_ratings(records, db_path=None):
    if not records:
        return 0
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO analyst_ratings (ticker, date, firm, to_grade, from_grade, action, target_price) "
            "VALUES (:ticker, :date, :firm, :to_grade, :from_grade, :action, :target_price)",
            records,
        )
        return len(records)


def _upsert_earnings(records, db_path=None):
    if not records:
        return 0
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO earnings_surprises (ticker, quarter, eps_actual, eps_estimate, surprise_pct) "
            "VALUES (:ticker, :quarter, :eps_actual, :eps_estimate, :surprise_pct)",
            records,
        )
        return len(records)


def _upsert_insiders(records, db_path=None):
    if not records:
        return 0
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO insider_trades (ticker, date, insider_name, position, transaction_type, shares, value) "
            "VALUES (:ticker, :date, :insider_name, :position, :transaction_type, :shares, :value)",
            records,
        )
        return len(records)


def _save_short_interest(records, db_path=None):
    """Short interest → external_analysis 테이블 저장."""
    if not records:
        return 0
    from datetime import date

    from nuri.collectors.external import save_external

    today = str(date.today())
    count = 0
    for r in records:
        save_external(
            "short_interest",
            r["ticker"],
            "short_pct_float",
            str(r["short_pct_float"]),
            r["short_pct_float"],
            details=f"days_to_cover={r.get('days_to_cover', 'N/A')}",
            target_date=today,
            db_path=db_path,
        )
        count += 1
    return count


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Nuri-Quant Wall Street 데이터 수집기")
    parser.add_argument(
        "--source", default="portfolio", choices=["portfolio", "universe", "all"], help="ticker 소스 (#272 Phase 2b)"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    collector = WallStreetCollector()
    collector.run(source=args.source)

    # 요약
    from nuri.core.db import query

    for table in ["analyst_ratings", "earnings_surprises", "insider_trades"]:
        rows = query(f"SELECT COUNT(*) as c FROM {table}")
        print(f"  {table}: {rows[0]['c']}건")

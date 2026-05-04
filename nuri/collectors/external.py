"""
외부 데이터 수집기 — 6개 사이트에서 투자 판단 근거 수집.

자동 수집 (API/scrape 가능):
  - Fear & Greed (CNN) — 기존 fear_greed collector 사용
  - ARK Invest — 기존 ark collector 사용

반자동 수집 (이 모듈):
  - 수동 입력된 외부 분석 결과를 DB에 저장
  - consensus 실행 시 자동으로 참조

사용법:
    python -m nuri.collectors.external --save-tipranks TSLA "Strong Buy" 393.51 30
    python -m nuri.collectors.external --save-superinvestor TSLA 14 "Duan Yongping +1110%"
    python -m nuri.collectors.external --show TSLA
    python -m nuri.collectors.external --summary
"""

import argparse
import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional

from nuri.core.db import get_db, query

logger = logging.getLogger(__name__)

# 외부 소스 정의 (6개 기존 + 5개 신규)
SOURCES = {
    # 기존 6개
    "tipranks": "TipRanks 애널리스트 컨센서스",
    "dataroma": "Dataroma 슈퍼투자자 13F",
    "macrotrends": "Macrotrends 펀더멘탈",
    "ark": "ARK Invest 매수/매도",
    "etf_flows": "ETF.com 펀드 플로우",
    "tradingeconomics": "TradingEconomics 매크로",
    # 신규 5개 (Phase 2)
    "short_interest": "Short Interest (공매도 비율)",
    "cboe": "CBOE Put/Call Ratio",
    "coingecko": "CoinGecko BTC/Crypto 리스크",
    "finviz": "FINVIZ 기술적 스크리너",
    "reddit": "Reddit/WSB 센티먼트 분석",
}


def save_external(
    source: str,
    ticker: str,
    data_type: str,
    value: str,
    numeric_value: float | None = None,
    details: str = "",
    target_date: str | None = None,
    db_path: Optional[Path] = None,
) -> bool:
    """외부 분석 데이터를 DB에 저장."""
    if source not in SOURCES:
        logger.warning("알 수 없는 소스: %s (가능: %s)", source, list(SOURCES.keys()))
        return False

    d = target_date or str(date.today())
    try:
        with get_db(db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO external_analysis
                   (date, source, ticker, data_type, value, numeric_value, details)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (d, source, ticker, data_type, value, numeric_value, details),
            )
        logger.info("외부 데이터 저장: %s/%s/%s = %s", source, ticker, data_type, value)
        return True
    except Exception as e:
        logger.error("외부 데이터 저장 실패: %s", e)
        return False


def save_tipranks(
    ticker: str,
    consensus: str,
    target_price: float,
    analyst_count: int,
    upside_pct: float | None = None,
    db_path: Optional[Path] = None,
) -> None:
    """TipRanks 데이터 저장."""
    save_external("tipranks", ticker, "consensus", consensus, db_path=db_path)
    save_external("tipranks", ticker, "target_price", str(target_price), target_price, db_path=db_path)
    details = json.dumps({"analyst_count": analyst_count, "upside_pct": upside_pct})
    save_external(
        "tipranks", ticker, "analyst_count", str(analyst_count), analyst_count, details=details, db_path=db_path
    )


def save_superinvestor(
    ticker: str,
    count: int,
    trend: str,
    details: str = "",
    db_path: Optional[Path] = None,
) -> None:
    """Dataroma 슈퍼투자자 데이터 저장."""
    save_external("dataroma", ticker, "superinvestor_count", str(count), count, db_path=db_path)
    save_external("dataroma", ticker, "superinvestor_trend", trend, details=details, db_path=db_path)


def get_external(
    ticker: str,
    source: str | None = None,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """종목의 외부 분석 데이터 조회."""
    if source:
        rows = query(
            """SELECT * FROM external_analysis
               WHERE ticker = ? AND source = ?
               ORDER BY date DESC, data_type""",
            (ticker, source),
            db_path=db_path,
        )
    else:
        rows = query(
            """SELECT * FROM external_analysis
               WHERE ticker = ?
               ORDER BY source, date DESC, data_type""",
            (ticker,),
            db_path=db_path,
        )
    return [dict(r) for r in rows]


def get_external_summary(db_path: Optional[Path] = None) -> dict:
    """전체 외부 데이터 요약."""
    rows = query(
        """SELECT source, COUNT(DISTINCT ticker) as tickers,
                  COUNT(*) as records, MAX(date) as latest_date
           FROM external_analysis
           GROUP BY source
           ORDER BY source""",
        db_path=db_path,
    )
    return {
        "sources": [dict(r) for r in rows],
        "total_records": sum(r["records"] for r in rows),
    }


def print_ticker_external(ticker: str, db_path=None) -> None:
    """종목 외부 데이터 출력."""
    data = get_external(ticker, db_path=db_path)
    if not data:
        print(f"{ticker}: 외부 데이터 없음")
        return

    print(f"\n{'=' * 60}")
    print(f"  {ticker} — 외부 데이터 분석")
    print(f"{'=' * 60}")

    current_source = ""
    for d in data:
        if d["source"] != current_source:
            current_source = d["source"]
            desc = SOURCES.get(current_source, current_source)
            print(f"\n  [{desc}]")
        print(f"    {d['data_type']}: {d['value']} ({d['date']})")
    print()


def print_summary(db_path=None) -> None:
    """외부 데이터 요약 출력."""
    summary = get_external_summary(db_path=db_path)
    print(f"\n{'=' * 60}")
    print(f"  외부 데이터 요약 ({summary['total_records']}건)")
    print(f"{'=' * 60}")

    for s in summary["sources"]:
        desc = SOURCES.get(s["source"], s["source"])
        print(f"  {desc}: {s['tickers']}종목, {s['records']}건 (최신: {s['latest_date']})")
    print()


def main(argv: list[str] | None = None) -> int:
    """CLI: 외부 데이터 저장 / 조회 / 요약 dispatcher."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="외부 데이터 관리")
    parser.add_argument(
        "--save-tipranks", nargs=4, metavar=("TICKER", "CONSENSUS", "TARGET", "ANALYSTS"), help="TipRanks 데이터 저장"
    )
    parser.add_argument(
        "--save-superinvestor", nargs=3, metavar=("TICKER", "COUNT", "TREND"), help="Dataroma 슈퍼투자자 데이터 저장"
    )
    parser.add_argument("--show", metavar="TICKER", help="종목 외부 데이터 조회")
    parser.add_argument("--summary", action="store_true", help="전체 요약")

    args = parser.parse_args(argv)

    if args.save_tipranks:
        ticker, consensus, target, analysts = args.save_tipranks
        save_tipranks(ticker, consensus, float(target), int(analysts))
        print(f"✅ TipRanks 저장: {ticker}")
    elif args.save_superinvestor:
        ticker, count, trend = args.save_superinvestor
        save_superinvestor(ticker, int(count), trend)
        print(f"✅ Dataroma 저장: {ticker}")
    elif args.show:
        print_ticker_external(args.show)
    elif args.summary:
        print_summary()
    else:
        summary = get_external_summary()
        if summary["total_records"] == 0:
            print("외부 데이터 없음. 저장 예시:")
            print("  python -m nuri.collectors.external --save-tipranks NVDA 'Strong Buy' 273.61 38")
            print("  python -m nuri.collectors.external --save-superinvestor NVDA 14 'buying'")
        else:
            print_summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

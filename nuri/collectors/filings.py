"""
SEC 10-K/10-Q 핵심 지표 파서 — edgartools 기반.

최신 10-K에서 매출, 순이익, 총자산, 부채, 현금을 추출.
US 대형주만 (SEC EDGAR CIK 필요).

사용법:
    python -m nuri.collectors.filings
    python -m nuri.collectors.filings --ticker AAPL
"""
import argparse
import logging

from nuri.core.db import get_tickers

logger = logging.getLogger(__name__)

# SEC EDGAR identity
EDGAR_IDENTITY = "Nuri-Quant research@nuri-quant.dev"


def parse_10k(ticker: str) -> dict | None:
    """최신 10-K에서 핵심 재무 지표 추출."""
    from edgar import Company, set_identity
    set_identity(EDGAR_IDENTITY)

    try:
        company = Company(ticker)
        filings = company.get_filings(form="10-K")
        if not filings or len(filings) == 0:
            return None

        latest = filings[0]
        obj = latest.obj()
        filing_date = str(latest.filing_date)

        result = {
            "ticker": ticker,
            "filing_date": filing_date,
            "form": "10-K",
        }

        # Income Statement
        try:
            inc = obj.income_statement
            if inc:
                df = inc.to_dataframe()
                # 비차원(dimension=False), 비breakdown 행만
                main = df[(df["dimension"] == False) & (df["is_breakdown"] == False)]

                # 매출
                rev_row = main[main["concept"].str.contains("Revenue", case=False, na=False)]
                if not rev_row.empty:
                    # 최신 연도 컬럼 (숫자인 것)
                    num_cols = [c for c in rev_row.columns if c[0].isdigit()]
                    if num_cols:
                        result["revenue"] = float(rev_row.iloc[0][num_cols[0]])

                # 순이익
                ni_row = main[main["concept"].str.contains("NetIncome", case=False, na=False)]
                if not ni_row.empty:
                    num_cols = [c for c in ni_row.columns if c[0].isdigit()]
                    if num_cols:
                        result["net_income"] = float(ni_row.iloc[0][num_cols[0]])

                # 영업이익
                oi_row = main[main["concept"].str.contains("OperatingIncome", case=False, na=False)]
                if not oi_row.empty:
                    num_cols = [c for c in oi_row.columns if c[0].isdigit()]
                    if num_cols:
                        result["operating_income"] = float(oi_row.iloc[0][num_cols[0]])
        except Exception as e:
            logger.debug(f"{ticker} income statement: {e}")

        # Balance Sheet
        try:
            bs = obj.balance_sheet
            if bs:
                df = bs.to_dataframe()
                main = df[(df["dimension"] == False) & (df["is_breakdown"] == False)]

                for field, keyword in [
                    ("total_assets", "Assets"),
                    ("total_liabilities", "Liabilities"),
                    ("cash", "CashAndCashEquivalents"),
                ]:
                    row = main[main["concept"].str.contains(keyword, case=False, na=False)]
                    if not row.empty:
                        num_cols = [c for c in row.columns if c[0].isdigit()]
                        if num_cols:
                            result[field] = float(row.iloc[0][num_cols[0]])
        except Exception as e:
            logger.debug(f"{ticker} balance sheet: {e}")

        if len(result) > 3:  # ticker + filing_date + form + 최소 1개 지표
            return result
        return None

    except Exception as e:
        logger.debug(f"{ticker}: 10-K 파싱 실패 — {e}")
        return None


def collect_filings(tickers: list[str] | None = None) -> list[dict]:
    """복수 종목의 10-K 파싱."""
    if tickers is None:
        tickers = [t for t in get_tickers() if not t.endswith(".KS")]  # US only

    results = []
    for ticker in tickers:
        result = parse_10k(ticker)
        if result:
            results.append(result)
            rev = result.get("revenue", 0)
            ni = result.get("net_income", 0)
            logger.info(f"  {ticker}: Rev ${rev/1e9:.1f}B, NI ${ni/1e9:.1f}B ({result['filing_date']})")
        else:
            logger.debug(f"  {ticker}: 10-K 없음")

    return results


def print_filings(results: list[dict]) -> None:
    if not results:
        print("10-K 데이터 없음")
        return

    print(f"\n{'=' * 75}")
    print(f"  SEC 10-K Filings — {len(results)} companies")
    print(f"{'=' * 75}")
    print(f"  {'Ticker':<8} {'Filing':>12} {'Revenue':>12} {'Net Income':>12} {'Assets':>12} {'Cash':>12}")
    print(f"  {'-' * 70}")

    for r in results:
        rev = f"${r.get('revenue', 0)/1e9:.1f}B" if r.get("revenue") else "—"
        ni = f"${r.get('net_income', 0)/1e9:.1f}B" if r.get("net_income") else "—"
        assets = f"${r.get('total_assets', 0)/1e9:.1f}B" if r.get("total_assets") else "—"
        cash = f"${r.get('cash', 0)/1e9:.1f}B" if r.get("cash") else "—"
        print(f"  {r['ticker']:<8} {r['filing_date']:>12} {rev:>12} {ni:>12} {assets:>12} {cash:>12}")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="SEC 10-K Parser")
    parser.add_argument("--ticker", help="특정 종목만")
    args = parser.parse_args()

    if args.ticker:
        result = parse_10k(args.ticker)
        if result:
            print_filings([result])
        else:
            print(f"{args.ticker}: 10-K 없음")
    else:
        results = collect_filings()
        print_filings(results)

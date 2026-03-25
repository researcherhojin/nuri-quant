"""
포트폴리오 현황 분석 — 종목별 현재가치, 비중, 손익 계산.

투자규칙 적용:
- 단일 종목 비중 15% 초과 경고
- 레버리지 ETF(TSLL) 매도 경고

사용법:
    python -m iris.analysis.portfolio
"""
import logging
from typing import Optional

import pandas as pd

from iris.db import query_df, query

logger = logging.getLogger(__name__)


def get_exchange_rate() -> float:
    """USD/KRW 환율 조회. DB에 없으면 기본값 사용."""
    rows = query(
        "SELECT value FROM macro WHERE indicator = 'usd_krw' ORDER BY date DESC LIMIT 1"
    )
    if rows:
        return rows[0]["value"]
    # 폴백: OpenBB로 환율 조회
    try:
        from openbb import obb
        result = obb.currency.price.historical("USDKRW", provider="yfinance", start_date="2026-01-01")
        df = result.to_dataframe()
        if not df.empty:
            return float(df["close"].iloc[-1])
    except Exception:
        pass
    return 1450.0  # 기본값


def analyze_portfolio() -> pd.DataFrame:
    """포트폴리오 전체 현황 분석."""
    # 보유 종목 조회
    holdings = query_df("""
        SELECT p.account, p.ticker, p.quantity, p.avg_price, p.currency, p.sector
        FROM portfolio p
        ORDER BY p.account, p.ticker
    """)

    if holdings.empty:
        logger.warning("보유 종목이 없습니다")
        return pd.DataFrame()

    usd_krw = get_exchange_rate()

    # 종목별 최신 가격 조회
    results = []
    for _, row in holdings.iterrows():
        ticker = row["ticker"]
        latest = query(
            "SELECT close, date FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (ticker,),
        )

        if not latest:
            logger.warning(f"{ticker}: 가격 데이터 없음")
            continue

        current_price = latest[0]["close"]
        price_date = latest[0]["date"]

        qty = row["quantity"]
        avg_price = row["avg_price"]
        currency = row["currency"]

        # 현재가치 (USD 기준으로 통일)
        # .KS 종목은 계좌 통화와 무관하게 KRW로 처리
        is_krw = currency == "KRW" or ticker.endswith(".KS")
        if is_krw:
            current_value_usd = (current_price * qty) / usd_krw
            cost_basis_usd = (avg_price * qty) / usd_krw
        else:
            current_value_usd = current_price * qty
            cost_basis_usd = avg_price * qty

        pnl = current_value_usd - cost_basis_usd
        pnl_pct = (pnl / cost_basis_usd * 100) if cost_basis_usd != 0 else 0.0

        results.append({
            "account": row["account"],
            "ticker": ticker,
            "sector": row["sector"],
            "quantity": qty,
            "avg_price": avg_price,
            "current_price": current_price,
            "currency": currency,
            "current_value_usd": round(current_value_usd, 2),
            "cost_basis_usd": round(cost_basis_usd, 2),
            "pnl_usd": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "price_date": price_date,
        })

    df = pd.DataFrame(results)
    if df.empty:
        return df

    # 비중 계산
    total_value = df["current_value_usd"].sum()
    df["weight_pct"] = round(df["current_value_usd"] / total_value * 100, 2)

    # 종목별 합산 비중 (다계좌 동일 종목)
    ticker_weights = df.groupby("ticker")["weight_pct"].sum()

    # ⚠️ 투자규칙 경고
    warnings = []
    for ticker, weight in ticker_weights.items():
        if weight > 15.0:
            warnings.append(f"⚠️ {ticker}: 비중 {weight:.1f}% > 15% 한도 초과!")

    # TSLL 레버리지 ETF 경고
    if "TSLL" in df["ticker"].values:
        warnings.append("⚠️ TSLL: 레버리지 ETF 장기 보유 금지! 매도 권장")

    df.attrs["warnings"] = warnings
    df.attrs["total_value_usd"] = round(total_value, 2)
    df.attrs["usd_krw"] = usd_krw

    return df


def print_summary(df: pd.DataFrame) -> None:
    """포트폴리오 요약 출력."""
    if df.empty:
        print("포트폴리오 데이터가 없습니다.")
        return

    usd_krw = df.attrs.get("usd_krw", 1450.0)
    total_usd = df.attrs.get("total_value_usd", 0)
    total_krw = total_usd * usd_krw

    print("=" * 70)
    print(f"  IRIS 포트폴리오 현황  (USD/KRW: {usd_krw:,.0f})")
    print(f"  총 평가액: ${total_usd:,.0f} (₩{total_krw:,.0f})")
    print("=" * 70)

    # 계좌별 출력
    for account in df["account"].unique():
        acct_df = df[df["account"] == account]
        acct_total = acct_df["current_value_usd"].sum()
        acct_pnl = acct_df["pnl_usd"].sum()
        print(f"\n📊 {account} (${acct_total:,.0f}, P&L: ${acct_pnl:+,.0f})")
        print("-" * 70)
        print(f"  {'Ticker':<12} {'비중%':>6} {'현재가':>10} {'평단':>10} "
              f"{'손익%':>8} {'평가액$':>10}")
        print("-" * 70)

        for _, row in acct_df.sort_values("current_value_usd", ascending=False).iterrows():
            print(f"  {row['ticker']:<12} {row['weight_pct']:>5.1f}% "
                  f"{row['current_price']:>10,.2f} {row['avg_price']:>10,.2f} "
                  f"{row['pnl_pct']:>+7.1f}% {row['current_value_usd']:>10,.0f}")

    # 경고
    warnings = df.attrs.get("warnings", [])
    if warnings:
        print("\n" + "=" * 70)
        print("  투자규칙 경고")
        print("=" * 70)
        for w in warnings:
            print(f"  {w}")

    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    df = analyze_portfolio()
    print_summary(df)

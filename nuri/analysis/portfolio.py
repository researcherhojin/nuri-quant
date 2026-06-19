# pyright: reportAttributeAccessIssue=false
"""
포트폴리오 현황 분석 — 종목별 현재가치, 비중, 손익 계산.

(OpenBB BaseApp 동적 attribute (currency 등) stub 부재 — runtime 정상.)

투자규칙 적용:
- 단일 종목 비중 15% 초과 경고
- 레버리지 ETF(TSLL) 매도 경고

사용법:
    python -m nuri.analysis.portfolio
"""

import logging

import pandas as pd

from nuri.core.db import query, query_df
from nuri.core.rules import LEVERAGE_ETFS, MAX_SINGLE_POSITION

logger = logging.getLogger(__name__)


class StaleExchangeRateError(Exception):
    """환율 데이터가 DB에 없을 때 발생하는 에러."""


def get_exchange_rate() -> float:
    """USD/KRW 환율 조회. 7일 이상 오래되면 WARNING, DB에 없으면 에러."""
    rows = query("SELECT value, date FROM macro WHERE indicator = 'usd_krw' ORDER BY date DESC LIMIT 1")
    if rows:
        rate = rows[0]["value"]
        rate_date = rows[0]["date"]

        # 신선도 체크: 7일 초과 시 경고
        from datetime import datetime

        from nuri.core.timezone import kst_now

        latest = datetime.strptime(rate_date, "%Y-%m-%d")
        age_days = (kst_now().replace(tzinfo=None) - latest).days
        if age_days > 7:
            logger.warning(
                "USD/KRW 환율 %d일 경과 (날짜: %s, 값: %.1f). 'make collect'으로 갱신 권장",
                age_days,
                rate_date,
                rate,
            )
        return rate

    # DB에 환율 없음 -> OpenBB 시도
    try:
        from openbb import obb

        result = obb.currency.price.historical("USDKRW", provider="yfinance", start_date="2026-01-01")
        df = result.to_dataframe()
        if not df.empty:
            return float(df["close"].iloc[-1])
    except Exception:
        pass

    raise StaleExchangeRateError(
        "USD/KRW 환율을 찾을 수 없습니다. 'python -m nuri.collectors.macro'로 환율 데이터를 수집하세요."
    )


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

        results.append(
            {
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
            }
        )

    df = pd.DataFrame(results)
    if df.empty:
        return df

    # 비중 계산
    total_value = df["current_value_usd"].sum()
    df["weight_pct"] = round(df["current_value_usd"] / total_value * 100, 2)

    # 종목별 합산 비중 (다계좌 동일 종목)
    ticker_weights = df.groupby("ticker")["weight_pct"].sum()

    # ⚠️ 투자규칙 경고 — 임계는 config/rules.yaml SSoT (#759)
    max_pos_pct = MAX_SINGLE_POSITION * 100
    warnings = []
    for ticker, weight in ticker_weights.items():
        if weight > max_pos_pct:
            warnings.append(f"⚠️ {ticker}: 비중 {weight:.1f}% > {max_pos_pct:.0f}% 한도 초과!")

    # 레버리지 ETF 경고 (rules.yaml banned_etfs — TSLL/TQQQ/SQQQ/UPRO/SPXU)
    for ticker in sorted({t for t in df["ticker"].values if t in LEVERAGE_ETFS}):
        warnings.append(f"⚠️ {ticker}: 레버리지 ETF 장기 보유 금지! 매도 권장")

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
    print(f"  Nuri-Quant 포트폴리오 현황  (USD/KRW: {usd_krw:,.0f})")
    print(f"  총 평가액: ${total_usd:,.0f} (₩{total_krw:,.0f})")
    print("=" * 70)

    # 계좌별 출력
    for account in df["account"].unique():
        acct_df = df[df["account"] == account]
        acct_total = acct_df["current_value_usd"].sum()
        acct_pnl = acct_df["pnl_usd"].sum()
        print(f"\n📊 {account} (${acct_total:,.0f}, P&L: ${acct_pnl:+,.0f})")
        print("-" * 70)
        print(f"  {'Ticker':<12} {'비중%':>6} {'현재가':>10} {'평단':>10} {'손익%':>8} {'평가액$':>10}")
        print("-" * 70)

        for _, row in acct_df.sort_values("current_value_usd", ascending=False).iterrows():
            print(
                f"  {row['ticker']:<12} {row['weight_pct']:>5.1f}% "
                f"{row['current_price']:>10,.2f} {row['avg_price']:>10,.2f} "
                f"{row['pnl_pct']:>+7.1f}% {row['current_value_usd']:>10,.0f}"
            )

    # 경고
    warnings = df.attrs.get("warnings", [])
    if warnings:
        print("\n" + "=" * 70)
        print("  투자규칙 경고")
        print("=" * 70)
        for w in warnings:
            print(f"  {w}")

    print()


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: 포트폴리오 요약 출력."""
    del argv  # 인자 없음
    logging.basicConfig(level=logging.INFO)
    df = analyze_portfolio()
    print_summary(df)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

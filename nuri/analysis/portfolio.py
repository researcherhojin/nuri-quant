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

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from nuri.core.db import query, query_df
from nuri.core.rules import LEVERAGE_ETFS, MAX_SINGLE_POSITION
from nuri.core.ticker_names import is_kr_ticker

logger = logging.getLogger(__name__)

#: 현금 잔고 원본. 모듈 상수로 두는 이유는 두 가지다 — 매 호출 경로 계산을 피하고,
#: `test_db_path_forwarding` 스윕이 `Path.resolve()` 를 (이름이 같은) DB 리더로 오탐하는
#: 것을 막는다. 그 스윕은 함수명으로 매칭하므로 `resolve` 가 함수 본문에 있으면 걸린다.
_DEFAULT_PORTFOLIO_YAML = Path(__file__).resolve().parents[2] / "config" / "portfolio.yaml"


class StaleExchangeRateError(Exception):
    """환율 데이터가 DB에 없을 때 발생하는 에러."""


def get_exchange_rate(db_path=None) -> float:
    """USD/KRW 환율 조회. 7일 이상 오래되면 WARNING, DB에 없으면 에러."""
    # #1278: 날짜 상한 + 미래행 경고는 공용 리더가 담당한다 (nuri/core/fx.py).
    from nuri.core.fx import latest_usd_krw

    got = latest_usd_krw(db_path=db_path)
    if got:
        rate, rate_date = got

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


def portfolio_state(db_path=None, config_path: Path | None = None) -> dict:
    """`ExecutionFirewall` 이 받는 포트폴리오 스냅샷 (#1107).

    반환 형태는 `execution_firewall.ExecutionFirewall._check` 의 계약 그대로:
    `{total_value, cash, positions: {ticker: {value, sector}}, vix}` — 전부 USD 정규화.

    ## 왜 이 함수가 새로 필요한가

    유일한 빌더가 `scripts/ops/run_phase2_chain.py:97` 의
    `SELECT ticker, qty, current_price FROM holdings` 였는데 **`holdings` 테이블은 존재하지
    않는다** (실제 테이블은 `portfolio`, 컬럼도 `quantity`/`avg_price` 이고 `current_price`
    는 없다). 예외가 `except Exception` 에 삼켜져 `total_value=100_000, positions={}` 라는
    **허구**로 계산됐고, 그래서 `execution_blocks` 는 도입 이래 프로덕션 **0행**이다 —
    firewall 이 "안 불린" 게 아니라 **산술적으로 아무것도 못 막는** 상태였다.

    ## 왜 `analyze_portfolio()` 를 재사용하나

    그쪽이 이미 KRW→USD 환산(`.KS`/`.KQ` 는 계좌 통화와 무관하게 KRW 처리, #764) ·
    다계좌 합산 · 섹터를 처리한다. 여기서 다시 짜면 두 경로가 갈라지고, 갈라진 쪽이
    조용히 낡는다.

    ## cash 는 DB 가 아니라 `config/portfolio.yaml` 이 원본이다

    잔고는 브로커에서 손으로 옮겨 적는 값이라 DB 에 없다. 없으면 **0** 이다 — 모르는
    현금을 넉넉하다고 가정하면 `cash_reserve` 가 있으나 마나가 된다.

    다만 0 이 모든 게이트를 조이는 건 아니다. 정확히는 이렇다:

    - `cash_reserve` — post-trade 현금 비중이 음수가 되므로 **반드시 막는다** (fail-closed).
    - `leverage_cap` — firewall 이 `cash > 0` 일 때만 검사하므로 **건너뛴다**. 0 으로
      나눌 수 없으니 그쪽 설계가 맞다. 즉 cash=0 은 그 한 게이트에 대해서는 조이는
      방향이 아니다 — 지금 룰에서 BUY 는 `cash_reserve` 가 먼저 잡아서 결과가 같지만,
      "0 이면 무조건 보수적" 이라고 읽지 말 것.

    **Test:** `tests/analysis/test_portfolio_state.py::TestTheFirewallActuallyBlocksNow::
    test_unreadable_cash_cannot_turn_a_block_into_a_pass`
    """
    import yaml

    from nuri.core.db import query

    df = analyze_portfolio(db_path=db_path)

    positions: dict[str, dict] = {}
    total_value = 0.0
    if not df.empty:
        # 다계좌 동일 종목은 합산한다 — firewall 의 position_limit 은 **종목** 단위다.
        for ticker, grp in df.groupby("ticker"):
            value = float(grp["current_value_usd"].sum())
            sector = next((s for s in grp["sector"] if s), None)
            positions[str(ticker)] = {"value": value, "sector": sector}
            total_value += value

    rate = get_exchange_rate(db_path=db_path) or 1400.0
    cash = 0.0
    path = config_path or _DEFAULT_PORTFOLIO_YAML
    try:
        accounts = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("accounts") or {}
        for info in accounts.values():
            if isinstance(info, dict):
                cash += float(info.get("cash_usd") or 0) + float(info.get("cash_krw") or 0) / rate
    except (OSError, yaml.YAMLError, TypeError, ValueError) as e:
        # 현금을 못 읽으면 0 — 넉넉하다고 가정하는 쪽이 위험하다.
        logger.warning("portfolio.yaml cash 읽기 실패, cash=0 으로 진행: %s", e)

    vix_row = query(
        "SELECT value FROM macro WHERE indicator = 'vix' ORDER BY date DESC LIMIT 1",
        db_path=db_path,
    )

    return {
        "total_value": round(total_value, 2),
        "cash": round(cash, 2),
        "positions": positions,
        "vix": float(vix_row[0]["value"]) if vix_row else None,
    }


def analyze_portfolio(db_path=None) -> pd.DataFrame:
    """포트폴리오 전체 현황 분석.

    `db_path` 는 선택이다 — 기존 호출자 10곳은 인자 없이 부르고 기본 DB 를 쓴다.
    받아야 하는 이유는 `certification._capture_snapshot()` 이다: 그쪽이 감사
    스냅샷을 뜨면서 이 함수만 db_path 를 못 넘겨, 스냅샷이 절반은 지정 DB
    절반은 기본 DB 에서 오는 상태였다 (#1050).
    """
    # 보유 종목 조회
    holdings = query_df(
        """
        SELECT p.account, p.ticker, p.quantity, p.avg_price, p.currency, p.sector
        FROM portfolio p
        ORDER BY p.account, p.ticker
    """,
        db_path=db_path,
    )

    if holdings.empty:
        logger.warning("보유 종목이 없습니다")
        return pd.DataFrame()

    usd_krw = get_exchange_rate(db_path=db_path)

    # 종목별 최신 가격 조회
    results = []
    for _, row in holdings.iterrows():
        ticker = row["ticker"]
        latest = query(
            "SELECT close, date FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (ticker,),
            db_path=db_path,
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
        # KR(.KS/.KQ) 종목은 계좌 통화와 무관하게 KRW로 처리 (#764)
        is_krw = currency == "KRW" or is_kr_ticker(ticker)
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

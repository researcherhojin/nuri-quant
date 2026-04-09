"""
레버리지 ETF 조건부 허용 연구 — TSLL vs TSLA 비교 백테스트.

SIEGE gate #6 (leverage_ban) 완화 가능성을 데이터로 평가한다.
4가지 시나리오를 비교하여 레버리지 ETF가 조건부로 수익을 개선하는지 검증.

시나리오:
    A) Buy-and-hold TSLL vs TSLA
    B) TSLL only when VIX < 20 (exit when VIX >= 25)
    C) TSLL only when SMA50 > SMA200 (trend following)
    D) TSLL with max 10-day holding period

사용법:
    python -m nuri.quant.backtest.leverage_study
"""
import argparse
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from nuri.core.db import query_df

logger = logging.getLogger(__name__)

# 연거래일 기준 (Sharpe 등 연율화)
TRADING_DAYS_PER_YEAR = 252


def _load_prices(ticker: str, db_path: Optional[Path] = None) -> pd.DataFrame:
    """DB에서 가격 데이터 로드. 없으면 yfinance 폴백."""
    df = query_df(
        "SELECT date, close FROM prices WHERE ticker = ? ORDER BY date",
        (ticker,),
        db_path=db_path,
    )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        return df

    # yfinance 폴백 (테스트에서는 conftest가 mock)
    logger.info(f"{ticker}: DB에 가격 없음, yfinance 폴백 시도")
    import yfinance as yf
    raw = yf.download(ticker, period="2y", progress=False)
    if raw.empty:
        return pd.DataFrame(columns=["close"])
    result = pd.DataFrame({"close": raw["Close"].values}, index=raw.index)
    result.index.name = "date"
    return result


def _load_vix(db_path: Optional[Path] = None) -> pd.Series:
    """DB에서 VIX 시계열 로드."""
    df = query_df(
        "SELECT date, value FROM macro WHERE indicator = 'vix' ORDER BY date",
        db_path=db_path,
    )
    if df.empty:
        return pd.Series(dtype=float, name="vix")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["value"].sort_index().rename("vix")


def _calc_metrics(returns: pd.Series) -> dict:
    """일간 수익률 시리즈에서 성과 지표 계산."""
    if returns.empty or len(returns) < 2:
        return {
            "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "annual_volatility_pct": 0.0,
            "trading_days": 0,
        }

    # 누적 수익률
    cum = (1 + returns).cumprod()
    total_return = (cum.iloc[-1] - 1) * 100

    # 최대 낙폭
    peak = cum.cummax()
    drawdown = (cum - peak) / peak
    max_dd = drawdown.min() * 100

    # Sharpe (연율화, 무위험 수익률 0 가정)
    mean_ret = returns.mean()
    std_ret = returns.std()
    sharpe = 0.0
    if std_ret > 0:
        sharpe = (mean_ret / std_ret) * np.sqrt(TRADING_DAYS_PER_YEAR)

    # 연율화 변동성
    annual_vol = std_ret * np.sqrt(TRADING_DAYS_PER_YEAR) * 100

    return {
        "total_return_pct": round(float(total_return), 2),
        "max_drawdown_pct": round(float(max_dd), 2),
        "sharpe_ratio": round(float(sharpe), 2),
        "annual_volatility_pct": round(float(annual_vol), 2),
        "trading_days": len(returns),
    }


def _calc_volatility_decay(leveraged: pd.Series, underlying: pd.Series) -> float:
    """변동성 감쇠(decay) 측정 — 레버리지 ETF vs 기초자산 2x 수익률 괴리.

    레버리지 ETF는 일간 리밸런싱으로 인해 장기 보유 시
    기초자산의 2배 수익률에서 괴리가 발생한다 (volatility drag).
    """
    if leveraged.empty or underlying.empty:
        return 0.0

    # 공통 기간 정렬
    common = leveraged.index.intersection(underlying.index)
    if len(common) < 2:
        return 0.0

    lev_ret = leveraged.loc[common]
    und_ret = underlying.loc[common]

    # 실제 레버리지 누적 vs 이론적 2x 누적
    actual_cum = (1 + lev_ret).cumprod().iloc[-1]
    theoretical_cum = (1 + und_ret * 2).cumprod().iloc[-1]

    if theoretical_cum == 0:
        return 0.0

    decay = (actual_cum / theoretical_cum - 1) * 100
    return round(float(decay), 2)


def scenario_buy_and_hold(
    leveraged_prices: pd.DataFrame,
    underlying_prices: pd.DataFrame,
) -> dict:
    """시나리오 A: Buy-and-hold TSLL vs TSLA 비교."""
    result = {"scenario": "A_buy_and_hold"}

    lev_returns = leveraged_prices["close"].pct_change().dropna()
    und_returns = underlying_prices["close"].pct_change().dropna()

    result["leveraged"] = _calc_metrics(lev_returns)
    result["underlying"] = _calc_metrics(und_returns)
    result["volatility_decay_pct"] = _calc_volatility_decay(lev_returns, und_returns)

    return result


def scenario_vix_filter(
    leveraged_prices: pd.DataFrame,
    vix: pd.Series,
    entry_below: float = 20.0,
    exit_above: float = 25.0,
) -> dict:
    """시나리오 B: VIX < entry_below일 때만 TSLL 보유, VIX >= exit_above 시 퇴장."""
    result = {"scenario": "B_vix_filter", "entry_below": entry_below, "exit_above": exit_above}

    lev_returns = leveraged_prices["close"].pct_change().dropna()

    if vix.empty:
        result["leveraged"] = _calc_metrics(pd.Series(dtype=float))
        result["trade_count"] = 0
        return result

    # VIX를 가격 인덱스에 정렬 (forward fill)
    vix_aligned = vix.reindex(lev_returns.index, method="ffill")

    # 포지션 상태 결정 (히스테리시스: entry < exit)
    in_position = False
    positions = []
    trade_count = 0
    for idx in lev_returns.index:
        v = vix_aligned.get(idx)
        if v is None or pd.isna(v):
            positions.append(in_position)
            continue
        if not in_position and v < entry_below:
            in_position = True
            trade_count += 1
        elif in_position and v >= exit_above:
            in_position = False
        positions.append(in_position)

    pos_mask = pd.Series(positions, index=lev_returns.index)
    filtered_returns = lev_returns.where(pos_mask, 0.0)

    result["leveraged"] = _calc_metrics(filtered_returns)
    result["trade_count"] = trade_count
    return result


def scenario_trend_follow(
    leveraged_prices: pd.DataFrame,
    sma_short: int = 50,
    sma_long: int = 200,
) -> dict:
    """시나리오 C: SMA50 > SMA200일 때만 TSLL 보유 (추세 추종)."""
    result = {"scenario": "C_trend_follow", "sma_short": sma_short, "sma_long": sma_long}

    close = leveraged_prices["close"]
    if len(close) < sma_long:
        result["leveraged"] = _calc_metrics(pd.Series(dtype=float))
        return result

    sma_s = close.rolling(sma_short).mean()
    sma_l = close.rolling(sma_long).mean()

    # SMA 교차 기반 포지션
    trend_up = sma_s > sma_l

    lev_returns = close.pct_change().dropna()
    trend_aligned = trend_up.reindex(lev_returns.index).fillna(False)
    filtered_returns = lev_returns.where(trend_aligned, 0.0)

    result["leveraged"] = _calc_metrics(filtered_returns)
    return result


def scenario_max_hold(
    leveraged_prices: pd.DataFrame,
    max_days: int = 10,
) -> dict:
    """시나리오 D: 최대 max_days일 보유 후 강제 청산, 1일 쿨다운 후 재진입."""
    result = {"scenario": "D_max_hold", "max_days": max_days}

    lev_returns = leveraged_prices["close"].pct_change().dropna()
    if lev_returns.empty:
        result["leveraged"] = _calc_metrics(pd.Series(dtype=float))
        result["trade_count"] = 0
        return result

    # max_days 보유 → 1일 쿨다운 → 재진입
    positions = []
    days_held = 0
    in_position = True
    cooldown = False
    trade_count = 1

    for _ in lev_returns.index:
        if cooldown:
            positions.append(False)
            cooldown = False
            in_position = True
            days_held = 0
            trade_count += 1
            continue

        if in_position:
            positions.append(True)
            days_held += 1
            if days_held >= max_days:
                in_position = False
                cooldown = True
                days_held = 0
        else:
            positions.append(False)

    pos_mask = pd.Series(positions, index=lev_returns.index)
    filtered_returns = lev_returns.where(pos_mask, 0.0)

    result["leveraged"] = _calc_metrics(filtered_returns)
    result["trade_count"] = trade_count
    return result


def run_leverage_study(
    leveraged_ticker: str = "TSLL",
    underlying_ticker: str = "TSLA",
    db_path: Optional[Path] = None,
) -> dict:
    """전체 레버리지 ETF 연구 실행.

    Returns:
        시나리오별 결과를 포함하는 딕셔너리.
    """
    lev_prices = _load_prices(leveraged_ticker, db_path)
    und_prices = _load_prices(underlying_ticker, db_path)
    vix = _load_vix(db_path)

    if lev_prices.empty:
        logger.warning(f"{leveraged_ticker}: 가격 데이터 없음 — 스터디 중단")
        return {"error": f"No price data for {leveraged_ticker}"}

    if und_prices.empty:
        logger.warning(f"{underlying_ticker}: 가격 데이터 없음 — 스터디 중단")
        return {"error": f"No price data for {underlying_ticker}"}

    # 공통 기간으로 정렬
    common_start = max(lev_prices.index.min(), und_prices.index.min())
    common_end = min(lev_prices.index.max(), und_prices.index.max())
    lev_prices = lev_prices.loc[common_start:common_end]
    und_prices = und_prices.loc[common_start:common_end]

    results = {
        "leveraged_ticker": leveraged_ticker,
        "underlying_ticker": underlying_ticker,
        "period_start": str(common_start.date()),
        "period_end": str(common_end.date()),
        "scenarios": {},
    }

    # 시나리오 A: Buy-and-hold
    results["scenarios"]["A_buy_and_hold"] = scenario_buy_and_hold(lev_prices, und_prices)

    # 시나리오 B: VIX 필터
    results["scenarios"]["B_vix_filter"] = scenario_vix_filter(lev_prices, vix)

    # 시나리오 C: 추세 추종
    results["scenarios"]["C_trend_follow"] = scenario_trend_follow(lev_prices)

    # 시나리오 D: 최대 보유일 제한
    results["scenarios"]["D_max_hold"] = scenario_max_hold(lev_prices)

    return results


def print_study(results: dict) -> None:
    """연구 결과 출력."""
    if "error" in results:
        print(f"\n  오류: {results['error']}")
        return

    print(f"\n{'=' * 60}")
    print("  레버리지 ETF 조건부 허용 연구")
    print(f"  {results['leveraged_ticker']} vs {results['underlying_ticker']}")
    print(f"  기간: {results['period_start']} ~ {results['period_end']}")
    print(f"{'=' * 60}")

    for key, scenario in results["scenarios"].items():
        print(f"\n  --- {scenario['scenario']} ---")
        if "underlying" in scenario:
            u = scenario["underlying"]
            print(f"  [{results['underlying_ticker']}] 수익: {u['total_return_pct']:+.2f}%  "
                  f"MDD: {u['max_drawdown_pct']:.2f}%  Sharpe: {u['sharpe_ratio']:.2f}")

        lev = scenario.get("leveraged", {})
        if lev:
            print(f"  [{results['leveraged_ticker']}] 수익: {lev.get('total_return_pct', 0):+.2f}%  "
                  f"MDD: {lev.get('max_drawdown_pct', 0):.2f}%  "
                  f"Sharpe: {lev.get('sharpe_ratio', 0):.2f}  "
                  f"Vol: {lev.get('annual_volatility_pct', 0):.1f}%")

        if "volatility_decay_pct" in scenario:
            print(f"  변동성 감쇠(decay): {scenario['volatility_decay_pct']:+.2f}%")
        if "trade_count" in scenario:
            print(f"  거래 횟수: {scenario['trade_count']}")

    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="레버리지 ETF 조건부 허용 연구")
    parser.add_argument("--leveraged", default="TSLL", help="레버리지 ETF 티커")
    parser.add_argument("--underlying", default="TSLA", help="기초자산 티커")
    args = parser.parse_args()

    results = run_leverage_study(
        leveraged_ticker=args.leveraged,
        underlying_ticker=args.underlying,
    )
    print_study(results)

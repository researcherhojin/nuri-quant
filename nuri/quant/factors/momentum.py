"""모멘텀 팩터 — 12개월 수익률, RSI, 52주 고점 근접도."""
import numpy as np
import pandas as pd

from nuri.db import query_df


def compute_momentum(tickers: list[str] | None = None) -> pd.DataFrame:
    """종목별 모멘텀 스코어 계산 (0~1 정규화)."""
    prices = query_df("SELECT ticker, date, close FROM prices ORDER BY date")
    if prices.empty:
        return pd.DataFrame()

    pivot = prices.pivot_table(index="date", columns="ticker", values="close")
    if tickers:
        pivot = pivot[[t for t in tickers if t in pivot.columns]]

    scores = {}
    for ticker in pivot.columns:
        s = pivot[ticker].dropna()
        if len(s) < 14:
            continue

        # 기간 수익률 (데이터 전체)
        period_return = (s.iloc[-1] / s.iloc[0]) - 1

        # RSI 기반 모멘텀 (signals 테이블에서)
        rsi_rows = query_df(
            "SELECT rsi_14 FROM signals WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (ticker,),
        )
        rsi = rsi_rows.iloc[0]["rsi_14"] if not rsi_rows.empty and rsi_rows.iloc[0]["rsi_14"] else 50

        # 52주(또는 가용 데이터) 고점 대비 %
        high_52w = s.max()
        proximity = s.iloc[-1] / high_52w if high_52w > 0 else 0

        scores[ticker] = {
            "period_return": period_return,
            "rsi_14": rsi,
            "high_proximity": proximity,
        }

    if not scores:
        return pd.DataFrame()

    df = pd.DataFrame(scores).T
    # 각 지표를 0~1 정규화 후 가중 합산
    for col in df.columns:
        col_min, col_max = df[col].min(), df[col].max()
        if col_max > col_min:
            df[col + "_norm"] = (df[col] - col_min) / (col_max - col_min)
        else:
            df[col + "_norm"] = 0.5

    df["momentum_score"] = (
        df["period_return_norm"] * 0.4 +
        df["rsi_14_norm"] * 0.3 +
        df["high_proximity_norm"] * 0.3
    )

    return df[["period_return", "rsi_14", "high_proximity", "momentum_score"]].round(4)

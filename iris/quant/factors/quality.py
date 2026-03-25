"""퀄리티 팩터 — ROE, 영업이익률 기반."""
import logging

import pandas as pd

logger = logging.getLogger(__name__)


def compute_quality(tickers: list[str] | None = None) -> pd.DataFrame:
    """종목별 퀄리티 스코어."""
    from openbb import obb

    if not tickers:
        from iris.db import get_tickers
        tickers = [t for t in get_tickers() if not t.endswith(".KS")]

    scores = {}
    for ticker in tickers:
        try:
            result = obb.equity.fundamental.ratios(ticker, provider="yfinance", limit=1)
            df = result.to_dataframe()
            if df.empty:
                continue

            row = df.iloc[0]
            roe = row.get("return_on_equity", row.get("roe"))
            margin = row.get("operating_profit_margin", row.get("net_profit_margin"))

            scores[ticker] = {
                "roe": float(roe) if roe and roe == roe else None,
                "operating_margin": float(margin) if margin and margin == margin else None,
            }
        except Exception as e:
            logger.debug(f"{ticker}: 퀄리티 조회 실패 — {e}")

    if not scores:
        return pd.DataFrame()

    df = pd.DataFrame(scores).T

    for col in ["roe", "operating_margin"]:
        if col in df.columns:
            valid = df[col].dropna()
            if len(valid) > 1:
                col_min, col_max = valid.min(), valid.max()
                if col_max > col_min:
                    df[col + "_norm"] = (valid - col_min) / (col_max - col_min)
                else:
                    df[col + "_norm"] = 0.5

    norm_cols = [c for c in df.columns if c.endswith("_norm")]
    if norm_cols:
        df["quality_score"] = df[norm_cols].mean(axis=1)
    else:
        df["quality_score"] = 0.5

    return df.round(4)

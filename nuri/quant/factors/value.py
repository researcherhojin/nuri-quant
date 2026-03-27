"""가치 팩터 — PER, PBR 기반 (OpenBB 펀더멘털 활용)."""
import logging

import pandas as pd

logger = logging.getLogger(__name__)


def compute_value(tickers: list[str] | None = None) -> pd.DataFrame:
    """종목별 가치 스코어 계산 (낮을수록 저평가)."""
    from openbb import obb

    if not tickers:
        from nuri.core.db import get_tickers
        tickers = [t for t in get_tickers() if not t.endswith(".KS")]

    scores = {}
    for ticker in tickers:
        try:
            result = obb.equity.fundamental.ratios(ticker, provider="yfinance", limit=1)
            df = result.to_dataframe()
            if df.empty:
                continue

            row = df.iloc[0]
            pe = row.get("pe_ratio", row.get("price_earnings_ratio"))
            pb = row.get("pb_ratio", row.get("price_to_book_ratio"))

            scores[ticker] = {
                "pe_ratio": float(pe) if pe and pe == pe else None,
                "pb_ratio": float(pb) if pb and pb == pb else None,
            }
        except Exception as e:
            logger.debug(f"{ticker}: 펀더멘털 조회 실패 — {e}")

    if not scores:
        return pd.DataFrame()

    df = pd.DataFrame(scores).T

    # 역수 정규화 (낮은 PE/PB = 높은 가치 스코어)
    for col in ["pe_ratio", "pb_ratio"]:
        if col in df.columns:
            valid = df[col].dropna()
            if len(valid) > 1:
                inverted = 1 / valid.clip(lower=0.01)
                col_min, col_max = inverted.min(), inverted.max()
                if col_max > col_min:
                    df[col + "_norm"] = (inverted - col_min) / (col_max - col_min)
                else:
                    df[col + "_norm"] = 0.5
            else:
                df[col + "_norm"] = 0.5

    norm_cols = [c for c in df.columns if c.endswith("_norm")]
    if norm_cols:
        df["value_score"] = df[norm_cols].mean(axis=1)
    else:
        df["value_score"] = 0.5

    return df.round(4)

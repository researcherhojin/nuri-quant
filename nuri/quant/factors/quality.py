"""퀄리티 팩터 — ROE, 영업이익률 기반 (fundamentals 테이블 read).

#349: 기존 구현은 `obb.equity.fundamental.ratios` 를 호출했으나 upstream #274 (`OBBject_EquityInfo`
ImportError) 로 silent 실패 → 전 종목 `quality_score = 0.5` 상수. fundamental.py 가 이미 수집한
`fundamentals` 테이블 (roe, operating_margin) 을 직접 읽도록 전환하여 아키텍처 일관성 회복
(STRATEGY §2.3 / §3.1).
"""
import logging

import pandas as pd

logger = logging.getLogger(__name__)


def compute_quality(tickers: list[str] | None = None, db_path=None) -> pd.DataFrame:
    """종목별 퀄리티 스코어 — fundamentals 테이블 기반."""
    from nuri.core.db import query

    if not tickers:
        from nuri.core.db import get_tickers
        tickers = [t for t in get_tickers() if not t.endswith(".KS")]

    if not tickers:
        return pd.DataFrame()

    # ticker 별 최신 row 만 조회 (latest per ticker)
    placeholders = ",".join("?" * len(tickers))
    rows = query(
        f"""
        SELECT f.ticker, f.roe, f.operating_margin
        FROM fundamentals f
        INNER JOIN (
            SELECT ticker, MAX(date) AS mx
            FROM fundamentals
            WHERE ticker IN ({placeholders})
            GROUP BY ticker
        ) latest ON f.ticker = latest.ticker AND f.date = latest.mx
        """,
        params=tuple(tickers),
        db_path=db_path,
    )

    scores: dict[str, dict] = {}
    for r in rows:
        ticker = r["ticker"]
        roe = r["roe"]
        margin = r["operating_margin"]
        if roe is None and margin is None:
            continue
        scores[ticker] = {
            "roe": float(roe) if roe is not None else None,
            "operating_margin": float(margin) if margin is not None else None,
        }

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

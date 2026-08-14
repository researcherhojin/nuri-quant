"""퀄리티 팩터 — ROE, 영업이익률 기반 (fundamentals 테이블 read).

#349: 기존 구현은 `obb.equity.fundamental.ratios` 를 호출했으나 upstream #274 (`OBBject_EquityInfo`
ImportError) 로 silent 실패 → 전 종목 `quality_score = 0.5` 상수. fundamental.py 가 이미 수집한
`fundamentals` 테이블 (roe, operating_margin) 을 직접 읽도록 전환하여 아키텍처 일관성 회복
(STRATEGY §2.3 / §3.1).
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def _normalize_quality_columns(df: pd.DataFrame) -> pd.DataFrame:
    """단일 시장 내 ROE/영업이익률 min-max 정규화 (높을수록 높은 퀄리티)."""
    for col in ["roe", "operating_margin"]:
        if col in df.columns:
            valid = df[col].dropna()
            if len(valid) > 1:
                col_min, col_max = valid.min(), valid.max()
                if col_max > col_min:
                    df[col + "_norm"] = (valid - col_min) / (col_max - col_min)
                else:
                    df[col + "_norm"] = 0.5
    return df


def compute_quality(tickers: list[str] | None = None, db_path=None) -> pd.DataFrame:
    """종목별 퀄리티 스코어 — fundamentals 테이블 기반."""
    from nuri.core.db import query

    if not tickers:
        from nuri.core.db import get_tickers

        # KR(.KS) 포함 — 정규화는 시장별로 분리한다 (#757). 과거엔 KR 을 제외해
        # composite 의 quality(25%) 가 KR 종목에서 flat 0.5 상수였다.
        tickers = get_tickers(db_path=db_path)

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

    # 시장별(.KS=KR vs US) 정규화 — ROE/영업이익률 baseline 이 시장마다 달라 cross-market
    # min-max 가 KR 종목을 왜곡한다. 각 시장 안에서만 정규화 (#757).
    is_kr = df.index.to_series().str.endswith(".KS")
    parts = [_normalize_quality_columns(sub.copy()) for sub in (df[is_kr], df[~is_kr]) if not sub.empty]
    df = pd.concat(parts)

    norm_cols = [c for c in df.columns if c.endswith("_norm")]
    if norm_cols:
        df["quality_score"] = df[norm_cols].mean(axis=1)
    else:
        df["quality_score"] = 0.5

    return df.round(4)

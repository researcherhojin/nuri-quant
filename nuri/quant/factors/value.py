"""가치 팩터 — PER, PBR 기반 (fundamentals 테이블 read).

#349: 기존 구현은 `obb.equity.fundamental.ratios` 를 호출했으나 upstream #274 (`OBBject_EquityInfo`
ImportError) 로 silent 실패 → 전 종목 `value_score = 0.5` 상수. fundamental.py 가 이미 수집한
`fundamentals` 테이블 (pe_ratio, price_to_book) 을 직접 읽도록 전환하여 아키텍처 일관성 회복
(STRATEGY §2.3 / §3.1).
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def _normalize_value_columns(df: pd.DataFrame) -> pd.DataFrame:
    """단일 시장 내 PE/PB 역수 min-max 정규화 (낮은 PE/PB = 높은 가치 스코어)."""
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
    return df


def compute_value(tickers: list[str] | None = None, db_path=None) -> pd.DataFrame:
    """종목별 가치 스코어 — fundamentals 테이블 기반. 낮은 PE/PB 가 높은 가치 스코어."""
    from nuri.core.db import query

    if not tickers:
        from nuri.core.db import get_tickers

        # KR(.KS) 포함 — 정규화는 시장별로 분리한다 (#757). 과거엔 KR 을 제외해
        # composite 의 value(25%) 가 KR 종목에서 flat 0.5 상수였다.
        tickers = get_tickers()

    if not tickers:
        return pd.DataFrame()

    placeholders = ",".join("?" * len(tickers))
    rows = query(
        f"""
        SELECT f.ticker, f.pe_ratio, f.price_to_book
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
        pe = r["pe_ratio"]
        pb = r["price_to_book"]
        if pe is None and pb is None:
            continue
        scores[ticker] = {
            "pe_ratio": float(pe) if pe is not None else None,
            "pb_ratio": float(pb) if pb is not None else None,
        }

    if not scores:
        return pd.DataFrame()

    df = pd.DataFrame(scores).T

    # 시장별(.KS=KR vs US) 정규화 — PE/PB baseline 이 시장마다 달라 cross-market min-max 는
    # 저PE 시장(KR)을 구조적 고가치로 왜곡한다. 각 시장 안에서만 정규화 (#757).
    is_kr = df.index.to_series().str.endswith(".KS")
    parts = [_normalize_value_columns(sub.copy()) for sub in (df[is_kr], df[~is_kr]) if not sub.empty]
    df = pd.concat(parts)

    norm_cols = [c for c in df.columns if c.endswith("_norm")]
    if norm_cols:
        df["value_score"] = df[norm_cols].mean(axis=1)
    else:  # pragma: no cover — pe/pb 둘 다 None 인 row 는 위에서 skip 됨, dict 키 항상 양쪽 존재
        df["value_score"] = 0.5

    return df.round(4)

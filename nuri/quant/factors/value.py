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
    """단일 시장 내 PE/PB **백분위** 정규화 (낮은 PE/PB = 높은 가치 스코어).

    ## 왜 min-max 가 아니라 백분위인가 (#1102)

    min-max 는 **양 끝값 2개에 앵커링**된다. PE/PBR 처럼 꼬리가 두꺼운 재무 비율에서는
    한 종목이 전체 척도를 정하고 나머지가 뭉개진다. 실측(2026-07-08 스냅샷, 유니버스
    확장 시뮬레이션): KR `pe_ratio_norm` 은 25종목이 1.0 에 고정되고 **나머지 194종목의
    중앙값이 0.00045** 였다. 변별력이 0 인 컬럼이다.

    앵커를 만든 건 이전 구현의 `1 / valid.clip(lower=0.01)` 이다. **음수 PE 는 0.01 로
    클립돼 역수 100** 이 되므로 그 시장의 최댓값이 되고, 적자기업이 정의상 `_norm == 1.0`
    = **가장 싼 종목**이 된다. 동시에 분모가 100 으로 벌어져 흑자기업 전부가 0 근처로
    압축된다. 두 시장이 서로의 실패를 가렸다 — US 는 음수 PE 가 0, KR 은 음수 PB 가 0
    이라 각자 다른 컬럼 하나씩만 죽어 있었다.

    백분위는 극단값이 순위 하나만 차지하므로 이 앵커링이 원천적으로 없고, 분포가 [0,1]
    에 균등해 **0.5 가 정의상 중앙값**이 된다 — `composite.py` 의 결측 중립값 대입이
    비로소 실제로 중립이다 (min-max 시절 0.5 는 92 백분위였다).

    비양수 PE/PB 는 **관측 불가**로 둔다(`NaN`). 적자기업은 "싼" 게 아니라 이 척도로
    잴 수 없는 것이고, 음수를 최저가로 취급하면 위 반전이 그대로 돌아온다.
    """
    for col in ["pe_ratio", "pb_ratio"]:
        if col in df.columns:
            # 비양수는 관측 불가 — dropna 가 아니라 where 로 걸러 **행 정렬을 유지**한다.
            valid = df[col].where(df[col] > 0)
            if valid.dropna().nunique() > 1:
                # 부호 반전으로 방향만 뒤집는다 (낮은 PE = 높은 점수). 미관측은 NaN 유지.
                df[col + "_norm"] = (-valid).rank(pct=True, na_option="keep")
            else:
                # 관측이 0~1개거나 전부 동값 — 순위를 매길 수 없다. 중립.
                df[col + "_norm"] = 0.5
    return df


def compute_value(tickers: list[str] | None = None, db_path=None) -> pd.DataFrame:
    """종목별 가치 스코어 — fundamentals 테이블 기반. 낮은 PE/PB 가 높은 가치 스코어."""
    from nuri.core.db import query

    if not tickers:
        from nuri.core.db import get_tickers

        # KR(.KS) 포함 — 정규화는 시장별로 분리한다 (#757). 과거엔 KR 을 제외해
        # composite 의 value(25%) 가 KR 종목에서 flat 0.5 상수였다.
        tickers = get_tickers(db_path=db_path)

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

    # 시장별(.KS=KR vs US) 정규화 — PE/PB baseline 이 시장마다 달라 cross-market 순위는
    # 저PE 시장(KR)을 구조적 고가치로 왜곡한다. 각 시장 안에서만 정규화 (#757).
    # 백분위로 바꿔도(#1102) 이 분리는 그대로 필요하다: 합쳐서 순위를 매기면 KR 이
    # 상위를 독식한다 — 척도만 바뀌었지 baseline 차이는 그대로다.
    is_kr = df.index.to_series().str.endswith(".KS")
    parts = [_normalize_value_columns(sub.copy()) for sub in (df[is_kr], df[~is_kr]) if not sub.empty]
    df = pd.concat(parts)

    norm_cols = [c for c in df.columns if c.endswith("_norm")]
    if norm_cols:
        # 미관측 측정치는 **그 척도의 중립값**으로 채운다 — 백분위 척도에서 중립값은
        # 정의상 0.5(중앙값)다. `skipna` 로 관측된 컬럼만 평균 내면 관측 1개짜리 종목의
        # 분산이 2개짜리의 2배가 되어 꼬리를 독점한다: 실측에서 ROE 결측 종목이 그
        # 이유만으로 quality 1.0 을 받아 확장 후 1위였다 (같은 원리, quality.py 참조).
        df["value_score"] = df[norm_cols].fillna(0.5).mean(axis=1)
    else:  # pragma: no cover — pe/pb 둘 다 None 인 row 는 위에서 skip 됨, dict 키 항상 양쪽 존재
        df["value_score"] = 0.5

    return df.round(4)

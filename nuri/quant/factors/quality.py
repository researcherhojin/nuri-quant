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
    """단일 시장 내 ROE/영업이익률 **백분위** 정규화 (높을수록 높은 퀄리티).

    ## min-max 가 아닌 이유 (#1102) — `value.py` 와 같은 병, 다른 증상

    극단값이 척도를 정한다. 실측(유니버스 확장 시뮬레이션): US `roe` 최댓값 84.57(MAS,
    자본잠식 종목의 산술 부산물) 대 최솟값 −1.19 로 범위가 85.76 이라, 정상적인 ROE
    0.153 이 **0.0156** 으로 정규화됐다 — US `roe_norm` 의 99.4% 가 [0, 0.1] 에 몰렸다.
    반대편에서 `operating_margin_norm` 은 MSTR 의 −44.0 이 최솟값이라 p50 이 0.977 이었다.
    거의-0 상수와 거의-1 상수의 평균은 **거의-0.5 상수** — #1102 의 증상이 유니버스를
    넓혀도 그대로 살아남는 경로다.

    ## 이전 구현의 두 번째 결함: `dropna()` 서브셋으로 대입

    `valid = df[col].dropna()` 로 만든 시리즈를 `df[col + "_norm"]` 에 대입하면 인덱스
    정렬 때문에 **결측 행에는 값이 아예 안 들어가고 NaN 이 남는다**. 그다음
    `df[norm_cols].mean(axis=1)` 이 기본 `skipna=True` 라, 그 종목은 살아남은 컬럼
    하나만으로 채점된다. 관측 1개의 평균은 관측 2개보다 분산이 2배라 꼬리를 독점한다:
    MO 는 ROE 가 없다는 이유만으로 영업이익률 단독 채점을 받아 `quality_score = 1.0000`
    이었고, ROE 가 실제로 있는 VICI 는 0.5035 였다. **결측이 곧 보너스**였고, 자본잠식
    종목 31개 중 27개가 ROE 결측이라 `value.py` 의 클립 보너스와 같은 종목에 겹쳐 쌓였다.

    그래서 여기서는 `where` 로 행 정렬을 유지하고, 중립값 대입은 평균 직전에 한 번만
    한다(`compute_quality`). 미관측은 그 척도의 중앙값 0.5 로 — 백분위라 그게 실제 중립이다.
    """
    for col in ["roe", "operating_margin"]:
        if col in df.columns:
            valid = df[col].astype(float)
            if valid.dropna().nunique() > 1:
                df[col + "_norm"] = valid.rank(pct=True, na_option="keep")
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
    # 순위가 KR 종목을 왜곡한다. 각 시장 안에서만 정규화 (#757, 백분위로 바꾼 #1102 이후도 동일).
    is_kr = df.index.to_series().str.endswith(".KS")
    parts = [_normalize_quality_columns(sub.copy()) for sub in (df[is_kr], df[~is_kr]) if not sub.empty]
    df = pd.concat(parts)

    norm_cols = [c for c in df.columns if c.endswith("_norm")]
    if norm_cols:
        # 미관측 측정치 → 그 척도의 중립값 0.5. `skipna` 로 관측된 것만 평균 내면
        # 결측이 보너스가 된다 (`_normalize_quality_columns` 참조).
        df["quality_score"] = df[norm_cols].fillna(0.5).mean(axis=1)
    else:
        df["quality_score"] = 0.5

    return df.round(4)

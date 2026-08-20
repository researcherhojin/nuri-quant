"""모멘텀 팩터 — 12개월 수익률, RSI, 52주 고점 근접도."""

import pandas as pd

from nuri.core.db import query_df

#: RSI 를 "현재값" 으로 인정하는 최대 나이 (일). `buy_candidate_emitter._get_rsi_snapshot`
#: 과 같은 값이다 (#1104) — 같은 테이블의 같은 컬럼을 읽는 두 소비자가 서로 다른 나이를
#: 현재로 치면, 같은 종목이 팩터에서는 신선하고 emitter 에서는 낡은 상태가 된다.
#: 낡은 RSI 를 쓰는 것과 없는 값을 중립 50 으로 치는 것 사이의 절충이고, 컷오프가 없으면
#: 상장폐지·수집중단 종목의 마지막 RSI 가 영원히 현재값 행세를 한다.
RSI_MAX_AGE_DAYS = 7


def _rsi_snapshot() -> dict[str, float]:
    """티커별 최신 RSI(14) — `RSI_MAX_AGE_DAYS` 보다 낡은 값은 버린다 (#1073).

    이전엔 루프 안에서 티커마다
    `SELECT rsi_14 FROM signals WHERE ticker = ? ORDER BY date DESC LIMIT 1` 을 돌렸다.
    **나이 제한이 없어서** `technical` 이 멈춘 종목의 마지막 RSI 가 무기한 현재값
    행세를 했다 — dev 스냅샷 실측(2026-08-14 기준): signals 를 가진 46종목 중 **29종목**이
    7일보다 낡았고, 가장 낡은 값은 **128일** 전이었다. 이 값은 모멘텀의 0.3 성분이고
    모멘텀은 다시 composite 의 0.30 이므로 BUY 점수의 9% 를 낡은 값이 만든다.

    전역 `MAX(date)` 하루치로 좁히지 않는 이유는 emitter 쪽과 같다: KR 은 KST 당일,
    US 는 전일로 signals 날짜가 갈라져 최신 하루만 고르면 한 시장이 통째로 빠진다.

    `rsi_14 IS NOT NULL` 이 여기서 새로 필요하다. 행이 하나면 pandas 가 NULL 을 객체
    `None` 으로 주지만(그래서 이전 코드는 우연히 안전했다), 여러 행을 한 번에 읽으면
    컬럼이 float64 가 되어 NULL 이 **NaN** 이 된다. `bool(nan) is True` 라 결측 검사를
    통과하고 NaN 이 momentum_score → composite_score 로 전파돼 NULL 로 저장된다.

    컷오프는 KST 로 계산해 파라미터로 넘긴다 — SQLite 의 `date('now')` 는 UTC 라 아침
    배치 시간대(09:00 KST 이전)에 하루 느슨해진다.
    """
    from datetime import timedelta

    from nuri.core.timezone import kst_now

    cutoff = (kst_now() - timedelta(days=RSI_MAX_AGE_DAYS)).strftime("%Y-%m-%d")
    df = query_df(
        """SELECT ticker, rsi_14, MAX(date) AS date FROM signals
           WHERE date >= ? AND rsi_14 IS NOT NULL
           GROUP BY ticker""",
        (cutoff,),
    )
    if df.empty:
        return {}
    return {str(row["ticker"]): float(row["rsi_14"]) for _, row in df.iterrows()}


def compute_momentum(tickers: list[str] | None = None) -> pd.DataFrame:
    """종목별 모멘텀 스코어 계산 (0~1 정규화)."""
    prices = query_df("SELECT ticker, date, close FROM prices ORDER BY date")
    if prices.empty:
        return pd.DataFrame()

    rsi_map = _rsi_snapshot()

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

        # RSI 기반 모멘텀 (signals 테이블에서). 없거나 낡았으면 중립 50.
        # `or 50` 이 아니라 `is None` 인 이유: RSI 0.0 은 falsy 라서 `or` 로 쓰면 실제
        # 관측값이 조용히 50 으로 덮인다 (이전 코드가 그랬다).
        rsi = rsi_map.get(ticker)
        if rsi is None:
            rsi = 50

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

    df["momentum_score"] = df["period_return_norm"] * 0.4 + df["rsi_14_norm"] * 0.3 + df["high_proximity_norm"] * 0.3

    return df[["period_return", "rsi_14", "high_proximity", "momentum_score"]].round(4)

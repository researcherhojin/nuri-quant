"""멀티팩터 합성 스코어 — 모멘텀(30%) + 가치(25%) + 퀄리티(25%) + 센티먼트(20%).

사용법:
    python -m nuri.quant.factors.composite
"""

import logging
from datetime import date

import numpy as np
import pandas as pd

from nuri.core.db import get_db, query
from nuri.core.rules import FACTOR_RULES
from nuri.core.timezone import today_kst

logger = logging.getLogger(__name__)

# 팩터 비중
WEIGHTS = {
    "momentum": 0.30,
    "value": 0.25,
    "quality": 0.25,
    "sentiment": 0.20,
}


# Fear & Greed 는 시장 지수라 주말·휴장일에 갱신되지 않는다 — VIX 와 같은 이유로
# 달력일이 아니라 영업일로 노후를 잰다 (`nuri/trading/recommend/vix_gate.py` 참조).
SENTIMENT_MAX_AGE_BUSINESS_DAYS = FACTOR_RULES.get("sentiment_max_age_business_days", 2)


def _market_sentiment() -> float | None:
    """Fear & Greed 0-1. 없거나 노후하면 **None** — 0.5 를 지어내지 않는다.

    과거엔 `else 0.5` 로 메웠다. 0.5 는 중립이라 무해해 보이지만, 실측 0.637 과
    비교하면 0-100 스케일에서 **2.74점** 차이고 `buy_signals.yaml` 의
    `quality_bar.base_threshold: 70` 앞에서 통과 개수를 움직인다. 즉 측정 실패가
    조용히 점수를 깎거나 올린다. 신선도 검사도 없어 수집기가 죽으면 옛 값이
    무기한 현재값 행세를 했다 (같은 구멍을 VIX 에서 #1017 로 고쳤다).
    """
    rows = query("SELECT date, value FROM macro WHERE indicator = 'fear_greed' ORDER BY date DESC LIMIT 1")
    if not rows:
        logger.warning("fear_greed 없음 — 센티먼트 성분 제외")
        return None
    try:
        observed = date.fromisoformat(str(rows[0]["date"])[:10])
        value = float(rows[0]["value"])
    except (ValueError, KeyError, TypeError):
        logger.warning("fear_greed 행이 깨졌음 — 센티먼트 성분 제외", exc_info=True)
        return None
    age = int(np.busday_count(observed, date.fromisoformat(today_kst())))
    if age > SENTIMENT_MAX_AGE_BUSINESS_DAYS:
        logger.warning("fear_greed 가 영업일 %d일 노후 — 센티먼트 성분 제외", age)
        return None
    return value / 100


def _effective_weights(fg_score: float | None) -> dict[str, float]:
    """센티먼트가 미상이면 그 비중을 나머지 3팩터에 **비례 재배분**한다.

    0.5 를 채워 넣는 대신 성분을 빼는 이유: 없는 관측을 지어내면 그 자체가 점수에
    기여한다. 재정규화하면 합계가 1.0 으로 유지돼 다른 티커·다른 날과 비교 가능하고,
    "센티먼트를 모른다" 가 점수를 위로도 아래로도 밀지 않는다.
    랭킹은 어차피 안 바뀐다(모든 티커에 같은 값) — 바뀌는 건 `quality_bar` 통과 개수다.
    """
    if fg_score is not None:
        return WEIGHTS
    rest = {k: v for k, v in WEIGHTS.items() if k != "sentiment"}
    total = sum(rest.values())
    return {**{k: v / total for k, v in rest.items()}, "sentiment": 0.0}


def compute_composite() -> pd.DataFrame:
    """멀티팩터 합성 스코어 계산."""
    from nuri.quant.factors.momentum import compute_momentum
    from nuri.quant.factors.quality import compute_quality
    from nuri.quant.factors.value import compute_value

    momentum = compute_momentum()
    value = compute_value()
    quality = compute_quality()

    # 센티먼트: Fear & Greed 기반 (전체 시장). 없으면 **지어내지 않고 뺀다** — 아래 참조.
    fg_score = _market_sentiment()
    weights = _effective_weights(fg_score)

    # 합산
    all_tickers = set()
    for df in [momentum, value, quality]:
        if not df.empty:
            all_tickers.update(df.index)

    results = []
    for ticker in sorted(all_tickers):
        m = momentum.loc[ticker, "momentum_score"] if ticker in momentum.index else 0.5
        v = value.loc[ticker, "value_score"] if ticker in value.index else 0.5
        q = quality.loc[ticker, "quality_score"] if ticker in quality.index else 0.5
        s = fg_score  # 시장 전체 센티먼트 (미상이면 None)

        composite = m * weights["momentum"] + v * weights["value"] + q * weights["quality"]
        if s is not None:
            composite += s * weights["sentiment"]

        results.append(
            {
                "ticker": ticker,
                "momentum_score": round(m, 4),
                "value_score": round(v, 4),
                "quality_score": round(q, 4),
                "sentiment_score": None if s is None else round(s, 4),
                "composite_score": round(composite, 4),
            }
        )

    df = pd.DataFrame(results).set_index("ticker").sort_values("composite_score", ascending=False)
    return df


def print_composite(df: pd.DataFrame) -> None:
    """팩터 스코어 출력."""
    if df.empty:
        print("팩터 데이터가 없습니다.")
        return

    print(f"\n{'=' * 70}")
    # 센티먼트가 빠진 실행에서 원래 비중을 찍으면 계산과 표기가 어긋난다.
    w = _effective_weights(None if df["sentiment_score"].isna().all() else 0.5)
    print(
        f"  멀티팩터 스코어 (M:{w['momentum'] * 100:.1f}% V:{w['value'] * 100:.1f}% "
        f"Q:{w['quality'] * 100:.1f}% S:{w['sentiment'] * 100:.1f}%)"
    )
    print(f"{'=' * 70}")
    print(f"  {'Ticker':<12} {'종합':>8} {'모멘텀':>8} {'가치':>8} {'퀄리티':>8} {'센티':>8}")
    print(f"  {'-' * 48}")
    for ticker, row in df.iterrows():
        print(
            f"  {ticker:<12} {row['composite_score']:>7.3f} "
            f"{row['momentum_score']:>7.3f} {row['value_score']:>7.3f} "
            f"{row['quality_score']:>7.3f} "
            f"{'   미상' if row['sentiment_score'] is None else format(row['sentiment_score'], '>7.3f')}"
        )
    print()


def save_composite(df: pd.DataFrame) -> int:
    """팩터 스코어를 factors 테이블에 멱등 저장 (date+ticker UNIQUE)."""
    if df.empty:
        return 0
    date = today_kst()
    rows = [
        {
            "ticker": ticker,
            "date": date,
            "momentum_score": row["momentum_score"],
            "value_score": row["value_score"],
            "quality_score": row["quality_score"],
            "sentiment_score": row["sentiment_score"],
            "composite_score": row["composite_score"],
        }
        for ticker, row in df.iterrows()
    ]
    with get_db() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO factors
               (ticker, date, momentum_score, value_score, quality_score, sentiment_score, composite_score)
               VALUES (:ticker, :date, :momentum_score, :value_score, :quality_score, :sentiment_score, :composite_score)""",
            rows,
        )
    logger.info(f"factors 테이블에 {len(rows)}건 저장")
    return len(rows)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    df = compute_composite()
    print_composite(df)
    save_composite(df)

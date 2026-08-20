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
    """멀티팩터 합성 스코어 계산.

    ## value/quality 도 **채점 대상 전체**에 대해 계산한다 (#1102)

    이전엔 `compute_value()` / `compute_quality()` 를 인자 없이 불렀다. 그 둘은 티커가
    없으면 `get_tickers()` = `SELECT DISTINCT ticker FROM portfolio` 로 떨어지므로
    **보유 18종목**만 계산됐고, 나머지는 아래 0.5 대입을 받았다. 실측(2026-07-08, 773종목):
    `value_score` 가 정확히 0.5 인 종목 **763**, `quality_score` 는 **766**. 센티먼트는
    시장 지수라 설계상 전 종목 동일하므로, 가중치 1.00 중 **0.70 이 종목 간 상수**였고
    순위를 만드는 건 momentum 0.30 하나였다. 항등식으로 확인된다 —
    `composite == 0.30 * momentum + 0.33692` 가 763/773 종목에서 오차 5e-5 이내로 성립한다.
    0.40 가중치짜리 "멀티팩터" 채널이 실은 두 번째 모멘텀 항이었다.

    유니버스는 momentum 의 인덱스를 그대로 쓴다. `config/universe.yaml` 을 따로 읽으면
    두 집합이 어긋나 (실측 23종목이 momentum 에만, 7종목이 yaml 에만) 그 차집합이 다시
    0.5 대입을 받는다. momentum 인덱스 = 실제로 채점될 종목이므로 **구성상 불일치가 0** 이다.
    """
    from nuri.quant.factors.momentum import compute_momentum
    from nuri.quant.factors.quality import compute_quality
    from nuri.quant.factors.value import compute_value

    momentum = compute_momentum()
    if momentum.empty:
        # 가격이 한 행도 없으면 채점할 대상이 없다. 여기서 끊지 않으면 아래 두 호출이
        # 빈 리스트를 받고, 그 둘은 falsy 인자를 "미지정" 으로 보아 **보유 종목으로
        # 되돌아간다** — 고치려던 바로 그 경로다.
        return pd.DataFrame()

    universe = list(momentum.index)
    value = compute_value(tickers=universe)
    quality = compute_quality(tickers=universe)

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
        # 0.5 대입은 **백분위 정규화 이후에야** 중립이다 (#1102). min-max 시절 확장된
        # value 분포의 중앙값은 0.0923 이라 0.5 는 92 백분위였다 — fundamentals 가 없다는
        # 이유만으로 상위 8% 에 앉았다. 백분위 척도에서는 0.5 가 정의상 중앙값이다.
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


def _market_as_of() -> str | None:
    """이 스냅샷이 근거한 **시장 데이터 날짜** (없으면 None).

    `factors.date` 는 쓴 날이 아니라 **재료의 날짜**여야 한다. 잡이 매일 08:10 에 도는데
    `today_kst()` 를 찍으면 주말·휴장에도 금요일 종가로 계산한 행이 "당일" 라벨을 달고
    들어간다. 그러면 신선도 정책이 낡음을 잡는 게 아니라 **세탁한다** — 가격 수집이
    멈춰도 파생 테이블은 매일 갱신돼 PASS 로 보이고, 그 사이 가중치 0.40 짜리 입력이
    옛 가격으로 BUY 점수를 만든다 (#1071 Codex P1).

    시장일로 찍으면 주말 실행은 금요일 행을 **덮어쓰기만** 하므로(멱등, date+ticker
    UNIQUE) 가짜 신선도가 생기지 않고, 소비자의 `MAX(date)` 는 그대로 최신을 집는다.
    """
    rows = query("SELECT MAX(date) AS d FROM prices")
    return dict(rows[0])["d"] if rows else None


def save_composite(df: pd.DataFrame, as_of: str | None = None) -> int:
    """팩터 스코어를 factors 테이블에 멱등 저장 (date+ticker UNIQUE).

    `as_of` 미지정 시 시장 데이터 날짜(`_market_as_of`)를 쓴다. 가격이 한 행도 없으면
    계산 자체가 비어 있어 여기 도달하지 않지만, 방어적으로 `today_kst()` 로 떨어진다.
    """
    if df.empty:
        return 0
    date = as_of or _market_as_of() or today_kst()
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

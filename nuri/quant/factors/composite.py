"""멀티팩터 합성 스코어 — 모멘텀(30%) + 가치(25%) + 퀄리티(25%) + 센티먼트(20%).

사용법:
    python -m nuri.quant.factors.composite
"""
import logging

import pandas as pd

from nuri.db import query, query_df

logger = logging.getLogger(__name__)

# 팩터 비중
WEIGHTS = {
    "momentum": 0.30,
    "value": 0.25,
    "quality": 0.25,
    "sentiment": 0.20,
}


def compute_composite() -> pd.DataFrame:
    """멀티팩터 합성 스코어 계산."""
    from nuri.quant.factors.momentum import compute_momentum
    from nuri.quant.factors.value import compute_value
    from nuri.quant.factors.quality import compute_quality

    momentum = compute_momentum()
    value = compute_value()
    quality = compute_quality()

    # 센티먼트: Fear & Greed 기반 (전체 시장)
    fg_rows = query(
        "SELECT value FROM macro WHERE indicator = 'fear_greed' ORDER BY date DESC LIMIT 1"
    )
    fg_score = (fg_rows[0]["value"] / 100) if fg_rows else 0.5

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
        s = fg_score  # 시장 전체 센티먼트

        composite = (
            m * WEIGHTS["momentum"] +
            v * WEIGHTS["value"] +
            q * WEIGHTS["quality"] +
            s * WEIGHTS["sentiment"]
        )

        results.append({
            "ticker": ticker,
            "momentum_score": round(m, 4),
            "value_score": round(v, 4),
            "quality_score": round(q, 4),
            "sentiment_score": round(s, 4),
            "composite_score": round(composite, 4),
        })

    df = pd.DataFrame(results).set_index("ticker").sort_values("composite_score", ascending=False)
    return df


def print_composite(df: pd.DataFrame) -> None:
    """팩터 스코어 출력."""
    if df.empty:
        print("팩터 데이터가 없습니다.")
        return

    print(f"\n{'=' * 70}")
    print(f"  멀티팩터 스코어 (M:{WEIGHTS['momentum']*100:.0f}% V:{WEIGHTS['value']*100:.0f}% "
          f"Q:{WEIGHTS['quality']*100:.0f}% S:{WEIGHTS['sentiment']*100:.0f}%)")
    print(f"{'=' * 70}")
    print(f"  {'Ticker':<12} {'종합':>8} {'모멘텀':>8} {'가치':>8} {'퀄리티':>8} {'센티':>8}")
    print(f"  {'-' * 48}")
    for ticker, row in df.iterrows():
        print(f"  {ticker:<12} {row['composite_score']:>7.3f} "
              f"{row['momentum_score']:>7.3f} {row['value_score']:>7.3f} "
              f"{row['quality_score']:>7.3f} {row['sentiment_score']:>7.3f}")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    df = compute_composite()
    print_composite(df)

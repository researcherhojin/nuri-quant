"""
상관관계 분석 — 종목 간 상관계수 계산 및 고상관 쌍 경고.

|상관계수| > 0.80 경고.

사용법:
    python -m nuri.analysis.correlation
"""
import logging
from pathlib import Path

import pandas as pd

from nuri.core.db import get_tickers, query_df

logger = logging.getLogger(__name__)

EXPORT_DIR = Path(__file__).parent.parent.parent / "data" / "exports"


def analyze_correlation(min_days: int = 60) -> tuple[pd.DataFrame, list[dict]]:
    """종목 간 상관관계 분석. (상관행렬, 경고목록) 반환."""
    tickers = get_tickers()
    if len(tickers) < 2:
        return pd.DataFrame(), []

    # 종목별 종가 피벗 테이블
    prices = query_df("SELECT ticker, date, close FROM prices ORDER BY date")
    pivot = prices.pivot_table(index="date", columns="ticker", values="close")

    # 최소 데이터 요구
    valid_tickers = [t for t in pivot.columns if pivot[t].dropna().shape[0] >= min_days]
    if len(valid_tickers) < 2:
        logger.warning(f"상관관계 분석 불가: {min_days}일 이상 데이터가 있는 종목 부족")
        return pd.DataFrame(), []

    pivot = pivot[valid_tickers]

    # 일간 수익률 → 상관행렬
    returns = pivot.ffill().pct_change().dropna()
    corr_matrix = returns.corr()

    # 고상관 경고 (|r| > 0.80)
    warnings = []
    n = len(valid_tickers)
    for i in range(n):
        for j in range(i + 1, n):
            r = corr_matrix.iloc[i, j]
            if abs(r) > 0.80:
                warnings.append({
                    "ticker_a": valid_tickers[i],
                    "ticker_b": valid_tickers[j],
                    "correlation": round(r, 3),
                })

    return corr_matrix, warnings


def save_heatmap(corr_matrix: pd.DataFrame) -> None:
    """상관관계 히트맵 저장."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import seaborn as sns

        EXPORT_DIR.mkdir(parents=True, exist_ok=True)

        fig, ax = plt.subplots(figsize=(12, 10))
        sns.heatmap(
            corr_matrix, annot=True, fmt=".2f",
            cmap="RdYlGn_r", center=0, vmin=-1, vmax=1,
            ax=ax, square=True,
        )
        ax.set_title("Nuri-Quant Portfolio Correlation Matrix")
        fig.tight_layout()
        fig.savefig(EXPORT_DIR / "correlation.png", dpi=150)
        plt.close(fig)
        logger.info(f"히트맵 저장: {EXPORT_DIR / 'correlation.png'}")
    except Exception as e:
        logger.warning(f"히트맵 생성 실패: {e}")


def print_correlation(corr_matrix: pd.DataFrame, warnings: list[dict]) -> None:
    """상관관계 분석 결과 출력."""
    if corr_matrix.empty:
        print("상관관계 데이터가 없습니다.")
        return

    print(f"\n{'=' * 60}")
    print(f"  상관관계 분석 ({len(corr_matrix)}종목)")
    print(f"{'=' * 60}")

    if warnings:
        print("\n  ⚠️ 고상관 쌍 (|r| > 0.80):")
        for w in warnings:
            print(f"    {w['ticker_a']} ↔ {w['ticker_b']}: {w['correlation']:.3f}")
    else:
        print("  ✅ 고상관 쌍 없음 (분산 양호)")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    corr, warns = analyze_correlation()
    print_correlation(corr, warns)
    if not corr.empty:
        save_heatmap(corr)

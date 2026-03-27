"""
D-3: 레짐 → 전략 매핑 — 시장 국면별 추천 전략.

C-1 시그널 백테스트 결과에 레짐 라벨을 붙여서
"어떤 레짐에서 어떤 시그널이 실제로 잘 먹히는지" 데이터로 검증한다.
데이터가 없으면 보수적 규칙 기반 폴백 사용.

사용법:
    python -m nuri.regime.strategy_map
    python -m nuri.regime.strategy_map --analyze   # 시그널×레짐 교차분석
"""
import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from nuri.quant.regime.classifier import (
    RegimeState,
    _classify_single,
    _get_vix,
    _load_spy_series,
    classify_regime,
    compute_dynamic_thresholds,
)
from nuri.quant.regime.macro_score import MacroScore, compute_macro_score

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).parent.parent.parent.parent / "data" / "reports"

# 섹터 → ETF 매핑 (portfolio.yaml의 sector 값 기준)
SECTOR_TO_ETF = {
    "Technology": "XLK",
    "Consumer Discretionary": "XLY",
    "Communication Services": "XLC",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Industrials": "XLI",
    "Consumer Staples": "XLP",
    "Utilities": "XLU",
    "Energy": "XLE",
    "Materials": "XLB",
    "Real Estate": "XLRE",
}

# 방어 섹터 / 공격 섹터 분류
DEFENSIVE_SECTORS = {"XLP", "XLU", "XLV", "XLRE"}
GROWTH_SECTORS = {"XLK", "XLY", "XLC"}

# 포지션 사이징 규칙 (레짐 trend × volatility)
POSITION_RULES = {
    ("bull", "low"): "aggressive",
    ("bull", "high"): "normal",
    ("sideways", "low"): "normal",
    ("sideways", "high"): "defensive",
    ("bear", "low"): "defensive",
    ("bear", "high"): "minimal",
}

# 섹터 선호 규칙
SECTOR_RULES = {
    "aggressive": list(GROWTH_SECTORS),
    "normal": list(GROWTH_SECTORS | {"XLV", "XLI"}),
    "defensive": list(DEFENSIVE_SECTORS),
    "minimal": ["XLP", "XLU"],
}

# PF 1.0 이하 = 비추천, PF 1.5 이상 = 추천
PF_RECOMMEND_THRESHOLD = 1.5
PF_AVOID_THRESHOLD = 1.0


@dataclass
class StrategyRecommendation:
    """레짐별 전략 추천."""
    regime: str
    macro_interpretation: str
    position_sizing: str
    recommended_signals: list[str]
    avoid_signals: list[str]
    sector_preference: list[str]
    signal_regime_stats: dict       # 시그널별 레짐 내 실제 성과
    notes: str


# ═══════════════════════════════════════════════════════
# R3: 시그널 × 레짐 교차분석
# ═══════════════════════════════════════════════════════


def analyze_signal_by_regime(db_path=None) -> pd.DataFrame:
    """C-1 시그널 결과 각 거래에 레짐 라벨을 붙여 교차분석.

    Returns:
        DataFrame: signal_id, regime, trades, win_rate, avg_return, profit_factor
    """
    # C-1 signal_results.csv 로드
    results_csv = _find_latest_csv("signal_results.csv")
    if results_csv is None:
        return pd.DataFrame()

    trades = pd.read_csv(results_csv)
    if trades.empty:
        return pd.DataFrame()

    # SPY 시계열 + 임계값 로드 (레짐 라벨링용)
    spy_df = _load_spy_series(db_path=db_path)
    if spy_df is None or spy_df.empty:
        return pd.DataFrame()

    thresholds = compute_dynamic_thresholds(db_path)

    # SPY date → 레짐 매핑 테이블 구축 (매 거래일)
    spy_df = spy_df.dropna(subset=["sma50", "sma200"])
    date_to_regime = {}
    for _, row in spy_df.iterrows():
        vix = _get_vix(date=row["date"], db_path=db_path)
        bb_w = float(row["bb_width"]) if pd.notna(row["bb_width"]) else 0
        trend, vol = _classify_single(
            row["close"], row["sma50"], row["sma200"],
            vix, bb_w, thresholds,
        )
        date_to_regime[row["date"]] = f"{trend}_{vol}_vol"

    # 각 거래에 레짐 라벨 붙이기
    trades["regime"] = trades["entry_date"].map(date_to_regime)
    trades = trades.dropna(subset=["regime"])

    if trades.empty:
        return pd.DataFrame()

    # 시그널 × 레짐 집계
    results = []
    for (sig, regime), group in trades.groupby(["signal_id", "regime"]):
        returns = group["return_pct"]
        wins = (returns > 0).sum()
        total_gain = returns[returns > 0].sum()
        total_loss = abs(returns[returns < 0].sum())
        pf = total_gain / total_loss if total_loss > 0 else float("inf")

        results.append({
            "signal_id": sig,
            "regime": regime,
            "trades": len(group),
            "win_rate": round(wins / len(group), 3),
            "avg_return": round(float(returns.mean()), 2),
            "profit_factor": round(pf, 2) if pf != float("inf") else 99.99,
        })

    return pd.DataFrame(results).sort_values(["regime", "profit_factor"], ascending=[True, False])


def _find_latest_csv(filename: str) -> Path | None:
    """가장 최근 report 디렉토리에서 CSV 찾기."""
    if not REPORT_DIR.exists():
        return None
    for d in sorted(REPORT_DIR.iterdir(), reverse=True):
        candidate = d / filename
        if candidate.exists():
            return candidate
    return None


# ═══════════════════════════════════════════════════════
# 전략 매핑
# ═══════════════════════════════════════════════════════


def _build_data_driven_strategy(regime: str, cross_df: pd.DataFrame) -> dict:
    """교차분석 데이터에서 특정 레짐의 추천/비추천 시그널 도출."""
    regime_data = cross_df[cross_df["regime"] == regime]

    if regime_data.empty:
        return {"recommended": [], "avoid": [], "stats": {}}

    # 최소 5건 이상인 시그널만 신뢰
    reliable = regime_data[regime_data["trades"] >= 5]

    if reliable.empty:
        return {"recommended": [], "avoid": [], "stats": {}}

    recommended = reliable[reliable["profit_factor"] >= PF_RECOMMEND_THRESHOLD]["signal_id"].tolist()
    avoid = reliable[reliable["profit_factor"] <= PF_AVOID_THRESHOLD]["signal_id"].tolist()

    stats = {
        row["signal_id"]: {
            "win_rate": row["win_rate"],
            "pf": row["profit_factor"],
            "trades": row["trades"],
            "avg_return": row["avg_return"],
        }
        for _, row in reliable.iterrows()
    }

    return {"recommended": recommended, "avoid": avoid, "stats": stats}


def map_regime_to_strategy(
    regime_state: RegimeState | None = None,
    macro_score: MacroScore | None = None,
    db_path=None,
) -> StrategyRecommendation | None:
    """현재 레짐에 맞는 전략 추천 (데이터 기반 + 규칙 폴백)."""
    if regime_state is None:
        regime_state = classify_regime(db_path=db_path)
    if regime_state is None:
        return None

    if macro_score is None:
        macro_score = compute_macro_score(db_path=db_path)

    regime = regime_state.regime
    trend = regime_state.trend
    vol = regime_state.volatility

    # 기본 포지션 사이징 (규칙 기반)
    position = POSITION_RULES.get((trend, vol), "defensive")

    # 교차분석 데이터 시도
    cross_df = analyze_signal_by_regime(db_path)
    data_strategy = _build_data_driven_strategy(regime, cross_df)

    recommended = data_strategy["recommended"]
    avoid = data_strategy["avoid"]
    stats = data_strategy["stats"]
    notes_parts = []

    if recommended:
        notes_parts.append(f"데이터 검증: {len(recommended)}개 시그널 PF>{PF_RECOMMEND_THRESHOLD}")
    else:
        # 데이터 부족 시 보수적 폴백
        if trend == "bull":
            recommended = ["rsi_oversold", "bb_bounce", "macd_golden"]
            avoid = ["macd_dead", "sma_dead"]
        elif trend == "bear":
            recommended = ["rsi_overbought", "macd_dead"]
            avoid = ["macd_golden", "sma_golden"]
        else:
            recommended = ["rsi_oversold", "bb_bounce"]
            avoid = ["sma_golden", "sma_dead"]
        notes_parts.append("데이터 부족 → 규칙 기반 폴백")

    # high vol에서는 추천 시그널 축소
    if vol == "high" and len(recommended) > 2:
        # PF 상위 2개만 유지
        if stats:
            ranked = sorted(recommended, key=lambda s: stats.get(s, {}).get("pf", 0), reverse=True)
            recommended = ranked[:2]
        else:
            recommended = recommended[:2]
        notes_parts.append("고변동성: 상위 시그널만 유지")

    # minimal에서는 추천 시그널 비움
    if position == "minimal":
        recommended = []
        notes_parts.append("최소 포지션: 시그널 매매 자제")

    # 섹터 선호
    sectors = SECTOR_RULES.get(position, list(DEFENSIVE_SECTORS))

    # 매크로 스코어 보정
    if macro_score.total_score < 30 and position in ("aggressive", "normal"):
        position = "defensive"
        sectors = SECTOR_RULES["defensive"]
        notes_parts.append("매크로 악화로 방어 전환")
    elif macro_score.total_score > 70 and position == "defensive":
        position = "normal"
        sectors = SECTOR_RULES["normal"]
        notes_parts.append("매크로 양호: 방어 완화")

    return StrategyRecommendation(
        regime=regime,
        macro_interpretation=macro_score.interpretation,
        position_sizing=position,
        recommended_signals=recommended,
        avoid_signals=avoid,
        sector_preference=sectors,
        signal_regime_stats=stats,
        notes="; ".join(notes_parts),
    )


def print_strategy(rec: StrategyRecommendation | None) -> None:
    if rec is None:
        print("전략 추천 불가 (데이터 부족)")
        return

    pos_labels = {
        "aggressive": "AGGRESSIVE (공격적)",
        "normal": "NORMAL (보통)",
        "defensive": "DEFENSIVE (방어적)",
        "minimal": "MINIMAL (최소)",
    }

    print(f"\n{'=' * 65}")
    print("  Strategy Recommendation")
    print(f"{'=' * 65}")
    print(f"  Regime:       {rec.regime}")
    print(f"  Macro:        {rec.macro_interpretation}")
    print(f"  Position:     {pos_labels.get(rec.position_sizing, rec.position_sizing)}")
    print(f"  Signals USE:  {', '.join(rec.recommended_signals) or '없음'}")
    print(f"  Signals AVOID:{', '.join(rec.avoid_signals) or '없음'}")
    print(f"  Sectors:      {', '.join(rec.sector_preference)}")
    print(f"  Notes:        {rec.notes}")

    if rec.signal_regime_stats:
        print(f"\n  --- Signal Performance in {rec.regime} ---")
        print(f"  {'Signal':<18} {'Trades':>6} {'WR':>6} {'PF':>6} {'AvgRet':>8}")
        print(f"  {'-' * 46}")
        for sig, st in sorted(rec.signal_regime_stats.items(), key=lambda x: x[1]["pf"], reverse=True):
            print(f"  {sig:<18} {st['trades']:>6} {st['win_rate']:>5.0%} "
                  f"{st['pf']:>5.1f} {st['avg_return']:>+7.1f}%")

    print()


def print_cross_analysis(df: pd.DataFrame) -> None:
    """교차분석 출력."""
    if df.empty:
        print("교차분석 데이터 없음 (C-1 signal_results.csv 필요)")
        return

    print(f"\n{'=' * 75}")
    print("  Signal × Regime Cross-Analysis")
    print(f"{'=' * 75}")

    for regime in sorted(df["regime"].unique()):
        rdf = df[df["regime"] == regime].sort_values("profit_factor", ascending=False)
        print(f"\n  [{regime}]")
        print(f"  {'Signal':<18} {'Trades':>6} {'WR':>6} {'PF':>6} {'AvgRet':>8}")
        print(f"  {'-' * 46}")
        for _, row in rdf.iterrows():
            pf_str = f"{row['profit_factor']:.1f}" if row["profit_factor"] < 99 else "∞"
            print(f"  {row['signal_id']:<18} {row['trades']:>6} {row['win_rate']:>5.0%} "
                  f"{pf_str:>6} {row['avg_return']:>+7.1f}%")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Nuri-Quant 레짐별 전략 추천")
    parser.add_argument("--analyze", action="store_true", help="시그널×레짐 교차분석 출력")
    args = parser.parse_args()

    if args.analyze:
        cross = analyze_signal_by_regime()
        print_cross_analysis(cross)
    else:
        from nuri.quant.regime.classifier import print_regime
        from nuri.quant.regime.macro_score import print_macro_score

        regime = classify_regime()
        print_regime(regime)

        macro = compute_macro_score()
        print_macro_score(macro)

        rec = map_regime_to_strategy(regime, macro)
        print_strategy(rec)

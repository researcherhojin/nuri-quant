"""시그널 후보 + 스코어카드 API."""
from dataclasses import asdict

from fastapi import APIRouter, Query

router = APIRouter(tags=["signals"])


@router.get("/candidates")
def get_candidates(days: int = Query(5, ge=1, le=30)):
    """시그널 기반 매매 후보."""
    from nuri.trading.recommend.candidates import screen_candidates
    candidates = screen_candidates(lookback_days=days)
    return {
        "candidates": [asdict(c) for c in candidates],
        "count": len(candidates),
        "buy": len([c for c in candidates if c.direction == "BUY" and c.regime_fit]),
        "sell": len([c for c in candidates if c.direction == "SELL" and c.regime_fit]),
    }


@router.get("/scorecard")
def get_scorecard():
    """시그널 스코어카드 (최신 CSV)."""
    from pathlib import Path

    import pandas as pd

    report_dir = Path(__file__).parent.parent.parent.parent / "data" / "reports"
    if not report_dir.exists():
        return {"error": "report 디렉토리 없음"}

    for d in sorted(report_dir.iterdir(), reverse=True):
        csv = d / "signal_scorecard.csv"
        if csv.exists():
            df = pd.read_csv(csv)
            total = df[df["ticker"].isna()].drop(columns=["ticker"])
            return {
                "scorecard": total.to_dict(orient="records"),
                "date": d.name,
            }

    return {"error": "signal_scorecard.csv 없음 (make validate 먼저 실행)"}


@router.get("/cross-analysis")
def get_cross_analysis():
    """시그널 × 레짐 교차분석."""
    from nuri.quant.regime.strategy_map import analyze_signal_by_regime
    df = analyze_signal_by_regime()
    if df.empty:
        return {"error": "교차분석 데이터 없음"}
    return {"data": df.to_dict(orient="records")}

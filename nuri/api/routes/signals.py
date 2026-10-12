"""시그널 후보 + 스코어카드 API."""

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query

from nuri.api.limits import heavy_slot

router = APIRouter(tags=["signals"])


@router.get("/candidates", dependencies=[Depends(heavy_slot)])
def get_candidates(days: int = Query(5, ge=1, le=30)):
    """시그널 기반 매매 후보. buy/sell 카운트는 actionable tier 만 (B-2-ext)."""
    from nuri.trading.recommend.candidates import TIER_ACTIONABLE, screen_candidates

    candidates = screen_candidates(lookback_days=days)
    actionable = [c for c in candidates if c.tier == TIER_ACTIONABLE and c.regime_fit]
    return {
        "candidates": [asdict(c) for c in candidates],
        "count": len(candidates),
        "buy": sum(1 for c in actionable if c.direction == "BUY"),
        "sell": sum(1 for c in actionable if c.direction == "SELL"),
    }


@router.get("/scorecard")
def get_scorecard():
    """시그널 스코어카드 (최신 CSV)."""
    import math
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
            # NaN·±inf → None (JSON 직렬화 호환). 값마다 판정한다 — 프레임 단위 replace/where 는 dtype 에
            # 따라 결과가 달라서, inf 가 없는 float 컬럼의 NaN 을 그대로 남겼다 (#1829).
            records = [
                {k: None if isinstance(v, float) and not math.isfinite(v) else v for k, v in row.items()}
                for row in total.to_dict(orient="records")
            ]
            return {
                "scorecard": records,
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

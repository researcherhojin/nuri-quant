"""상대강도(RS) + 거래대금 leadership 팩터 (P2 shadow).

"돈이 몰리는 리더" 측정: cross-sectional RS percentile(trailing 수익률 순위) +
거래대금(close×volume) surge. prices 테이블만 사용 (신규 수집 없음).

규율:
- 120d 히스토리 floor: lookback 미만 종목은 제외 (짧은 히스토리로 랭킹 왜곡 방지).
- KR/US 동일 lookback: 데이터 가용성이 아닌 strength 를 랭킹한다. RS percentile(수익률
  순위)·거래대금 surge(비율) 모두 통화-무관 → KR/US 직접 비교 가능.
- crowding 가드는 점수화 단계(_score_ticker)에서 적용 — 완만한 거래대금 확장은 보상,
  과열(parabolic) 추격은 페널티. 이 모듈은 raw surge 비율만 산출.

shadow: buy_candidate_emitter 에 weight=0 으로 편입 → 라이브 점수 무변경, sources 노출만.
승격(weight>0)은 P1 walk-forward 통과 후 별도 STRATEGY PR.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from nuri.core.db import query_df

_EMPTY = pd.DataFrame(columns=["rs_percentile", "dollar_volume_surge"])


def compute_leadership(
    lookback: int = 120,
    surge_window: int = 20,
    db_path: Optional[Path] = None,
) -> pd.DataFrame:
    """종목별 RS percentile + 거래대금 surge.

    Args:
        lookback: RS 수익률 + 거래대금 baseline 기간 (영업일). 120d floor 겸용.
        surge_window: 최근 거래대금 평균 구간 (영업일).

    Returns:
        ticker-indexed DataFrame:
          rs_percentile (0~100): trailing-`lookback` 수익률의 cross-sectional 순위
          dollar_volume_surge (배): 최근 surge_window 거래대금 평균 / lookback 평균
        조건 미달(데이터 부족) 시 빈 DataFrame.
    """
    prices = query_df("SELECT ticker, date, close, volume FROM prices ORDER BY date", db_path=db_path)
    if prices.empty:
        return _EMPTY.copy()

    close = prices.pivot_table(index="date", columns="ticker", values="close").sort_index()
    vol = prices.pivot_table(index="date", columns="ticker", values="volume").sort_index()
    if close.shape[0] < lookback:
        return _EMPTY.copy()

    # 120d floor: lookback 이상 non-NaN close 보유 종목만 (KR/US 동일 기준)
    enough = [t for t in close.columns if close[t].notna().sum() >= lookback]
    if not enough:
        return _EMPTY.copy()
    close = close[enough].ffill()
    vol = vol[enough].ffill()

    # RS: trailing-lookback 수익률의 cross-sectional percentile (통화-무관)
    trailing_ret = close.iloc[-1] / close.iloc[-lookback] - 1.0
    rs_pct = trailing_ret.rank(pct=True) * 100.0

    # 거래대금 surge: 최근 surge_window 평균 / lookback 평균 (비율 → 통화-무관)
    dollar_vol = close * vol
    dv_recent = dollar_vol.iloc[-surge_window:].mean()
    dv_base = dollar_vol.iloc[-lookback:].mean()
    surge = (dv_recent / dv_base).replace([np.inf, -np.inf], np.nan).fillna(1.0)

    out = pd.DataFrame({"rs_percentile": rs_pct.round(2), "dollar_volume_surge": surge.round(3)})
    return out.dropna(subset=["rs_percentile"])


def leadership_snapshot(
    lookback: int = 120,
    surge_window: int = 20,
    db_path: Optional[Path] = None,
) -> dict[str, tuple[float, float]]:
    """compute_leadership → {ticker: (rs_percentile, dollar_volume_surge)} 룩업 맵."""
    df = compute_leadership(lookback, surge_window, db_path=db_path)
    if df.empty:
        return {}
    return {str(t): (float(r["rs_percentile"]), float(r["dollar_volume_surge"])) for t, r in df.iterrows()}

# pyright: reportArgumentType=false, reportCallIssue=false
"""증거 차트 데이터 — 단일 소스 (#1224 U5a-1).

Plotly HTML 생성기(`evidence_charts.py`, 리포트 아카이브용)와 대시보드의
`/api/evidence/data/{chart_id}` JSON API 가 **같은 조회·조립을 공유**한다.
이전에는 생성기 안에 쿼리가 인라인이라 네이티브 차트를 만들면 두 벌이 되어
드리프트가 필연이었다.

함수들은 DataFrame/list 를 반환한다 — JSON 직렬화는 API 레이어(`routes/evidence.py`)
몫. db_path 는 받은 값을 모든 DB 리더에 그대로 전달한다 (invariants.md).
"""

import logging
from pathlib import Path

import pandas as pd

from nuri.core.db import query_df

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).parent.parent.parent / "data" / "reports"


# ═══ 1. 레짐: SPY + SMA + VIX ══════════════════════════════════


def load_spy_with_sma(db_path=None, limit: int = 252) -> pd.DataFrame:
    """SPY OHLCV 1년 + SMA50/200. 빈 DataFrame 이면 데이터 없음."""
    spy = query_df(
        f"SELECT date, open, high, low, close, volume FROM prices WHERE ticker='SPY' ORDER BY date DESC LIMIT {int(limit)}",
        db_path=db_path,
    )
    if spy.empty:
        return spy
    spy = spy.sort_values("date").reset_index(drop=True)
    spy["date"] = pd.to_datetime(spy["date"])
    spy["sma50"] = spy["close"].rolling(50).mean()
    spy["sma200"] = spy["close"].rolling(200).mean()
    return spy


def load_vix_history(db_path=None, limit: int = 252) -> pd.DataFrame:
    """VIX 히스토리 (macro 테이블). 빈 DataFrame 허용."""
    vix = query_df(
        f"SELECT date, value FROM macro WHERE indicator='vix' ORDER BY date DESC LIMIT {int(limit)}",
        db_path=db_path,
    )
    if vix.empty:
        return vix
    vix = vix.sort_values("date").reset_index(drop=True)
    vix["date"] = pd.to_datetime(vix["date"])
    return vix


# ═══ 2. 포트폴리오 히트맵 ══════════════════════════════════════


def load_portfolio_grouped(db_path=None) -> pd.DataFrame:
    """종목별 합산(가치·손익·비중·섹터) + 위반 판정 컬럼.

    violation ∈ {"stop_loss", "overweight", None} — 판정 기준은 config/rules.yaml
    (PORTFOLIO_STOP / MAX_SINGLE_POSITION). 손절 위반이 비중 위반보다 우선한다
    (기존 생성기 동작 유지).
    """
    from nuri.analysis.portfolio import analyze_portfolio

    df = analyze_portfolio(db_path=db_path)
    if df.empty:
        return df

    from nuri.core.rules import MAX_SINGLE_POSITION, PORTFOLIO_STOP

    grouped = (
        df.groupby("ticker")
        .agg(
            {
                "current_value_usd": "sum",
                "pnl_pct": "mean",
                "weight_pct": "sum",
                "sector": "first",
            }
        )
        .reset_index()
    )

    def _violation(row) -> str | None:
        if row["pnl_pct"] <= PORTFOLIO_STOP:
            return "stop_loss"
        if row["weight_pct"] > MAX_SINGLE_POSITION * 100:
            return "overweight"
        return None

    grouped["violation"] = grouped.apply(_violation, axis=1)
    return grouped


# ═══ 3. 시그널 성과 (scorecard + drift) ════════════════════════


def load_latest_scorecard() -> pd.DataFrame | None:
    """최신 signal_scorecard.csv 로드 (evidence_charts 에서 이동, #1224)."""
    if not REPORT_DIR.exists():
        return None
    for d in sorted(REPORT_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        csv_path = d / "signal_scorecard.csv"
        if csv_path.exists():
            return pd.read_csv(csv_path)
    return None


def load_drift_map(db_path=None) -> dict[str, dict]:
    """Learning Memory 시그널별 드리프트 상태 (evidence_charts 에서 이동, #1224)."""
    try:
        from nuri.trading.engine.memory import detect_drift

        drifts = detect_drift(db_path=db_path)
        return {d.signal_id: {"status": d.status, "drift_pct": d.drift_pct} for d in drifts}
    except Exception:
        return {}


def load_signal_performance(db_path=None) -> pd.DataFrame | None:
    """스코어카드 전체 합산 행(ticker NaN) + drift_status 컬럼. 없으면 None.

    합산 행이 없으면 상위 20행 폴백 (기존 생성기 동작 유지).
    """
    scorecard = load_latest_scorecard()
    if scorecard is None or scorecard.empty:
        return None
    total = scorecard[scorecard["ticker"].isna()].copy()
    if total.empty:
        total = scorecard.head(20).copy()
    total = total.sort_values(by="win_rate", ascending=True)
    drift_map = load_drift_map(db_path=db_path)
    total["drift_status"] = [drift_map.get(sig, {}).get("status", "stable") for sig in total["signal_id"]]
    return total


# ═══ 4. 공포·탐욕 90일 ═════════════════════════════════════════


def load_fear_greed_history(db_path=None, limit: int = 90) -> pd.DataFrame:
    fg = query_df(
        f"SELECT date, value FROM macro WHERE indicator='fear_greed' ORDER BY date DESC LIMIT {int(limit)}",
        db_path=db_path,
    )
    if fg.empty:
        return fg
    fg = fg.sort_values("date").reset_index(drop=True)
    fg["date"] = pd.to_datetime(fg["date"])
    return fg


# ═══ 5. 매도 근거 (위반 감지) ═════════════════════════════════


def detect_portfolio_violations(db_path=None) -> list[dict]:
    """포트폴리오 위반 자동 감지 → 매도 근거 리스트 (evidence_charts 에서 이동, #1224).

    반환 형식은 generate_sell_evidence_chart 의 docstring 계약과 동일:
    [{"ticker", "type", "severity", "action", "recovery"}]
    """
    try:
        from nuri.analysis.portfolio import analyze_portfolio

        df = analyze_portfolio(db_path=db_path)
    except Exception:
        return []

    if df.empty:
        return []

    from nuri.core.rules import MAX_SINGLE_POSITION, PORTFOLIO_STOP

    violations = []
    stop_loss_threshold = PORTFOLIO_STOP  # -10%
    max_weight = MAX_SINGLE_POSITION * 100  # 15.0%

    grouped = (
        df.groupby("ticker")
        .agg(
            {
                "pnl_pct": "mean",
                "weight_pct": "sum",
            }
        )
        .reset_index()
    )

    for _, row in grouped.iterrows():
        ticker = row["ticker"]
        pnl = row["pnl_pct"]
        weight = row["weight_pct"]

        # 손절선 위반 — 비중 위반과 독립 (한 종목이 둘 다 낼 수 있다, 원 동작 유지)
        if pnl <= stop_loss_threshold:
            violations.append(
                {
                    "ticker": ticker,
                    "type": "stop_loss",
                    "severity": abs(pnl),
                    "action": "SELL ALL",
                    "recovery": f"손실 {abs(pnl):.1f}% → 회복에 {abs(pnl) / (100 + pnl) * 100:.0f}% 상승 필요"
                    if pnl > -100
                    else "회복 불가",
                }
            )

        # 비중 초과
        if weight > max_weight:
            excess = weight - max_weight
            violations.append(
                {
                    "ticker": ticker,
                    "type": "overweight",
                    "severity": excess,
                    "action": "REDUCE",
                    "recovery": f"비중 {weight:.1f}% → {max_weight:.0f}%까지 리밸런싱 필요",
                }
            )

    # 심각도 내림차순 정렬
    violations.sort(key=lambda v: v["severity"], reverse=True)
    return violations

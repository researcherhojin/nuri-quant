"""
Append-Only Learning Memory — SIEGE 패턴 적용.

시그널 성과를 주기적으로 스냅샷하여 누적 기록.
과거 대비 최근 성과 변화를 감지하고, 성과 하락한 시그널을 경고.

사용법:
    python -m nuri.trading.engine.memory              # 현재 상태 조회
    python -m nuri.trading.engine.memory --snapshot   # 오늘 스냅샷 저장
"""

import argparse
import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pandas as pd

from nuri.core.db import get_db, query
from nuri.core.timezone import kst_now, today_kst

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).parent.parent.parent.parent / "data" / "reports"


@dataclass
class PerformanceDrift:
    """성과 변화 감지."""

    signal_id: str
    regime: str | None
    all_time_wr: float
    recent_wr: float
    drift_pct: float  # (recent - all_time) / all_time * 100
    status: str  # "stable", "improving", "degrading", "critical"
    detail: str


def save_snapshot(db_path=None) -> int:
    """현재 시그널 성과를 strategy_memory에 스냅샷 저장 (append-only)."""
    today = today_kst()

    # signal_results.csv에서 거래 데이터 로드
    results_csv = _find_latest_csv("signal_results.csv")
    if results_csv is None:
        logger.warning("signal_results.csv 없음. make validate 먼저 실행.")
        return 0

    trades = pd.read_csv(results_csv)
    if trades.empty:
        return 0

    # 레짐 라벨 (있으면)
    try:
        from nuri.quant.regime.strategy_map import analyze_signal_by_regime

        cross_df = analyze_signal_by_regime(db_path=db_path)
    except Exception:
        cross_df = pd.DataFrame()

    records = []

    # 1. 전체 기간 (all_time) — 시그널별
    for sig_id, group in trades.groupby("signal_id"):
        stats = _compute_stats(group)
        records.append(
            {
                "snapshot_date": today,
                "signal_id": sig_id,
                "regime": None,
                "period": "all_time",
                **stats,
            }
        )

    # 2. 최근 90일
    cutoff_90 = (kst_now().replace(tzinfo=None) - timedelta(days=90)).strftime("%Y-%m-%d")
    recent_90 = trades[trades["entry_date"] >= cutoff_90]
    for sig_id, group in recent_90.groupby("signal_id"):
        stats = _compute_stats(group)
        records.append(
            {
                "snapshot_date": today,
                "signal_id": sig_id,
                "regime": None,
                "period": "recent_90d",
                **stats,
            }
        )

    # 3. 최근 30일
    cutoff_30 = (kst_now().replace(tzinfo=None) - timedelta(days=30)).strftime("%Y-%m-%d")
    recent_30 = trades[trades["entry_date"] >= cutoff_30]
    for sig_id, group in recent_30.groupby("signal_id"):
        stats = _compute_stats(group)
        records.append(
            {
                "snapshot_date": today,
                "signal_id": sig_id,
                "regime": None,
                "period": "recent_30d",
                **stats,
            }
        )

    # 4. 레짐별 (교차분석 결과가 있으면)
    if not cross_df.empty:
        for _, row in cross_df.iterrows():
            records.append(
                {
                    "snapshot_date": today,
                    "signal_id": row["signal_id"],
                    "regime": row["regime"],
                    "period": "all_time",
                    "trades": int(row["trades"]),
                    "win_rate": row["win_rate"],
                    "profit_factor": row["profit_factor"],
                    "avg_return": row["avg_return"],
                }
            )

    if not records:  # pragma: no cover  # invariant: trades non-empty 일 때 all_time groupby 가 반드시 1+ record 생성 — 도달 X (line 50 trades.empty check 가 선행)
        return 0

    with get_db(db_path) as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO strategy_memory
               (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return)
               VALUES (:snapshot_date, :signal_id, :regime, :period, :trades, :win_rate, :profit_factor, :avg_return)""",
            records,
        )
        return len(records)


def detect_drift(db_path=None) -> list[PerformanceDrift]:
    """전체 기간 대비 최근 성과 변화를 감지."""
    # 최신 스냅샷에서 all_time vs recent_90d 비교
    latest = query(
        "SELECT MAX(snapshot_date) as d FROM strategy_memory",
        db_path=db_path,
    )
    if not latest or not latest[0]["d"]:
        return []

    snap_date = latest[0]["d"]

    all_time = query(
        "SELECT signal_id, win_rate, profit_factor, trades FROM strategy_memory "
        "WHERE snapshot_date = ? AND period = 'all_time' AND regime IS NULL",
        (snap_date,),
        db_path=db_path,
    )
    recent = query(
        "SELECT signal_id, win_rate, profit_factor, trades FROM strategy_memory "
        "WHERE snapshot_date = ? AND period = 'recent_90d' AND regime IS NULL",
        (snap_date,),
        db_path=db_path,
    )

    all_map = {r["signal_id"]: r for r in all_time}
    recent_map = {r["signal_id"]: r for r in recent}

    drifts = []
    for sig_id, at in all_map.items():
        rc = recent_map.get(sig_id)
        if not rc or at["win_rate"] == 0:
            continue

        drift_wr = (rc["win_rate"] - at["win_rate"]) / at["win_rate"] * 100

        if drift_wr < -30:
            status = "critical"
            detail = f"승률 {drift_wr:+.0f}% 급락 (전체 {at['win_rate']:.0%} → 최근 {rc['win_rate']:.0%})"
        elif drift_wr < -15:
            status = "degrading"
            detail = f"승률 {drift_wr:+.0f}% 하락 (전체 {at['win_rate']:.0%} → 최근 {rc['win_rate']:.0%})"
        elif drift_wr > 15:
            status = "improving"
            detail = f"승률 {drift_wr:+.0f}% 개선 (전체 {at['win_rate']:.0%} → 최근 {rc['win_rate']:.0%})"
        else:
            status = "stable"
            detail = f"승률 변화 {drift_wr:+.0f}% (안정)"

        drifts.append(
            PerformanceDrift(
                signal_id=sig_id,
                regime=None,
                all_time_wr=at["win_rate"],
                recent_wr=rc["win_rate"],
                drift_pct=round(drift_wr, 1),
                status=status,
                detail=detail,
            )
        )

    # critical/degrading 우선
    order = {"critical": 0, "degrading": 1, "improving": 2, "stable": 3}
    drifts.sort(key=lambda d: order.get(d.status, 9))
    return drifts


def _compute_stats(group: pd.DataFrame) -> dict:
    returns = group["return_pct"]
    wins = (returns > 0).sum()
    gain = returns[returns > 0].sum()
    loss = abs(returns[returns < 0].sum())
    pf = gain / loss if loss > 0 else float("inf")
    return {
        "trades": len(group),
        "win_rate": round(wins / len(group), 3) if len(group) > 0 else 0,
        "profit_factor": round(pf, 2) if pf != float("inf") else 99.99,
        "avg_return": round(float(returns.mean()), 2),
    }


def _find_latest_csv(filename: str) -> Path | None:
    if not REPORT_DIR.exists():
        return None
    for d in sorted(REPORT_DIR.iterdir(), reverse=True):
        candidate = d / filename
        if candidate.exists():
            return candidate
    return None


def print_memory_status(drifts: list[PerformanceDrift]) -> None:
    if not drifts:
        print("학습 메모리 없음 (--snapshot으로 스냅샷 먼저 저장)")
        return

    print(f"\n{'=' * 60}")
    print("  Strategy Learning Memory — Performance Drift")
    print(f"{'=' * 60}")
    print(f"  {'Signal':<18} {'Status':<12} {'AllTime':>8} {'Recent':>8} {'Drift':>8}")
    print(f"  {'-' * 56}")

    for d in drifts:
        status_icon = {
            "critical": "[!!!]",
            "degrading": "[!!]",
            "improving": "[+]",
            "stable": "[=]",
        }
        print(
            f"  {d.signal_id:<18} {status_icon.get(d.status, '')} {d.status:<8} "
            f"{d.all_time_wr:>7.0%} {d.recent_wr:>7.0%} {d.drift_pct:>+7.1f}%"
        )
    print()

    critical = [d for d in drifts if d.status in ("critical", "degrading")]
    if critical:
        print(f"  ⚠ 성과 하락 시그널 {len(critical)}개:")
        for d in critical:
            print(f"    {d.signal_id}: {d.detail}")
        print()


def main(argv: list[str] | None = None) -> int:
    """CLI entry — argparse + 오케스트레이션 (testable)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Nuri-Quant Strategy Learning Memory")
    parser.add_argument("--snapshot", action="store_true", help="오늘 스냅샷 저장")
    args = parser.parse_args(argv)

    if args.snapshot:
        from nuri.core.db import init_db

        init_db()
        n = save_snapshot()
        logger.info(f"스냅샷 {n}건 저장")

    drifts = detect_drift()
    print_memory_status(drifts)
    return 0


if __name__ == "__main__":  # pragma: no cover  # invariant: 표준 entry idiom — main() 이 testable
    raise SystemExit(main())

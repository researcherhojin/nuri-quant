"""
C-4: 통합 스코어카드 — C-1/C-2/C-3 결과를 단일 HTML로 통합.

C-1 (시그널 백테스트) 완료 후 실행 가능. C-2/C-3은 있으면 포함.

사용법:
    python -m nuri.validation.scorecard
"""
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).parent.parent.parent.parent / "data" / "reports"


def generate_validation_report(output_dir: Path | None = None) -> Path | None:
    """C-1/C-2/C-3 결과를 통합 Plotly HTML로 생성."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    if output_dir is None:
        today = datetime.now().strftime("%Y-%m-%d")
        output_dir = REPORT_DIR / today

    signal_csv = output_dir / "signal_scorecard.csv"
    si_csv = output_dir / "superinvestor_scorecard.csv"
    analyst_csv = output_dir / "analyst_results.csv"

    # C-1은 필수
    if not signal_csv.exists():
        logger.warning("통합 스코어카드 생성 불가: signal_scorecard.csv 없음 (C-1 먼저 실행)")
        return None

    # 섹션 수 결정
    has_si = si_csv.exists()
    has_analyst = analyst_csv.exists()
    n_rows = 2 + (1 if has_si else 0) + (1 if has_analyst else 0)

    subtitles = ["시그널 승률 랭킹 (Profit Factor)", "시그널 평균수익률"]
    row_heights = [0.3, 0.3]
    if has_si:
        subtitles.append("슈퍼투자자 추종 성과")
        row_heights.append(0.2)
    if has_analyst:
        subtitles.append("애널리스트 목표가 적중률")
        row_heights.append(0.2)

    # 비율 정규화
    total = sum(row_heights)
    row_heights = [h / total for h in row_heights]

    fig = make_subplots(
        rows=n_rows, cols=1,
        subplot_titles=subtitles,
        vertical_spacing=0.08,
        row_heights=row_heights,
    )

    # ── 섹션 1: 시그널 승률 (PF 기준 정렬) ──
    sig_df = pd.read_csv(signal_csv)
    # 전체합산 (ticker가 NaN인 행)만
    sig_total = sig_df[sig_df["ticker"].isna()].copy()
    sig_total = sig_total.sort_values("profit_factor", ascending=True)

    # PF가 inf인 경우 표시용 클램핑
    sig_total["pf_display"] = sig_total["profit_factor"].clip(upper=10)
    colors = ["#26a69a" if pf > 1 else "#ef5350" for pf in sig_total["profit_factor"]]

    fig.add_trace(go.Bar(
        y=sig_total["signal_id"],
        x=sig_total["pf_display"],
        orientation="h",
        marker_color=colors,
        text=[f"PF={pf:.1f} | 승률={wr:.0%} | {n}건"
              for pf, wr, n in zip(sig_total["profit_factor"], sig_total["win_rate"], sig_total["total_trades"])],
        textposition="auto",
        name="Profit Factor",
        showlegend=False,
    ), row=1, col=1)
    fig.add_vline(x=1.0, line_dash="dash", line_color="#666", row=1, col=1)

    # ── 섹션 2: 시그널 평균수익률 ──
    sig_total2 = sig_total.sort_values("avg_return", ascending=True)
    colors2 = ["#26a69a" if r > 0 else "#ef5350" for r in sig_total2["avg_return"]]

    fig.add_trace(go.Bar(
        y=sig_total2["signal_id"],
        x=sig_total2["avg_return"],
        orientation="h",
        marker_color=colors2,
        text=[f"{r:+.1f}% (중앙값 {m:+.1f}%)"
              for r, m in zip(sig_total2["avg_return"], sig_total2["median_return"])],
        textposition="auto",
        name="평균수익률",
        showlegend=False,
    ), row=2, col=1)
    fig.add_vline(x=0, line_dash="dash", line_color="#666", row=2, col=1)

    current_row = 3

    # ── 섹션 3: 슈퍼투자자 (선택) ──
    if has_si:
        si_df = pd.read_csv(si_csv)
        si_df = si_df.sort_values("avg_excess_return", ascending=True)
        si_colors = ["#26a69a" if r > 0 else "#ef5350" for r in si_df["avg_excess_return"]]

        fig.add_trace(go.Bar(
            y=si_df["investor"],
            x=si_df["avg_excess_return"],
            orientation="h",
            marker_color=si_colors,
            text=[f"초과수익 {e:+.1f}% | 수익 {r:+.1f}% | 승률 {w:.0%} | {n}건"
                  for e, r, w, n in zip(si_df["avg_excess_return"], si_df["avg_return"],
                                        si_df["win_rate"], si_df["total_follows"])],
            textposition="auto",
            name="초과수익률",
            showlegend=False,
        ), row=current_row, col=1)
        fig.add_vline(x=0, line_dash="dash", line_color="#666", row=current_row, col=1)
        current_row += 1

    # ── 섹션 4: 애널리스트 (선택) ──
    if has_analyst:
        an_df = pd.read_csv(analyst_csv)
        by_rec = an_df.groupby("recommendation").agg(
            hit_rate=("target_hit", "mean"),
            count=("target_hit", "count"),
            avg_return=("actual_return_pct", "mean"),
        ).reset_index()
        by_rec = by_rec.sort_values("hit_rate", ascending=True)

        fig.add_trace(go.Bar(
            y=by_rec["recommendation"],
            x=by_rec["hit_rate"] * 100,
            orientation="h",
            marker_color="#42a5f5",
            text=[f"{hr:.0%} ({n}건, 수익 {r:+.1f}%)"
                  for hr, n, r in zip(by_rec["hit_rate"], by_rec["count"], by_rec["avg_return"])],
            textposition="auto",
            name="적중률",
            showlegend=False,
        ), row=current_row, col=1)

    # ── 레이아웃 ──
    fig.update_layout(
        template="plotly_dark",
        height=300 * n_rows,
        margin=dict(l=150, r=30, t=50, b=30),
        paper_bgcolor="#1a1a2e",
        plot_bgcolor="#16213e",
        font=dict(family="Inter, -apple-system, sans-serif", size=11, color="#e0e0e0"),
        title=dict(
            text=f"Nuri-Quant Validation Report ({output_dir.name})",
            font=dict(size=16),
        ),
    )

    for i in range(1, n_rows + 1):
        fig.update_xaxes(gridcolor="rgba(255,255,255,0.05)", row=i, col=1)
        fig.update_yaxes(gridcolor="rgba(255,255,255,0.05)", row=i, col=1)

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "validation_report.html"
    fig.write_html(str(path), include_plotlyjs="cdn")
    logger.info(f"통합 리포트 생성: {path}")
    return path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    path = generate_validation_report()
    if path:
        print(f"통합 리포트: {path}")
    else:
        print("통합 리포트 생성 불가 (C-1부터 먼저 실행하세요)")

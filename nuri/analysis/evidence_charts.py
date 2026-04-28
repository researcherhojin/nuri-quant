# pyright: reportArgumentType=false, reportCallIssue=false, reportAttributeAccessIssue=false
"""
증거 기반 차트 — 포트폴리오 의사결정 근거를 시각화하는 Plotly HTML 차트.

(pandas Scalar union / Plotly add_hline row/col Literal stub mismatch — runtime 정상.)

레짐, 포트폴리오 히트맵, 시그널 성과, 공포·탐욕 지수, 매도 근거를 차트로 생성.

사용법:
    python -m nuri.analysis.evidence_charts
"""
import logging
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from nuri.core.db import query_df
from nuri.core.timezone import today_kst
from nuri.quant.regime.classifier import classify_regime

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).parent.parent.parent / "data" / "reports"


# ═══════════════════════════════════════════════════════
# 1. 레짐 증거 차트
# ═══════════════════════════════════════════════════════


def generate_regime_chart(output_dir: Path, db_path=None) -> Path:
    """SPY 캔들스틱 + SMA50/200 + 레짐 영역 + VIX 서브플롯."""
    # SPY 가격 (1년)
    spy = query_df(
        "SELECT date, open, high, low, close, volume FROM prices "
        "WHERE ticker='SPY' ORDER BY date DESC LIMIT 252",
        db_path=db_path,
    )
    if spy.empty:
        logger.warning("SPY 가격 데이터 없음")
        return output_dir / "regime_evidence.html"

    spy = spy.sort_values("date").reset_index(drop=True)
    spy["date"] = pd.to_datetime(spy["date"])
    spy["sma50"] = spy["close"].rolling(50).mean()
    spy["sma200"] = spy["close"].rolling(200).mean()

    # VIX
    vix = query_df(
        "SELECT date, value FROM macro WHERE indicator='vix' ORDER BY date DESC LIMIT 252",
        db_path=db_path,
    )
    if not vix.empty:
        vix = vix.sort_values("date").reset_index(drop=True)
        vix["date"] = pd.to_datetime(vix["date"])

    # 현재 레짐
    regime = classify_regime(db_path=db_path)

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.7, 0.3],
        subplot_titles=["SPY 캔들스틱 + 이동평균", "VIX 변동성 지수"],
    )

    # 캔들스틱
    fig.add_trace(go.Candlestick(
        x=spy["date"], open=spy["open"], high=spy["high"],
        low=spy["low"], close=spy["close"], name="SPY",
        increasing=dict(line=dict(color="#26a69a"), fillcolor="#26a69a"),
        decreasing=dict(line=dict(color="#ef5350"), fillcolor="#ef5350"),
    ), row=1, col=1)

    # SMA50 / SMA200
    sma50_valid = spy.dropna(subset=["sma50"])
    if not sma50_valid.empty:
        fig.add_trace(go.Scatter(
            x=sma50_valid["date"], y=sma50_valid["sma50"],
            name="SMA 50", line=dict(color="#42a5f5", width=1.5),
        ), row=1, col=1)

    sma200_valid = spy.dropna(subset=["sma200"])
    if not sma200_valid.empty:
        fig.add_trace(go.Scatter(
            x=sma200_valid["date"], y=sma200_valid["sma200"],
            name="SMA 200", line=dict(color="#ab47bc", width=2),
        ), row=1, col=1)

    # 레짐 영역 음영 (SMA50 vs SMA200 관계로 구간 착색)
    _shade_regime_zones(fig, spy)

    # 현재 레짐 주석
    if regime:
        trend_label = {"bull": "강세", "bear": "약세", "sideways": "횡보"}
        vol_label = {"high": "고변동", "low": "저변동"}
        regime_text = (
            f"현재 레짐: {trend_label.get(regime.trend, regime.trend)} · "
            f"{vol_label.get(regime.volatility, regime.volatility)} "
            f"(신뢰도 {regime.confidence:.0%})"
        )
        fig.add_annotation(
            x=spy["date"].iloc[-1], y=spy["high"].max(),
            text=regime_text,
            showarrow=False,
            font=dict(size=14, color="#ffd54f"),
            bgcolor="rgba(0,0,0,0.6)",
            bordercolor="#ffd54f",
            borderwidth=1,
            xanchor="right",
            row=1, col=1,
        )

    # VIX 서브플롯
    if not vix.empty:
        fig.add_trace(go.Scatter(
            x=vix["date"], y=vix["value"],
            name="VIX", line=dict(color="#ff7043", width=1.5),
            fill="tozeroy", fillcolor="rgba(255,112,67,0.15)",
        ), row=2, col=1)
        # 경계선
        fig.add_hline(y=20, line_dash="dot", line_color="#ffd54f",
                      opacity=0.5, row=2, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="#ef5350",
                      opacity=0.5, row=2, col=1)

    fig.update_layout(
        template="plotly_dark",
        title="레짐 증거 차트 — SPY + VIX",
        height=700,
        xaxis_rangeslider_visible=False,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )

    output_path = output_dir / "regime_evidence.html"
    fig.write_html(str(output_path))
    logger.info(f"레짐 차트 저장: {output_path}")
    return output_path


def _shade_regime_zones(fig: go.Figure, spy: pd.DataFrame) -> None:
    """SMA50/SMA200 관계에 따라 강세(녹색)/횡보(노란색)/약세(빨간색) 영역 음영."""
    df = spy.dropna(subset=["sma50", "sma200"]).copy()
    if df.empty:
        return

    df["gap_pct"] = (df["sma50"] - df["sma200"]) / df["sma200"] * 100
    # 강세: gap > 2%, 약세: gap < -2%, 횡보: -2% ~ 2%
    zone_colors = {
        "bull": "rgba(76,175,80,0.08)",
        "sideways": "rgba(255,235,59,0.06)",
        "bear": "rgba(244,67,54,0.08)",
    }

    prev_zone = None
    zone_start = None

    for _, row in df.iterrows():
        gap = row["gap_pct"]
        if gap > 2:
            zone = "bull"
        elif gap < -2:
            zone = "bear"
        else:
            zone = "sideways"

        if zone != prev_zone:
            if prev_zone is not None and zone_start is not None:
                fig.add_vrect(
                    x0=zone_start, x1=row["date"],
                    fillcolor=zone_colors[prev_zone],
                    layer="below", line_width=0,
                    row=1, col=1,
                )
            zone_start = row["date"]
            prev_zone = zone

    # 마지막 영역
    if prev_zone is not None and zone_start is not None:
        fig.add_vrect(
            x0=zone_start, x1=df["date"].iloc[-1],
            fillcolor=zone_colors[prev_zone],
            layer="below", line_width=0,
            row=1, col=1,
        )


# ═══════════════════════════════════════════════════════
# 2. 포트폴리오 히트맵 (Treemap)
# ═══════════════════════════════════════════════════════


def generate_portfolio_heatmap(output_dir: Path, db_path=None) -> Path:
    """포트폴리오 트리맵: 크기=포지션 가치, 색상=손익%."""
    from nuri.analysis.portfolio import analyze_portfolio

    df = analyze_portfolio()
    output_path = output_dir / "portfolio_heatmap.html"

    if df.empty:
        logger.warning("포트폴리오 데이터 없음")
        _save_empty_chart("포트폴리오 데이터 없음", output_path)
        return output_path

    # 종목별 합산 (다계좌 동일 종목)
    grouped = df.groupby("ticker").agg({
        "current_value_usd": "sum",
        "pnl_pct": "mean",
        "weight_pct": "sum",
        "sector": "first",
    }).reset_index()

    # 위반 감지 (config/rules.yaml 기준)
    from nuri.core.rules import MAX_SINGLE_POSITION, PORTFOLIO_STOP
    max_single = MAX_SINGLE_POSITION  # 0.15 (15%)
    stop_loss = PORTFOLIO_STOP        # -10
    violations = []
    border_colors = []

    for _, row in grouped.iterrows():
        color = "#ef5350"  # 기본: 빨간 테두리 없음
        if row["pnl_pct"] <= stop_loss:
            violations.append(row["ticker"])
            color = "#ef5350"
        elif row["weight_pct"] > max_single * 100:
            violations.append(row["ticker"])
            color = "#ffd54f"
        border_colors.append(color)

    # 라벨
    labels = [
        f"{row['ticker']}<br>"
        f"손익: {row['pnl_pct']:+.1f}%<br>"
        f"비중: {row['weight_pct']:.1f}%"
        for _, row in grouped.iterrows()
    ]

    # PnL% 색상 범위
    pnl_values = grouped["pnl_pct"].values
    abs_max = max(abs(pnl_values.min()), abs(pnl_values.max()), 1)

    fig = go.Figure(go.Treemap(
        labels=labels,
        parents=[""] * len(grouped),
        values=grouped["current_value_usd"].clip(lower=1).values,
        marker=dict(
            colors=pnl_values,
            colorscale=[
                [0.0, "#d32f2f"],      # 큰 손실: 진한 빨강
                [0.35, "#ef5350"],     # 손실: 빨강
                [0.5, "#616161"],      # 0%: 회색
                [0.65, "#66bb6a"],     # 이익: 초록
                [1.0, "#2e7d32"],      # 큰 이익: 진한 초록
            ],
            cmid=0,
            cmin=-abs_max,
            cmax=abs_max,
            colorbar=dict(title="손익 %", ticksuffix="%"),
            line=dict(width=2),
        ),
        textinfo="label",
        textfont=dict(size=12),
        hovertemplate=(
            "<b>%{label}</b><br>"
            "가치: $%{value:,.0f}<extra></extra>"
        ),
    ))

    # 위반 종목 주석
    if violations:
        violation_text = "위반 종목: " + ", ".join(violations)
        fig.add_annotation(
            text=violation_text,
            xref="paper", yref="paper",
            x=0.5, y=-0.05,
            showarrow=False,
            font=dict(size=12, color="#ef5350"),
        )

    fig.update_layout(
        template="plotly_dark",
        title="포트폴리오 히트맵 — 크기=가치, 색상=손익%",
        height=600,
        margin=dict(t=60, b=40, l=10, r=10),
    )

    fig.write_html(str(output_path))
    logger.info(f"포트폴리오 히트맵 저장: {output_path}")
    return output_path


# ═══════════════════════════════════════════════════════
# 3. 시그널 성과 차트
# ═══════════════════════════════════════════════════════


def generate_signal_performance_chart(output_dir: Path, db_path=None) -> Path:
    """시그널별 승률 바 차트 + 이익계수 라인 (보조 Y축)."""
    output_path = output_dir / "signal_performance.html"

    # 최신 signal_scorecard.csv 찾기
    scorecard_df = _load_latest_scorecard()
    if scorecard_df is None or scorecard_df.empty:
        logger.warning("signal_scorecard.csv 없음 (make validate 먼저 실행)")
        _save_empty_chart("시그널 스코어카드 없음 (make validate 실행 필요)", output_path)
        return output_path

    # 전체 종목 합산 행만 사용 (ticker가 NaN)
    total = scorecard_df[scorecard_df["ticker"].isna()].copy()
    if total.empty:
        total = scorecard_df.head(20)

    total = total.sort_values("win_rate", ascending=True)

    # 드리프트 상태 로드
    drift_map = _load_drift_map(db_path)

    # 색상: 드리프트 상태별
    colors = []
    for _, row in total.iterrows():
        sig_id = row["signal_id"]
        drift = drift_map.get(sig_id, {}).get("status", "stable")
        if drift == "critical":
            colors.append("#ef5350")    # 빨강
        elif drift == "degrading":
            colors.append("#ff9800")    # 주황
        else:
            colors.append("#42a5f5")    # 파랑 (정상)

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # 승률 바 차트
    fig.add_trace(go.Bar(
        y=total["signal_id"],
        x=total["win_rate"],
        orientation="h",
        name="승률",
        marker_color=colors,
        text=[f"{wr:.0%}" for wr in total["win_rate"]],
        textposition="auto",
        hovertemplate="시그널: %{y}<br>승률: %{x:.1%}<extra></extra>",
    ), secondary_y=False)

    # 이익계수 라인 (보조 Y축)
    pf = total["profit_factor"].clip(upper=10)  # 극단값 제한
    fig.add_trace(go.Scatter(
        y=total["signal_id"],
        x=pf,
        mode="lines+markers",
        name="이익계수 (PF)",
        line=dict(color="#ffd54f", width=2),
        marker=dict(size=8),
        hovertemplate="시그널: %{y}<br>PF: %{x:.2f}<extra></extra>",
    ), secondary_y=True)

    # critical/degrading 마커
    for _, row in total.iterrows():
        sig_id = row["signal_id"]
        drift = drift_map.get(sig_id, {}).get("status", "stable")
        if drift in ("critical", "degrading"):
            marker_color = "#ef5350" if drift == "critical" else "#ff9800"
            label = "성과 급락" if drift == "critical" else "성과 하락"
            fig.add_annotation(
                y=sig_id, x=row["win_rate"],
                text=f" {label}",
                showarrow=False,
                font=dict(size=10, color=marker_color),
                xanchor="left",
            )

    fig.update_layout(
        template="plotly_dark",
        title="시그널 성과 — 승률 + 이익계수",
        height=max(400, len(total) * 35 + 100),
        xaxis_title="승률",
        margin=dict(l=180),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.update_xaxes(tickformat=".0%")
    fig.update_yaxes(title_text="승률", secondary_y=False)
    fig.update_yaxes(title_text="이익계수", secondary_y=True)

    fig.write_html(str(output_path))
    logger.info(f"시그널 성과 차트 저장: {output_path}")
    return output_path


# ═══════════════════════════════════════════════════════
# 4. 공포·탐욕 지수 차트
# ═══════════════════════════════════════════════════════


def generate_fear_greed_chart(output_dir: Path, db_path=None) -> Path:
    """90일 공포·탐욕 지수 라인 + 구간 음영."""
    output_path = output_dir / "fear_greed.html"

    fg = query_df(
        "SELECT date, value FROM macro WHERE indicator='fear_greed' "
        "ORDER BY date DESC LIMIT 90",
        db_path=db_path,
    )
    if fg.empty:
        logger.warning("공포·탐욕 데이터 없음")
        _save_empty_chart("공포·탐욕 데이터 없음", output_path)
        return output_path

    fg = fg.sort_values("date").reset_index(drop=True)
    fg["date"] = pd.to_datetime(fg["date"])

    fig = go.Figure()

    # 구간 음영 (배경)
    zones = [
        (0, 20, "극단적 공포", "rgba(244,67,54,0.15)"),
        (20, 40, "공포", "rgba(255,152,0,0.12)"),
        (40, 60, "중립", "rgba(158,158,158,0.08)"),
        (60, 80, "탐욕", "rgba(76,175,80,0.12)"),
        (80, 100, "극단적 탐욕", "rgba(33,150,243,0.15)"),
    ]
    for y0, y1, label, color in zones:
        fig.add_hrect(
            y0=y0, y1=y1,
            fillcolor=color,
            layer="below",
            line_width=0,
            annotation_text=label,
            annotation_position="right",
            annotation_font=dict(size=10, color="rgba(255,255,255,0.5)"),
        )

    # 라인
    fig.add_trace(go.Scatter(
        x=fg["date"], y=fg["value"],
        mode="lines",
        name="공포·탐욕 지수",
        line=dict(color="#ffd54f", width=2.5),
        fill="tozeroy",
        fillcolor="rgba(255,213,79,0.08)",
        hovertemplate="날짜: %{x|%Y-%m-%d}<br>지수: %{y:.0f}<extra></extra>",
    ))

    # 현재 값 강조
    current_value = fg["value"].iloc[-1]
    current_date = fg["date"].iloc[-1]

    # 현재 값에 따른 색상
    if current_value <= 20:
        dot_color = "#ef5350"
        status = "극단적 공포"
    elif current_value <= 40:
        dot_color = "#ff9800"
        status = "공포"
    elif current_value <= 60:
        dot_color = "#9e9e9e"
        status = "중립"
    elif current_value <= 80:
        dot_color = "#66bb6a"
        status = "탐욕"
    else:
        dot_color = "#42a5f5"
        status = "극단적 탐욕"

    fig.add_trace(go.Scatter(
        x=[current_date], y=[current_value],
        mode="markers+text",
        name="현재",
        marker=dict(size=16, color=dot_color, line=dict(width=2, color="white")),
        text=[f"{current_value:.0f}"],
        textposition="top center",
        textfont=dict(size=14, color=dot_color),
        hovertemplate=f"현재: {current_value:.0f} ({status})<extra></extra>",
    ))

    fig.update_layout(
        template="plotly_dark",
        title=f"공포·탐욕 지수 (90일) — 현재: {current_value:.0f} ({status})",
        yaxis_title="지수",
        yaxis_range=[0, 100],
        height=450,
        showlegend=False,
    )

    fig.write_html(str(output_path))
    logger.info(f"공포·탐욕 차트 저장: {output_path}")
    return output_path


# ═══════════════════════════════════════════════════════
# 5. 매도 근거 차트
# ═══════════════════════════════════════════════════════


def generate_sell_evidence_chart(violations: list[dict], output_dir: Path) -> Path:
    """위반 항목별 수평 바 차트.

    violations 형식:
        [{"ticker": "TSLA", "type": "stop_loss", "severity": 25.3,
          "action": "SELL ALL", "recovery": "6-12개월"},
         {"ticker": "NVDA", "type": "overweight", "severity": 5.2,
          "action": "REDUCE", "recovery": "리밸런싱 필요"}]
    """
    output_path = output_dir / "sell_evidence.html"

    if not violations:
        _save_empty_chart("매도 근거 위반 없음", output_path)
        return output_path

    df = pd.DataFrame(violations)

    # 심각도별 색상
    severity_color = {"critical": "#ef5350", "high": "#ff9800", "medium": "#ffd54f"}
    colors = [severity_color.get(str(sev), "#ffd54f") for sev in df["severity"]]

    # 라벨 — violation_type 또는 type 컬럼 사용
    type_col = "violation_type" if "violation_type" in df.columns else "type"
    labels = [
        f"{row['ticker']} ({row.get(type_col, '')})"
        for _, row in df.iterrows()
    ]

    fig = go.Figure()

    # severity가 숫자면 그대로, 문자열이면 current_value 사용
    x_values = []
    for _, row in df.iterrows():
        if isinstance(row["severity"], (int, float)):
            x_values.append(abs(float(row["severity"])))
        elif "current_value" in df.columns:
            x_values.append(abs(float(row["current_value"])))
        else:
            x_values.append(1.0)

    fig.add_trace(go.Bar(
        y=labels,
        x=x_values,
        orientation="h",
        marker_color=colors,
        text=[
            f"{row['action']} | {row['severity']}"
            for _, row in df.iterrows()
        ],
        textposition="auto",
        textfont=dict(size=11),
        hovertemplate=(
            "<b>%{y}</b><br>"
            "심각도: %{x:.1f}%<br>"
            "<extra></extra>"
        ),
    ))

    # 조치 + 회복 주석
    for i, (_, row) in enumerate(df.iterrows()):
        recovery = row.get("recovery", "")
        if recovery:
            fig.add_annotation(
                y=i, x=df["severity"].max() * 1.05,
                text=f"회복: {recovery}",
                showarrow=False,
                font=dict(size=10, color="#b0bec5"),
                xanchor="left",
            )

    # 임계선
    fig.add_vline(x=20, line_dash="dot", line_color="#ef5350",
                  opacity=0.6, annotation_text="손절선 -20%",
                  annotation_position="top")

    fig.update_layout(
        template="plotly_dark",
        title="매도 근거 — 위반 항목별 심각도",
        xaxis_title="심각도 (%)",
        height=max(300, len(df) * 50 + 100),
        margin=dict(l=200, r=120),
    )

    fig.write_html(str(output_path))
    logger.info(f"매도 근거 차트 저장: {output_path}")
    return output_path


# ═══════════════════════════════════════════════════════
# 6. 전체 생성
# ═══════════════════════════════════════════════════════


def generate_all_evidence(db_path=None) -> list[Path]:
    """모든 증거 차트 생성 → 파일 경로 리스트 반환."""
    today = today_kst()
    output_dir = REPORT_DIR / today / "evidence"
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = []

    # 1. 레짐 차트
    try:
        paths.append(generate_regime_chart(output_dir, db_path))
    except Exception as e:
        logger.error(f"레짐 차트 생성 실패: {e}")

    # 2. 포트폴리오 히트맵
    try:
        paths.append(generate_portfolio_heatmap(output_dir, db_path))
    except Exception as e:
        logger.error(f"포트폴리오 히트맵 생성 실패: {e}")

    # 3. 시그널 성과
    try:
        paths.append(generate_signal_performance_chart(output_dir, db_path))
    except Exception as e:
        logger.error(f"시그널 성과 차트 생성 실패: {e}")

    # 4. 공포·탐욕 지수
    try:
        paths.append(generate_fear_greed_chart(output_dir, db_path))
    except Exception as e:
        logger.error(f"공포·탐욕 차트 생성 실패: {e}")

    # 5. 매도 근거 (포트폴리오 위반 자동 감지)
    try:
        violations = _detect_portfolio_violations(db_path)
        paths.append(generate_sell_evidence_chart(violations, output_dir))
    except Exception as e:
        logger.error(f"매도 근거 차트 생성 실패: {e}")

    # 요약
    print(f"\n{'='*50}")
    print(f"증거 차트 생성 완료: {len(paths)}개")
    print(f"저장 경로: {output_dir}")
    for p in paths:
        print(f"  - {p.name}")
    print(f"{'='*50}\n")

    return paths


# ═══════════════════════════════════════════════════════
# 유틸리티
# ═══════════════════════════════════════════════════════


def _load_latest_scorecard() -> pd.DataFrame | None:
    """최신 signal_scorecard.csv 로드."""
    if not REPORT_DIR.exists():
        return None
    for d in sorted(REPORT_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        csv_path = d / "signal_scorecard.csv"
        if csv_path.exists():
            return pd.read_csv(csv_path)
    return None


def _load_drift_map(db_path=None) -> dict[str, dict]:
    """Learning Memory에서 시그널별 드리프트 상태 로드."""
    try:
        from nuri.trading.engine.memory import detect_drift
        drifts = detect_drift(db_path=db_path)
        return {d.signal_id: {"status": d.status, "drift_pct": d.drift_pct} for d in drifts}
    except Exception:
        return {}


def _detect_portfolio_violations(db_path=None) -> list[dict]:
    """포트폴리오 위반 항목 자동 감지 → 매도 근거 리스트."""
    try:
        from nuri.analysis.portfolio import analyze_portfolio
        df = analyze_portfolio()
    except Exception:
        return []

    if df.empty:
        return []

    from nuri.core.rules import MAX_SINGLE_POSITION, PORTFOLIO_STOP
    violations = []
    stop_loss_threshold = PORTFOLIO_STOP       # -10%
    max_weight = MAX_SINGLE_POSITION * 100     # 15.0%

    # 종목별 합산
    grouped = df.groupby("ticker").agg({
        "pnl_pct": "mean",
        "weight_pct": "sum",
    }).reset_index()

    for _, row in grouped.iterrows():
        ticker = row["ticker"]
        pnl = row["pnl_pct"]
        weight = row["weight_pct"]

        # 손절선 위반
        if pnl <= stop_loss_threshold:
            violations.append({
                "ticker": ticker,
                "type": "stop_loss",
                "severity": abs(pnl),
                "action": "SELL ALL",
                "recovery": f"손실 {abs(pnl):.1f}% → 회복에 {abs(pnl) / (100 + pnl) * 100:.0f}% 상승 필요"
                if pnl > -100 else "회복 불가",
            })

        # 비중 초과
        if weight > max_weight:
            excess = weight - max_weight
            violations.append({
                "ticker": ticker,
                "type": "overweight",
                "severity": excess,
                "action": "REDUCE",
                "recovery": f"비중 {weight:.1f}% → {max_weight:.0f}%까지 리밸런싱 필요",
            })

    # 심각도 내림차순 정렬
    violations.sort(key=lambda v: v["severity"], reverse=True)
    return violations


def _save_empty_chart(message: str, output_path: Path) -> None:
    """데이터 없을 때 안내 메시지 차트 저장."""
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper", yref="paper",
        x=0.5, y=0.5,
        showarrow=False,
        font=dict(size=18, color="#9e9e9e"),
    )
    fig.update_layout(
        template="plotly_dark",
        height=300,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
    )
    fig.write_html(str(output_path))


# ═══════════════════════════════════════════════════════
# 메인
# ═══════════════════════════════════════════════════════


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    generate_all_evidence()

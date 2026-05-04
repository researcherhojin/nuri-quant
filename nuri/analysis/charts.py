# pyright: reportArgumentType=false, reportCallIssue=false
"""
기술적 분석 차트 — 투자 플랫폼 스타일 인터랙티브 HTML.

캔들스틱 + BB + SMA + 거래량 + RSI + MACD + 매수/매도 시그널 + 정보 패널.

사용법:
    python -m nuri.analysis.charts --ticker TSLA
    python -m nuri.analysis.charts --all

Pylance 정책: TA-Lib NDArray 호환성 / Plotly add_hline row/col Literal 시그니처
mismatch 는 광범위 false positive — 실행 시점에는 모두 정상 동작 (pandas Series
→ float ndarray, plotly subplot 정수 row/col 표준 사용). file-level disable.
"""

import argparse
import logging
from pathlib import Path

import pandas as pd

from nuri.core.db import get_tickers, query, query_df
from nuri.core.timezone import today_kst

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).parent.parent.parent / "data" / "reports"


# ═══════════════════════════════════════════════════════
# 데이터 로딩 + 지표 계산
# ═══════════════════════════════════════════════════════


def _load_chart_data(ticker: str) -> pd.DataFrame | None:
    """가격 데이터 로드 + TA-Lib으로 기술적 지표 계산."""
    prices = query_df(
        "SELECT date, open, high, low, close, volume FROM prices WHERE ticker = ? ORDER BY date",
        (ticker,),
    )
    if prices.empty or len(prices) < 20:
        return None

    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.set_index("date")
    close = prices["close"].values

    try:
        import talib

        prices["rsi_14"] = talib.RSI(close, timeperiod=14)
        macd, signal, hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
        prices["macd"], prices["macd_signal"], prices["macd_hist"] = macd, signal, hist
        upper, middle, lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
        prices["bb_upper"], prices["bb_middle"], prices["bb_lower"] = upper, middle, lower
        prices["sma_20"] = talib.SMA(close, timeperiod=20)
        prices["sma_50"] = talib.SMA(close, timeperiod=50)
        prices["sma_200"] = talib.SMA(close, timeperiod=200)
        prices["ema_12"] = talib.EMA(close, timeperiod=12)
    except ImportError:
        prices["sma_20"] = prices["close"].rolling(20).mean()
        prices["sma_50"] = prices["close"].rolling(50).mean()
        prices["sma_200"] = prices["close"].rolling(200).mean()
        prices["ema_12"] = prices["close"].ewm(span=12).mean()
        bb_mid = prices["sma_20"]
        bb_std = prices["close"].rolling(20).std()
        prices["bb_upper"] = bb_mid + 2 * bb_std
        prices["bb_middle"] = bb_mid
        prices["bb_lower"] = bb_mid - 2 * bb_std
        delta = prices["close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss
        prices["rsi_14"] = 100 - (100 / (1 + rs))
        ema12 = prices["close"].ewm(span=12).mean()
        ema26 = prices["close"].ewm(span=26).mean()
        prices["macd"] = ema12 - ema26
        prices["macd_signal"] = prices["macd"].ewm(span=9).mean()
        prices["macd_hist"] = prices["macd"] - prices["macd_signal"]

    return prices


def _detect_signals(df: pd.DataFrame) -> pd.DataFrame:
    """매수/매도 시그널 감지 — signal_backtest의 detector registry 재사용."""
    from nuri.quant.validation.signal_backtest import BUY_SIGNALS, SIGNAL_DEFINITIONS, detect_signal_entries

    # charts.py는 date index 사용, signal_backtest는 positional index 사용
    # volume_sma_20 계산 (signal_backtest의 compute_indicators와 동일 패턴)
    if "volume" in df.columns and "volume_sma_20" not in df.columns:
        df["volume_sma_20"] = df["volume"].rolling(20).mean()

    # 차트에 표시할 시그널 (매크로/데이터 의존 시그널 제외 — 가격 기반만)
    chart_signals = [
        "rsi_oversold",
        "rsi_overbought",
        "macd_golden",
        "macd_dead",
        "sma_golden",
        "sma_dead",
        "volume_spike",
        "gap_up",
        "gap_down",
    ]

    signals = []
    for sig_id in chart_signals:
        defn = SIGNAL_DEFINITIONS.get(sig_id)
        if defn is None:
            continue

        direction = "buy" if sig_id in BUY_SIGNALS else "sell"
        entries = detect_signal_entries(df, sig_id)
        for idx in entries:
            signals.append(
                {
                    "date": df.index[idx],
                    "price": df["close"].iloc[idx],
                    "type": direction,
                    "reason": defn["description"],
                }
            )

    return pd.DataFrame(signals) if signals else pd.DataFrame(columns=["date", "price", "type", "reason"])


def _get_info_panel(ticker: str) -> dict:
    """펀더멘탈 + 애널리스트 + 센티먼트 정보 조회."""
    info = {"ticker": ticker}

    # 펀더멘탈
    fund = query("SELECT * FROM fundamentals WHERE ticker = ? ORDER BY date DESC LIMIT 1", (ticker,))
    if fund:
        f = fund[0]
        info["pe"] = f.get("pe_ratio") or f.get("forward_pe")
        info["roe"] = f.get("roe")
        info["revenue_growth"] = f.get("revenue_growth")
        info["debt_to_equity"] = f.get("debt_to_equity")
        info["market_cap"] = f.get("market_cap")
        info["beta"] = f.get("beta")

    # 애널리스트
    est = query("SELECT * FROM estimates WHERE ticker = ? ORDER BY date DESC LIMIT 1", (ticker,))
    if est:
        e = est[0]
        info["recommendation"] = e.get("recommendation")
        info["target_mean"] = e.get("target_mean")
        info["target_high"] = e.get("target_high")
        info["target_low"] = e.get("target_low")
        info["num_analysts"] = e.get("num_analysts")
        info["current_price"] = e.get("current_price")

    # 센티먼트
    sent = query(
        "SELECT AVG(sentiment) as avg_s, COUNT(*) as cnt FROM news WHERE ticker = ? AND sentiment IS NOT NULL",
        (ticker,),
    )
    if sent and sent[0]["cnt"]:
        info["sentiment"] = sent[0]["avg_s"]
        info["news_count"] = sent[0]["cnt"]

    # 슈퍼투자자
    si = query(
        "SELECT investor, portfolio_pct FROM superinvestors WHERE ticker = ? ORDER BY portfolio_pct DESC", (ticker,)
    )
    if si:
        info["superinvestors"] = [(r["investor"], r["portfolio_pct"]) for r in si[:3]]

    return info


# ═══════════════════════════════════════════════════════
# Plotly 차트 생성
# ═══════════════════════════════════════════════════════


def generate_plotly_chart(ticker: str, df: pd.DataFrame, output_dir: Path) -> Path:
    """투자 플랫폼 스타일 Plotly 차트."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    sig_df = _detect_signals(df)
    info = _get_info_panel(ticker)

    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.025,
        row_heights=[0.50, 0.12, 0.18, 0.20],
        subplot_titles=["", "", "", ""],
    )

    # ── 1. 캔들스틱 ──
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="OHLC",
            increasing=dict(line=dict(color="#26a69a"), fillcolor="#26a69a"),
            decreasing=dict(line=dict(color="#ef5350"), fillcolor="#ef5350"),
            whiskerwidth=0.5,
        ),
        row=1,
        col=1,
    )

    # 볼린저밴드 (채우기)
    if "bb_upper" in df.columns:
        bb = df[["bb_upper", "bb_lower"]].dropna()
        if not bb.empty:
            fig.add_trace(
                go.Scatter(
                    x=bb.index,
                    y=bb["bb_upper"],
                    name="BB Upper",
                    line=dict(width=0),
                    showlegend=False,
                ),
                row=1,
                col=1,
            )
            fig.add_trace(
                go.Scatter(
                    x=bb.index,
                    y=bb["bb_lower"],
                    name="BB",
                    line=dict(width=0),
                    fill="tonexty",
                    fillcolor="rgba(100,181,246,0.12)",
                    showlegend=True,
                ),
                row=1,
                col=1,
            )

    # SMA
    sma_config = [
        ("sma_20", "SMA 20", "#ff9800", 1.2),
        ("sma_50", "SMA 50", "#42a5f5", 1.5),
        ("sma_200", "SMA 200", "#ab47bc", 2.0),
    ]
    for col, name, color, width in sma_config:
        if col in df.columns:
            data = df[col].dropna()
            if not data.empty:
                fig.add_trace(
                    go.Scatter(
                        x=data.index,
                        y=data,
                        name=name,
                        line=dict(color=color, width=width),
                    ),
                    row=1,
                    col=1,
                )

    # 애널리스트 목표가 라인
    if info.get("target_mean"):
        fig.add_hline(
            y=info["target_mean"],
            line_dash="dot",
            line_color="#4caf50",
            opacity=0.6,
            annotation_text=f"목표가 ${info['target_mean']:,.0f}",
            annotation_position="top right",
            annotation_font_color="#4caf50",
            row=1,
            col=1,
        )
    if info.get("target_low"):
        fig.add_hline(
            y=info["target_low"],
            line_dash="dot",
            line_color="#ff5252",
            opacity=0.3,
            row=1,
            col=1,
        )

    # 매수/매도 시그널 마커
    if not sig_df.empty:
        buys = sig_df[sig_df["type"] == "buy"]
        sells = sig_df[sig_df["type"] == "sell"]

        if not buys.empty:
            fig.add_trace(
                go.Scatter(
                    x=buys["date"],
                    y=buys["price"],
                    mode="markers",
                    name="BUY",
                    marker=dict(symbol="triangle-up", size=12, color="#00e676", line=dict(width=1, color="white")),
                    text=buys["reason"],
                    hovertemplate="%{text}<br>$%{y:,.2f}<extra></extra>",
                ),
                row=1,
                col=1,
            )

        if not sells.empty:
            fig.add_trace(
                go.Scatter(
                    x=sells["date"],
                    y=sells["price"],
                    mode="markers",
                    name="SELL",
                    marker=dict(symbol="triangle-down", size=12, color="#ff1744", line=dict(width=1, color="white")),
                    text=sells["reason"],
                    hovertemplate="%{text}<br>$%{y:,.2f}<extra></extra>",
                ),
                row=1,
                col=1,
            )

    # ── 2. 거래량 ──
    vol_colors = ["rgba(38,166,154,0.7)" if c >= o else "rgba(239,83,80,0.7)" for c, o in zip(df["close"], df["open"])]
    fig.add_trace(
        go.Bar(
            x=df.index,
            y=df["volume"],
            name="Volume",
            marker_color=vol_colors,
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    # 거래량 20일 평균
    vol_ma = df["volume"].rolling(20).mean()
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=vol_ma,
            name="Vol MA20",
            line=dict(color="#ffab40", width=1),
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    # ── 3. RSI ──
    rsi = df["rsi_14"].dropna()
    if not rsi.empty:
        # 과매수/과매도 영역 배경
        fig.add_hrect(y0=70, y1=100, fillcolor="rgba(255,82,82,0.08)", line_width=0, row=3, col=1)
        fig.add_hrect(y0=0, y1=30, fillcolor="rgba(0,230,118,0.08)", line_width=0, row=3, col=1)

        fig.add_trace(
            go.Scatter(
                x=rsi.index,
                y=rsi,
                name="RSI",
                line=dict(color="#7c4dff", width=1.5),
                fill="tozeroy",
                fillcolor="rgba(124,77,255,0.05)",
            ),
            row=3,
            col=1,
        )

        fig.add_hline(y=70, line_dash="dash", line_color="#ff5252", opacity=0.4, row=3, col=1)
        fig.add_hline(y=50, line_dash="dot", line_color="#666", opacity=0.3, row=3, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="#00e676", opacity=0.4, row=3, col=1)

    # ── 4. MACD ──
    macd_data = df[["macd", "macd_signal", "macd_hist"]].dropna()
    if not macd_data.empty:
        # 히스토그램
        hist_pos = macd_data["macd_hist"].clip(lower=0)
        hist_neg = macd_data["macd_hist"].clip(upper=0)

        fig.add_trace(
            go.Bar(
                x=macd_data.index,
                y=hist_pos,
                name="MACD+",
                marker_color="rgba(38,166,154,0.5)",
                showlegend=False,
            ),
            row=4,
            col=1,
        )
        fig.add_trace(
            go.Bar(
                x=macd_data.index,
                y=hist_neg,
                name="MACD-",
                marker_color="rgba(239,83,80,0.5)",
                showlegend=False,
            ),
            row=4,
            col=1,
        )

        fig.add_trace(
            go.Scatter(
                x=macd_data.index,
                y=macd_data["macd"],
                name="MACD",
                line=dict(color="#42a5f5", width=1.5),
            ),
            row=4,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=macd_data.index,
                y=macd_data["macd_signal"],
                name="Signal",
                line=dict(color="#ff9800", width=1.5),
            ),
            row=4,
            col=1,
        )

        fig.add_hline(y=0, line_color="#555", opacity=0.3, row=4, col=1)

    # ── 레이아웃 ──
    # 정보 패널 텍스트 (차트 우측 상단)
    info_lines = [f"<b>{ticker}</b>"]
    latest = df["close"].iloc[-1]
    prev = df["close"].iloc[-2] if len(df) > 1 else latest
    chg = (latest - prev) / prev * 100
    chg_color = "#26a69a" if chg >= 0 else "#ef5350"
    info_lines.append(f"<span style='font-size:18px;color:{chg_color}'>${latest:,.2f} ({chg:+.2f}%)</span>")

    if info.get("pe"):
        info_lines.append(f"PE {info['pe']:.1f}")
    if info.get("roe"):
        info_lines.append(f"ROE {info['roe'] * 100:.1f}%")
    if info.get("recommendation"):
        rec_colors = {
            "strong_buy": "#00e676",
            "buy": "#66bb6a",
            "hold": "#ffab40",
            "sell": "#ef5350",
            "strong_sell": "#d50000",
        }
        rec = info["recommendation"]
        rc = rec_colors.get(rec, "#999")
        info_lines.append(f"<span style='color:{rc}'>{rec.upper()}</span> ({info.get('num_analysts', '?')} analysts)")
    if info.get("sentiment") is not None:
        s = info["sentiment"]
        sc = "#26a69a" if s > 0.05 else ("#ef5350" if s < -0.05 else "#999")
        info_lines.append(f"Sentiment <span style='color:{sc}'>{s:+.2f}</span>")
    if info.get("superinvestors"):
        names = ", ".join(inv for inv, _ in info["superinvestors"])
        info_lines.append(f"Held by: {names}")

    info_text = "<br>".join(info_lines)

    fig.add_annotation(
        text=info_text,
        xref="paper",
        yref="paper",
        x=1.0,
        y=1.0,
        showarrow=False,
        font=dict(size=11, color="#ccc"),
        align="right",
        bgcolor="rgba(30,30,30,0.85)",
        bordercolor="#444",
        borderwidth=1,
        borderpad=8,
        xanchor="right",
        yanchor="top",
    )

    # 최근 시그널 알림 박스
    if not sig_df.empty:
        recent = sig_df.tail(3)
        alert_lines = ["<b>Recent Signals</b>"]
        for _, s in recent.iterrows():
            icon = "▲" if s["type"] == "buy" else "▼"
            c = "#00e676" if s["type"] == "buy" else "#ff1744"
            d = s["date"].strftime("%m/%d")
            alert_lines.append(f"<span style='color:{c}'>{icon} {d}</span> {s['reason']}")

        fig.add_annotation(
            text="<br>".join(alert_lines),
            xref="paper",
            yref="paper",
            x=0.0,
            y=1.0,
            showarrow=False,
            font=dict(size=10, color="#ccc"),
            align="left",
            bgcolor="rgba(30,30,30,0.85)",
            bordercolor="#555",
            borderwidth=1,
            borderpad=8,
            xanchor="left",
            yanchor="top",
        )

    fig.update_layout(
        template="plotly_dark",
        height=900,
        margin=dict(l=60, r=20, t=30, b=40),
        paper_bgcolor="#1a1a2e",
        plot_bgcolor="#16213e",
        font=dict(family="Inter, -apple-system, sans-serif", size=11, color="#e0e0e0"),
        xaxis_rangeslider_visible=False,
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.01,
            xanchor="center",
            x=0.5,
            font=dict(size=10),
            bgcolor="rgba(0,0,0,0)",
        ),
        # 기간 선택 버튼
        xaxis4=dict(
            rangeselector=dict(
                buttons=[
                    dict(count=1, label="1M", step="month", stepmode="backward"),
                    dict(count=3, label="3M", step="month", stepmode="backward"),
                    dict(count=6, label="6M", step="month", stepmode="backward"),
                    dict(count=1, label="1Y", step="year", stepmode="backward"),
                    dict(count=2, label="2Y", step="year", stepmode="backward"),
                    dict(label="ALL", step="all"),
                ],
                bgcolor="#1a1a2e",
                activecolor="#0a3d62",
                font=dict(color="#e0e0e0"),
            ),
        ),
        bargap=0,
        bargroupgap=0,
    )

    # Y축 라벨
    fig.update_yaxes(title_text="Price", row=1, col=1, gridcolor="rgba(255,255,255,0.05)")
    fig.update_yaxes(title_text="Vol", row=2, col=1, gridcolor="rgba(255,255,255,0.05)")
    fig.update_yaxes(title_text="RSI", range=[0, 100], row=3, col=1, gridcolor="rgba(255,255,255,0.05)")
    fig.update_yaxes(title_text="MACD", row=4, col=1, gridcolor="rgba(255,255,255,0.05)")

    for i in range(1, 5):
        fig.update_xaxes(gridcolor="rgba(255,255,255,0.05)", row=i, col=1)

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{ticker}.html"
    fig.write_html(str(path), include_plotlyjs="cdn")
    return path


# ═══════════════════════════════════════════════════════
# PNG (mplfinance)
# ═══════════════════════════════════════════════════════


def generate_png_chart(ticker: str, df: pd.DataFrame, output_dir: Path) -> Path:
    """mplfinance 정적 PNG."""
    import matplotlib

    matplotlib.use("Agg")
    import mplfinance as mpf

    ohlcv = df[["open", "high", "low", "close", "volume"]].copy()
    ohlcv.columns = ["Open", "High", "Low", "Close", "Volume"]

    addplots = []
    if "bb_upper" in df.columns and df["bb_upper"].notna().any():
        addplots.append(mpf.make_addplot(df["bb_upper"], panel=0, color="lightblue", width=0.7))
        addplots.append(mpf.make_addplot(df["bb_lower"], panel=0, color="lightblue", width=0.7))
    if "sma_50" in df.columns and df["sma_50"].notna().any():
        addplots.append(mpf.make_addplot(df["sma_50"], panel=0, color="#42a5f5", width=1))
    if "rsi_14" in df.columns:
        addplots.append(mpf.make_addplot(df["rsi_14"], panel=2, color="purple", width=1, ylabel="RSI"))
    if "macd" in df.columns:
        addplots.append(mpf.make_addplot(df["macd"], panel=3, color="blue", width=1, ylabel="MACD"))
        addplots.append(mpf.make_addplot(df["macd_signal"], panel=3, color="orange", width=1))

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{ticker}.png"

    mpf.plot(
        ohlcv,
        type="candle",
        style="nightclouds",
        title=f"\n{ticker}",
        volume=True,
        addplot=addplots if addplots else None,
        figsize=(14, 10),
        savefig=str(path),
    )
    return path


# ═══════════════════════════════════════════════════════
# 메인
# ═══════════════════════════════════════════════════════


def generate_charts(
    tickers: list[str] | None = None,
    output_dir: Path | None = None,
    png: bool = False,
    html: bool = True,
) -> list[str]:
    if tickers is None:
        tickers = get_tickers()
    if output_dir is None:
        today = today_kst()
        output_dir = REPORT_DIR / today / "charts"

    generated = []
    for ticker in tickers:
        df = _load_chart_data(ticker)
        if df is None:
            logger.warning(f"{ticker}: 차트 데이터 부족")
            continue
        try:
            if html:
                path = generate_plotly_chart(ticker, df, output_dir)
                generated.append(str(path))
                logger.info(f"{ticker}: HTML → {path.name}")
            if png:
                path = generate_png_chart(ticker, df, output_dir)
                generated.append(str(path))
                logger.info(f"{ticker}: PNG → {path.name}")
        except Exception as e:
            logger.error(f"{ticker}: 차트 실패 — {e}")
    return generated


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: --ticker 또는 --all 로 차트 생성."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Nuri-Quant 기술적 분석 차트")
    parser.add_argument("--ticker", help="특정 종목")
    parser.add_argument("--all", action="store_true", help="전 보유종목")
    parser.add_argument("--png", action="store_true", help="PNG도 생성")
    parser.add_argument("--no-html", action="store_true", help="HTML 안 함")
    args = parser.parse_args(argv)

    tickers = [args.ticker] if args.ticker else (None if args.all else None)
    if not args.ticker and not args.all:
        parser.print_help()
        print("\n--ticker 또는 --all 중 하나를 지정하세요.")
        return 1

    files = generate_charts(tickers=tickers, png=args.png, html=not args.no_html)
    print(f"\n생성: {len(files)}개 차트")
    for f in files:
        print(f"  {f}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

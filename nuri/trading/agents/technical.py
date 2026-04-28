# pyright: reportArgumentType=false, reportCallIssue=false, reportAttributeAccessIssue=false, reportOperatorIssue=false, reportOptionalMemberAccess=false, reportOptionalSubscript=false, reportOptionalOperand=false
"""기술적 분석 에이전트 — RSI, MACD, SMA, BB, 차트 패턴(BB 위치/MACD 전환/52주/추세선) 기반 판정.

FINVIZ 스크리너 데이터를 보조 시그널로 활용 (external_analysis 테이블).
"""
import logging

import pandas as pd

from nuri.core.agent_config import AGENT_CONFIG
from nuri.core.db import query, query_df
from nuri.core.timezone import kst_now
from nuri.quant.chart_analysis import analyze_chart
from nuri.trading.agents.base import AgentVerdict, BaseAgent

logger = logging.getLogger(__name__)

_CFG = AGENT_CONFIG.get("technical", {})
_CONF = _CFG.get("confidence", {})
_FINVIZ_CFG = _CFG.get("finviz", {})

# FINVIZ 시그널 → BUY/SELL 분류
_FINVIZ_BUY_SIGNALS = {"oversold_rsi", "new_low"}
_FINVIZ_SELL_SIGNALS = {"overbought_rsi", "new_high"}
# unusual_volume, most_volatile → 방향 중립 (가산 없음)


class TechnicalAgent(BaseAgent):
    def __init__(self):
        super().__init__("technical")

    def analyze(self, ticker: str, db_path=None) -> AgentVerdict:
        min_dp = _CFG.get("min_data_points", 50)
        df = query_df(
            "SELECT date, close FROM prices WHERE ticker = ? ORDER BY date",
            (ticker,), db_path=db_path,
        )
        # prices에 없으면 yfinance fallback (스캐너 종목 대응)
        if (df.empty or len(df) < min_dp) and db_path is None:
            try:
                import yfinance as yf
                _df = yf.download(ticker, period="6mo", progress=False)
                if not _df.empty and len(_df) >= min_dp:
                    close_col = _df["Close"].squeeze() if hasattr(_df["Close"], "squeeze") else _df["Close"]
                    df = pd.DataFrame({"close": close_col.values})
            except Exception:
                pass
        if df.empty or len(df) < min_dp:
            return AgentVerdict(self.name, ticker, "HOLD", 0, "데이터 부족")

        close = df["close"]
        latest = float(close.iloc[-1])

        rsi_period = _CFG.get("rsi_period", 14)
        sma_short = _CFG.get("sma_short", 50)
        sma_long = _CFG.get("sma_long", 200)

        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(rsi_period).mean()
        loss = (-delta.clip(upper=0)).rolling(rsi_period).mean()
        rs = gain / loss
        rsi = float((100 - (100 / (1 + rs))).iloc[-1]) if pd.notna(rs.iloc[-1]) else 50

        # SMA
        sma50 = float(close.rolling(sma_short).mean().iloc[-1]) if len(df) >= sma_short else latest
        sma200 = float(close.rolling(sma_long).mean().iloc[-1]) if len(df) >= sma_long else latest

        # MACD
        ema_fast = close.ewm(span=_CFG.get("macd_fast", 12)).mean()
        ema_slow = close.ewm(span=_CFG.get("macd_slow", 26)).mean()
        macd = float((ema_fast - ema_slow).iloc[-1])
        signal = float((ema_fast - ema_slow).ewm(span=_CFG.get("macd_signal", 9)).mean().iloc[-1])

        # 차트 패턴 분석 (DB 기반 — yfinance fallback 시 skip)
        chart = None
        if not df.empty and "date" in df.columns:
            try:
                chart = analyze_chart(ticker, db_path=db_path)
            except Exception:
                chart = None

        # 판정 로직
        buy_signals = 0
        sell_signals = 0
        reasons = []

        rsi_oversold = _CFG.get("rsi_oversold", 30)
        rsi_overbought = _CFG.get("rsi_overbought", 70)

        if rsi < rsi_oversold:
            buy_signals += 2
            reasons.append(f"RSI 과매도({rsi:.0f})")
        elif rsi > rsi_overbought:
            sell_signals += 2
            reasons.append(f"RSI 과매수({rsi:.0f})")

        if latest > sma200 and sma50 > sma200:
            buy_signals += 1
            reasons.append("SMA50>SMA200 (골든크로스)")
        elif latest < sma200 and sma50 < sma200:
            sell_signals += 1
            reasons.append("SMA50<SMA200 (데드크로스)")

        if macd > signal:
            buy_signals += 1
            reasons.append("MACD>Signal")
        else:
            sell_signals += 1
            reasons.append("MACD<Signal")

        # 차트 패턴 기여 (시각 정보)
        if chart is not None and chart.price > 0:
            if chart.macd_turn == "bullish":
                buy_signals += 2
                reasons.append("MACD 히스토그램 양전환")
            elif chart.macd_turn == "bearish":
                sell_signals += 2
                reasons.append("MACD 히스토그램 음전환")

            if chart.bb_position >= 80:
                buy_signals += 1
                reasons.append(f"BB 상단({chart.bb_position:.0f})")
            elif chart.bb_position <= 20:
                buy_signals += 1  # BB 하단은 반등 신호 (RSI와 동일 컨셉)
                reasons.append(f"BB 하단({chart.bb_position:.0f})")

            if chart.dist_from_52w_low <= 10 and chart.trend_strength > 0:
                buy_signals += 1
                reasons.append(f"52주 저점 +{chart.dist_from_52w_low:.0f}% 반등")
            elif chart.dist_from_52w_high >= -3:
                sell_signals += 1
                reasons.append(f"52주 고점 근접({chart.dist_from_52w_high:.0f}%)")

            if chart.trend_strength >= 30:
                buy_signals += 1
                reasons.append(f"추세강세({chart.trend_strength:+.0f})")
            elif chart.trend_strength <= -30:
                sell_signals += 1
                reasons.append(f"추세약세({chart.trend_strength:+.0f})")

        # FINVIZ 스크리너 보조 시그널 (external_analysis 테이블)
        finviz_signals = self._get_finviz_signals(ticker, db_path=db_path)
        finviz_buy_boost = _FINVIZ_CFG.get("buy_boost", 1)
        finviz_sell_boost = _FINVIZ_CFG.get("sell_boost", 1)
        for sig in finviz_signals:
            if sig in _FINVIZ_BUY_SIGNALS:
                buy_signals += finviz_buy_boost
                reasons.append(f"FINVIZ {sig}")
            elif sig in _FINVIZ_SELL_SIGNALS:
                sell_signals += finviz_sell_boost
                reasons.append(f"FINVIZ {sig}")

        conf_cap = _CONF.get("cap", 90)
        conf_hold = _CONF.get("hold", 40)

        total = buy_signals + sell_signals
        if buy_signals > sell_signals:
            action = "BUY"
            confidence = min(conf_cap, buy_signals / total * 100) if total > 0 else 50
        elif sell_signals > buy_signals:
            action = "SELL"
            confidence = min(conf_cap, sell_signals / total * 100) if total > 0 else 50
        else:
            action = "HOLD"
            confidence = conf_hold

        data_points = {
            "rsi": round(rsi, 1), "sma50": round(sma50, 2), "sma200": round(sma200, 2),
            "macd": round(macd, 4), "price": round(latest, 2),
        }
        if chart is not None and chart.price > 0:
            data_points.update({
                "bb_pos": chart.bb_position,
                "macd_turn": chart.macd_turn,
                "dist_high_52w": chart.dist_from_52w_high,
                "dist_low_52w": chart.dist_from_52w_low,
                "poc": chart.poc_price,
                "trend": chart.trend_strength,
                "visual_bias": chart.visual_bias,
            })
        if finviz_signals:
            data_points["finviz_signals"] = sorted(finviz_signals)

        return AgentVerdict(
            self.name, ticker, action, round(self.normalize_confidence(confidence), 1),
            "; ".join(reasons) or "혼조",
            data_points,
        )

    def _get_finviz_signals(self, ticker: str, db_path=None) -> list[str]:
        """external_analysis 테이블에서 최근 FINVIZ 시그널 조회.

        max_age_days 이내의 데이터만 사용. 데이터 없으면 빈 리스트 (graceful fallback).
        """
        from datetime import timedelta
        max_age = _FINVIZ_CFG.get("max_age_days", 3)
        cutoff = (kst_now() - timedelta(days=max_age)).strftime("%Y-%m-%d")
        try:
            rows = query(
                "SELECT value FROM external_analysis "
                "WHERE source = 'FINVIZ' AND ticker = ? AND data_type = 'finviz_signal' "
                "AND date >= ? ORDER BY date DESC",
                (ticker, cutoff),
                db_path=db_path,
            )
            return [r["value"] for r in rows if r.get("value")]
        except Exception:
            logger.debug("FINVIZ 데이터 조회 실패: %s", ticker, exc_info=True)
            return []

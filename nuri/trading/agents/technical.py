"""기술적 분석 에이전트 — RSI, MACD, SMA, BB 기반 판정."""
import pandas as pd

from nuri.core.agent_config import AGENT_CONFIG
from nuri.core.db import query_df
from nuri.trading.agents.base import AgentVerdict, BaseAgent

_CFG = AGENT_CONFIG.get("technical", {})
_CONF = _CFG.get("confidence", {})


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

        return AgentVerdict(
            self.name, ticker, action, round(self.normalize_confidence(confidence), 1),
            "; ".join(reasons) or "혼조",
            {"rsi": round(rsi, 1), "sma50": round(sma50, 2), "sma200": round(sma200, 2),
             "macd": round(macd, 4), "price": round(latest, 2)},
        )

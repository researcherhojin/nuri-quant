"""기술적 분석 에이전트 — RSI, MACD, SMA, BB 기반 판정."""
import pandas as pd
from nuri.trading.agents.base import BaseAgent, AgentVerdict
from nuri.core.db import query_df


class TechnicalAgent(BaseAgent):
    def __init__(self):
        super().__init__("technical")

    def analyze(self, ticker: str, db_path=None) -> AgentVerdict:
        df = query_df(
            "SELECT date, close FROM prices WHERE ticker = ? ORDER BY date",
            (ticker,), db_path=db_path,
        )
        # prices에 없으면 yfinance fallback (스캐너 종목 대응)
        if (df.empty or len(df) < 50) and db_path is None:
            try:
                import yfinance as yf
                _df = yf.download(ticker, period="6mo", progress=False)
                if not _df.empty and len(_df) >= 50:
                    close_col = _df["Close"].squeeze() if hasattr(_df["Close"], "squeeze") else _df["Close"]
                    df = pd.DataFrame({"close": close_col.values})
            except Exception:
                pass
        if df.empty or len(df) < 50:
            return AgentVerdict(self.name, ticker, "HOLD", 0, "데이터 부족")

        close = df["close"]
        latest = float(close.iloc[-1])

        # RSI 14
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss
        rsi = float((100 - (100 / (1 + rs))).iloc[-1]) if pd.notna(rs.iloc[-1]) else 50

        # SMA 50/200
        sma50 = float(close.rolling(50).mean().iloc[-1]) if len(df) >= 50 else latest
        sma200 = float(close.rolling(200).mean().iloc[-1]) if len(df) >= 200 else latest

        # MACD
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd = float((ema12 - ema26).iloc[-1])
        signal = float((ema12 - ema26).ewm(span=9).mean().iloc[-1])

        # 판정 로직
        buy_signals = 0
        sell_signals = 0
        reasons = []

        if rsi < 30:
            buy_signals += 2
            reasons.append(f"RSI 과매도({rsi:.0f})")
        elif rsi > 70:
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

        total = buy_signals + sell_signals
        if buy_signals > sell_signals:
            action = "BUY"
            confidence = min(90, buy_signals / total * 100) if total > 0 else 50
        elif sell_signals > buy_signals:
            action = "SELL"
            confidence = min(90, sell_signals / total * 100) if total > 0 else 50
        else:
            action = "HOLD"
            confidence = 40

        return AgentVerdict(
            self.name, ticker, action, round(confidence, 1),
            "; ".join(reasons) or "혼조",
            {"rsi": round(rsi, 1), "sma50": round(sma50, 2), "sma200": round(sma200, 2),
             "macd": round(macd, 4), "price": round(latest, 2)},
        )

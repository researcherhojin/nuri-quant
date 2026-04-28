# pyright: reportArgumentType=false, reportCallIssue=false, reportAttributeAccessIssue=false, reportOperatorIssue=false, reportOptionalMemberAccess=false, reportOptionalSubscript=false, reportOptionalOperand=false
"""매크로 분석 에이전트 — 시장 레짐 + 매크로 스코어 + 개별 종목 모멘텀 기반 판정."""
from nuri.core.agent_config import AGENT_CONFIG
from nuri.core.db import query_df
from nuri.trading.agents.base import AgentVerdict, BaseAgent

_CFG = AGENT_CONFIG.get("macro", {})
_CONF = _CFG.get("confidence", {})


class MacroAgent(BaseAgent):
    def __init__(self):
        super().__init__("macro")

    def analyze(self, ticker: str, db_path=None) -> AgentVerdict:
        """시장 레짐 기반 판정 + 개별 종목 모멘텀 조정.

        sideways 레짐에서도 강한 모멘텀 종목은 BUY, 약한 종목은 SELL 가능.
        """
        try:
            from nuri.quant.regime.classifier import classify_regime
            from nuri.quant.regime.macro_score import compute_macro_score

            regime = classify_regime(db_path=db_path)
            macro = compute_macro_score(db_path=db_path)
        except Exception:
            no_data = round(self.normalize_confidence(_CONF.get("no_data", 30)), 1)
            return AgentVerdict(self.name, ticker, "HOLD", no_data, "레짐/매크로 데이터 부족")

        if regime is None:
            no_data = round(self.normalize_confidence(_CONF.get("no_data", 30)), 1)
            return AgentVerdict(self.name, ticker, "HOLD", no_data, "SPY 데이터 부족")

        trend = regime.trend
        macro_score = macro.total_score

        ms_bull = _CFG.get("macro_score_bull", 60)
        ms_bear = _CFG.get("macro_score_bear", 35)
        conf_cap = _CONF.get("cap", 80)
        conf_sideways = _CONF.get("sideways_base", 42)

        # ── 1. 시장 전체 기본 판정 ──
        if trend == "bull" and macro_score >= ms_bull:
            base_action, base_conf = "BUY", min(conf_cap, macro_score)
            reason = f"상승장({regime.regime}), 매크로 {macro_score:.0f}/100 양호"
        elif trend == "bear" or macro_score < ms_bear:
            base_action, base_conf = "SELL", min(conf_cap, 100 - macro_score)
            reason = f"하락장({regime.regime}), 매크로 {macro_score:.0f}/100 악화"
        else:
            base_action, base_conf = "HOLD", conf_sideways
            reason = f"횡보({regime.regime}), 매크로 {macro_score:.0f}/100 중립"

        # ── 2. 개별 종목 모멘텀으로 조정 (sideways에서 차별화) ──
        action = base_action
        confidence = base_conf

        df = query_df(
            "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 20",
            (ticker,), db_path=db_path,
        )
        # prices에 없으면 yfinance에서 직접 가져오기 (스캐너 종목 대응)
        if df.empty or len(df) < 5:
            try:
                import pandas as pd
                import yfinance as yf
                _df = yf.download(ticker, period="30d", progress=False)
                if not _df.empty:
                    close_col = _df["Close"].squeeze() if hasattr(_df["Close"], "squeeze") else _df["Close"]
                    df = pd.DataFrame({"close": close_col.values[::-1]})
            except Exception:
                pass

        min_candles = _CFG.get("min_candles", 10)
        if len(df) >= min_candles:
            close = df["close"]
            ret_5d = (close.iloc[0] - close.iloc[4]) / close.iloc[4] * 100 if len(df) >= 5 else 0
            ret_10d = (close.iloc[0] - close.iloc[9]) / close.iloc[9] * 100 if len(df) >= 10 else 0

            mom_5d_bull = _CFG.get("momentum_5d_bull", 8)
            mom_10d_bull = _CFG.get("momentum_10d_bull", 10)
            mom_5d_bear = _CFG.get("momentum_5d_bear", -8)
            mom_10d_bear = _CFG.get("momentum_10d_bear", -10)
            conf_mom_cap = _CONF.get("momentum_cap", 65)
            conf_mom_base = _CONF.get("momentum_base", 45)
            conf_hold = _CONF.get("override_hold", 40)

            if trend == "sideways":
                # sideways에서 강한 모멘텀은 BUY 가능
                if ret_5d > mom_5d_bull and ret_10d > mom_10d_bull:
                    action = "BUY"
                    confidence = min(conf_mom_cap, conf_mom_base + ret_5d)
                    reason += f"; 개별 모멘텀 강세(5D +{ret_5d:.1f}%)"
                elif ret_5d < mom_5d_bear and ret_10d < mom_10d_bear:
                    action = "SELL"
                    confidence = min(conf_mom_cap, conf_mom_base + abs(ret_5d))
                    reason += f"; 개별 모멘텀 약세(5D {ret_5d:.1f}%)"

            elif trend == "bull":
                # bull에서 개별 종목이 하락 중이면 BUY 약화
                if ret_5d < _CFG.get("bull_underperform", -5):
                    action = "HOLD"
                    confidence = conf_hold
                    reason += f"; 상승장이나 개별 약세(5D {ret_5d:.1f}%)"

            elif trend == "bear":
                # bear에서 개별 종목이 강한 반등이면 SELL 약화
                if ret_5d > _CFG.get("bear_bounce", 10):
                    action = "HOLD"
                    confidence = conf_hold
                    reason += f"; 하락장이나 개별 반등(5D +{ret_5d:.1f}%)"

        # ── 3. 섹터 조정 ──
        sector_rows = self._safe_query(
            "SELECT sector FROM portfolio WHERE ticker = ?", (ticker,), db_path,
        )
        sector = sector_rows[0]["sector"] if sector_rows else ""
        if trend == "bear" and sector:
            from nuri.trading.recommend.rebalance import _classify_sector
            if _classify_sector(sector) == "defensive":
                if action == "SELL":
                    action = "HOLD"
                    reason += "; 방어 섹터 → 매도 유보"

        return AgentVerdict(
            self.name, ticker, action, round(self.normalize_confidence(confidence), 1), reason,
            {"regime": regime.regime, "macro_score": macro_score,
             "confidence_pct": regime.confidence},
        )

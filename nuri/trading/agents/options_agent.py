"""옵션 시장 에이전트 — Put/Call Ratio 기반 시장 심리 판정.

CBOE PCR 데이터로 시장 공포/탐욕 수준을 판단한다.
PCR 높음(≥1.2) = 극도 공포 → 역발상 매수 신호.
PCR 낮음(≤0.7) = 과도한 낙관 → 경계 신호.
데이터 없으면 graceful HOLD 반환.
"""

from nuri.core.agent_config import AGENT_CONFIG
from nuri.trading.agents.base import AgentVerdict, BaseAgent

_CFG = AGENT_CONFIG.get("options", {})
_CONF = _CFG.get("confidence", {})


class OptionsAgent(BaseAgent):
    def __init__(self):
        super().__init__("options")

    def analyze(self, ticker: str, db_path=None) -> AgentVerdict:
        lookback = _CFG.get("lookback_days", 5)
        rows = self._safe_query(
            "SELECT value FROM macro WHERE indicator='put_call_ratio' ORDER BY date DESC LIMIT ?",
            (lookback,),
            db_path,
        )
        if not rows:
            return AgentVerdict(self.name, ticker, "HOLD", _CONF.get("no_data", 0), "PCR 데이터 없음")

        values = [r["value"] for r in rows if r["value"] is not None]
        if not values:
            return AgentVerdict(self.name, ticker, "HOLD", _CONF.get("no_data", 0), "PCR 데이터 없음")

        pcr = sum(values) / len(values)

        pcr_bearish = _CFG.get("pcr_bearish", 1.2)
        pcr_bullish = _CFG.get("pcr_bullish", 0.7)
        pcr_neutral_low = _CFG.get("pcr_neutral_low", 0.8)
        pcr_neutral_high = _CFG.get("pcr_neutral_high", 1.0)

        score = 0
        reasons = []

        # 높은 PCR = 공포 → 역발상 매수 (contrarian)
        if pcr >= pcr_bearish:
            score += 2
            reasons.append(f"PCR {pcr:.2f} 극도 공포 (역발상 매수)")
        elif pcr >= pcr_neutral_high:
            score += 1
            reasons.append(f"PCR {pcr:.2f} 약한 공포")
        elif pcr <= pcr_bullish:
            score -= 2
            reasons.append(f"PCR {pcr:.2f} 과도한 낙관 (경계)")
        elif pcr <= pcr_neutral_low:
            score -= 1
            reasons.append(f"PCR {pcr:.2f} 낙관적")
        else:
            reasons.append(f"PCR {pcr:.2f} 중립")

        # PCR 추세 (최근 값 vs 평균)
        if len(values) >= 3:
            recent = values[0]
            rise_ratio = _CFG.get("trend_rise_ratio", 1.1)
            fall_ratio = _CFG.get("trend_fall_ratio", 0.9)
            if recent > pcr * rise_ratio:
                score += 1
                reasons.append("PCR 상승 추세")
            elif recent < pcr * fall_ratio:
                score -= 1
                reasons.append("PCR 하락 추세")

        score_buy = _CFG.get("score_buy", 2)
        score_sell = _CFG.get("score_sell", -2)

        if score >= score_buy:
            action, confidence = (
                "BUY",
                min(
                    _CONF.get("cap", 80),
                    _CONF.get("buy_base", 45) + score * _CONF.get("buy_multiplier", 12),
                ),
            )
        elif score <= score_sell:
            action, confidence = (
                "SELL",
                min(
                    _CONF.get("cap", 80),
                    _CONF.get("sell_base", 45) + abs(score) * _CONF.get("sell_multiplier", 12),
                ),
            )
        else:
            action, confidence = "HOLD", _CONF.get("hold_base", 35) + abs(score) * _CONF.get("hold_multiplier", 8)

        return AgentVerdict(
            self.name,
            ticker,
            action,
            round(self.normalize_confidence(confidence), 1),
            "; ".join(reasons),
            {
                "pcr_avg": round(pcr, 3),
                "pcr_latest": round(values[0], 3) if values else None,
                "lookback_count": len(values),
            },
        )

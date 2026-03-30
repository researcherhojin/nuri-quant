"""크립토 센티먼트 에이전트 — BTC 가격/지배력 기반 리스크 선호도 판정.

BTC는 위험자산 선행지표. BTC 급등 = 리스크온, BTC 급락 = 리스크오프.
BTC 지배력(dominance) 하락 = 알트코인 강세 = 투기 심리 과열.
데이터 없으면 graceful HOLD 반환.
"""
from nuri.core.agent_config import AGENT_CONFIG
from nuri.trading.agents.base import AgentVerdict, BaseAgent

_CFG = AGENT_CONFIG.get("crypto", {})
_CONF = _CFG.get("confidence", {})


class CryptoAgent(BaseAgent):
    def __init__(self):
        super().__init__("crypto")

    def analyze(self, ticker: str, db_path=None) -> AgentVerdict:
        # BTC 24h 변화율
        change_rows = self._safe_query(
            "SELECT value FROM macro WHERE indicator='btc_24h_change_pct' "
            "ORDER BY date DESC LIMIT 1",
            db_path=db_path,
        )
        # BTC 지배력
        dom_rows = self._safe_query(
            "SELECT value FROM macro WHERE indicator='btc_dominance' "
            "ORDER BY date DESC LIMIT 1",
            db_path=db_path,
        )
        # BTC 가격
        btc_rows = self._safe_query(
            "SELECT value FROM macro WHERE indicator='btc_usd_cg' "
            "ORDER BY date DESC LIMIT 1",
            db_path=db_path,
        )

        if not change_rows and not dom_rows and not btc_rows:
            return AgentVerdict(self.name, ticker, "HOLD", _CONF.get("no_data", 0), "크립토 데이터 없음")

        score = 0
        reasons = []
        data = {}

        # 1. BTC 24h 변화율
        if change_rows and change_rows[0]["value"] is not None:
            change = change_rows[0]["value"]
            data["btc_24h_change"] = round(change, 2)

            strong_rally = _CFG.get("btc_strong_rally", 10)
            rally = _CFG.get("btc_rally", 3)
            crash = _CFG.get("btc_crash", -5)
            severe_crash = _CFG.get("btc_severe_crash", -10)

            if change > strong_rally:
                score += 2
                reasons.append(f"BTC +{change:.1f}% 강한 리스크온")
            elif change > rally:
                score += 1
                reasons.append(f"BTC +{change:.1f}% 리스크온")
            elif change < severe_crash:
                score -= 2
                reasons.append(f"BTC {change:.1f}% 강한 리스크오프")
            elif change < crash:
                score -= 1
                reasons.append(f"BTC {change:.1f}% 리스크오프")

        # 2. BTC 지배력
        if dom_rows and dom_rows[0]["value"] is not None:
            dom = dom_rows[0]["value"]
            data["btc_dominance"] = round(dom, 1)

            dom_high = _CFG.get("dominance_high", 60)
            dom_low = _CFG.get("dominance_low", 40)

            if dom > dom_high:
                score -= 1
                reasons.append(f"BTC 지배력 {dom:.0f}% (알트 약세, 리스크오프)")
            elif dom < dom_low:
                score += 1
                reasons.append(f"BTC 지배력 {dom:.0f}% (알트 강세, 투기 심리)")

        # 3. BTC 가격 (참고용)
        if btc_rows and btc_rows[0]["value"] is not None:
            data["btc_price"] = round(btc_rows[0]["value"], 0)

        if not reasons:
            return AgentVerdict(self.name, ticker, "HOLD", _CONF.get("no_data", 0), "크립토 변동 없음", data)

        score_buy = _CFG.get("score_buy", 2)
        score_sell = _CFG.get("score_sell", -2)

        if score >= score_buy:
            action, confidence = "BUY", min(
                _CONF.get("cap", 80),
                _CONF.get("buy_base", 40) + score * _CONF.get("buy_multiplier", 10),
            )
        elif score <= score_sell:
            action, confidence = "SELL", min(
                _CONF.get("cap", 80),
                _CONF.get("sell_base", 40) + abs(score) * _CONF.get("sell_multiplier", 10),
            )
        else:
            action, confidence = "HOLD", _CONF.get("hold_base", 30) + abs(score) * _CONF.get("hold_multiplier", 8)

        return AgentVerdict(
            self.name, ticker, action, round(self.normalize_confidence(confidence), 1),
            "; ".join(reasons),
            data,
        )

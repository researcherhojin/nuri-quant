"""크립토 센티먼트 에이전트 — BTC 가격/지배력 기반 리스크 선호도 판정.

BTC는 위험자산 선행지표. BTC 급등 = 리스크온, BTC 급락 = 리스크오프.
BTC 지배력(dominance) 하락 = 알트코인 강세 = 투기 심리 과열.
데이터 없으면 graceful HOLD 반환.
"""

from nuri.core.agent_config import AGENT_CONFIG
from nuri.trading.agents.base import AgentVerdict, BaseAgent, QueryRows, finite_or_none

_CFG = AGENT_CONFIG.get("crypto", {})
_CONF = _CFG.get("confidence", {})


class CryptoAgent(BaseAgent):
    def __init__(self):
        super().__init__("crypto")

    def analyze(self, ticker: str, db_path=None) -> AgentVerdict:
        # BTC 24h 변화율
        change_rows = self._safe_query(
            "SELECT value FROM macro WHERE indicator='btc_24h_change_pct' ORDER BY date DESC LIMIT 1",
            db_path=db_path,
        )
        # BTC 지배력
        dom_rows = self._safe_query(
            "SELECT value FROM macro WHERE indicator='btc_dominance' ORDER BY date DESC LIMIT 1",
            db_path=db_path,
        )
        # BTC 가격
        btc_rows = self._safe_query(
            "SELECT value FROM macro WHERE indicator='btc_usd_cg' ORDER BY date DESC LIMIT 1",
            db_path=db_path,
        )

        # 실패 누적은 **모든 출구**가 봐야 한다 (#1436, codex R5). 전에는 "셋 다 비었음"
        # 분기에서만 봤는데, 변화율 조회가 실패하고 지배력이 중립값(50)으로 성공하면 아래
        # "변동 없음" 출구로 빠져 장애가 정상 기권으로 기록됐다.
        db_failed = any(r.failed for r in (change_rows, dom_rows, btc_rows))

        if not change_rows and not dom_rows and not btc_rows:
            return self._no_data(
                ticker,
                QueryRows(failed=db_failed),
                confidence=_CONF.get("no_data", 0),
                empty_reason="크립토 데이터 없음",
                failed_reason="크립토 조회 실패",
            )

        score = 0
        reasons = []
        data = {}

        # NaN/±inf 가 macro 에 들어와도 `is not None` 은 통과한다 — finite 만 값으로 친다 (#1485)
        change = finite_or_none(change_rows[0]["value"]) if change_rows else None
        dom = finite_or_none(dom_rows[0]["value"]) if dom_rows else None
        btc_price = finite_or_none(btc_rows[0]["value"]) if btc_rows else None

        # 1. BTC 24h 변화율
        if change is not None:
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
        if dom is not None:
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
        if btc_price is not None:
            data["btc_price"] = round(btc_price, 0)

        if not reasons:
            return self._no_data(
                ticker,
                QueryRows(failed=db_failed),
                confidence=_CONF.get("no_data", 0),
                empty_reason="크립토 변동 없음",
                failed_reason="크립토 조회 실패",
                data_points=data,
            )

        score_buy = _CFG.get("score_buy", 2)
        score_sell = _CFG.get("score_sell", -2)

        if score >= score_buy:
            action, confidence = (
                "BUY",
                min(
                    _CONF.get("cap", 80),
                    _CONF.get("buy_base", 40) + score * _CONF.get("buy_multiplier", 10),
                ),
            )
        elif score <= score_sell:
            action, confidence = (
                "SELL",
                min(
                    _CONF.get("cap", 80),
                    _CONF.get("sell_base", 40) + abs(score) * _CONF.get("sell_multiplier", 10),
                ),
            )
        else:
            action, confidence = "HOLD", _CONF.get("hold_base", 30) + abs(score) * _CONF.get("hold_multiplier", 8)

        return AgentVerdict(
            self.name,
            ticker,
            action,
            round(self.normalize_confidence(confidence), 1),
            "; ".join(reasons),
            data,
        )

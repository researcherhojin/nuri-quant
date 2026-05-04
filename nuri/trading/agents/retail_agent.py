"""리테일 센티먼트 에이전트 — Reddit/WSB 데이터 기반 개인 투자자 심리 판정.

WSB 언급 급증 = 과열 경계 (역발상 매도 신호).
WSB 전체 활동 증가 = 시장 관심도 과열.
데이터 없으면 graceful HOLD 반환.
"""
from nuri.core.agent_config import AGENT_CONFIG
from nuri.trading.agents.base import AgentVerdict, BaseAgent

_CFG = AGENT_CONFIG.get("retail", {})
_CONF = _CFG.get("confidence", {})


class RetailAgent(BaseAgent):
    def __init__(self):
        super().__init__("retail")

    def analyze(self, ticker: str, db_path=None) -> AgentVerdict:
        # 종목별 WSB 언급 횟수
        mention_rows = self._safe_query(
            "SELECT value FROM macro WHERE indicator=? ORDER BY date DESC LIMIT 1",
            (f"wsb_mention_{ticker}",), db_path,
        )
        # WSB 전체 게시물 수
        post_rows = self._safe_query(
            "SELECT value FROM macro WHERE indicator='wsb_post_count' "
            "ORDER BY date DESC LIMIT 1",
            db_path=db_path,
        )

        if not mention_rows and not post_rows:
            return AgentVerdict(self.name, ticker, "HOLD", _CONF.get("no_data", 0), "리테일 센티먼트 데이터 없음")

        score = 0
        reasons = []
        data = {}

        spike_th = _CFG.get("wsb_spike_threshold", 10)
        hot_th = _CFG.get("wsb_hot_threshold", 30)
        post_high = _CFG.get("post_count_high", 1000)

        # 1. 종목별 언급 — 높으면 과열 (역발상 매도)
        if mention_rows and mention_rows[0]["value"] is not None:
            mentions = mention_rows[0]["value"]
            data["wsb_mentions"] = mentions

            if mentions >= hot_th:
                score -= 2
                reasons.append(f"WSB 과열 ({mentions}건 언급, 역발상 매도)")
            elif mentions >= spike_th:
                score -= 1
                reasons.append(f"WSB 관심 상승 ({mentions}건, 주의)")
            elif mentions > 0:
                score += 1
                reasons.append(f"WSB 적정 관심 ({mentions}건)")

        # 2. 전체 게시물 수 — 시장 전체 과열 판단
        if post_rows and post_rows[0]["value"] is not None:
            posts = post_rows[0]["value"]
            data["wsb_post_count"] = posts

            if posts >= post_high:
                score -= 1
                reasons.append(f"WSB 전체 과열 ({posts}건/일)")

        if not reasons:
            return AgentVerdict(self.name, ticker, "HOLD", _CONF.get("no_data", 0), "리테일 데이터 부족", data)

        score_buy = _CFG.get("score_buy", 2)
        score_sell = _CFG.get("score_sell", -2)

        if score >= score_buy:
            action, confidence = "BUY", min(
                _CONF.get("cap", 80),
                _CONF.get("buy_base", 35) + score * _CONF.get("buy_multiplier", 10),
            )
        elif score <= score_sell:
            action, confidence = "SELL", min(
                _CONF.get("cap", 80),
                _CONF.get("sell_base", 35) + abs(score) * _CONF.get("sell_multiplier", 10),
            )
        else:
            action, confidence = "HOLD", _CONF.get("hold_base", 30) + abs(score) * _CONF.get("hold_multiplier", 8)

        return AgentVerdict(
            self.name, ticker, action, round(self.normalize_confidence(confidence), 1),
            "; ".join(reasons),
            data,
        )

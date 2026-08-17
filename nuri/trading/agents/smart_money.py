"""스마트머니 에이전트 — 슈퍼투자자 + ARK + 애널리스트 컨센서스 기반 판정."""

from nuri.core.agent_config import AGENT_CONFIG
from nuri.trading.agents.base import AgentVerdict, BaseAgent

_CFG = AGENT_CONFIG.get("smart_money", {})
_CONF = _CFG.get("confidence", {})


class SmartMoneyAgent(BaseAgent):
    def __init__(self):
        super().__init__("smart_money")

    def analyze(self, ticker: str, db_path=None) -> AgentVerdict:
        score = 0
        reasons = []

        pct_high = _CFG.get("portfolio_pct_high", 5)
        upside_th = _CFG.get("upside_threshold", 20)
        downside_th = _CFG.get("downside_threshold", -10)

        # 1. 슈퍼투자자 보유 여부
        si_rows = self._safe_query(
            "SELECT investor, portfolio_pct FROM superinvestors WHERE ticker = ? ORDER BY portfolio_pct DESC",
            (ticker,),
            db_path,
        )
        if si_rows:
            investors = [r["investor"] for r in si_rows[:3]]
            max_pct = si_rows[0]["portfolio_pct"]
            score += min(2, len(si_rows))
            reasons.append(f"슈퍼투자자 {len(si_rows)}명 보유 ({', '.join(investors[:2])})")
            if max_pct > pct_high:
                score += 1
                reasons.append(f"최대 비중 {max_pct:.1f}%")

        # 2. 슈퍼투자자 포지션 변화 (NEW/INCREASED)
        change_rows = self._safe_query(
            "SELECT DISTINCT investor FROM superinvestors s1 "
            "WHERE ticker = ? AND filing_date = ("
            "  SELECT MAX(filing_date) FROM superinvestors WHERE investor = s1.investor"
            ") AND NOT EXISTS ("
            "  SELECT 1 FROM superinvestors s2 "
            "  WHERE s2.investor = s1.investor AND s2.ticker = s1.ticker "
            "  AND s2.filing_date < s1.filing_date"
            ")",
            (ticker,),
            db_path,
        )
        if change_rows:
            score += 1
            reasons.append(f"최근 신규 매수: {', '.join(r['investor'] for r in change_rows)}")

        # 3. 애널리스트 컨센서스
        est_rows = self._safe_query(
            "SELECT recommendation, target_mean, current_price, num_analysts "
            "FROM estimates WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (ticker,),
            db_path,
        )
        if est_rows:
            est = est_rows[0]
            rec = est.get("recommendation", "")
            target = est.get("target_mean")
            current = est.get("current_price")

            if rec in ("buy", "strong_buy"):
                score += 1
                reasons.append(f"애널리스트: {rec} ({est.get('num_analysts', '?')}명)")
            elif rec in ("sell", "strong_sell"):
                score -= 1
                reasons.append(f"애널리스트: {rec}")

            if target and current and current > 0:
                upside = (target - current) / current * 100
                if upside > upside_th:
                    score += 1
                    reasons.append(f"목표가 괴리 +{upside:.0f}%")
                elif upside < downside_th:
                    score -= 1
                    reasons.append(f"목표가 하회 {upside:.0f}%")

        # 4. ARK 최근 매매
        ark_rows = self._safe_query(
            "SELECT direction, shares FROM ark WHERE ticker = ? ORDER BY date DESC LIMIT 5",
            (ticker,),
            db_path,
        )
        if ark_rows:
            buys = sum(1 for r in ark_rows if r["direction"] == "Buy")
            sells = len(ark_rows) - buys
            if buys > sells:
                score += 1
                reasons.append(f"ARK 최근 매수 {buys}건")
            elif sells > buys:
                score -= 1
                reasons.append(f"ARK 최근 매도 {sells}건")

        if not reasons:
            return AgentVerdict(self.name, ticker, "HOLD", _CONF.get("no_data", 30), "스마트머니 데이터 없음")

        score_buy = _CFG.get("score_buy", 2)
        score_sell = _CFG.get("score_sell", -1)

        if score >= score_buy:
            action, confidence = (
                "BUY",
                min(
                    _CONF.get("buy_cap", 80),
                    _CONF.get("buy_base", 40) + score * _CONF.get("buy_multiplier", 12),
                ),
            )
        elif score <= score_sell:
            action, confidence = (
                "SELL",
                min(
                    _CONF.get("sell_cap", 70),
                    _CONF.get("sell_base", 40) + abs(score) * _CONF.get("sell_multiplier", 12),
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
            {"score": score, "n_superinvestors": len(si_rows)},
        )

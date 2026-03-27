"""펀더멘탈 분석 에이전트 — PE, ROE, 성장률, 부채 기반 판정."""
from nuri.trading.agents.base import AgentVerdict, BaseAgent


class FundamentalAgent(BaseAgent):
    def __init__(self):
        super().__init__("fundamental")

    def analyze(self, ticker: str, db_path=None) -> AgentVerdict:
        rows = self._safe_query(
            "SELECT * FROM fundamentals WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (ticker,), db_path,
        )
        if not rows:
            return AgentVerdict(self.name, ticker, "HOLD", 0, "펀더멘탈 데이터 없음")

        f = rows[0]
        pe = f.get("pe_ratio")
        roe = f.get("roe")
        growth = f.get("revenue_growth")
        debt = f.get("debt_to_equity")

        score = 0
        reasons = []

        # PE: 낮으면 저평가
        if pe and pe > 0:
            if pe < 15:
                score += 2
                reasons.append(f"PE {pe:.1f} (저평가)")
            elif pe < 25:
                score += 1
                reasons.append(f"PE {pe:.1f} (적정)")
            elif pe > 40:
                score -= 2
                reasons.append(f"PE {pe:.1f} (고평가)")
            else:
                reasons.append(f"PE {pe:.1f}")

        # ROE: 높으면 양호
        if roe:
            if roe > 0.2:
                score += 2
                reasons.append(f"ROE {roe*100:.0f}% (우수)")
            elif roe > 0.1:
                score += 1
                reasons.append(f"ROE {roe*100:.0f}%")
            elif roe < 0:
                score -= 1
                reasons.append(f"ROE {roe*100:.0f}% (적자)")

        # 성장률
        if growth:
            if growth > 0.2:
                score += 1
                reasons.append(f"매출성장 {growth*100:.0f}%")
            elif growth < -0.1:
                score -= 1
                reasons.append(f"매출감소 {growth*100:.0f}%")

        # 부채
        if debt and debt > 2.0:
            score -= 1
            reasons.append(f"부채비율 {debt:.1f}x (과다)")

        if score >= 2:
            action, confidence = "BUY", min(80, 50 + score * 10)
        elif score <= -2:
            action, confidence = "SELL", min(80, 50 + abs(score) * 10)
        else:
            action, confidence = "HOLD", 40 + abs(score) * 5

        return AgentVerdict(
            self.name, ticker, action, round(confidence, 1),
            "; ".join(reasons) or "데이터 제한적",
            {"pe": pe, "roe": roe, "growth": growth, "debt": debt},
        )

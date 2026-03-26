"""리스크 관리 에이전트 — VaR, 손절선, 포지션 집중도 기반 판정."""
from nuri.trading.agents.base import BaseAgent, AgentVerdict
from nuri.core.rules import STOCK_STOP_LOSS, MAX_SINGLE_POSITION


class RiskAgent(BaseAgent):
    def __init__(self):
        super().__init__("risk")

    def analyze(self, ticker: str, db_path=None) -> AgentVerdict:
        reasons = []
        score = 0  # 양수=안전, 음수=위험

        # 1. 손절선 체크
        holding = self._safe_query(
            "SELECT avg_price, quantity FROM portfolio WHERE ticker = ?",
            (ticker,), db_path,
        )
        price_row = self._safe_query(
            "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (ticker,), db_path,
        )

        if holding and price_row and holding[0]["avg_price"] and price_row[0]["close"]:
            avg = holding[0]["avg_price"]
            current = price_row[0]["close"]
            pnl_pct = (current - avg) / avg * 100

            if pnl_pct <= STOCK_STOP_LOSS:
                score -= 3
                reasons.append(f"손절선 돌파 ({pnl_pct:+.1f}% ≤ {STOCK_STOP_LOSS}%)")
            elif pnl_pct < -10:
                score -= 1
                reasons.append(f"손실 중 ({pnl_pct:+.1f}%)")
            elif pnl_pct > 20:
                reasons.append(f"수익 양호 ({pnl_pct:+.1f}%)")
                score += 1

        # 2. 변동성 체크 (최근 30일 수익률 표준편차)
        from nuri.core.db import query_df
        recent = query_df(
            "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 30",
            (ticker,), db_path=db_path,
        )
        if len(recent) >= 10:
            vol = recent["close"].pct_change().std() * 100
            if vol > 5:
                score -= 1
                reasons.append(f"고변동성 (일간σ {vol:.1f}%)")
            elif vol < 2:
                score += 1
                reasons.append(f"저변동성 (일간σ {vol:.1f}%)")

        # 3. 포지션 집중도
        total_rows = self._safe_query(
            "SELECT SUM(quantity * avg_price) as total FROM portfolio", db_path=db_path,
        )
        if holding and total_rows and total_rows[0]["total"]:
            weight = (holding[0]["quantity"] * holding[0]["avg_price"]) / total_rows[0]["total"]
            if weight > MAX_SINGLE_POSITION:
                score -= 1
                reasons.append(f"비중 초과 ({weight*100:.1f}% > {MAX_SINGLE_POSITION*100:.0f}%)")

        # 판정
        if score <= -2:
            action, confidence = "SELL", min(85, 50 + abs(score) * 15)
            if any("손절선" in r for r in reasons):
                confidence = 90  # 손절선 돌파는 최고 확신
        elif score >= 2:
            action, confidence = "BUY", 50 + score * 10
        else:
            action, confidence = "HOLD", 40 + abs(score) * 10

        return AgentVerdict(
            self.name, ticker, action, round(confidence, 1),
            "; ".join(reasons) or "리스크 정상",
            {"score": score},
        )

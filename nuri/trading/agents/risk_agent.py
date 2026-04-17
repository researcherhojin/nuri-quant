"""리스크 관리 에이전트 — VaR, 손절선, 포지션 집중도 기반 판정."""
from nuri.core.agent_config import AGENT_CONFIG
from nuri.core.rules import MAX_SINGLE_POSITION, get_stop_loss_for_account
from nuri.trading.agents.base import AgentVerdict, BaseAgent

_CFG = AGENT_CONFIG.get("risk", {})
_CONF = _CFG.get("confidence", {})


class RiskAgent(BaseAgent):
    def __init__(self):
        super().__init__("risk")

    def analyze(self, ticker: str, db_path=None) -> AgentVerdict:
        reasons = []
        score = 0  # 양수=안전, 음수=위험

        loss_threshold = _CFG.get("loss_threshold", -10)
        profit_threshold = _CFG.get("profit_threshold", 20)

        # 1. 손절선 체크 — A-3: 같은 row 의 account 로 threshold 조회 (pnl 과 일치)
        holding = self._safe_query(
            "SELECT account, avg_price, quantity FROM portfolio WHERE ticker = ?",
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

            # 같은 holding row 의 account 로 threshold 조회 — pnl_pct 는 이 row 의
            # cost basis 에서 계산됨. certification.py 와 동일한 per-row 패턴.
            stop_loss_threshold = get_stop_loss_for_account(holding[0]["account"])
            if pnl_pct < stop_loss_threshold:
                score -= 3
                reasons.append(f"손절선 돌파 ({pnl_pct:+.1f}% < {stop_loss_threshold}%)")
            elif pnl_pct < loss_threshold:
                score -= 1
                reasons.append(f"손실 중 ({pnl_pct:+.1f}%)")
            elif pnl_pct > profit_threshold:
                reasons.append(f"수익 양호 ({pnl_pct:+.1f}%)")
                score += 1

        # 2. 변동성 체크 (최근 30일 수익률 표준편차)
        vol_high = _CFG.get("volatility_high", 5)
        vol_low = _CFG.get("volatility_low", 2)

        from nuri.core.db import query_df
        recent = query_df(
            "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 30",
            (ticker,), db_path=db_path,
        )
        if len(recent) >= 10:
            vol = recent["close"].pct_change().std() * 100
            if vol > vol_high:
                score -= 1
                reasons.append(f"고변동성 (일간σ {vol:.1f}%)")
            elif vol < vol_low:
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
        score_sell = _CFG.get("score_sell", -2)
        score_buy = _CFG.get("score_buy", 2)

        if score <= score_sell:
            action, confidence = "SELL", min(
                _CONF.get("sell_cap", 85),
                _CONF.get("sell_base", 50) + abs(score) * _CONF.get("sell_multiplier", 15),
            )
            if any("손절선" in r for r in reasons):
                confidence = _CONF.get("stop_loss_override", 90)
        elif score >= score_buy:
            action, confidence = "BUY", _CONF.get("buy_base", 50) + score * _CONF.get("buy_multiplier", 10)
        else:
            action, confidence = "HOLD", _CONF.get("hold_base", 40) + abs(score) * _CONF.get("hold_multiplier", 10)

        return AgentVerdict(
            self.name, ticker, action, round(self.normalize_confidence(confidence), 1),
            "; ".join(reasons) or "리스크 정상",
            {"score": score},
        )

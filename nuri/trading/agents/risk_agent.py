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

        # 1. 손절선 체크 — A-3 per-row, A-4 codex P2: 모든 account row 를 iterate.
        # (이전: `holding[0]` 사용으로 SQLite 순서에 의존 → 다른 계좌가 breach 해도
        # 첫 row 만 확인하는 masking 버그. certification.py:304 동일 패턴으로 정렬.)
        holding = self._safe_query(
            "SELECT account, avg_price, quantity FROM portfolio WHERE ticker = ?",
            (ticker,), db_path,
        )
        price_row = self._safe_query(
            "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (ticker,), db_path,
        )

        if holding and price_row and price_row[0]["close"]:
            current = price_row[0]["close"]
            # 모든 row 에서 per-account breach check; 가장 큰 breach 만 보고.
            worst_breach: tuple[float, int] | None = None  # (pnl_pct, threshold)
            worst_loss_pct: float | None = None  # breach 없을 때만 사용
            for row in holding:
                avg = row["avg_price"]
                if not avg:
                    continue
                row_pnl = (current - avg) / avg * 100
                row_threshold = get_stop_loss_for_account(row["account"])
                if row_pnl < row_threshold:
                    if worst_breach is None or row_pnl < worst_breach[0]:
                        worst_breach = (row_pnl, row_threshold)
                elif worst_loss_pct is None or row_pnl < worst_loss_pct:
                    worst_loss_pct = row_pnl

            if worst_breach is not None:
                pnl_pct, th = worst_breach
                score -= 3
                reasons.append(f"손절선 돌파 ({pnl_pct:+.1f}% < {th}%)")
            elif worst_loss_pct is not None and worst_loss_pct < loss_threshold:
                score -= 1
                reasons.append(f"손실 중 ({worst_loss_pct:+.1f}%)")
            elif worst_loss_pct is not None and worst_loss_pct > profit_threshold:
                reasons.append(f"수익 양호 ({worst_loss_pct:+.1f}%)")
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

        # 3. 포지션 집중도 — A-4 codex Round 2 P2: 같은 ticker 가 여러 계좌에
        # 걸쳐 있으면 모든 row 의 exposure 를 합산. 이전 `holding[0]` 사용 시 첫
        # row 만 카운트 → 집중도 undercount (SQLite 순서에 의존).
        total_rows = self._safe_query(
            "SELECT SUM(quantity * avg_price) as total FROM portfolio", db_path=db_path,
        )
        if holding and total_rows and total_rows[0]["total"]:
            ticker_exposure = sum(
                (row["quantity"] or 0) * (row["avg_price"] or 0) for row in holding
            )
            weight = ticker_exposure / total_rows[0]["total"]
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

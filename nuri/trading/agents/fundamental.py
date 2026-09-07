"""펀더멘탈 분석 에이전트 — PE, ROE, 성장률, 부채 기반 판정."""

from nuri.core.agent_config import AGENT_CONFIG
from nuri.trading.agents.base import AgentVerdict, BaseAgent

_CFG = AGENT_CONFIG.get("fundamental", {})
_CONF = _CFG.get("confidence", {})


class FundamentalAgent(BaseAgent):
    def __init__(self):
        super().__init__("fundamental")

    def analyze(self, ticker: str, db_path=None) -> AgentVerdict:
        rows = self._safe_query(
            "SELECT * FROM fundamentals WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (ticker,),
            db_path,
        )
        if not rows:
            return self._no_data(
                ticker, rows, confidence=0, empty_reason="펀더멘탈 데이터 없음", failed_reason="펀더멘탈 조회 실패"
            )

        f = rows[0]
        pe = f.get("pe_ratio")
        roe = f.get("roe")
        growth = f.get("revenue_growth")
        debt = f.get("debt_to_equity")

        # 행은 있는데 소비하는 네 필드가 **전부 NULL** 이면 읽은 게 없다 (#1436, codex R8).
        # 앞 게이트(`if not rows`)는 행이 있으면 통과시키므로 여기서 한 번 더 본다. 전에는
        # `"; ".join(reasons) or "데이터 제한적"` 로 빠져나가 확신도 50 짜리 살아 있는 HOLD 가
        # 됐고, 실측 3-verdict 프로브에서 커버리지를 0.667 → 1.0 으로, HOLD 동의율을 0.50 →
        # 0.67 로 부풀렸다.
        #
        # ⚠️ 조건은 "평가할 값이 있었나" 지 **"근거 문구가 비었나" 가 아니다** (codex R9).
        # 처음엔 `not reasons` 로 썼는데, ROE 5% · 매출성장 5% · 부채 1.0 처럼 전부 중립
        # 구간인 행은 어느 임계도 안 건드려 근거가 비지만 **실제 데이터로 중립을 확인한
        # 판단**이다. 그걸 기권으로 깎는 것이 codex R1 이 `risk` 의 "리스크 정상" 에서 잡은
        # 오류와 같다 — 이 이슈에서 반대 방향으로 세 번째 밟은 함정이다.
        if pe is None and roe is None and growth is None and debt is None:
            return self._no_data(
                ticker,
                rows,
                confidence=0,
                empty_reason="펀더멘탈 데이터 제한적",
                failed_reason="펀더멘탈 조회 실패",
                data_points={"pe": pe, "roe": roe, "growth": growth, "debt": debt},
            )

        pe_undervalued = _CFG.get("pe_undervalued", 15)
        pe_fair = _CFG.get("pe_fair", 25)
        pe_overvalued = _CFG.get("pe_overvalued", 40)

        score = 0
        reasons = []

        # PE: 낮으면 저평가
        if pe and pe > 0:
            if pe < pe_undervalued:
                score += 2
                reasons.append(f"PE {pe:.1f} (저평가)")
            elif pe < pe_fair:
                score += 1
                reasons.append(f"PE {pe:.1f} (적정)")
            elif pe > pe_overvalued:
                score -= 2
                reasons.append(f"PE {pe:.1f} (고평가)")
            else:
                reasons.append(f"PE {pe:.1f}")

        # ROE: 높으면 양호
        roe_excellent = _CFG.get("roe_excellent", 0.20)
        roe_good = _CFG.get("roe_good", 0.10)
        if roe:
            if roe > roe_excellent:
                score += 2
                reasons.append(f"ROE {roe * 100:.0f}% (우수)")
            elif roe > roe_good:
                score += 1
                reasons.append(f"ROE {roe * 100:.0f}%")
            elif roe < 0:
                score -= 1
                reasons.append(f"ROE {roe * 100:.0f}% (적자)")

        # 성장률
        growth_strong = _CFG.get("growth_strong", 0.20)
        growth_decline = _CFG.get("growth_decline", -0.10)
        if growth:
            if growth > growth_strong:
                score += 1
                reasons.append(f"매출성장 {growth * 100:.0f}%")
            elif growth < growth_decline:
                score -= 1
                reasons.append(f"매출감소 {growth * 100:.0f}%")

        # 부채
        if debt and debt > _CFG.get("debt_high", 2.0):
            score -= 1
            reasons.append(f"부채비율 {debt:.1f}x (과다)")

        score_buy = _CFG.get("score_buy", 2)
        score_sell = _CFG.get("score_sell", -2)
        conf_cap = _CONF.get("cap", 80)
        buy_base = _CONF.get("buy_base", 50)
        buy_mult = _CONF.get("buy_multiplier", 10)
        sell_base = _CONF.get("sell_base", 50)
        sell_mult = _CONF.get("sell_multiplier", 10)
        hold_base = _CONF.get("hold_base", 40)
        hold_mult = _CONF.get("hold_multiplier", 5)

        if score >= score_buy:
            action, confidence = "BUY", min(conf_cap, buy_base + score * buy_mult)
        elif score <= score_sell:
            action, confidence = "SELL", min(conf_cap, sell_base + abs(score) * sell_mult)
        else:
            action, confidence = "HOLD", hold_base + abs(score) * hold_mult

        return AgentVerdict(
            self.name,
            ticker,
            action,
            round(self.normalize_confidence(confidence), 1),
            # 값은 읽었는데 전부 중립 구간이면 근거 문구가 빈다 — 그건 **판단**이다
            # (`risk` 의 "리스크 정상" 과 같은 부류). 위 게이트가 부재를 이미 걸렀다.
            "; ".join(reasons) or "펀더멘탈 중립",
            {"pe": pe, "roe": roe, "growth": growth, "debt": debt},
        )

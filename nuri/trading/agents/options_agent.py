"""옵션 시장 에이전트 — Put/Call Ratio 기반 시장 심리 판정.

CBOE PCR 데이터로 시장 공포/탐욕 수준을 판단한다.
PCR 높음(≥1.2) = 극도 공포 → 역발상 매수 신호.
PCR 낮음(≤0.7) = 과도한 낙관 → 경계 신호.
데이터 없으면 graceful HOLD 반환.
"""

from datetime import datetime

from nuri.core.agent_config import AGENT_CONFIG
from nuri.core.timezone import kst_now, today_kst
from nuri.trading.agents.base import AgentVerdict, BaseAgent, finite_values

_CFG = AGENT_CONFIG.get("options", {})
_CONF = _CFG.get("confidence", {})


class OptionsAgent(BaseAgent):
    def __init__(self):
        super().__init__("options")

    def analyze(self, ticker: str, db_path=None) -> AgentVerdict:
        lookback = _CFG.get("lookback_days", 5)
        rows = self._safe_query(
            "SELECT value, source, date FROM macro WHERE indicator='put_call_ratio' AND date <= ? ORDER BY date DESC LIMIT ?",
            # 출처별로 고르므로 넉넉히 읽는다 — 다른 출처 행이 끼어 있어도 한 출처로 lookback 을 채운다.
            (today_kst(), lookback * 4),
            db_path,
        )
        if not rows:
            return self._no_data(
                ticker,
                rows,
                confidence=_CONF.get("no_data", 0),
                empty_reason="PCR 데이터 없음",
                failed_reason="PCR 조회 실패",
            )

        max_age = _CFG.get("max_age_hours", 132)

        def _age_hours(row) -> float:
            try:
                return (kst_now().date() - datetime.strptime(row.get("date"), "%Y-%m-%d").date()).days * 24
            except (TypeError, ValueError):
                return float("inf")

        # 임계와 같은 스케일의 출처(config `preferred_sources`)가 유효 기간 안에 있으면 그 계열을 쓴다.
        # CBOE 행은 미국 거래일, 폴백(yfinance SPY) 행은 KST 날짜라 주말 폴백 행이 복구된 CBOE 보다
        # 늦은 날짜로 남는다 — "최신 행의 출처" 만 따르면 복구 뒤에도 다른 스케일을 읽었다 (#1748).
        preferred = set(_CFG.get("preferred_sources", []))
        fresh_preferred = next((r for r in rows if r.get("source") in preferred and _age_hours(r) <= max_age), None)
        source = (fresh_preferred or rows[0]).get("source")
        # 다른 출처 시계열은 평균/추세에서 섞지 않는다 — 고른 출처의 최근 lookback 행만.
        same_source = [r for r in rows if r.get("source") == source][:lookback]
        as_of = same_source[0].get("date")
        metadata = {"scope": "us_market", "source": source, "as_of": as_of}
        if _age_hours(same_source[0]) > max_age:
            return AgentVerdict(
                self.name, ticker, "HOLD", 0, "미국 시장 PCR — 자료 유효 기간 초과", metadata, abstained=True
            )
        values = finite_values(r["value"] for r in same_source)
        if not values:
            # 조회는 성공했고 행도 있는데 값이 전부 NULL — 실패가 아니라 부재다.
            return AgentVerdict(
                self.name, ticker, "HOLD", _CONF.get("no_data", 0), "PCR 값 없음", metadata, abstained=True
            )

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
            f"미국 시장 PCR ({source}, {as_of}): " + "; ".join(reasons),
            {
                "pcr_avg": round(pcr, 3),
                "pcr_latest": round(values[0], 3) if values else None,
                "lookback_count": len(values),
                **metadata,
            },
        )

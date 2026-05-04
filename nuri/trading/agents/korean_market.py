"""
한국 시장 에이전트 — .KS 종목 전용 분석.

KOSPI/KOSDAQ 구분, 환율 영향, 외국인/기관 수급,
한국 시장 특성 (공매도 제한, 배당락 등)을 반영한다.

US 종목에는 HOLD(중립)을 반환하여 합의에 영향을 주지 않는다.
"""
import logging

from nuri.core.agent_config import AGENT_CONFIG
from nuri.trading.agents.base import AgentVerdict, BaseAgent

logger = logging.getLogger(__name__)

_CFG = AGENT_CONFIG.get("korean_market", {})


def _calibrate_fx_thresholds(db_path=None) -> tuple[float, float]:
    """90일 환율 데이터로 동적 FX 임계값 계산.

    약세: 90일 평균 + 1 표준편차
    강세: 90일 평균 - 1 표준편차
    데이터 부족 시 기본값 반환.
    """
    fx_weak_default = _CFG.get("fx_weak_default", 1400)
    fx_strong_default = _CFG.get("fx_strong_default", 1250)

    from nuri.core.db import query_df
    df = query_df(
        "SELECT value FROM macro WHERE indicator='usd_krw' ORDER BY date DESC LIMIT 90",
        db_path=db_path,
    )
    if df.empty or len(df) < _CFG.get("fx_calibration_min", 30):
        return fx_weak_default, fx_strong_default

    mean = df["value"].mean()
    std = df["value"].std()
    weak = round(mean + std, 0)
    strong = round(mean - std, 0)
    return max(weak, _CFG.get("fx_weak_floor", 1300)), min(strong, _CFG.get("fx_strong_ceil", 1350))

# KOSPI/KOSDAQ 구분
KOSDAQ_TICKERS = {
    "247540.KS", "068270.KS", "035720.KS", "035420.KS",
    "263750.KS", "293490.KS", "112040.KS",
}

# 수출 비중 높은 섹터
EXPORT_SECTORS = {"Semiconductor", "Automobile", "Shipbuilding", "Steel", "Tech"}


class KoreanMarketAgent(BaseAgent):
    """한국 시장 전문 에이전트."""

    def __init__(self):
        super().__init__("korean_market")

    def analyze(self, ticker: str, db_path=None) -> AgentVerdict:
        """한국 종목 분석. US 종목은 중립 반환."""
        # US 종목은 패스
        if not ticker.endswith(".KS"):
            return AgentVerdict(
                agent_name=self.name, ticker=ticker,
                action="HOLD", confidence=_CFG.get("us_confidence", 50.0),
                reasoning="US ticker — Korean market agent neutral",
                data_points={"is_korean": False},
            )

        score = float(_CFG.get("score_base", 50))
        reasons = []
        data = {"is_korean": True, "market": "KOSDAQ" if ticker in KOSDAQ_TICKERS else "KOSPI"}

        # 1. 환율 영향 (동적 캘리브레이션)
        fx_rate = self._get_fx_rate(db_path)
        data["fx_rate"] = fx_rate
        sector = self._get_sector(ticker, db_path)
        data["sector"] = sector
        fx_weak, fx_strong = _calibrate_fx_thresholds(db_path)
        data["fx_weak_threshold"] = fx_weak
        data["fx_strong_threshold"] = fx_strong

        if fx_rate:
            if fx_rate >= fx_weak and sector in EXPORT_SECTORS:
                score += _CFG.get("fx_export_strong", 10)
                reasons.append(f"원화약세({fx_rate:.0f}) 수출주 유리")
            elif fx_rate >= fx_weak and sector not in EXPORT_SECTORS:
                score += _CFG.get("fx_nonexport_weak", -5)
                reasons.append(f"원화약세({fx_rate:.0f}) 내수주 부담")
            elif fx_rate <= fx_strong and sector not in EXPORT_SECTORS:
                score += _CFG.get("fx_nonexport_strong", 5)
                reasons.append(f"원화강세({fx_rate:.0f}) 내수주 유리")

        # 2. 외국인 수급 (institutional_flows 테이블)
        foreign_net = self._get_foreign_flow(ticker, db_path)
        data["foreign_net"] = foreign_net
        if foreign_net is not None:
            if foreign_net > 0:
                score += _CFG.get("foreign_positive", 8)
                reasons.append("외국인 순매수")
            elif foreign_net < 0:
                score += _CFG.get("foreign_negative", -8)
                reasons.append("외국인 순매도")

        # 3. 가격 모멘텀 (20일 수익률)
        momentum = self._get_momentum(ticker, db_path)
        data["momentum_20d"] = momentum
        if momentum is not None:
            if momentum > _CFG.get("momentum_positive_threshold", 5):
                score += _CFG.get("momentum_positive_score", 5)
                reasons.append(f"20일 모멘텀 +{momentum:.1f}%")
            elif momentum < _CFG.get("momentum_negative_threshold", -10):
                score += _CFG.get("momentum_negative_score", -10)
                reasons.append(f"20일 모멘텀 {momentum:.1f}%")

        # 4. KOSDAQ 변동성 프리미엄
        if ticker in KOSDAQ_TICKERS:
            score += _CFG.get("kosdaq_discount", -3)
            reasons.append("KOSDAQ 변동성 할인")

        # 5. 매크로 이벤트 반영 (#247) — export_surge/demand_growth 시 한국 종목 부스트
        macro_boost = self._get_macro_event_boost(sector, db_path)
        data["macro_event_boost"] = macro_boost
        if macro_boost != 0:
            score += macro_boost
            if macro_boost > 0:
                reasons.append(f"매크로 이벤트 긍정적 (+{macro_boost})")
            else:
                reasons.append(f"매크로 이벤트 부정적 ({macro_boost})")

        # 판정
        score_base = _CFG.get("score_base", 50)
        if score >= _CFG.get("score_buy", 65):
            action = "BUY"
        elif score <= _CFG.get("score_sell", 35):
            action = "SELL"
        else:
            action = "HOLD"

        return AgentVerdict(
            agent_name=self.name, ticker=ticker,
            action=action, confidence=round(self.normalize_confidence(min(abs(score - score_base) * 2, 100)), 1),
            reasoning="; ".join(reasons) if reasons else "Korean market neutral",
            data_points=data,
        )

    def _get_fx_rate(self, db_path=None) -> float | None:
        """최신 KRW/USD 환율."""
        rows = self._safe_query(
            "SELECT value FROM macro WHERE indicator='usd_krw' ORDER BY date DESC LIMIT 1",
            db_path=db_path,
        )
        return rows[0]["value"] if rows else None

    def _get_sector(self, ticker: str, db_path=None) -> str:
        """종목 섹터 조회."""
        rows = self._safe_query(
            "SELECT sector FROM portfolio WHERE ticker=? LIMIT 1",
            (ticker,), db_path=db_path,
        )
        return rows[0]["sector"] if rows else ""

    def _get_foreign_flow(self, ticker: str, db_path=None) -> float | None:
        """최근 외국인 순매수."""
        rows = self._safe_query(
            "SELECT foreign_net FROM institutional_flows "
            "WHERE ticker=? ORDER BY date DESC LIMIT 1",
            (ticker,), db_path=db_path,
        )
        return rows[0]["foreign_net"] if rows else None

    def _get_macro_event_boost(self, sector: str, db_path=None) -> int:
        """최근 3일 매크로 이벤트에서 한국 관련 시그널 추출 (#247).

        export_surge, demand_growth → 수출 섹터(반도체 등)에 긍정적
        trade_war, geopolitical_escalation → 전체 부정적
        """
        rows = self._safe_query(
            """SELECT category, COUNT(*) as cnt, AVG(confidence) as avg_conf
               FROM macro_events
               WHERE published_at >= date('now', '-3 days')
                 AND confidence >= 0.3
                 AND category IN ('export_surge', 'demand_growth', 'trade_war', 'geopolitical_escalation')
               GROUP BY category""",
            db_path=db_path,
        )
        if not rows:
            return 0

        boost = 0
        for row in rows:
            cat = row["category"]
            cnt = row["cnt"]
            conf = row["avg_conf"] or 0.5
            if cnt < 2:
                continue  # 1건은 노이즈 가능성
            if cat in ("export_surge", "demand_growth") and sector in EXPORT_SECTORS:
                boost += int(min(cnt * conf * 3, 8))  # 최대 +8
            elif cat in ("trade_war", "geopolitical_escalation"):
                boost -= int(min(cnt * conf * 2, 6))  # 최대 -6
        return boost

    def _get_momentum(self, ticker: str, db_path=None) -> float | None:
        """20일 가격 모멘텀."""
        rows = self._safe_query(
            "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 21",
            (ticker,), db_path=db_path,
        )
        if len(rows) < 21:
            return None
        latest = rows[0]["close"]
        past = rows[-1]["close"]
        if past and past > 0:
            return (latest - past) / past * 100
        return None

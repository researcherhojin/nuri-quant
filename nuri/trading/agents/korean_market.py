"""
한국 시장 에이전트 — .KS 종목 전용 분석.

KOSPI/KOSDAQ 구분, 환율 영향, 외국인/기관 수급,
한국 시장 특성 (공매도 제한, 배당락 등)을 반영한다.

US 종목에는 HOLD(중립)을 반환하여 합의에 영향을 주지 않는다.
"""
import logging

from nuri.trading.agents.base import AgentVerdict, BaseAgent

logger = logging.getLogger(__name__)

# 환율 임계값 (KRW/USD) — 90일 이동평균 기반 동적 캘리브레이션
# 기본값은 2024~2026 평균 기반. _calibrate_fx_thresholds()로 DB 데이터 반영.
FX_WEAK_KRW = 1400  # 원화 약세 → 수출주 유리 (기본값, 동적 갱신)
FX_STRONG_KRW = 1250  # 원화 강세 → 내수주 유리 (기본값, 동적 갱신)


def _calibrate_fx_thresholds(db_path=None) -> tuple[float, float]:
    """90일 환율 데이터로 동적 FX 임계값 계산.

    약세: 90일 평균 + 1 표준편차
    강세: 90일 평균 - 1 표준편차
    데이터 부족 시 기본값 반환.
    """
    from nuri.core.db import query_df
    df = query_df(
        "SELECT value FROM macro WHERE indicator='usd_krw' ORDER BY date DESC LIMIT 90",
        db_path=db_path,
    )
    if df.empty or len(df) < 30:
        return FX_WEAK_KRW, FX_STRONG_KRW

    mean = df["value"].mean()
    std = df["value"].std()
    weak = round(mean + std, 0)
    strong = round(mean - std, 0)
    return max(weak, 1300), min(strong, 1350)  # 최소/최대 안전장치

# KOSPI/KOSDAQ 구분
KOSDAQ_TICKERS = {
    "247540.KS", "068270.KS", "035720.KS", "035420.KS",
    "263750.KS", "293490.KS", "112040.KS",
}

# 수출 비중 높은 섹터
EXPORT_SECTORS = {"Semiconductor", "Automobile", "Shipbuilding", "Steel", "EV/AI"}


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
                action="HOLD", confidence=50.0,
                reasoning="US ticker — Korean market agent neutral",
                data_points={"is_korean": False},
            )

        score = 50.0  # 기본 중립
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
                score += 10
                reasons.append(f"원화약세({fx_rate:.0f}) 수출주 유리")
            elif fx_rate >= fx_weak and sector not in EXPORT_SECTORS:
                score -= 5
                reasons.append(f"원화약세({fx_rate:.0f}) 내수주 부담")
            elif fx_rate <= fx_strong and sector not in EXPORT_SECTORS:
                score += 5
                reasons.append(f"원화강세({fx_rate:.0f}) 내수주 유리")

        # 2. 외국인 수급 (institutional_flows 테이블)
        foreign_net = self._get_foreign_flow(ticker, db_path)
        data["foreign_net"] = foreign_net
        if foreign_net is not None:
            if foreign_net > 0:
                score += 8
                reasons.append("외국인 순매수")
            elif foreign_net < 0:
                score -= 8
                reasons.append("외국인 순매도")

        # 3. 가격 모멘텀 (20일 수익률)
        momentum = self._get_momentum(ticker, db_path)
        data["momentum_20d"] = momentum
        if momentum is not None:
            if momentum > 5:
                score += 5
                reasons.append(f"20일 모멘텀 +{momentum:.1f}%")
            elif momentum < -10:
                score -= 10
                reasons.append(f"20일 모멘텀 {momentum:.1f}%")

        # 4. KOSDAQ 변동성 프리미엄
        if ticker in KOSDAQ_TICKERS:
            score -= 3  # KOSDAQ은 변동성 리스크 할인
            reasons.append("KOSDAQ 변동성 할인")

        # 판정
        if score >= 65:
            action = "BUY"
        elif score <= 35:
            action = "SELL"
        else:
            action = "HOLD"

        return AgentVerdict(
            agent_name=self.name, ticker=ticker,
            action=action, confidence=min(abs(score - 50) * 2, 100),
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

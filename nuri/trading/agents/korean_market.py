"""
한국 시장 에이전트 — .KS 종목 전용 분석.

KOSPI/KOSDAQ 구분, 환율 영향, 외국인/기관 수급,
한국 시장 특성 (공매도 제한, 배당락 등)을 반영한다.

US 종목에는 HOLD(중립)을 반환하여 합의에 영향을 주지 않는다.
"""

import logging

import numpy as np
import pandas as pd

from nuri.core.agent_config import AGENT_CONFIG
from nuri.trading.agents.base import AgentVerdict, BaseAgent, QueryRows, finite_or_none

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

    # #1278: 미래 날짜 행이 90일 창에 섞이면 평균·표준편차가 오염된다 — 최신 1건뿐
    # 아니라 **시계열도** 상한이 필요하다.
    from nuri.core.timezone import today_kst

    df = query_df(
        "SELECT value FROM macro WHERE indicator='usd_krw' AND date <= ? ORDER BY date DESC LIMIT 90",
        (today_kst(),),
        db_path=db_path,
    )
    # NULL/NaN 값 행은 행 수에 넣지 않는다 — 30행이 전부 NULL 이면 예전엔 임계가 NaN 으로 data_points 에 실렸다 (#1481)
    values = np.asarray(pd.to_numeric(df["value"], errors="coerce"), dtype=float) if not df.empty else np.array([])
    values = values[np.isfinite(values)]
    if len(values) < _CFG.get("fx_calibration_min", 30):
        return fx_weak_default, fx_strong_default

    mean = float(values.mean())
    std = float(values.std(ddof=1))
    weak = round(mean + std, 0)
    strong = round(mean - std, 0)
    return max(weak, _CFG.get("fx_weak_floor", 1300)), min(strong, _CFG.get("fx_strong_ceil", 1350))


# KOSPI/KOSDAQ 구분
KOSDAQ_TICKERS = {
    "247540.KS",
    "068270.KS",
    "035720.KS",
    "035420.KS",
    "263750.KS",
    "293490.KS",
    "112040.KS",
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
                agent_name=self.name,
                ticker=ticker,
                action="HOLD",
                confidence=_CFG.get("us_confidence", 50.0),
                reasoning="US ticker — Korean market agent neutral",
                data_points={"is_korean": False},
                # 전문 범위 밖이다 — 의견이 아니라 부재다 (#1436). CLAUDE.md 의 Specialization
                # 표가 "Returns low-conf HOLD outside specialization by design" 이라 적어둔 그
                # 경로인데, 지금까지 확신도 50 짜리 HOLD 표로 세어져 **모든 US 종목**에서
                # 동의율과 패널 커버리지를 부풀렸다.
                abstained=True,
            )

        score = float(_CFG.get("score_base", 50))
        reasons = []
        data = {"is_korean": True, "market": "KOSDAQ" if ticker in KOSDAQ_TICKERS else "KOSPI"}

        # 조회 실패를 누적한다 (#1446). 헬퍼 5 개가 각자 예외를 삼켜 반환값만 보면 "값이
        # 없다" 와 "조회가 실패했다" 가 구분되지 않았고, 그래서 DB 장애가 상시 부재로
        # 기록됐다 — #1436 이 다른 9 개 에이전트에서 없앤 형태가 여기만 남아 있었다.
        db_failures: list[str] = []

        # 1. 환율 영향 (동적 캘리브레이션)
        # 세 입력(환율·외국인·모멘텀)도 non-finite 면 '없음' 으로 — 캘리브레이션만 정제하면 반쪽이다 (Codex P2, #1481)
        fx_rate = finite_or_none(self._get_fx_rate(db_path, failures=db_failures))
        data["fx_rate"] = fx_rate
        sector = self._get_sector(ticker, db_path, failures=db_failures)
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
        foreign_net = finite_or_none(self._get_foreign_flow(ticker, db_path, failures=db_failures))
        data["foreign_net"] = foreign_net
        if foreign_net is not None:
            if foreign_net > 0:
                score += _CFG.get("foreign_positive", 8)
                reasons.append("외국인 순매수")
            elif foreign_net < 0:
                score += _CFG.get("foreign_negative", -8)
                reasons.append("외국인 순매도")

        # 3. 가격 모멘텀 (20일 수익률)
        momentum = finite_or_none(self._get_momentum(ticker, db_path, failures=db_failures))
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
        macro_events: list[str] = []
        macro_boost = self._get_macro_event_boost(sector, db_path, saw_input=macro_events, failures=db_failures)
        data["macro_event_boost"] = macro_boost
        if macro_boost != 0:
            score += macro_boost
            if macro_boost > 0:
                reasons.append(f"매크로 이벤트 긍정적 (+{macro_boost})")
            else:
                reasons.append(f"매크로 이벤트 부정적 ({macro_boost})")

        # 값 입력 셋이 **전부 부재**면 이 종목에 대해 평가한 것이 없다 (#1436, codex R11).
        # `fundamental` 의 전부-NULL 게이트와 같은 조건이다. 전에는 그대로 내려가
        # "Korean market neutral" HOLD 가 살아 있는 의견으로 집계돼 `panel_coverage` 와
        # HOLD 동의율을 부풀렸다.
        #
        # ⚠️ 하나라도 있으면 **판단**이다 — 값을 읽고 어느 임계도 안 건드린 것은 중립 판단이지
        # 기권이 아니다 (`risk` 의 "리스크 정상"). `sector` 와 KOSDAQ 할인은 값 입력이 아니다:
        # 전자는 수정자고, 후자는 종목 소속에서 나오는 상수라 이 종목의 상태에 대한 근거가 아니다.
        # 매크로 이벤트 부스트는 **값 입력이다** — 첫 판이 이걸 빼먹어, 이벤트가 실제로 잡힌
        # 종목까지 기권으로 깎았다 (`test_negative_macro_event_appends_negative_reason` 이 잡음).
        # 그 다음 판은 `macro_boost == 0` 으로 봤는데 그것도 틀렸다 (codex R12): 수출주에
        # demand_growth +6 과 trade_war -6 이 함께 오면 순 0 이지만 평가는 한 것이다.
        # **점수가 아니라 입력의 존재**를 본다.
        #
        # 조회 **실패** 는 여기서 못 가른다 — 헬퍼 5 개가 각자 예외를 삼켜 신호가 안 온다.
        # 그건 #1446 이고, 그때까지 실패는 이 부재 경로로 합류한다.
        if fx_rate is None and foreign_net is None and momentum is None and not macro_events:
            return self._no_data(
                ticker,
                QueryRows(failed=bool(db_failures)),
                confidence=0,
                empty_reason="한국 시장 데이터 없음",
                failed_reason="한국 시장 조회 실패",
                data_points={**data, "read_failures": db_failures},
            )

        # 판정
        score_base = _CFG.get("score_base", 50)
        if score >= _CFG.get("score_buy", 65):
            action = "BUY"
        elif score <= _CFG.get("score_sell", 35):
            action = "SELL"
        else:
            action = "HOLD"

        return AgentVerdict(
            agent_name=self.name,
            ticker=ticker,
            action=action,
            confidence=round(self.normalize_confidence(min(abs(score - score_base) * 2, 100)), 1),
            reasoning="; ".join(reasons) if reasons else "Korean market neutral",
            data_points=data,
        )

    def _get_fx_rate(self, db_path=None, failures: list | None = None) -> float | None:
        """최신 KRW/USD 환율.

        `failures` 를 주면 조회 실패를 append 한다 (#1446). 반환값 `None` 은 "환율을 모른다"
        와 "조회가 실패했다" 를 뭉갠다 — 후자를 정상 부재로 기록하면 DB 장애가 상시 기권으로
        위장된다(#1436 이 다른 9 개 에이전트에서 없앤 바로 그 형태). 반환형을 안 바꾸는 이유는
        이 private 헬퍼들을 직접 부르는 테스트가 여럿이라서다.
        """
        # #1278: 날짜 상한 + 미래행 경고는 공용 리더가 담당한다 (nuri/core/fx.py). `_safe_query` 의 예외 삼킴을 유지하려 쿼리 형태만 맞춘다.
        from nuri.core.timezone import today_kst

        rows = self._safe_query(
            "SELECT value FROM macro WHERE indicator='usd_krw' AND date <= ? ORDER BY date DESC LIMIT 1",
            (today_kst(),),
            db_path=db_path,
        )
        if failures is not None and rows.failed:
            failures.append("fx")
        return rows[0]["value"] if rows else None

    def _get_sector(self, ticker: str, db_path=None, failures: list | None = None) -> str:
        """종목 섹터 조회. `failures` 규약은 `_get_fx_rate` 참조 (#1446)."""
        rows = self._safe_query(
            "SELECT sector FROM portfolio WHERE ticker=? LIMIT 1",
            (ticker,),
            db_path=db_path,
        )
        if failures is not None and rows.failed:
            failures.append("sector")
        return rows[0]["sector"] if rows else ""

    def _get_foreign_flow(self, ticker: str, db_path=None, failures: list | None = None) -> float | None:
        """최근 외국인 순매수. `failures` 규약은 `_get_fx_rate` 참조 (#1446)."""
        rows = self._safe_query(
            "SELECT foreign_net FROM institutional_flows WHERE ticker=? ORDER BY date DESC LIMIT 1",
            (ticker,),
            db_path=db_path,
        )
        if failures is not None and rows.failed:
            failures.append("foreign_flow")
        return rows[0]["foreign_net"] if rows else None

    def _get_macro_event_boost(
        self, sector: str, db_path=None, saw_input: list | None = None, failures: list | None = None
    ) -> int:
        """최근 3일 매크로 이벤트에서 한국 관련 시그널 추출 (#247).

        export_surge, demand_growth → 수출 섹터(반도체 등)에 긍정적
        trade_war, geopolitical_escalation → 전체 부정적

        `saw_input` 을 주면 **점수에 실제로 기여한 이벤트가 있었는지**를 append 한다
        (#1436, codex R12). 반환값 0 은 "이벤트 없음" 과 "상쇄돼 0" 을 구분하지 못한다 —
        수출주에 demand_growth +6 과 trade_war -6 이 함께 오면 순 0 이지만 **평가는 했다.**
        그걸 부재로 읽으면 근거가 있는 판단을 기권으로 깎는다. 반환형을 안 바꾸는 이유는
        이 private 메서드를 직접 부르는 테스트가 6 곳이라서다.
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
        if failures is not None and rows.failed:
            failures.append("macro_events")
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
                if saw_input is not None:
                    saw_input.append(cat)
            elif cat in ("trade_war", "geopolitical_escalation"):
                boost -= int(min(cnt * conf * 2, 6))  # 최대 -6
                if saw_input is not None:
                    saw_input.append(cat)
        return boost

    def _get_momentum(self, ticker: str, db_path=None, failures: list | None = None) -> float | None:
        """20일 가격 모멘텀. `failures` 규약은 `_get_fx_rate` 참조 (#1446)."""
        rows = self._safe_query(
            "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 21",
            (ticker,),
            db_path=db_path,
        )
        if failures is not None and rows.failed:
            failures.append("momentum")
        if len(rows) < 21:
            return None
        latest = rows[0]["close"]
        past = rows[-1]["close"]
        if past and past > 0:
            return (latest - past) / past * 100
        return None

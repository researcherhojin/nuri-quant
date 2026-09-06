"""
멀티 에이전트 프레임워크 — SIEGE Multi-Agent 패턴.

각 에이전트는 독립적으로 종목을 분석하여 verdict(판정)을 내린다.
Consensus engine이 가중 투표로 최종 결론을 도출한다.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AgentVerdict:
    """에이전트 개별 판정.

    Alpha 와 portfolio 신호를 분리 (PR A, 2026-04-21 codex bubble-bear #1):
    - `alpha_action` — 시장 기대 (LONG/SHORT/FLAT). Risk veto 와 UI action 노출
      을 구동.
    - `portfolio_action` — 포트폴리오 룰 신호 (REBALANCE/TRIM/HEDGE/NONE). UI
      에 병렬 표시. veto 경로에 영향 없음.
    - legacy `action` (BUY/SELL/HOLD) — 두 axis 에서 derive (back-compat). 기존
      consumer (tracker.py, /decisions UI, Learning Memory hit 판정) 가 계속
      사용. axis 가 None 이면 agent 별 기존 logic 유지.
    """

    agent_name: str
    ticker: str
    action: str  # "BUY", "SELL", "HOLD"
    confidence: float  # 0~100 (정규화 후)
    reasoning: str  # 판정 근거 (1~2문장)
    data_points: dict = field(default_factory=dict)  # 사용한 데이터
    alpha_action: str | None = None  # "LONG" | "SHORT" | "FLAT" | None
    portfolio_action: str | None = None  # "REBALANCE" | "TRIM" | "HEDGE" | "NONE" | None
    # 에이전트가 예외/타임아웃으로 **판단을 못 한** 경우 True (#1028). 그때도 패널이
    # 무너지지 않게 HOLD/0 verdict 를 채우는데(#130), 그 대체물이 진짜 HOLD 와
    # 구분되지 않으면 거부권 무력화·동의율 부풀림이 조용히 일어난다.
    degraded: bool = False

    @property
    def abstained(self) -> bool:
        """정상 실행됐지만 **의견을 내지 않은** verdict (#1436).

        `degraded` 가 못 덮는 절반이다. 저쪽은 예외·타임아웃으로 에이전트가 **죽은** 경우만
        True 인데, 멀쩡히 돌고도 확신도 0 을 내는 경로가 따로 있다 — `fundamental` 의
        "펀더멘탈 데이터 없음", `technical` 의 "데이터 부족", 그리고 주식 티커를 받은
        `crypto` 처럼 입력은 있으나 그 입력으로 이 종목에 대해 할 말이 없는 경우다.
        산출물은 양쪽 다 HOLD/0 으로 같고, 그래서 `degraded` 만 거르면 자리표시자가
        의견으로 집계된다 (#1436 실측: 180 셀 중 36 개, `crypto` 는 18/18).

        **왜 `degraded` 를 넓히지 않았나**: crypto·retail 은 거의 매일 기권한다. 둘을
        `degraded_agents` 에 넣으면 그 목록이 매 행 가득 차고, 진짜 사고(에이전트 크래시)가
        노이즈에 묻힌다 — #1028 이 만든 인시던트 신호가 죽는다. 원인이 다르므로 축을 나눈다.

        **왜 확신도로 판정하나**: 에이전트마다 기권 표시를 손으로 붙이면 빠뜨린다.
        확신도 0 은 정의상 "확신 없음" 이고, 확신 0 짜리 의견은 의견이 아니다.
        """
        return not self.degraded and self.confidence == 0


def _load_norm_config() -> dict:
    """confidence_normalization 설정 로드 (import cycle 방지를 위해 lazy)."""
    from nuri.core.agent_config import AGENT_CONFIG

    return AGENT_CONFIG.get("confidence_normalization", {})


class BaseAgent(ABC):
    """투자 분석 에이전트 기반 클래스."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def analyze(self, ticker: str, db_path=None) -> AgentVerdict:
        """종목을 분석하여 verdict 반환."""
        ...

    def normalize_confidence(self, raw: float) -> float:
        """에이전트별 confidence를 0-100 통일 스케일로 정규화.

        config/agents.yaml의 confidence_normalization.scales에서
        에이전트별 [raw_min, raw_max] 범위를 읽어 선형 매핑.
        설정이 없거나 비활성화면 원본 반환.
        """
        cfg = _load_norm_config()
        if not cfg.get("enabled", False):
            return raw
        scale = cfg.get("scales", {}).get(self.name)
        if not scale:
            return raw
        raw_min = scale.get("raw_min", 0)
        raw_max = scale.get("raw_max", 100)
        if raw_max <= raw_min:
            return raw
        normalized = (raw - raw_min) / (raw_max - raw_min) * 100
        return max(0.0, min(100.0, normalized))

    def _safe_query(self, sql, params=(), db_path=None):
        """DB 쿼리 안전 래퍼."""
        from nuri.core.db import query

        try:
            return query(sql, params, db_path=db_path)
        except Exception:
            return []

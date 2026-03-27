"""
멀티 에이전트 프레임워크 — SIEGE Multi-Agent 패턴.

각 에이전트는 독립적으로 종목을 분석하여 verdict(판정)을 내린다.
Consensus engine이 가중 투표로 최종 결론을 도출한다.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AgentVerdict:
    """에이전트 개별 판정."""
    agent_name: str
    ticker: str
    action: str             # "BUY", "SELL", "HOLD"
    confidence: float       # 0~100
    reasoning: str          # 판정 근거 (1~2문장)
    data_points: dict = field(default_factory=dict)  # 사용한 데이터


class BaseAgent(ABC):
    """투자 분석 에이전트 기반 클래스."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def analyze(self, ticker: str, db_path=None) -> AgentVerdict:
        """종목을 분석하여 verdict 반환."""
        ...

    def _safe_query(self, sql, params=(), db_path=None):
        """DB 쿼리 안전 래퍼."""
        from nuri.core.db import query
        try:
            return query(sql, params, db_path=db_path)
        except Exception:
            return []

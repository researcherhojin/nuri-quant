"""은퇴한 Reddit 입력의 호환 슬롯 — 외부 수집과 과거 행 조회 없이 명시적으로 기권한다 (#1979)."""

from nuri.trading.agents.base import AgentVerdict, BaseAgent


class RetailAgent(BaseAgent):
    def __init__(self):
        super().__init__("retail")

    def analyze(self, ticker: str, db_path=None) -> AgentVerdict:
        # 과거 WSB 행을 다시 투표로 쓰지 않는다. 0 은 확신도 부재이며 투자 임계값이 아니다.
        return AgentVerdict(self.name, ticker, "HOLD", 0.0, "Reddit 입력 은퇴 (#1979)", {}, abstained=True)

"""
멀티 에이전트 프레임워크 — SIEGE Multi-Agent 패턴.

각 에이전트는 독립적으로 종목을 분석하여 verdict(판정)을 내린다.
Consensus engine이 가중 투표로 최종 결론을 도출한다.
"""

import math
import numbers
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


def finite_or_none(value):
    """숫자면 finite 일 때만 그대로, NaN/±inf/None 은 None — `data_points` 는 strict JSON(`allow_nan=False`) 을 지난다.

    #1479(technical) → #1481(korean_market · wallstreet): 행 수만 세고 값의 유효성은 안 본 자리마다 NaN 이
    `/api/consensus/{ticker}` 를 500 으로 죽였다. `data_points` 에 넣는 파생 숫자는 이 함수를 거친다.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, numbers.Integral):  # int · np.int64 → int
        return int(value)
    if isinstance(
        value, numbers.Real
    ):  # float · np.float32/64 → float (Codex P2: np.float32 는 float 서브클래스가 아니다)
        f = float(value)
        return f if math.isfinite(f) else None
    return value


def finite_values(values) -> list[float]:
    """iterable 에서 finite 로 변환되는 값만 float 리스트로 — 문자열·None·NaN·±inf 는 버린다."""
    out: list[float] = []
    for v in values:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            out.append(f)
    return out


def finite_or_zero(value) -> float:
    """yfinance 필드용 — `x or 0` 은 NaN 을 못 거른다(`nan or 0 == nan`)."""
    out = finite_or_none(value)
    return float(out) if isinstance(out, (int, float)) and not isinstance(out, bool) else 0.0


class QueryRows(list):
    """`BaseAgent._safe_query` 결과 — 빈 결과와 **조회 실패** 를 구분한다 (#1436).

    `list` 하위 타입이라 `if not rows` · 순회 · 인덱싱이 그대로 동작한다. 실패를 알아야 하는
    호출부만 `rows.failed` 를 본다.
    """

    def __init__(self, iterable=(), *, failed: bool = False):
        super().__init__(iterable)
        self.failed = failed


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

    # 에이전트가 정상 실행됐지만 **의견을 내지 않은** 경우 True (#1436). `degraded` 가 못
    # 덮는 절반이다 — 저쪽은 예외·타임아웃으로 에이전트가 **죽은** 경우만 잡는데, 멀쩡히
    # 돌고도 "데이터 없음" 으로 자리표시자를 내는 경로가 따로 있다. 산출물이 같은 HOLD/낮은
    # 확신도라 `degraded` 만 거르면 자리표시자가 의견으로 집계된다.
    #
    # ⚠️ **확신도로 파생하지 않는다.** 처음엔 `confidence == 0` 으로 유도했는데 틀렸다
    # (codex R1): `normalize_confidence` 가 낮은 원점수를 0 으로 깎는다 — `risk` 는 raw
    # 0~40 이, `macro` 는 0~30 이 전부 0.0 이 된다. 실측에서 `risk` 의 "리스크 정상"
    # (평가해서 위험 없음을 확인한 **진짜 판단**) 3 건이 확신도 0 이었고, 파생 방식은 그걸
    # 기권으로 오분류해 `risk_veto_available=False` 로 뒤집어 적었다 — 거부권을 평가했는데
    # "평가 못 함" 으로 기록하는 정반대 오류다. 생산 지점이 스스로 선언해야 한다.
    #
    # 새 자리표시자 경로를 만들면 이 플래그를 붙일 것. 잠금은
    # `tests/trading/agents/test_abstained_verdicts.py::TestFailureIsNeverReportedAsAbstention`
    # 인데, **이건 실패↔기권 오분류만 잡지 "플래그를 아예 안 붙인 새 자리표시자" 는 못 잡는다**
    # (codex R6 P2). 그 형태를 구조로 잡으려던 AST 스윕은 지역변수·키워드 인자·헬퍼 이동에
    # 네 번 뚫려 폐기했다 — 자리표시자와 진짜 저확신 판단을 코드 모양으로는 못 가른다
    # (`risk` 의 "리스크 정상" 이 그 반례다). 남은 방어는 리뷰이므로 여기 적어 둔다.
    abstained: bool = False


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

    def _safe_query(self, sql, params=(), db_path=None) -> "QueryRows":
        """DB 쿼리 안전 래퍼.

        예외를 삼키되 **삼켰다는 사실을 남긴다** (#1436). 전에는 그냥 `[]` 를 돌려줘서
        "테이블이 비었다" 와 "DB 가 죽었다" 가 호출부에서 완전히 같아 보였고, 그 결과 DB
        장애가 6 개 에이전트에서 전부 **정상 기권**(abstained)으로 기록됐다 — 실패를 상시
        부재로 위장하는 것은 #1028 이 막으려던 바로 그 형태다.

        삼킴 자체는 유지한다. 26 개 호출처 중 상당수가 선택적 보강 쿼리(환율·섹터·합계)라
        예외를 올리면 부수 실패가 에이전트 전체를 죽인다.
        """
        from nuri.core.db import query

        try:
            return QueryRows(query(sql, params, db_path=db_path))
        except Exception:
            return QueryRows(failed=True)

    def _no_data(
        self,
        ticker: str,
        rows,
        *,
        confidence: float,
        empty_reason: str,
        failed_reason: str,
        data_points: dict | None = None,
    ) -> AgentVerdict:
        """데이터가 없을 때의 자리표시자 — **부재와 실패를 갈라서** 낸다 (#1436).

        `rows` 가 `_safe_query` 결과이고 그 조회가 실패했다면 `degraded`(사고), 조회는
        됐는데 비었다면 `abstained`(상시 기권)다. 둘을 뭉뚱그리면 DB·소스 장애가 정상
        기권으로 위장돼 인시던트 신호가 죽는다.
        """
        if rows.failed:
            # 확신도 0 — `confidence` 인자를 **의도적으로 버린다** (#1436, codex R6).
            # `action_scores[action] += w * (conf/100)` 이라 0 이 아니면 죽은 에이전트가 계속
            # 투표한다. 러너가 만드는 degraded verdict 는 처음부터 0 이었는데
            # (`consensus/__init__.py`), `_no_data` 가 에이전트별 `no_data` 값(smart_money 30 ·
            # wallstreet 20 · macro 30)을 그대로 물려주면서 **0 이 아닌 첫 degraded** 가 생겼다.
            # 실측: smart_money 자리표시자 conf 30 이 HOLD 에 0.0228 을 더해 final_confidence 를
            # 79.3 → 71.9 로 끌어내렸다 — UI 는 그동안 "가중치 0 — 합의에 미반영" 이라고 적고
            # 있었다. 기권(#1437)과 달리 이쪽은 미룰 이유가 없다: **실패한 조회에 표를 주는
            # 것은 어느 축에서도 옳지 않다.**
            return AgentVerdict(self.name, ticker, "HOLD", 0.0, failed_reason, data_points or {}, degraded=True)
        return AgentVerdict(self.name, ticker, "HOLD", confidence, empty_reason, data_points or {}, abstained=True)

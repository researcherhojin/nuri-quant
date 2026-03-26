"""
멀티 에이전트 합의 엔진 — SIEGE Swarm Intelligence 패턴.

5개 전문 에이전트의 독립 판정을 가중 투표로 합산.
에이전트별 가중치는 과거 적중률(Learning Memory)에서 동적 계산.
의견 불일치는 명시적으로 기록하여 감사 가능.

사용법:
    python -m nuri.agents.consensus
    python -m nuri.agents.consensus --ticker TSLA
"""
import argparse
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime

from nuri.trading.agents.base import AgentVerdict
from nuri.trading.agents.technical import TechnicalAgent
from nuri.trading.agents.fundamental import FundamentalAgent
from nuri.trading.agents.macro_agent import MacroAgent
from nuri.trading.agents.risk_agent import RiskAgent
from nuri.trading.agents.smart_money import SmartMoneyAgent
from nuri.trading.agents.wallstreet import WallStreetAgent
from nuri.core.db import get_tickers

logger = logging.getLogger(__name__)

# 기본 가중치 (과거 데이터 없을 때)
DEFAULT_WEIGHTS = {
    "technical": 0.20,
    "fundamental": 0.15,
    "macro": 0.15,
    "risk": 0.25,      # 리스크는 거부권 수준으로 높음
    "smart_money": 0.10,
    "wallstreet": 0.15, # 애널리스트 등급 + 실적 서프라이즈 + 내부자
}

ALL_AGENTS = [
    TechnicalAgent(),
    FundamentalAgent(),
    MacroAgent(),
    RiskAgent(),
    SmartMoneyAgent(),
    WallStreetAgent(),
]


@dataclass
class ConsensusResult:
    """멀티 에이전트 합의 결과."""
    ticker: str
    final_action: str       # "BUY", "SELL", "HOLD"
    final_confidence: float # 0~100
    agreement_rate: float   # 0~1 (동일 action 비율)
    verdicts: list[AgentVerdict]
    dissent: list[str]      # 반대 의견 에이전트 목록
    reasoning: str          # 합의 근거 요약


def _compute_weights(db_path=None) -> dict[str, float]:
    """Learning Memory에서 에이전트별 가중치 동적 계산.

    아직 에이전트별 적중률 데이터가 없으면 DEFAULT_WEIGHTS 반환.
    향후: recommendations 테이블에서 에이전트별 hit rate를 추적하여 가중치 보정.
    """
    # TODO: 추적 데이터 축적 후 동적 가중치 구현
    # 현재는 기본 가중치 사용
    return dict(DEFAULT_WEIGHTS)


def analyze_ticker(ticker: str, db_path=None) -> ConsensusResult:
    """단일 종목에 대해 6개 에이전트 분석 + 합의."""
    import concurrent.futures
    weights = _compute_weights(db_path)
    verdicts = []

    # 에이전트 병렬 실행 (타임아웃 10초)
    def _run_agent(agent):
        try:
            return agent.analyze(ticker, db_path)
        except Exception as e:
            return AgentVerdict(agent.name, ticker, "HOLD", 0, f"에러: {e}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(_run_agent, agent): agent for agent in ALL_AGENTS}
        for future in concurrent.futures.as_completed(futures, timeout=15):
            try:
                verdicts.append(future.result())
            except concurrent.futures.TimeoutError:
                agent = futures[future]
                verdicts.append(AgentVerdict(agent.name, ticker, "HOLD", 0, "타임아웃"))
            except Exception as e:
                agent = futures[future]
                verdicts.append(AgentVerdict(agent.name, ticker, "HOLD", 0, f"에러: {e}"))

    # 가중 투표
    action_scores = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
    for v in verdicts:
        w = weights.get(v.agent_name, 0.1)
        action_scores[v.action] += w * (v.confidence / 100)

    # 리스크 에이전트 거부권: SELL + confidence >= 80 이면 전체 override
    risk_v = next((v for v in verdicts if v.agent_name == "risk"), None)
    if risk_v and risk_v.action == "SELL" and risk_v.confidence >= 80:
        final_action = "SELL"
        final_confidence = risk_v.confidence
        reasoning = f"리스크 에이전트 거부권 발동: {risk_v.reasoning}"
    else:
        # 최고 점수 action
        final_action = max(action_scores, key=action_scores.get)
        total_weight = sum(action_scores.values())
        final_confidence = (action_scores[final_action] / total_weight * 100) if total_weight > 0 else 0

        # 합의 근거 조립
        supporters = [v for v in verdicts if v.action == final_action]
        reasoning = " | ".join(f"{v.agent_name}: {v.reasoning}" for v in supporters)

    # 동의율
    agree_count = sum(1 for v in verdicts if v.action == final_action)
    agreement_rate = agree_count / len(verdicts) if verdicts else 0

    # 반대 의견
    dissent = [
        f"{v.agent_name}({v.action}, {v.confidence:.0f}): {v.reasoning}"
        for v in verdicts if v.action != final_action
    ]

    return ConsensusResult(
        ticker=ticker,
        final_action=final_action,
        final_confidence=round(final_confidence, 1),
        agreement_rate=round(agreement_rate, 2),
        verdicts=verdicts,
        dissent=dissent,
        reasoning=reasoning,
    )


def analyze_portfolio(db_path=None) -> list[ConsensusResult]:
    """전 보유종목에 대해 멀티 에이전트 합의."""
    tickers = get_tickers(db_path=db_path)
    results = []
    for ticker in tickers:
        result = analyze_ticker(ticker, db_path)
        results.append(result)
        logger.info(f"{ticker}: {result.final_action} (conf={result.final_confidence:.0f}, agree={result.agreement_rate:.0%})")
    return results


def print_consensus(results: list[ConsensusResult]) -> None:
    """합의 결과 CLI 출력."""
    if not results:
        print("합의 결과 없음")
        return

    print(f"\n{'=' * 85}")
    print(f"  Multi-Agent Consensus ({len(results)} tickers)")
    print(f"{'=' * 85}")
    print(f"  {'Ticker':<10} {'Action':<6} {'Conf':>5} {'Agree':>6} {'Tech':>5} {'Fund':>5} {'Macro':>5} {'Risk':>5} {'Smart':>5}")
    print(f"  {'-' * 78}")

    for r in sorted(results, key=lambda x: x.final_confidence, reverse=True):
        agent_map = {v.agent_name: v for v in r.verdicts}
        cols = []
        for name in ["technical", "fundamental", "macro", "risk", "smart_money"]:
            v = agent_map.get(name)
            if v:
                icon = {"BUY": "B", "SELL": "S", "HOLD": "H"}.get(v.action, "?")
                cols.append(f"{icon}{v.confidence:.0f}")
            else:
                cols.append("--")

        print(f"  {r.ticker:<10} {r.final_action:<6} {r.final_confidence:>4.0f} {r.agreement_rate:>5.0%} "
              f"{'  '.join(f'{c:>4}' for c in cols)}")

    # 반대 의견 요약
    dissents = [(r.ticker, r.dissent) for r in results if r.dissent]
    if dissents:
        print(f"\n  Dissent ({sum(len(d) for _, d in dissents)} opinions):")
        for ticker, ds in dissents[:5]:
            for d in ds:
                print(f"    {ticker}: {d}")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Nuri-Quant 멀티 에이전트 합의")
    parser.add_argument("--ticker", help="특정 종목만")
    args = parser.parse_args()

    if args.ticker:
        result = analyze_ticker(args.ticker)
        print_consensus([result])
        if result.dissent:
            print("  반대 의견:")
            for d in result.dissent:
                print(f"    {d}")
    else:
        results = analyze_portfolio()
        print_consensus(results)

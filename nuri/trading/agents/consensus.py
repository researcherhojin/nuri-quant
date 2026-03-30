"""
멀티 에이전트 합의 엔진 — SIEGE Swarm Intelligence 패턴.

5개 전문 에이전트의 독립 판정을 가중 투표로 합산.
에이전트별 가중치는 과거 적중률(Learning Memory)에서 동적 계산.
의견 불일치는 명시적으로 기록하여 감사 가능.

사용법:
    python -m nuri.trading.agents.consensus
    python -m nuri.trading.agents.consensus --ticker TSLA
"""
import argparse
import logging
from dataclasses import dataclass

from nuri.core.agent_config import AGENT_CONFIG
from nuri.core.db import get_tickers
from nuri.trading.agents.base import AgentVerdict
from nuri.trading.agents.crypto_agent import CryptoAgent
from nuri.trading.agents.fundamental import FundamentalAgent
from nuri.trading.agents.korean_market import KoreanMarketAgent
from nuri.trading.agents.macro_agent import MacroAgent
from nuri.trading.agents.options_agent import OptionsAgent
from nuri.trading.agents.retail_agent import RetailAgent
from nuri.trading.agents.risk_agent import RiskAgent
from nuri.trading.agents.smart_money import SmartMoneyAgent
from nuri.trading.agents.technical import TechnicalAgent
from nuri.trading.agents.wallstreet import WallStreetAgent

logger = logging.getLogger(__name__)

# 기본 가중치 (과거 데이터 없을 때)
# 7→10 에이전트 확장: 기존 에이전트 비중 소폭 하향, 신규 3개 배분
DEFAULT_WEIGHTS = {
    "technical": 0.16,       # 18→16
    "fundamental": 0.12,     # 14→12
    "macro": 0.12,           # 14→12
    "risk": 0.20,            # 22→20 (거부권 유지)
    "smart_money": 0.08,     # 9→8
    "wallstreet": 0.11,      # 13→11
    "korean_market": 0.08,   # 10→8 (.KS 종목에서만 실질 영향)
    "options": 0.08,          # 신규: PCR 기반 시장 심리
    "crypto": 0.05,           # 신규: BTC 리스크 선호
    "retail": 0.00,           # 신규: WSB 센티먼트 (데이터 안정화까지 0%)
}

ALL_AGENTS = [
    TechnicalAgent(),
    FundamentalAgent(),
    MacroAgent(),
    RiskAgent(),
    SmartMoneyAgent(),
    WallStreetAgent(),
    KoreanMarketAgent(),
    OptionsAgent(),
    CryptoAgent(),
    RetailAgent(),
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
    """Learning Memory + recommendations 기반 동적 가중치 계산.

    recommendations 테이블에서 에이전트별 적중률을 추적하여 가중치를 보정한다.
    30일 이상 경과한 추천 중 outcome_30d가 있는 건으로 계산.
    데이터 부족 시(< 10건) DEFAULT_WEIGHTS 반환.
    """
    from nuri.core.db import query

    _lm = AGENT_CONFIG.get("consensus", {}).get("learning_memory", {})
    lookback = _lm.get("lookback_days", 180)
    min_records = _lm.get("min_records", 10)

    rows = query(
        """
        SELECT signals FROM recommendations
        WHERE outcome_30d IS NOT NULL
          AND date >= date('now', ? || ' days')
        """,
        (f"-{lookback}",),
        db_path=db_path,
    )

    if len(rows) < min_records:
        return dict(DEFAULT_WEIGHTS)

    # 에이전트별 적중률 계산
    # signals 필드에 에이전트 verdict가 JSON으로 저장되어 있으면 파싱
    import json
    agent_hits: dict[str, list[bool]] = {name: [] for name in DEFAULT_WEIGHTS}

    for row in rows:
        try:
            signals_str = row["signals"]
            if not signals_str:
                continue
            # signals 필드가 에이전트 verdict JSON이 아닌 경우 스킵
            data = json.loads(signals_str) if isinstance(signals_str, str) else None
            if not isinstance(data, dict) or "verdicts" not in data:
                continue

            outcome = row.get("outcome_30d", 0) if hasattr(row, "get") else 0
            is_positive = outcome > 0

            for v in data["verdicts"]:
                agent_name = v.get("agent_name", "")
                action = v.get("action", "HOLD")
                if agent_name in agent_hits:
                    # BUY가 양수 수익이면 적중, SELL이 음수 수익이면 적중
                    if action == "BUY":
                        agent_hits[agent_name].append(is_positive)
                    elif action == "SELL":
                        agent_hits[agent_name].append(not is_positive)
                    # HOLD는 적중 판정 제외
        except (json.JSONDecodeError, TypeError, KeyError):
            continue

    # 적중률 기반 가중치 계산
    min_agent_records = _lm.get("min_agent_records", 5)
    hit_rates = {}
    for name, hits in agent_hits.items():
        if len(hits) >= min_agent_records:
            hit_rates[name] = sum(hits) / len(hits)

    if not hit_rates:
        return dict(DEFAULT_WEIGHTS)

    # 적중률을 가중치로 변환 (정규화)
    # 기본 가중치의 ±adjustment_range 범위 내에서 조정
    adj_range = _lm.get("adjustment_range", 0.30)
    min_weight = _lm.get("min_weight_floor", 0.03)
    weights = dict(DEFAULT_WEIGHTS)
    for name, rate in hit_rates.items():
        base = DEFAULT_WEIGHTS.get(name, 0.1)
        # 50% 적중률 = 기본값, 70% = +30%, 30% = -30%
        adjustment = (rate - 0.5) * 1.5  # -0.75 ~ +0.75 범위
        adjusted = base * (1 + max(-adj_range, min(adj_range, adjustment)))
        weights[name] = max(min_weight, adjusted)

    # 총합 1.0으로 정규화
    total = sum(weights.values())
    if total > 0:
        weights = {k: v / total for k, v in weights.items()}

    return weights


def analyze_ticker(ticker: str, db_path=None) -> ConsensusResult:
    """단일 종목에 대해 10개 에이전트 분석 + 합의."""
    import concurrent.futures
    weights = _compute_weights(db_path)
    verdicts = []

    # 에이전트 병렬 실행 (타임아웃 10초)
    def _run_agent(agent):
        try:
            return agent.analyze(ticker, db_path)
        except Exception as e:
            return AgentVerdict(agent.name, ticker, "HOLD", 0, f"에러: {e}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(ALL_AGENTS)) as executor:
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

    # 리스크 에이전트 거부권: SELL + confidence >= threshold 이면 전체 override
    veto_threshold = AGENT_CONFIG.get("consensus", {}).get("risk_veto_threshold", 80)
    risk_v = next((v for v in verdicts if v.agent_name == "risk"), None)
    if risk_v and risk_v.action == "SELL" and risk_v.confidence >= veto_threshold:
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

    print(f"\n{'=' * 120}")
    print(f"  Multi-Agent Consensus ({len(results)} tickers, 10 agents)")
    print(f"{'=' * 120}")
    header_agents = ["Tech", "Fund", "Macro", "Risk", "Smart", "Wall", "KR", "Opt", "Crypto", "Ret"]
    print(f"  {'Ticker':<10} {'Action':<6} {'Conf':>5} {'Agree':>6} " + " ".join(f"{h:>5}" for h in header_agents))
    print(f"  {'-' * 110}")

    agent_order = ["technical", "fundamental", "macro", "risk", "smart_money",
                    "wallstreet", "korean_market", "options", "crypto", "retail"]

    for r in sorted(results, key=lambda x: x.final_confidence, reverse=True):
        agent_map = {v.agent_name: v for v in r.verdicts}
        cols = []
        for name in agent_order:
            v = agent_map.get(name)
            if v:
                icon = {"BUY": "B", "SELL": "S", "HOLD": "H"}.get(v.action, "?")
                cols.append(f"{icon}{v.confidence:.0f}")
            else:
                cols.append("--")

        print(f"  {r.ticker:<10} {r.final_action:<6} {r.final_confidence:>4.0f} {r.agreement_rate:>5.0%} "
              f"{' '.join(f'{c:>5}' for c in cols)}")

    # 반대 의견 요약
    dissents = [(r.ticker, r.dissent) for r in results if r.dissent]
    if dissents:
        print(f"\n  Dissent ({sum(len(d) for _, d in dissents)} opinions):")
        for ticker, ds in dissents[:5]:
            for d in ds:
                print(f"    {ticker}: {d}")

    # 가격 타겟 출력
    try:
        from nuri.trading.recommend.price_targets import calculate_targets, format_target_tree
        buy_hold = [r for r in results if r.final_action in ("BUY", "HOLD")]
        if buy_hold:
            print(f"\n{'=' * 85}")
            print("  Price Targets (BUY/HOLD 종목)")
            print(f"{'=' * 85}")
            for r in sorted(buy_hold, key=lambda x: x.final_confidence, reverse=True)[:10]:
                target = calculate_targets(r.ticker)
                if "error" not in target:
                    print(format_target_tree(target))
                    print(f"  {'─' * 50}")
    except Exception as e:
        logger.debug("가격 타겟 출력 실패: %s", e)

    # 외부 데이터 요약 출력
    try:
        from nuri.collectors.external import get_external
        tickers_with_data = set()
        for r in results:
            ext = get_external(r.ticker)
            if ext:
                tickers_with_data.add(r.ticker)
        if tickers_with_data:
            print(f"\n{'=' * 85}")
            print(f"  External Data ({len(tickers_with_data)} tickers)")
            print(f"{'=' * 85}")
            for r in results:
                if r.ticker not in tickers_with_data:
                    continue
                ext = get_external(r.ticker)
                parts = []
                for d in ext:
                    if d["data_type"] == "consensus":
                        parts.append(f"TipRanks:{d['value']}")
                    elif d["data_type"] == "superinvestor_count":
                        parts.append(f"슈퍼투자자:{d['value']}명")
                    elif d["data_type"] == "target_price" and d["source"] == "tipranks":
                        parts.append(f"목표가:${d['numeric_value']:,.0f}")
                if parts:
                    print(f"  {r.ticker:<10} {' | '.join(parts)}")
    except Exception as e:
        logger.debug("외부 데이터 출력 실패: %s", e)
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

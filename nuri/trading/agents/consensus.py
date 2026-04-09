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


def _build_consensus(ticker: str, verdicts: list[AgentVerdict], weights: dict) -> ConsensusResult:
    """가중 투표로 합의 결과 산출 (analyze_ticker / stream_analyze_ticker 공용)."""
    action_scores = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
    for v in verdicts:
        w = weights.get(v.agent_name, 0.1)
        action_scores[v.action] += w * (v.confidence / 100)

    # 리스크 에이전트 거부권
    veto_threshold = AGENT_CONFIG.get("consensus", {}).get("risk_veto_threshold", 80)
    risk_v = next((v for v in verdicts if v.agent_name == "risk"), None)
    if risk_v and risk_v.action == "SELL" and risk_v.confidence >= veto_threshold:
        final_action = "SELL"
        final_confidence = risk_v.confidence
        reasoning = f"리스크 에이전트 거부권 발동: {risk_v.reasoning}"
    else:
        final_action = max(action_scores, key=action_scores.get)
        total_weight = sum(action_scores.values())
        final_confidence = (action_scores[final_action] / total_weight * 100) if total_weight > 0 else 0
        supporters = [v for v in verdicts if v.action == final_action]
        reasoning = " | ".join(f"{v.agent_name}: {v.reasoning}" for v in supporters)

    agree_count = sum(1 for v in verdicts if v.action == final_action)
    agreement_rate = agree_count / len(verdicts) if verdicts else 0
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


def analyze_ticker(ticker: str, db_path=None) -> ConsensusResult:
    """단일 종목에 대해 10개 에이전트 분석 + 합의.

    한 에이전트가 외부 API 등으로 느려져도 전체가 죽지 않도록,
    `as_completed` iterator의 TimeoutError를 잡고 미완료 future는
    HOLD/0/타임아웃 verdict로 폴백한다 (#130 회귀 방지).

    Timeout은 `config/agents.yaml` `consensus.agent_timeout_sec` 에서 설정.
    """
    import concurrent.futures

    weights = _compute_weights(db_path)
    verdicts: list[AgentVerdict] = []
    agent_timeout = AGENT_CONFIG.get("consensus", {}).get("agent_timeout_sec", 60)

    def _run_agent(agent):
        try:
            return agent.analyze(ticker, db_path)
        except Exception as e:  # noqa: BLE001 — 에이전트 예외를 verdict로 흡수
            return AgentVerdict(agent.name, ticker, "HOLD", 0, f"에러: {e}")

    # `with` 대신 명시적 shutdown — 미완료 future를 cancel하고 즉시 반환.
    # `with` 블록은 __exit__에서 wait=True로 모든 future 완료를 기다리므로
    # timeout의 의미가 사라짐.
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(ALL_AGENTS))
    try:
        futures = {executor.submit(_run_agent, agent): agent for agent in ALL_AGENTS}
        completed: set[concurrent.futures.Future] = set()
        try:
            for future in concurrent.futures.as_completed(futures, timeout=agent_timeout):
                completed.add(future)
                agent = futures[future]
                try:
                    verdicts.append(future.result())
                except Exception as e:  # noqa: BLE001
                    verdicts.append(
                        AgentVerdict(agent.name, ticker, "HOLD", 0, f"에러: {e}")
                    )
        except concurrent.futures.TimeoutError:
            # 전체 batch timeout — 미완료 future는 폴백 verdict로
            for future, agent in futures.items():
                if future not in completed:
                    verdicts.append(
                        AgentVerdict(agent.name, ticker, "HOLD", 0, "타임아웃")
                    )
    finally:
        # cancel_futures: 큐에 대기중인(아직 시작 안 한) future 취소
        # wait=False: 실행 중인 future가 끝날 때까지 기다리지 않음
        executor.shutdown(wait=False, cancel_futures=True)

    return _build_consensus(ticker, verdicts, weights)


def stream_analyze_ticker(ticker: str, db_path=None):
    """단일 종목 스트리밍 분석 — 에이전트 완료 순서대로 verdict 생성.

    `analyze_ticker`와 동일한 timeout 폴백 로직 (#130). 미완료 에이전트는
    timeout 도달 시점에 일괄 HOLD/0/타임아웃 verdict로 yield.

    Yields:
        ("verdict", AgentVerdict) — 에이전트 완료 시마다
        ("consensus", ConsensusResult) — 전체 합의 완료 시
    """
    import concurrent.futures

    weights = _compute_weights(db_path)
    verdicts: list[AgentVerdict] = []
    agent_timeout = AGENT_CONFIG.get("consensus", {}).get("agent_timeout_sec", 60)

    def _run_agent(agent):
        try:
            return agent.analyze(ticker, db_path)
        except Exception as e:  # noqa: BLE001
            return AgentVerdict(agent.name, ticker, "HOLD", 0, f"에러: {e}")

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(ALL_AGENTS))
    try:
        futures = {executor.submit(_run_agent, agent): agent for agent in ALL_AGENTS}
        completed: set[concurrent.futures.Future] = set()
        try:
            for future in concurrent.futures.as_completed(futures, timeout=agent_timeout):
                completed.add(future)
                agent = futures[future]
                try:
                    verdict = future.result()
                except Exception as e:  # noqa: BLE001
                    verdict = AgentVerdict(agent.name, ticker, "HOLD", 0, f"에러: {e}")
                verdicts.append(verdict)
                yield ("verdict", verdict)
        except concurrent.futures.TimeoutError:
            for future, agent in futures.items():
                if future not in completed:
                    verdict = AgentVerdict(agent.name, ticker, "HOLD", 0, "타임아웃")
                    verdicts.append(verdict)
                    yield ("verdict", verdict)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    yield ("consensus", _build_consensus(ticker, verdicts, weights))


def analyze_portfolio(db_path=None) -> list[ConsensusResult]:
    """전 보유종목에 대해 멀티 에이전트 합의."""
    tickers = get_tickers(db_path=db_path)
    results = []
    for ticker in tickers:
        result = analyze_ticker(ticker, db_path)
        results.append(result)
        logger.info(f"{ticker}: {result.final_action} (conf={result.final_confidence:.0f}, agree={result.agreement_rate:.0%})")
    return results


def save_to_recommendations(results: list[ConsensusResult], db_path=None) -> int:
    """ConsensusResult를 recommendations 테이블에 INSERT.

    이전: `make consensus`는 stdout만 출력하고 DB에 저장하지 않아 frontend
    /decision 페이지가 빈 상태로 표시되었음 (routing failure).
    이제 합의 직후 자동 저장하여 evidence trail 연속성 보장.

    중복 방지: (date, ticker) 같은 날 재실행 시 INSERT OR REPLACE.
    """
    import json

    from nuri.core.db import get_db, query
    from nuri.core.timezone import today_kst

    if not results:
        return 0

    today = today_kst()
    records = []
    for r in results:
        # 현재가 조회
        price_row = query(
            "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (r.ticker,),
            db_path=db_path,
        )
        entry_price = price_row[0]["close"] if price_row else 0.0

        verdicts_json = json.dumps(
            [
                {
                    "agent_name": v.agent_name,
                    "ticker": v.ticker,
                    "action": v.action,
                    "confidence": v.confidence,
                    "reasoning": v.reasoning,
                    "data_points": v.data_points,
                }
                for v in r.verdicts
            ],
            ensure_ascii=False,
        )

        records.append(
            {
                "date": today,
                "ticker": r.ticker,
                "action": r.final_action,
                "confidence": r.final_confidence,
                "regime": None,  # consensus는 regime 정보 없음 — tracker.py가 채움
                "signals": json.dumps(
                    {
                        "agreement_rate": r.agreement_rate,
                        "dissent_count": len(r.dissent),
                        "reasoning": r.reasoning,
                    }
                ),
                "entry_price": entry_price,
                "agent_verdicts": verdicts_json,
                "scoring_detail": None,
            }
        )

    with get_db(db_path) as conn:
        # 같은 날 같은 종목 재실행 시 덮어쓰기 (REPLACE)
        # UNIQUE 제약(date, ticker)이 있으면 REPLACE 동작, 없으면 단순 INSERT
        conn.executemany(
            """INSERT OR REPLACE INTO recommendations
               (date, ticker, action, confidence, regime, signals, entry_price,
                agent_verdicts, scoring_detail)
               VALUES (:date, :ticker, :action, :confidence, :regime, :signals, :entry_price,
                       :agent_verdicts, :scoring_detail)""",
            records,
        )
        return len(records)


def print_consensus(results: list[ConsensusResult], *, verbose: bool = False) -> None:
    """합의 결과 CLI 출력.

    Args:
        results: ConsensusResult 리스트
        verbose: True 시 종목별 supporting verdicts (합의 의견의 reasoning) 함께 출력
    """
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

    # 합의 supporters reasoning 출력 (verbose 모드 또는 단일 종목)
    show_supporters = verbose or len(results) == 1
    if show_supporters:
        for r in sorted(results, key=lambda x: x.final_confidence, reverse=True):
            supporters = [v for v in r.verdicts if v.action == r.final_action]
            if not supporters:
                continue
            print(f"\n  ▸ {r.ticker} {r.final_action} ({r.final_confidence:.0f}, agree={r.agreement_rate:.0%}) — supporters:")
            for v in sorted(supporters, key=lambda x: x.confidence, reverse=True):
                print(f"      {v.agent_name}({v.confidence:.0f}): {v.reasoning}")

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
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="합의 의견의 supporting verdicts reasoning 함께 출력")
    args = parser.parse_args()

    if args.ticker:
        result = analyze_ticker(args.ticker)
        print_consensus([result], verbose=args.verbose)
        # 단일 종목도 DB 저장 (frontend evidence 연속성)
        saved = save_to_recommendations([result])
        if saved:
            logger.info(f"recommendations 테이블에 {saved}건 저장")
    else:
        results = analyze_portfolio()
        print_consensus(results, verbose=args.verbose)
        saved = save_to_recommendations(results)
        if saved:
            logger.info(f"recommendations 테이블에 {saved}건 저장 (frontend /decision 활성화)")

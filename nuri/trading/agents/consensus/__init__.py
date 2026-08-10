"""
멀티 에이전트 합의 엔진 — SIEGE Swarm Intelligence 패턴.

10개 전문 에이전트의 독립 판정을 가중 투표로 합산.
에이전트별 가중치는 과거 적중률(Learning Memory)에서 동적 계산.
의견 불일치는 명시적으로 기록하여 감사 가능.

사용법:
    python -m nuri.trading.agents.consensus
    python -m nuri.trading.agents.consensus --ticker TSLA

Package layout (P2.1 split, codex Round 1 — 2026-05-01):
    models       — ConsensusResult, AgentEligibility (data shapes)
    registry     — DEFAULT_WEIGHTS, build_all_agents()
    learning_memory — _compute_horizon_eligibility, compute_canonical_weights,
                      compute_provisional_weights, select_weight_source
    scoring      — _build_consensus (pure scoring kernel)
    events       — _emit_penalty_event_if_fired (audit trail)
    persistence  — save_to_recommendations (DB upsert)
    presentation — print_consensus (CLI output)
    __main__     — CLI entry point

This file is the compatibility facade. orchestration functions (analyze_ticker,
stream_analyze_ticker, _compute_weights, agent_readiness, analyze_portfolio) are
DEFINED HERE so monkeypatch.setattr(consensus, "ALL_AGENTS", ...) works — they
read the package-level globals.
"""

from __future__ import annotations

import logging

from nuri.core.agent_config import AGENT_CONFIG
from nuri.core.db import get_tickers
from nuri.trading.agents.base import AgentVerdict

from .events import _emit_penalty_event_if_fired
from .learning_memory import (
    _compute_horizon_eligibility,
    compute_canonical_weights,
    compute_provisional_weights,
    select_weight_source,
)
from .models import AgentEligibility, ConsensusResult
from .persistence import save_to_recommendations
from .presentation import print_consensus
from .registry import DEFAULT_WEIGHTS, build_all_agents
from .scoring import _build_consensus

logger = logging.getLogger(__name__)

# Package-root mutable binding for tests that patch ALL_AGENTS.
# (do not move into registry.py — monkeypatch.setattr(consensus, "ALL_AGENTS", ...) 가 동작하려면 root 에 있어야 함.)
ALL_AGENTS = build_all_agents()

__all__ = [
    "AgentVerdict",
    "AgentEligibility",
    "ALL_AGENTS",
    "ConsensusResult",
    "DEFAULT_WEIGHTS",
    "_build_consensus",
    "_compute_horizon_eligibility",
    "_compute_weights",
    "_emit_penalty_event_if_fired",
    "agent_readiness",
    "analyze_portfolio",
    "analyze_ticker",
    "compute_canonical_weights",
    "compute_provisional_weights",
    "print_consensus",
    "save_to_recommendations",
    "select_weight_source",
    "stream_analyze_ticker",
]


def _compute_weights(db_path=None) -> dict[str, float]:
    """Legacy entry — backward compat. mainline (analyze_ticker / stream_analyze_ticker) 만 사용.

    #468 codex Round 1: 내부적으로 select_weight_source 위임. veto/amplifier 절대
    이 함수 직접 호출 금지 — `compute_canonical_weights` 만 사용 (structural separation).

    TODO(#178): decisions 테이블 기반 compute_agent_accuracy() 가 30건 이상 완료되면
    recommendations 대신 decisions 를 primary source 로 전환.
    See: nuri.trading.engine.decisions.compute_agent_accuracy()
    """
    canonical = compute_canonical_weights(db_path=db_path)
    provisional = compute_provisional_weights(db_path=db_path)
    weights, sources = select_weight_source(canonical, provisional)

    # provisional 발동 또는 structurally_unsaturating 시만 INFO surface
    # (조작자에게 low-confidence warm-start 또는 영구 default 상태 알림).
    # Pure canonical-only success 는 DEBUG (기존 _compute_weights normal path 와 동일 톤).
    prov_agents = [n for n, s in sources.items() if s == "provisional_21d"]
    unsaturating = [n for n, s in sources.items() if s == "structurally_unsaturating"]
    canon_agents = [n for n, s in sources.items() if s == "canonical_30d"]
    if prov_agents or unsaturating:
        logger.info(
            "_compute_weights per-agent source: canonical_30d=%s provisional_21d=%s structurally_unsaturating=%s",
            canon_agents,
            prov_agents,
            unsaturating,
        )
    elif canon_agents:
        logger.debug("_compute_weights per-agent: all canonical_30d eligible (n=%d)", len(canon_agents))

    return weights


def agent_readiness(db_path=None) -> dict:
    """Per-agent readiness snapshot for /api/learning-memory/readiness.

    #468 codex Round 1 #6/#7 — API 응답 형태 per-agent (global label 금지).
    structurally_unsaturating 표시 (HOLD-only emit pattern).
    """
    canonical = compute_canonical_weights(db_path=db_path)
    provisional = compute_provisional_weights(db_path=db_path)
    final_weights, sources = select_weight_source(canonical, provisional)

    agents = []
    for name in DEFAULT_WEIGHTS:
        c = canonical.get(name)
        p = provisional.get(name)
        agents.append(
            {
                "name": name,
                "default_weight": DEFAULT_WEIGHTS[name],
                "final_weight": round(final_weights[name], 4),
                "source": sources[name],
                "canonical_30d": {
                    "sample_count": c.sample_count if c else 0,
                    "eligible": c.eligible if c else False,
                    "weight": round(c.weight, 4) if c else DEFAULT_WEIGHTS[name],
                },
                "provisional_21d": {
                    "sample_count": p.sample_count if p else 0,
                    "eligible": p.eligible if p else False,
                    "weight": round(p.weight, 4) if p else DEFAULT_WEIGHTS[name],
                },
            }
        )
    return {
        "agents": agents,
        "summary": {
            "canonical_30d": sum(1 for s in sources.values() if s == "canonical_30d"),
            "provisional_21d": sum(1 for s in sources.values() if s == "provisional_21d"),
            "default": sum(1 for s in sources.values() if s == "default"),
            "structurally_unsaturating": sum(1 for s in sources.values() if s == "structurally_unsaturating"),
        },
    }


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
            return AgentVerdict(agent.name, ticker, "HOLD", 0, f"에러: {e}", degraded=True)

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
                    verdicts.append(AgentVerdict(agent.name, ticker, "HOLD", 0, f"에러: {e}", degraded=True))
        except concurrent.futures.TimeoutError:
            # 전체 batch timeout — 미완료 future는 폴백 verdict로
            for future, agent in futures.items():
                if future not in completed:
                    verdicts.append(AgentVerdict(agent.name, ticker, "HOLD", 0, "타임아웃", degraded=True))
    finally:
        # cancel_futures: 큐에 대기중인(아직 시작 안 한) future 취소
        # wait=False: 실행 중인 future가 끝날 때까지 기다리지 않음
        executor.shutdown(wait=False, cancel_futures=True)

    result = _build_consensus(ticker, verdicts, weights)
    _emit_penalty_event_if_fired(result, verdicts, db_path=db_path)
    return result


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
            return AgentVerdict(agent.name, ticker, "HOLD", 0, f"에러: {e}", degraded=True)

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
                    verdict = AgentVerdict(agent.name, ticker, "HOLD", 0, f"에러: {e}", degraded=True)
                verdicts.append(verdict)
                yield ("verdict", verdict)
        except concurrent.futures.TimeoutError:
            for future, agent in futures.items():
                if future not in completed:
                    verdict = AgentVerdict(agent.name, ticker, "HOLD", 0, "타임아웃", degraded=True)
                    verdicts.append(verdict)
                    yield ("verdict", verdict)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    result = _build_consensus(ticker, verdicts, weights)
    _emit_penalty_event_if_fired(result, verdicts, db_path=db_path)
    yield ("consensus", result)


def analyze_portfolio(db_path=None) -> list[ConsensusResult]:
    """전 보유종목에 대해 멀티 에이전트 합의."""
    tickers = get_tickers(db_path=db_path)
    results = []
    for ticker in tickers:
        result = analyze_ticker(ticker, db_path)
        results.append(result)
        logger.info(
            f"{ticker}: {result.final_action} (conf={result.final_confidence:.0f}, agree={result.agreement_rate:.0%})"
        )
    return results

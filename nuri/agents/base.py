"""15-actor base class — Layer A/B/C separation enforced (#529 Phase 1).

Codex Round 5 핵심 결정:
- 모든 actor 는 1개 primary layer 에 소속 (A/B/C)
- Layer A 결정은 LLM 호출 절대 X (enforcement path)
- Layer C narrative 는 모든 actor 가 optional 보유 (interpretation enrichment)
- 모든 invocation 은 audit_ledger + run_ledger 에 자동 기록

설계 원칙:
- Actor.run() = 동기 lifecycle (start_run → execute → finish_run)
- Actor.execute() = subclass 구현 의무. ActorResult 반환
- ActorResult.outcome = enforcement 결정 (Layer A 시 필수)
- LLM 호출 실패 시 Layer A/B 결정은 그대로 진행 (graceful degradation)
"""

from __future__ import annotations

import hashlib
import json
import platform
import socket
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, TypeVar

from nuri.core.db import (
    finish_agent_run,
    log_agent_audit,
    start_agent_run,
)


class Layer(str, Enum):
    """Actor 의 primary layer (Round 5 codex consult)."""

    A = "A"  # Enforcement — pure rule, ZERO LLM
    B = "B"  # Computation — statistical, deterministic
    C = "C"  # Interpretation — LLM essential, async enrichment only


class Outcome(str, Enum):
    """Layer A enforcement 결정 (사용 시 필수)."""

    PASS = "pass"
    BLOCK = "block"
    WARN = "warn"
    ERROR = "error"


@dataclass
class RunContext:
    """Actor invocation context — causation chain 추적용.

    parent_run_id 로 cross-actor chain 구성:
        Decision-Compiler (parent) → Execution-Firewall (child) → emit (grandchild)
    """

    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_run_id: Optional[str] = None
    machine: str = field(default_factory=lambda: f"{socket.gethostname()}/{platform.machine()}")


@dataclass
class ActorResult:
    """Actor.execute() 반환 타입 — audit 에 기록될 모든 필드.

    Layer A: outcome 필수 (pass/block/warn/error).
    Layer B: outcome optional (계산 성공 = pass).
    Layer C: outcome 보통 None (해석은 차단/허용 결정 X).
    """

    output: dict[str, Any]
    outcome: Optional[Outcome] = None
    sample_n: Optional[int] = None
    input_summary: Optional[str] = None
    llm_narrative: Optional[str] = None


class Actor(ABC):
    """15-actor base class — primary layer + audit/run lifecycle 자동화.

    Subclass 구현 의무:
        name: ClassVar[str]               — actor 고유 이름 (DB key)
        version: ClassVar[str]            — semver, audit 에 기록
        layer: ClassVar[Layer]            — primary layer (A/B/C)
        execute(input, ctx) -> ActorResult — 핵심 로직 (audit 자동)

    Subclass 사용 패턴:
        result = MyActor().run(input_dict)
        # → start_agent_run → execute → finish_agent_run
        # → log_agent_audit (input_hash + output + outcome 자동 기록)
    """

    name: str = ""
    version: str = "0.0.0"
    layer: Layer = Layer.B

    def __init__(self) -> None:
        if not self.name:
            raise ValueError(f"{type(self).__name__}.name must be set (DB key)")
        if self.layer not in Layer:
            raise ValueError(f"{type(self).__name__}.layer must be Layer.A/B/C")
        # Layer A 는 LLM 의존 절대 금지 — subclass 가 _llm_companion 정의 시 fail-fast.
        if self.layer == Layer.A and getattr(self, "_uses_llm", False):
            raise RuntimeError(
                f"{type(self).__name__}: Layer A actor cannot use LLM "
                "(Codex Round 5 mandatory). Move LLM narrative to Layer C companion."
            )

    @abstractmethod
    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        """Subclass 의무 구현. ActorResult 반환.

        Layer A: outcome 필수 (pass/block).
        예외 raise 가능 — base.run() 이 'failed' 상태로 finish 처리.
        """

    def run(
        self,
        input_data: dict[str, Any],
        parent_run_id: Optional[str] = None,
        decision_id: Optional[str] = None,
    ) -> ActorResult:
        """Lifecycle wrapper — start_run → execute → finish_run + audit log.

        decision_id 미제공 시 run_id 사용 (단일 actor 의사결정).
        cross-actor decision 일 경우 호출자가 decision_id 전달.
        """
        ctx = RunContext(parent_run_id=parent_run_id)
        decision_id = decision_id or ctx.run_id
        input_hash = self._hash_input(input_data)
        start_ms = time.monotonic()

        start_agent_run(
            run_id=ctx.run_id,
            actor_name=self.name,
            parent_run_id=parent_run_id,
            machine=ctx.machine,
        )

        try:
            result = self.execute(input_data, ctx)
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_ms) * 1000)
            finish_agent_run(
                run_id=ctx.run_id,
                status="failed",
                duration_ms=duration_ms,
                error_message=str(exc)[:500],
            )
            log_agent_audit(
                decision_id=decision_id,
                actor_name=self.name,
                actor_version=self.version,
                layer=self.layer.value,
                input_hash=input_hash,
                output=json.dumps({"error": str(exc)[:500]}),
                outcome=Outcome.ERROR.value,
                duration_ms=duration_ms,
                run_id=ctx.run_id,
            )
            raise

        duration_ms = int((time.monotonic() - start_ms) * 1000)
        # Layer A 강제: outcome 필수
        if self.layer == Layer.A and result.outcome is None:
            finish_agent_run(
                run_id=ctx.run_id,
                status="failed",
                duration_ms=duration_ms,
                error_message="Layer A actor returned no outcome",
            )
            raise ValueError(f"{self.name}: Layer A actor must return outcome (Codex Round 5 enforcement requirement)")

        finish_agent_run(
            run_id=ctx.run_id,
            status="finished",
            duration_ms=duration_ms,
        )
        log_agent_audit(
            decision_id=decision_id,
            actor_name=self.name,
            actor_version=self.version,
            layer=self.layer.value,
            input_hash=input_hash,
            input_summary=result.input_summary,
            output=json.dumps(result.output, default=str),
            sample_n=result.sample_n,
            duration_ms=duration_ms,
            outcome=result.outcome.value if result.outcome else None,
            llm_narrative=result.llm_narrative,
            run_id=ctx.run_id,
        )
        return result

    @staticmethod
    def _hash_input(input_data: dict[str, Any]) -> str:
        """Stable hash — sort_keys 로 dict 순서 무관."""
        payload = json.dumps(input_data, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


_ActorT = TypeVar("_ActorT", bound=Actor)


class ActorRegistry:
    """15-actor 인벤토리 — name → class 매핑 + 검증.

    Phase 1 에서는 base 만 제공. Phase 2 부터 actor 별 등록.
    canonical 15-actor 목록 (Round 5 codex):
        1. Collector-Orchestrator
        2. Freshness-Gatekeeper
        3. Regime-Posterior
        4. Hypothesis-Registry
        5. WalkForward-Validator
        6. Causal-Factor-Auditor
        7. Foundation-Benchmark
        8. Decision-Compiler
        9. Execution-Firewall
        10. Audit-Ledger
        11. Forward-Outcome-Tracker
        12. Drift-Sentinel
        13. Release-Rollback-Manager
        14. SRE-Incident-Agent
        15. State-Replicator-DR
    """

    # 2026-08-21 (#975) 로스터를 현실로 축소: 15종 광고 중 실제 호출자가 있는 것은
    # 8종뿐이었다 (scheduler 4 + sleeve/rules 2 + phase2 수동 체인 2+). 호출자 없는
    # 7종은 DORMANT 로 강등 — 코드·테스트는 보존하고 광고만 철회한다 ("wired ≠
    # validated"). 승격 조건: 실제 호출 경로가 생기는 PR 에서 CANONICAL 로 이동.
    CANONICAL_ACTORS: tuple[str, ...] = (
        "collector-orchestrator",
        "regime-posterior",
        "hypothesis-registry",
        "causal-factor-auditor",
        "decision-compiler",
        "execution-firewall",
        "forward-outcome-tracker",
        "sre-incident-agent",
    )
    #: 구현·테스트는 있으나 어떤 경로도 부르지 않는 휴면 액터. 등록은 허용하되
    #: `missing()` 추적에서 제외 — "미배선을 pending 으로 광고" 하지 않기 위해.
    DORMANT_ACTORS: tuple[str, ...] = (
        "freshness-gatekeeper",
        "walkforward-validator",
        "foundation-benchmark",
        "audit-ledger",
        "drift-sentinel",
        "release-rollback-manager",
        "state-replicator-dr",
    )
    # 하위 호환 별칭 — 외부 참조가 있을 수 있어 한 릴리즈 유지 (전체 = canonical + dormant)
    CANONICAL_15: tuple[str, ...] = CANONICAL_ACTORS + DORMANT_ACTORS

    def __init__(self) -> None:
        self._registry: dict[str, type[Actor]] = {}

    def register(self, actor_cls: "type[_ActorT]") -> "type[_ActorT]":
        """Decorator-friendly 등록. canonical 15 중 하나여야 함.

        Idempotent — 같은 module:qualname 재등록 OK (`python -m` re-import 패턴 —
        Python 이 같은 module 을 `__main__` 로 한 번 더 로드해 class identity 가 달라짐).
        다른 module/qualname 으로 같은 name 등록 시 ValueError.

        TypeVar로 반환 타입을 입력 subclass 로 보존 — Pylance 가 클래스 변수
        (VALID_ACTIONS 등) 접근을 정확히 추론하도록.
        """
        if actor_cls.name not in self.CANONICAL_ACTORS + self.DORMANT_ACTORS:
            raise ValueError(
                f"{actor_cls.__name__}.name={actor_cls.name!r} not in the actor roster. "
                f"Allowed: {self.CANONICAL_ACTORS + self.DORMANT_ACTORS}"
            )
        existing = self._registry.get(actor_cls.name)
        if existing is not None and (existing.__qualname__, getattr(existing, "name", None)) != (
            actor_cls.__qualname__,
            actor_cls.name,
        ):
            raise ValueError(
                f"actor {actor_cls.name!r} already registered as {existing.__module__}.{existing.__qualname__}, refusing to overwrite with {actor_cls.__module__}.{actor_cls.__qualname__}"
            )
        self._registry[actor_cls.name] = actor_cls
        return actor_cls

    def get(self, name: str) -> Optional[type[Actor]]:
        return self._registry.get(name)

    def all(self) -> dict[str, type[Actor]]:
        return dict(self._registry)

    def missing(self) -> list[str]:
        """canonical 중 미등록 actor 목록 — dormant 는 제외 (미배선은 pending 이 아니다)."""
        return [n for n in self.CANONICAL_ACTORS if n not in self._registry]


# Module-level singleton
REGISTRY = ActorRegistry()

"""Mixed-sample evidence 바인딩 규칙 (#1305) — 승격 근거의 필수 게이트.

바인딩(#1305 `code_rev` / `execution_config_sha_v1`) 있는 행과 없는 행이 **섞인**
표본으로 계산한 primary metric 은 무조건 not-measurable — 승격(§2.6 ladder
promotion) 근거로 쓸 수 없다. "바인딩 있는 행만 필터"는 호출자 재량처럼 보이지만
과거 패배 증거를 떨어뜨리는 내장 편향 경로다 (Codex challenge P1) — 그래서 이
판정은 호출자 선택이 아니라 여기서 강제한다. #1307 champion-challenger 게이트가
이 모듈을 소비한다.
"""

from __future__ import annotations

from collections.abc import Iterable

BOUND = "bound"
UNBOUND = "unbound"
MIXED = "mixed"


class MixedEvidenceBindingError(ValueError):
    """바인딩 유무가 섞인 표본으로 primary metric 을 계산하려 했다.

    복구는 필터가 아니라 재실험이다 — 표본 전체를 같은 코드·설정에서 재산출하거나,
    미귀속 행을 프로덕션 DB 에서 판정(재실행 후 저장/삭제)한 뒤 다시 계산한다.
    """


def binding_status(bindings: Iterable[str | None]) -> str:
    """표본의 바인딩 값 목록 → BOUND / UNBOUND / MIXED.

    bindings: 행별 바인딩 값 (`code_rev` 또는 `execution_config_sha_v1` 컬럼).
    None = 미귀속(#1305 이전 행). 빈 표본은 UNBOUND — 바인딩된 행이 하나도 없다는
    사실 서술이고, 표본 크기 검정은 이 모듈 소관이 아니다.
    """
    has_bound = False
    has_unbound = False
    for value in bindings:
        if value is None:
            has_unbound = True
        else:
            has_bound = True
        if has_bound and has_unbound:
            return MIXED
    return BOUND if has_bound else UNBOUND


def require_measurable(bindings: Iterable[str | None], context: str = "") -> str:
    """primary metric 계산 전 필수 호출 — MIXED 면 예외, 아니면 status 반환.

    UNBOUND 는 통과시킨다: 전-#1305 히스토리만으로 구성된 표본은 균질해서 행 간
    비교가 성립한다 (단, #1307 승격 게이트는 BOUND 를 별도로 요구한다 — 그 검사는
    게이트 소관). 막는 것은 오직 **혼합**이다.
    """
    status = binding_status(bindings)
    if status == MIXED:
        suffix = f" ({context})" if context else ""
        raise MixedEvidenceBindingError(
            f"바인딩 유무가 섞인 표본{suffix} — primary metric 은 not-measurable. "
            "바인딩된 행만 필터해 재시도하지 말 것: 그게 이 규칙이 막는 편향이다."
        )
    return status
